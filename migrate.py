"""
migrate.py — Pindahkan file dari folder lokal ke Google Drive Desktop (24 jam).

Sederhana, satu file, stdlib-only (tanpa dependency). Tahan network error.

Contoh pakai:
    python migrate.py                      # awasi dummy -> G:\\My Drive\\dummy, 24/7 (default)
    python migrate.py --duration 24        # hanya 24 jam lalu berhenti
    python migrate.py --interval 30        # cek tiap 30 detik
    python migrate.py --src "D:/data" --dst "G:/My Drive/backup"
    python migrate.py --once               # sekali jalan lalu keluar
    python migrate.py --dry-run            # hanya tampilkan, tidak copy/hapus

Cara kerja tiap putaran:
    1. Scan semua file di SRC.
    2. Untuk tiap file: copy ke DST, verifikasi hash, lalu hapus file lokal.
    3. Kalau nama sudah ada di DST -> simpan sebagai "nama (1).ext" (tidak menimpa).
    4. Folder kosong TIDAK menghentikan script; file baru yang muncul langsung dipindah.
    5. Jalan terus 24/7 (default). Pakai --duration N untuk berhenti otomatis, atau Ctrl+C.

Ketahanan (penting untuk 24 jam):
    - Network error / Drive terputus TIDAK mematikan script.
    - Setiap file dicoba ulang beberapa kali dengan jeda sebelum menyerah.
    - Kalau 1 file gagal, file lain tetap diproses.
    - File lokal TIDAK pernah dihapus kalau copy belum terverifikasi.
    - Drive yang hilang dideteksi & ditunggu sampai kembali (dengan backoff).

Semua aktivitas juga ditulis ke migrate.log di folder script ini.
"""

import argparse
import hashlib
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# ====== SETTING DEFAULT (bisa dioverride lewat argumen) ======
DEFAULT_SRC = r"C:\Users\USER\Desktop\PROJECT\gdrive-desktop\dummy"
DEFAULT_DST = r"G:\My Drive\dummy"
DEFAULT_INTERVAL = 60     # detik antar pengecekan
DEFAULT_DURATION_H = 0    # jam; 0 = 24/7 tanpa batas (DEFAULT). Isi angka utk batas waktu.

# ====== SETTING KETAHANAN NETWORK ERROR ======
FILE_RETRIES = 3          # percobaan per file sebelum menyerah (dicoba lagi putaran berikutnya)
FILE_RETRY_DELAY = 3      # jeda antar percobaan (detik), naik 2x tiap gagal
DRIVE_MAX_BACKOFF = 300   # batas maksimal jeda saat Drive lama tidak siap (detik)

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_FILE = SCRIPT_DIR / "migrate.log"
HEARTBEAT_FILE = SCRIPT_DIR / "migrate.heartbeat"
LOCK_FILE = SCRIPT_DIR / "migrate.lock"


class AlreadyRunning(Exception):
    """Dilempar kalau instance lain sedang berjalan."""


class SingleInstance:
    """Lock sederhana agar hanya satu migrasi berjalan (cegah race/duplikat)."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self) -> None:
        self._fh = open(self.path, "a+")
        try:
            if sys.platform == "win32":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self._fh.close()
            self._fh = None
            raise AlreadyRunning(str(e)) from e
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(f"pid={os.getpid()}\n")
        self._fh.flush()

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                self._fh.close()
            finally:
                self._fh = None


def log(msg: str) -> None:
    """Tulis ke layar + file log. Tidak pernah melempar exception."""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except OSError:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


def safe_exists(path: Path) -> bool:
    """Path.exists() yang tidak melempar exception (Drive bisa terputus)."""
    try:
        return path.exists()
    except OSError:
        return False


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_unlink(path: Path) -> bool:
    """Hapus file, jangan sampai melempar exception."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def unique_target(dst_dir: Path, name: str) -> Path:
    """Kalau nama sudah ada, kembalikan 'nama (1).ext', 'nama (2).ext', dst."""
    target = dst_dir / name
    if not safe_exists(target):
        return target
    stem, ext = Path(name).stem, Path(name).suffix
    i = 1
    while i <= 100000:
        target = dst_dir / f"{stem} ({i}){ext}"
        if not safe_exists(target):
            return target
        i += 1
    raise OSError(f"Tidak bisa menemukan nama unik untuk {name}")


def migrate_file(src_file: Path, dst_dir: Path, dry_run: bool) -> bool:
    """Copy + verifikasi + hapus satu file.

    Return True kalau sukses. Return False kalau gagal — file lokal
    DIPERTAHANKAN dan akan dicoba lagi putaran berikutnya.
    Fungsi ini TIDAK PERNAH melempar exception (tahan network error).
    """
    name = src_file.name
    try:
        size = src_file.stat().st_size
    except OSError as e:
        log(f"[GAGAL] Tidak bisa baca {name}: {e}")
        return False

    # Tentukan nama tujuan (bisa gagal kalau Drive terputus).
    try:
        target = unique_target(dst_dir, name)
    except OSError as e:
        log(f"[GAGAL] Drive tidak bisa diakses saat cek nama {name}: {e}")
        return False

    if dry_run:
        log(f"[DRY] {name} ({human(size)}) -> {target.name}")
        return True

    # Coba beberapa kali untuk mengatasi network error yang sifatnya sementara.
    delay = FILE_RETRY_DELAY
    for attempt in range(1, FILE_RETRIES + 1):
        tmp = dst_dir / f".{name}.tmp-{os.getpid()}"
        try:
            # 1. Copy ke nama sementara.
            shutil.copy2(src_file, tmp)

            # 2. Verifikasi hash (baca ulang dari Drive).
            if sha256(src_file) != sha256(tmp):
                safe_unlink(tmp)
                log(f"[GAGAL] Verifikasi hash tidak cocok: {name} (percobaan {attempt}/{FILE_RETRIES})")
                if attempt < FILE_RETRIES:
                    time.sleep(delay)
                    delay *= 2
                continue

            # 3. Rename ke nama final (atomic).
            tmp.replace(target)

            # 4. Hapus lokal HANYA setelah copy terverifikasi.
            if safe_unlink(src_file):
                log(f"[OK] {name} ({human(size)}) -> {target.name}")
            else:
                log(f"[OK] {name} -> {target.name} (Drive aman; file lokal gagal dihapus, "
                    f"akan dirapikan putaran berikutnya)")
            return True

        except OSError as e:
            # Termasuk network error / Drive terputus. Bersihkan sisa & coba lagi.
            safe_unlink(tmp)
            if attempt < FILE_RETRIES:
                log(f"[RETRY] {name} gagal (percobaan {attempt}/{FILE_RETRIES}): {e} "
                    f"— coba lagi dalam {delay}s")
                time.sleep(delay)
                delay *= 2
            else:
                log(f"[GAGAL] {name} setelah {FILE_RETRIES} percobaan: {e} "
                    f"(file lokal DIPERTAHANKAN, dicoba putaran berikutnya)")

    return False


def scan_files(src: Path) -> list[Path]:
    """Daftar file di SRC (level teratas, lewati file tersembunyi). Tahan error."""
    try:
        return sorted(f for f in src.iterdir() if f.is_file() and not f.name.startswith("."))
    except OSError as e:
        log(f"[WARN] Tidak bisa scan folder lokal {src}: {e}")
        return []


def run_once(src: Path, dst: Path, dry_run: bool) -> tuple[int, int]:
    """Scan SRC, migrasi semua file. Return (jumlah_sukses, sisa_file).

    Tahan error: kegagalan 1 file tidak menghentikan file lain.
    """
    files = scan_files(src)
    if not files:
        return 0, 0

    if not dry_run:
        try:
            dst.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log(f"[WARN] Drive tidak siap ({dst}): {e}")
            return 0, len(files)

    ok = 0
    for f in files:
        try:
            if migrate_file(f, dst, dry_run):
                ok += 1
        except Exception as e:  # noqa: BLE001 - jangan biarkan 1 file mematikan loop
            log(f"[GAGAL] Error tak terduga pada {f.name}: {e}")

    sisa = len(scan_files(src))
    return ok, sisa


def main() -> int:
    ap = argparse.ArgumentParser(description="Pindahkan file lokal ke Google Drive Desktop (24 jam).")
    ap.add_argument("--src", default=DEFAULT_SRC, help="Folder lokal sumber")
    ap.add_argument("--dst", default=DEFAULT_DST, help="Folder tujuan di Drive")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Interval cek (detik)")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION_H,
                    help="Lama jalan (jam). 0 = 24/7 tanpa batas (default).")
    ap.add_argument("--once", action="store_true", help="Jalankan sekali lalu keluar")
    ap.add_argument("--dry-run", action="store_true", help="Tampilkan saja, tidak copy/hapus")
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    interval = max(1, args.interval)

    if not safe_exists(src):
        log(f"[ERROR] Folder lokal tidak ada: {src}")
        return 1

    # Cegah dua instance berjalan bersamaan (race -> bisa duplikat/hilang).
    lock = SingleInstance(LOCK_FILE)
    try:
        lock.acquire()
    except AlreadyRunning:
        log(f"[ERROR] Sudah ada migrasi berjalan (lock: {LOCK_FILE}). Keluar.")
        print("[ERROR] Sudah ada migrasi berjalan. Hentikan yang lama dulu.", file=sys.stderr)
        return 3

    try:
        return _run(args, src, dst, interval)
    finally:
        lock.release()


def _run(args, src: Path, dst: Path, interval: int) -> int:
    dur_text = "tanpa batas" if args.duration <= 0 else f"{args.duration:g} jam"
    log("=" * 64)
    log(f"Lokal    : {src}")
    log(f"Drive    : {dst}")
    log(f"Interval : {interval}s | Durasi: {dur_text}")
    log(f"Mode     : {'DRY-RUN' if args.dry_run else 'AKTIF'}{' | sekali' if args.once else ''}")
    log(f"Log      : {LOG_FILE}")
    log("=" * 64)

    start = time.monotonic()
    deadline = None if args.duration <= 0 else start + args.duration * 3600
    total_ok = 0
    drive_down_since = None
    backoff = interval

    while True:
        # -- Cek Drive siap SEBELUM menyentuh file apa pun (jangan hapus kalau Drive mati).
        drive_ok = True
        if not args.dry_run:
            try:
                dst.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                drive_ok = False
                if drive_down_since is None:
                    drive_down_since = time.monotonic()
                    log(f"[WARN] Drive tidak siap ({dst}): {e} — tunggu sampai tersedia")

        if drive_ok:
            if drive_down_since is not None:
                down_for = time.monotonic() - drive_down_since
                log(f"[INFO] Drive siap kembali (setelah {down_for:.0f}s).")
                drive_down_since = None
                backoff = interval

            try:
                ok, sisa = run_once(src, dst, args.dry_run)
                total_ok += ok
                if ok or sisa:
                    log(f"Putaran: {ok} dimigrasi, {sisa} file tersisa di lokal.")
            except Exception as e:  # noqa: BLE001 - satu putaran gagal jangan matikan loop
                log(f"[ERROR] Putaran gagal (akan dicoba lagi): {e}")

        # -- Tulis heartbeat (untuk cek 'masih hidup?').
        try:
            HEARTBEAT_FILE.write_text(
                f"{datetime.now():%Y-%m-%d %H:%M:%S} | uptime {time.monotonic()-start:.0f}s "
                f"| total {total_ok}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

        # -- Keluar kalau sekali jalan, atau durasi habis.
        if args.once:
            log(f"Selesai (sekali jalan). {total_ok} file dimigrasi.")
            return 0
        if deadline is not None and time.monotonic() >= deadline:
            log(f"Durasi {dur_text} selesai. Total {total_ok} file dimigrasi.")
            return 0

        # -- Tidur. Kalau Drive mati, jeda bertambah (backoff) sampai batas tertentu.
        if drive_down_since is not None:
            wait = min(backoff, DRIVE_MAX_BACKOFF)
            backoff = min(backoff * 2, DRIVE_MAX_BACKOFF)
        else:
            wait = interval
        time.sleep(wait)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Dihentikan oleh user.")
        sys.exit(130)

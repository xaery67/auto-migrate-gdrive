"""
migrate.py — Pindahkan file dari folder lokal ke Google Drive Desktop (24 jam).

Sederhana, satu file, stdlib-only (tanpa dependency).

Contoh pakai:
    python migrate.py                      # awasi dummy -> G:\\My Drive\\dummy selama 24 jam
    python migrate.py --duration 0         # jalan terus tanpa batas waktu
    python migrate.py --interval 30        # cek tiap 30 detik
    python migrate.py --src "D:/data" --dst "G:/My Drive/backup"
    python migrate.py --once               # sekali jalan lalu keluar
    python migrate.py --dry-run            # hanya tampilkan, tidak copy/hapus

Cara kerja tiap putaran:
    1. Scan semua file di SRC.
    2. Untuk tiap file: copy ke DST, verifikasi hash, lalu hapus file lokal.
    3. Kalau nama sudah ada di DST -> simpan sebagai "nama (1).ext" (tidak menimpa).
    4. Folder kosong TIDAK menghentikan script; file baru yang muncul langsung dipindah.
    5. Berhenti setelah DURATION jam (default 24), atau Ctrl+C.

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
DEFAULT_DURATION_H = 24   # jam; 0 = tanpa batas (jalan terus)

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
    """Tulis ke layar + file log."""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique_target(dst_dir: Path, name: str) -> Path:
    """Kalau nama sudah ada, kembalikan 'nama (1).ext', 'nama (2).ext', dst."""
    target = dst_dir / name
    if not target.exists():
        return target
    stem, ext = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        target = dst_dir / f"{stem} ({i}){ext}"
        if not target.exists():
            return target
        i += 1


def migrate_file(src_file: Path, dst_dir: Path, dry_run: bool) -> bool:
    """Copy + verifikasi + hapus satu file. Return True kalau sukses."""
    target = unique_target(dst_dir, src_file.name)
    size = src_file.stat().st_size

    if dry_run:
        log(f"[DRY] {src_file.name} ({human(size)}) -> {target.name}")
        return True

    # 1. Copy ke nama sementara, verifikasi hash, baru rename ke nama final.
    tmp = dst_dir / f".{src_file.name}.tmp-{os.getpid()}"
    try:
        shutil.copy2(src_file, tmp)
        if sha256(src_file) != sha256(tmp):
            log(f"[GAGAL] Verifikasi hash tidak cocok: {src_file.name}")
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(target)
    except OSError as e:
        log(f"[GAGAL] Copy {src_file.name}: {e}")
        tmp.unlink(missing_ok=True)
        return False

    # 2. Hapus file lokal hanya setelah copy terverifikasi.
    try:
        src_file.unlink()
    except OSError as e:
        log(f"[GAGAL] Tidak bisa hapus lokal {src_file.name}: {e} (file Drive sudah aman)")
        return True  # copy sudah sukses; lokal gagal hapus dicoba lagi putaran berikutnya

    log(f"[OK] {src_file.name} ({human(size)}) -> {target.name}")
    return True


def run_once(src: Path, dst: Path, dry_run: bool) -> tuple[int, int]:
    """Scan SRC, migrasi semua file. Return (jumlah_sukses, sisa_file)."""
    files = [f for f in sorted(src.iterdir()) if f.is_file() and not f.name.startswith(".")]
    if not files:
        return 0, 0

    if not dst.exists() and not dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    ok = 0
    for f in files:
        if migrate_file(f, dst, dry_run):
            ok += 1

    sisa = len([f for f in src.iterdir() if f.is_file()])
    return ok, sisa


def main() -> int:
    ap = argparse.ArgumentParser(description="Pindahkan file lokal ke Google Drive Desktop (24 jam).")
    ap.add_argument("--src", default=DEFAULT_SRC, help="Folder lokal sumber")
    ap.add_argument("--dst", default=DEFAULT_DST, help="Folder tujuan di Drive")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Interval cek (detik)")
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION_H,
                    help="Lama jalan (jam). 0 = tanpa batas. Default 24.")
    ap.add_argument("--once", action="store_true", help="Jalankan sekali lalu keluar")
    ap.add_argument("--dry-run", action="store_true", help="Tampilkan saja, tidak copy/hapus")
    args = ap.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    interval = max(1, args.interval)

    if not src.exists():
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
    drive_was_down = False

    while True:
        # -- Cek Drive siap SEBELUM menyentuh file apa pun.
        drive_ok = dst.exists()
        if not drive_ok and not args.dry_run:
            try:
                dst.mkdir(parents=True, exist_ok=True)
                drive_ok = True
            except OSError as e:
                if not drive_was_down:
                    log(f"[WARN] Drive tidak siap ({dst}): {e} — tunggu sampai tersedia")
                    drive_was_down = True

        if drive_ok:
            if drive_was_down:
                log("[INFO] Drive siap kembali.")
                drive_was_down = False

            ok, sisa = run_once(src, dst, args.dry_run)
            total_ok += ok
            if ok or sisa:
                log(f"Putaran: {ok} dimigrasi, {sisa} file tersisa di lokal.")

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

        time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Dihentikan oleh user.")
        sys.exit(130)

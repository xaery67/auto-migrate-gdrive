# Auto-Migrate Lokal → Google Drive Desktop

Script Python sederhana untuk **memindahkan file** dari sebuah folder lokal ke folder di
**Google Drive Desktop** secara otomatis. File lokal dihapus setelah salinan di Drive terverifikasi,
dan script mengawasi folder tersebut terus-menerus (**24/7**, jalan tanpa batas).

- **Satu file, tanpa dependency** — cukup Python 3.11+ (stdlib saja).
- **Anti nama double** — kalau nama sudah ada di Drive, otomatis jadi `nama (1).ext`.
- **Aman** — file lokal hanya dihapus setelah copy diverifikasi dengan SHA-256.
- **Tahan network error** — Drive terputus tidak mematikan script; file dicoba ulang otomatis.
- **Interval & folder bisa diset** — lewat argumen, tanpa edit kode.

---

## Daftar Isi
- [Kebutuhan](#kebutuhan)
- [Cara Pakai Cepat](#cara-pakai-cepat)
- [Cara Kerja](#cara-kerja)
- [Ketahanan saat Network Error](#ketahanan-saat-network-error)
- [Opsi Command-Line](#opsi-command-line)
- [Konfigurasi Default](#konfigurasi-default)
- [File yang Dihasilkan](#file-yang-dihasilkan)
- [Menjalankan 24/7](#menjalankan-247)
- [Troubleshooting](#troubleshooting)
- [Struktur Folder](#struktur-folder)

---

## Kebutuhan

| Item | Keterangan |
|---|---|
| OS | Windows |
| Python | 3.11 atau lebih baru (dites di 3.14.7) |
| Google Drive Desktop | Terpasang & berjalan, drive sudah ter-mount (mis. `G:\My Drive`) |
| Dependency | **Tidak ada** (stdlib-only) |

> Pastikan huruf drive Google Drive Desktop sesuai. Cek di File Explorer — biasanya
> `G:\My Drive`, kadang `H:\My Drive`. Kalau beda, ganti lewat argumen `--dst`.

---

## Cara Pakai Cepat

```bat
REM 1. Jalankan 24/7 (default: folder "dummy" -> G:\My Drive\dummy, jalan terus)
run_24jam.bat

REM 2. Atau langsung lewat Python
python migrate.py

REM 3. Uji dulu tanpa menghapus/menyalin apa pun (aman)
python migrate.py --dry-run
```

Taruh file apa saja ke folder `dummy\`. Dalam beberapa detik (sesuai interval), file itu akan
pindah ke `G:\My Drive\dummy` dan **terhapus dari folder lokal**. Script jalan terus (24/7).

---

## Cara Kerja

Setiap putaran (default tiap **60 detik**):

```
1. Scan semua file di folder lokal (SRC).
2. Untuk tiap file:
     a. Tentukan nama tujuan. Kalau nama sudah ada di Drive
        -> pakai "nama (1).ext", "nama (2).ext", dst. (TIDAK pernah menimpa)
     b. Copy ke Drive dengan nama sementara (".nama.ext.tmp-<pid>").
     c. Hitung SHA-256 sumber & hasil copy -> kalau BEDA, batalkan (file lokal dipertahankan).
     d. Kalau COCOK -> rename ke nama final.
     e. Hapus file lokal (hanya setelah copy terverifikasi).
     f. Kalau langkah b/c gagal (mis. network error) -> ulangi 3x dengan jeda bertambah.
        Masih gagal? File lokal DIPERTAHANKAN, lanjut ke file berikutnya.
3. Kalau folder lokal kosong -> TIDAK berhenti, tetap menunggu file baru.
4. Jalan terus 24/7 (default). Pakai `--duration N` untuk berhenti otomatis, atau Ctrl+C.
```

**Prinsip aman:** file lokal tidak akan pernah hilang sebelum salinan di Drive terbukti utuh.
Kalau Drive tidak siap / copy gagal, file lokal dibiarkan dan dicoba lagi putaran berikutnya.

---

## Ketahanan saat Network Error

Ini bagian yang menjawab: *"bagaimana kalau file banyak dan proses kena network error?"*

**Jawaban singkat: script tidak akan mati, tidak ada file yang hilang, dan semua file akan
tetap dipindah begitu koneksi/Drive kembali normal.**

### Apa yang terjadi saat Drive/network putus

| Situasi | Perilaku script |
|---|---|
| Drive hilang **sebelum** menyentuh file | Script berhenti sejenak (`[WARN] Drive tidak siap`), **tidak menghapus apa pun**, dan menunggu. Jeda cek makin lama (backoff: 60s → 120s → 240s → maks 300s) supaya tidak membebani. Begitu Drive kembali → `[INFO] Drive siap kembali`, lanjut normal. |
| Drive putus **di tengah** copy 1 file | File itu dicoba ulang **3×** dengan jeda bertambah (3s → 6s → 12s). Kalau tetap gagal → `[GAGAL]`, **file lokal DIPERTAHANKAN** dan dicoba lagi putaran berikutnya. |
| 1 file gagal | File **lain tetap diproses**. Satu file bermasalah tidak menghentikan antrean. |
| Copy terputus, menyisakan file sementara | Sisa `.nama.ext.tmp-<pid>` otomatis dibersihkan. Kalau pun tersisa (Drive mati total), aman dihapus manual — tidak akan dianggap file final. |
| Folder lokal error dibaca | `[WARN] Tidak bisa scan folder lokal`, loop tetap hidup dan mencoba lagi. |
| Error tak terduga apa pun | Ditangkap, dicatat, loop **tetap jalan** sampai durasi habis. |

### Jaminan (dijamin oleh kode)

1. **File lokal tidak pernah dihapus** kecuali copy-nya sudah lolos verifikasi SHA-256.
2. **Tidak ada file hilang** — skenario terburuk hanyalah file tetap tinggal di folder lokal
   (aman) dan dicoba lagi nanti.
3. **Tidak ada file setengah jadi** yang terlihat sebagai file final (selalu lewat nama `.tmp`).
4. **Loop 24/7 tidak mati** karena network error — diuji dengan memutus Drive di tengah proses.

### Contoh log saat network error

```
[WARN] Drive tidak siap (G:\My Drive\dummy): [Errno 2] ... — tunggu sampai tersedia
[RETRY] laporan.pdf gagal (percobaan 1/3): [Errno 59] ... — coba lagi dalam 3s
[RETRY] laporan.pdf gagal (percobaan 2/3): [Errno 59] ... — coba lagi dalam 6s
[GAGAL] laporan.pdf setelah 3 percobaan: [Errno 59] ... (file lokal DIPERTAHANKAN, dicoba putaran berikutnya)
[INFO] Drive siap kembali (setelah 84s).
[OK] laporan.pdf (2.4 MB) -> laporan.pdf
```

### Kalau file sangat banyak (ratusan / ribuan)

- Diproses **satu per satu**, jadi aman untuk jumlah besar.
- 1 file gagal tidak menghambat file lain — langsung lanjut ke berikutnya.
- File yang gagal otomatis masuk antrean ulang di putaran berikutnya (tidak perlu diapa-apakan).
- Progres terlihat di `migrate.log` dan `migrate.heartbeat` (`total N` = jumlah file sukses).
- **Tips:** kalau file sangat besar/banyak dan ingin jeda lebih longgar antar percobaan, atur
  `FILE_RETRIES`, `FILE_RETRY_DELAY`, dan `DRIVE_MAX_BACKOFF` di bagian atas `migrate.py`.

---

## Opsi Command-Line

| Opsi | Default | Keterangan |
|---|---|---|
| `--src` | `C:\Users\USER\Desktop\PROJECT\gdrive-desktop\dummy` | Folder lokal sumber |
| `--dst` | `G:\My Drive\dummy` | Folder tujuan di Drive |
| `--interval` | `60` | Jeda antar pengecekan (detik) |
| `--duration` | `0` | Lama jalan (jam). `0` = **24/7 tanpa batas (default)** |
| `--once` | — | Jalankan sekali lalu keluar |
| `--dry-run` | — | Tampilkan saja, tidak copy/hapus |
| `--help` | — | Tampilkan bantuan |

### Contoh

```bat
REM Ganti folder sumber & tujuan
python migrate.py --src "D:\data" --dst "G:\My Drive\backup"

REM Cek tiap 30 detik
python migrate.py --interval 30

REM Jalan terus tanpa batas waktu (sampai Ctrl+C) -- INI DEFAULT
python migrate.py --duration 0

REM Hanya 24 jam lalu berhenti sendiri
python migrate.py --duration 24

REM Sekali jalan saja (cocok untuk dijadikan scheduled task)
python migrate.py --once

REM Coba aman: lihat apa yang AKAN dipindah, tanpa benar-benar memindah
python migrate.py --dry-run
```

---

## Konfigurasi Default

Nilai default ada di bagian atas `migrate.py` (boleh diedit langsung):

```python
DEFAULT_SRC = r"C:\Users\USER\Desktop\PROJECT\gdrive-desktop\dummy"
DEFAULT_DST = r"G:\My Drive\dummy"
DEFAULT_INTERVAL = 60     # detik antar pengecekan
DEFAULT_DURATION_H = 0    # jam; 0 = 24/7 tanpa batas (default)
```

Kalau folder Anda tetap, edit 2 baris pertama agar tidak perlu mengetik argumen tiap kali.
Kalau folder sering berubah, biarkan default dan pakai `--src` / `--dst`.

---

## File yang Dihasilkan

Semua dibuat otomatis di folder script:

| File | Fungsi |
|---|---|
| `migrate.log` | Catatan semua aktivitas (OK, GAGAL, peringatan). Untuk memeriksa riwayat. |
| `migrate.heartbeat` | Diperbarui tiap putaran — bukti script masih hidup. Berisi waktu, uptime, total file. |
| `migrate.lock` | Kunci agar hanya **satu** instance berjalan. Mencegah duplikat/race. |

**Cek status kapan saja:**
```bat
type migrate.heartbeat     REM lihat kapan terakhir jalan
type migrate.log           REM lihat riwayat lengkap
```

---

## Menjalankan 24/7

### Cara 1 — Dobel-klik `run_24jam.bat`
Paling mudah. Menjalankan migrasi **24/7** (jalan terus) dengan pengaturan default.

```bat
run_24jam.bat                          REM default: 24/7, jalan terus
run_24jam.bat --interval 30            REM custom: cek tiap 30 detik
run_24jam.bat --duration 24            REM hanya 24 jam lalu berhenti
run_24jam.bat --src "D:\data" --dst "G:\My Drive\backup"
```

### Cara 2 — Langsung Python
```bat
python migrate.py                      REM default 24/7 (jalan terus)
python migrate.py --interval 60 --duration 24   REM hanya 24 jam
```

### Menghentikan
- Tutup jendela console-nya, atau tekan **Ctrl+C** di jendela tersebut.

> **Catatan penting:** kalau komputer dimatikan/restart, proses ini ikut berhenti.
> Setelah komputer menyala lagi, jalankan `run_24jam.bat` kembali.
> Kalau ingin jalan otomatis setiap kali komputer nyala, lihat bagian berikut.

### (Opsional) Auto-start saat komputer nyala

Buat file `auto_start.bat`:

```bat
@echo off
cd /d "%~dp0"
python migrate.py --duration 0
```

Lalu daftarkan ke Startup Windows:
1. Tekan `Win + R`, ketik `shell:startup`, Enter.
2. Salin (shortcut) `auto_start.bat` ke folder yang terbuka.

Atau lewat Task Scheduler (PowerShell **Administrator**):

```powershell
$action  = New-ScheduledTaskAction -Execute "python" `
           -Argument "migrate.py --duration 0" `
           -WorkingDirectory "C:\Users\USER\Desktop\PROJECT\gdrive-desktop"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "GDriveDesktopMigrator" -Action $action -Trigger $trigger
```

---

## Troubleshooting

| Gejala | Penyebab & Solusi |
|---|---|
| `[ERROR] Folder lokal tidak ada` | Path `--src` salah. Pastikan foldernya benar-benar ada. |
| `[ERROR] Sudah ada migrasi berjalan` | Sudah ada instance lain. Tutup yang lama dulu, atau hapus `migrate.lock` kalau prosesnya sudah mati. |
| `[WARN] Drive tidak siap ...` | Google Drive Desktop belum jalan / drive belum ter-mount / huruf drive beda. Cek `G:\My Drive` di File Explorer, lalu sesuaikan `--dst`. |
| File tidak kunjung pindah | Script hanya berjalan tiap `--interval` detik. Tunggu sebentar, atau perkecil intervalnya. |
| File tetap di folder lokal | Kemungkinan gagal copy (Drive penuh / file terkunci / network error). Cek `migrate.log` untuk baris `[GAGAL]` / `[RETRY]`. File itu otomatis dicoba lagi putaran berikutnya. |
| Log penuh `[RETRY]` / `[GAGAL]` berulang | Drive/network sedang bermasalah. Script tetap hidup dan akan menuntaskan sendiri setelah koneksi normal. Tidak perlu restart. |
| Muncul file aneh `.namafile.ext.tmp-1234` | Sisa proses yang terputus saat copy. Aman untuk dihapus manual — tidak akan dianggap file final. |
| Nama file jadi `nama (1).ext` | Normal — itu artinya sudah ada file dengan nama sama di Drive, jadi tidak ditimpa. |

---

## Struktur Folder

```
gdrive-desktop/
├── migrate.py          # Script utama
├── run_24jam.bat       # Peluncur 24/7
├── README.md           # Dokumen ini
├── dummy/              # Folder lokal (sumber)
├── migrate.log         # Log aktivitas        (dibuat otomatis)
├── migrate.heartbeat   # Status hidup         (dibuat otomatis)
└── migrate.lock        # Kunci single-instance (dibuat otomatis)
```

---

## Catatan Teknis

- **Hash:** SHA-256, dihitung streaming (hemat memori untuk file besar).
- **Nama sementara:** `.nama.ext.tmp-<pid>` mencegah file setengah jadi terlihat sebagai file final.
- **Single-instance:** pakai `msvcrt.locking` (Windows) / `fcntl.flock` (Linux/macOS).
- **Atomic rename:** `Path.replace()` supaya perpindahan ke nama final tidak setengah jalan.
- **Retry & backoff:** tiap file dicoba `FILE_RETRIES`× (default 3) dengan jeda berlipat; saat Drive
  lama tidak siap, jeda antar putaran naik sampai `DRIVE_MAX_BACKOFF` (default 300s).
- **Anti-crash:** semua operasi I/O dibungkus penanganan error — satu file/putaran gagal tidak
  menghentikan loop 24/7.
- **File tersembunyi** (diawali `.`) di folder sumber dilewati.
- **Subfolder** di folder sumber saat ini **tidak** diproses (hanya file di level teratas).

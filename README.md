# Auto-Migrate Lokal → Google Drive Desktop

Script Python sederhana untuk **memindahkan file** dari sebuah folder lokal ke folder di
**Google Drive Desktop** secara otomatis. File lokal dihapus setelah salinan di Drive terverifikasi,
dan script mengawasi folder tersebut terus-menerus (default **24 jam**).

- **Satu file, tanpa dependency** — cukup Python 3.11+ (stdlib saja).
- **Anti nama double** — kalau nama sudah ada di Drive, otomatis jadi `nama (1).ext`.
- **Aman** — file lokal hanya dihapus setelah copy diverifikasi dengan SHA-256.
- **Interval & folder bisa diset** — lewat argumen, tanpa edit kode.

---

## Daftar Isi
- [Kebutuhan](#kebutuhan)
- [Cara Pakai Cepat](#cara-pakai-cepat)
- [Cara Kerja](#cara-kerja)
- [Opsi Command-Line](#opsi-command-line)
- [Konfigurasi Default](#konfigurasi-default)
- [File yang Dihasilkan](#file-yang-dihasilkan)
- [Menjalankan 24 Jam](#menjalankan-24-jam)
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
REM 1. Jalankan selama 24 jam (default: folder "dummy" -> G:\My Drive\dummy)
run_24jam.bat

REM 2. Atau langsung lewat Python
python migrate.py

REM 3. Uji dulu tanpa menghapus/menyalin apa pun (aman)
python migrate.py --dry-run
```

Taruh file apa saja ke folder `dummy\`. Dalam beberapa detik (sesuai interval), file itu akan
pindah ke `G:\My Drive\dummy` dan **terhapus dari folder lokal**.

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
3. Kalau folder lokal kosong -> TIDAK berhenti, tetap menunggu file baru.
4. Berhenti setelah durasi habis (default 24 jam), atau Ctrl+C.
```

**Prinsip aman:** file lokal tidak akan pernah hilang sebelum salinan di Drive terbukti utuh.
Kalau Drive tidak siap / copy gagal, file lokal dibiarkan dan dicoba lagi putaran berikutnya.

---

## Opsi Command-Line

| Opsi | Default | Keterangan |
|---|---|---|
| `--src` | `C:\Users\USER\Desktop\PROJECT\gdrive-desktop\dummy` | Folder lokal sumber |
| `--dst` | `G:\My Drive\dummy` | Folder tujuan di Drive |
| `--interval` | `60` | Jeda antar pengecekan (detik) |
| `--duration` | `24` | Lama jalan (jam). `0` = tanpa batas |
| `--once` | — | Jalankan sekali lalu keluar |
| `--dry-run` | — | Tampilkan saja, tidak copy/hapus |
| `--help` | — | Tampilkan bantuan |

### Contoh

```bat
REM Ganti folder sumber & tujuan
python migrate.py --src "D:\data" --dst "G:\My Drive\backup"

REM Cek tiap 30 detik
python migrate.py --interval 30

REM Jalan terus tanpa batas waktu (sampai Ctrl+C)
python migrate.py --duration 0

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
DEFAULT_DURATION_H = 24   # jam; 0 = tanpa batas
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

## Menjalankan 24 Jam

### Cara 1 — Dobel-klik `run_24jam.bat`
Paling mudah. Menjalankan migrasi 24 jam dengan pengaturan default, lalu menutup jendela sendiri.

```bat
run_24jam.bat                          REM default
run_24jam.bat --interval 30            REM custom: cek tiap 30 detik
run_24jam.bat --duration 0             REM jalan terus tanpa batas
run_24jam.bat --src "D:\data" --dst "G:\My Drive\backup"
```

### Cara 2 — Langsung Python
```bat
python migrate.py --interval 60 --duration 24
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
| File tetap di folder lokal | Kemungkinan gagal copy (Drive penuh / file terkunci). Cek `migrate.log` untuk baris `[GAGAL]`. |
| Muncul file aneh `.namafile.ext.tmp-1234` | Sisa proses yang terputus saat copy. Aman untuk dihapus manual. |
| Nama file jadi `nama (1).ext` | Normal — itu artinya sudah ada file dengan nama sama di Drive, jadi tidak ditimpa. |

---

## Struktur Folder

```
gdrive-desktop/
├── migrate.py          # Script utama
├── run_24jam.bat       # Peluncur 24 jam
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
- **File tersembunyi** (diawali `.`) di folder sumber dilewati.
- **Subfolder** di folder sumber saat ini **tidak** diproses (hanya file di level teratas).

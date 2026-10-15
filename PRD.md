# PRD — Auto-Migrate Lokal → Google Drive Desktop

**Status:** Draft siap eksekusi
**Target eksekusi:** Orca (repo `gdrive-desktop`, kind: folder)
**Bahasa deliverable:** kode + komentar + log dalam Bahasa Indonesia

---

## 1. Ringkasan

Bangun otomatisasi Python yang memantau sebuah **folder lokal**, lalu **memindahkan** setiap file
ke folder tujuan di **Google Drive Desktop** (drive yang di-mount sebagai huruf drive, mis. `G:`),
**menghapus file lokal setelah migrasi terverifikasi**, dan mengulanginya setiap **60 detik**
selama 24 jam non-stop.

Pendekatan yang dipakai adalah **filesystem copy ke mount point**, **bukan** Google Drive API.
Alasannya: tidak perlu OAuth, tidak ada `credentials.json` / `token.json`, tidak ada refresh token
yang expired 7 hari, dan tidak ada kuota API. Drive Desktop sudah menangani upload ke cloud.

> **Catatan konteks:** project lama di `C:\Users\USER\Desktop\PROJECT\gdrive` memakai Google Drive
> API. Project ini **terpisah** dan berada di `C:\Users\USER\Desktop\PROJECT\gdrive-desktop`.
> Jangan menyentuh folder lama.

---

## 2. Environment terverifikasi

| Item | Nilai |
|---|---|
| Project dir | `C:\Users\USER\Desktop\PROJECT\gdrive-desktop` |
| Orca repo id | `95016819-7659-4911-bbbe-5da40414c75e` (kind: `folder`) |
| Orca CLI | `C:\Users\USER\AppData\Local\Programs\orca\resources\bin\orca.exe` (v1.4.226) |
| Google Drive Desktop | running (`GoogleDriveFS`), mount di `G:\My Drive` |
| Python | 3.14.7 (Windows) |
| Git | 2.53.0 |
| OS | Windows |

Repo Orca berjenis **folder**, jadi **tidak ada git worktree**. Semua eksekusi memakai
`orca agent launch` / `orca terminal` di dalam folder tersebut.

---

## 3. Tujuan & Non-Tujuan

### Tujuan
1. File di folder lokal otomatis pindah ke Google Drive tanpa intervensi manual.
2. File lokal **hanya dihapus setelah** salinan di Drive terbukti utuh.
3. Tidak pernah ada duplikat di Drive.
4. Berjalan 24/7, tahan crash, auto-restart.
5. Semua path (folder lokal & folder Drive) bisa diganti **hanya dari config**, tanpa edit kode.

### Non-Tujuan
- Bukan tool sync dua arah (Drive → lokal). Satu arah saja: lokal → Drive.
- Bukan tool backup/versioning. File lokal memang dihapus.
- Tidak menangani Google Drive API / OAuth.
- Tidak menangani multi-akun Drive secara bersamaan.
- Tidak ada UI/GUI. CLI + log file saja.

---

## 4. Requirement Fungsional

### FR-1 — Mount detection
- Sistem harus mendeteksi apakah Google Drive Desktop **benar-benar ter-mount** dan **bisa ditulis**.
- Deteksi bukan hanya `Path.exists()`, tapi juga: buat file probe kecil → hapus. Jika gagal → dianggap belum siap.
- Jika mount tidak siap:
  - **Fase hapus DILEWATI total** (safety-critical: jangan hapus apa pun kalau Drive tidak siap).
  - Log peringatan yang jelas, lalu tunggu interval berikutnya dan coba lagi.
- Jika folder tujuan belum ada → buat otomatis (`mkdir`).
- **Opsional (nice-to-have):** auto-detect huruf drive dengan memindai volume yang punya folder `My Drive`.

### FR-2 — Scan folder lokal
- Scan **rekursif** seluruh file di `LOCAL_DIR`.
- Lewati (skip) file dengan pola: `~$*`, `*.tmp`, `*.temp`, `*.part`, `*.partial`,
  `*.crdownload`, `Thumbs.db`, `.DS_Store`, `desktop.ini`, dan file milik aplikasi ini sendiri
  (manifest, log, config).
- **Stability check:** file hanya dianggap siap migrasi jika `(size, mtime)` **identik dengan scan
  sebelumnya** DAN `mtime` sudah lebih tua dari `MIN_AGE_SECONDS`. Ini mencegah file yang sedang
  disalin setengah jalan ikut ter-migrasi.

### FR-3 — Anti-duplikat
- Hitung **SHA-256** setiap file lokal.
- Manifest (SQLite) menyimpan setiap hash yang sudah pernah dimigrasi.
- Jika hash sudah tercatat **dan** file tujuan masih ada di Drive → **jangan upload ulang**,
  langsung tandai selesai (dan hapus lokal sesuai fase hapus).
- Jika nama file sudah ada di Drive tapi **hash berbeda** → **jangan menimpa**. Simpan sebagai
  `nama (1).ext`, `nama (2).ext`, dst. Data lama tidak pernah ditimpa.
- Kunci dedupe adalah **hash konten**, bukan nama file.

### FR-4 — Copy + verifikasi (fase upload)
- Copy file ke Drive dengan **nama sementara** (mis. `namafile.ext.partial-<uuid>`).
- **Baca ulang file dari Drive dan hitung SHA-256-nya**, bandingkan dengan sumber.
  Ini membuktikan byte yang sampai di DriveFS identik.
- Jika cocok → rename (atomic) dari nama sementara ke nama final.
- Jika tidak cocok / error → hapus file sementara, catat `state=failed`, file lokal **dipertahankan**,
  ulangi di siklus berikutnya.
- Catat ke manifest: `state=verified`, `verified_at=<timestamp>`, `sha256`, `size`, `drive_path`.

### FR-5 — Hapus lokal (fase hapus, dengan grace period)
- File lokal **hanya** dihapus jika semua kondisi ini terpenuhi:
  1. Manifest mencatat `state=verified`.
  2. `now - verified_at >= DELETE_GRACE_SECONDS` (default **60 detik**).
  3. File tujuan **masih ada** di Drive.
  4. Hash file di Drive **masih sama** dengan yang tercatat.
  5. Mount Drive sedang sehat (FR-1 lolos di siklus ini).
- Setelah hapus sukses → `state=done`.
- Jika file lokal terkunci (mis. sedang dibuka Excel, `WinError 32`) → retry beberapa kali dengan
  backoff, kalau tetap gagal → log `[ERR]` dan coba lagi siklus berikutnya. **Jangan** paksa hapus.

> **Kenapa grace period?** Google Drive Desktop adalah filesystem streaming dengan cache lokal.
> Ukuran file di `G:` bisa langsung terlihat besar padahal upload ke cloud belum selesai.
> Grace period + verifikasi ulang memberi jendela waktu bagi DriveFS menyelesaikan upload sebelum
> sumber dihapus. Ini pengaman utama anti data-loss.

### FR-6 — Loop 60 detik
- Siklus berjalan setiap `INTERVAL_SECONDS` (default **60**).
- Interval dihitung dari **mulai siklus** (`sleep = max(1, INTERVAL - elapsed)`), sehingga tidak drift.
- Urutan dalam satu siklus: **(1) cek mount → (2) fase hapus → (3) scan → (4) fase upload → (5) log ringkasan → (6) sleep**.
- Satu error tidak boleh mematikan loop. Semua exception ditangkap, di-log, loop lanjut.

### FR-7 — Konfigurasi
Semua setting di **satu file config** (`config.toml`), dengan nilai contoh yang jelas bisa diganti:

```toml
# ====== GANTI SESUAI KEBUTUHAN ======
[paths]
# Contoh folder lokal — ganti ke folder mana pun
local_dir = "C:/Users/USER/Desktop/PROJECT/gdrive-desktop/local_data"
# Contoh root Google Drive Desktop — ganti sesuai huruf drive kamu
drive_root = "G:/My Drive"
# Subfolder tujuan di dalam drive_root (dibuat otomatis kalau belum ada)
drive_folder = "MIGRASI_LOCAL"

[behavior]
interval_seconds = 60        # interval loop
delete_grace_seconds = 60    # jeda aman sebelum hapus lokal
min_age_seconds = 5          # file harus setua ini sebelum dianggap stabil
delete_after_migrate = true  # false = pindahkan ke local_archive/ (tidak dihapus)
max_delete_retries = 3

[dedupe]
on_name_conflict = "rename"  # rename | skip
hash_algo = "sha256"

[logging]
log_file = "logs/migrator.log"
log_max_bytes = 5242880
log_backup_count = 5
level = "INFO"

[safety]
dry_run = false              # true = tidak menghapus apa pun, hanya log
require_mount_probe = true   # wajib lolos probe tulis-baca sebelum fase hapus
```

- **Tidak boleh ada path yang di-hardcode di kode.** Semua lewat config.
- Config dibaca sekali saat start; kalau file config tidak ada → buat dari default + beri pesan jelas.

### FR-8 — Logging & observability
- Log ke **stdout** DAN file dengan rotasi (`RotatingFileHandler`).
- Format: `[YYYY-MM-DD HH:MM:SS] [LEVEL] pesan`.
- Setiap file yang diproses di-log: nama, ukuran (human-readable), aksi, hasil.
- Ringkasan akhir siklus: `N uploaded, N duplicate, N deleted, N gagal, X MB dipindahkan`.
- **Heartbeat:** tulis timestamp ke `logs/heartbeat.txt` setiap siklus (untuk cek "masih hidup?").

### FR-9 — Single instance
- Hanya boleh ada **satu** monitor berjalan. Dua instance = risiko race & duplikat.
- Pakai lock file (`msvcrt.locking` di Windows). Instance kedua → keluar dengan pesan jelas.

### FR-10 — 24/7 & auto-start
- Sediakan `install_task.ps1` untuk mendaftarkan **Windows Scheduled Task**:
  - Trigger: **at system startup**
  - Setting: **run whether user is logged on or not**
  - Restart on failure: 3x, interval 1 menit
  - Start in: project dir
- Sediakan `run_monitor.bat` untuk menjalankan manual.
- Sediakan `uninstall_task.ps1` untuk membatalkan.

### FR-11 — Graceful shutdown
- `Ctrl+C` (SIGINT) dan SIGTERM harus menutup dengan rapi: hentikan siklus, tutup manifest DB,
  tulis log `"Dihentikan oleh user"`.
- Jangan pernah tinggal di tengah copy tanpa membereskan file `.partial-*`.

### FR-12 — Crash recovery
- Saat start, bersihkan file `.partial-*` yang tertinggal di Drive dari run sebelumnya.
- Rekonsiliasi manifest: entri `state=verified` yang file Drive-nya hilang → tandai `state=stale`
  dan jangan hapus lokalnya.

---

## 5. Requirement Non-Fungsional

| ID | Requirement |
|---|---|
| NFR-1 | **Zero data loss.** Tidak ada file yang hilang. Safety > kecepatan. |
| NFR-2 | **Idempotent.** Jalankan 10x pada input sama = hasil sama, tanpa duplikat. |
| NFR-3 | Tahan mati listrik / kill -9. Restart tidak boleh menduplikasi atau menghilangkan data. |
| NFR-4 | Loop tidak boleh mati karena exception apa pun. |
| NFR-5 | Log cukup untuk diagnosa tanpa debugger. |
| NFR-6 | Windows-first, tapi hindari API yang tidak portabel kalau mudah. |
| NFR-7 | Path panjang (`>260` char) harus ditangani (prefix `\\?\` atau `longPathAware`). |
| NFR-8 | Tidak ada dependency berat. Cukup stdlib + minimal (kalau perlu). |
| NFR-9 | CPU idle rendah (loop tidur 60 detik, bukan busy-wait). |

---

## 6. Alur (Logic)

```
START
  ├─ baca config
  ├─ ambil lock file (gagal → exit)
  ├─ buka manifest SQLite
  ├─ bersihkan file .partial-* yang tertinggal
  └─ LOOP:
       ├─ 1. CEK MOUNT
       │     └─ probe tulis-baca ke drive_root
       │        ├─ GAGAL → log, SKIP fase hapus, lanjut ke step 6
       │        └─ OK → lanjut
       │
       ├─ 2. FASE HAPUS
       │     └─ untuk entri manifest state=verified & umur >= grace:
       │          cek file Drive ada? hash masih sama?
       │            ├─ YA  → hapus file lokal → state=done
       │            └─ TIDAK → state=stale, JANGAN hapus lokal
       │
       ├─ 3. SCAN LOKAL (rekursif, skip pola & file tidak stabil)
       │
       ├─ 4. FASE UPLOAD
       │     └─ untuk tiap file stabil:
       │          hitung SHA-256
       │            ├─ hash sudah di manifest & file Drive ada
       │            │     → SKIP upload (anti-duplikat), state=verified
       │            └─ belum
       │                  → copy ke Drive sebagai .partial-<uuid>
       │                  → baca ulang + hash ulang
       │                     ├─ cocok  → rename ke nama final
       │                     │           (nama bentrok? → "nama (1).ext")
       │                     │           state=verified, verified_at=now
       │                     └─ beda   → hapus .partial, state=failed,
       │                                 file lokal DIPERTAHANKAN
       │
       ├─ 5. LOG RINGKASAN + tulis heartbeat
       │
       └─ 6. SLEEP max(1, INTERVAL - elapsed) → ulang LOOP
```

---

## 7. Deliverables

```
gdrive-desktop/
├── PRD.md                    # dokumen ini
├── README.md                 # cara pakai, setup, troubleshooting
├── config.toml               # config aktif (dibuat dari contoh kalau belum ada)
├── config.example.toml       # template dengan nilai contoh yang jelas
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── config.py             # loader + validasi config
│   ├── logging_setup.py      # logger + rotasi
│   ├── drivefs.py            # deteksi mount, probe, resolve path, mkdir
│   ├── manifest.py           # SQLite journal (schema, CRUD, rekonsiliasi)
│   ├── migrator.py           # core: scan, hash, copy, verify, delete
│   └── monitor.py            # loop 60s, lock file, signal handling
├── scripts/
│   ├── run_monitor.bat
│   ├── run_once.bat          # jalankan 1 siklus saja
│   ├── install_task.ps1
│   └── uninstall_task.ps1
├── tests/
│   ├── test_config.py
│   ├── test_drivefs.py       # pakai temp dir sebagai fake mount
│   ├── test_manifest.py
│   ├── test_migrator.py      # upload, dedupe, konflik nama, gagal verify
│   ├── test_delete_phase.py  # grace period, file hilang, mount mati
│   └── test_monitor.py       # loop, single instance, crash recovery
├── local_data/               # CONTOH folder lokal (isi file uji)
├── local_archive/            # dipakai kalau delete_after_migrate = false
├── logs/
└── .gitignore
```

**Dependencies:** target **stdlib-only**. `tomllib` sudah ada di Python 3.11+ (kita pakai 3.14).
SQLite (`sqlite3`) sudah bawaan. Jadi `requirements.txt` idealnya kosong/kosmetik.

---

## 8. Kriteria Penerimaan (Acceptance Criteria)

| ID | Skenario | Hasil yang Diharapkan |
|---|---|---|
| AC-1 | 3 file di `local_data/`, jalankan monitor | 3 file muncul di Drive, SHA-256 identik, file lokal terhapus setelah grace |
| AC-2 | Jalankan ulang dengan file yang sama | **0 upload baru**, jumlah file di Drive tetap 3 (tidak ada duplikat) |
| AC-3 | File `laporan.pdf` sudah ada di Drive dengan isi berbeda | File baru tersimpan sebagai `laporan (1).pdf`; file lama **tidak tertimpa** |
| AC-4 | Drive Desktop dimatikan, ada file `state=verified` | **Tidak ada** file lokal yang terhapus; log peringatan jelas; retry siklus berikutnya |
| AC-5 | File sedang dibuka di Excel | Tidak terhapus; log `[ERR] terkunci`; berhasil dihapus setelah file ditutup |
| AC-6 | File besar sedang disalin ke `local_data/` | Tidak dimigrasi sampai ukuran stabil (`min_age_seconds`) |
| AC-7 | `kill -9` di tengah siklus, lalu start lagi | Tidak ada duplikat, tidak ada data hilang, `.partial-*` dibersihkan |
| AC-8 | Dua instance dijalankan bersamaan | Instance kedua exit dengan pesan jelas (lock file) |
| AC-9 | Ganti `local_dir` & `drive_root` di config | Berjalan tanpa mengubah satu baris pun kode |
| AC-10 | `dry_run = true` | Tidak ada file yang dihapus maupun ditulis ke Drive; hanya log |
| AC-11 | Siklus gagal (exception) | Loop tetap hidup, error ter-log, siklus berikutnya normal |
| AC-12 | Interval | Siklus berikutnya mulai ~60 detik setelah siklus sebelumnya **mulai** |

---

## 9. Rencana Eksekusi di Orca

Repo `gdrive-desktop` berjenis **folder**, jadi tidak ada worktree. Semua agent dijalankan
langsung di folder itu.

`ORCA` di bawah = `C:\Users\USER\AppData\Local\Programs\orca\resources\bin\orca.exe`

### Opsi A — Satu agent (disarankan untuk mulai)

```powershell
& "C:\Users\USER\AppData\Local\Programs\orca\resources\bin\orca.exe" agent launch `
  --agent codex `
  --worktree "id:95016819-7659-4911-bbbe-5da40414c75e::C:\Users\USER\Desktop\PROJECT\gdrive-desktop" `
  --prompt "<ISI PROMPT DARI SEKSI 10>" `
  --json
```

### Opsi B — DAG paralel (kalau mau lebih cepat)

| Task | Isi | Depends on |
|---|---|---|
| T1 | Scaffold: struktur folder, `config.py`, `config.toml`, `logging_setup.py`, `requirements.txt` | — |
| T2 | `drivefs.py`: deteksi mount, probe tulis-baca, resolve path, mkdir | T1 |
| T3 | `manifest.py`: schema SQLite, CRUD, rekonsiliasi | T1 |
| T4 | `migrator.py`: scan, hash, copy+verify, dedupe, konflik nama, delete phase | T2, T3 |
| T5 | `monitor.py`: loop 60s, lock file, signal handling, heartbeat | T4 |
| T6 | `tests/`: seluruh test suite | T4, T5 |
| T7 | `scripts/`: .bat + install_task.ps1 + uninstall_task.ps1 | T5 |
| T8 | `README.md`: setup, cara ganti path, troubleshooting | T6, T7 |

T1–T3 bisa paralel. T6–T8 bisa paralel setelah T5.

---

## 10. Prompt untuk Agent Orca

```
Bangun otomatisasi Python di folder ini (C:\Users\USER\Desktop\PROJECT\gdrive-desktop)
sesuai PRD.md yang ada di folder ini. Baca PRD.md dulu sampai habis.

Ringkas: monitor folder lokal, pindahkan file ke Google Drive Desktop (mount G:\My Drive),
hapus file lokal setelah migrasi terverifikasi, ulang tiap 60 detik, 24/7, anti-duplikat.

Aturan wajib:
1. Ikuti PRD.md sebagai sumber kebenaran. Semua FR-1..FR-12 dan AC-1..AC-12 harus terpenuhi.
2. Semua path WAJIB dari config.toml — jangan hardcode path di kode.
3. SAFETY-CRITICAL: file lokal hanya boleh dihapus setelah (a) mount lolos probe tulis-baca,
   (b) file tujuan ada di Drive, (c) hash SHA-256 cocok, (d) grace period terlewati.
   Kalau salah satu gagal, PERTAHANKAN file lokal.
4. Anti-duplikat berbasis hash konten, bukan nama file. Nama bentrok -> "nama (1).ext",
   jangan pernah menimpa file yang sudah ada.
5. stdlib-only. Python 3.14 sudah tersedia. Jangan tambah dependency eksternal.
6. Tulis test untuk setiap modul. Test TIDAK BOLEH menyentuh G:\ — pakai temp directory
   sebagai fake mount. Jalankan pytest dan pastikan semua hijau.
7. JANGAN menyentuh folder C:\Users\USER\Desktop\PROJECT\gdrive (project lama, beda pendekatan).
8. JANGAN menulis/menghapus apa pun di G:\My Drive saat development. Semua pengujian
   pakai fake mount di temp dir.
9. Komentar dan pesan log dalam Bahasa Indonesia.
10. Kalau ada keputusan desain yang ambigu, tulis di PRD.md bagian "Open Questions"
    dan pilih default yang paling aman (tidak menghapus data).

Deliverable: struktur file sesuai Seksi 7 PRD.md, semua test hijau, README.md lengkap
dengan cara ganti path lokal & path Drive.
```

---

## 11. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| DriveFS belum selesai upload, sumber sudah dihapus | **Data loss** | Grace period + verifikasi ulang hash sebelum hapus (FR-5) |
| Huruf drive berubah (G: → H:) | Migrasi gagal | Path di config; opsional auto-detect (FR-1) |
| Dua instance jalan bersamaan | Duplikat / race | Lock file (FR-9) |
| File setengah tersalin ikut ter-migrasi | File korup di Drive | Stability check (FR-2) |
| File terkunci antivirus/Excel | Gagal hapus | Retry + backoff, jangan paksa (FR-5) |
| Nama file bentrok, isi beda | Data tertimpa | Rename `(1)`, `(2)`, never overwrite (FR-3) |
| Cache DriveFS penuh | Upload gagal | Deteksi error, pertahankan lokal, log jelas |
| Path > 260 karakter | Error OS | Prefix `\\?\` / longPathAware (NFR-7) |
| Listrik mati di tengah copy | File `.partial-*` nyangkut | Bersihkan saat start (FR-12) |
| App OAuth Drive Desktop logout | Mount hilang | Probe gagal → skip hapus (FR-1) |

---

## 12. Open Questions (default aman sudah dipilih)

| # | Pertanyaan | Default yang dipakai | Perlu konfirmasi? |
|---|---|---|---|
| Q1 | Struktur folder lokal dipertahankan di Drive, atau di-flatten? | **Flatten** ke satu folder Drive | Boleh diubah |
| Q2 | Kalau `delete_after_migrate = false`, file lokal dipindah ke `local_archive/`? | **Ya** | — |
| Q3 | File yang sudah ada di Drive dengan hash sama — lokal langsung dihapus? | **Ya**, setelah grace | — |
| Q4 | Auto-start pakai Scheduled Task atau Windows Service (NSSM)? | **Scheduled Task** (tanpa dependency) | Boleh diubah |
| Q5 | Perlu notifikasi (email/Telegram) saat gagal? | **Tidak** (v1), cukup log | Bisa ditambah v2 |
| Q6 | Batas ukuran file maksimal? | **Tidak ada batas** | Bisa ditambah |
| Q7 | Folder Drive tujuan: `G:\My Drive\MIGRASI_LOCAL` sudah ada — pakai itu atau bikin baru? | **Pakai** yang sudah ada | — |

### Keputusan desain saat implementasi (tambahan)

| # | Keputusan | Alasan |
|---|---|---|
| D1 | **Snapshot stabilitas di-persist ke disk** (`logs/stability_snapshot.json`) | Sebelumnya snapshot hanya di memori, sehingga proses baru (mis. `--once` atau restart) tidak pernah memigrasi apa pun sebelum 2 siklus. Persist membuat stability check tahan restart (FR-2 + FR-12) dan `--once` langsung berguna. |
| D2 | **Verifikasi ulang hash file LOKAL sebelum hapus** (di fase hapus) | Pengaman tambahan anti data-loss: kalau file lokal diganti isinya selama grace period, file itu **tidak** dihapus. |
| D3 | **Mode `on_name_conflict = "skip"`** diperlakukan sebagai: lewati kalau nama sudah ada di Drive (tidak menimpa, tidak rename) | Sesuai opsi `rename | skip` di FR-3. |
| D4 | **`hash_algo` dikunci ke `sha256`** | Manifest & dedupe mengasumsikan SHA-256; algo lain ditolak dengan pesan jelas. |
| D5 | **`--once` melakukan priming snapshot dulu** sebelum siklus | Agar satu pemanggilan `--once` benar-benar memigrasi file stabil (tanpa perlu 2x). |

---

## 13. Definisi Selesai (Definition of Done)

- [x] Semua FR-1..FR-12 terimplementasi
- [x] Semua AC-1..AC-12 punya test otomatis yang hijau (73 test lulus)
- [x] `pytest` lulus 100% tanpa menyentuh `G:\`
- [x] `config.example.toml` jelas dan path contoh mudah diganti
- [x] `README.md` mencakup: install, cara ganti path, cara start/stop, troubleshooting
- [x] `install_task.ps1` berhasil mendaftarkan scheduled task *(script siap; pendaftaran nyata butuh admin & dijalankan oleh user)*
- [ ] Uji nyata (manual, oleh user): 3 file dummy di `local_data/` → muncul di Drive → lokal terhapus
- [x] Tidak ada path yang di-hardcode di luar config

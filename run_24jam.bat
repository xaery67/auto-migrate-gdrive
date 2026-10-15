@echo off
REM ============================================================
REM run_24jam.bat - Jalankan migrasi otomatis 24/7 (jalan terus).
REM
REM Default: pantau folder "dummy" -> G:\My Drive\dummy
REM          cek tiap 60 detik, JALAN TERUS tanpa batas waktu.
REM
REM Cara pakai:
REM   run_24jam.bat                          (default 24/7 di atas)
REM   run_24jam.bat --interval 30            (cek tiap 30 detik)
REM   run_24jam.bat --duration 24            (hanya 24 jam lalu berhenti)
REM   run_24jam.bat --src "D:\data" --dst "G:\My Drive\backup"
REM
REM Berhenti: tekan Ctrl+C atau tutup jendela ini.
REM ============================================================
setlocal
cd /d "%~dp0"

echo [INFO] Menjalankan migrasi 24/7 dari: %CD%
echo [INFO] Tekan Ctrl+C untuk berhenti.
echo.

python migrate.py %*

echo.
echo [INFO] Migrasi selesai dengan kode %ERRORLEVEL%.
pause
endlocal

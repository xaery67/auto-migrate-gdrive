@echo off
REM ============================================================
REM run_24jam.bat - Jalankan migrasi otomatis selama 24 jam.
REM
REM Default: pantau folder "dummy" -> G:\My Drive\dummy
REM          cek tiap 60 detik, berhenti sendiri setelah 24 jam.
REM
REM Cara pakai:
REM   run_24jam.bat                          (default di atas)
REM   run_24jam.bat --interval 30            (cek tiap 30 detik)
REM   run_24jam.bat --duration 0             (jalan terus, tanpa batas)
REM   run_24jam.bat --src "D:\data" --dst "G:\My Drive\backup"
REM ============================================================
setlocal
cd /d "%~dp0"

echo [INFO] Menjalankan migrasi 24 jam dari: %CD%
echo [INFO] Tekan Ctrl+C untuk berhenti lebih awal.
echo.

python migrate.py %*

echo.
echo [INFO] Migrasi selesai dengan kode %ERRORLEVEL%.
pause
endlocal

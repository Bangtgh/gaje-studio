@echo off
setlocal
title Roblox Hub
cd /d "%~dp0"

REM --- Cari Python asli (abaikan shortcut Microsoft Store) ---
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"

if not defined PY goto :nopython

REM --- Buat venv kalau belum ada ---
if not exist "venv\Scripts\python.exe" (
  echo [*] Membuat virtual environment...
  %PY% -m venv venv
  if errorlevel 1 goto :fail
)

echo [*] Menginstall / mengecek dependensi...
"venv\Scripts\python.exe" -m pip install -q --upgrade pip
"venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail
"venv\Scripts\python.exe" -m pip install -q -U yt-dlp

echo [*] Server jalan di http://localhost:5000  (tutup jendela ini untuk berhenti)
start "" http://localhost:5000
"venv\Scripts\python.exe" app.py
pause
exit /b

:nopython
echo.
echo [!] Python asli belum terinstall di PC ini.
echo     Yang terdeteksi hanya shortcut Microsoft Store, itu bukan Python.
echo.
winget --version >nul 2>nul
if errorlevel 1 (
  echo     Install manual: https://www.python.org/downloads/
  echo     PENTING: centang "Add python.exe to PATH" saat install.
  start "" https://www.python.org/downloads/
  pause
  exit /b
)
set /p A=Install Python otomatis sekarang? Y/N: 
if /i "%A%"=="Y" (
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo [*] Selesai. TUTUP jendela ini, lalu jalankan run.bat lagi.
) else (
  start "" https://www.python.org/downloads/
)
pause
exit /b

:fail
echo.
echo [!] Terjadi error di langkah di atas. Screenshot / copy pesan errornya.
pause
exit /b

@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 py -3.11 -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo Install Python 3.12 x64 from python.org including the Python Launcher.
  exit /b 1
)
.venv\Scripts\python.exe -m pip install -q --upgrade pip
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 exit /b 1
rem Speech models (Parakeet v3, GigaAM v3, Silero VAD) and Piper voices, downloaded once.
.venv\Scripts\python.exe scripts\download_model.py
if errorlevel 1 exit /b 1
echo.
echo Setup complete. Start with START_WINDOWS.vbs.
echo Everything runs locally for free: speech recognition, voice and the AI model.
exit /b 0

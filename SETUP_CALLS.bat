@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem 6.9: optional libraries for calls - Discord voice channels (py-cord) and Telegram calls (Telethon + py-tgcalls).
rem Run once before BUILD_WINDOWS.bat so the installer includes them. Details: docs\CALLS.md
if not exist .venv\Scripts\python.exe call SETUP_WINDOWS.bat
if not exist .venv\Scripts\python.exe goto error
.venv\Scripts\python.exe -m pip install -r requirements-calls.txt
if errorlevel 1 goto error
echo.
echo Done. Now run BUILD_WINDOWS.bat - Discord and Telegram calls will be inside the installer.
pause
exit /b 0
:error
echo.
echo Install failed - see the messages above.
pause
exit /b 1

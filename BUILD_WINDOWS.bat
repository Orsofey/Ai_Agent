@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call SETUP_WINDOWS.bat
if errorlevel 1 goto error
rem Test output has Russian text and arrows; without this it fails in cp1251 when the output is redirected to a file.
set "PYTHONIOENCODING=utf-8"
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto error
rem The previous build may still be running (it hides in the tray on close) and lock dist\LocalAIAgent.
rem Stop only copies started from this dist folder; an installed copy elsewhere is not touched.
echo Stopping LocalAIAgent started from dist (if running)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = (Join-Path (Get-Location) 'dist') + '\'; Get-Process -Name LocalAIAgent,llama-server -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800"
if exist dist\LocalAIAgent rmdir /s /q dist\LocalAIAgent 2>nul
if exist dist\LocalAIAgent (
  timeout /t 3 /nobreak >nul
  rmdir /s /q dist\LocalAIAgent 2>nul
)
if exist dist\LocalAIAgent (
  echo.
  echo dist\LocalAIAgent is locked by another program.
  echo Quit LocalAIAgent from the tray icon, close Explorer windows opened in dist, and run the build again.
  goto error
)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean LocalAIAgent.spec
if errorlevel 1 goto error
.venv\Scripts\python.exe scripts\bundle_model.py
if errorlevel 1 goto error
rem Piper voices are copied by bundle_model.py
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo EXE folder ready: dist\LocalAIAgent. Do not move only the EXE out of this folder.
  echo Install Inno Setup 6 to also create a single installer EXE.
  exit /b 0
)
rem 7.1: version for the installer comes from app.py (it used to say 5.0.0).
.venv\Scripts\python.exe scripts\installer_check.py > "%TEMP%\andrey_version.txt"
if errorlevel 1 goto error
set /p APPVER=<"%TEMP%\andrey_version.txt"
if not defined APPVER set "APPVER=7.1"
if exist installer rmdir /s /q installer 2>nul
rem 1) LocalAIAgent_Setup.exe: ONE file, send this one to people. The AI model downloads itself on first launch.
"%ISCC%" /DAppVersion=%APPVER% installer.iss
if errorlevel 1 goto error
rem 7.2: update for people who already have Andrey (program files only) + update.json for /admin "Publish update".
"%ISCC%" /DAppVersion=%APPVER% /DUpdate installer.iss
if errorlevel 1 goto error
.venv\Scripts\python.exe scripts\installer_check.py --release installer\LocalAIAgent_Update.exe
if errorlevel 1 goto error
if "%SKIP_FULL%"=="1" goto done
rem 2) Full offline installer: exe + .bin parts, packed into ONE zip so nobody gets the exe without its parts.
"%ISCC%" /DAppVersion=%APPVER% /DFull installer.iss
if errorlevel 1 goto error
pushd installer
tar.exe -a -c -f LocalAIAgent_Setup_Full.zip LocalAIAgent_Setup_Full.exe LocalAIAgent_Setup_Full-*.bin
if errorlevel 1 (
  popd
  echo Could not pack the full installer into a zip. Send LocalAIAgent_Setup_Full.exe together with all .bin files.
  goto done
)
del /q LocalAIAgent_Setup_Full.exe LocalAIAgent_Setup_Full-*.bin
popd
:done
echo.
echo Ready (version %APPVER%):
echo   installer\LocalAIAgent_Setup.exe       - one file, send this one (AI model downloads on first launch)
echo   installer\LocalAIAgent_Update.exe      - in-app update: upload it, then /admin - "Publish update" with update.json
if not "%SKIP_FULL%"=="1" echo   installer\LocalAIAgent_Setup_Full.zip  - offline, everything inside (extract fully, then run)
exit /b 0
:error
echo Build failed. Review output above.
exit /b 1

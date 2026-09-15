@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHON="
where py >nul 2>&1
if not errorlevel 1 set "PYTHON=py"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python313\python.exe" set "PYTHON=%ProgramFiles%\Python313\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python312\python.exe" set "PYTHON=%ProgramFiles%\Python312\python.exe"

echo ============================================
echo  Local AI Agent - Windows desktop build
echo ============================================
echo.

if not defined PYTHON (
  echo [ERROR] Python not found.
  echo Install Python 3.11-3.13 from python.org and enable "Add python.exe to PATH".
  pause
  exit /b 1
)
echo [1/6] Python: !PYTHON!

if not exist venv (
  echo [2/6] Creating virtual environment... this can take a minute.
  "!PYTHON!" -m venv venv
  if errorlevel 1 (
    echo [ERROR] Failed to create the virtual environment.
    pause
    exit /b 1
  )
) else (
  echo [2/6] Virtual environment already exists.
)
if not exist venv\Scripts\activate.bat (
  echo [ERROR] venv\Scripts\activate.bat is missing. Delete the venv folder and run again.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat

echo [3/6] Installing dependencies...
python -m pip install --upgrade pip -q
if errorlevel 1 goto error

python -m pip install -r requirements.txt -q
if errorlevel 1 goto error

python -m pip install pyinstaller -q
if errorlevel 1 goto error

echo [3/6] Verifying imports...
python -c "import flask, psutil, pyautogui, pyperclip, PyInstaller; print('    deps ok')"
if errorlevel 1 goto error

python -c "import webview; print('    pywebview ok')"
if errorlevel 1 (
  echo [WARN] pywebview missing - the app will open in the browser instead of a native window.
)

python -c "import gtts; print('    gTTS ok')"
if errorlevel 1 (
  echo [WARN] gTTS missing - voice feedback will be disabled.
)

echo [4/6] Cleaning previous build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist LocalAIAgent.spec del /q LocalAIAgent.spec

echo [5/6] Building the application with PyInstaller...
python -m PyInstaller --noconfirm --clean --onedir --console --name LocalAIAgent ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "src;src" ^
  --hidden-import flask ^
  --hidden-import psutil ^
  --hidden-import pyautogui ^
  --hidden-import pyperclip ^
  --hidden-import webview ^
  --hidden-import gtts ^
  --hidden-import winreg ^
  --collect-submodules src ^
  main.py
if errorlevel 1 goto error

if not exist "dist\LocalAIAgent\LocalAIAgent.exe" (
  echo [ERROR] PyInstaller finished but dist\LocalAIAgent\LocalAIAgent.exe is missing.
  goto error
)
echo [5/6] Application built: dist\LocalAIAgent\LocalAIAgent.exe

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo.
  echo [6/6] Inno Setup not found - installer was not built.
  echo       Download it from https://jrsoftware.org/isdl.php
  echo       Then run this script again.
  echo.
  echo The application itself is ready: dist\LocalAIAgent\LocalAIAgent.exe
  pause
  exit /b 0
)

echo [6/6] Building the installer...
"%ISCC%" installer.iss
if errorlevel 1 goto error

echo.
echo ============================================
echo  DONE
echo ============================================
echo  Application: dist\LocalAIAgent\LocalAIAgent.exe
echo  Installer:   installer\LocalAIAgent_Setup.exe
echo.
echo  Для Android: соберите APK отдельно - android_app\build_apk.bat
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] Build failed. Read the message above this line.
pause
exit /b 1

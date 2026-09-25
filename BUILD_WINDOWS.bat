@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call SETUP_WINDOWS.bat
if errorlevel 1 goto error
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto error
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
"%ISCC%" installer.iss
if errorlevel 1 goto error
echo Ready: installer\LocalAIAgent_Setup.exe + LocalAIAgent_Setup-*.bin (distribute them together)
exit /b 0
:error
echo Build failed. Review output above.
exit /b 1

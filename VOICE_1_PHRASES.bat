@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem Step 1 of the voice studio: build phrases.txt (everything the Agent says aloud).
set "PY="
if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if not defined PY if exist venv\Scripts\python.exe set "PY=venv\Scripts\python.exe"
if not defined PY set "PY=py -3"
if not exist voice_work mkdir voice_work
%PY% scripts\voice\make_phrases.py --out voice_work\phrases.txt
if errorlevel 1 (
  echo.
  echo Could not build phrases.txt. Install Python 3.12 from python.org, or run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
echo.
echo Done: voice_work\phrases.txt
echo Next: open it in Notepad, delete lines you do not like, then upload the file to Google Drive,
echo folder "andrey_voice". Full guide: docs\VOICE_STUDIO.md
start "" explorer "%CD%\voice_work"
pause
exit /b 0

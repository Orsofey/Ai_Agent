@echo off
setlocal
cd /d "%~dp0"
py -3.12 -c "import sys" >nul 2>&1
if errorlevel 1 (
  py -3.11 scripts\build_android.py
) else (
  py -3.12 scripts\build_android.py
)
exit /b %errorlevel%

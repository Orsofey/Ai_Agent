@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem Checks the phone page in the Safari engine (WebKit): iPhone 13, iPhone SE, iPad and Safari on Mac.
rem No Mac, iPhone or Apple ID needed. Screenshots go to build\iphone-check. Details: docs\MAC_IPHONE_TESTING.md
if not exist .venv\Scripts\python.exe call SETUP_WINDOWS.bat
if not exist .venv\Scripts\python.exe goto error
set "PYTHONIOENCODING=utf-8"
echo Installing the Safari engine (WebKit) once, about 100 MB...
.venv\Scripts\python.exe -m playwright install webkit
if errorlevel 1 goto error
echo Checking iPhone, iPhone SE, iPad and Mac Safari...
.venv\Scripts\python.exe scripts\check_phone_page.py --out build\iphone-check
set "RESULT=%errorlevel%"
start "" "%~dp0build\iphone-check"
if not "%RESULT%"=="0" goto error
echo.
echo All good: the page works in the Safari engine on iPhone, iPad and Mac.
pause
exit /b 0
:error
echo.
echo Something is wrong - see the lines with a cross above and the screenshots in build\iphone-check.
pause
exit /b 1

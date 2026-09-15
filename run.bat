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
echo  Local AI Agent - запуск из исходников
echo ============================================
echo.

if not defined PYTHON (
  echo [ERROR] Python не найден.
  echo Установите Python 3.11-3.13 с python.org и включите "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist venv (
  echo [1/3] Создание виртуального окружения...
  "!PYTHON!" -m venv venv
  if errorlevel 1 (
    echo [ERROR] Не удалось создать venv.
    pause
    exit /b 1
  )
) else (
  echo [1/3] Виртуальное окружение уже есть.
)

call venv\Scripts\activate.bat

echo [2/3] Установка зависимостей...
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo [ERROR] Не удалось установить зависимости.
  pause
  exit /b 1
)

echo [3/3] Запуск...
echo.
python main.py

pause
exit /b 0

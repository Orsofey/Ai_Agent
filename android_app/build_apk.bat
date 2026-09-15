@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  Local AI Agent - Android APK builder
echo ============================================
echo.

where flutter >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Flutter not found in PATH.
  echo.
  echo Установите Flutter:
  echo   1. Скачайте: https://docs.flutter.dev/get-started/install/windows
  echo   2. Распакуйте в C:\flutter
  echo   3. Добавьте C:\flutter\bin в PATH
  echo   4. Установите Android Studio: https://developer.android.com/studio
  echo   5. Перезапустите это окно и запустите снова
  echo.
  pause
  exit /b 1
)

echo [1/4] Flutter найден. Проверка окружения...
flutter doctor
echo.

echo [2/4] Получение зависимостей...
call flutter pub get
if errorlevel 1 goto error

echo [3/4] Сборка release APK...
call flutter build apk --release
if errorlevel 1 goto error

echo [4/4] Готово!
echo.
echo ============================================
echo  APK: android_app\build\app\outputs\flutter-apk\app-release.apk
echo ============================================
echo.
echo Скопируйте APK на телефон и установите
echo (разрешите установку из неизвестных источников).
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] Сборка не удалась. Прочитайте сообщение выше.
pause
exit /b 1

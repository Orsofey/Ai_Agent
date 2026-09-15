@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  Local AI Agent - Android APK Builder
echo ============================================
echo.

REM Переходим в папку android_app где находится pubspec.yaml
cd android_app

where flutter >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Flutter not found.
  echo.
  echo Установите Flutter:
  echo   1. Скачайте: https://flutter.dev/docs/get-started/install/windows
  echo   2. Распакуйте в C:\flutter
  echo   3. Добавьте C:\flutter\bin в PATH переменную окружения
  echo   4. Перезагрузитесь или откройте новое окно командной строки
  echo   5. Проверьте: flutter --version
  echo.
  pause
  exit /b 1
)

echo [1/4] Проверка окружения...
flutter doctor
echo.

echo [2/4] Получение зависимостей (flutter pub get)...
call flutter pub get
if errorlevel 1 (
  echo [ERROR] Ошибка при получении зависимостей.
  echo Убедитесь, что интернет подключен и ~/.pub-cache доступен.
  pause
  exit /b 1
)
echo.

echo [3/4] Сборка release APK (это может занять 5-15 минут)...
call flutter build apk --release
if errorlevel 1 (
  echo [ERROR] Сборка не удалась.
  echo Прочитайте ошибку выше и повторите попытку.
  pause
  exit /b 1
)
echo.

echo ============================================
echo  ГОТОВО!
echo ============================================
echo.
if exist "build\app\outputs\flutter-apk\app-release.apk" (
  echo APK файл успешно создан:
  echo   C:\OS\Ai_Agent\android_app\build\app\outputs\flutter-apk\app-release.apk
  echo.
  echo Размер файла:
  for %%A in ("build\app\outputs\flutter-apk\app-release.apk") do echo   %%~zA байт
  echo.
) else (
  echo [WARNING] APK файл не найден. Проверьте вывод выше на ошибки.
  echo.
)

echo Установка на телефон:
echo   1. Скопируйте APK на телефон через USB
echo   2. Откройте файл на телефоне
echo   3. Android спросит разрешение - нажмите "Установить"
echo.
echo Или прямая установка по USB (если телефон подключен):
echo   cd android_app
echo   flutter install
echo.
pause
exit /b 0

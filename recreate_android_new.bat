@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  Recreating Android Gradle Project
echo ============================================
echo.

REM Создаём новый Flutter проект с правильным Android
echo [1/5] Creating new Flutter project with proper Gradle...
flutter create --platforms=android --org=com.localaiagent temp_flutter_new

if not exist temp_flutter_new (
  echo [ERROR] Failed to create new project
  pause
  exit /b 1
)

echo [2/5] Backing up your Dart code...
REM Копируем Dart код
if exist android_app\lib (
  echo   - Copying lib folder...
  xcopy android_app\lib temp_flutter_new\lib /E /I /Y >nul 2>&1
)

echo [3/5] Backing up assets and pubspec...
REM Копируем pubspec и assets
if exist android_app\pubspec.yaml (
  echo   - Copying pubspec.yaml...
  copy android_app\pubspec.yaml temp_flutter_new\pubspec.yaml /Y >nul 2>&1
)
if exist android_app\assets (
  echo   - Copying assets folder...
  xcopy android_app\assets temp_flutter_new\assets /E /I /Y >nul 2>&1
)

echo [4/5] Installing dependencies in new project...
cd temp_flutter_new
call flutter pub get
cd ..

echo [5/5] Replacing old Android with new one...
REM Удаляем старый Android
echo   - Removing old android folder...
rmdir /s /q android_app\android >nul 2>&1
REM Копируем новый Android
echo   - Copying new android folder...
xcopy temp_flutter_new\android android_app\android /E /I /Y >nul 2>&1

REM Чистим временный проект
echo   - Cleaning temporary files...
rmdir /s /q temp_flutter_new >nul 2>&1

echo.
echo ============================================
echo  SUCCESS! Android project recreated.
echo ============================================
echo.
echo Now build APK:
echo   cd android_app
echo   flutter clean
echo   flutter pub get
echo   flutter build apk --release
echo.
pause

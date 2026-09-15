@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  Recreating Android Gradle Project
echo ============================================
echo.

REM Создаём новый Flutter проект с правильным Android
echo [1/3] Creating new Flutter project with proper Gradle...
flutter create --platforms=android --org=com.localaiagent temp_flutter_rebuild

if not exist temp_flutter_rebuild (
  echo [ERROR] Failed to create new project
  pause
  exit /b 1
)

echo [2/3] Backing up your app files...
REM Копируем важные файлы
if exist android_app\lib (
  xcopy android_app\lib temp_flutter_rebuild\lib /E /I /Y >nul
)
if exist android_app\pubspec.yaml (
  copy android_app\pubspec.yaml temp_flutter_rebuild\pubspec.yaml /Y >nul
)
if exist android_app\assets (
  xcopy android_app\assets temp_flutter_rebuild\assets /E /I /Y >nul
)

echo [3/3] Replacing old Android with new one...
REM Удаляем старый Android
rmdir /s /q android_app\android >nul 2>&1
REM Копируем новый Android
xcopy temp_flutter_rebuild\android android_app\android /E /I /Y >nul

REM Чистим временный проект
rmdir /s /q temp_flutter_rebuild >nul 2>&1

echo.
echo ============================================
echo  DONE! Android project recreated.
echo ============================================
echo.
echo Now run:
echo   cd android_app
echo   flutter pub get
echo   flutter build apk --release
echo.
pause

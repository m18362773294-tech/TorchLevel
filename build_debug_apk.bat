@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==== assembleDebug ====
call gradlew.bat --no-daemon :app:assembleDebug

if errorlevel 1 (
  echo.
  echo 构建失败：把本窗口最后 50 行发我，我按报错点位修。
  pause
  exit /b 1
)

echo.
echo 构建成功 ✅ APK 路径：
echo %cd%\app\build\outputs\apk\debug\app-debug.apk
echo.
pause
endlocal

@echo off
setlocal
cd /d "%~dp0.."
if exist "%~dp0board_sync.py" (
  python -m capture_studio.portable_connect
  if errorlevel 1 pause
  exit /b 0
)
if exist "%~dp0release\CaptureStudio\CaptureStudio.exe" (
  start "" "%~dp0release\CaptureStudio\CaptureStudio.exe" --connect
  exit /b 0
)
if exist "%~dp0dist\CaptureStudio\CaptureStudio.exe" (
  start "" "%~dp0dist\CaptureStudio\CaptureStudio.exe" --connect
  exit /b 0
)
python -m capture_studio.portable_connect
if errorlevel 1 pause
endlocal

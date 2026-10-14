@echo off
setlocal
cd /d "%~dp0.."
for %%I in ("%~dp0.") do set "PKG=%%~nxI"
if exist "%~dp0board_sync.py" (
  python -m %PKG%
  if errorlevel 1 pause
  exit /b 0
)
if exist "%~dp0release\BoardCaptureStudio\BoardCaptureStudio.exe" (
  start "" "%~dp0release\BoardCaptureStudio\BoardCaptureStudio.exe" --connect
  exit /b 0
)
if exist "%~dp0dist\BoardCaptureStudio\BoardCaptureStudio.exe" (
  start "" "%~dp0dist\BoardCaptureStudio\BoardCaptureStudio.exe" --connect
  exit /b 0
)
python -m %PKG%.portable_connect
if errorlevel 1 pause
endlocal

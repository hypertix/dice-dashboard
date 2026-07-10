@echo off
rem DICE bench dashboard - first-time setup
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from https://www.python.org/downloads/
  echo   ^(check "Add python.exe to PATH" during install^)
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
echo.
echo Done. Start the dashboard with run.bat
pause

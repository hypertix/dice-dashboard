@echo off
rem DICE bench dashboard - http://localhost:8765
rem exit code 3 = self-update requested restart
cd /d %~dp0
:start
python -m server.app %*
if %errorlevel%==3 goto start
echo.
echo [Server stopped]
echo If it exited immediately, another instance may already be running.
echo Check http://localhost:8765 in your browser first.
pause

@echo off
rem DICE bench dashboard - http://localhost:8765
cd /d %~dp0
python -m server.app %*
echo.
echo [Server stopped]
echo If it exited immediately, another instance may already be running.
echo Check http://localhost:8765 in your browser first.
pause

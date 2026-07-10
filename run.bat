@echo off
rem DICE 벤치 대시보드 실행 — http://localhost:8765
cd /d %~dp0
python -m server.app %*

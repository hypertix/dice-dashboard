@echo off
rem DICE 벤치 대시보드 실행 — http://localhost:8765
cd /d %~dp0
python -m server.app %*
echo.
echo [서버가 종료되었습니다]
echo 시작하자마자 이 메시지가 떴다면: 이미 다른 인스턴스가 실행 중일 수 있습니다.
echo 브라우저에서 http://localhost:8765 를 먼저 확인해 보세요.
pause

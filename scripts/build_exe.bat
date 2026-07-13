@echo off
rem DiceDashboard.exe 로컬 빌드 -> dist\DiceDashboard.exe
rem (릴리스 배포는 태그 push 로 GitHub Actions 가 자동 수행)
cd /d %~dp0\..
python -m pip install -q pyinstaller -r requirements.txt
python -m PyInstaller --clean --noconfirm DiceDashboard.spec
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
echo.
echo OK: dist\DiceDashboard.exe

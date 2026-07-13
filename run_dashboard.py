# -*- coding: utf-8 -*-
"""PyInstaller 단일 exe 진입점 — 소스 실행은 run.bat(python -m server.app) 사용."""
from server.app import main

if __name__ == "__main__":
    main()

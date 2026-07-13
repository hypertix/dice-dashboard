# -*- coding: utf-8 -*-
"""실행 형태별 경로 — 소스 실행(git 사본)과 PyInstaller 단일 exe 를 구분.

RES_DIR  읽기 전용 리소스(static/) 위치. exe 는 PyInstaller 가 임시 폴더에
         풀어놓은 번들(sys._MEIPASS), 소스 실행은 레포 루트.
APP_DIR  쓰기 가능한 작업 위치(config.json, logs/). exe 는 exe 가 있는 폴더,
         소스 실행은 레포 루트 — 기존 동작과 동일.
"""
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))

if FROZEN:
    RES_DIR = sys._MEIPASS
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RES_DIR = _ROOT
    APP_DIR = _ROOT

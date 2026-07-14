# -*- coding: utf-8 -*-
"""대시보드 버전 — 단일 exe 배포의 기준.

릴리스 절차: 이 값을 올리고 커밋 → 같은 값의 태그(v1.0.0)를 push 하면
GitHub Actions 가 exe 를 빌드해 Release 에 첨부한다 (태그≠버전이면 빌드 실패).
"""
__version__ = "1.1.0"

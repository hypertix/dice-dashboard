# -*- coding: utf-8 -*-
"""CI 용 — 릴리스 태그와 server/version.py 의 __version__ 일치 검사."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.version import __version__  # noqa: E402

tag = os.environ.get("GITHUB_REF_NAME", "")
if tag != "v" + __version__:
    sys.exit(f"태그 {tag} != 코드 버전 v{__version__} — server/version.py 를 갱신하고 다시 태그하세요")
print(f"version OK: {tag}")

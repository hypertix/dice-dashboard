# -*- mode: python ; coding: utf-8 -*-
# 단일 exe 빌드:  pyinstaller --clean --noconfirm DiceDashboard.spec
# 산출물:         dist/DiceDashboard.exe  (static/ 내장, 콘솔 창 표시)
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["run_dashboard.py"],
    datas=[("static", "static")],
    hiddenimports=[
        # uvicorn 은 프로토콜 구현을 문자열로 동적 import 한다
        "uvicorn.logging",
        "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols", "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
    ] + collect_submodules("websockets"),
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="DiceDashboard",
    console=True,
    upx=False,
)

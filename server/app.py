# -*- coding: utf-8 -*-
"""DICE 벤치 대시보드 서버.

실행:  DiceDashboard.exe (담당자) 또는 python -m server.app / run.bat (개발자)
접속:  브라우저  http://localhost:8765
       AI/스크립트  GET  /api/state          — 전체 상태 스냅샷 (JSON)
                    POST /api/event          — 진행사항 타임라인에 이벤트 기록
                    POST /api/cmd            — DICE 제어 (HV/파형/시작/정지/ESTOP)
                    GET  /api/fw/check       — dice-ota 최신 릴리스 조회
                    POST /api/fw/apply       — 릴리스 다운로드 → J-Link 플래시
                    GET  /api/update/check   — 대시보드 자체 업데이트 확인
                    POST /api/update/apply   — 적용+재시작 (exe=Release / 소스=git)
                    WS   /ws                 — 실시간 delta push (5 Hz)
"""
import asyncio
import json
import os
import struct
import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import console_tail, dice_link, fw_update, jlink_watch, self_update
from .paths import APP_DIR, FROZEN, RES_DIR
from .state import AppState

CONFIG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULT_CONFIG = {
    "http_port": 8765,
    "console_port": None,        # null = SEGGER VID 로 자동 감지
    "console_baud": 115200,
    "dice_port": None,           # null = NXP VID 로 자동 감지
    "jlink_exe": r"C:\Program Files\SEGGER\JLink_V926\JLink.exe",
    "jlink_poll_sec": 3,
    "ota_repo": "hypertix/dice-ota",
    "dashboard_repo": "hypertix/dice-dashboard",   # exe 자기 업데이트 Release 레포
    "github_token": None,        # 레포가 private 일 때만 필요
}

WAVE_NAME = {0: "사인", 1: "구형", 2: "톱니", 3: "펄스", 4: "임의"}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


cfg = load_config()
state = AppState(os.path.join(APP_DIR, "logs"))
link = None                      # DiceLink — lifespan 에서 생성


@asynccontextmanager
async def lifespan(_app):
    global link
    state.version = self_update.current_version()
    jlink_watch.start(state, cfg)
    console_tail.start(state, cfg)
    link = dice_link.start(state, cfg)
    state.add_event("dashboard", "info", f"대시보드 시작 (버전 {state.version})")
    if FROZEN:                       # 창 없는 exe: 서버 수명 = 브라우저 탭
        asyncio.create_task(_auto_exit_watch())
    yield


app = FastAPI(title="DICE Bench Dashboard", lifespan=lifespan)

# ---- 창 없는 exe 수명 관리 (실행=자동 오픈, 탭 닫으면=자동 종료) ----
_ws_clients = 0                  # 현재 열린 브라우저 탭(WS) 수
_had_client = False              # 세션 중 한 번이라도 브라우저가 붙었는지
_last_activity = time.time()     # 마지막 HTTP 요청 시각 (스크립트 REST 사용 보호)


@app.middleware("http")
async def _touch_activity(request, call_next):
    global _last_activity
    _last_activity = time.time()
    return await call_next(request)


async def _auto_exit_watch():
    """마지막 브라우저 탭이 닫히면 자동 종료.

    - 새로고침/재접속은 수 초 안에 WS 가 다시 붙으므로 10초 유예로 구분한다.
    - REST 만 쓰는 스크립트(verify_fw.py 등)가 돌고 있으면 종료하지 않는다.
    - 브라우저가 아예 안 붙은 채 3분이 지나면 고아 프로세스 방지로 종료한다.
    """
    zero_since = None
    while True:
        await asyncio.sleep(2)
        now = time.time()
        if _ws_clients > 0:
            zero_since = None
            continue
        if zero_since is None:
            zero_since = now
        idle = now - _last_activity
        if _had_client and now - zero_since > 10 and idle > 10:
            state.add_event("dashboard", "info", "브라우저 종료 감지 — 서버 자동 종료")
            os._exit(0)
        if not _had_client and idle > 180:
            os._exit(0)


@app.get("/api/state")
async def api_state():
    return state.snapshot()


class EventIn(BaseModel):
    source: str = "script"
    level: str = "info"          # info | warn | error
    message: str


@app.post("/api/event")
async def api_event(ev: EventIn):
    """외부 스크립트(자동 검증 루프 등)가 진행사항 타임라인에 기록하는 입구."""
    state.add_event(ev.source, ev.level, ev.message)
    return {"ok": True}


# ---- DICE 제어 (② 제어 패널) ----
class CmdIn(BaseModel):
    action: str                  # hv | start | stop | estop | waveform
    on: bool = True              # hv 용
    mask: int = 0x0F             # start/stop 채널 마스크 (bit0=CH1)
    ch: int = 1                  # waveform 용 (1~4)
    type: int = 0                # 0=사인 1=구형 2=톱니 3=펄스 4=임의
    freq_hz: float = 1000.0
    amp_ma: float = 5.0
    phase_deg: float = 0.0
    cycles: int = 0              # 0=연속


@app.post("/api/cmd")
async def api_cmd(c: CmdIn):
    if link is None or not link.ser:
        return JSONResponse({"ok": False, "error": "DICE USB CDC 미연결"}, status_code=409)
    if c.action == "hv":
        ok = link.send(0x13, bytes([1 if c.on else 0]))
        desc = f"HV {'ON' if c.on else 'OFF'}"
    elif c.action == "start":
        ok = link.send(0x11, bytes([c.mask & 0x0F]))
        desc = f"OUT_START mask={c.mask & 0x0F:04b}"
    elif c.action == "stop":
        ok = link.send(0x12, bytes([c.mask & 0x0F]))
        desc = f"OUT_STOP mask={c.mask & 0x0F:04b}"
    elif c.action == "estop":
        ok = link.send(0x17)
        desc = "ESTOP"
    elif c.action == "waveform":
        if not (1 <= c.ch <= 4 and 0 <= c.type <= 4 and 0 < c.freq_hz <= 200000
                and 0 <= c.amp_ma <= 62 and c.cycles >= 0):
            return JSONResponse({"ok": False, "error": "파라미터 범위 초과"}, status_code=400)
        args = struct.pack("<BBIIHI", c.ch - 1, c.type,
                           int(c.freq_hz * 1000), int(c.amp_ma * 1000),
                           int(c.phase_deg * 100) % 36000, c.cycles)
        ok = link.send(0x10, args)
        desc = (f"SET_WAVEFORM CH{c.ch} {WAVE_NAME.get(c.type, c.type)} "
                f"{c.freq_hz:g}Hz {c.amp_ma:g}mA {c.phase_deg:g}°"
                + (f" ×{c.cycles}" if c.cycles else ""))
    else:
        return JSONResponse({"ok": False, "error": f"알 수 없는 action: {c.action}"},
                            status_code=400)
    state.add_event("control", "info" if ok else "error",
                    ("TX " if ok else "송신 실패 ") + desc)
    return {"ok": ok}


# ---- 펌웨어 업데이트 (dice-ota 릴리스 → J-Link) ----
@app.get("/api/fw/check")
async def api_fw_check():
    return await asyncio.to_thread(fw_update.check, cfg)


class FwApplyIn(BaseModel):
    tag: str
    asset_name: str
    asset_url: str


@app.post("/api/fw/apply")
async def api_fw_apply(a: FwApplyIn):
    if state.badges["jlink"]["state"] != "connected":
        return JSONResponse({"ok": False, "error": "J-Link(MCU-Link) 미연결 — 플래시 불가"},
                            status_code=409)
    started = fw_update.apply_async(state, cfg,
                                    {"name": a.asset_name, "url": a.asset_url}, a.tag)
    if not started:
        return JSONResponse({"ok": False, "error": "이미 업데이트 진행 중"}, status_code=409)
    return {"ok": True}


# ---- 대시보드 자기 업데이트 (exe=Release 다운로드+교체 / 소스=git pull) ----
@app.get("/api/update/check")
async def api_update_check():
    return await asyncio.to_thread(self_update.check, state, cfg)


@app.post("/api/update/apply")
async def api_update_apply():
    return await asyncio.to_thread(self_update.apply, state, cfg)


@app.websocket("/ws")
async def ws(sock: WebSocket):
    global _ws_clients, _had_client
    await sock.accept()
    _ws_clients += 1
    _had_client = True
    try:
        snap = state.snapshot()
        await sock.send_text(json.dumps({"t": "snap", **snap}, ensure_ascii=False))
        cursor = snap["cursor"]
        while True:
            await asyncio.sleep(0.2)
            delta = state.delta_since(cursor)
            cursor = delta["cursor"]
            await sock.send_text(json.dumps({"t": "delta", **delta}, ensure_ascii=False))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _ws_clients -= 1


@app.get("/")
async def index():
    """정적 리소스 URL 에 버전 쿼리를 심어 브라우저 캐시 무효화(?v=버전)."""
    with open(os.path.join(RES_DIR, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html.replace("{{v}}", state.version))


app.mount("/static", StaticFiles(directory=os.path.join(RES_DIR, "static")), name="static")


def main():
    # 창 없는 exe 모드: 콘솔이 없어 stdout/stderr 가 없으므로 서버 로그를 파일로
    if sys.stdout is None or sys.stderr is None:
        f = open(os.path.join(APP_DIR, "logs", "server.log"), "a",
                 buffering=1, encoding="utf-8", errors="replace")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f

    import socket
    import webbrowser
    url = f"http://localhost:{cfg['http_port']}"
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", cfg["http_port"]))
    except OSError:                  # 이미 실행 중 — 브라우저만 열고 조용히 종료
        webbrowser.open(url)
        return
    finally:
        probe.close()

    # exe 더블클릭 UX: 서버가 뜨면 브라우저 자동 오픈 (자기 업데이트 재시작은 제외)
    if FROZEN and "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn
    print(f"DICE 벤치 대시보드 {self_update.current_version()}: {url}  (Ctrl+C = 종료)")
    uvicorn.run(app, host="127.0.0.1", port=cfg["http_port"], log_level="warning")


if __name__ == "__main__":
    main()

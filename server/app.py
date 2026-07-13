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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import console_tail, dice_link, fw_update, jlink_watch, self_update
from .paths import APP_DIR, RES_DIR
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
app = FastAPI(title="DICE Bench Dashboard")
link = None                      # DiceLink — startup 에서 생성


@app.on_event("startup")
async def startup():
    global link
    state.version = self_update.current_version()
    jlink_watch.start(state, cfg)
    console_tail.start(state, cfg)
    link = dice_link.start(state, cfg)
    state.add_event("dashboard", "info", f"대시보드 시작 (버전 {state.version})")


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
    await sock.accept()
    snap = state.snapshot()
    await sock.send_text(json.dumps({"t": "snap", **snap}, ensure_ascii=False))
    cursor = snap["cursor"]
    try:
        while True:
            await asyncio.sleep(0.2)
            delta = state.delta_since(cursor)
            cursor = delta["cursor"]
            await sock.send_text(json.dumps({"t": "delta", **delta}, ensure_ascii=False))
    except (WebSocketDisconnect, RuntimeError):
        pass


@app.get("/")
async def index():
    return FileResponse(os.path.join(RES_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(RES_DIR, "static")), name="static")


def main():
    import uvicorn
    print(f"DICE 벤치 대시보드 {self_update.current_version()}: "
          f"http://localhost:{cfg['http_port']}  (Ctrl+C = 종료)")
    uvicorn.run(app, host="127.0.0.1", port=cfg["http_port"], log_level="warning")


if __name__ == "__main__":
    main()

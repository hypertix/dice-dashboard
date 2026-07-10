# -*- coding: utf-8 -*-
"""DICE 벤치 대시보드 서버.

실행:  python -m server.app   (또는 run.bat)
접속:  브라우저  http://localhost:8765
       AI/스크립트  GET  /api/state          — 전체 상태 스냅샷 (JSON)
                    POST /api/event          — 진행사항 타임라인에 이벤트 기록
                    WS   /ws                 — 실시간 delta push (5 Hz)
"""
import asyncio
import json
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import console_tail, dice_link, jlink_watch
from .state import AppState

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULT_CONFIG = {
    "http_port": 8765,
    "console_port": None,        # null = SEGGER VID 로 자동 감지
    "console_baud": 115200,
    "dice_port": None,           # null = NXP VID 로 자동 감지
    "jlink_exe": r"C:\Program Files\SEGGER\JLink_V926\JLink.exe",
    "jlink_poll_sec": 5,
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


cfg = load_config()
state = AppState(os.path.join(ROOT, "logs"))
app = FastAPI(title="DICE Bench Dashboard")


@app.on_event("startup")
async def startup():
    jlink_watch.start(state, cfg)
    console_tail.start(state, cfg)
    dice_link.start(state, cfg)
    state.add_event("dashboard", "info", "대시보드 시작")


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
    return FileResponse(os.path.join(ROOT, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=cfg["http_port"], log_level="warning")

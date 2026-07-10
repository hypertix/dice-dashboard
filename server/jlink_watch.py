# -*- coding: utf-8 -*-
"""J-Link 프로브 연결 감시 — USB 열거(pyserial)로만 감지.

JLink.exe 를 실행하지 않는다: J-Link 는 한 프로세스만 잡을 수 있어서
폴링용 JLink.exe 가 IDE 디버그 세션이나 CLI 플래시(verify_fw.py)와
프로브 점유 경합을 일으킨다 (실측 2026-07-10 — 플래시가
"SWD is not supported" 로 오탐 실패). 프로브의 CDC 포트(SEGGER VID 0x1366)
존재 여부 + USB serial number 로 대체 — 부작용 0.
"""
import threading
import time

from serial.tools import list_ports

from .state import AppState

SEGGER_VID = 0x1366


def _query() -> list:
    """USB 에 붙은 SEGGER 프로브 시리얼 목록 (CDC 포트 기준)."""
    serials = set()
    for p in list_ports.comports():
        if p.vid == SEGGER_VID:
            serials.add(p.serial_number or "?")
    return sorted(serials)


def start(state: AppState, cfg: dict) -> threading.Thread:
    interval = cfg.get("jlink_poll_sec", 3)

    def run():
        while True:
            serials = _query()
            if serials:
                state.set_badge("jlink", state="connected", serials=serials, detail="")
            else:
                state.set_badge("jlink", state="disconnected", serials=[], detail="")
            time.sleep(interval)

    t = threading.Thread(target=run, name="jlink_watch", daemon=True)
    t.start()
    return t

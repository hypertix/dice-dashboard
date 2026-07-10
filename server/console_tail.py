# -*- coding: utf-8 -*-
"""UART 디버그 콘솔(FC3 → MCU-Link VCOM, 115200) tail 스레드.

포트가 없거나 다른 프로그램(터미널/IDE)이 점유 중이면 배지에 표시하고
3 초 간격으로 재시도한다 — 포트를 뺏지 않는다.
"""
import threading
import time

import serial

from . import ports
from .state import AppState

# 콘솔 로그에서 이벤트 승격할 패턴 (진행사항 타임라인에 자동 기록)
_PATTERNS = [
    ("PASS", "info"),
    ("FAIL", "error"),
    ("ERROR", "error"),
    ("frames dropped", "warn"),
    ("Malloc failed", "error"),
    ("stack overflow", "error"),
]


def start(state: AppState, cfg: dict) -> threading.Thread:
    def run():
        buf = bytearray()
        while True:
            port, _, plist = ports.autodetect(cfg)
            state.set_ports(plist)
            if not port:
                state.set_badge("console", state="absent", port=None,
                                detail="MCU-Link VCOM(COM 포트) 없음")
                time.sleep(3)
                continue
            try:
                ser = serial.Serial(port, cfg.get("console_baud", 115200), timeout=0.2)
            except serial.SerialException as e:
                busy = "PermissionError" in str(e) or "denied" in str(e).lower()
                state.set_badge("console", state="busy" if busy else "error", port=port,
                                detail="다른 프로그램이 점유 중" if busy else str(e))
                time.sleep(3)
                continue

            state.set_badge("console", state="open", port=port, detail="")
            buf.clear()
            try:
                while True:
                    data = ser.read(1024)
                    if data:
                        buf += data
                        while b"\n" in buf:
                            line, _, rest = bytes(buf).partition(b"\n")
                            buf[:] = rest
                            text = line.decode("utf-8", errors="replace").rstrip("\r")
                            if not text:
                                continue
                            state.add_console_line(text)
                            for pat, lv in _PATTERNS:
                                if pat in text:
                                    state.add_event("console", lv, text)
                                    break
            except serial.SerialException:
                state.set_badge("console", state="disconnected", port=port,
                                detail="포트 끊김 — 재시도")
                try:
                    ser.close()
                except Exception:
                    pass
                time.sleep(2)

    t = threading.Thread(target=run, name="console_tail", daemon=True)
    t.start()
    return t

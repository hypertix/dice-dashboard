# -*- coding: utf-8 -*-
"""LCD(RK3566, dice_lcd) 연동 — adb 네트워크로 스크린샷 주기 캡처.

LCD 가 USB CDC 를 소유한 통합 테스트 중에도 "지금 LCD 화면에 뭐가 떠 있는지"를
대시보드에서 보기 위한 모듈. LCD 미연결이면 배지만 absent 로 두고 조용히 재시도.
"""
import subprocess
import threading
import time

from .state import AppState


def _run(args: list, timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout)


def start(state: AppState, cfg: dict) -> threading.Thread:
    adb = cfg.get("adb_exe", "adb")
    addr = cfg.get("lcd_addr", "192.168.50.78:5555")
    shot_sec = cfg.get("lcd_shot_sec", 5)

    def run():
        while True:
            try:
                # adb connect 는 멱등 — 이미 연결이면 "already connected"
                _run([adb, "connect", addr], timeout=8)
                r = _run([adb, "-s", addr, "get-state"], timeout=8)
                online = r.returncode == 0 and b"device" in r.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError):
                online = False
            if not online:
                state.set_badge("lcd", state="absent", addr=addr,
                                detail=f"adb {addr} 응답 없음 (LCD 미연결/전원 꺼짐)")
                time.sleep(10)
                continue

            state.set_badge("lcd", state="connected", addr=addr, detail="")
            try:
                r = _run([adb, "-s", addr, "exec-out", "screencap", "-p"], timeout=15)
                if r.returncode == 0 and r.stdout[:8].startswith(b"\x89PNG"):
                    state.set_lcd_png(r.stdout)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(shot_sec)

    t = threading.Thread(target=run, name="lcd_watch", daemon=True)
    t.start()
    return t

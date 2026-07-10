# -*- coding: utf-8 -*-
"""J-Link 프로브 연결 감시 — JLink.exe ShowEmuList 를 주기 폴링.

ShowEmuList 는 USB 열거만 하고 타겟에 연결하지 않으므로
MCUXpresso 디버그 세션과 병행해도 안전하다.
"""
import re
import subprocess
import threading
import time

from .state import AppState

_SERIAL_RE = re.compile(r"Serial number:\s*(\d+)")


def _query(jlink_exe: str) -> list:
    """연결된 J-Link 시리얼 목록. 실패 시 None (도구 문제와 미연결을 구분)."""
    try:
        # J-Link Commander 는 스크립트 없이 실행하면 stdin 에서 명령을 읽는다
        r = subprocess.run(
            [jlink_exe, "-NoGui", "1"],
            input="ShowEmuList USB\nExit\n",
            capture_output=True, text=True, timeout=15,
        )
        return _SERIAL_RE.findall(r.stdout)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def start(state: AppState, cfg: dict) -> threading.Thread:
    jlink_exe = cfg.get("jlink_exe", r"C:\Program Files\SEGGER\JLink_V926\JLink.exe")
    interval = cfg.get("jlink_poll_sec", 5)

    def run():
        while True:
            serials = _query(jlink_exe)
            if serials is None:
                state.set_badge("jlink", state="error", serials=[],
                                detail="JLink.exe 실행 실패 — config.json 의 jlink_exe 경로 확인")
            elif serials:
                state.set_badge("jlink", state="connected", serials=serials, detail="")
            else:
                state.set_badge("jlink", state="disconnected", serials=[], detail="")
            time.sleep(interval)

    t = threading.Thread(target=run, name="jlink_watch", daemon=True)
    t.start()
    return t

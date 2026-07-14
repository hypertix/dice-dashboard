# -*- coding: utf-8 -*-
"""UART 디버그 콘솔(FC3 → MCU-Link VCOM, 115200) tail 스레드.

포트가 없거나 다른 프로그램(터미널/IDE)이 점유 중이면 배지에 표시하고
3 초 간격으로 재시도한다 — 포트를 뺏지 않는다.

포트 선택 규칙:
- 기본은 자동 감지(SEGGER VID). 데이터를 한 번 받으면 그 포트에 고정.
- 무수신 상태면 5초마다 재스캔 — 현재 포트가 사라졌거나 후보가 여럿이면
  다음 후보로 순환하며 데이터가 나오는 포트를 찾는다.
- 브라우저 새로고침(WS 재접속) 시에도 무수신이면 즉시 재스캔한다.
- UI 배지 드롭다운으로 수동 고정 가능(/api/console/select) — 자동보다 우선,
  빈 값을 보내면 자동 감지로 복귀.
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


class Ctl:
    """tail 스레드에 대한 포트 선택 요청 (API/WS 핸들러에서 호출)."""

    def __init__(self):
        self.manual = None      # 수동 고정 포트, None = 자동 감지
        self.force_gen = 0      # 수동 선택 세대 — 수신 중이어도 즉시 포트 재선택
        self.soft_gen = 0       # 재스캔 요청 세대 — 무수신일 때만 반영

    def select(self, port) -> None:
        self.manual = port or None
        self.force_gen += 1

    def rescan(self) -> None:
        if self.manual is None:
            self.soft_gen += 1


def start(state: AppState, cfg: dict) -> Ctl:
    ctl = Ctl()

    def candidates() -> list:
        """지금 시도할 포트 후보 (우선순위: UI 수동 > config > SEGGER VID 자동)."""
        plist = ports.scan()
        state.set_ports(plist)
        if ctl.manual:
            return [ctl.manual]
        if cfg.get("console_port"):
            return [cfg["console_port"]]
        return [p["device"] for p in plist if p["vid"] == ports.SEGGER_VID]

    def run():
        buf = bytearray()
        idx = 0                          # 자동 모드 무수신 시 후보 순환 인덱스
        while True:
            f_seen, s_seen = ctl.force_gen, ctl.soft_gen
            cands = candidates()
            if not cands:
                state.set_badge("console", state="absent", port=None,
                                manual=ctl.manual,
                                detail="MCU-Link VCOM(COM 포트) 없음")
                time.sleep(3)
                continue
            port = cands[idx % len(cands)]
            try:
                ser = serial.Serial(port, cfg.get("console_baud", 115200), timeout=0.2)
            except serial.SerialException as e:
                busy = "PermissionError" in str(e) or "denied" in str(e).lower()
                state.set_badge("console", state="busy" if busy else "error", port=port,
                                manual=ctl.manual,
                                detail="다른 프로그램이 점유 중" if busy else str(e))
                idx += 1                 # 다음 후보도 시도해 본다
                time.sleep(3)
                continue

            # 포트 열림 = MCU-Link 프로브가 PC 에 있다는 뜻일 뿐, 보드 UART 가
            # 살아있다는 보장이 아니다 → 데이터를 받기 전까지는 "무수신"(노랑).
            state.set_badge("console", state="idle", port=port, last_rx=None,
                            manual=ctl.manual,
                            detail="포트 열림 — 수신 데이터 없음 (보드 전원/UART 배선 확인)")
            buf.clear()
            got_data = False
            last_rx_badge = 0.0
            last_scan = time.time()
            try:
                while True:
                    if ctl.force_gen != f_seen:
                        idx = 0          # 수동 선택 — 즉시 포트 다시 잡기
                        break
                    if ctl.soft_gen != s_seen and not got_data:
                        # 새로고침 재스캔: 후보가 지금 포트 하나뿐이면 닫지 않고
                        # 유지한다 (재오픈 갭 동안의 수신 유실 방지)
                        s_seen = ctl.soft_gen
                        c2 = candidates()
                        if port not in c2 or len(c2) > 1:
                            idx = 0
                            break
                    data = ser.read(1024)
                    if data:
                        got_data = True
                        now = time.time()
                        if now - last_rx_badge >= 1.0:    # 배지 갱신은 1초 스로틀
                            last_rx_badge = now
                            state.set_badge("console", state="open", port=port,
                                            last_rx=now, manual=ctl.manual, detail="")
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
                    elif not got_data and time.time() - last_scan >= 5.0:
                        # 무수신 지속: 포트 목록이 바뀌었거나 후보가 여럿이면
                        # 다음 후보로 옮겨가며 데이터가 나오는 포트를 찾는다
                        last_scan = time.time()
                        c2 = candidates()
                        if port not in c2 or len(c2) > 1:
                            idx += 1
                            break
            except serial.SerialException:
                state.set_badge("console", state="disconnected", port=port,
                                manual=ctl.manual, detail="포트 끊김 — 재시도")
                time.sleep(2)
            finally:
                try:
                    ser.close()
                except Exception:
                    pass

    threading.Thread(target=run, name="console_tail", daemon=True).start()
    return ctl

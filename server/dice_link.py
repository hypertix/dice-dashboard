# -*- coding: utf-8 -*-
"""DICE USB CDC 링크 — 가상 LCD 역할 스레드.

LCD(dice_lcd)가 하는 일을 대신한다:
- 접속 시 GET_INFO 로 펌웨어 버전 확인
- PING 하트비트 500 ms (계약 문서 4절)
- STATUS(10 Hz)/EVENT/RSP 수신 → 상태 저장소 기록
포트가 없으면(LCD 가 잡고 있거나 미연결) 배지에 표시하고 재시도.
"""
import struct
import threading
import time

import serial

from . import ports
from .dice_protocol import (CMD_GET_INFO, CMD_NAME, CMD_PING, CMD_SELFTEST,
                            FrameParser, RSP_NAME, TYPE_EVENT, TYPE_RSP,
                            TYPE_STATUS, encode_cmd, parse_event, parse_status)
from .state import AppState


class DiceLink:
    def __init__(self, state: AppState, cfg: dict):
        self.state = state
        self.cfg = cfg
        self.ser = None
        self.seq = 0
        self.lock = threading.Lock()   # 송신 직렬화 (추후 제어 API 대비)
        self.last_pong = 0.0           # 마지막 PING OK 수신 시각 → MCU 배지

    def send(self, cmd_id: int, args: bytes = b"") -> bool:
        with self.lock:
            if not self.ser:
                return False
            try:
                self.ser.write(encode_cmd(self.seq, cmd_id, args))
                self.seq = (self.seq + 1) & 0xFF
                return True
            except serial.SerialException:
                return False

    def _on_frame(self, typ: int, seq: int, pl: bytes) -> None:
        if typ == TYPE_STATUS:
            st = parse_status(pl)
            if st:
                self.state.add_status(st)
        elif typ == TYPE_EVENT:
            ev = parse_event(pl)
            if ev:
                self.state.add_event(
                    "dice", "warn",
                    f"EVENT code=0x{ev['code']:04X} ch={ev['ch']} value={ev['value']}")
        elif typ == TYPE_RSP and len(pl) >= 2:
            cmd, status = pl[0], pl[1]
            if cmd == CMD_PING and status == 0:
                self.last_pong = time.time()              # MCU 생존 신호
                return
            if cmd == CMD_SELFTEST:
                if status == 0 and len(pl) >= 4:
                    mask = pl[2] | (pl[3] << 8)           # bit=1 정상 (계약 7.1절)
                    st = {"dac": bool(mask & 1), "adc": bool(mask & 2), "raw": mask}
                    self.state.set_selftest(st)
                    self.state.add_event(
                        "dice", "info" if mask & 3 == 3 else "error",
                        f"자가진단: AD9106(DAC) {'OK' if st['dac'] else 'FAIL'}, "
                        f"ADS131(ADC) {'OK' if st['adc'] else 'FAIL'}")
                else:
                    self.state.set_selftest({"error": RSP_NAME.get(status, status)})
                    self.state.add_event("dice", "warn",
                                         f"자가진단 실패: {RSP_NAME.get(status, status)}")
                return
            if cmd == CMD_GET_INFO and status == 0 and len(pl) >= 7:
                info = {"fw": f"{pl[2]}.{pl[3]}.{pl[4]}", "hw": pl[5], "proto": pl[6]}
                self.state.set_fw_info(info)
                self.state.add_event("dice", "info", f"펌웨어 v{info['fw']} "
                                     f"(hw {info['hw']}, proto {info['proto']})")
                return
            name = CMD_NAME.get(cmd, hex(cmd))
            lv = "info" if status == 0 else "error"
            self.state.add_event("dice", lv,
                                 f"RSP {name}: {RSP_NAME.get(status, status)}")

    def run(self) -> None:
        while True:
            _, port, _ = ports.autodetect(self.cfg)
            if not port:
                self.state.set_badge("dice", state="absent", port=None,
                                     detail="DICE USB CDC 없음 (미연결 또는 LCD 가 소유)")
                self.state.set_badge("mcu", state="absent", detail="DICE USB CDC 미연결")
                time.sleep(3)
                continue
            try:
                self.ser = serial.Serial(port, 115200, timeout=0.05)
            except serial.SerialException as e:
                busy = "PermissionError" in str(e) or "denied" in str(e).lower()
                self.state.set_badge("dice", state="busy" if busy else "error", port=port,
                                     detail="다른 프로그램이 점유 중 (dice_host.py?)"
                                     if busy else str(e))
                self.ser = None
                time.sleep(3)
                continue

            self.state.set_badge("dice", state="open", port=port, detail="")
            parser = FrameParser()
            self.send(CMD_GET_INFO)
            self.send(CMD_SELFTEST)                       # LCD 상태 화면과 동일 진단
            self.last_pong = 0.0
            last_ping = 0.0
            last_mcu = 0.0
            try:
                while True:
                    now = time.time()
                    if now - last_ping >= 0.5:            # 하트비트 (문서 4절)
                        last_ping = now
                        if not self.send(CMD_PING):
                            raise serial.SerialException("write fail")
                    if now - last_mcu >= 1.0:             # MCU 배지 (PONG 신선도)
                        last_mcu = now
                        if now - self.last_pong < 2.0:
                            self.state.set_badge("mcu", state="connected",
                                                 detail="PING 하트비트 응답 정상")
                        else:
                            self.state.set_badge("mcu", state="no_pong",
                                                 detail="PING 응답 없음 — 펌웨어 미응답")
                    data = self.ser.read(4096)
                    for typ, seq, pl in parser.feed(data):
                        self._on_frame(typ, seq, pl)
                    time.sleep(0.005)
            except serial.SerialException:
                self.state.set_badge("dice", state="disconnected", port=port,
                                     detail="포트 끊김 — 재시도")
                self.state.set_badge("mcu", state="absent", detail="DICE USB CDC 끊김")
                self.state.set_selftest(None)
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
                time.sleep(2)


def start(state: AppState, cfg: dict) -> DiceLink:
    link = DiceLink(state, cfg)
    t = threading.Thread(target=link.run, name="dice_link", daemon=True)
    t.start()
    return link

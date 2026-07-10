# -*- coding: utf-8 -*-
"""DICE UI↔MCU 프로토콜 v0.1 프레이밍/파싱 (dice_RW612/tools/dice_host.py 에서 이식).

계약 문서: dice_RW612/docs/DICE_UI_MCU_Protocol_v0.1.md
프레임 = SOF(D1 CE) + type(1) + seq(1) + len(2,LE) + payload + CRC-16-CCITT(2,LE)
CRC 범위 = type..payload (SOF 제외).
"""
import struct

SOF = b"\xD1\xCE"

TYPE_CMD = 0x01
TYPE_RSP = 0x81
TYPE_STREAM = 0x02
TYPE_STATUS = 0x03
TYPE_EVENT = 0x04

RSP_NAME = {0: "OK", 1: "BAD_PARAM", 2: "DENIED", 3: "BUSY", 4: "HW_FAIL"}
CMD_NAME = {
    0x01: "PING", 0x02: "GET_INFO", 0x10: "SET_WAVEFORM", 0x11: "OUT_START",
    0x12: "OUT_STOP", 0x13: "HV_SWITCH", 0x14: "FAN", 0x15: "DAC_PWR",
    0x16: "ADC_PWR", 0x17: "ESTOP", 0x18: "HCC_ENABLE", 0x20: "ADC_CONFIG",
    0x21: "STREAM_START", 0x22: "STREAM_STOP", 0x30: "REG_READ",
    0x31: "REG_WRITE", 0x32: "SRAM_LOAD", 0x40: "SELFTEST",
    0x50: "DFU_BEGIN", 0x51: "DFU_DATA", 0x52: "DFU_END", 0x53: "DFU_APPLY",
    0x54: "DFU_ABORT", 0x55: "DFU_STATUS", 0x56: "DFU_CONFIRM",
}

CMD_PING = 0x01
CMD_GET_INFO = 0x02


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_cmd(seq: int, cmd_id: int, args: bytes = b"") -> bytes:
    """CMD 프레임 인코딩. seq 는 호출자가 0~255 순환 관리."""
    payload = bytes([cmd_id]) + args
    body = bytes([TYPE_CMD, seq & 0xFF]) + struct.pack("<H", len(payload)) + payload
    return SOF + body + struct.pack("<H", crc16_ccitt(body))


class FrameParser:
    """수신 바이트 스트림 → 프레임 리스트. SOF 재동기화 포함 (dice_host.pump 이식)."""

    def __init__(self):
        self.rx = bytearray()

    def feed(self, data: bytes):
        """데이터를 넣고 완성된 (type, seq, payload) 리스트를 반환."""
        frames = []
        if data:
            self.rx += data
        while True:
            i = self.rx.find(SOF)
            if i < 0:
                if len(self.rx) > 1:
                    del self.rx[:-1]
                return frames
            if i:
                del self.rx[:i]
            if len(self.rx) < 8:
                return frames
            ln = struct.unpack_from("<H", self.rx, 4)[0]
            if ln > 512:
                del self.rx[:1]
                continue
            total = 8 + ln
            if len(self.rx) < total:
                return frames
            body = bytes(self.rx[2:6 + ln])
            rx_crc = struct.unpack_from("<H", self.rx, total - 2)[0]
            if crc16_ccitt(body) == rx_crc:
                frames.append((body[0], body[1], body[4:]))
                del self.rx[:total]
            else:
                del self.rx[:1]


def parse_status(pl: bytes):
    """STATUS payload → dict. flags bit0=HV, bit4=STRM, bit8~11=RUN mask, meas=채널 RMS µA."""
    if len(pl) < 20:
        return None
    flags, alarm = struct.unpack_from("<HH", pl, 0)
    meas = list(struct.unpack_from("<4i", pl, 4))
    return {
        "flags": flags,
        "alarm": alarm,
        "hv": flags & 1,
        "strm": (flags >> 4) & 1,
        "run": (flags >> 8) & 0xF,
        "meas": meas,
    }


def parse_event(pl: bytes):
    """EVENT payload → dict (code, ch, value). ch 0xFF = SYS."""
    if len(pl) < 7:
        return None
    code, = struct.unpack_from("<H", pl, 0)
    ch = pl[2]
    val, = struct.unpack_from("<i", pl, 3)
    return {"code": code, "ch": "SYS" if ch == 0xFF else ch + 1, "value": val}

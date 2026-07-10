# -*- coding: utf-8 -*-
"""COM 포트 열거 및 역할 자동 감지.

- MCU-Link(J-Link 펌웨어) VCOM = SEGGER VID 0x1366 → UART 디버그 콘솔 (FC3, 115200)
- RW612 USB CDC (DICE 프로토콜)  = NXP VID 0x1FC9 → USB Serial Device
config.json 에서 명시하면 자동 감지보다 우선한다.
"""
from serial.tools import list_ports

SEGGER_VID = 0x1366
NXP_VID = 0x1FC9


def scan() -> list:
    out = []
    for p in list_ports.comports():
        out.append({
            "device": p.device,
            "vid": p.vid,
            "pid": p.pid,
            "desc": p.description,
        })
    return out


def autodetect(cfg: dict):
    """(console_port, dice_port, ports) 반환. 못 찾으면 None."""
    ports = scan()
    console = cfg.get("console_port")
    dice = cfg.get("dice_port")
    if not console:
        for p in ports:
            if p["vid"] == SEGGER_VID:
                console = p["device"]
                break
    if not dice:
        for p in ports:
            if p["vid"] == NXP_VID:
                dice = p["device"]
                break
    return console, dice, ports

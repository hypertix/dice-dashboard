# -*- coding: utf-8 -*-
"""LCD(RK3566, dice_lcd) 연동 — adb 로 프레임버퍼(/dev/fb0) 주기 캡처.

DWIN RK3566 은 Android 가 아니라 임베디드 Linux(eglfs Qt) 라서 screencap 이 없다.
대신 fbdev 에뮬레이션(/dev/fb0, 1024×600 32bpp BGRX)을 그대로 덤프해서
서버에서 PNG 로 변환한다 (실측 2026-07-10: 라이브 Qt 화면 확인됨).
패널이 뒤집혀 장착되어 있어 기본 180° 회전 (config lcd_rotate).
LCD 미연결이면 배지만 absent 로 두고 조용히 재시도.
"""
import io
import os
import subprocess
import tempfile
import threading
import time

from .state import AppState

try:
    from PIL import Image
except ImportError:                      # Pillow 없으면 배지 전용으로 동작
    Image = None


def _run(args: list, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout)


def _fb_geometry(adb: str, addr: str):
    """(width, height, bpp) — sysfs 에서 읽기. 실패 시 None."""
    r = _run([adb, "-s", addr, "shell",
              "cat /sys/class/graphics/fb0/virtual_size /sys/class/graphics/fb0/bits_per_pixel"])
    try:
        size_line, bpp_line = r.stdout.decode().split()[:2]
        w, h = (int(x) for x in size_line.split(","))
        return w, h, int(bpp_line)
    except (ValueError, IndexError):
        return None


def start(state: AppState, cfg: dict) -> threading.Thread:
    adb = cfg.get("adb_exe", "adb")
    addr = cfg.get("lcd_addr", "192.168.50.78:5555")
    shot_sec = cfg.get("lcd_shot_sec", 5)
    rotate = cfg.get("lcd_rotate", 180)

    def run():
        geom = None
        while True:
            try:
                _run([adb, "connect", addr], timeout=8)   # 멱등
                r = _run([adb, "-s", addr, "get-state"], timeout=8)
                online = r.returncode == 0 and b"device" in r.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError):
                online = False
            if not online:
                geom = None
                state.set_badge("lcd", state="absent", addr=addr,
                                detail=f"adb {addr} 응답 없음 (LCD 미연결/전원 꺼짐)")
                time.sleep(10)
                continue

            state.set_badge("lcd", state="connected", addr=addr, detail="")
            if Image is not None:
                try:
                    if geom is None:
                        geom = _fb_geometry(adb, addr)
                    if geom and geom[2] == 32:
                        w, h, _ = geom
                        # 이 보드의 adbd 는 exec-out 미지원("error: closed") —
                        # shell dd → pull 2단계로 덤프 (실측 검증된 경로)
                        local = os.path.join(tempfile.gettempdir(), "dice_lcd_fb.raw")
                        _run([adb, "-s", addr, "shell",
                              "dd if=/dev/fb0 of=/tmp/fb.raw bs=65536 2>/dev/null"],
                             timeout=15)
                        r = _run([adb, "-s", addr, "pull", "/tmp/fb.raw", local],
                                 timeout=20)
                        raw = b""
                        if r.returncode == 0 and os.path.exists(local):
                            with open(local, "rb") as f:
                                raw = f.read()
                        if len(raw) >= w * h * 4:
                            img = Image.frombuffer("RGB", (w, h),
                                                   raw[:w * h * 4], "raw", "BGRX")
                            if rotate:
                                img = img.rotate(rotate)
                            buf = io.BytesIO()
                            img.save(buf, "PNG", optimize=False)
                            state.set_lcd_png(buf.getvalue())
                except (subprocess.TimeoutExpired, OSError):
                    pass
            time.sleep(shot_sec)

    t = threading.Thread(target=run, name="lcd_watch", daemon=True)
    t.start()
    return t

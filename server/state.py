# -*- coding: utf-8 -*-
"""중앙 상태 저장소 — 수집 스레드들이 쓰고, HTTP/WS 가 읽는다.

모든 항목(콘솔 라인/이벤트/STATUS 포인트)에 전역 seq 를 부여해서
WS 클라이언트가 커서 기반 delta 수신을 할 수 있게 한다.
콘솔 라인과 이벤트는 logs/ 아래 파일로도 남긴다 (AI 사후 판독용).
"""
import json
import os
import threading
import time
from collections import deque


class AppState:
    def __init__(self, log_dir: str):
        self.lock = threading.Lock()
        self._seq = 0
        self.started_at = time.time()

        self.console = deque(maxlen=1000)     # (seq, ts, line)
        self.events = deque(maxlen=500)       # (seq, ts, source, level, msg)
        self.status_pts = deque(maxlen=1500)  # (seq, ts, status dict) — 10 Hz × 2.5분

        # 연결 배지 — 수집 스레드가 갱신
        self.badges = {
            "jlink":   {"state": "unknown", "serials": [], "ts": 0},
            "console": {"state": "unknown", "port": None, "ts": 0},
            "dice":    {"state": "unknown", "port": None, "ts": 0},
            "mcu":     {"state": "unknown", "ts": 0},   # PING 하트비트 응답 기반
        }
        self.fw_info = None                   # GET_INFO 응답 {fw, hw, proto}
        self.selftest = None                  # SELFTEST 응답 {dac, adc, raw} — LCD 상태 화면과 동일 소스
        self.ports = []                       # 마지막 COM 스캔 결과
        self.version = "dev"                  # 대시보드 버전 (git describe)
        self.fw_update = {"phase": "idle", "detail": ""}   # OTA 플래시 진행 상태

        os.makedirs(log_dir, exist_ok=True)
        day = time.strftime("%Y%m%d")
        self._console_log = open(os.path.join(log_dir, f"console-{day}.log"),
                                 "a", encoding="utf-8", buffering=1)
        self._event_log = open(os.path.join(log_dir, f"events-{day}.jsonl"),
                               "a", encoding="utf-8", buffering=1)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ---- 수집 스레드용 기록 API ----
    def add_console_line(self, line: str) -> None:
        ts = time.time()
        with self.lock:
            self.console.append((self._next_seq(), ts, line))
        stamp = time.strftime("%H:%M:%S", time.localtime(ts))
        self._console_log.write(f"[{stamp}] {line}\n")

    def add_event(self, source: str, level: str, msg: str) -> None:
        ts = time.time()
        with self.lock:
            self.events.append((self._next_seq(), ts, source, level, msg))
        self._event_log.write(json.dumps(
            {"ts": ts, "source": source, "level": level, "msg": msg},
            ensure_ascii=False) + "\n")

    def add_status(self, status: dict) -> None:
        with self.lock:
            self.status_pts.append((self._next_seq(), time.time(), status))

    def set_badge(self, name: str, **fields) -> None:
        """배지 갱신. state 필드가 바뀌면 이벤트로도 남긴다."""
        with self.lock:
            old_state = self.badges[name].get("state")
            self.badges[name].update(fields, ts=time.time())
            new_state = self.badges[name].get("state")
        if old_state not in (new_state, "unknown"):
            self.add_event(name, "info", f"{name}: {old_state} → {new_state}")

    def set_fw_info(self, info: dict) -> None:
        with self.lock:
            self.fw_info = info

    def set_selftest(self, st) -> None:
        with self.lock:
            self.selftest = st

    def set_ports(self, ports: list) -> None:
        with self.lock:
            self.ports = ports

    def set_fw_update(self, phase: str, detail: str = "") -> None:
        with self.lock:
            self.fw_update = {"phase": phase, "detail": detail}

    # ---- 조회 API ----
    def snapshot(self, console_n=200, events_n=100, status_n=600) -> dict:
        """전체 스냅샷 (REST /api/state, WS 최초 접속용)."""
        with self.lock:
            last_status = self.status_pts[-1] if self.status_pts else None
            return {
                "now": time.time(),
                "started_at": self.started_at,
                "version": self.version,
                "badges": {k: dict(v) for k, v in self.badges.items()},
                "fw_info": self.fw_info,
                "selftest": dict(self.selftest) if self.selftest else None,
                "fw_update": dict(self.fw_update),
                "ports": list(self.ports),
                "last_status": {"ts": last_status[1], **last_status[2]} if last_status else None,
                "console": [{"seq": s, "ts": t, "line": l}
                            for s, t, l in list(self.console)[-console_n:]],
                "events": [{"seq": s, "ts": t, "source": src, "level": lv, "msg": m}
                           for s, t, src, lv, m in list(self.events)[-events_n:]],
                "status_pts": [{"seq": s, "ts": t, **st}
                               for s, t, st in list(self.status_pts)[-status_n:]],
                "cursor": self._seq,
            }

    def delta_since(self, cursor: int) -> dict:
        """cursor 이후 신규 항목만 (WS 주기 push 용)."""
        with self.lock:
            return {
                "now": time.time(),
                "badges": {k: dict(v) for k, v in self.badges.items()},
                "fw_info": self.fw_info,
                "selftest": dict(self.selftest) if self.selftest else None,
                "fw_update": dict(self.fw_update),
                "console": [{"seq": s, "ts": t, "line": l}
                            for s, t, l in self.console if s > cursor],
                "events": [{"seq": s, "ts": t, "source": src, "level": lv, "msg": m}
                           for s, t, src, lv, m in self.events if s > cursor],
                "status_pts": [{"seq": s, "ts": t, **st}
                               for s, t, st in self.status_pts if s > cursor],
                "cursor": self._seq,
            }

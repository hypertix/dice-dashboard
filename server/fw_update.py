# -*- coding: utf-8 -*-
"""펌웨어 OTA — GitHub 릴리스(hypertix/dice-ota)에서 받아 J-Link 로 플래시.

배포 규약: dice-ota 레포에 GitHub Release 를 만들고 (tag = 버전, 예 v0.2.0),
asset 으로 dice_RW612.axf (또는 .hex / .bin) 를 첨부한다.
.bin 은 XIP 베이스 0x08000000 에 로드한다.

전제: 담당자 PC 에 J-Link 소프트웨어 설치 + MCU-Link(J-Link) 프로브 연결.
플래시 중 J-Link 는 이 프로세스가 독점 — IDE 디버그 세션과 동시 사용 불가.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from .state import AppState

FLASH_BASE = "0x08000000"          # RW612 QSPI XIP (dice_RW612 링커 기준)
_lock = threading.Lock()           # 플래시 동시 실행 방지


def _gh_api(cfg: dict, path: str) -> dict:
    repo = cfg.get("ota_repo", "hypertix/dice-ota")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/{path}",
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "dice-dashboard"})
    token = cfg.get("github_token")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def check(cfg: dict) -> dict:
    """최신 릴리스 조회 → {tag, name, published_at, notes, assets:[{name,size,url}]}"""
    try:
        rel = _gh_api(cfg, "releases/latest")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"error": "릴리스 없음 — dice-ota 레포에 Release 를 먼저 만드세요"}
        return {"error": f"GitHub API 오류 (HTTP {e.code})"}
    except urllib.error.URLError as e:
        return {"error": f"네트워크 오류: {e.reason}"}
    assets = [{"name": a["name"], "size": a["size"],
               "url": a["browser_download_url"]}
              for a in rel.get("assets", [])
              if a["name"].lower().endswith((".axf", ".hex", ".bin", ".elf"))]
    if not assets:
        return {"error": f"릴리스 {rel.get('tag_name')} 에 펌웨어 asset(.axf/.hex/.bin) 없음"}
    return {
        "tag": rel.get("tag_name"),
        "name": rel.get("name") or rel.get("tag_name"),
        "published_at": rel.get("published_at"),
        "notes": (rel.get("body") or "")[:300],
        "assets": assets,
    }


def _flash(jlink_exe: str, path: str) -> tuple:
    """(ok, message). verify_fw.py 와 동일한 J-Link Commander 시퀀스 + 3회 재시도."""
    load = f'loadfile "{path}"'
    if path.lower().endswith(".bin"):
        load += f",{FLASH_BASE}"
    script = f"r\nh\n{load}\nr\ng\nqc\n"
    with tempfile.NamedTemporaryFile("w", suffix=".jlink", delete=False) as f:
        f.write(script)
        cmdfile = f.name
    try:
        for attempt in range(1, 4):
            r = subprocess.run(
                [jlink_exe, "-NoGui", "1", "-Device", "RW612", "-If", "SWD",
                 "-Speed", "4000", "-AutoConnect", "1", "-CommandFile", cmdfile],
                capture_output=True, text=True, timeout=300)
            out = r.stdout + r.stderr
            bad = [k for k in ("Cannot connect", "FAILED", "Error occurred",
                               "not supported") if k in out]
            if r.returncode == 0 and not bad:
                return True, "플래시 OK"
            if attempt < 3:
                time.sleep(2)
        return False, f"J-Link 실패: {', '.join(bad) or f'rc={r.returncode}'}"
    finally:
        os.unlink(cmdfile)


def apply_async(state: AppState, cfg: dict, asset: dict, tag: str) -> bool:
    """다운로드+플래시를 백그라운드 스레드로. 이미 진행 중이면 False."""
    if not _lock.acquire(blocking=False):
        return False

    def run():
        try:
            state.set_fw_update("download", f"{tag} {asset['name']} 다운로드 중")
            state.add_event("fw-update", "info", f"펌웨어 {tag} 다운로드 시작 ({asset['name']})")
            suffix = os.path.splitext(asset["name"])[1]
            fd, path = tempfile.mkstemp(suffix=suffix)
            try:
                req = urllib.request.Request(asset["url"],
                                             headers={"User-Agent": "dice-dashboard"})
                with urllib.request.urlopen(req, timeout=60) as r, os.fdopen(fd, "wb") as f:
                    f.write(r.read())
                state.set_fw_update("flash", f"{tag} J-Link 플래시 중")
                state.add_event("fw-update", "info", f"J-Link 플래시 시작 ({tag})")
                ok, msg = _flash(cfg.get("jlink_exe", "JLink.exe"), path)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            if ok:
                state.add_event("fw-update", "info",
                                f"펌웨어 {tag} 플래시 완료 + 리셋 — 부팅 로그/버전 확인")
            else:
                state.add_event("fw-update", "error", f"펌웨어 {tag} 플래시 실패 — {msg}")
        except Exception as e:                        # 진행 상태가 멈춘 채 남지 않게
            state.add_event("fw-update", "error", f"펌웨어 업데이트 예외: {e}")
        finally:
            state.set_fw_update("idle")
            _lock.release()

    threading.Thread(target=run, name="fw_update", daemon=True).start()
    return True

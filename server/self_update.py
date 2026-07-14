# -*- coding: utf-8 -*-
"""대시보드 자기 업데이트 — 실행 형태에 따라 경로가 다르다.

소스 실행(개발자): git fetch/pull + pip 갱신 후 종료코드 3 → run.bat 재시작 루프.
단일 exe(담당자):  GitHub Release(dashboard_repo) 조회 → 새 exe 다운로드 →
                   교체 배치 스크립트를 띄우고 종료 → 배치가 exe 교체 후 재실행.

/api/update/* 응답 형태는 두 모드 공통이라 프론트엔드는 구분하지 않는다:
  check → {current, behind, log[]} 또는 {error}
  apply → {ok, restarting} 또는 {ok:false, error}
"""
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request

from . import fw_update
from .paths import APP_DIR, FROZEN, WINDOWLESS
from .version import __version__

RESTART_EXIT_CODE = 3            # run.bat 이 이 코드를 보면 재시작 루프를 돈다
_applying = threading.Lock()     # exe 교체 동시 실행 방지

# 교체 배치: 본체 종료를 기다렸다가(삭제될 때까지 재시도) 새 exe 로 바꾸고 재실행.
# cmd 는 OEM 코드페이지로 배치를 읽으므로 내용은 ASCII 만 사용, 경로는 인자로 받는다.
# timeout 은 콘솔 없는 환경에서 실패하므로 ping 으로 1초 대기한다.
_UPDATER_BAT = """@echo off
rem DICE dashboard self-update helper (auto-generated, deletes itself)
set "EXE=%~1"
set "NEW=%~2"
:wait
ping -n 2 127.0.0.1 >nul
del "%EXE%" >nul 2>&1
if exist "%EXE%" goto wait
move /y "%NEW%" "%EXE%" >nul
start "" "%EXE%" --no-browser
del "%~f0"
"""


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=APP_DIR,
                          capture_output=True, text=True, timeout=60)


def current_version() -> str:
    if FROZEN:
        return "v" + __version__
    r = _git("describe", "--always", "--dirty")
    return r.stdout.strip() if r.returncode == 0 else "dev"


def check(state, cfg: dict) -> dict:
    return _check_release(cfg) if FROZEN else _check_git(state)


def apply(state, cfg: dict) -> dict:
    return _apply_release(state, cfg) if FROZEN else _apply_git(state)


# ---- 소스 실행: git 기반 (기존 동작 그대로) ----
def _check_git(state) -> dict:
    f = _git("fetch", "--quiet")
    if f.returncode != 0:
        return {"error": "git fetch 실패 — 원격/네트워크 확인",
                "detail": f.stderr.strip()[:200]}
    behind = _git("rev-list", "--count", "HEAD..@{u}")
    if behind.returncode != 0:
        return {"error": "업스트림 미설정 — git clone 으로 설치된 사본인지 확인"}
    n = int(behind.stdout.strip() or 0)
    log = _git("log", "HEAD..@{u}", "--oneline").stdout.strip().splitlines()[:5]
    return {"current": state.version, "behind": n, "log": log}


def _apply_git(state) -> dict:
    r = _git("pull", "--ff-only")
    if r.returncode != 0:
        return {"ok": False, "error": "git pull 실패", "detail": r.stderr.strip()[:200]}
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                    os.path.join(APP_DIR, "requirements.txt")],
                   capture_output=True, timeout=300)
    state.add_event("dashboard", "info", "대시보드 업데이트 적용 — 3초 후 재시작")
    if WINDOWLESS:
        # pythonw 숨김 실행에는 run.bat 재시작 루프가 없다 — 포트가 풀린 뒤(3초)
        # 스스로 재실행하는 배치를 띄우고 종료한다 (exe 교체 배치와 같은 패턴).
        bat = os.path.join(APP_DIR, "_dice_restart.bat")
        with open(bat, "w", encoding="ascii") as f:
            f.write("@echo off\nping -n 4 127.0.0.1 >nul\n"
                    f'start "" "{sys.executable}" -m server.app --no-browser\n'
                    'del "%~f0"\n')
        subprocess.Popen(["cmd", "/c", bat], cwd=APP_DIR,
                         creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        threading.Timer(1.0, lambda: os._exit(0)).start()
    else:
        threading.Timer(3.0, lambda: os._exit(RESTART_EXIT_CODE)).start()
    return {"ok": True, "restarting": True}


# ---- 단일 exe: GitHub Release 기반 ----
def _check_release(cfg: dict) -> dict:
    repo = cfg.get("dashboard_repo", "hypertix/dice-dashboard")
    try:
        rel = fw_update._gh_api(cfg, "releases/latest", repo=repo)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"error": f"릴리스 없음 — {repo} 레포에 Release 가 아직 없습니다"}
        return {"error": f"GitHub API 오류 (HTTP {e.code})"}
    except urllib.error.URLError as e:
        return {"error": f"네트워크 오류: {e.reason}"}
    tag = rel.get("tag_name") or ""
    asset = next((a for a in rel.get("assets", [])
                  if a["name"].lower().endswith(".exe")), None)
    if not asset:
        return {"error": f"릴리스 {tag} 에 exe asset 없음"}
    cur = "v" + __version__
    if tag == cur:
        return {"current": cur, "behind": 0, "log": []}
    title = rel.get("name") or ""
    return {"current": cur, "behind": 1,
            "log": [f"{tag}" + (f" — {title}" if title and title != tag else "")],
            "tag": tag,
            "asset_url": asset["browser_download_url"],
            "asset_size": asset["size"]}


def _apply_release(state, cfg: dict) -> dict:
    info = _check_release(cfg)
    if info.get("error"):
        return {"ok": False, "error": info["error"]}
    if not info.get("behind"):
        return {"ok": False, "error": f"이미 최신 버전입니다 ({info['current']})"}
    if not _applying.acquire(blocking=False):
        return {"ok": False, "error": "이미 업데이트 진행 중"}

    def run():
        exe = os.path.abspath(sys.executable)
        new = exe + ".new"
        try:
            mb = info["asset_size"] / (1 << 20)
            state.add_event("dashboard", "info",
                            f"대시보드 {info['tag']} 다운로드 중 ({mb:.0f} MB)")
            req = urllib.request.Request(info["asset_url"],
                                         headers={"User-Agent": "dice-dashboard"})
            with urllib.request.urlopen(req, timeout=600) as r, open(new, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            bat = os.path.join(APP_DIR, "_dice_update.bat")
            with open(bat, "w", encoding="ascii") as f:
                f.write(_UPDATER_BAT)
            state.add_event("dashboard", "info",
                            f"대시보드 {info['tag']} 적용 — 재시작합니다 (자동 재연결)")
            subprocess.Popen(["cmd", "/c", bat, exe, new],
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             close_fds=True)
            threading.Timer(1.5, lambda: os._exit(0)).start()
        except Exception as e:
            try:
                os.unlink(new)
            except OSError:
                pass
            state.add_event("dashboard", "error", f"대시보드 업데이트 실패: {e}")
            _applying.release()

    threading.Thread(target=run, name="self_update", daemon=True).start()
    return {"ok": True, "restarting": True}

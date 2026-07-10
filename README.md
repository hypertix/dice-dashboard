# DICE Bench Dashboard

DICE(RW612 펌웨어) 벤치 개발용 **로컬 웹 대시보드**. 브라우저 탭 하나에서
J-Link/COM 연결 상태, UART 콘솔, 채널 전류 차트, 진행사항 타임라인을 한눈에 본다.
사람(브라우저)과 AI(REST API)가 **같은 데이터 소스**를 읽는 구조.

관련 레포: `c:\nxp\Project\ublox\dice_RW612` (펌웨어), `C:\Project\hypertix\dice_lcd` (제품 UI).

## 실행

```
run.bat            (또는 python -m server.app)
브라우저 → http://localhost:8765
```

필요 패키지: `pip install -r requirements.txt` (fastapi, uvicorn, pyserial)

## 하는 일 (벤치 모드 = 가상 LCD)

- **DICE USB CDC** (NXP VID 0x1FC9 자동 감지): LCD 역할 대행 — PING 500 ms 하트비트,
  GET_INFO, STATUS(10 Hz)/EVENT/RSP 수신. LCD 없이 LCD 연결과 동일한 환경으로 펌웨어 검증.
- **UART 디버그 콘솔** (MCU-Link VCOM, SEGGER VID 0x1366 자동 감지, 115200):
  tail + PASS/FAIL/dropped 패턴 자동 이벤트 승격. `logs/console-*.log` 로도 기록.
- **J-Link 프로브 감시**: `JLink.exe ShowEmuList` 폴링 (타겟 비연결 — IDE 디버그와 병행 안전).
- **진행사항 타임라인**: 연결 상태 변화 + 콘솔 패턴 + 외부 스크립트 POST 이벤트.
  `logs/events-*.jsonl` 로 영구 기록.

## API (AI/스크립트용)

| 경로 | 설명 |
|---|---|
| `GET /api/state` | 전체 상태 스냅샷 JSON (배지, 최근 콘솔/이벤트/STATUS 포인트) |
| `POST /api/event` | `{"source","level","message"}` — 타임라인에 진행사항 기록 |
| `WS /ws` | 실시간 delta push (5 Hz, 커서 기반) |

## 설정 (config.json — 없으면 자동 감지)

```json
{
  "http_port": 8765,
  "console_port": null,   // null = SEGGER VID 자동 감지 (예: "COM7")
  "dice_port": null,      // null = NXP VID 자동 감지
  "jlink_exe": "C:\\Program Files\\SEGGER\\JLink_V926\\JLink.exe"
}
```

## 주의

- **시리얼 포트는 한 프로세스만** 연다. dice_host.py / PuTTY 가 포트를 잡고 있으면
  배지에 "점유됨"으로 표시되고 뺏지 않는다 (해제 후 자동 재연결).
- 대시보드는 STATUS/EVENT 수신과 PING 만 한다 — 출력 제어(파형/HV)는 아직
  dice_host.py 사용 (제어 패널은 로드맵 참조).

## 로드맵

- **2단계 — 통합 모드**: LCD(RK3566)가 USB 를 소유할 때 adb/TCP 로 LCD 상태·스크린샷·
  로그를 가져와 표시. 제어 패널(파형/HV/시작정지) 추가.
- **3단계**: FreeMASTER Lite(JSON-RPC) 연동으로 임의 전역변수 모니터링,
  자동 검증 루프(플래시→부팅판정→스코프)와 타임라인 연동.

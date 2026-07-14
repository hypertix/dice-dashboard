# DICE Bench Dashboard

DICE(RW612 펌웨어) 벤치/검증용 **로컬 웹 대시보드**. 브라우저 탭 하나에서
연결 상태(J-Link/COM), UART 콘솔, 채널 전류 차트, LCD 와 동일한 출력 제어 화면,
펌웨어 업데이트, 진행사항 타임라인을 한눈에 본다. 사람(브라우저)과 AI(REST API)가
**같은 데이터 소스**를 읽는 구조.

관련 레포: [dice-rw612](https://github.com/hypertix/dice-rw612) (펌웨어),
[dice_lcd](https://github.com/hypertix/dice_lcd) (제품 UI),
[dice-ota](https://github.com/hypertix/dice-ota) (펌웨어 릴리스 배포).

## 설치 (H/W·검증 담당자) — exe 하나면 끝

1. **J-Link Software** 설치 — [segger.com](https://www.segger.com/downloads/jlink/) (펌웨어 플래시용, 최초 1회)
2. [**Releases**](https://github.com/hypertix/dice-dashboard/releases/latest) 에서
   `DiceDashboard.exe` 다운로드 → 적당한 폴더에 두고 **더블클릭**
3. 브라우저가 자동으로 열린다 (수동 접속: http://localhost:8765)

창 없이 백그라운드로 실행되고, **수명은 브라우저 탭에 묶인다** —
실행하면 브라우저가 자동으로 열리고, 마지막 대시보드 탭을 닫으면 서버도
몇 초 뒤 자동 종료된다 (새로고침은 종료로 오인하지 않음).
이미 켜진 상태에서 exe 를 또 실행하면 브라우저 탭만 다시 열린다.
서버 내부 오류는 exe 옆 `logs/server.log` 에 남는다.

Python·Git 설치 불필요. 처음 실행 시 Windows SmartScreen 경고가 뜨면
**"추가 정보" → "실행"** (서명 없는 사내 배포 exe 라 뜨는 정상 경고).
`config.json`·`logs/` 는 exe 옆에 생성된다. J-Link 설치 경로가
기본값(`C:\Program Files\SEGGER\JLink_V926`)과 다르면 exe 옆에 `config.json` 을
만들어 `jlink_exe` 를 지정한다 (아래 설정 참조).

## 설치 (개발자) — 소스 실행

준비물: Python 3.10+ / Git. 그 후:
```bat
git clone https://github.com/hypertix/dice-dashboard.git
cd dice-dashboard
install.bat        ← 최초 1회 (pip 패키지 설치)
run.bat            ← 실행. 브라우저에서 http://localhost:8765
```

## 화면 구성

- **연결 배지**: J-Link 프로브 / UART 콘솔(MCU-Link VCOM) / DICE USB CDC /
  MCU(PING 하트비트) / AD9106·ADC(SELFTEST 자가진단, LCD 상태 화면과 동일 소스) / 펌웨어 버전.
  UART 콘솔은 포트가 열려도 수신 데이터가 없으면 노랑("무수신") — 초록은 실제 수신 중일 때만.
- **채널 전류 차트**: STATUS 10 Hz 실시간 (CH1 노랑·CH2 초록·CH3 파랑·CH4 빨강)
- **출력 제어 — dice_lcd 출력제어 화면 복제**: LCD 실물과 동일한 조작
  (CH1~4 탭, 사인 파형, 주파수/진폭(P-P)/위상/버스트 +− 스테퍼 — 변경 즉시 적용,
  사인 주파수는 4채널 공통 동기화(LCD 와 동일), 파형 미리보기(설정값 시뮬레이션),
  실측 전류 RMS, 채널별 출력 시작/정지, 전체 시작/정지, 비상정지, HV)
- **UART 콘솔**: 부팅 로그 tail, PASS/FAIL 하이라이트 + 타임라인 자동 승격
- **펌웨어 업데이트**: dice-ota 최신 릴리스 조회 → 다운로드 → J-Link 플래시 (아래)
- **진행사항 타임라인**: 모든 이벤트 시간순 기록 (`logs/events-*.jsonl` 영구 보관)

## 펌웨어 업데이트 (담당자용)

전제: **MCU-Link(J-Link) 프로브가 PC 에 연결**되어 있을 것 (J-Link 배지 녹색).

1. 개발자가 [dice-ota](https://github.com/hypertix/dice-ota) 에 **GitHub Release** 를
   만든다 — tag = 버전(예 `v0.2.0`), asset = `dice_RW612.axf` (또는 .hex/.bin).
2. 담당자는 대시보드의 **「펌웨어 업데이트」 카드 → 릴리스 확인 → 다운로드+플래시**.
3. 진행/결과는 타임라인에 기록되고, 리부팅 후 펌웨어 배지에 새 버전이 뜬다.

주의: 플래시 중 J-Link 를 다른 프로그램(IDE 디버그)이 잡고 있으면 실패한다.

## 대시보드 자체 업데이트

헤더의 **「업데이트 확인」** 버튼 하나로 실행 형태에 맞게 동작한다:

- **exe 실행 (담당자)**: 이 레포의 GitHub Release 최신 태그와 내장 버전을 비교 →
  새 버전이면 새 exe 다운로드 → 자동 교체 + 재시작. 브라우저는 자동 재연결.
- **소스 실행 (개발자)**: `git fetch` 로 새 커밋 확인 → `git pull` + 패키지 갱신 후
  자동 재시작 (run.bat 재시작 루프). 수동: 서버 끄고 `git pull` → `run.bat`.

## 배포 (개발자) — exe 릴리스 만들기

1. `server/version.py` 의 `__version__` 을 올린다 (예 `"1.1.0"`)
2. 커밋 + push 후 같은 버전으로 태그: `git tag v1.1.0 && git push origin v1.1.0`
3. GitHub Actions(`release-exe.yml`)가 자동으로: 태그=버전 검사 → PyInstaller 빌드 →
   기동 스모크 테스트 → Release 생성 + `DiceDashboard.exe` 첨부
4. 담당자들은 「업데이트 확인」 버튼으로 받아간다

로컬 빌드(테스트용): `scripts\build_exe.bat` → `dist\DiceDashboard.exe`

## API (AI/스크립트용)

| 경로 | 설명 |
| --- | --- |
| `GET /api/state` | 전체 상태 스냅샷 JSON |
| `POST /api/event` | `{"source","level","message"}` — 타임라인에 기록 |
| `POST /api/cmd` | DICE 제어: `{"action":"hv/start/stop/estop/waveform", ...}` |
| `GET /api/fw/check` · `POST /api/fw/apply` | 펌웨어 릴리스 조회/플래시 |
| `GET /api/update/check` · `POST /api/update/apply` | 대시보드 자기 업데이트 |
| `WS /ws` | 실시간 delta push (5 Hz) |

자동 검증 루프: 펌웨어 레포의 `tools/verify_fw.py` (빌드→플래시→부팅판정→STATUS)
가 이 API 로 판정/기록한다.

## 설정 (config.json — 없으면 기본값/자동 감지)

위치: exe 실행은 **exe 옆**, 소스 실행은 레포 루트.

```json
{
  "http_port": 8765,
  "console_port": null,              // null = SEGGER VID 자동 감지 (예: "COM7")
  "dice_port": null,                 // null = NXP VID 자동 감지
  "jlink_exe": "C:\\Program Files\\SEGGER\\JLink_V926\\JLink.exe",
  "ota_repo": "hypertix/dice-ota",
  "dashboard_repo": "hypertix/dice-dashboard",   // exe 자기 업데이트 Release 레포
  "github_token": null               // 레포가 private 일 때만
}
```

## 주의

- **시리얼 포트는 한 프로세스만** 연다. dice_host.py / PuTTY 가 잡고 있으면
  배지에 "점유됨" 표시 (해제 후 자동 재연결). 프로브 감시는 USB 열거 방식이라
  IDE 디버그·플래시와 충돌하지 않는다.
- USB 케이블이 LCD 에 꽂혀 있으면 DICE CDC 배지는 "없음"이 정상 — 제어/차트는
  PC 에 USB 를 연결했을 때만 동작한다 (LCD 와 동시 소유 불가).
- **펌웨어 알려진 이슈 (2026-07-10, 미해결)**: 출력 정지 후 재시작(재적용) 시
  전류가 부팅 기본 출력과 다르게 나오는 버그가 있다 (동일 설정인데 CH2 ≈ 1/18,
  CH3/4 ≈ 1/2 로 측정됨). 제어 화면의 시작/정지가 이 경로를 타므로, 값이 이상하면
  보드 리셋(전원 재인가)으로 복구하고 펌웨어 수정을 기다릴 것.

# S4 상주·자동 시작 — 자식 프로세스 관리, 잠금 화면, 로그오프

결론 → [ADR-0023](../../docs/decisions/0023-bot-ui-process-supervision.md) (제안)

## 확인하려 한 것

ADR-0012·0014의 제안 「Bot 실행은 Bot UI의 자식 프로세스(실행기) 하나, 목적은 격리」를 Windows에서 확정할 수 있는가 — 자식 관리가 과하게 복잡하면 Bot UI 안의 스레드 실행으로 되돌린다는 조건이 있었다.

- Bot UI가 Worker 프로세스·실행기를 띄우고 감시·재시작·강제 종료 (C10 기동 절차 포함)
- 대기열에서 다음 Bot으로 넘어가기, 실행 중 Bot → Worker REST
- 잠금 화면·로그오프 때의 동작, 로그온 자동 시작

## 환경

| 항목 | 값 |
| --- | --- |
| OS | Windows 11 Education 10.0.26200, 한국어, 모니터 한 대 100% |
| Python | 3.12, 저장소 `.venv` (가상환경의 `python.exe`는 진짜 인터프리터를 자식으로 띄우는 런처) |
| 의존 | 표준 라이브러리 + ctypes (`lock_probe.py`만 uiautomation·mss) |

## 파일

| 파일 | 하는 일 |
| --- | --- |
| `winjob.py` | Job Object 헬퍼. 자식마다 Job 하나, `KILL_ON_JOB_CLOSE`, 일시 정지로 만들고 Job에 넣은 뒤 깨움, 나무째 종료 |
| `supervisor.py` | Bot UI 핵심만: Worker 기동(토큰 파일 → `/v1/health` 대기)·감시·재시작(연속 3회), 실행기 하나로 대기열 처리(시간 초과 → stdin `stop` → 2초 → 나무째 종료) |
| `fake_worker.py` | 가짜 Worker (127.0.0.1 REST, 토큰 검사, `/v1/admin/crash`, 포트 실패 시 종료 코드 2) |
| `fake_runner.py` | 가짜 실행기 (normal·hang·spawn·crash·poll) |
| `fake_botui.py` | 강제 종료 시험용 가짜 Bot UI |
| `probe.py` | 자동 시험 → `outputs/result.json` |
| `lock_target.py`, `lock_probe.py` | 잠금 화면 시험 (3초마다 UIA·클릭·키·캡처·REST) → `outputs/lock.jsonl` |
| `resident_botui.py` | 숨은 창을 가진 상주 가짜 Bot UI. 로그오프·잠금 알림 기록 → `outputs/logoff.jsonl` |
| `autostart_probe.py`, `wts.py` | 자동 시작 시각 기록, WTS 세션 정보 (잠금 플래그·로그온 시각) |

```bash
uv run python spikes/S4-resident-supervisor/probe.py
uv run spikes/S4-resident-supervisor/lock_probe.py 180     # 실행 중에 Win+L → 30초 뒤 해제
```

## 본 것

### 1. 자식 프로세스 격리 (`probe.py`)

| 시험 | 결과 |
| --- | --- |
| Bot UI 강제 종료(TerminateProcess), Job 없이 | Worker·실행기의 런처·인터프리터·손자 **6개 모두 고아로 남음** |
| 같은 시험, 자식마다 Job | **6개 모두 함께 죽음** |
| 대기열 6건: 보통 → 협조 중지 → 멈춤 → 손자 남김 → 비정상 종료 → 보통 | 순서대로 전부 처리, 11.7초. 협조 중지는 stdin `stop`으로 스스로 끝남(1.1초), 멈춤·손자 남김은 2초 유예 뒤 나무째 강제 종료(손자도 죽음), 비정상 종료(코드 7)도 다음으로 넘어감 |
| Worker 강제 종료 → 재시작 | 1.6초 만에 다시 건강. 토큰 파일이 바뀜. 그 사이 실행기의 REST 호출 42번 중 2번 실패 |
| Worker가 뜨자마자 죽음 | 3회 재시작 뒤 포기 (C10 「연속 3회」) |
| 포트를 다른 프로그램이 쥐고 있음 | Worker가 약 1초 안에 종료 코드 2. Windows 오류 문구는 `[WinError 10013] 액세스 권한에 의해 숨겨진 소켓에 액세스를 시도했습니다` — 사용자에게 그대로 보이면 뜻을 알 수 없다 |

- Job은 **자식을 일시 정지로 만들고 넣은 뒤 깨워야** 한다. 그냥 띄운 다음 넣으면 그 사이에 손자가 Job 밖에 생길 수 있다. 가상환경 `python.exe`처럼 런처가 진짜 프로그램을 손자로 띄우는 경우가 흔하다.
- `Popen`은 주 스레드 핸들을 버리므로 스레드 스냅숏으로 찾아 깨웠다 (`winjob._resume_all_threads`). 헬퍼 전체가 약 150줄 — 「과하게 복잡」하지 않다.
- Job의 살아 있는 프로세스 수는 자식이 끝난 직후 약 0.1초 늦게 0이 된다 (집계 지연, 누수 아님).
- 실행기가 매 호출마다 토큰 파일을 다시 읽어서 Worker 재시작(토큰 교체) 뒤에도 이어서 동작했다. 토큰을 시작할 때 한 번만 읽으면 재시작 뒤 401이 난다.

### 2. 잠금 화면 (`lock_probe.py`, 사용자가 Win+L)

| 단계 | 감지 | UIA 읽기 | 클릭·키 | 캡처 | Worker REST |
| --- | --- | --- | --- | --- | --- |
| 잠금 화면(LockApp) | **WTS 플래그만** 잠김. 입력 데스크톱 이름은 `Default` 그대로 | 됨 (사각형도 그대로) | 그 자리는 `LockApp.exe` — 누르면 잠금 화면에 들어간다 | 잠금 화면이 찍힘 | 됨 |
| 비밀번호 입력 화면 | 입력 데스크톱 열기 실패 (오류 5) | 됨 | 가려짐 | **예외** (`BitBlt` 실패) | 됨 |
| 해제 직후 | — | 됨 | 바로 회복 | 바로 회복 | 됨 |

- **UIA는 잠긴 동안에도 「요소가 있다」고 답한다.** UIA만 보고 조작하면 입력이 잠금 화면으로 간다. 잠금은 WTS(`WTSSessionInfoEx`의 `SessionFlags`, 또는 `WTSRegisterSessionNotification`)로 알아야 한다.
- 캡처는 잠금 단계에 따라 잠금 화면을 찍거나 예외를 던진다 — 둘 다 처리해야 한다.
- 시험 중 실수: 첫 실행에서 입력칸 클릭에 「그 점의 창이 시험 창인가」 확인이 빠져 잠금 화면을 눌렀다. 고친 뒤 결과만 위에 적었다. 실제 Worker도 **입력 전에 그 점의 창 주인을 확인**하는 편이 안전하다.
- `WTSINFOEXW`는 공용체에 8바이트 필드가 있어 `Data`가 오프셋 8에서 시작한다. 처음에 4로 읽어 잠금 여부를 거꾸로 읽었다 (`wts.py`는 구조체로 정의).

### 3. 로그오프 (`resident_botui.py`, 사용자가 로그아웃)

```
23:08:48 WM_QUERYENDSESSION  logoff=true
23:08:48 WM_ENDSESSION       ending=true
23:08:48 children-terminated 1ms, 실행기 Job 남은 프로세스 0
```

- 최상위 숨은 창이 두 알림을 모두 받았다 (메시지 전용 창 `HWND_MESSAGE`는 `WM_QUERYENDSESSION`을 받지 못하므로 쓰지 않았다).
- `WM_ENDSESSION`에서 Job을 끝내는 데 1ms. 다시 로그인한 뒤 남은 시험 프로세스는 없었다.
- 로그오프 때 받는 WTS 세션 알림(`logoff`)은 기록되지 않았다 — 그 전에 프로세스가 끝난다. 정리는 `WM_ENDSESSION`에서 해야 한다.

### 4. 자동 시작 (사용자가 로그아웃·로그인 두 번)

| 방식 | 결과 |
| --- | --- |
| 작업 스케줄러 「로그온 시」 (현재 사용자, 관리자 권한 없이 등록됨) | **로그온 4초 뒤 실행** (23:16:40 → 23:16:44). 실행된 프로그램의 창이 사용자 화면에 떴다 — 사용자 세션에서 GUI가 뜬다 |
| HKCU `Run` | 이 PC에서는 Run 항목을 **하나씩 차례로** 실행한다 (Shell-Core 운영 로그 9705~9708). HKLM Run 다음에 HKCU Run이 로그온 **2.5~3분 뒤** 시작했다 (두 번 모두). 시작 프로그램이 많은 업무 PC에서는 더 늦을 수 있다 |

**시험 환경 문제 (제품 결함 아님):** Claude 데스크톱 앱이 MSIX 패키지라, 그 안에서 띄운 셸이 `%APPDATA%`·HKCU에 쓴 것이 **패키지 전용 가상화 위치**로 갔다.

- uv가 받은 Python이 실제로는 `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\uv\python`에 있다. 그래서 패키지 밖(작업 스케줄러)에서 실행한 `.venv` 런처가 `No Python at '…'` 창을 띄웠다.
- 셸에서 쓴 HKCU Run 값도 패키지 밖에서는 보이지 않아, 로그온 때 건너뛰어졌다 (작업 스케줄러로 `reg query`를 돌려 확인).
- 그래서 Run 키 방식의 「우리 항목이 몇 초에 떴나」는 재지 못했다. 위 2.5~3분은 같은 목록의 다른 항목들이 시작된 시각이다.

### 하지 않은 것 (다음에)

- Linux (프로세스 그룹·`PR_SET_PDEATHSIG`, XDG autostart).
- 진짜 설치 파일(S5)로 자동 시작 — 가상환경 런처가 아닌 실행 파일로.
- 원격 데스크톱 연결 끊김·최소화, 빠른 사용자 전환, 절전·최대 절전에서 돌아올 때.
- 로그오프 중 Center에 「거절 — Bot UI 종료」를 보낼 시간이 있는지 (ADR-0014 §2 「종료 시」).
- 토큰 파일 ACL(현재 사용자만 읽기, C10).

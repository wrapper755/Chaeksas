"""서버 실행기 — 실행 위치 「서버」 BPM 프로세스 동시 실행, 상태 저장·재개 (화면 없음, C12)

지금 도는 것은 **등록·하트비트**다 (M7 조각 2) — `agent.py`가 `core.machine`의
`machine_id`로 등록하고 주기마다 상태를 올린다. 내려온 작업·배포는 **받아 두고 돌리지 않는다**
(다음 조각). 담고 되살리는 모양은 ADR-0054가 정해 두었다.

| 모듈 | 무엇 |
| --- | --- |
| `settings` | `BPM_SERVER_RUNNER__*` (화면이 없으니 설정 파일도 없다) |
| `credentials` | Center API 키 — 환경변수가 먼저, 그다음 OS 비밀 저장소 |
| `center_client` | C12 등록·하트비트. 오류를 갈라서 올린다 |
| `agent` | 한 걸음(`tick()`) — **스레드를 만들지 않는다** |
| `main` | `bpm-server-runner` — SIGTERM에 곱게 끝낸다 |

자세히: docs/01-architecture.md §2, docs/03-contracts/C12-server-runner-center.md.
"""

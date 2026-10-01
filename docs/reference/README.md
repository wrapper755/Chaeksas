# 참고: 프로토타입 4개 지도

프로토타입 저장소는 **읽기 전용**으로 둔다 ([ADR-0001](../decisions/0001-new-repo-prototypes-as-reference.md)).
이 폴더는 "무엇이 어디 있고, 무엇을 가져오고, 무엇을 버리는가"를 적는다. 분석 기준일: 2026-10-01.

프로토타입 코드가 없는 PC에서도 이 폴더만으로 뜻이 통하게 썼다. 파일 경로는 **각 프로토타입 저장소 안의 상대경로**다.

## 이름 대응표 (이 문서 묶음에서 프로토타입 이름이 나오는 유일한 곳)

| 내부 용어 | 프로토타입 저장소 이름 | 원래 위치 (분석 당시 PC) | 상세 |
| --- | --- | --- | --- |
| 프로토타입 Studio·Bot (Admin 포함) → 새 Studio, Bot UI(실행 부분) | AgentWorks | `~/Workspace/AgentWorks` | [proto-studio-bot.md](proto-studio-bot.md) |
| 프로토타입 Center | AgentCenter | `~/Workspace/AgentCenter` | [proto-center.md](proto-center.md) |
| 프로토타입 UI 자동화 서버 (→ 새 UI 자동화 앱) | TapTap | `~/Workspace/TapTap` | [proto-ui-automation.md](proto-ui-automation.md) |
| 프로토타입 Worker → 새 Worker 프로세스 + Bot UI의 UI 셀렉터 등록 | TapTapWorker | `~/Workspace/TapTapWorker` | [proto-worker.md](proto-worker.md) |

프로토타입 코드 안의 용어는 새 용어와 다르다. 코드를 읽을 때 아래처럼 바꿔 읽는다.

| 프로토타입 코드의 말 | 새 용어 |
| --- | --- |
| Employee, 직원, 에이전트(배포 단위) | BPM 프로세스 (운영 화면: Bot) |
| Library, process-lib | 공유 프로세스 |
| HITL (business 층) | 결재 |
| HITL (execution 층) | 확인 |
| escalation, User Task 전환 | 전환 |
| Dashboard | Center 콘솔 |
| TapTap 서버, 셀렉터 서버 | UI 자동화 앱 |
| 프로토타입 Bot (aw-bot, 현장 실행 프로그램) | Bot UI |
| Worker 트레이·화면 등록 탭 | Bot UI의 「UI 셀렉터 등록」 |
| Worker 문서의 "Bot"(임의의 BPM/RPA 봇) | 실행 중인 Bot (Bot UI가 실행) |
| job (UI 자동화 서버) | UI 세션 |
| `.awpkg` | 패키지 |
| `AW_`, `AC_`, `TAPTAP_` 환경변수 | `CHK_` |

전체 판단 근거는 [lessons-learned.md](lessons-learned.md).

## 주제별로 어디를 보는가

| 새 저장소에서 만들 것 | 먼저 볼 프로토타입 | 파일 |
| --- | --- | --- |
| 계약: 패키지·이벤트·서명 | Studio·Bot | `packages/protocol/<패키지>/manifest.py`, `events.py`, `hashing.py`, `signing.py` |
| BPMN 실행·AI 태스크 연결 | Studio·Bot | `packages/core/<패키지>/orchestration/engine.py`, `bridge.py`, `parser.py` |
| 사전 점검 | Studio·Bot | `packages/core/<패키지>/orchestration/preflight.py` |
| 에이전트 루프 | Studio·Bot | `packages/core/<패키지>/agent/graph.py`, `nodes/` |
| 도구 레지스트리·화이트리스트 | Studio·Bot | `packages/core/<패키지>/agent/tools/registry.py` |
| 데스크톱 조작 (Windows UIA) | Studio·Bot | `packages/core/<패키지>/agent/tools/desktop.py`의 Windows 백엔드 (미검증) |
| 재생 기억 | Studio·Bot | `packages/core/<패키지>/memory/replay.py`, `episodic.py` |
| Studio 화면 | Studio·Bot | `apps/studio/<패키지>/ui/main.py`, `property_panel.py`, `editors.py`, `ui/web/` |
| Bot 상주·배포 적용 | Studio·Bot | `apps/bot/<패키지>/host.py`, `deploy.py`, `jobs.py`, `ui/tray.py` |
| 결재 창 | Studio·Bot | `packages/qt/<패키지>/hitl_dialog.py` |
| Center API·DB | Center | `<패키지>/api/`, `db/models.py`, `docs/center_api_phase2.md` |
| 콘솔 화면 | Center | `dashboard/pages/`, `dashboard/timeline.py` |
| 결재 원격 전달 | Studio·Bot, Center | Bot `remote_hitl.py`, Center `services/hitl.py` |
| 로케이터 모델·사다리 | Worker | `src/contracts/locators.py`, `src/executor/engine.py` |
| 치유 요청·검증 | Worker, UI 자동화 서버 | Worker `src/executor/runner.py`, 서버 `src/worker_api/healer.py` |
| 그래프 스키마 | UI 자동화 서버 | `src/knowledge_graph/schema.py`, `queries.py` |
| 화면 등록 GUI·요소 선택기 | Worker | `src/gui/windows/onboarding.py`, `src/executor/picker.py`, `inspector.py` |
| 셀렉터 인벤토리·모니터링 화면 | UI 자동화 서버 | `src/webui/views/` |
| 오프라인 큐·캐시 | Worker | `src/client/cache.py`, `provider.py` |
| 업무 시나리오·인수 기준 | Studio·Bot | `docs/scenarios.md`, `docs/bpmn_coverage.md` |

## 판정 요약

| 분류 | 항목 |
| --- | --- |
| **개념 그대로 가져옴** | 지도/운전사 경계, 패키지+서명+배포 체인, 하트비트로 지시 전달, 실행 이벤트 멱등 키, 로케이터 사다리·승격, 결재/확인 구분, 사전 점검, 오프라인 큐 |
| **코드 참고해 새로 씀** | BPMN 엔진 연결, 에이전트 루프, Center API, 로케이터 실행기, 화면 등록 GUI, 콘솔 화면 |
| **버림** | UI 자동화 서버의 lease(작업 배분), 계약 복사본+드리프트 테스트, git 태그 계약 의존, 구성요소별 환경변수 접두사, 결정 이력이 쌓인 CLAUDE.md, 서버별 별도 웹 화면 |
| **새로 확인 필요** | Windows 데스크톱 조작·캡처, Windows 자동 시작·무인 실행, 봇별 인증, 서비스 앱 공통 계약 |

# 프로토타입 Studio·Bot (Admin 포함)

Python 3.12 고정 · uv 워크스페이스. 저장소 이름은 [대응표](README.md) 참고.

## 구성

| 멤버 | 역할 | 명령 (프로토타입) |
| --- | --- | --- |
| `packages/protocol` | 계약: 실행 이벤트, 매니페스트, 해시, Ed25519 서명 봉투 | — |
| `packages/core` | 런타임: 오케스트레이션(SpiffWorkflow), 에이전트(LangGraph), 도구, 재생 기억, 패키지 빌드, Center 클라이언트 | 패키지 빌드 CLI |
| `packages/qt` | 공용 PySide6 테마, 결재 창 | — |
| `apps/studio` | Qt 클라이언트 + bpmn-js(QtWebEngine) | Studio, 터미널 실행기 |
| `apps/bot` | 현장 실행 호스트, 트레이, 자동 시작 | Bot, Bot 트레이 |
| `apps/admin` | 서명 키, 승인·배포 서명 (CLI만) | Admin |

## 핵심 개념

- 실행 흐름: SpiffWorkflow가 ServiceTask에 도달하면 브리지가 페이로드를 만든다. 페이로드에는 `mission`, `business_parameters`, `execution_environment`, `guardrails`가 담긴다. LangGraph 루프(prime → reason ⇄ execute/heal → evaluate)가 이를 받아 돈다. 결과는 스키마 검증 후 프로세스 변수로 넘긴다.
- 대상 환경: LLM, WEB, DESKTOP, API, DOCUMENT, HYBRID. (새 설계에서는 UI 태스크·서비스 앱 태스크로 나뉜다 — [용어집](../02-glossary.md) 태스크 종류)
- 도구 규칙: `@tool` + docstring이 유일한 설명서다. 예외를 던지지 않고 오류 문자열을 반환한다. `registry.py`가 단일 원본이고, 허용 도구는 화이트리스트다.
- 재생: 성공 궤적을 ChromaDB에 저장한다. 다음에는 LLM 없이 재실행하고, 실패하면 자율 모드로 돌아가 성공 궤적으로 덮어쓴다.
- 데스크톱 3계층: ① 접근성 트리(AT-SPI) → ② 스크린샷 + VLM 좌표 → ③ 사람 확인.
- 사람 개입 두 층: 결재(BPMN UserTask, Center로 올릴 수 있음)와 확인(에이전트 중단, 화면 앞 사람만).
- 화면 설계의 교훈은 [../06-screens/README.md](../06-screens/README.md) §2에 옮겼다.

## 가져올 것

- `orchestration/engine.py`, `bridge.py`, `parser.py`, `preflight.py`의 구조. 크기가 각각 61KB, 33KB, 24KB, 65KB로 크므로 나눠서 다시 쓴다.
- `agent/tools/registry.py`의 화이트리스트 방식.
- `protocol/`의 해시·서명 규칙.
- `docs/scenarios.md`, `docs/bpmn_coverage.md`를 인수 기준으로 쓴다. BPMN 요소 16종 실행 가능, 미지원: 이벤트 기반·복합 게이트웨이, 오류 외 경계 이벤트, 트랜잭션, 애드혹 하위 프로세스, 시그널 시작, 메시지 송신, 데이터 저장소.

## Windows 이식 시 걸리는 것

- `config.py`: `system_python = "/usr/bin/python3"`. AT-SPI 헬퍼를 시스템 Python으로 실행한다.
- `apps/bot/<패키지>/autostart.py`: `~/.config/autostart`, `systemd --user` 전용.
- `agent/tools/desktop.py`의 Windows 백엔드(pywinauto UIA)는 코드만 있고 실기 검증이 없다.
- 스크린샷 경로가 xdg-desktop-portal 중심이다.
- 기본 데이터 위치가 `~/.local/share/...`, `~/.config/...`로 고정되어 있다.

## 버릴 것

- 159KB 작업 지침 파일(CLAUDE.md)의 이력 서술. 결론만 ADR로 옮긴다.
- 궤적 치유와 healer 노드의 `"오류"` 문자열 감지. 오류는 구조화된 결과로 판정한다.
- Center 클라이언트가 core 안에 있는 구조. 서버 통신은 앱 쪽으로 옮긴다.

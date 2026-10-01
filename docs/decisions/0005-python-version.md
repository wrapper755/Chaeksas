# ADR-0005. Python 3.12로 통일

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 (2026-10-01) |
| 날짜 | 2026-10-01 |
| 관련 | ADR-0004 |

## 배경

프로토타입의 Python 버전이 갈렸다.
- 프로토타입 Studio·Bot, 프로토타입 Center: `>=3.12,<3.13` 고정
- 프로토타입 UI 자동화 서버, 프로토타입 Worker: `>=3.11`로 선언했지만 실제로는 3.14로 실행

uv 워크스페이스 하나는 lock 파일 하나이므로 버전 범위를 맞춰야 한다. 클라이언트는 Windows가 주 환경이므로 휠 제공 여부가 중요하다. 대상 패키지는 PySide6, Playwright, SpiffWorkflow, UIA 라이브러리, 임베딩 저장소 등이다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| 3.12 | 프로토타입 핵심(Studio·Bot 런타임)이 검증된 버전. 서드파티 호환 폭이 넓음 | 최신 문법·성능 일부 포기 |
| 3.13 | 중간 | 검증 이력 없음 |
| 3.14 | 프로토타입 UI 자동화 쪽 실사용 버전 | Windows 휠·일부 라이브러리 호환 위험 |

## 결정

**3.12**, `requires-python = ">=3.12,<3.13"`. 코드 문법은 3.12 기준으로 쓴다.

## 구현 — uv가 인터프리터를 관리한다

uv는 단일 실행 파일이고 인터프리터를 직접 내려받아 쓴다. 그래서 **개발 PC에 깔린 시스템 Python 버전은 이 저장소와 상관없다.** 두 가지를 섞지 않도록 네 자리에 못을 박는다 ([ADR-0004](0004-monorepo-uv-workspace.md)).

| 둘 곳 | 값 | 뜻 |
| --- | --- | --- |
| `pyproject.toml`의 `requires-python` | `">=3.12,<3.13"` | 해결·설치의 하한·상한. `uv.lock`에 기록된다 |
| `.python-version` (워크스페이스 루트) | `3.12` | `uv run`·`uv sync`가 고를 버전. `uv python pin 3.12`이 쓴다 |
| `[tool.uv]`의 `python-preference` | `only-managed` | 시스템 Python을 아예 쓰지 않는다 |
| `[tool.uv]`의 `python-downloads` | `automatic` (기본값) | 없으면 내려받는다. CI는 `uv python install 3.12`를 먼저 부른다 |

- `python-preference`·`python-downloads`는 워크스페이스 전역 설정이라 **루트에만** 둔다.
- `only-managed`가 핵심이다. 기본값(`managed`)은 조건이 맞으면 시스템 Python도 집으므로, PC마다 다른 버전이 잡혀 "내 PC에서는 됐다"가 생긴다. `only-managed`면 시스템에 3.13이 있어도 보이지 않는다.
- `uv.lock`은 패치 버전(`3.12.13` 같은)까지 고정하지 않는다. 패치 차이는 허용하고, 그 때문에 문제가 나면 `.python-version`에 전체 버전을 적는다.
- 명령은 `python ...`이 아니라 **`uv run python ...`**으로 쓴다. 예제 생성기(`docs/08-business-examples/_source/build.py`)는 표준 라이브러리만 쓰므로 맨 `python`으로도 돌지만, 워크스페이스가 생기면 `uv run`으로 통일한다.

## 결과

- 쉬워지는 것: 의존성 충돌 가능성 최소. 인터프리터 설치가 PC마다 같아진다 (uv가 같은 빌드를 내려받는다).
- 포기하는 것: 3.13+ 기능. 시스템 Python 재사용(디스크 수백 MB).
- 위험 하나: uv가 주는 인터프리터는 python-build-standalone 빌드다. Linux에서 AT-SPI를 PyGObject·dbus-python으로 붙이면 시스템 GI 라이브러리에 기대는 패키지라 깨질 수 있다 — S1 스파이크에서 확인한다 (Linux 클라이언트는 선택 환경이라 치명적이지는 않다).
- 다시 볼 조건: M1 CI(Windows·Linux)가 안정된 뒤, 핵심 의존성이 모두 3.13 휠을 제공하면 올리는 ADR을 새로 쓴다.

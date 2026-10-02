# CLAUDE.md — Chaeksas 작업 규칙

이 파일은 **지금 지켜야 할 규칙과 문서 위치**만 담는다. 200줄을 넘기지 않는다.
결정의 배경·이력은 여기 쓰지 않고 `docs/decisions/`에 ADR로 남긴다.

## 1. 프로젝트 한 줄

BPMN = 지도, AI = 운전사. **Bot = BPM 프로세스**(업무, Center가 배포). **Bot UI** = 항상 떠 있는 트레이 GUI 프로그램으로 Bot을 다운로드·실행하고, **Worker 프로세스**(화면 없는 REST 서버, Bot이 UI 자동화를 요청)를 실행 관리하고, 확장이 더한 유틸리티(기본 제공: UI 셀렉터 등록)를 띄운다. 공통 기능은 **확장**으로 붙고(첫 내장 확장 = UI 자동화), 서비스 앱은 확장의 서버 부분으로 BPM 프로세스가 API 키로 호출하는 서버 앱(대부분 LLM 앱)이며 앱마다 관리 콘솔에서 키를 발급한다. Studio 개발 실행은 자율 수행, Bot UI 운영 실행은 결정 수행.
서버(Center, 서비스 앱)는 Linux 주, 클라이언트(Studio·Bot UI·Worker 프로세스)는 Windows 주.
자세히: `docs/00-vision.md`, `docs/01-architecture.md`, `docs/02-glossary.md`.

## 2. 문서 위치

| 필요한 것 | 파일 |
| --- | --- |
| 용어 | `docs/02-glossary.md` — 새 용어를 코드에 쓰기 전에 여기 먼저 추가 |
| 구조·경계 규칙 | `docs/01-architecture.md` |
| 구성요소 간 계약 | `docs/03-contracts/` |
| 화면 | `docs/06-screens/` (무엇을 어디에) |
| 모양 (색·글자·구성요소·문구) | `docs/07-style-guide.md`, 토큰 원본 `design/tokens.json` |
| 결정과 이유 | `docs/decisions/NNNN-*.md` |
| 환경 구성·포트 | `docs/04-setup.md` |
| 단계·완료 기준 | `docs/05-roadmap.md` |
| BPM 업무 예제·시험 묶음 | `docs/08-business-examples/` — `bpmn/`·`cases/`·`README.md`·`{finance,scm,hr,ops,feature-examples}.md`는 **생성물이다. 직접 고치지 않는다.** 원본은 `_source/spec_*.py`(예제 정의)와 `_source/exdsl.py`(DSL·생성기). 손으로 쓰는 것은 `writing-guide.md`뿐 |
| 프로토타입 참고 | `docs/reference/` |

## 3. 작업 순서 (반드시)

0. 예제를 고치면 → `_source/spec_*.py`를 고친 뒤 `uv run python docs/08-business-examples/_source/build.py`로 다시 만든다.
   끝내기 전에 `uv run python docs/08-business-examples/_source/build.py --check` (쓰지 않고 검사만, 어긋나면 1). 표준 라이브러리만 쓴다.
   `build.py`는 생성만 하지 않는다 — C14 검사(B3 짝·B11·B12), 호출 대상·DMN 입출력·케이스 필수 입력·결재 폼 칸 타입을 대조해 틀리면 아무것도 쓰지 않고 멈춘다. 커버리지 표와 마일스톤 시험 묶음도 예제에서 자동으로 계산한다.
1. 모르는 것 → `spikes/<주제>/`에서 실험. 실험 코드는 제품 코드에서 import 금지.
2. 실험이 끝나면 → ADR 작성 (`docs/decisions/template.md` 복사). 결론이 "안 된다"여도 쓴다.
3. 구성요소 사이 약속이 바뀌면 → `docs/03-contracts/`를 **먼저** 고치고, 그다음 코드.
4. 화면이 바뀌면 → `docs/06-screens/`를 **먼저** 고치고, 그다음 코드.
5. 구현 → 테스트 → 문서의 "상태" 갱신.
6. 엔진·태스크·확장을 바꾸면 → 영향받는 업무 예제(`docs/08-business-examples/README.md` 커버리지 표)의 케이스를 돌린다. 예제가 계약 공백을 드러내면 예제를 비틀지 말고 계약·ADR에 적는다.

결정을 뒤집을 때는 기존 ADR을 고치지 않는다. 새 ADR을 쓰고, 옛 ADR의 상태를 `대체됨(ADR-XXXX)`으로 바꾼다.

## 4. 문서 규칙

- 문서는 **현재 상태**를 쓴다. "전에는 X였는데 Y로 바꿨다"는 ADR로 보낸다.
- 한 파일이 커지면(대략 500줄) 나눈다.
- 모든 문서는 한국어, 코드·식별자는 원문 그대로.
- 확정되지 않은 내용은 `> 미정:` 또는 `> 제안:`으로 표시한다.
- "프로세스"를 단독으로 쓰지 않는다. 업무는 "BPM 프로세스"(운영 화면 "Bot"), OS 프로세스는 "<이름> 프로세스", 화면 있는 프로그램은 "<이름> UI"·앱 이름 (`docs/02-glossary.md` §0).
- 프로토타입 저장소 이름은 쓰지 않는다. "프로토타입 Studio·Bot / Center / UI 자동화 서버 / Worker"로 쓰고, 대응표는 `docs/reference/README.md` 한 곳에만 둔다.
- 화면 배치도의 상자 안에는 영문 영역 표시만 쓰고, 한글 설명은 표로 뺀다 (글꼴 폭 차이).

## 5. 코드 규칙 (크로스플랫폼 — 클라이언트는 Windows가 주 환경)

- 경로는 `pathlib.Path`만. 문자열로 `/` 붙이기, 하드코딩된 `/home/...`·`/usr/bin/...` 금지.
- 사용자 데이터·설정 위치는 `platformdirs`로 얻는다 (Windows `%LOCALAPPDATA%`, Linux `~/.local/share`).
- 파일 입출력은 항상 `encoding="utf-8"` 명시 (Windows 기본 인코딩은 cp949).
- **한글을 화면에 찍는 도구(생성기·CLI)는 stdout도 UTF-8로 고정한다.** Windows의 기본 코드페이지(cp949·cp1252)에서는 `print("경고: …")` 한 줄에 `UnicodeEncodeError`로 죽는다. `if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")`. `tests/test_generators_on_windows_encoding.py`가 Linux에서도 막는다.
- 외부 프로세스는 `subprocess`에 인자 리스트로 넘긴다. `shell=True`, bash 전용 문법 금지.
- **서버 우선.** 업무 대부분은 서버 BPM 프로세스(「서버 Bot」, 기본값)로 돌고, PC Bot은 UI 조작·현장 확인·PC 전용 자원이 필요할 때만 쓴다 (`docs/decisions/0016-server-first.md`).
- BPM 프로세스는 **실행 위치**(PC / 서버)를 가진다. 서버 실행은 Center가 관리하는 서버 실행기(`apps/server_runner`)가 맡고 동시 실행을 허용한다. 서버 실행 BPM 프로세스에는 UI 태스크·웹/데스크톱 AI 태스크·현장 확인을 넣을 수 없다 (`docs/decisions/0015-run-location.md`).
- **PC 한 대에서 실행 중인 Bot은 하나**, 결재·확인을 기다려도 끝날 때까지 자리를 쥔다. 나머지 요청은 Bot UI 대기열에서 기다린다. Worker의 UI 세션도 한 번에 하나 (`docs/decisions/0014-one-bot-per-pc.md`).
- 자식 프로세스(Bot UI → Worker 프로세스·실행기 하나) 관리는 공통 헬퍼로. `os.killpg`, 그룹 신호는 Windows에 없다. Bot(BPM 프로세스)은 Worker를 띄우거나 끄지 않는다.
- OS 전용 기능(UIA/AT-SPI, 자동 시작, 비밀 저장소)은 인터페이스 뒤에 두고 구현을 OS별로 나눈다.
- 비밀 값(토큰·비밀번호)은 코드·설정 파일·실행 기록에 넣지 않는다. 환경변수 또는 OS 비밀 저장소(`keyring`).
- 포트 숫자를 코드에 직접 쓰지 않는다. 설정 모델의 기본값에만 둔다 (`docs/04-setup.md` §6).
- 환경변수는 `CHK_` 접두사, 중첩은 `__` (`CHK_CENTER__PORT`).
- 웹 화면은 Next.js(`web/`), 데스크톱은 PySide6. **Streamlit은 쓰지 않는다.** 색·크기·간격은 `design/tokens.json`의 토큰만 쓰고 값을 코드에 직접 쓰지 않는다. 상태 표시는 `status_map`의 표기와 색만 (`docs/07-style-guide.md`).
- 웹 화면의 브라우저 코드는 서버 API·토큰을 직접 다루지 않는다. Next.js 서버 쪽(BFF)이 부른다. API 타입은 계약 JSON Schema에서 생성한다.
- **공통 기능은 확장으로 붙인다** (`docs/decisions/0018-extensions.md`). 플랫폼 코드(`core`, `apps/*`)는 특정 확장을 import하지 않고 `packages/extension_api`와 엔트리 포인트 `chaeksas.extensions`로만 다룬다. 확장 하나는 `extensions/<id>/` 폴더 하나(정의·계약·서버·로컬 런타임·클라이언트 기여). 외부 앱은 확장 정의의 HTTP 어댑터로 붙이고 코드를 기여하지 않는다.
- 모든 서비스 앱은 `packages/service_kit`으로 만들고 공통 계약 C11(수행 모드, 자체 API 키 발급·검증, 관리 콘솔)을 지킨다.
- 패키지·BPM 파일에 키 값을 넣지 않는다. 서비스 앱 키는 BPM 프로세스 속성에 **참조 이름**으로만 둔다.
- 결정 수행에서 LLM을 몰래 부르지 않는다. 폴백은 manifest 정책으로만.

## 6. 프로토타입 저장소

프로토타입 4개는 **읽기 전용 참고**다. 수정·import·경로 의존 금지. 개발 PC에 없을 수 있다 — `docs/reference/`만으로 뜻이 통하게 되어 있다.
코드를 가져올 때는 복사한 뒤 이 저장소 규칙에 맞게 고치고, 출처를 커밋 메시지에 남긴다.

## 7. 현재 상태

M1 진행. uv 워크스페이스(Python 멤버 11개)와 `tests/`가 있다. **`contracts`의 C1~C7·C11과 `service_kit`만 내용이 있고**, 나머지 패키지는 docstring만 있는 빈 패키지다.

- 명령: `uv sync --all-packages` → `uv run pytest` (259개 통과. CI가 Windows + Linux x86_64에서, 개발 PC가 Linux aarch64에서 돈다). 검사는 `uv run ruff check .`, `uv run mypy` (인자 없이 — 경로는 `pyproject.toml`에 있다).
- 계약 모델을 고치면 → `uv run python scripts/gen_schemas.py`, 디자인 토큰을 고치면 → `uv run python scripts/gen_tokens.py` (명암비 검사 포함). 둘 다 `--check`가 pytest·CI에 들어 있어 잊으면 깨진다.
- import 이름은 `chaeksas.<이름>`, 확장은 `chaeksas.ext.<id>` ([ADR-0019](docs/decisions/0019-package-names.md)). `src/chaeksas/`에 `__init__.py`를 만들면 조용히 깨진다.
- 의존 방향은 `tests/test_import_direction.py`가 막는다. 새 멤버를 더하면 `tests/test_workspace.py`의 `MEMBERS` 표도 고친다.
- 계약을 고칠 때는 문서(`docs/03-contracts/`)가 원본이다. 문서의 JSON 예시를 테스트가 **문서에서 뽑아** 검증하니(`tests/test_contract_examples.py`), 예시도 같이 고친다.
- 푸시·PR마다 CI가 돈다 (`.github/workflows/ci.yml`): 매트릭스 두 개에서 pytest·ruff·mypy·생성물 최신 여부. 경로를 비교할 때 `str(path)`가 아니라 `as_posix()`를 쓴다 (Windows는 `\`).
- 아직 없는 것: `web/` 뼈대(토큰 CSS만 생성되어 있다), 스파이크 S1~S5, 확장 `extension.json`(C13), 나머지 계약(C8~C10·C12~C14), 외부 의존(PySide6·Playwright). 남은 M1 기준은 `docs/05-roadmap.md`.

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
- **HTTP 헤더 값에 한글을 넣지 않는다.** 헤더는 ASCII라서 보내는 쪽 라이브러리가 요청 자체를 거부한다 (httpx·undici 모두). 사람 이름 같은 값은 퍼센트 인코딩해서 싣고 받는 쪽이 디코딩한다 (C5 `X-CHK-Actor`). 토큰·키도 ASCII만 쓴다.
- **서버 우선.** 업무 대부분은 서버 BPM 프로세스(「서버 Bot」, 기본값)로 돌고, PC Bot은 UI 조작·현장 확인·PC 전용 자원이 필요할 때만 쓴다 (`docs/decisions/0016-server-first.md`).
- BPM 프로세스는 **실행 위치**(PC / 서버)를 가진다. 서버 실행은 Center가 관리하는 서버 실행기(`apps/server_runner`)가 맡고 동시 실행을 허용한다. 서버 실행 BPM 프로세스에는 UI 태스크·웹/데스크톱 AI 태스크·현장 확인을 넣을 수 없다 (`docs/decisions/0015-run-location.md`).
- **PC 한 대에서 실행 중인 Bot은 하나**, 결재·확인을 기다려도 끝날 때까지 자리를 쥔다. 나머지 요청은 Bot UI 대기열에서 기다린다. Worker의 UI 세션도 한 번에 하나 (`docs/decisions/0014-one-bot-per-pc.md`).
- 자식 프로세스(Bot UI → Worker 프로세스·실행기 하나) 관리는 공통 헬퍼로. `os.killpg`, 그룹 신호는 Windows에 없다. Bot(BPM 프로세스)은 Worker를 띄우거나 끄지 않는다.
- OS 전용 기능(UIA/AT-SPI, 자동 시작, 비밀 저장소)은 인터페이스 뒤에 두고 구현을 OS별로 나눈다. OS 분기는 **`if sys.platform == "win32":`로 쓴다** — mypy가 그 비교만 보고 다른 OS의 코드를 지운다 (`IS_WINDOWS` 같은 별명 상수로 분기하면 Windows 전용 API가 Linux에서 오류가 된다). 개발 PC에서 `uv run mypy --platform win32`로 반대쪽도 본다 (CI에도 있다).
- 비밀 값(토큰·비밀번호)은 코드·설정 파일·실행 기록에 넣지 않는다. 환경변수 또는 OS 비밀 저장소(`keyring`).
- 포트 숫자를 코드에 직접 쓰지 않는다. 설정 모델의 기본값에만 둔다 (`docs/04-setup.md` §6).
- 환경변수는 `CHK_` 접두사, 중첩은 `__` (`CHK_CENTER__PORT`).
- 웹 화면은 Next.js(`web/`), 데스크톱은 PySide6. **Streamlit은 쓰지 않는다.** 색·크기·간격은 `design/tokens.json`의 토큰만 쓰고 값을 코드에 직접 쓰지 않는다. 상태 표시는 `status_map`의 표기와 색만 (`docs/07-style-guide.md`).
- 웹 화면의 브라우저 코드는 서버 API·토큰을 직접 다루지 않는다. Next.js 서버 쪽(BFF)이 부른다. API 타입은 계약 JSON Schema에서 생성한다.
- **공통 기능은 확장으로 붙인다** (`docs/decisions/0018-extensions.md`). 플랫폼 코드(`core`, `apps/*`)는 특정 확장을 import하지 않고 `packages/extension_api`와 엔트리 포인트 `chaeksas.extensions`로만 다룬다. 확장 하나는 `extensions/<id>/` 폴더 하나(정의·계약·서버·로컬 런타임·클라이언트 기여). 외부 앱은 확장 정의의 HTTP 어댑터로 붙이고 코드를 기여하지 않는다.
- 모든 서비스 앱은 `packages/service_kit`으로 만들고 공통 계약 C11(수행 모드, 자체 API 키 발급·검증, 관리 콘솔)을 지킨다.
- 패키지·BPM 파일에 키 값을 넣지 않는다. 서비스 앱 키는 BPM 프로세스 속성에 **참조 이름**으로만 둔다.
- 결정 수행에서 LLM을 몰래 부르지 않는다. 폴백은 manifest 정책으로만. **재생이 깨져도 자율로 넘어가지 않는다** — `TaskFailed`로 올려 오류 경계가 받게 한다 ([ADR-0028](docs/decisions/0028-replay-memory.md)).

## 6. 프로토타입 저장소

프로토타입 4개는 **읽기 전용 참고**다. 수정·import·경로 의존 금지. 개발 PC에 없을 수 있다 — `docs/reference/`만으로 뜻이 통하게 되어 있다.
코드를 가져올 때는 복사한 뒤 이 저장소 규칙에 맞게 고치고, 출처를 커밋 메시지에 남긴다.

## 7. 현재 상태

M2 끝, **M3 진행 중** (조각 1 식 → 2·3a 엔진 뼈대·토큰 모형 → **3b 값을 만드는 노드**까지 끝. **3c 바깥 호출**(서비스 앱·AI 태스크·재생)까지 끝. **3d 타이머·메시지·신호·호출**까지 끝. **3e Studio**는 셋으로 나눠 **3e-1 셸·캔버스**·**3e-2 속성 패널·검사**·**3e-3 시험 실행**까지 끝. 남은 조각: 3e-4 케이스 편집기·패키지 내보내기, 도구 4종, 3f 예제 `_source` 수정 + 인수 시험, 3g 실행 기록 전송). uv 워크스페이스(Python 멤버 11개)와 `tests/`가 있다. **`contracts`의 C1~C7·C11·C13·C14(DMN 포함), `service_kit`, `extension_api`, `core`의 BPMN 엔진·식·파일·보내기·서비스 앱 호출·AI 태스크·재생·확장 호스트·자식 프로세스 헬퍼, `apps/bot_ui`, **`apps/studio`의 셸·캔버스·작업 폴더**, 내장 확장 `ui-automation`의 `extension.json`에 내용이 있고**, 나머지 패키지는 docstring만 있는 빈 패키지다. 확장의 클라이언트 코드(UI 태스크 수행·편집기·셀렉터 등록)는 모양만 맞춘 뼈대이고 속은 M4다. `web/`은 pnpm 워크스페이스(앱 2 + 패키지 3)에 구성요소 7개·계약 타입 생성이 있고, **Center 콘솔(CON-00·03·11)과 서비스 앱 콘솔(SVC-00~03)이 실제로 돈다**. `qt`는 테마 적용(`apply_theme()`)과 포함 글꼴까지 있고 위젯은 없다. `apps/center`는 **키·등록·하트비트·패키지까지 돈다** (`uv run chk-center`). 서버 구성은 `deploy/compose.yaml` 한 번으로 Center + Center 콘솔이 뜬다 (확인함). `apps/bot_ui`는 **트레이·설정(BUI-03)·등록·하트비트·대기열까지 돈다** (`uv run chk-bot-ui`, Windows 11 실기 확인 끝 — 이슈 #3) — Bot 실행(엔진)은 M3이다.

- 명령: `uv sync --all-packages` → `uv run pytest` (1206개 중 Linux에서 1204개 통과·2개 건너뜀, Windows에서 1205개 통과·1개 건너뜀 — 건너뛰는 것은 OS 전용이다 (Windows 네이티브 플랫폼의 메뉴 글꼴, `CHK_TEST_AUTOSTART=1`로 켜는 자동 시작 실기). CI가 Windows + Linux x86_64에서, 개발 PC가 Linux aarch64에서 돈다). 검사는 `uv run ruff check .`, `uv run mypy` (인자 없이 — 경로는 `pyproject.toml`에 있다).
- 계약 모델을 고치면 → `uv run python scripts/gen_schemas.py`, 디자인 토큰을 고치면 → `uv run python scripts/gen_tokens.py` (명암비·간격 배수 검사 포함). 둘 다 `--check`가 pytest·CI에 들어 있어 잊으면 깨진다.
- 웹은 `web/`에서 pnpm (`pnpm install` → `pnpm dev`·`pnpm typecheck`·`pnpm build`). **계약을 고치면 두 단계다** — `gen_schemas.py`로 스키마, 그다음 `pnpm gen:api-types`로 TypeScript 타입. 색·크기는 토큰만 쓴다 (`tokens.css`·`theme.css`는 생성물). 상태 표기는 생성된 `status-map.ts`에 있는 것만 쓴다.
- import 이름은 `chaeksas.<이름>`, 확장은 `chaeksas.ext.<id>` ([ADR-0019](docs/decisions/0019-package-names.md)). `src/chaeksas/`에 `__init__.py`를 만들면 조용히 깨진다.
- 의존 방향은 `tests/test_import_direction.py`가 막는다. 새 멤버를 더하면 `tests/test_workspace.py`의 `MEMBERS` 표도 고친다.
- 계약을 고칠 때는 문서(`docs/03-contracts/`)가 원본이다. 문서의 JSON 예시를 테스트가 **문서에서 뽑아** 검증하니(`tests/test_contract_examples.py`), 예시도 같이 고친다.
- 푸시·PR마다 CI가 돈다 (`.github/workflows/ci.yml`): 매트릭스 두 개에서 pytest·ruff·mypy·생성물 최신 여부. 경로를 비교할 때 `str(path)`가 아니라 `as_posix()`를 쓴다 (Windows는 `\`).
- 확장은 엔트리 포인트 `chaeksas.extensions`로 찾는다. 확장 하나를 더하면 `extension.json`을 그 확장의 **파이썬 패키지 안**에 두고(호스트가 `importlib.resources`로 읽는다), `pyproject.toml`에 엔트리 포인트를 적는다. 기여의 `entry`는 그 확장 패키지 안만 가리킬 수 있다. 설치 파일에 넣는 일은 `core`가 주는 PyInstaller 훅이 하므로 빌드 인자를 적지 않는다 ([ADR-0024](docs/decisions/0024-desktop-packaging-extensions.md)).
- 데스크톱은 `apply_theme(app)` 한 줄로 테마를 쓴다 (글꼴 등록 + QSS + 팔레트). Qt 테스트는 `QT_QPA_PLATFORM=offscreen`으로 화면 없이 돈다.
- Studio 캔버스는 **QtWebEngine 안의 bpmn-js**다 (`apps/studio/canvas.py`, ADR-0022). Python ↔ JS는 **QWebChannel 하나**이고 요청 id로 짝을 맞춘다 (`runJavaScript`는 Promise를 못 받는다). bpmn-js 배포본은 `web/packages/bpmn-canvas`가 판을 고정해 `apps/studio/.../web/vendor/`로 **복사하고 복사본을 커밋한다** — 파이썬 쪽에 Node가 없기 때문이다 (ADR-0029). `chk:*` moddle 설명은 `scripts/gen_moddle.py`가 C14 모델에서 만든다. 둘 다 `--check`가 CI에 있다 (배포본은 웹 작업, 설명은 파이썬 작업).
- Studio 속성 패널(STU-04)의 「JSON」 탭은 **C14 모델(`ELEMENT_MODELS`)로 그 자리에서 검증한다** — 저장한 뒤 실행 전 검사에서야 아는 것보다 낫다. 「적용」은 캔버스의 `setProperties`를 거친다 — **XML을 파이썬이 직접 만지지 않는다** (실행 취소·「저장 안 한 변경」이 깨진다). moddle 타입 이름은 대문자로 시작하고(`chk:AiTask`) C14 이름은 소문자로 시작한다(`aiTask`) — 경계에서 바꾼다.
- Studio 시험 실행은 `apps/studio/runner.py`다 — **스레드를 만들지 않고** `QTimer`가 엔진을 민다. 멈추면(`blocked()`) 케이스가 시킨 대로 답하거나 메시지를 넣고, 타이머는 앞당긴다. **케이스가 틀린 답을 주면 그 자리에서 끝낸다** (다음 틱에 또 같은 일이 생겨 영원히 돈다). 자율 수행이 배운 것은 **Studio가** 패키지에 적는다 (엔진은 파일을 쓰지 않는다).
- **Studio는 바깥으로 웹훅을 쏘지 않는다** — 시험 수신기(`receiver.py`)로만 간다. 메일은 담아 두기만 한다. 개발 PC에서 실수로 바깥에 쏘는 일을 막는 것이다 (C14는 `$test_receiver`만 예외로 둔다).
- **BPMN을 글자로 견주지 않는다** — bpmn-js가 DI 순서·기본값 속성·`exporter`를 바꾼다. 시험·「저장 안 한 변경」 판단은 **뜻으로** 본다 (ADR-0022).
- 자식 프로세스(Worker·실행기)는 `chaeksas.core.processes`만 쓴다 — Windows는 **Job Object**로 묶어 트리째 끄고, 그 밖에서는 프로세스 그룹에 신호를 보낸다. `os.killpg`를 직접 부르지 않는다 (ADR-0023). 자식에게 UTF-8 입출력(`PYTHONUTF8`)도 물려준다 — 출력을 로그 파일로 돌리면 Windows에서 한글을 찍다 죽는다.
- Bot UI의 비밀(Center API 키·서비스 앱 키)은 `credentials.py`를 거친다 — OS 비밀 저장소가 없으면 **저장이 분명히 실패한다**(평문으로 흘리지 않는다). 읽기는 환경변수가 먼저다 (개발·CI).
- C14(BPMN `chk:*`)는 모델·읽기·검사 B1~B14가 있다. 업무 예제 50개를 읽고 검사하는 테스트가 그것을 지킨다 — 예제를 고치면 함께 돈다.
- Center는 `apps/center`에 있고 **API만** 가진다 (콘솔은 `web/apps/center-console`, ADR-0017). 비밀은 환경변수로만 준다 — `CHK_CENTER__ADMIN_TOKEN`이 없으면 쓰기 API가 막힌다.
- 콘솔의 브라우저 코드는 토큰을 모른다. 세션은 **암호화된 httpOnly 쿠키**(`lib/session.ts`), Center 호출은 **서버에서만**(`lib/center.ts`, `server-only`). 쓰기는 Server Action으로 한다.
- 서비스 앱 콘솔(`web/apps/svc-console`)은 **한 벌로 모든 서비스 앱**을 그린다 — 어느 앱인지는 `CHK_SVC_CONSOLE__APP_URL`이 정하고, 앱 이름·버전·고유 메뉴는 `/admin/v1/status`의 `app_id`에서 온다. 관리 API(`service_kit`의 `admin.py`)는 **관리자 토큰으로만** 열린다 — `CHK_SVC_<앱>__ADMIN_TOKEN`이 없으면 503이고, 업무 키로 부르면 403이다 (키를 가진 Bot이 다른 키를 발급하지 못한다).
- BPMN 실행은 **모듈 셋**이고 **쓰는 쪽은 `chaeksas.core.engine` 하나만 본다** (나머지를 다시 내보낸다): `core.run_state`(상태·수행기 규약 — `Run`·`Token`·`RunEnv`·`Context`·`Go`/`Wait`/`Consume`), `core.nodes`(노드마다 무엇을 하는지 — **노드 종류를 더하는 자리**, `DEFAULT_HANDLERS`), `core.engine`(한 걸음씩 돌리는 것). 셋으로 가른 것은 순환 import 없이 수행기를 늘리기 위해서다 — 수행기는 `run_state`만 보고, 엔진이 수행기를 모아 꽂는다.
- 엔진은 **한 걸음씩**(`step()`) 돌고, 사람·메시지·타이머를 기다리면 `WAITING`으로 멈춘다. **스레드를 만들지 않는다** — 시간은 `RunEnv.clock`이 주고 부르는 쪽이 `tick()`을, 메시지는 `deliver()`를, 신호는 `signal()`을 부른다. 「멈췄나」는 `blocked()`가 답한다 (`step()`의 반환값이 아니다 — 토큰 하나가 멈춰도 `WAITING`이 된다). 경계 이벤트(타이머·메시지·신호)는 **멈춰 있는 동안에만** 켜지고, 중단이면 호스트가 쥔 것(결재 요청·안쪽 토큰)을 걷는다. 호출(`callActivity`)은 **같은 `run_id`로 안쪽 실행**을 띄운다 (`run_started`는 하나뿐이다). **토큰이 여러 개일 수 있다** (병렬·포함 게이트웨이·하위 프로세스). **모르는 노드는 조용히 지나가지 않고 실행을 실패로 끝낸다.** 업무 실패는 `TaskFailed`로 올려야 오류 경계가 받는다 — 식 오류·그림 오류·허용 밖 경로(`path_denied`)는 경계로 받지 않는다 (고쳐야 할 버그다). 실행 기록은 `core.run_log`가 C3 그대로 `runs/<run_id>.jsonl`에 먼저 쓴다 (업무 값은 `sanitize()`가 걸러 개수만 남긴다).
- **엔진이 바깥 세계에 닿는 길은 `RunEnv` 하나**다 — 파일(`core.files.Workspace`), 보내기(`core.senders`), 서비스 앱(`core.services`), 모델(`core.llm`), 도구, 같은 패키지의 DMN 결정. 실행하는 쪽이 `Engine.start(..., env=…)`로 준다. **기본값은 아무것도 못 한다** — 어댑터가 없으면 파일도 못 쓰고 메일도 못 보내고 모델도 못 부른다 (조용히 넘어가지 않는다). **주소·키 값은 어댑터만 안다** (ADR-0013 — BPM 프로세스·실행 기록에는 참조 이름만).
- 재생(결정 수행)은 `core.replay`다 — 명세는 **패키지 안 `memory/specs.json`**이고 배포된 Bot은 **읽기만** 한다. 태스크마다 `chk:aiTask.replay`(`plan`·`full`·`none`)로 고르고, **도구 인자는 값이 아니라 `{변수}` 템플릿**으로 적는다 (입력이 달라져도 같은 명세가 맞게). 자율 수행이 배운 것은 `Run.learned`에 담기고 **엔진은 파일을 쓰지 않는다**.
- AI 태스크(운전사)는 `core.agent`, 모델에 닿는 길은 `core.llm`이다 — **OpenAI 호환 HTTP를 우리 루프로** 부른다 ([ADR-0027](docs/decisions/0027-llm-connection.md)). 도구 허용 목록은 `chk:aiTask.tools`가 정하고 **밖을 부르면 실행 오류**다. 결과는 `results: {이름: 타입}`대로 검증하고 틀리면 **업무 실패**다 (모델은 가끔 틀린다). 벤더 SDK·에이전트 프레임워크는 쓰지 않는다 (설치 파일이 45~219 MB 커지고 궤적을 우리가 못 쥔다).
- 파일은 **출력 폴더**(쓰기·상대 경로의 기준)와 **읽기 허용 폴더** 안만 된다. 변수에 들어가는 경로는 **BPM 프로세스가 적은 그대로**이고, 실행 기록에는 **경로를 남기지 않는다** (파일 이름에 거래처 이름이 들어간다).
- DMN은 `chaeksas.contracts.dmn`이 읽고 판정한다 (형식 해석이라 계약 쪽이다). FEEL 전체가 아니라 **C14에 적은 입력 칸 문법만** 받고, 그 밖은 읽기 단계에서 거부한다. 입력 이름은 `label`이 아니라 `inputExpression` 본문이다.
- 식 `chk-expr`·스크립트·템플릿은 `chaeksas.core.expr`다 (ADR-0025). `eval`을 쓰지 않는다 — 허용한 AST 노드만 걷는다. **도우미 함수를 더하면** `core.helpers.HELPERS`와 ADR-0025의 표를 함께 고친다 (시험이 둘을 대조한다). 식에는 순수 함수만 둔다 — 디스크·환경을 읽는 것은 태스크로 (`chk:fileList`가 그 예다).
- `tests/test_core_engine.py`의 `test_no_example_breaks_the_engine_in_an_unexpected_way`가 **진행 눈금**이다 — 예제 50개를 돌려 끝까지 가는 것·기다리는 것을 적어 둔다. 조각마다 그 수를 올리고 목록을 고쳐 적는다.
- 아직 없는 것: Studio의 속성 패널·시험 실행(M3 남은 조각), AI 태스크의 도구 4종, 배포·작업·결재·리소스 목록(M5), Qt 공용 위젯, HTTP 어댑터 해석기(규격만 있다), 계약 코드 C8~C10·C12, Playwright. 남은 M1 기준은 `docs/05-roadmap.md`.

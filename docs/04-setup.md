# 04. 개발 환경 구성

> 상태: **일부 확인됨.** `uv sync --all-packages` → `uv run pytest`가 **CI(Windows Server + Linux x86_64)와 개발 PC(Linux aarch64)에서 돈다.** `web/`·Playwright·Docker 쪽과 Windows 데스크톱(Studio 창·트레이·UIA)은 그 단계가 오면 갱신한다.
> 이 문서는 **새 PC에서 이 문서만 보고** 환경을 만들 수 있어야 한다. 막히는 곳이 있으면 그 자리에서 고친다.

## 1. 어떤 PC에 무엇을 까는가

| PC 역할 | OS | 필요한 것 |
| --- | --- | --- |
| 클라이언트 개발 (Studio·Bot UI·Worker 프로세스) | **Windows 10/11 (주)**, Linux | Git, uv, Python, Playwright 브라우저 |
| 서버 개발 (Center·서버 실행기·서비스 앱) | **Linux (주)**, Windows | Git, uv, Python, Docker, Ollama |
| 한 대로 전부 | Windows 또는 Linux | 위 둘 다 |

## 2. 공통 도구

| 도구 | 버전 | 용도 |
| --- | --- | --- |
| Git | 최신 | 소스 관리 |
| uv | 최신 | Python 설치·가상환경·의존성 (pip·venv 직접 사용 안 함) |
| Python | **3.12** ([ADR-0005](decisions/0005-python-version.md)) | **직접 깔지 않는다 — uv가 내려받는다.** 시스템 Python 버전은 상관없다 |
| Docker | 최신 | 서버 구성(`deploy/compose.yaml`) — Center·콘솔·서비스 앱 (선택: PostgreSQL) |
| Ollama | 최신 | 로컬 LLM (외부 API를 쓰면 생략) |
| Node.js | LTS | 웹 화면(Next.js) 개발·빌드 ([ADR-0017](decisions/0017-web-nextjs-design-system.md)). 웹 화면을 만지지 않는 PC는 생략 |
| pnpm | 최신 (corepack으로) | `web/` 의존성 |

> **Python은 uv가 관리한다.** PC에 Python이 없어도, 또는 다른 버전(3.13·3.14)이 깔려 있어도 된다. 워크스페이스 루트의 `.python-version`(`3.12`)과 `[tool.uv]`의 `python-preference = "only-managed"`가 uv가 내려받은 3.12만 쓰게 한다 ([ADR-0005](decisions/0005-python-version.md) 구현). 확인: `uv python find 3.12`가 `.../uv/python/cpython-3.12-.../bin/python3.12`를 가리키면 맞다.
> 그래서 명령은 `python ...`이 아니라 `uv run python ...`으로 쓴다. 맨 `python`은 PC마다 다른 인터프리터다.

## 3. Windows (클라이언트 주 환경)

PowerShell에서:

```powershell
# 1) Git, uv 설치
winget install --id Git.Git -e
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2) 저장소 받기 (경로에 한글·공백이 없는 곳 권장)
git clone https://github.com/wrapper755/Chaeksas.git C:\dev\Chaeksas
cd C:\dev\Chaeksas

# 3) Python과 의존성 (uv가 3.12를 내려받는다)
uv sync --all-packages
uv run pytest

# 4) Playwright 브라우저 (M1 이후)
uv run playwright install chromium
```

### 웹 화면 (Windows·Linux 같음)

```powershell
# Node.js LTS 설치 (Windows: winget, Linux: 배포판 패키지 또는 nvm)
winget install --id OpenJS.NodeJS.LTS -e
corepack enable          # pnpm 사용 준비 (버전은 web/package.json의 packageManager가 정한다)
cd web
pnpm install
pnpm dev                 # 콘솔 둘을 함께 띄운다 (8501, 8001)
pnpm --filter @chaeksas/center-console dev   # 하나만 — http://localhost:8501
```

| 명령 (`web/`에서) | 하는 일 |
| --- | --- |
| `pnpm dev` | 콘솔 둘을 함께 띄운다 (Center 8501, 서비스 앱 8001) |
| 환경변수 | Center 콘솔: `CHK_CONSOLE__CENTER_URL`(기본 `http://localhost:8800`), `CHK_CONSOLE__SESSION_SECRET`(**필수**, 16자 이상 — 로그인 쿠키를 암호화한다) |
| 환경변수 | 서비스 앱 콘솔: `CHK_SVC_CONSOLE__APP_URL`(기본 `http://localhost:8000` — **어느 서비스 앱의 콘솔인지는 이 값이 정한다**), `CHK_SVC_CONSOLE__SESSION_SECRET`(**필수**, 16자 이상) |
| `pnpm build` | 둘 다 제품 빌드 (`output: standalone`) |
| `pnpm typecheck` | 모든 패키지·앱의 TypeScript 검사 |
| `pnpm gen:api-types` | 계약 JSON Schema → TypeScript 타입 |
| `pnpm check:api-types` | 그 타입이 최신인지 검사만 (CI가 쓴다) |

- **고정한 버전** ([ADR-0017](decisions/0017-web-nextjs-design-system.md) — 「버전은 M1에서 고정」): Node 22 LTS, pnpm 10.32.1, Next.js 16.3.8, React 19.3.0, TypeScript 7.0.2, Tailwind CSS 4.3.3, lucide-react 1.50.0. `web/.npmrc`가 `save-exact=true`라 새 의존성도 정확한 버전으로 적힌다.
- 계약을 고치면 **두 단계**다: `uv run python scripts/gen_schemas.py` (스키마) → `pnpm gen:api-types` (타입). 손으로 타입을 쓰지 않는다.
- 토큰을 바꾸면 `uv run python scripts/gen_tokens.py`로 웹 CSS·Tailwind 테마·상태 표·Qt QSS를 다시 만든다.
- Tailwind 4는 설정 파일이 없다 — 테마가 CSS(`@theme`)다. 그래서 토큰 생성기가 `web/packages/ui/src/theme.css`를 만든다.
- 사내망에서 글꼴을 외부 CDN으로 받지 않는다. Pretendard·JetBrains Mono는 **저장소에 들어 있다** (웹 `web/packages/ui/src/fonts/`, 데스크톱 `packages/qt/src/chaeksas/qt/fonts/`). 따로 깔 것이 없다.

### Windows 주의점

| 문제 | 증상 | 대처 |
| --- | --- | --- |
| 기본 인코딩 cp949 | 한글 파일 읽기에서 `UnicodeDecodeError` | 코드에서 `encoding="utf-8"` 명시 (CLAUDE.md §5). 개발 PC에는 `PYTHONUTF8=1` 환경변수 설정 |
| 줄바꿈 CRLF | BPMN·YAML diff가 전부 바뀜 | 저장소의 `.gitattributes`가 LF로 고정. `git config --global core.autocrlf false` 권장 |
| 긴 경로 | Playwright·Qt 설치 중 경로 오류 | 짧은 경로(`C:\dev\`)에 clone. 필요하면 `git config --global core.longpaths true` |
| 화면 배율(125%·150%) | 스크린샷 좌표와 클릭 위치가 어긋남 | 프로세스를 Per-Monitor DPI Aware로 선언 (M1 스파이크에서 확인) |
| 루프백 방화벽 알림 | Worker가 8899를 열 때 방화벽 창 | 127.0.0.1에만 바인드하면 보통 뜨지 않음. 뜨면 "개인 네트워크"만 허용 |
| 백신 실시간 검사 | `uv sync`, Playwright 설치가 매우 느림 | 개발 폴더를 검사 예외에 추가 (조직 정책 확인) |
| 실행 정책 | `.ps1` 스크립트 실행 거부 | 스크립트 대신 `uv run <명령>`을 쓴다 |
| 포트가 이미 쓰임 | `pnpm dev`가 `EADDRINUSE: :::8501`로 죽음 | 다른 프로그램(프로토타입 Streamlit도 8501을 쓴다)이 잡고 있다. `pnpm --filter <앱> exec next dev --port <빈 포트>`로 옮겨 띄운다 |

## 4. Linux (서버 주 환경)

```bash
# 1) uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) 저장소와 의존성 (uv가 3.12를 내려받는다)
git clone https://github.com/wrapper755/Chaeksas.git ~/dev/Chaeksas && cd ~/dev/Chaeksas
uv sync --all-packages
uv run pytest

# 3) Ollama (로컬 LLM을 쓸 때)
curl -fsSL https://ollama.com/install.sh | sh

# 4) Qt 테스트를 돌릴 때만 (화면 없이 돌려도 그래픽 라이브러리가 필요하다)
sudo apt-get install -y --no-install-recommends \
  libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libfreetype6
```

- **Qt 테스트는 화면이 없어도 돈다** — `QT_QPA_PLATFORM=offscreen`을 테스트가 스스로 켠다. 위 라이브러리가 없으면 그 테스트만 건너뛴다 (CI는 깔고 돌린다).
- PySide6는 `uv sync`가 받는다. `packages/qt`는 **Essentials만** 쓰고, QtWebEngine이 든 Addons는 Studio가 따로 받는다 ([ADR-0022](decisions/0022-studio-canvas.md)·[ADR-0024](decisions/0024-desktop-packaging-extensions.md) — Bot UI 설치 파일을 작게 두려는 것이다).

서버 쪽 구성(Center·Center 콘솔·서비스 앱과 그 관리 콘솔)은 `deploy/compose.yaml` **한 번으로** 뜬다 — Windows에서도 Docker Desktop으로 같은 서버를 띄운다. 레지스트리는 서비스 앱 안의 SQLite 한 파일이라 따로 세울 DB가 없다 ([ADR-0040](decisions/0040-registry-storage-sqlite.md)).

## 5. 설정과 비밀

- 설정 파일: 저장소의 `configs/*.example.yaml`을 복사해 쓴다 (M1).
- 비밀(토큰·DB 비밀번호·API 키): `.env` (git 제외) 또는 OS 비밀 저장소. 설정 파일·코드에 넣지 않는다.
- 환경변수 접두사: **`CHK_`** 하나. 중첩은 `__` (예: `CHK_CENTER__PORT`, `CHK_CENTER__API_KEY`). [ADR-0011](decisions/0011-config-ports-env.md)
- 우선순위: 환경변수 > `.env` > 설정 파일 > 기본값.
- 서비스 앱 API 키: 평소에는 OS 비밀 저장소. 개발·CI에서만 `CHK_SERVICE_APP__API_KEY`로 넣을 수 있다.
- 서버 실행기: 들어오는 포트가 없다 (Center로 접속만). **화면이 없으니 설정 파일도 없다** — 환경변수로만 설정한다: `CHK_SERVER_RUNNER__CENTER_URL`(기본 `http://localhost:8800`), `CHK_SERVER_RUNNER__MAX_CONCURRENCY`(동시 실행 상한, 기본 10), `CHK_SERVER_RUNNER__NAME`(비우면 호스트 이름), `CHK_SERVER_RUNNER__HEARTBEAT_S`(첫 주기, 기본 10 — 그다음은 Center가 주는 `next_heartbeat_s`를 따른다), `CHK_SERVER_RUNNER__RETRY_S`(닿지 못했을 때, 기본 30), `CHK_SERVER_RUNNER__DATA_DIR`. **Center API 키(서버 실행기용)는 `CHK_SERVER_RUNNER__CENTER_API_KEY`가 주 경로다**(서버에서는 컨테이너·systemd가 환경변수로 준다) — OS 비밀 저장소(`chaeksas-server-runner`, 이름 `center_api_key`)도 읽지만 환경변수가 이긴다. 서비스 앱 키는 `CHK_SERVER_RUNNER__SVC__<참조 이름>`(Bot UI·Studio와 같은 규칙, [ADR-0013](decisions/0013-api-keys.md)). 띄우는 것은 `uv run chk-server-runner`이고 `--once`는 **등록하고 하트비트까지 한 번** 해 보고 상태 한 줄을 찍는다(설치 확인용 — 끝 코드 0/1/3이 「됐다」·「사람이 고쳐야 한다」·「닿지 못했다」를 가른다). 배포는 하트비트로 받아 `<데이터>/bots/<id>/<버전>/`에 푼다 (Bot UI와 같은 자리 규칙). 실행 기록은 `<데이터>/runs/<run_id>.jsonl`이고(파일이 원본이다 — C3) 하트비트 뒤에 Center로 보낸다. **`--once`는 작업을 받지 않는다** — 곧 끝나는 프로세스가 실행 스레드를 버리면 안 된다 (받지 않은 작업은 다음 하트비트에 다시 실린다, C4). **SIGTERM에 곱게 끝낸다** ([ADR-0015](decisions/0015-run-location.md), C12).
- Bot UI 대기열 크기: 기본 20, `CHK_BOT_UI__QUEUE__MAX`. 실행 자리(동시 실행 Bot 수)는 1로 고정이라 설정이 없다 ([ADR-0014](decisions/0014-one-bot-per-pc.md)).
- Worker 프로세스는 Bot UI가 띄운다. 개발 PC에도 Bot UI를 설치해 켜 두면 Studio 시험 실행이 그 Worker를 쓴다 — Bot UI가 `<Bot UI 데이터>/runtimes/worker/`에 남긴 `runtime.json`(포트)과 토큰 파일로 찾는다. Bot을 돌릴 때는 Bot UI가 그 Bot이 쓰는 확장의 Worker를 **먼저 띄운다**.
- Studio 시험 실행의 서비스 앱 키(개발용): 환경변수 `CHK_STUDIO__SVC__<참조 이름>`(영대문자·숫자·`_`로 바꾼 이름, 예: `CHK_STUDIO__SVC__TEST_UI`) 또는 OS 비밀 저장소(`chaeksas-studio`, 이름 `svc:<참조 이름>`). Studio 설정(STU-10 「서비스 앱 키」)에서 넣으면 비밀 저장소로 간다. 모델 키도 같다 — 「LLM」에서 넣거나 `CHK_STUDIO__LLM__API_KEY`(이것이 이긴다).
- Bot UI(실행기)의 서비스 앱·외부 앱 키: 평소에는 OS 비밀 저장소(`chaeksas-bot-ui`, 이름 `svc:<참조 이름>`, BUI-10에서 넣는다). 개발·CI에서는 `CHK_BOT_UI__SVC__<참조 이름>`(영대문자·숫자·`_`, 예: `CHK_BOT_UI__SVC__OCR_KEY`) — Studio와 같은 규칙이다. **외부 앱 키도 같은 창고**를 쓴다 (정의가 참조 이름만 적는다, [ADR-0013](decisions/0013-api-keys.md)).
- Center API 키: Center 콘솔(CON-11)에서 발급해 Bot UI 설정·Studio 설정에 넣는다. 개발·CI에서만 `CHK_CENTER__API_KEY`. Studio 쪽은 STU-10 「Center」에서 넣으면 OS 비밀 저장소(`chaeksas-studio`, 이름 `center_api_key`)로 가고, 비밀 저장소가 없는 환경(헤드리스 CI)에서는 `CHK_STUDIO__CENTER_API_KEY`로 준다(이것이 이긴다).
- Studio: `uv run chk-studio` (캔버스는 QtWebEngine이라 `pyside6-addons`가 함께 깔린다). 작업 폴더·설정은 사용자 데이터 폴더의 `studio/`이고 환경변수로 덮어쓴다 — `CHK_STUDIO__DATA_DIR`, `CHK_STUDIO__CENTER__URL`, `CHK_STUDIO__LLM__BASE_URL`, `CHK_STUDIO__LLM__MODEL`, `CHK_STUDIO__READABLE_DIRS`.
- Bot UI: `uv run chk-bot-ui` (트레이에 뜬다. 트레이가 없는 환경이면 메인 창으로 뜬다). 설정은 BUI-03 창에서 하고 파일은 사용자 데이터 폴더의 `settings.json`이다. 환경변수로 덮어쓸 수 있다 — `CHK_BOT_UI__CENTER__URL`, `CHK_BOT_UI__QUEUE__MAX`, `CHK_BOT_UI__WORKER__PORT`, `CHK_BOT_UI__AUTOSTART`, `CHK_BOT_UI__DATA_DIR`. **Center API 키는 OS 비밀 저장소**에 있고, 비밀 저장소가 없는 환경(헤드리스 CI)에서는 `CHK_BOT_UI__CENTER_API_KEY`로 준다.
- 서비스 앱 관리자 토큰: `CHK_SVC_<앱 id>__ADMIN_TOKEN` (예: `CHK_SVC_UI_AUTOMATION__ADMIN_TOKEN`). **이 토큰이 없으면 그 앱의 관리 API(`/admin/v1/*`)가 503으로 닫혀 있다** — 빈 토큰으로 열리지 않는다 ([C11](03-contracts/C11-service-app-common.md) §관리 API). 서비스 앱 API 키는 그 콘솔(SVC-02)에서 발급해 Bot UI 설정·Studio 설정에 **참조 이름**으로 넣는다.
- 서비스 앱의 모델: `CHK_SVC_<앱 id>__LLM__BASE_URL`·`__LLM__MODEL`·`__LLM__API_KEY`(선택, 비밀). 없으면 모델이 필요한 작업만 503 `llm_unavailable`이고 나머지는 돈다 ([C11](03-contracts/C11-service-app-common.md) §모델 연결).

## 6. 포트

아래 기본값을 쓰고, 바꿔야 하면 설정 파일 또는 환경변수로 바꾼다. 코드에는 포트 숫자를 직접 쓰지 않는다 ([ADR-0011](decisions/0011-config-ports-env.md)). 이 표가 기본값의 원본이다.

| 구성요소 | 기본 포트 | 바인드 | 바꾸는 환경변수 |
| --- | --- | --- | --- |
| Center API | 8800 | 서버 | `CHK_CENTER__PORT` |
| Center 콘솔 (웹) | 8501 | 서버 | `CHK_CONSOLE__PORT` |
| UI 자동화 앱 API | 8000 | 서버 | `CHK_SVC_UI_AUTOMATION__PORT` |
| 다음 서비스 앱 | 8010부터 10씩 | 서버 | `CHK_SVC_<앱 id>__PORT` |
| 모의 앱 16개 (`samples/`, 개발·시험용) | 8010부터 10씩 — 순서는 `uv run chk-mock-apps list` | **127.0.0.1** | `CHK_SVC_<앱 id>__PORT` |
| Worker 로컬 API | 8899 | 127.0.0.1 고정 | `CHK_WORKER__LOCAL_API__PORT` |
| Bot UI 메시지 수신 (ReceiveTask·메시지 시작 이벤트) | 8790 | 127.0.0.1 기본 | `CHK_BOT_UI__WEBHOOK__PORT` |
| UI 자동화 앱 관리 콘솔 | 8001 | 서버 | `CHK_SVC_UI_AUTOMATION__CONSOLE_PORT` |
| Ollama | 11434 | 로컬 또는 서버 | `CHK_LLM__BASE_URL` |

> 주의: 프로토타입과 같은 기본 포트다. 한 PC에서 프로토타입과 새 구성요소를 동시에 띄우면 충돌하므로, 그때는 환경변수로 한쪽을 옮긴다.
>
> 모의 앱은 `uv run chk-mock-apps serve` 하나로 **전부 한 포트(8010)**에 `/<app_id>` 밑에 뜬다 — 열여섯 포트를 쓰지 않아도 된다. 인증 없는 제어 길(`/mock/v1/scenario`)이 있어 127.0.0.1에만 바인드한다 (`samples/README.md`).
>
> `docker compose`로 띄울 때는 `.env`의 `CHK_CENTER__HOST_PORT`·`CHK_CONSOLE__HOST_PORT`가 **호스트 쪽 포트만** 옮긴다 (컨테이너 안의 포트는 위 표 그대로다).

## 7. 시험 돌리기와 **건너뛰는 것**

`uv sync --all-packages` → `uv run pytest`. `addopts`에 `-q`가 있으니 **`-q`를 또 주면 셈이 안 보인다**. 왜 건너뛰는지는 `uv run pytest -rs`가 말해 준다.

건너뛰는 것은 두 갈래다.

| 갈래 | 무엇 | 어디서 도나 |
| --- | --- | --- |
| **OS 전용** | 네이티브 메뉴 글꼴, 데스크톱 UIA 백엔드와 그것을 쓰는 예제(BX-17·BX-04·FX-05·BX-36), Bot UI·Studio 확장 연결 한 바퀴 | Windows에서만 |
| **CI에 없는 조건** | Playwright 브라우저(바이너리를 내려받지 않는다), `CHK_TEST_AUTOSTART=1` 작업 스케줄러, **트레이가 있는 데스크톱 세션** | 개발 PC에서 조건을 갖추면 |

트레이가 필요한 BUI-01 「도구」·BUI-11 「확장...」은 그래서 **양쪽 모두** 건너뛴다. 거꾸로 트레이가 **없어야** 도는 U15 알림 자리 시험은 양쪽에서 돈다.

그래서 **CI의 Windows가 Linux보다 열넷을 더 돈다** (건너뛰는 것이 44개 ↔ 58개). 양쪽의 「통과 + 건너뜀」 합은 모은 시험 수로 같다 — 셈을 적을 때 그것으로 맞춰 본다.

### Qt 창 시험에 `TestClient`를 붙이지 않는다

**창을 띄운 채 `fastapi.testclient.TestClient`를 들고 있으면 안 된다.** 그러면 anyio 포털
스레드와 QtWebEngine 스레드가 한 프로세스에 쌓이고, **실행이 통째로 죽는다** (`SIGSEGV`,
exit 139). 죽는 자리는 **돌던 시험과 무관한 곳**이라 — 우리 때는 한참 뒤의 업로드 시험
안이었다 — 로그만 보고는 원인을 찾을 수 없다.

**드물게 난다.** 처음 본 곳은 ubuntu x86_64 CI였고 그때는 개발 PC(aarch64)·Windows에서
재현되지 않았는데, 뒤에 **개발 PC(aarch64)에서도 한 번 났다** — 같은 코드로 세 번 돌려
한 번만 죽었다 (앞뒤 두 번은 끝까지 갔다). 그러므로 **한 번 죽은 것으로 코드를 의심하기 전에
다시 돌려 본다**: 되풀이되지 않으면 이 병이고, 되풀이되면 창을 띄우는 시험과 `TestClient`를
드는 시험이 한 프로세스에 함께 있는지 본다. **그리고 죽은 실행을 「통과」로 적지 않는다** —
셈은 끝까지 간 실행에서만 읽는다.

- 창은 **가짜 읽기 클라이언트**로 시험한다 (`CenterReader`를 상속해 메모리에서 답한다 —
  `tests/test_studio_install.py`의 `FakeReader`). 창이 아니라 **담는 것**(목록·줄 계산)은
  애초에 Qt 없이 도는 함수로 갈라져 있다.
- 진짜 Center로 보는 것은 **Qt 없는 시험**에 둔다 (설치·제거·내보내기처럼 값이 큰 길).
- 창을 띄웠으면 그 시험 안에서 **닫고 `deleteLater()`**로 치운다 — 뒤 시험이 도는 중에 Qt
  객체가 죽으면 같은 꼴로 터진다.

**그리고 시험은 안 듣는 포트로 전화하지 않는다.** 같은 병의 다른 얼굴을 Windows에서 봤다 —
STU-13 편집기가 열릴 때 공개 카탈로그(C9)를 읽는데 주소는 **확장 정의**가 주므로 Qt 단위
시험에서도 값이 차 있어, 창을 띄우는 시험마다 **진짜 TCP 연결을 시도**하고 있었다. 거기서
`Fatal Python error: Aborted` (exit 1)로 죽었다. `tests/conftest.py`의 autouse 가드가
**주소는 있는데 클라이언트를 끼우지 않은** 조합만 「오프라인」으로 떨어뜨린다 — 가짜를 준
시험은 진짜 코드를 그대로 돌고, 주소가 없는 길도 그대로다.

### 자식 프로세스를 기다리는 시험은 한 자리에서 기다린다

진짜 실행기를 띄우는 시험(결재 통로·Bot UI 실행기·PC 예제 재통과)은 「자식이 파일에 쓸
때까지」를 기다린다. 그 기다림은 **`tests/waiting.py`의 `wait_for` 하나**다 — 파일마다
베껴 두었더니 셋이 **서로 다른 한도**(30·30·60초)를 들고 있었고, 느린 Windows 러너에서
30초를 넘겨 **CI가 한 번 빨갛게 됐다**(그 묶음이 Linux의 4배 느렸다. 다시 돌리니 통과했다 —
고장이 아니라 한도였다).

- **Windows에는 더 준다** (120초 ↔ 30초). 자식은 파이썬을 새로 띄워 우리 패키지를 전부
  import한다 — 거기서 갈리는 것이 수십 초다.
- **죽었으면 바로 끝낸다** (`child=` 손잡이). 한도를 늘린 대신 **진짜 고장은 더 빨리**
  드러나야 한다. 포기할 때는 자식 로그 꼬리를 찍는다 — CI 로그만 보고도 무엇이 멈췄는지
  알게.
- **죽음보다 조건을 먼저 본다.** 실행기는 요청 파일을 **쓰고 바로 끝나는** 길이 있어, 순서를
  뒤집으면 멀쩡한 성공을 실패로 읽는다.
- 한도를 손으로 적는 자리는 **그 시험이 기다리는 것이 자식이 아닐 때**만 둔다 (예: 하트비트
  한 주기).

## 8. 확인 체크리스트 (M1 완료 시 채움)

- [x] Windows에서 clone → `uv sync` → 테스트 통과 (CI `windows-latest` = Windows Server. **Windows 11 데스크톱은 아직 확인 안 됨**)
- [x] Linux에서 clone → `uv sync` → 테스트 통과 (CI `ubuntu-latest` x86_64 + 개발 PC aarch64)
- [ ] Windows에서 Studio 창이 뜬다
- [ ] Windows에서 Bot UI가 Worker 프로세스를 띄우고, Worker가 Chromium을 조작한다
- [ ] Linux 서버의 Center에 Windows Bot UI가 Center API 키로 등록·하트비트한다

# 04. 개발 환경 구성

> 상태: **일부 확인됨.** Windows 11 데스크톱에서 이 문서만 따라 해 봤다 (§8 실행 기록, 23분쯤). `uv sync --all-packages` → `uv run pytest`가 **CI(Windows Server + Linux x86_64)와 개발 PC(Linux aarch64)에서 돈다.** `web/`·Playwright·Docker 쪽과 Windows 데스크톱(Studio 창·트레이·UIA)은 그 단계가 오면 갱신한다.
> 이 문서는 **새 PC에서 이 문서만 보고** 환경을 만들 수 있어야 한다. 막히는 곳이 있으면 그 자리에서 고친다.

## 1. 어떤 PC에 무엇을 까는가

| PC 역할 | OS | 필요한 것 |
| --- | --- | --- |
| 클라이언트 개발 (Studio·PC 실행기·Worker 프로세스) | **Windows 10/11 (주)**, Linux | Git, uv, Python, Playwright 브라우저 |
| 서버 개발 (Center·서버 실행기·서비스 앱) | **Linux (주)**, Windows | Git, uv, Python, Docker, Ollama |
| 한 대로 전부 | Windows 또는 Linux | 위 둘 다 |

## 2. 공통 도구

| 도구 | 버전 | 용도 |
| --- | --- | --- |
| Git | 최신 | 소스 관리 |
| uv | 최신 | Python 설치·가상환경·의존성 (pip·venv 직접 사용 안 함) |
| Python | **3.12** ([ADR-0005](decisions/0005-python-version.md)) | **직접 깔지 않는다 — uv가 내려받는다.** 시스템 Python 버전은 상관없다 |
| Docker | 최신 | 서버 구성(`deploy/compose.yaml`) — Center·콘솔·서버 실행기·서비스 앱. 저장소는 모두 SQLite 파일이라 **따로 세울 DB가 없다** ([ADR-0070](decisions/0070-center-stays-on-sqlite.md)) |
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

# 4) Playwright 브라우저 — 선택 의존성이라 `--with`로 부른다 (아래 설명)
uv run --with playwright python -m playwright install chromium
```

- **Playwright는 워크스페이스 의존성이 아니다** — CI가 브라우저 바이너리를 내려받지 않게 일부러 뺐다. 그래서 `uv run playwright …`는 `program not found`로 끝난다. 브라우저를 쓰는 시험(웹 UI 태스크·셀렉터 등록·M4 인수 시험의 웹 쪽)은 `uv run --with playwright python -m pytest`로 돌리고, **`python -m`으로** 부른다 (그냥 `pytest`는 프로젝트 venv의 실행 파일이라 Windows에서 Playwright가 붙지 않는다). 그 밖에는 Playwright 시험을 건너뛸 뿐 실패하지 않는다 (§7).
- `uv run pytest`는 Windows 데스크톱에서 **17분쯤** 걸린다 (아래 §8의 실행 기록). 멈춘 것이 아니다.

### 웹 화면 (Windows·Linux 같음)

```powershell
# Node.js LTS 설치 (Windows: winget, Linux: 배포판 패키지 또는 nvm)
winget install --id OpenJS.NodeJS.LTS -e
# pnpm 사용 준비 (버전은 web/package.json의 packageManager가 정한다).
# Windows는 관리자 권한 없이 — uv가 이미 PATH에 넣어 둔 사용자 폴더에 둔다 (아래 「Windows 주의점」)
corepack enable pnpm --install-directory "$env:USERPROFILE\.local\bin"
# Linux·macOS, 또는 관리자 PowerShell이면: corepack enable
cd web
pnpm install
pnpm dev                 # 콘솔 둘을 함께 띄운다 (8501, 8001)
pnpm --filter @chaeksas/center-console dev   # 하나만 — http://localhost:8501
```

| 명령 (`web/`에서) | 하는 일 |
| --- | --- |
| `pnpm dev` | 콘솔 둘을 함께 띄운다 (Center 8501, 서비스 앱 8001) |
| 환경변수 | Center 콘솔: `CHK_CONSOLE__CENTER_URL`(기본 `http://localhost:8800` — 콘솔 서버가 부르는 주소), `CHK_CONSOLE__CENTER_PUBLIC_URL`(위 막대에 보일 주소 — PC 실행기·Studio가 적는 바깥 주소, 비우면 앞의 것), `CHK_CONSOLE__SESSION_SECRET`(**필수**, 16자 이상 — 로그인 쿠키를 암호화한다) |
| 환경변수 | 서비스 앱 콘솔: `CHK_SVC_CONSOLE__APP_URL`(기본 `http://localhost:8000` — **어느 서비스 앱의 콘솔인지는 이 값이 정한다**), `CHK_SVC_CONSOLE__SESSION_SECRET`(**필수**, 16자 이상), `CHK_SVC_CONSOLE__CENTER_CONSOLE_URL`(선택 — **브라우저가 여는** Center 콘솔 주소. 있으면 SVC-03·UIA-03의 「실행 id」가 CON-01로 이어진다, [ADR-0075](decisions/0075-service-console-links-to-center-console.md)) |
| `pnpm build` | 둘 다 제품 빌드 (`output: standalone`) |
| `pnpm typecheck` | 모든 패키지·앱의 TypeScript 검사 |
| `pnpm test` | 콘솔 집계 함수의 단위 시험 (vitest — 브라우저를 띄우지 않는다) |
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
| `corepack enable`이 `EPERM` | `EPERM: operation not permitted, open 'C:\Program Files\nodejs\yarnpkg'` | winget·MSI로 깐 Node는 `Program Files`에 있어 **일반 사용자는 거기에 쓸 수 없다**. `corepack enable pnpm --install-directory "$env:USERPROFILE\.local\bin"` — uv 설치가 이미 PATH에 넣은 폴더다. `corepack pnpm install`만으로는 모자란다: 루트 스크립트(`pnpm typecheck` 등)가 안에서 `pnpm -r …`을 다시 부르는데 PATH에 `pnpm`이 없으면 `'pnpm'은(는) … 프로그램이 아닙니다`로 끝난다 |
| 한글 사용자 폴더의 Chromium | 화면에 보이는 Chromium이 뜨지 않음 — Playwright `spawn UNKNOWN`, 직접 띄우면 「side-by-side configuration is incorrect」(응용 프로그램 로그: `Dependent Assembly … could not be found`) | Playwright가 브라우저를 `%LOCALAPPDATA%\ms-playwright`에 받는데 **사용자 이름이 한글이면** 그 경로에서 Windows가 Chrome의 매니페스트를 찾지 못한다(같은 파일을 `C:\dev\…`로 옮기면 뜬다). `PLAYWRIGHT_BROWSERS_PATH`를 ASCII 경로(예: `C:\dev\ms-playwright`)로 두고 그 자리에 받는다 — PC 실행기·Worker를 띄우는 창에도 같은 값을 준다. 화면 없는 실행(headless shell)은 이 병을 피해 가서 시험만으로는 드러나지 않는다 |
| Playwright 판과 받아 둔 브라우저가 어긋남 | `Executable doesn't exist at …chromium_headless_shell-<번호>…` | `--with playwright`는 그때의 최신 판을 받고, 판마다 찾는 Chromium 번호가 다르다. 받아 둔 브라우저에 맞는 판으로 고정하거나(`--with playwright==<판>`) 그 판으로 `python -m playwright install chromium`을 다시 한다 |
| 서버를 띄운 채 `uv run` | `error: failed to remove file …\.venv\Scripts\chk-mock-apps.exe … (os error 32)` | `git pull` 뒤 `uv run`이 환경을 맞추려다 **떠 있는 프로세스가 쥔 실행 파일**을 바꾸지 못한다(Windows는 실행 중인 파일을 지울 수 없다). 그 서버를 끄고 `uv sync`를 하거나, 우리 코드만 바뀌었으면 `uv run --no-sync …`로 띄운다 (멤버는 편집 가능 설치라 코드는 이미 반영돼 있다) |
| PC 실행기에 Playwright 붙이기 | 셀렉터 등록 「이 PC에는 브라우저 백엔드가 없습니다」 | Playwright는 선택 의존성이다. `uv run --with playwright chk-bot-ui`로는 **붙지 않는다**(uv가 `chk-bot-ui`를 프로젝트 `.venv`의 실행 파일로 풀어 그 Python으로 돈다). **`uv run --with playwright==<판> python -m chaeksas.bot_ui`**로 띄운다 — Worker는 PC 실행기의 Python으로 뜨므로 함께 붙는다. 판은 받아 둔 브라우저에 맞춘다(바로 위 줄) |
| 트레이의 PC 실행기가 둘 | Worker 포트(8899)를 옛 쪽이 쥐고 새 PC 실행기의 요청이 그리로 간다 | 창을 닫는 것은 끄는 것이 아니다(트레이에 남는다). 다시 띄우기 전에 트레이에서 「종료」했는지 본다 |
| Git Bash에서 `pnpm test`가 127 | 아무 말 없이 `ELIFECYCLE Test failed`, 끝 코드 127 | 웹 명령은 **PowerShell**에서 돌린다 (이 문서의 명령이 모두 PowerShell 기준이다). 같은 명령이 PowerShell에서는 통과한다 |
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
- PySide6는 `uv sync`가 받는다. `packages/qt`는 **Essentials만** 쓰고, QtWebEngine이 든 Addons는 Studio가 따로 받는다 ([ADR-0022](decisions/0022-studio-canvas.md)·[ADR-0024](decisions/0024-desktop-packaging-extensions.md) — PC 실행기 설치 파일을 작게 두려는 것이다).

서버 쪽 구성(Center·Center 콘솔·**서버 실행기**·서비스 앱과 그 관리 콘솔)은 `deploy/compose.yaml` **한 번으로** 뜬다 — Windows에서도 Docker Desktop으로 같은 서버를 띄운다. 레지스트리는 서비스 앱 안의 SQLite 한 파일이라 따로 세울 DB가 없다 ([ADR-0040](decisions/0040-registry-storage-sqlite.md)).

**Center를 새 판으로 올리면 저장소가 뜰 때 저절로 옮겨진다** ([ADR-0065](decisions/0065-center-schema-migrations.md)) — 모자란 단계만 차례로 돌고, 단계 하나가 실패하면 그 단계는 없던 일이 되고 **Center가 뜨지 않는다**(사유가 로그에 남는다). **되돌리는 단계는 없다** — 옮겨진 DB를 옛 판 Center가 열면 「새 판의 Center로 띄우세요」라며 **뜨지 않는다**. 그래서 **올리기 전에 DB 파일을 떠 둔다**(WAL이라 `center.sqlite3`·`-wal`·`-shm` 셋을 함께, Center를 멈춘 뒤). 지금 판은 `SELECT * FROM schema_migrations`가 말해 준다.

**3판에서 멈췄다면** — 같은 키·같은 기계가 여러 행에 있다는 뜻이다(2026-10-08 전에 만든 DB에서 같은 PC를 두 키로 등록하면 생긴다). Center는 **어느 행을 남길지 짐작하지 않는다**([ADR-0066](decisions/0066-migration-guards.md)) — Center를 멈춘 채로 사람이 고른다:

```bash
uv run chk-center hosts duplicates
```

```bash
uv run chk-center hosts retire bui_xxxxxxxx
```

목록은 무리마다 이름·마지막으로 본 때를 보인다. 은퇴는 **지우지 않고**(배포·실행 기록이 그 id를 가리킨다) 그 행의 키·기계 자리를 놓게 하고 다시 쓰이지 않게 한다(PC는 비활성, 서버 실행기는 일시 중지). **겹친 무리에 든 행만** 은퇴시킬 수 있다. 다 고른 뒤 Center를 다시 띄우면 3판으로 간다.

## 5. 설정과 비밀

- 설정 파일: 저장소의 `configs/*.example.yaml`을 복사해 쓴다 (M1).
- 비밀(토큰·DB 비밀번호·API 키): `.env` (git 제외) 또는 OS 비밀 저장소. 설정 파일·코드에 넣지 않는다.
- 환경변수 접두사: **`CHK_`** 하나. 중첩은 `__` (예: `CHK_CENTER__PORT`, `CHK_CENTER__API_KEY`). [ADR-0011](decisions/0011-config-ports-env.md)
- 우선순위: 환경변수 > `.env` > 설정 파일 > 기본값.
- 서비스 앱 API 키: **없다** ([ADR-0102](decisions/0102-calling-outside-is-pull.md)) — BPM 프로세스는 바깥 기능을 Center의 외부 작업으로 부른다(C15). 서버 실행기·Studio는 제 Center API 키로, 실행 프로세스는 PC 실행기가 청한 **호출 토큰**으로 올린다. 외부 앱의 주소·키는 **어댑터 일꾼**의 설정에만 있다(아래).
- 서버 실행기: 들어오는 포트가 없다 (Center로 접속만). **화면이 없으니 설정 파일도 없다** — 환경변수로만 설정한다: `CHK_SERVER_RUNNER__CENTER_URL`(기본 `http://localhost:8800`), `CHK_SERVER_RUNNER__MAX_CONCURRENCY`(동시 실행 상한, 기본 10), `CHK_SERVER_RUNNER__NAME`(비우면 호스트 이름), `CHK_SERVER_RUNNER__HEARTBEAT_S`(첫 주기, 기본 10 — 그다음은 Center가 주는 `next_heartbeat_s`를 따른다), `CHK_SERVER_RUNNER__RETRY_S`(닿지 못했을 때, 기본 30), **`CHK_SERVER_RUNNER__PARK_AFTER_S`**(외부 작업을 이만큼 기다려 끝나지 않으면 기다림으로 넘기고 자리를 놓는다, 기본 20초 — 결과는 하트비트 주기마다 묻는다, [ADR-0103](decisions/0103-long-external-tasks.md)), `CHK_SERVER_RUNNER__DATA_DIR`, **`CHK_SERVER_RUNNER__LLM__BASE_URL`·`CHK_SERVER_RUNNER__LLM__MODEL`**(AI 태스크가 쓰는 모델, 기본 모델 이름은 `qwen2.5:7b`. **주소를 비우면 AI 태스크가 실패한다** — 조용히 넘어가지 않는다, [ADR-0027](decisions/0027-llm-connection.md)), **`CHK_SERVER_RUNNER__READABLE_DIRS`·`CHK_SERVER_RUNNER__WRITABLE_DIRS`**(읽기·쓰기 허용 폴더, `os.pathsep`으로 여럿 — Linux `:`, Windows `;`. **기본은 비어 있다**: 출력 폴더 밖은 적어 주지 않으면 `PathDenied`다, [ADR-0032](decisions/0032-writable-dirs.md)), **`CHK_SERVER_RUNNER__SMTP__HOST`·`__PORT`·`__SECURITY`·`__USERNAME`·`__FROM`·`__ATTACHMENT_MB`**(메일 보내기 — 보안은 `starttls`(기본)·`ssl`·`none`, 포트를 비우면 보안에 맞는 기본(587·465·25), 첨부 합계 상한 기본 10 MB. **주소·보내는 주소를 비우면 `chk:email`이 실패한다** — 조용히 넘어가지 않는다, [ADR-0059](decisions/0059-sending-mail-and-webhooks.md)), **`CHK_SERVER_RUNNER__WEBHOOK__ALLOWED_HOSTS`**(웹훅을 보낼 수 있는 호스트, **쉼표로 여럿**. **기본은 비어 있고 비면 아무 데도 보내지 않는다** — 사설·루프백은 적어도 열리지 않는다). **Center API 키(서버 실행기용)는 둘 중 하나로 온다** — 환경변수 `CHK_SERVER_RUNNER__CENTER_API_KEY`(systemd·CI, 이것이 이긴다) 또는 **등록 승인**(**`CHK_SERVER_RUNNER__JOIN_TOKEN`이 Center의 들이기 비밀과 맞으면 그 자리에서 승인된다** — ADR-0117. OS 비밀 저장소 `chaeksas-server-runner`나 **비밀 폴더 `CHK_SERVER_RUNNER__SECRETS_DIR`**가 있을 때만 — 키가 없으면 등록 요청을 보내고 요청 코드를 로그에 찍는다, C12 §등록 요청과 승인. 둘 다 없으면 요청하지 않고 끝 코드 2로 끝난다). **컨테이너는 비밀 폴더가 그 자리다** ([ADR-0100](decisions/0100-server-runner-secrets-dir.md) — `deploy/compose.yaml`의 실행기는 볼륨 `server-runner-secrets`를 쓰고 키 회전도 그대로 돈다). **모델 키는 `CHK_SERVER_RUNNER__LLM__API_KEY`**, **메일 비밀번호는 `CHK_SERVER_RUNNER__SMTP__PASSWORD`**(PC 실행기·Studio와 같은 규칙, [ADR-0013](decisions/0013-api-keys.md) — 값은 설정·실행 기록에 넣지 않는다). **확장 설정 칸은 `CHK_SERVER_RUNNER__EXT__<확장 id>__<칸 이름>`이다** (C13 `configuration`의 `scope: server_runner`인 것만. 이름은 영대문자·숫자·`_`로 바꿔 쓴다 — `doc-ocr`·`ocr_key` → `..._EXT__DOC_OCR__OCR_KEY`. **PC 실행기의 `CHK_BOT_UI__EXT__…`와 같은 규칙**이고 비밀 칸도 같은 이름으로 온다, [ADR-0064](decisions/0064-extension-tasks-on-the-server.md) §2). **로컬 런타임은 띄우지 않으므로** 그 자리를 가리키는 환경변수는 없다. 띄우는 것은 `uv run chk-server-runner`이고 `--once`는 **등록하고 하트비트까지 한 번** 해 보고 상태 한 줄을 찍는다(설치 확인용 — 끝 코드 0/1/3이 「됐다」·「사람이 고쳐야 한다」·「닿지 못했다」를 가른다). 배포는 하트비트로 받아 `<데이터>/bots/<id>/<버전>/`에 푼다 (PC 실행기와 같은 자리 규칙). 실행 기록은 `<데이터>/runs/<run_id>.jsonl`이고(파일이 원본이다 — C3) 하트비트 뒤에 Center로 보낸다. **기다리는 실행은 `<데이터>/state.sqlite3`에 담긴다** — 실행기를 다시 띄우면 그것을 훑어 되살린다 (ADR-0054). 그 파일을 지우면 기다리던 실행은 `runner_restarted`로 닫힌다. **메시지를 받는 포트는 없다** — 서버 실행기는 들어오는 포트가 없고, 외부 시스템은 Center의 `POST /api/v1/messages`에 넣는다 (C12 §메시지. PC는 PC 실행기의 8790이다). **`--once`는 작업을 받지 않는다** — 곧 끝나는 프로세스가 실행 스레드를 버리면 안 된다 (받지 않은 작업은 다음 하트비트에 다시 실린다, C4). **SIGTERM에 곱게 끝낸다** ([ADR-0015](decisions/0015-run-location.md), C12).
- PC 실행기 대기열 크기: 기본 20, `CHK_BOT_UI__QUEUE__MAX`. 실행 자리(동시 실행 BPM 프로세스 수)는 1로 고정이라 설정이 없다 ([ADR-0014](decisions/0014-one-bot-per-pc.md)).
- Worker 프로세스는 PC 실행기가 띄운다. 개발 PC에도 PC 실행기를 설치해 켜 두면 Studio 시험 실행이 그 Worker를 쓴다 — PC 실행기가 `<PC 실행기 데이터>/runtimes/worker/`에 남긴 `runtime.json`(포트)과 토큰 파일로 찾는다. BPM 프로세스를 돌릴 때는 PC 실행기가 그 BPM 프로세스가 쓰는 확장의 Worker를 **먼저 띄운다**.
- Studio 시험 실행의 서비스 앱 태스크: **키가 없다** — Studio가 제 Center API 키로 C15 외부 작업을 올린다(`origin: test` — 시험 쪽으로 보낼지는 일꾼이 정한다, ADR-0102 §6). 모델 키는 「LLM」에서 넣거나 `CHK_STUDIO__LLM__API_KEY`(이것이 이긴다). 확장의 **비밀 설정 칸**(C13 `configuration[].secret`, scope `studio`)은 STU-10 「확장별 설정」에서 넣으면 `ext:<확장>:<칸>`으로 가고 `CHK_STUDIO__EXT__<확장>__<칸>`이 이긴다 ([ADR-0073](decisions/0073-studio-settings-only-what-is-used.md)).
- PC 실행기(실행기)의 호출 토큰 (C15): PC 실행기가 제 Center API 키로 `POST /api/v1/call-tokens`에 청해(24시간) 실행 프로세스에게 넘기고(환경변수 `CHK_BOT_UI__CALL_TOKEN`·제어 파일, 만료 2시간 전부터 새것), Worker에는 C10 세션으로 주고, Tool UI가 읽게 OS 비밀 저장소(`chaeksas-bot-ui`, 이름 `call_token`)에도 둔다. 사람이 넣는 것은 없다.
- PC 실행기의 메일 보내기(BUI-03 「보내기」): 설정 파일에 **주소·보안·사용자·보내는 주소·첨부 상한·웹훅 허용 호스트**가 가고, **비밀번호는 OS 비밀 저장소**(`chaeksas-bot-ui`, 이름 `smtp-password`)다. 개발·CI에서는 `CHK_BOT_UI__SMTP__PASSWORD`로 주고, 나머지도 `CHK_BOT_UI__SMTP__HOST`·`__PORT`·`__SECURITY`·`__USERNAME`·`__FROM`·`CHK_BOT_UI__WEBHOOK__ALLOWED_HOSTS`(쉼표)로 덮어쓸 수 있다 ([ADR-0059](decisions/0059-sending-mail-and-webhooks.md) — **비우면 보내지 않고 실패한다**). 실행 프로세스에는 **비밀번호를 명령줄로 넘기지 않는다** — 자식이 같은 저장소에서 제 손으로 읽는다.
- Center API 키: **PC 실행기·서버 실행기는 사람이 넣지 않는다** ([ADR-0092](decisions/0092-keys-are-issued-and-delivered-by-center.md)) — Center 주소만 주고 띄우면 등록 요청을 보내고, 관리자가 콘솔 CON-03(서버는 CON-12) 「승인 대기」에서 요청 코드(현장 화면·서버 로그)와 같은 줄을 승인하면 키를 받아 OS 비밀 저장소에 둔다. 만료 14일 전부터 Center가 갈아 준다. **Studio도 같다** — STU-10 「Center」에 주소를 넣고 「연결 테스트」를 누르면 요청 코드가 뜨고, 관리자가 CON-11 「승인 대기」에서 승인하면 Studio 키(1년, 회전하지 않는다 — 만료되면 「다시 요청」)를 받는다. 개발·CI에서만 `CHK_CENTER__API_KEY`. Studio가 승인으로 받은 키는 OS 비밀 저장소(`chaeksas-studio`, 이름 `center`)로 가고, 비밀 저장소가 없는 환경(헤드리스 CI)에서는 관리자 토큰으로 발급한 Studio용 키를 `CHK_STUDIO__CENTER_API_KEY`로 준다(이것이 이기고, 그때 STU-10은 요청을 보내지 않는다).
- Studio: `uv run chk-studio` (캔버스는 QtWebEngine이라 `pyside6-addons`가 함께 깔린다). 작업 폴더·설정은 사용자 데이터 폴더의 `studio/`이고 환경변수로 덮어쓴다 — `CHK_STUDIO__DATA_DIR`, `CHK_STUDIO__CENTER__URL`, `CHK_STUDIO__LLM__BASE_URL`, `CHK_STUDIO__LLM__MODEL`, `CHK_STUDIO__READABLE_DIRS`.
- PC 실행기: `uv run chk-bot-ui` (트레이에 뜬다. 트레이가 없는 환경이면 메인 창으로 뜬다). 설정은 BUI-03 창에서 하고 파일은 사용자 데이터 폴더의 `settings.json`이다. 환경변수로 덮어쓸 수 있다 — `CHK_BOT_UI__CENTER__URL`, `CHK_BOT_UI__QUEUE__MAX`, `CHK_BOT_UI__WORKER__PORT`, `CHK_BOT_UI__AUTOSTART`, `CHK_BOT_UI__DATA_DIR`. **Center API 키는 등록 승인으로 받아 OS 비밀 저장소**에 둔다(사람이 넣는 칸은 없다 — BUI-03). 비밀 저장소가 없는 환경(헤드리스 CI)에서는 `CHK_BOT_UI__CENTER_API_KEY`로 주고, 그러면 등록 요청을 보내지 않는다.
- Tool UI: `uv run chk-tool-ui [--open <확장>:<도구>]` (TOL-01, [ADR-0077](decisions/0077-tool-ui.md)) — 보통은 PC 실행기 「도구」에서 연다(그러면 PC 실행기가 Worker를 먼저 띄운다). **Worker를 띄우지 않으므로** PC 실행기가 떠 있어야 셀렉터 등록이 열린다. 설정은 데이터 폴더(`CHK_TOOL_UI__DATA_DIR`로 바꾼다)의 `settings.json`이다. **셀렉터 등록 키는 없다** — Tool UI는 PC 실행기 비밀 저장소의 호출 토큰(`call_token`)으로 등록 작업을 Center에 올리고, Center는 관리자가 CON-03에서 그 PC의 「셀렉터 등록」을 켰을 때만 받는다 (ADR-0102 §5). 개발·CI에서는 `CHK_TOOL_UI__EXT__UI_AUTOMATION__CALL_TOKEN`이 이긴다. 묶은 앱에서는 PC 실행기 실행 파일에 `--tool-ui`를 붙인 것이고 설치 파일이 시작 메뉴에 「Chaeksas Tool UI」를 만든다.
- Center 관리자 계정 ([ADR-0090](decisions/0090-center-admin-accounts.md)): 콘솔은 **아이디·비밀번호**로 들어온다. 첫 관리자는 `CHK_CENTER__FIRST_ADMIN__USERNAME`(비우면 `admin`)·`CHK_CENTER__FIRST_ADMIN__PASSWORD`로 정하고 **계정이 하나도 없을 때만** 쓰인다(그다음에는 콘솔 CON-14에서 바꾼다). 비밀번호는 12자 이상·영문과 숫자를 모두 넣는다 — 맞지 않으면 Center가 **뜨지 않는다**. 비우면 Center가 만들어 로그에 한 번 찍고 데이터 폴더의 `first-admin-password.txt`에 둔다(그 계정이 비밀번호를 바꾸면 지운다). `CHK_CENTER__ADMIN_TOKEN`·`CHK_CENTER__READ_TOKEN`은 **자동화용**이고 선택이다 — 비우면 그 길이 닫힌다. **`CHK_CENTER__SERVER_RUNNER_JOIN_TOKEN`**은 같이 배포된 서버 실행기를 승인 없이 들이는 비밀이다 — 실행기의 `CHK_SERVER_RUNNER__JOIN_TOKEN`과 같은 값이고, 비우면 그 길이 닫혀 실행기는 콘솔 「승인 대기」를 거친다 ([ADR-0117](decisions/0117-bundled-server-runner-joins-by-shared-secret.md), compose는 둘을 `.env`의 한 값에서 준다).
- Center 서명 키: Center가 **처음 뜰 때 만들어 DB에 둔다**(승인·배포·외부 확장 봉투에 Center가 서명한다, ADR-0090). 서버 셸에서 `chk-center signing-key list`(믿는 키) · `rotate`(새 키로 바꾼다 — 옛 키는 믿는 목록에 남는다) · `retire <key_id>`(그 키가 서명한 승인·배포가 **모두 무효**가 된다, 묻는다)다. compose면 `docker compose exec center uv run --frozen --package chaeksas-center chk-center signing-key …`.
- 서비스 앱 관리자 토큰: `CHK_SVC_<앱 id>__ADMIN_TOKEN` (예: `CHK_SVC_UI_AUTOMATION__ADMIN_TOKEN`). **이 토큰이 없으면 그 앱의 관리 API(`/admin/v1/*`)가 503으로 닫혀 있다** — 빈 토큰으로 열리지 않는다 ([C11](03-contracts/C11-service-app-common.md) §관리 API). **서비스 앱은 일꾼으로 Center에 붙는다** ([C15](03-contracts/C15-external-tasks.md), `service_kit.consumer`) — 업무 호출을 받는 포트는 없다. UI 자동화 앱은 `CHK_SVC_UI_AUTOMATION__CENTER__URL`(Center 주소 — 비우면 일감을 가져가지 않고 관리 API만 돈다)을 받아 들이기 요청을 보내고 요청 코드를 로그에 찍는다. 관리자가 CON-07 「일꾼 승인 대기」에서 승인하면 일꾼 토큰을 데이터 폴더(`CHK_SVC_UI_AUTOMATION__DATA_DIR`)의 `consumer-token.json`(`0600`)에 둔다. `CHK_SVC_UI_AUTOMATION__CENTER__TOKEN`이 있으면 그것이 이긴다(개발·CI·컨테이너).
- 모의 앱 (`chk-mock-apps serve`, [samples/README](../samples/README.md)): `CHK_MOCK_APPS__CENTER__URL`을 주면 C11 모의 앱 열셋이 **일꾼 하나**로 붙는다(요청 코드는 화면에 찍힌다). 토큰은 `CHK_MOCK_APPS__DATA_DIR`(기본 `.mock-apps`)에 두고 `CHK_MOCK_APPS__CENTER__TOKEN`이 이긴다.
- 어댑터 일꾼 (`uv run chk-adapter-consumer`, `apps/adapter_consumer` — 외부 앱을 부른다, C13 §4): `CHK_ADAPTER__CENTER__URL`(Center 주소)·`CHK_ADAPTER__EXTENSIONS`(맡을 외부 확장 id, 쉼표)가 있어야 뜬다. 토큰은 `CHK_ADAPTER__DATA_DIR`(기본 `.adapter-consumer`)에 두고 `CHK_ADAPTER__CENTER__TOKEN`이 이긴다. **외부 앱의 주소·키는 여기에만 있다** — 확장마다 `CHK_ADAPTER__EXT__<확장>__BASE_URL`(없으면 정의의 `base_url`)·`__KEY`(키를 받는 앱만), 시험 일감(`origin: test`)용 `__TEST_BASE_URL`·`__TEST_KEY`(없으면 운영 쪽). 이름은 영대문자·숫자·`_`로 바꿔 쓴다(`ext-credit` → `EXT_CREDIT`). 정의가 허용한 사설망으로 나가려면 `CHK_ADAPTER__ALLOW_PRIVATE_NETWORK=1`(기본 닫힘).
- 타이머 시작의 시간대 ([ADR-0110](decisions/0110-center-keeps-the-schedule.md), C5 §일정): `CHK_CENTER__TIMEZONE`(IANA 이름, 기본 `Asia/Seoul`). cron이 이 벽시계로 읽힌다. 풀 수 없는 이름이면 Center가 **뜨지 않는다** (이미지에 시간대 자료가 있어야 한다 — `python:*-slim`에는 있다).
- 외부 작업 롱폴링 상한 ([C15](03-contracts/C15-external-tasks.md)): `CHK_CENTER__EXTERNAL_TASKS__MAX_WAITERS`(기본 200 — 올리는 쪽·일꾼의 기다림을 함께 센다). 넘으면 503 `too_many_waiters`.
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
| PC 실행기 메시지 수신 (ReceiveTask·메시지 시작 이벤트) | 8790 | 127.0.0.1 기본 | `CHK_BOT_UI__WEBHOOK__PORT` |
| UI 자동화 앱 관리 콘솔 | 8001 | 서버 | `CHK_SVC_UI_AUTOMATION__CONSOLE_PORT` |
| Ollama | 11434 | 로컬 또는 서버 | `CHK_LLM__BASE_URL` |

> 주의: 프로토타입과 같은 기본 포트다. 한 PC에서 프로토타입과 새 구성요소를 동시에 띄우면 충돌하므로, 그때는 환경변수로 한쪽을 옮긴다.
>
> 모의 앱은 `uv run chk-mock-apps serve` 하나로 **전부 한 포트(8010)**에 `/<app_id>` 밑에 뜬다 — 열여섯 포트를 쓰지 않아도 된다. 인증 없는 제어 길(`/mock/v1/scenario`)이 있어 127.0.0.1에만 바인드한다 (`samples/README.md`).
>
> `docker compose`로 띄울 때는 `.env`의 `CHK_CENTER__HOST_PORT`·`CHK_CONSOLE__HOST_PORT`가 **호스트 쪽 포트만** 옮긴다 (컨테이너 안의 포트는 위 표 그대로다).

## 6-2. 데스크톱 앱 묶기 (설치 파일의 앞 단계)

```bash
uv run --group build python packaging/build.py              # Studio·PC 실행기 둘 다
uv run --group build python packaging/build.py bot-ui       # 하나만
uv run --group build python packaging/build.py --version 0.2.0
uv run --group build python packaging/build.py --installer    # Windows에서만 — 설치 파일까지
```

PyInstaller **onedir**로 묶는다 ([ADR-0024](decisions/0024-desktop-packaging-extensions.md)) — 산출물은
`build/dist/<이름>/`이고 **설치 프로그램이 담을 폴더**다(설치 프로그램 종류는 아직 정하지 않았다).
PyInstaller는 `--group build`에만 있어 평소 `uv sync`로는 들어오지 않는다.

- **확장 인자를 적지 않는다.** `core`가 주는 PyInstaller 훅이 설치된 엔트리 포인트를 훑어 넣는다 —
  확장을 더해도 빌드 명령이 그대로다. 그래서 **무엇이 들어가는가는 빌드 환경에 무엇이 설치됐는가**로
  정해진다 (사내 확장이 생기면 ADR-0018 §5의 포함 목록을 설치하는 걸음이 앞에 붙는다).
- **묶은 뒤 스스로 검사한다** — `<실행 파일> --selftest <파일>`로 확장이 다 보이는지 보고 하나라도
  빠지면 **빌드를 실패시킨다** (빠진 확장은 실행 중에야 드러난다). 못 박고 싶으면
  `--want ui-automation`처럼 적는다. 그 깃발은 PC 실행기·Studio가 **같은 검사**(`core.selftest`)를 쓴다.
  **PC 실행기는 로컬 런타임을 정말 띄워 본다**(`--start-runtimes` — 빈 포트·임시 폴더로 띄워 `health`가
  답하는지 보고 끈다). 못 뜨면 자식 로그의 끝이 빌드 출력에 실린다.
- **판을 찍는다** ([ADR-0067](decisions/0067-build-stamp.md)) — `--version`이 이기고, 없으면 지금 커밋의
  `v*` 태그, 그것도 없으면 `<core 판>+g<커밋>`(고치다 만 파일이 있으면 `.dirty`)이다. 실행 파일 옆
  `chaeksas-build.json`에 적히고(열어 볼 수 있다) PC 실행기가 C4 `versions`로 올려 **CON-03에 보인다**.
  **판을 올리려면 태그를 민다** — 산출물 워크플로가 태그 이름을 그대로 넘긴다. 묶은 앱이 되읽은 판이
  찍은 판과 다르면 빌드가 멈춘다.
- **설치 파일은 Inno Setup이다** ([ADR-0068](decisions/0068-installer-inno-setup-per-user.md)) — `--installer`가
  `build/installer/Chaeksas<앱>-setup-<판>.exe`를 만든다(Windows에서만, Inno Setup 6 필요 — 없으면
  `choco install innosetup`). **사용자별**이라 관리자 권한을 묻지 않고 `%LOCALAPPDATA%\Programs\Chaeksas\<앱>`에
  깔린다. 덮어쓰면 옛 판의 `_internal`을 지우고 깐다. 제거해도 **사용자 데이터는 남는다**(실행 기록·설치한 BPM 프로세스).
  `--check-install`(설치 → 설치된 앱 검사 → 제거)은 **같은 앱의 설치를 덮으므로 CI에서만** 쓴다.
  설치 파일 크기는 CI가 말해 준 값으로 **PC 실행기 63MB·Studio 205MB**다 (2026-10-17, 런 39004329132).
- **설치 파일에 서명이 없다** — 처음 실행하면 SmartScreen이 「Windows의 PC 보호」를 띄운다.
  「추가 정보」 → 「실행」을 누른다. 백신이 실행 파일을 막으면 그 자리의 예외로 넣는다(서명이 생기면 줄어든다).
- **매니페스트는 Windows에서만** 들어간다 (`packaging/app.manifest` — DPI Per-Monitor v2,
  [ADR-0021](decisions/0021-worker-dpi-capture.md)). 개발 PC가 Linux면 **Linux 묶음**이 나온다 —
  빌드가 서는지 보는 데는 그것으로 되고 **Windows 산출물은 CI가 만든다**(아래).
- **Windows 산출물은 수동으로 돌린다** — `.github/workflows/desktop.yml`(「데스크톱 산출물」)을
  Actions에서 실행하거나 `v*` 태그를 민다. 푸시마다 묶지 않는다 (몇 분이 걸려 모든 PR에 붙이면 값이 크다).
- 크기·시간은 **OS·아키텍처마다 다르다.** CI가 말해 준 값이다 (2026-10-16, 런 38873092925):

  | | PC 실행기 | Studio |
  | --- | --- | --- |
  | **Windows** (CI, x86_64) | **160MB · 86초** | **598MB · 109초** |
  | Linux (CI, x86_64) | 353MB · 33초 | 1009MB · 37초 |
  | Linux (개발 PC, aarch64) | 356MB · 50~62초 | 1008MB · 81초 |

  PC 실행기는 모든 현장 PC에 깔리므로 **QtWebEngine을 넣지 않는다** — 그 차이가 크기의 대부분이다.
  스파이크 S5가 Windows에서 본 것은 PC 실행기 113MB·Studio 551MB였고, 그 뒤 확장·의존이 늘어
  조금 커졌다.

## 6-3. 판 올리기 (Studio·PC 실행기)

**사람이 설치 파일을 다시 돌린다** ([ADR-0069](decisions/0069-upgrading-by-reinstall.md)) — Center는 프로그램을
내려 주지 않는다. BPM 프로세스의 판은 이것이 아니라 배포로 오간다(C2·C5).

1. 설치 파일은 **산출물 워크플로가 올린 것**(`installers-windows`)에서 받는다. 처음 설치와 같은 파일이다.
2. **PC 실행기는 빈 때 깐다** — 설치 파일이 PC 실행기를 닫으면 도는 BPM 프로세스와 대기열을 잃는다. CON-03에서 그 PC를
   「비활성화...」하면 새 작업이 그 PC로 가지 않고(Center에서 기다린다) 도는 BPM 프로세스는 끝까지 돈다. 「실행 중」·
   「대기열」이 비면 깐다. 결재를 기다리는 BPM 프로세스를 기다릴지 멈출지는 사람이 정한다.
3. 설치 파일을 돌린다 — 덮어쓰기이고 설정·설치한 BPM 프로세스·실행 기록은 남는다. 끝 화면의 「실행」으로 다시 띄운다.
4. CON-03에서 그 PC의 「버전」이 새 판으로 바뀌었는지 보고 「다시 활성화」한다.
5. 문제가 있으면 **옛 판의 설치 파일로 다시 깐다**(낮은 판으로 덮어써도 된다). **옛 설치 파일은 받은 사람이
   보관한다** — 산출물 워크플로는 30일만 남긴다(`desktop.yml` `retention-days`).

## 6-4. Center 백업

Center의 저장소는 **SQLite 파일 하나와 패키지 폴더**다([ADR-0070](decisions/0070-center-stays-on-sqlite.md) —
PostgreSQL은 쓰지 않는다). 컨테이너에서는 `/data/center.sqlite3`·`/data/packages`이고 자리는
`CHK_CENTER__DATA_DIR`(또는 `DB_PATH`·`PACKAGE_DIR`)가 정한다.

- **DB 파일을 그냥 복사하지 않는다** — WAL이라 커밋 일부가 `-wal` 파일에 있다. SQLite의 백업 API로 뜬다
  (Center가 도는 중에도 된다):

  ```bash
  docker compose exec center python -c "import sqlite3; sqlite3.connect('/data/center.sqlite3').backup(sqlite3.connect('/data/center-backup.sqlite3'))"
  ```

- **패키지 폴더도 함께** 남긴다 — DB에는 메타데이터만 있고 zip은 폴더에 있다.
- 되살릴 때는 **판 번호가 같거나 높은 Center**로 연다 — DB 판이 코드보다 높으면 Center가 뜨지 않는다
  ([ADR-0065](decisions/0065-center-schema-migrations.md) §2).

## 7. 시험 돌리기와 **건너뛰는 것**

`uv sync --all-packages` → `uv run pytest`. `addopts`에 `-q`가 있으니 **`-q`를 또 주면 셈이 안 보인다**. 왜 건너뛰는지는 `uv run pytest -rs`가 말해 준다.

건너뛰는 것은 두 갈래다.

| 갈래 | 무엇 | 어디서 도나 |
| --- | --- | --- |
| **OS 전용** | 네이티브 메뉴 글꼴, 데스크톱 UIA 백엔드와 그것을 쓰는 예제(BX-17·BX-04·FX-05·BX-36), PC 실행기·Studio 확장 연결 한 바퀴 | Windows에서만 |
| **CI에 없는 조건** | Playwright 브라우저(바이너리를 내려받지 않는다), `CHK_TEST_AUTOSTART=1` 작업 스케줄러, **트레이가 있는 데스크톱 세션** | 개발 PC에서 조건을 갖추면 |

트레이가 필요한 BUI-01 「도구」·BUI-11 「확장...」은 그래서 **양쪽 모두** 건너뛴다. 거꾸로 트레이가 **없어야** 도는 U15 알림 자리 시험은 양쪽에서 돈다.

그래서 같은 시험 묶음이면 **Windows가 Linux보다 OS 전용 시험만큼 더 돈다** (건너뛰는 것이 49개 ↔ 64개 — #196 CI).

**그런데 CI의 Windows 잡은 같은 묶음이 아니다 — 서버 시험을 뺀다** ([ADR-0104](decisions/0104-windows-ci-runs-the-client-side.md)). 서버(Center·서버 실행기·일꾼·서비스 앱·모의 앱·M7 묶음)는 Linux에서만 돌므로 그 파일들을 `tests/ci_scope.py`의 `SERVER_SIDE`에 적고, `conftest.py`가 `server` 표시를 붙이며 Windows 잡은 `uv run pytest -m "not server"`로 돈다. 표시로 빠진 시험은 **건너뜀이 아니라 「선택 해제」**라 셈에 따로 나온다(`… deselected`). 그래서 Linux는 「통과 + 건너뜀 = 모은 시험 수」이고 Windows는 「통과 + 건너뜀 + 선택 해제 = 모은 시험 수」다 — 셈을 적을 때 그것으로 맞춰 본다.

- **기본은 양쪽이다** — 새 시험 파일은 적지 않으면 Windows에서도 돈다.
- **엔진(`core`)과 PC 쪽 코드가 걸린 시험은 서버로 적지 않는다** — PC BPM 프로세스는 Windows에서 엔진을 돌린다. `tests/test_ci_scope.py`가 서버 파일이 PC 실행기·Tool UI·Qt·Worker·UI 자동화 클라이언트를 import하지 않는지 본다.
- Windows 개발 PC에서 CI와 같은 것을 보려면 `uv run pytest -m "not server"`, 전부는 그냥 `uv run pytest`다.

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
- **진짜 소켓 서버를 띄우는 fixture는 `session`이 아니라 `module`이다** — `session`이면 그 파일이 끝난 뒤에도
  uvicorn 스레드가 살아 **뒤의 Qt 시험과 한 프로세스에 겹친다**. M5 인수 시험의 서버 넷(모의 앱·외부 앱 둘·Center)이
  그랬고, Windows CI가 서버 시험을 빼 순서가 바뀌자 STU-04 캔버스 fixture에서 `access violation`으로 죽었다
  (ADR-0104 PR). 같은 파일 안에서만 나눠 쓰는 것이라 `module`로 잃는 것이 없다 (M3의 모델 스텁이 처음부터 그렇다).

**그리고 시험은 안 듣는 포트로 전화하지 않는다.** 같은 병의 다른 얼굴을 Windows에서 봤다 —
STU-13 편집기가 열릴 때 공개 카탈로그(C9)를 읽는데 주소는 **확장 정의**가 주므로 Qt 단위
시험에서도 값이 차 있어, 창을 띄우는 시험마다 **진짜 TCP 연결을 시도**하고 있었다. 거기서
`Fatal Python error: Aborted` (exit 1)로 죽었다. `tests/conftest.py`의 autouse 가드가
**주소는 있는데 클라이언트를 끼우지 않은** 조합만 「오프라인」으로 떨어뜨린다 — 가짜를 준
시험은 진짜 코드를 그대로 돌고, 주소가 없는 길도 그대로다.

### 자식 프로세스를 기다리는 시험은 한 자리에서 기다린다

진짜 실행기를 띄우는 시험(결재 통로·실행 프로세스·PC 예제 재통과)은 「자식이 파일에 쓸
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

- [x] Windows에서 clone → `uv sync` → 테스트 통과 (CI `windows-latest` = Windows Server, 그리고 **Windows 11 데스크톱**에서 이 문서만 따라 해 봤다 — 아래 실행 기록)
- [x] Linux에서 clone → `uv sync` → 테스트 통과 (CI `ubuntu-latest` x86_64 + 개발 PC aarch64)
- [ ] Windows에서 Studio 창이 뜬다
- [ ] Windows에서 PC 실행기가 Worker 프로세스를 띄우고, Worker가 Chromium을 조작한다
- [ ] Linux 서버의 Center에 Windows PC 실행기가 Center API 키로 등록·하트비트한다

### 실행 기록 — Windows 11 데스크톱에서 이 문서만 보고 (2026-10-13)

M6 둘째 기준(「새 개발자가 이 문서만 보고 1시간 안에」)을 재 보려고 **이 문서의 명령을 글자 그대로** 따라 했다. 새 폴더 `C:\dev\Chaeksas`에 clone하고 **uv 캐시를 비운 채**(`UV_CACHE_DIR`를 새 폴더로) 돌렸다. Git·uv·Node는 이미 깔려 있었고, uv가 받은 Python 3.12도 이미 있었다 — 그 셋을 까는 몇 분은 셈에 없다. 일반 사용자 계정(관리자 아님)이다.

| 단계 | 걸린 시간 | 결과 |
| --- | --- | --- |
| `git clone` | 5초 | 됐다 |
| `uv sync --all-packages` (빈 캐시) | 57초 | 됐다 |
| `uv run pytest` | 17분 | **2965 통과·44 건너뜀** (§7의 Windows 건너뜀 수와 같다) |
| `uv run playwright install chromium` | — | **안 됐다** — `program not found`. 고쳤다: §3 4)번 |
| `corepack enable` | — | **안 됐다** — `EPERM`. 고쳤다: §3 「웹 화면」·「Windows 주의점」 |
| `pnpm install` | 1분 43초 | 됐다 (고친 명령으로) |
| `pnpm typecheck` · `pnpm test` · `pnpm build` | 37초 · 8초 · 1분 53초 | 됐다 (`pnpm test`는 PowerShell에서 — Git Bash에서는 127) |

**합이 23분쯤**이라 1시간 안이다 — 단 **문서가 틀린 곳 둘**을 그 자리에서 고친 뒤의 셈이다(고치기 전의 문서로는 Playwright와 웹 쪽에서 막힌다). 사람이 아니라 Claude가 문서를 따라 한 것이라, 「처음 보는 사람이 문서만으로」는 아직 사람이 한 번 해 봐야 한다 (로드맵 M6 둘째는 그래서 열어 둔다).

### 실행 기록 — 시나리오 3 현장 리허설 (2026-10-17)

M6 첫째 기준을 사람이 현장 PC에서 해 보기 전에 **같은 PC에서 Claude와 함께** 이어 봤다 (Windows 11, 일반 사용자, **한글 사용자 이름**). 서버(Center·UI 자동화 앱·모의 앱 포털·리허설용 SMTP 받는 곳)는 그 PC의 127.0.0.1에 띄우고 데이터는 따로 둔 폴더(`C:\dev\field-run\`)에 모았다. PC 실행기·Studio·Admin(그때는 데스크톱 창이었다 — 지금은 콘솔, ADR-0090)은 사람이 제 PowerShell에서 띄웠다.

**끝까지 돌았다** — 올리기 → 승인·배포 서명 → 설치·「준비됨」 → 작업 지시 → 포털 표 읽기 → 회계 프로그램 4줄 입력 → 검산 → 메일 (`success`, 약 50초). 막힌 자리와 처리:

| 막힌 자리 | 처리 |
| --- | --- |
| Worker가 브라우저를 열지 못함 (「화면을 열지 못했습니다 (Error)」) | **제품 버그 — 고쳤다** (화면 스레드, CLAUDE.md §7 UI 자동화). 시험이 Worker 객체를 직접 불러 현장 경로를 밟지 않았다 → `test_worker_http_browser.py` |
| 한글 사용자 폴더의 Chromium이 뜨지 않음 | `PLAYWRIGHT_BROWSERS_PATH`를 ASCII 경로로 (§3 「Windows 주의점」) |
| Playwright 판과 받아 둔 Chromium이 어긋남 | 판 고정 (§3 「Windows 주의점」) |
| `uv run --with playwright chk-bot-ui`로는 Playwright가 붙지 않음 | `python -m chaeksas.bot_ui`로 (§3 「Windows 주의점」) |
| 「예제 가져오기」가 예제를 못 찾음 | **제품 버그 — 고쳤다** (기본 폴더가 한 단계 모자랐다 — 시험이 모두 폴더를 넘겨 기본값을 밟지 않았다) |
| SMTP를 넣어도 「준비 안 됨」(`settings_missing`) | **제품 버그 — 고쳤다** (BUI-03 저장이 사전 점검을 비우지 않았다) |
| SMTP 주소에 `localhost:2525`를 적어도 받아 줌 | **고쳤다** — 「포트는 포트 칸에」를 사전 점검·화면이 말한다 |
| BUI-06이 데스크톱 화면을 담지 못함 / 첫 실행 전 앱 주소 명부가 비어 있음 | **사람 손이 닿지 않아 대신했다** — [09-gaps §6](09-gaps.md) |
| `.ps1`이 실행 정책에 막힘 | 그 창에서만 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (창을 닫으면 돌아간다) |
| 키 칸을 바꿔 넣음 (`finance-tax` 키를 「등록 담당자 키」에) | 화면이 「권한이 필요하다」로 말해 찾았다 — 두 칸 모두 「UI 자동화 앱 키」라 헷갈린다 |
| 트레이의 PC 실행기 둘, 서버를 띄운 채 `uv run` | §3 「Windows 주의점」 |


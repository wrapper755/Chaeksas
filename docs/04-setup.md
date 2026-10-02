# 04. 개발 환경 구성

> 상태: **일부 확인됨.** `uv sync --all-packages` → `uv run pytest`가 **CI(Windows Server + Linux x86_64)와 개발 PC(Linux aarch64)에서 돈다.** `web/`·Playwright·Docker 쪽과 Windows 데스크톱(Studio 창·트레이·UIA)은 그 단계가 오면 갱신한다.
> 이 문서는 **새 PC에서 이 문서만 보고** 환경을 만들 수 있어야 한다. 막히는 곳이 있으면 그 자리에서 고친다.

## 1. 어떤 PC에 무엇을 까는가

| PC 역할 | OS | 필요한 것 |
| --- | --- | --- |
| 클라이언트 개발 (Studio·Bot UI·Worker 프로세스) | **Windows 10/11 (주)**, Linux | Git, uv, Python, Playwright 브라우저 |
| 서버 개발 (Center·서버 실행기·서비스 앱) | **Linux (주)**, Windows | Git, uv, Python, Docker (Neo4j용), Ollama |
| 한 대로 전부 | Windows 또는 Linux | 위 둘 다 |

## 2. 공통 도구

| 도구 | 버전 | 용도 |
| --- | --- | --- |
| Git | 최신 | 소스 관리 |
| uv | 최신 | Python 설치·가상환경·의존성 (pip·venv 직접 사용 안 함) |
| Python | **3.12** ([ADR-0005](decisions/0005-python-version.md)) | **직접 깔지 않는다 — uv가 내려받는다.** 시스템 Python 버전은 상관없다 |
| Docker | 최신 | 서버 쪽 Neo4j (선택: PostgreSQL) |
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
corepack enable          # pnpm 사용 준비
cd web
pnpm install             # M1 이후
pnpm dev --filter center-console   # http://localhost:8501
```

- 토큰을 바꾸면 `uv run python scripts/gen_tokens.py`로 웹 CSS·Qt QSS를 다시 만든다 (M1).
- 사내망에서 글꼴을 외부 CDN으로 받지 않는다. Pretendard 파일은 저장소에 포함한다.

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

## 4. Linux (서버 주 환경)

```bash
# 1) uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) 저장소와 의존성 (uv가 3.12를 내려받는다)
git clone https://github.com/wrapper755/Chaeksas.git ~/dev/Chaeksas && cd ~/dev/Chaeksas
uv sync --all-packages
uv run pytest

# 3) Neo4j (UI 자동화 앱용)
docker run -d --name chaeksas-neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/<비밀번호> neo4j:5

# 4) Ollama (로컬 LLM을 쓸 때)
curl -fsSL https://ollama.com/install.sh | sh
```

> 제안: M2에서 서버 쪽 구성(Center, 서비스 앱, Neo4j)을 `docker compose` 파일 하나로 묶는다. 그러면 Windows에서도 Docker Desktop으로 같은 서버를 띄울 수 있다.

## 5. 설정과 비밀

- 설정 파일: 저장소의 `configs/*.example.yaml`을 복사해 쓴다 (M1).
- 비밀(토큰·DB 비밀번호·API 키): `.env` (git 제외) 또는 OS 비밀 저장소. 설정 파일·코드에 넣지 않는다.
- 환경변수 접두사: **`CHK_`** 하나. 중첩은 `__` (예: `CHK_CENTER__PORT`, `CHK_CENTER__API_KEY`). [ADR-0011](decisions/0011-config-ports-env.md)
- 우선순위: 환경변수 > `.env` > 설정 파일 > 기본값.
- 서비스 앱 API 키: 평소에는 OS 비밀 저장소. 개발·CI에서만 `CHK_SERVICE_APP__API_KEY`로 넣을 수 있다.
- 서버 실행기: 들어오는 포트가 없다 (Center로 접속만). 동시 실행 상한 `CHK_SERVER_RUNNER__MAX_CONCURRENCY`(기본 10), Center API 키(서버 실행기용) `CHK_SERVER_RUNNER__CENTER_API_KEY`(개발·CI만, 평소에는 서버 비밀 저장소). 서비스 앱 키 값은 `chk-runner keys set <참조>` (가안) ([ADR-0015](decisions/0015-run-location.md)).
- Bot UI 대기열 크기: 기본 20, `CHK_BOT_UI__QUEUE__MAX`. 실행 자리(동시 실행 Bot 수)는 1로 고정이라 설정이 없다 ([ADR-0014](decisions/0014-one-bot-per-pc.md)).
- Worker 프로세스는 Bot UI가 띄운다. 개발 PC에도 Bot UI를 설치해 켜 두면 Studio 시험 실행이 그 Worker를 쓴다.
- Center API 키: Center 콘솔(CON-11)에서 발급해 Bot UI 설정·Studio 설정에 넣는다. 개발·CI에서만 `CHK_CENTER__API_KEY`.

## 6. 포트

아래 기본값을 쓰고, 바꿔야 하면 설정 파일 또는 환경변수로 바꾼다. 코드에는 포트 숫자를 직접 쓰지 않는다 ([ADR-0011](decisions/0011-config-ports-env.md)). 이 표가 기본값의 원본이다.

| 구성요소 | 기본 포트 | 바인드 | 바꾸는 환경변수 |
| --- | --- | --- | --- |
| Center API | 8800 | 서버 | `CHK_CENTER__PORT` |
| Center 콘솔 (웹) | 8501 | 서버 | `CHK_CONSOLE__PORT` |
| UI 자동화 앱 API | 8000 | 서버 | `CHK_SVC_UI_AUTOMATION__PORT` |
| 다음 서비스 앱 | 8010부터 10씩 | 서버 | `CHK_SVC_<앱 id>__PORT` |
| Worker 로컬 API | 8899 | 127.0.0.1 고정 | `CHK_WORKER__LOCAL_API__PORT` |
| Bot UI 메시지 수신 (ReceiveTask·메시지 시작 이벤트) | 8790 | 127.0.0.1 기본 | `CHK_BOT_UI__WEBHOOK__PORT` |
| UI 자동화 앱 관리 콘솔 | 8001 | 서버 | `CHK_SVC_UI_AUTOMATION__CONSOLE_PORT` |
| Neo4j | 7474 (HTTP) / 7687 (Bolt) | 서버 | `CHK_SVC_UI_AUTOMATION__NEO4J__URI` |
| Ollama | 11434 | 로컬 또는 서버 | `CHK_LLM__BASE_URL` |

> 주의: 프로토타입과 같은 기본 포트다. 한 PC에서 프로토타입과 새 구성요소를 동시에 띄우면 충돌하므로, 그때는 환경변수로 한쪽을 옮긴다.

## 7. 확인 체크리스트 (M1 완료 시 채움)

- [x] Windows에서 clone → `uv sync` → 테스트 통과 (CI `windows-latest` = Windows Server. **Windows 11 데스크톱은 아직 확인 안 됨**)
- [x] Linux에서 clone → `uv sync` → 테스트 통과 (CI `ubuntu-latest` x86_64 + 개발 PC aarch64)
- [ ] Windows에서 Studio 창이 뜬다
- [ ] Windows에서 Bot UI가 Worker 프로세스를 띄우고, Worker가 Chromium을 조작한다
- [ ] Linux 서버의 Center에 Windows Bot UI가 Center API 키로 등록·하트비트한다

# 01. 아키텍처

> 상태: **제안**. 코드가 생기면 실제 모듈 이름으로 갱신한다.
> 용어: "BPM 프로세스(=Bot)"는 업무, "<이름> 프로세스"는 OS 프로세스, "UI"·앱 이름은 화면 있는 프로그램이다 ([02-glossary.md](02-glossary.md) §0).

## 1. 배치

```
 ┌───────────────────────────── 서버 (Linux 주 / Windows 선택) ─────────────────────────────┐
 │  Center API ── Center DB          서비스 앱들                                           │
 │  Center 콘솔 (웹)                  ├─ UI 자동화 앱 ── Neo4j    + 관리 콘솔 (웹)          │
 │  - Center API 키 발급              ├─ (다음 서비스 앱)          + 관리 콘솔 (웹)          │
 │                                   └─ 각 앱: 서비스 앱 API 키 발급·검증                    │
 │  서버 실행기 (Center 관리, 서버 BPM 프로세스 동시 실행)                                     │
 │  LLM 게이트웨이 (Ollama 또는 외부 API)                                                   │
 └──────▲───────────────────▲──────────────────────▲───────────────────────▲──────────────┘
        │ 업로드             │ 등록·하트비트·         │ 서비스 앱 태스크        │ 계획·치유·보고
        │ (Center API 키)    │ 다운로드·실행기록       │ (서비스 앱 API 키)      │ (Worker → UI 자동화 앱)
        │                   │ (Center API 키)        │                       │
 ┌── 설계자 PC ─────────────┐ ┌──────────────────── 현장 PC (Windows 주 / Linux 선택) ─────────────────┐
 │ Studio (자율 수행)        │ │ Bot UI (트레이 GUI, 항상 실행)                                         │
 │ Bot UI + Worker 프로세스  │ │  ├─ 실행 ─▶ Bot (BPM 프로세스, 결정 수행) ──REST 127.0.0.1──▶ Worker   │
 │  (개발 실행·셀렉터 등록)   │ │  ├─ 시작·감시 ─▶ Worker 프로세스 (서버, 화면 없음) ── 브라우저·데스크톱 │
 │ Admin (서명)             │ │  └─ 유틸리티: UI 셀렉터 등록                                           │
 └──────────────────────────┘ └────────────────────────────────────────────────────────────────────┘
```

## 2. 구성요소

| 구성요소 | 종류 | 위치 | 책임 | 책임지지 않는 것 |
| --- | --- | --- | --- | --- |
| 공통 계약 (`contracts`) | 패키지 | 모든 곳 | 주고받는 데이터 모델, 스키마 버전, 해시·서명 규칙 | 로직, I/O |
| 런타임 코어 (`core`) | 패키지 | Studio, Bot UI(실행기), 서버 실행기 | BPMN 실행, **확장 호스트**(확장을 찾아 기여 등록), HTTP 어댑터 해석기, AI 태스크(에이전트 루프), 도구, 재생 기억, 설정 로더 | 화면(Qt), 서버 통신 |
| 확장 API (`extension_api`) | 패키지 | 모든 클라이언트·실행하는 쪽 | 확장이 구현하는 안정 인터페이스: 태스크 종류·수행기, Studio 편집기, Bot UI 유틸리티, 로컬 런타임, 사전 점검, HTTP 어댑터 해석 규격 ([ADR-0018](decisions/0018-extensions.md)) | 특정 확장의 로직 |
| 확장 (`extensions/*`, 외부 정의) | 확장 | 곳곳 (기여 지점) | BPM 프로세스에 공통 기능을 더함. 서버 부분(서비스 앱) + 클라이언트 기여. 확장 정의 C13 | 플랫폼 흐름 |
| 모델 클라이언트 (`llm`) | 패키지 | 모델을 부르는 모든 곳 (`core`, 서비스 앱) | OpenAI 호환 `/v1/chat/completions` 어댑터와 그 모양(`Reply`·`ToolSpec`·`LlmError`). **맨 아래** — 우리 멤버를 하나도 모른다 ([ADR-0034](decisions/0034-service-app-model-connection.md)) | 도구 루프·결과 검증·궤적(`core.agent`), 주소·키 보관 |
| 서비스 앱 뼈대 (`service_kit`) | 패키지 | 서비스 앱 | API 키 발급·검증, 관리 API(상태·키·사용 기록 — 화면은 `web/apps/svc-console`), `/healthz`, `/manifest`, 작업 호출 틀(수행 모드), 로깅 | 업무 로직 |
| Studio | 화면 | 설계자 PC | BPM 프로세스 편집(BPMN), 시험 실행(자율 수행·재생), 학습, 패키지 빌드·업로드 | 배포 결정 |
| **Bot UI** | 화면 (트레이) | 현장 PC, 설계자 PC | Center 등록·하트비트(Center API 키), **Bot 다운로드·설치·실행**(결정 수행, 실행 자리 하나 + 대기열), **Worker 프로세스 시작·감시·재시작**, **UI 셀렉터 등록**, 로컬 결재·확인 창, 서비스 앱 키 값 보관 | 셀렉터 보관, 화면 조작 자체 |
| 실행기 | 프로세스 | 현장 PC | 실행 중인 Bot 하나 (Bot UI의 자식, 동시에 하나만, [ADR-0014](decisions/0014-one-bot-per-pc.md)) | 다른 실행, 대기열 |
| **Worker** (UI 자동화 확장의 로컬 런타임) | 프로세스 (서버) | 현장 PC, 설계자 PC | 127.0.0.1 REST: UI 세션, 로케이터 사다리 실행, 치유 제안 검증, 셀렉터 등록용 분석·선택·검증 | 화면(GUI), 그래프 쓰기, 업무 판단 |
| 서버 실행기 | 프로세스 (서버) | 서버 | 실행 위치 「서버」인 BPM 프로세스를 동시 실행(상한 있음), 기다리는 동안 실행 상태 저장·재개, Center API 키로 등록·하트비트, 서비스 앱 키 값 보관(서버 비밀 저장소) | UI 태스크, 웹·데스크톱 AI 태스크, 현장 결재·확인 |
| Admin | 도구 | 관리자 PC | 서명 키, 패키지 승인·배포 서명 | 서버 운영 |
| Center | 서버 | 서버 | 패키지 레지스트리, Bot UI 등록·상태, 배포, 작업, 결재 창구, 실행 이력, 리소스 목록, Center API 키, 콘솔 | BPMN 해석, 비밀(서비스 앱 키) 저장, 배포 결정 |
| 서비스 앱 (확장의 서버 부분) | 서버 | 서버 또는 외부 | BPM 프로세스가 API로 맡기는 일 (C11, 외부 앱은 HTTP 어댑터), 자기 API 키 발급·검증, 관리 콘솔 | 프로세스 흐름, 작업 배분 |
| UI 자동화 앱 (첫 내장 확장의 서버 부분) | 서버 | 서버 | 화면·요소·로케이터 그래프, 실행 계획, 치유 제안, 승격, 관리 콘솔(셀렉터·모니터링) | 브라우저 실행 |

## 3. 태스크별 호출 경로

| 태스크 종류 | 경로 | 서버 호출 시점 |
| --- | --- | --- |
| AI 태스크 | Bot(실행기, core) → LLM 게이트웨이, 도구. 결정 수행이면 재생 명세로 LLM 없이 | 자율 수행: LLM 호출마다. 결정 수행: 값 추출 때만 |
| UI 태스크 | Bot → Worker 프로세스(REST, 127.0.0.1) → UI 자동화 앱 | 계획을 받을 때, 모든 로케이터가 실패했을 때, 끝날 때 보고 |
| 서비스 앱 태스크 | Bot → 서비스 앱 `POST /v1/ops/{작업}` (서비스 앱 API 키, 수행 모드) | 태스크 한 번에 한 번 |
| 결재 | Bot → Bot UI → Center (하트비트로 답 수신) 또는 현장 PC 결재 창. PC Bot은 답이 올 때까지 실행 자리를 쥐고 기다린다 | 요청·답 |
| (서버 실행) PC 위임 (제안) | 서버 실행기 → Center 작업 → Bot UI 대기열 → PC Bot → 결과가 Center를 거쳐 서버 실행기로. 서버 Bot은 상태 저장 후 대기 ([ADR-0016](decisions/0016-server-first.md) §3) | 위임 요청·결과 |
| (서버 실행) 모든 태스크 | 서버 실행기(core) → LLM·서비스 앱. 결재는 Center 결재함만, 기다리는 동안 상태 저장 | 태스크 종류별로 위와 같음 |

- **수행 모드:** Studio 개발 실행 = 자율 수행, Bot UI의 Bot 실행 = 결정 수행. 실행 주체가 정하고, Worker·서비스 앱은 받은 모드를 따른다 ([ADR-0010](decisions/0010-service-apps.md)).
- **서비스 앱 키:** BPM 프로세스 속성의 키 참조를 실행하는 쪽(Bot UI / Studio / 서버 실행기)이 자기 비밀 저장소에서 풀어 쓴다. UI 태스크는 Bot이 푼 키를 Worker 세션 요청에 실어 보낸다 ([ADR-0013](decisions/0013-api-keys.md), 제안).

## 4. 통신 규칙

1. **연결은 항상 현장 PC → 서버.** 서버가 현장 PC로 먼저 연결하지 않는다. 서버 실행기도 Center에 먼저 접속하는 쪽이다. 지시(배포·작업·결재 답)는 Bot UI 하트비트 응답에 실려 내려간다 ([ADR-0007](decisions/0007-client-initiated-communication.md)).
2. **Center 인증은 Center API 키.** Bot UI·Studio·서버 실행기마다 키 하나. 키가 그 Bot UI의 신원이라 다른 Bot UI를 사칭할 수 없다 ([ADR-0013](decisions/0013-api-keys.md)).
3. **Bot → Worker는 같은 PC의 127.0.0.1만.** 로컬 토큰으로 같은 PC의 다른 프로그램도 막는다. Worker는 Bot UI가 띄워 두며, 응답이 없으면 Bot UI가 다시 띄우고, 그래도 안 되면 UI 태스크를 확인(실행 개입)으로 넘긴다 ([ADR-0012](decisions/0012-bot-ui.md)).
4. **UI 태스크 도중에는 서버를 거의 부르지 않는다.** 로케이터 사다리는 Worker가 가진 계획으로 로컬에서 돈다.
5. **서버가 꺼져 있어도 현장 PC는 가능한 만큼 계속한다.** 계획은 캐시, 보고·실행 기록은 로컬 큐. 서비스 앱 태스크는 서버가 없으면 실패하고 재시도 정책을 따른다.
6. 모든 메시지는 `contracts` 패키지의 모델로 만들고 검증한다.
7. 모든 내장·사내 서비스 앱은 공통 계약 C11(healthz, manifest, 수행 모드, 자체 API 키 검증)을 지킨다. 외부 앱은 확장 정의의 HTTP 어댑터(C13)로 붙이고, 어댑터는 허용 호스트에만 닿는다.
8. **서버 우선, 실행 위치에 따라 규칙이 다르다.** 기본은 서버 ([ADR-0016](decisions/0016-server-first.md)). PC: 한 대에서 실행 중인 Bot은 하나, 끝날 때까지 기다림. 서버: 서버 실행기가 동시 실행, 기다리는 동안 상태 저장 ([ADR-0015](decisions/0015-run-location.md)). 아래는 PC 쪽.
   **PC 한 대에서 실행 중인 Bot은 하나.** 다른 요청은 Bot UI 대기열에서 기다리고, 대기열 상태는 하트비트로 Center에 보고한다. Worker의 UI 세션도 한 번에 하나라, Bot 실행·Studio 시험 실행·UI 셀렉터 등록이 겹치지 않는다 ([ADR-0014](decisions/0014-one-bot-per-pc.md)).

## 5. 의존 방향 (코드)

```
contracts ◀── extension_api ◀── core ◀── studio, bot_ui, server_runner
    ▲               ▲
    │               └── extensions/<id>/client  (확장 호스트가 엔트리 포인트로 찾음)
    ├── service_kit ◀── extensions/<id>/service
    ├── extensions/<id>/worker  (로컬 런타임)
    ├── center
    └── admin

llm ◀── core, service_kit   (맨 아래 — chaeksas의 아무것도 import하지 않는다, ADR-0034)
```

- **플랫폼은 특정 확장을 import하지 않는다.** `core`·`apps/*`는 `extension_api`를 통해서만 확장을 부르고, 확장은 엔트리 포인트 `chaeksas.extensions`로 찾는다. 확장끼리도 import하지 않는다 ([ADR-0018](decisions/0018-extensions.md)).
  - 찾아 켜는 것은 `chaeksas.core.extensions`의 **확장 호스트**다 (**있음**). 확장의 `extension.json`(C13)은 그 확장의 파이썬 패키지 안에 있고, 정의가 가리키는 `entry`는 그 패키지 안만 가리킬 수 있다. 검사 규칙에 걸리거나 `api` 범위가 맞지 않는 확장은 켜지 않고 사유와 함께 목록에 남는다.

- `web/`은 Python 코드를 import하지 않는다. HTTP로만 부르고, 타입은 `contracts`의 JSON Schema에서 생성한다. 브라우저는 서버 API를 직접 부르지 않는다 (콘솔 서버가 중계, [ADR-0017](decisions/0017-web-nextjs-design-system.md)).
- `center`, `extensions/*/service`, `extensions/*/worker`는 `core`를 import하지 않는다.
- 서비스 앱끼리 서로 import하지 않는다. 필요하면 HTTP로 부른다.
- `core`는 Qt를 import하지 않는다. 화면은 `studio`, `bot_ui`의 몫. `worker`는 화면이 없다.
- 제품 코드는 `spikes/`를 import하지 않는다.
- 위 규칙은 `tests/test_import_direction.py`가 강제한다 (**있음**). 두 가지를 본다: 선언한 의존(`pyproject.toml`, 전이 포함)과 실제 import(AST). 규칙을 더하려면 그 파일의 `FORBIDDEN_DEPS`·`FORBIDDEN_IMPORTS` 표에 줄을 더한다.

## 6. OS별로 갈리는 지점 (인터페이스 뒤에 둔다)

| 기능 | Windows (주) | Linux (선택) | 비고 |
| --- | --- | --- | --- |
| 데스크톱 앱 조작 (Worker) | UIA (`uiautomation`, [ADR-0020](decisions/0020-windows-desktop-backend.md)) | AT-SPI | 프로토타입은 AT-SPI만 실사용. Windows는 S1에서 메모장·엑셀로 확인 |
| 화면 캡처 (Worker) | `mss`, Worker는 Per-Monitor v2 DPI 인식 ([ADR-0021](decisions/0021-worker-dpi-capture.md)) | xdg-desktop-portal, Pillow | 배율(125%, 150%) 주의 |
| 브라우저 조작 (Worker) | Playwright (Chromium/Edge) | Playwright | 공통 |
| Bot UI 로그인 시 자동 시작 | 작업 스케줄러 「로그온 시」 (현재 사용자, [ADR-0023](decisions/0023-bot-ui-process-supervision.md)) | XDG autostart | 트레이 하나만 |
| 자식 프로세스 관리 (Bot UI → Worker, 실행기) | 자식마다 Job Object (`KILL_ON_JOB_CLOSE`) | 프로세스 그룹 | 공통 헬퍼 하나로 ([ADR-0023](decisions/0023-bot-ui-process-supervision.md)) |
| 무인 실행 (로그인 없이) | Windows 서비스 — UI 태스크 불가 | systemd | **나중에 검토** |
| 비밀 저장 (Center 키, 서비스 앱 키 값) | Windows 자격 증명 관리자 (`keyring`) | Secret Service (`keyring`) | |
| 사용자 데이터 위치 | `%LOCALAPPDATA%\Chaeksas\` | `~/.local/share/chaeksas/` | `platformdirs` |

## 7. 저장소

| 데이터 | 저장 위치 | 비고 |
| --- | --- | --- |
| 패키지 파일 (zip) | Center 파일 저장소 | DB에는 메타데이터만. 비밀 없음 |
| Bot UI·배포·작업·결재·실행 이력·리소스·Center API 키(해시) | Center DB | SQLite로 시작, PostgreSQL 호환 |
| 화면·요소·로케이터·인텐트 | UI 자동화 앱의 Neo4j | YAML 레지스트리는 개발용 폴백 |
| 서비스 앱 API 키(해시)·사용 기록 | 각 서비스 앱 | |
| 서비스 앱 키 값, Center 키 값 | Bot UI·Studio PC의 OS 비밀 저장소, 서버 실행기는 서버의 비밀 저장소·환경변수 | |
| 서버 실행 상태 (기다리는 실행) | 서버 실행기 저장소 (SQLite로 시작) | 재시작 후 이어 가기 |
| 재생 기억(성공 궤적) | **패키지 안 `memory/specs.json`** (C1) | Studio가 자율 수행으로 만들어 넣고, 배포된 Bot은 **읽기만** 한다 ([ADR-0028](decisions/0028-replay-memory.md)) |
| 실행 기록·보고 버퍼 | 현장 PC 로컬 큐 | 전송 후 삭제 |
| BPM 프로세스가 만든 파일 (보고서·표) | 실행하는 쪽의 **출력 폴더** | 실행마다 하나. 쓰기는 그 안만, 읽기는 **읽기 허용 폴더**까지 ([ADR-0026](decisions/0026-file-paths-and-file-list-task.md)) |

## 8. 저장소(코드) 구조

폴더는 아래 그대로, **import 이름은 `chaeksas.<이름>`**(확장은 `chaeksas.ext.<id>`)이다. src 레이아웃이라 멤버마다 `src/chaeksas/<이름>/`이고, `src/chaeksas/`에는 `__init__.py`를 두지 않는다 (PEP 420 네임스페이스, [ADR-0019](decisions/0019-package-names.md)).

```
Chaeksas/
├─ pyproject.toml          # uv workspace 루트 (패키지 아님) + ruff·pytest·mypy 설정
├─ .python-version         # 3.12 (ADR-0005)
├─ uv.lock                 # 워크스페이스 전체 하나
├─ packages/
│  ├─ contracts/           # 공통 계약
│  ├─ extension_api/       # 확장이 구현하는 인터페이스 (ADR-0018)
│  ├─ core/                # 런타임 코어 + 확장 호스트
│  ├─ llm/                 # 모델 클라이언트 (맨 아래, ADR-0034)
│  ├─ qt/                  # 공용 PySide6 위젯·테마·결재 창
│  └─ service_kit/         # 서비스 앱 공통 뼈대 + 관리 API
├─ apps/
│  ├─ studio/
│  ├─ bot_ui/              # 트레이 GUI + 실행기 + 확장 기여(유틸리티·로컬 런타임) 자리
│  ├─ server_runner/       # 서버 실행기 (화면 없음, core 사용)
│  ├─ admin/
│  └─ center/              # Center API (콘솔은 web/apps/center-console)
├─ extensions/             # 내장 확장 (확장 하나 = 폴더 하나, ADR-0018)
│  └─ ui_automation/       # extension.json, contracts/(C8·C9·C10), service/(UI 자동화 앱),
│                          # worker/(Worker 프로세스), client/(UI 태스크·STU-13·BUI-06~08), console/(UIA-01~03)
├─ web/                    # 웹 화면 (Next.js, pnpm 워크스페이스, ADR-0017)
│  ├─ apps/center-console/ # Center 콘솔
│  ├─ apps/svc-console/    # 서비스 앱 관리 콘솔 (앱마다 하나씩 띄움)
│  └─ packages/            # ui(구성요소+토큰 CSS), api-types(계약에서 생성), config
├─ design/                 # tokens.json (디자인 토큰 원본), preview.html
├─ spikes/                 # 실험 (제품 코드에서 import 금지, 워크스페이스 멤버 아님)
├─ tests/                  # 앱 간 통합·계약 테스트 + 의존 방향 검사(§5)
└─ docs/
```

> 상태: 위 Python 멤버 12개(`llm`은 M4에 더했다)와 `tests/`는 M1에서 만들어졌다 (`uv sync --all-packages` → `uv run pytest`). `web/`도 뼈대가 있다 (pnpm 워크스페이스: `apps/center-console`·`apps/svc-console`, `packages/ui`·`api-types`·`config`). 화면 내용은 M2다.

근거: [ADR-0018](decisions/0018-extensions.md), [ADR-0017](decisions/0017-web-nextjs-design-system.md), [ADR-0015](decisions/0015-run-location.md), [ADR-0004](decisions/0004-monorepo-uv-workspace.md), [ADR-0010](decisions/0010-service-apps.md), [ADR-0012](decisions/0012-bot-ui.md), [ADR-0013](decisions/0013-api-keys.md).

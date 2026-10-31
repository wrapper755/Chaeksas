# 01. 아키텍처

> 상태: **제안**. 코드가 생기면 실제 모듈 이름으로 갱신한다.
> 용어: "BPM 프로세스"는 업무, "<이름> 프로세스"는 OS 프로세스, "UI"·앱 이름은 화면 있는 프로그램이다 ([02-glossary.md](02-glossary.md) §0).

## 1. 배치

```
 ┌───────────────────────────── 서버 (Linux 주 / Windows 선택) ─────────────────────────────┐
 │  Center API ── Center DB          서비스 앱들 (C11 일꾼)                                  │
 │  Center 콘솔 (웹, 관리자 계정)      ├─ (서비스 앱)              + 관리 콘솔 (웹)          │
 │  - 승인·배포 (Center가 서명)       └─ 어댑터 일꾼 (외부 앱 HTTP 어댑터)                   │
 │  - Center API 키 발급                                                                    │
 │  - 외부 작업 대기열 (C15)                                                                │
 │  서버 실행기 (Center 관리, 서버 BPM 프로세스 동시 실행)                                     │
 │  LLM 게이트웨이 (Ollama 또는 외부 API)                                                   │
 └──────▲───────────────────▲──────────────────────▲──────────────────────────────────────┘
        │ 업로드             │ 등록·하트비트·         │ 외부 작업 올리기·결과
        │ (Center API 키)    │ 다운로드·실행기록       │ (호출 토큰)
        │                   │ (Center API 키)        │
 ┌── 설계자 PC ─────────────┐ ┌──────────────────── 현장 PC (Windows 주 / Linux 선택) ─────────────────┐
 │ Studio (자율 수행)        │ │ PC 실행기 (트레이 GUI, 항상 실행)                                         │
 │ PC 실행기                 │ │  ├─ 실행 ─▶ 실행 프로세스 (BPM 프로세스 하나, 결정 수행)                │
 │                          │ │  └─ 현장 결재·확인 창 (CMN-01)                                         │
 └──────────────────────────┘ └────────────────────────────────────────────────────────────────────┘
```

## 2. 구성요소

| 구성요소 | 종류 | 위치 | 책임 | 책임지지 않는 것 |
| --- | --- | --- | --- | --- |
| 공통 계약 (`contracts`) | 패키지 | 모든 곳 | 주고받는 데이터 모델, 스키마 버전, 해시·서명 규칙 | 로직, I/O |
| 런타임 코어 (`core`) | 패키지 | Studio, PC 실행기(실행기), 서버 실행기 | BPMN 실행, **확장 호스트**(확장을 찾아 기여 등록), HTTP 어댑터 해석기, AI 태스크(에이전트 루프), 도구, 재생 기억, 설정 로더 | 화면(Qt), 서버 통신 |
| 확장 API (`extension_api`) | 패키지 | 모든 클라이언트·실행하는 쪽 | 확장이 구현하는 안정 인터페이스: 태스크 종류·수행기, Studio 편집기, 사전 점검, HTTP 어댑터 해석 규격 ([ADR-0018](decisions/0018-extensions.md)) | 특정 확장의 로직 |
| 확장 (내장·사내는 파이썬 패키지, 외부는 정의 파일) | 확장 | 곳곳 (기여 지점) | BPM 프로세스에 공통 기능을 더함. 서버 부분(서비스 앱) + 클라이언트 기여. 확장 정의 C13. **지금 깔린 내장 확장은 없다** ([ADR-0114](decisions/0114-remove-ui-automation.md)) | 플랫폼 흐름 |
| 모델 클라이언트 (`llm`) | 패키지 | 모델을 부르는 모든 곳 (`core`, 서비스 앱) | OpenAI 호환 `/v1/chat/completions` 어댑터와 그 모양(`Reply`·`ToolSpec`·`LlmError`). **맨 아래** — 우리 멤버를 하나도 모른다 ([ADR-0034](decisions/0034-service-app-model-connection.md)) | 도구 루프·결과 검증·궤적(`core.agent`), 주소·키 보관 |
| 서비스 앱 뼈대 (`service_kit`) | 패키지 | 서비스 앱 | **일꾼**(`service_kit.consumer` — Center 들이기·가져가기 루프·manifest·카탈로그 올리기, C15), 작업 틀(수행 모드·멱등·오류 형식), 관리 API(상태·사용 기록 — 화면은 `web/apps/svc-console`), `/healthz`, 로깅 | 업무 로직, 업무 호출을 받는 포트 |
| 어댑터 일꾼 (`adapter_consumer`, `chk-adapter-consumer`) | 프로세스 (서버) | 서버 또는 외부 앱이 있는 망 | 외부 확장 정의(C13)의 HTTP 어댑터를 C15 일꾼으로 돌린다. **외부 앱의 주소·키는 이 일꾼의 설정에만** 있다 ([ADR-0102](decisions/0102-calling-outside-is-pull.md) §4) | 정의 등록(Center) |
| Studio | 화면 | 설계자 PC | BPM 프로세스 편집(BPMN), 시험 실행(자율 수행·재생), 학습, 패키지 빌드·업로드 | 배포 결정 |
| **PC 실행기** | 화면 (트레이) | 현장 PC, 설계자 PC | Center 등록·하트비트(Center API 키), **BPM 프로세스 다운로드·설치·실행**(결정 수행, 실행 자리 하나 + 대기열), 로컬 결재·확인 창, C15 호출 토큰 받기(메모리에만 두고 실행 프로세스에 넘긴다), 확장 켜기·끄기(BUI-11) | 화면 조작 자체 |
| 실행 프로세스 | 프로세스 | 현장 PC | 실행 중인 BPM 프로세스 하나 (PC 실행기의 자식, 동시에 하나만, [ADR-0014](decisions/0014-one-bot-per-pc.md)) | 다른 실행, 대기열 |
| 서버 실행기 | 프로세스 (서버) | 서버 | 실행 위치 「서버」인 BPM 프로세스를 동시 실행(상한 있음), 기다리는 동안 실행 상태 저장·재개, Center API 키로 등록·하트비트, 바깥 기능은 제 Center API 키로 C15에 올린다 | 웹·데스크톱 AI 태스크, 현장 결재·확인 |
| Center | 서버 | 서버 | 패키지 레지스트리, **관리자 계정**, 승인·배포 봉투 서명(서버의 키, [ADR-0090](decisions/0090-center-admin-accounts.md)), PC 실행기 등록·상태, 배포, 작업, 결재 창구, 실행 이력, 리소스 목록, Center API 키, **외부 작업 대기열·일꾼 승인**(C15), 콘솔 | BPMN 해석, 바깥 기능의 주소·키 |
| 서비스 앱 (확장의 서버 부분) | 서버 | 서버 또는 외부 | BPM 프로세스가 맡기는 일을 Center에서 가져가 수행 (C11 일꾼, C15. 외부 앱은 어댑터 일꾼), 관리 콘솔 | BPM 프로세스 흐름, 작업 배분(Center가 한다) |

## 3. 태스크별 호출 경로

| 태스크 종류 | 경로 | 서버 호출 시점 |
| --- | --- | --- |
| AI 태스크 | BPM 프로세스(실행기, core) → LLM 게이트웨이, 도구. 결정 수행이면 재생 명세로 LLM 없이 | 자율 수행: LLM 호출마다. 결정 수행: 값 추출 때만 |
| 서비스 앱 태스크 | BPM 프로세스 → Center `POST /api/v1/external-tasks`(토픽 = `app_id`, 수행 모드) ← 서비스 앱·어댑터 일꾼이 가져가 끝낸다 → BPM 프로세스가 결과를 기다려 받는다 (C15, [ADR-0102](decisions/0102-calling-outside-is-pull.md)) | 태스크 한 번에 한 번 (올리기 + 결과 기다리기) |
| 결재 | BPM 프로세스 → PC 실행기 → Center (하트비트로 답 수신) 또는 현장 PC 결재 창. PC BPM 프로세스는 답이 올 때까지 실행 자리를 쥐고 기다린다 | 요청·답 |
| (서버 실행) PC 위임 | 서버 실행기 → Center 작업 → PC 실행기 대기열 → PC BPM 프로세스 → 결과가 Center를 거쳐 서버 실행기로. 서버 BPM 프로세스는 상태 저장 후 대기 ([ADR-0062](decisions/0062-pc-delegation.md)) | 위임 요청·결과 |
| (서버 실행) 모든 태스크 | 서버 실행기(core) → LLM·Center 외부 작업(서비스 앱). 결재는 Center 결재함만, 기다리는 동안 상태 저장 | 태스크 종류별로 위와 같음 |

- **수행 모드:** Studio 개발 실행 = 자율 수행, PC 실행기의 BPM 프로세스 실행 = 결정 수행. 실행 주체가 정하고, 서비스 앱은 받은 모드를 따른다 ([ADR-0010](decisions/0010-service-apps.md)).
- **서비스 앱 키는 없다** ([ADR-0102](decisions/0102-calling-outside-is-pull.md)). 부르는 쪽은 Center에 올릴 때 **호출 토큰**을 쓴다 — 서버 실행기·Studio는 제 Center API 키, 실행 프로세스는 PC 실행기가 청해 넘긴 호출 토큰(24시간). 「불러도 되나」는 Center가 배포에서 가린다 (C15).

## 4. 통신 규칙

1. **연결은 항상 현장 PC → 서버.** 서버가 현장 PC로 먼저 연결하지 않는다. 서버 실행기도 Center에 먼저 접속하는 쪽이다. 지시(배포·작업·결재 답)는 PC 실행기 하트비트 응답에 실려 내려간다 ([ADR-0007](decisions/0007-client-initiated-communication.md)).
2. **Center 인증은 Center API 키.** PC 실행기·Studio·서버 실행기마다 키 하나. 키가 그 PC 실행기의 신원이라 다른 PC 실행기를 사칭할 수 없다 ([ADR-0013](decisions/0013-api-keys.md)).
3. **서버가 꺼져 있어도 현장 PC는 가능한 만큼 계속한다.** 실행 기록·결재 요청은 로컬 파일이 원본이고 닿을 때 보낸다. 서비스 앱 태스크는 서버가 없으면 실패하고 재시도 정책을 따른다.
4. 모든 메시지는 `contracts` 패키지의 모델로 만들고 검증한다.
5. 모든 내장·사내 서비스 앱은 공통 계약 C11(일꾼 루프, manifest, 수행 모드, 관리 콘솔)을 지킨다. 외부 앱은 확장 정의의 HTTP 어댑터(C13)로 붙이고, 어댑터는 허용 호스트에만 닿는다.
6. **서버 우선, 실행 위치에 따라 규칙이 다르다.** 기본은 서버 ([ADR-0016](decisions/0016-server-first.md)). PC: 한 대에서 실행 중인 BPM 프로세스는 하나, 끝날 때까지 기다림. 서버: 서버 실행기가 동시 실행, 기다리는 동안 상태 저장 ([ADR-0015](decisions/0015-run-location.md)). 아래는 PC 쪽.
   **PC 한 대에서 실행 중인 BPM 프로세스는 하나.** 다른 요청은 PC 실행기 대기열에서 기다리고, 대기열 상태는 하트비트로 Center에 보고한다 ([ADR-0014](decisions/0014-one-bot-per-pc.md)).

## 5. 의존 방향 (코드)

```
contracts ◀── extension_api ◀── core ◀── studio, bot_ui, server_runner, adapter_consumer
    ▲               ▲
    │               └── (확장의 클라이언트 부분 — 확장 호스트가 엔트리 포인트로 찾음)
    ├── service_kit ◀── (확장의 서버 부분 = 서비스 앱), samples/mock_apps
    └── center

llm ◀── core, service_kit   (맨 아래 — chaeksas의 아무것도 import하지 않는다, ADR-0034)
```

- **플랫폼은 특정 확장을 import하지 않는다.** `core`·`apps/*`는 `extension_api`를 통해서만 확장을 부르고, 확장은 엔트리 포인트 `chaeksas.extensions`로 찾는다. 확장끼리도 import하지 않는다 ([ADR-0018](decisions/0018-extensions.md)).
  - 찾아 켜는 것은 `chaeksas.core.extensions`의 **확장 호스트**다 (**있음**). 확장의 `extension.json`(C13)은 그 확장의 파이썬 패키지 안에 있고, 정의가 가리키는 `entry`는 그 패키지 안만 가리킬 수 있다. 검사 규칙에 걸리거나 `api` 범위가 맞지 않는 확장은 켜지 않고 사유와 함께 목록에 남는다.

- `web/`은 Python 코드를 import하지 않는다. HTTP로만 부르고, 타입은 `contracts`의 JSON Schema에서 생성한다. 브라우저는 서버 API를 직접 부르지 않는다 (콘솔 서버가 중계, [ADR-0017](decisions/0017-web-nextjs-design-system.md)).
- `center`와 서비스 앱(확장의 서버 부분)은 `core`를 import하지 않는다.
- **Studio는 Center를 읽는다** (`studio/services.py` — C7 리소스 목록·믿는 서명 키). 쓰지 않는다. 실행기는 Center를 부르지 않는다 ([ADR-0031](decisions/0031-runner-control-file.md)) — Studio는 실행기가 아니라 제 안에서 엔진을 돌리는 쪽이라 다르다.
- 서비스 앱끼리 서로 import하지 않는다. 필요하면 HTTP로 부른다.
- `core`는 Qt를 import하지 않는다. 화면은 `studio`, `bot_ui`의 몫.
- 제품 코드는 `spikes/`를 import하지 않는다.
- **아무 멤버도 `samples/`를 의존하지 않는다.** `samples/mock_apps`는 업무 예제가 부르는 모의 앱이고(`samples/README.md`), 쓰는 쪽은 `tests/`와 사람이 띄우는 `chk-mock-apps`뿐이다. 그 안의 C11 앱도 서비스 앱이라 `core`를 import하지 않는다.
- 위 규칙은 `tests/test_import_direction.py`가 강제한다 (**있음**). 두 가지를 본다: 선언한 의존(`pyproject.toml`, 전이 포함)과 실제 import(AST). 규칙을 더하려면 그 파일의 `FORBIDDEN_DEPS`·`FORBIDDEN_IMPORTS` 표에 줄을 더한다.

## 6. OS별로 갈리는 지점 (인터페이스 뒤에 둔다)

| 기능 | Windows (주) | Linux (선택) | 비고 |
| --- | --- | --- | --- |
| PC 실행기 로그인 시 자동 시작 | 작업 스케줄러 「로그온 시」 (현재 사용자, [ADR-0023](decisions/0023-bot-ui-process-supervision.md)) | XDG autostart | 트레이 하나만 |
| 자식 프로세스 관리 (PC 실행기 → 실행 프로세스) | 자식마다 Job Object (`KILL_ON_JOB_CLOSE`) | 프로세스 그룹 | 공통 헬퍼 하나로 ([ADR-0023](decisions/0023-bot-ui-process-supervision.md)) |
| 무인 실행 (로그인 없이) | Windows 서비스 — 현장 확인 불가 | systemd | **나중에 검토** |
| 비밀 저장 (Center 키, 모델 키) | Windows 자격 증명 관리자 (`keyring`) | Secret Service (`keyring`) | |
| 사용자 데이터 위치 | `%LOCALAPPDATA%\Chaeksas\` | `~/.local/share/chaeksas/` | `platformdirs` |

## 7. 저장소

| 데이터 | 저장 위치 | 비고 |
| --- | --- | --- |
| 패키지 파일 (zip) | Center 파일 저장소 | DB에는 메타데이터만. 비밀 없음 |
| PC 실행기·배포·작업·결재·실행 이력·리소스·Center API 키(해시) | Center DB | SQLite로 시작, PostgreSQL 호환 |
| 서비스 앱 사용 기록·멱등 결과 | 각 서비스 앱 | |
| 외부 작업(일감)의 입력·출력 | Center DB | 부른 쪽이 받으면(`ack`) 지우고, 못 받은 것은 7일에 지운다 (C15) |
| Center 키 값, 일꾼 토큰 | PC 실행기·Studio PC의 OS 비밀 저장소, 서버 실행기는 서버의 비밀 저장소·환경변수, 일꾼은 데이터 폴더의 토큰 파일(`0600`)·환경변수 | |
| 외부 앱의 주소·키 | 어댑터 일꾼의 설정(환경변수) | Center·현장은 모른다 |
| 서버 실행 상태 (기다리는 실행) | 서버 실행기 저장소 (SQLite로 시작) | 재시작 후 이어 가기 |
| 재생 기억(성공 궤적) | **패키지 안 `memory/specs.json`** (C1) | Studio가 자율 수행으로 만들어 넣고, 배포된 BPM 프로세스는 **읽기만** 한다 ([ADR-0028](decisions/0028-replay-memory.md)) |
| 실행 기록 | 실행하는 쪽의 `runs/<run_id>.jsonl` (원본) | 하트비트 뒤에 Center로 보낸다 |
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
│  ├─ bot_ui/              # PC 실행기 (트레이 GUI) + 실행 프로세스
│  ├─ server_runner/       # 서버 실행기 (화면 없음, core 사용)
│  ├─ adapter_consumer/    # 어댑터 일꾼 (외부 확장의 HTTP 어댑터, C15)
│  └─ center/              # Center API (콘솔은 web/apps/center-console)
├─ web/                    # 웹 화면 (Next.js, pnpm 워크스페이스, ADR-0017)
│  ├─ apps/center-console/ # Center 콘솔
│  ├─ apps/svc-console/    # 서비스 앱 관리 콘솔 (앱마다 하나씩 띄움)
│  └─ packages/            # ui(구성요소+토큰 CSS), api-types(계약에서 생성), config
├─ design/                 # tokens.json (디자인 토큰 원본), preview.html
├─ samples/                # 제품이 아니다 — 업무 예제가 부르는 모의 앱 (워크스페이스 멤버)
│  └─ mock_apps/           # C11 앱 13 + 외부 앱 2 + 그 C13 어댑터 정의. chk-mock-apps
├─ spikes/                 # 실험 (제품 코드에서 import 금지, 워크스페이스 멤버 아님)
├─ tests/                  # 앱 간 통합·계약 테스트 + 의존 방향 검사(§5)
└─ docs/
```

> 상태: 위 Python 멤버 12개(`packages/*` 여섯·`apps/*` 다섯·`samples/mock_apps`)가 돈다 (`uv sync --all-packages` → `uv run pytest`). 내장 확장을 두는 `extensions/<id>/`는 지금 없다 — 확장을 다시 들일 때 워크스페이스 멤버 목록에 `extensions/*`를 함께 더한다 ([ADR-0114](decisions/0114-remove-ui-automation.md)). `web/`은 pnpm 워크스페이스다 (`apps/center-console`·`apps/svc-console`, `packages/ui`·`api-types`·`config`).

근거: [ADR-0114](decisions/0114-remove-ui-automation.md), [ADR-0018](decisions/0018-extensions.md), [ADR-0017](decisions/0017-web-nextjs-design-system.md), [ADR-0015](decisions/0015-run-location.md), [ADR-0004](decisions/0004-monorepo-uv-workspace.md), [ADR-0010](decisions/0010-service-apps.md), [ADR-0012](decisions/0012-bot-ui.md), [ADR-0013](decisions/0013-api-keys.md).

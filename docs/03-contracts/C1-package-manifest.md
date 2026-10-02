# C1. 패키지 매니페스트

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Studio(빌드) → Center(업로드·검사·보관) → Bot UI·서버 실행기(설치·사전 점검) |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/manifest.py` (import `chaeksas.contracts.manifest`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c1-manifest.json`](../../packages/contracts/schemas/c1-manifest.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0006](../decisions/0006-single-contracts-package.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md) |

## 목적

패키지(zip) 안의 `manifest.json`이 "이 패키지가 무엇이고, 어디서 돌며, 실행하려면 무엇이 있어야 하는가"를 말한다. Center는 이것으로 업로드를 검사하고, Bot UI·서버 실행기는 이것으로 설치 전 사전 점검을 한다. **키 값은 들어가지 않는다** — 키 참조 이름만 들어간다.

## 전송

- 방식: 파일. 패키지 zip 루트의 `manifest.json` (UTF-8, LF). 업로드는 C5.
- 인증: 해당 없음 (패키지 자체는 C2 서명 봉투로 보호).
- 멱등성: 같은 `id`+`version`·같은 `content_hash`를 다시 올리면 200 (재시도 안전). 내용이 다르면 409 (C5) → 버전을 올린다.
- 크기 한도: `manifest.json` 256 KB, 패키지 zip 50 MB (Center 설정 `CHK_CENTER__PACKAGE__MAX_MB`).

### 패키지 구성

```
<package>.zip
├─ manifest.json            # 이 계약
├─ process/                 # 진입 정의 + 하위 정의 (.bpmn), 규칙 (.dmn)
├─ memory/specs.json        # 재생 명세 (학습 자료)
├─ preflight.json           # Studio가 계산한 사전 점검 결과 (노드별 ok/warning/blocked)
├─ libs/                    # 복사해 넣은 공유 BPM 프로세스 (requires.libs)
└─ SIGNATURE                # Admin 승인 서명 (C2, 있을 때만)
```

시험 케이스·실행 기록·비밀은 넣지 않는다.

## 모델

### Manifest (최상위)

| 필드 | 타입 | 필수 | 뜻 | 추가된 schema |
| --- | --- | --- | --- | --- |
| `schema` | int | ✓ | 이 계약의 schema 번호. 지금 1 | 1 |
| `kind` | `"bpm_process"` \| `"process_lib"` \| `"toolpack"` | ✓ | 패키지 종류. 운영 화면에서 `bpm_process`가 Bot / 서버 Bot이다 | 1 |
| `id` | str | ✓ | 소문자·숫자·`.` `_` `-`, 1~100자, 첫 글자는 소문자·숫자 | 1 |
| `version` | str | ✓ | SemVer (`1.2.0`, `1.2.0-rc.1`) | 1 |
| `name` | str | | 화면 표시 이름 | 1 |
| `description` | str | | | 1 |
| `run_location` | `"server"` \| `"pc"` | `bpm_process`만 ✓ | **실행 위치.** 생략하면 `server` (서버 우선). 다른 kind에는 두지 않는다 | 1 |
| `entry` | str | `bpm_process`만 ✓ | 진입 정의 경로 (예: `process/main.bpmn`) | 1 |
| `process_id` | str | `bpm_process`만 ✓ | 진입 정의의 BPMN process id | 1 |
| `triggers` | Trigger[] | | 시작 방법 | 1 |
| `requires` | Requires | ✓ | 실행에 필요한 것 (아래) | 1 |
| `human` | HumanNeeds | ✓ | 사람 개입 종류 (서버 검사에 씀) | 1 |
| `outputs` | str[] | | 실행이 끝나면 만드는 변수 이름 | 1 |
| `provides` | Provides | `process_lib`·`toolpack`만 | 제공하는 BPM 프로세스·도구 목록 | 1 |
| `built` | Built | ✓ | 누가 언제 무엇으로 빌드했나 | 1 |
| `content_hash` | str | ✓ | `sha256:<hex>`. 계산 규칙은 C2 (SIGNATURE와 이 필드 자신은 제외) | 1 |

### Requires

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `core` | str | 필요한 런타임 코어 버전 범위 (예: `>=0.3,<0.4`) |
| `tools` | str[] | 쓰는 도구 이름 전체 (AI 태스크의 허용 도구 합) |
| `domains` | str[] | AI 태스크 대상 환경 합: `llm` `api` `doc` `web` `desktop` |
| `settings` | str[] | 실행하는 쪽이 갖춰야 할 설정 이름: `llm` `vlm` `smtp` |
| `secrets` | str[] | 툴팩이 쓰는 비밀 **이름**만 |
| `service_apps` | ServiceAppNeed[] | 부르는 서비스 앱과 **키 참조** (아래). UI 태스크가 있으면 `ui-automation`이 들어간다 |
| `resources` | `{type, id}`[] | 확장이 기여한 자원 중 쓰는 것 (예: `{type: "ui_page", id: "erp.order.form"}`). Center 리소스 목록(C7 확장 기여 자원)과 대조 |
| `extensions` | `{id, version, definition_hash?}`[] | 쓰는 확장과 버전 범위 (C13). 외부 확장이면 `definition_hash`로 정의를 고정한다. Studio가 채운다 |
| `task_types` | `{id, extension, run_locations}`[] | 쓰는 태스크 종류 중 **확장이 기여한 것**과, 그 확장 정의에 적힌 실행 위치. Studio가 빌드할 때 확장 정의에서 옮겨 적는다. Center는 이것으로 R2를 판정하고, 실행하는 쪽은 자기 확장 정의로 다시 확인한다 |
| `libs` | str[] | 복사해 넣은 공유 BPM 프로세스 `<id>@<version>` |
| `toolpacks` | ToolpackRef[] | 쓰는 툴팩 `{id, version, content_hash}` (해시로 고정) |
| `runtimes` | str[] | 예: `node>=20`, `chromium` |
| `os` | str[] | `windows` `linux`. 비면 제한 없음 |

### ServiceAppNeed

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `app_id` | str | ✓ | 서비스 앱 id (C11 manifest의 `app_id`) |
| `operations` | str[] | ✓ | 부르는 작업 이름 |
| `key_ref` | str | ✓ | BPM 프로세스 단위 **키 참조 이름**. `^[a-z0-9][a-z0-9-]{0,39}$` (1~40자, 소문자·숫자·`-`). Studio 기본값은 BPM 프로세스 id에서 `.`·`_`를 `-`로 바꾸고 40자로 자른 것 (예: `finance.invoice-issue` → `finance-invoice-issue`) |
| `task_key_refs` | str[] | | 태스크에서 다르게 지정한 참조 (예외). 사전 점검은 `key_ref` + 이것 모두를 찾는다 |

### HumanNeeds

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `approval_center` | bool | Center 결재함으로 가는 결재가 있다 |
| `approval_field` | bool | 「현장」 결재 위치(현장 PC 창)가 있다 |
| `confirmation` | bool | 실행 중 확인(막힘)이 생길 수 있다 (AI 태스크 확인 트리거, UI 태스크 전환) |

### Trigger, Provides, Built

| 모델 | 필드 |
| --- | --- |
| Trigger | `kind`: `none` \| `message` \| `timer` \| `conditional` \| `signal`, `name`(메시지 이름) |
| ToolpackRef | `id`, `version`, `content_hash` |
| Provides | `processes`: `{process_id, file, name, description, reads[], writes[], run_location, ai_tasks, human}`[] · `tools`: `{name, domain, description, args(JSON Schema)}`[] |
| Built | `by`: `studio` \| `cli`, `at`(ISO 8601), `core`(버전), `spec_version`(재생 명세 버전) |

## 검사 규칙

Studio(빌드 때), Center(업로드 때), Bot UI·서버 실행기(설치 때)가 **같은 함수**(`contracts.manifest.validate`)로 검사한다.

| # | 규칙 | 위반 시 |
| --- | --- | --- |
| R1 | `kind=bpm_process`면 `run_location`, `entry`, `process_id`가 있다 (`run_location`은 생략 시 `server`로 채움) | 422 |
| R2 | `run_location=server`면: `requires.domains`에 `web`·`desktop` 없음, `requires.task_types[]`가 모두 `run_locations`에 `server`를 가짐 (예: `ui_task`는 `pc`만이라 불가), `human.approval_field=false`, `human.confirmation=false` | 422 `server_incompatible` + 걸린 항목 목록 |
| R3 | `run_location=server`인 BPM 프로세스가 `run_location=pc`인 공유 BPM 프로세스를 부르면 PC 위임이다 → schema 1에서는 **거부** (PC 위임은 ADR-0016 §3 제안, 확정되면 필드를 추가) | 422 `delegation_not_supported` |
| R8 | (Center, 배포 때) `run_location=server`면 `requires.service_apps[].operations`가 모두 C11 manifest에서 `server_ok=true`이고 결정 수행을 지원한다 (리소스 목록 C7과 대조). 업로드 때는 경고만 | 배포 422 `operation_not_server_ok` / `operation_not_deterministic` |
| R4 | `key_ref`·`task_key_refs`는 이름 규칙을 따른다. 규칙상 `_`가 없어 키 값(`chk_…`)은 들어갈 수 없다 | 422 `invalid_key_ref` |
| R5 | `manifest.json`·BPMN 어디에도 키 값·비밀 값이 없다 (Studio 빌드가 보장, Center는 R4만 검사) | — |
| R6 | `content_hash`가 실제 내용과 같다 (C2) | 422 `hash_mismatch` |
| R7 | `requires.toolpacks[].content_hash`가 비어 있지 않다 (로컬 개발용 툴팩은 업로드 불가) | 422 |

## 예시

서버 Bot (기본):

```json
{
  "schema": 1,
  "kind": "bpm_process",
  "id": "finance.invoice-issue",
  "version": "1.0.0",
  "name": "세금계산서 발행",
  "run_location": "server",
  "entry": "process/main.bpmn",
  "process_id": "invoice_issue",
  "triggers": [{"kind": "message", "name": "invoice.requested"}],
  "requires": {
    "core": ">=0.3,<0.4",
    "tools": ["doc.read_pdf"],
    "domains": ["llm", "doc"],
    "settings": ["llm"],
    "secrets": [],
    "service_apps": [
      {"app_id": "tax-invoice", "operations": ["issue"], "key_ref": "finance-invoice"}
    ],
    "resources": [],
    "task_types": [],
    "extensions": [],
    "libs": [],
    "toolpacks": [],
    "runtimes": [],
    "os": []
  },
  "human": {"approval_center": true, "approval_field": false, "confirmation": false},
  "outputs": ["invoice_no"],
  "built": {"by": "studio", "at": "2026-10-01T10:00:00+09:00", "core": "0.3.0", "spec_version": 1},
  "content_hash": "sha256:9f2c…"
}
```

PC Bot (UI 태스크가 있음):

```json
{
  "schema": 1,
  "kind": "bpm_process",
  "id": "erp.order-entry",
  "version": "2.1.0",
  "run_location": "pc",
  "entry": "process/main.bpmn",
  "process_id": "order_entry",
  "requires": {
    "domains": ["llm"],
    "service_apps": [
      {"app_id": "ui-automation", "operations": ["plan", "heal", "report"], "key_ref": "erp-order"}
    ],
    "resources": [{"type": "ui_page", "id": "erp.order.form"}],
    "task_types": [{"id": "ui_task", "extension": "ui-automation", "run_locations": ["pc"]}],
    "extensions": [{"id": "ui-automation", "version": ">=0.4,<0.5"}],
    "os": ["windows"]
  },
  "human": {"approval_center": false, "approval_field": true, "confirmation": true},
  "built": {"by": "studio", "at": "2026-10-01T10:00:00+09:00", "core": "0.3.0", "spec_version": 1},
  "content_hash": "sha256:41ab…"
}
```

## 오류

| 상태 코드 | 언제 | 보내는 쪽이 할 일 |
| --- | --- | --- |
| 400 | zip이 깨짐, `manifest.json` 없음, JSON 아님 | 다시 빌드 |
| 200 | 같은 `id`+`version`이고 `content_hash`도 같음 (재시도한 업로드) | 성공으로 본다 |
| 409 | 같은 `id`+`version`인데 내용이 다름 (C5) | 버전을 올린다 |
| 422 | 검사 규칙 R1~R7 위반, 모르는(더 높은) `schema` | 응답 `detail[]`의 규칙 코드를 Studio 「실행 전 검사」와 같은 문구로 보인다 |

## 호환 규칙

- 받는 쪽이 모르는 **선택 필드**를 받으면: 보관하고 무시한다 (패키지 해시는 원문 그대로 유지).
- 받는 쪽보다 **높은 `schema`** 를 받으면: 거부한다 (아는 필드의 뜻이 바뀌었을 수 있다).
- `run_location`이 없는 매니페스트는 `server`로 읽는다. 단, Studio는 빌드할 때 **항상 명시**한다.
- M6까지 Center는 `run_location=server` 패키지의 **업로드는 받고 서버 배포는 거부**한다 (「서버 실행은 M7부터」, C5).

## 프로토타입과 달라진 것

| 프로토타입 | 여기 |
| --- | --- |
| `kind`: `employee` / `process-lib` / `toolpack` / `template` | `bpm_process` / `process_lib` / `toolpack` (template 없음) |
| 실행 위치 없음 (전부 PC) | `run_location` (기본 `server`) |
| `hitl.business` / `hitl.execution` | `human.approval_center` / `approval_field` / `confirmation` (서버 검사에 필요) |
| 서비스 앱·화면 의존 없음 | `requires.service_apps`(키 참조 포함), `requires.extensions`·`task_types`·`resources` |

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 | 0013, 0015, 0016 |
| 2026-10-01 | 1 | 검토 반영: `key_ref` 규칙 하나로(40자), 같은 해시 재업로드 200, R8 서버 작업 검사 | — |
| 2026-10-01 | 1 | 확장 반영: `requires.extensions`, R2를 확장 정의의 `run_locations`로 판정 | 0018 |
| 2026-10-01 | 1 | 확장 검토 반영: `ui_pages` → `resources{type,id}`, `task_types{id, extension, run_locations}`로 R2 판정, 외부 확장 `definition_hash` 고정 | 0018 |

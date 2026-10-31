# C1. 패키지 매니페스트

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-10, [09-gaps](../09-gaps.md) §1 대조 — `Provides`를 Studio가 짓고 CON-06이 읽는다) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Studio(빌드) → Center(업로드·검사·보관) → PC 실행기·서버 실행기(설치·사전 점검) |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/manifest.py` (import `chaeksas.contracts.manifest`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c1-manifest.json`](../../packages/contracts/schemas/c1-manifest.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0006](../decisions/0006-single-contracts-package.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0110](../decisions/0110-center-keeps-the-schedule.md) |

## 목적

패키지(zip) 안의 `manifest.json`이 "이 패키지가 무엇이고, 어디서 돌며, 실행하려면 무엇이 있어야 하는가"를 말한다. Center는 이것으로 업로드를 검사하고, PC 실행기·서버 실행기는 이것으로 설치 전 사전 점검을 한다. **키 값도 키 참조도 들어가지 않는다** — 바깥 기능은 Center의 외부 작업으로 부른다 (C15, ADR-0102).

## 전송

- 방식: 파일. 패키지 zip 루트의 `manifest.json` (UTF-8, LF). 업로드는 C5.
- 인증: 해당 없음 (패키지 자체는 C2 서명 봉투로 보호).
- 멱등성: 같은 `id`+`version`·같은 `content_hash`를 다시 올리면 200 (재시도 안전). 내용이 다르면 409 (C5) → 버전을 올린다.
- 크기 한도: `manifest.json` 256 KB, 패키지 zip 50 MB (Center 설정 `BPM_CENTER__PACKAGE__MAX_MB`).

### 패키지 구성

```
<package>.zip
├─ manifest.json            # 이 계약
├─ process/                 # 진입 정의 + 하위 정의 (.bpmn), 규칙 (.dmn)
├─ memory/specs.json        # 재생 명세 (학습 자료)
├─ preflight.json           # Studio가 계산한 사전 점검 결과 (노드별 ok/warning/blocked)
├─ libs/                    # 복사해 넣은 공유 BPM 프로세스 (requires.libs) — 정의(.bpmn)와 그것이 쓰는 결정표(.dmn)
└─ SIGNATURE                # 승인 서명 — Center가 짓는다 (C2, 있을 때만)
```

시험 케이스·실행 기록·비밀은 넣지 않는다.

## 모델

### Manifest (최상위)

| 필드 | 타입 | 필수 | 뜻 | 추가된 schema |
| --- | --- | --- | --- | --- |
| `schema` | int | ✓ | 이 계약의 schema 번호. 지금 1 | 1 |
| `kind` | `"bpm_process"` \| `"process_lib"` | ✓ | 패키지 종류. 운영 화면에서 `bpm_process`가 BPM 프로세스 / 서버 BPM 프로세스이다. **도구 묶음(툴팩)은 패키지가 아니다** — 도구는 확장이 기여한다 ([ADR-0050](../decisions/0050-no-toolpack-kind.md)) | 1 |
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
| `inputs` | ManifestInput[] | | 진입 정의가 받는 입력 (`bpm:process.inputs`를 그대로 옮긴 것 — `source?` 포함). 작업을 만드는 화면(CON-05)이 입력 칸을 그린다(**`source`가 있는 입력은 그리지 않는다** — Center가 넣는다). Center는 `source`가 있는 이름이 작업 `inputs`에 오면 거절한다(C5 `input_not_from_caller`, [ADR-0099](../decisions/0099-input-value-source.md)). 실행하는 쪽은 이것이 아니라 BPMN을 본다 | 1 |
| `outputs` | str[] | | 실행이 끝나면 만드는 변수 이름 | 1 |
| `provides` | Provides | `process_lib`만 | 제공하는 BPM 프로세스 목록 | 1 |
| `built` | Built | ✓ | 누가 언제 무엇으로 빌드했나 | 1 |
| `content_hash` | str | ✓ | `sha256:<hex>`. 계산 규칙은 C2 (SIGNATURE와 이 필드 자신은 제외) | 1 |

### ManifestInput

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `name` | str | 입력 변수 이름 |
| `type` | str | 값 타입 (C14 `VALUE_TYPES`) |
| `required` | bool | 주지 않으면 실행이 시작되지 않는다. 기본 `false` |
| `description` | str? | 화면 안내 |
| `default` | any? | 주지 않았을 때의 값. **업무 값을 넣지 않는다** (패키지는 서명되어 여러 PC로 간다) |

### Requires

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `core` | str | 필요한 런타임 코어 버전 범위 (예: `>=0.3,<0.4`) |
| `tools` | str[] | 쓰는 도구 이름 전체 (AI 태스크의 허용 도구 합) |
| `domains` | str[] | AI 태스크 대상 환경 합: `llm` `api` `doc` `web` `desktop`. **`web`·`desktop`은 낱말로만 남는다** — 그 환경을 주는 확장이 없어 실행하는 쪽의 사전 점검이 `missing_agent_environment`로 시작 전에 막는다 ([ADR-0114](../decisions/0114-remove-ui-automation.md)) |
| `settings` | str[] | 실행하는 쪽이 갖춰야 할 설정 이름: `llm` `vlm` `smtp` |
| `service_apps` | ServiceAppNeed[] | 부르는 서비스 앱(= C15 토픽)과 작업 (아래). 제 앱을 부르는 확장(C13 `requires_keys[].purpose: run`)의 태스크가 있으면 그 확장 id가 들어간다 |
| `resources` | `{type, id}`[] | 확장이 기여한 자원 중 쓰는 것 (예: `{type: "seal_specimen", id: "hq.corporate-seal"}`). Center 리소스 목록(C7 확장 기여 자원)과 대조 |
| `extensions` | `{id, version, definition_hash?}`[] | 쓰는 확장과 버전 범위 (C13). 외부 확장이면 `definition_hash`로 정의를 고정한다. Studio가 채운다 |
| `task_types` | `{id, extension, run_locations?}`[] | 쓰는 태스크 종류 중 **확장이 기여한 것**과, 그 확장 정의에 적힌 실행 위치. Studio가 빌드할 때 확장 정의에서 옮겨 적는다. Center는 이것으로 R2를 판정하고, 실행하는 쪽은 자기 확장 정의로 다시 확인한다. **`run_locations`는 아는 쪽이 준다 — 모르면 넣지 않는다**: 빌드하는 PC에 그 확장이 깔려 있지 않거나 꺼져 있으면(ADR-0043) 적을 값이 없다 |
| `libs` | str[] | 복사해 넣은 공유 BPM 프로세스 `<id>@<version>` |
| `delegations` | str[] | **PC 위임**으로 부르는 PC BPM 프로세스 `<id>@<version>` 또는 `<id>`(판을 비우면 배포된 판). 복사해 넣는 것이 **아니다** — 따로 올리고 따로 배포한 BPM 프로세스라 `libs/`에 들어가지 않는다 ([ADR-0062](../decisions/0062-pc-delegation.md)). Studio가 그림(`bpm:call.delegate`)에서 모은다 |
| `runtimes` | str[] | 예: `node>=20`, `chromium` |
| `os` | str[] | `windows` `linux`. 비면 제한 없음 |

### ServiceAppNeed

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `app_id` | str | ✓ | 서비스 앱 id (C11 manifest의 `app_id`) |
| `operations` | str[] | ✓ | 부르는 작업 이름 |

> [ADR-0102](../decisions/0102-calling-outside-is-pull.md): **키가 없다.** 바깥 기능은 Center의 외부 작업으로 부르므로(C15) 현장에 키가 없고, 매니페스트에도 키 참조 칸이 없다.
> - 옛 패키지에 적힌 `key_ref`·`task_key_refs`는 **모르는 칸으로 받아 두고 보지 않는다**(원칙 3) — 거부하지 않으므로 옛 패키지도 그대로 올라가고 설치된다. 빌드는 적지 않는다.
> - `app_id`가 곧 **토픽**이다 — Center는 배포된 BPM 프로세스의 `requires.service_apps`(와 `requires.extensions`)에 있는 토픽만 그 BPM 프로세스가 올리게 둔다(C15 「불러도 되나」). `operations`는 그 안의 허용 작업이다(비면 모든 작업).

### HumanNeeds

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `approval_center` | bool | Center 결재함으로 가는 결재가 있다 |
| `approval_field` | bool | 「현장」 결재 위치(현장 PC 창)가 있다 |
| `confirmation` | bool | 실행 중 확인(막힘)이 생길 수 있다 (AI 태스크 확인 트리거, 확장 태스크의 전환) |

### Trigger, Provides, Built

| 모델 | 필드 |
| --- | --- |
| Trigger | `kind`: `none` \| `message` \| `timer` \| `conditional` \| `signal`, `name`(이벤트 이름 — 메시지·신호), `expression`(타이머 식) |
| Provides | `processes`: `{process_id, file, name, description, reads[], writes[], run_location, ai_tasks, human}`[] |
| Built | `by`: `studio` \| `cli`, `at`(ISO 8601), `core`(버전), `spec_version`(재생 명세 버전) |

**`triggers`는 진입 정의의 시작 이벤트를 그대로 옮긴 것이다** — `kind`는 BPMN 시작 이벤트의
이벤트 정의와 1:1이고, 값은 이 다섯뿐이다 (R9가 검사한다).

| `kind` | 시작 이벤트 | `name` | `expression` |
| --- | --- | --- | --- |
| `none` | 이벤트 정의 없음 | — | — |
| `message` | `messageEventDefinition` | `messageRef`가 가리키는 `bpmn:message name` | — |
| `timer` | `timerEventDefinition` | — | `timeCycle` 본문 (5필드 cron 또는 ISO `R/…`) |
| `conditional` | `conditionalEventDefinition` | — | — |
| `signal` | `signalEventDefinition` | `signalRef`가 가리키는 `bpmn:signal name` | — |

- **이름과 식은 다른 칸이다.** `name`은 이벤트 **이름**이고(C12 메시지 API가 이 이름으로 보낸다),
  타이머 식은 `expression`에 싣는다. 한 칸에 둘을 담으면 `timer` 트리거의 `name`을 메시지
  이름으로 읽어 **영원히 오지 않는 메시지를 보낸다**.
- **`none`은 「시작 이벤트에 정의가 없다」는 뜻**이다. 그 BPM 프로세스는 작업 지시(C5 `/jobs`)나 수동
  실행으로만 시작한다.
- **`conditional`·`signal`로 시작하는 그림은 schema 1의 범위 밖이다** (C14 §이벤트 — 조건 시작은
  쓰지 않고, 신호는 한 실행 안의 가지 사이에서만 간다). 그래도 **`none`으로 뭉개지 않고 그린 대로
  적는다** — 「작업 지시로 시작한다」고 적어 주면 왜 안 도는지 아무도 모른다.
- **타이머 일정은 Center가 `triggers`로 쓴다** ([ADR-0110](../decisions/0110-center-keeps-the-schedule.md),
  C5 §일정) — Center는 그림을 읽지 않으므로 Studio가 `timeCycle` 본문을 `expression`에 옮겨 둔 것이
  일정의 원본이다. 읽는 문법은 `contracts.schedule` 하나이고 **R13이 올릴 때 같은 함수로 본다**.
  실행하는 쪽(PC 실행기·서버 실행기)은 일정을 잡지 않는다 — 일정이 만든 것은 평범한 작업이다.
  메시지 시작도 Center가 `triggers`의 이름으로 고른다(C12 — 상관 키는 Center가 기다리는 실행과 맞춘다).

## 검사 규칙

Studio(빌드 때), Center(업로드 때), PC 실행기·서버 실행기(설치 때)가 **같은 함수**(`contracts.manifest.validate`)로 검사한다.

| # | 규칙 | 위반 시 |
| --- | --- | --- |
| R1 | `kind=bpm_process`면 `run_location`, `entry`, `process_id`가 있다 (`run_location`은 생략 시 `server`로 채움) | 422 |
| R2 | `run_location=server`면: `requires.domains`에 `web`·`desktop` 없음, `requires.task_types[]`가 **`run_locations`를 적었으면** 거기에 `server`가 있음 (`pc`만 적은 종류는 불가), `human.approval_field=false`, `human.confirmation=false` | 422 `server_incompatible` + 걸린 항목 목록 |
| R3 | `run_location=server`인 BPM 프로세스가 `run_location=pc`인 **공유 BPM 프로세스**를 부르면 **거부**다. PC 위임의 길이 아니다 — 패키지에 복사해 넣은 정의는 **PC에서 돌릴 길이 없다**(작업은 배포된 패키지를 가리키고 공유 BPM 프로세스에는 진입이 없다, R1). 위임은 `requires.delegations`로 적는다 ([ADR-0062](../decisions/0062-pc-delegation.md)) | 422 `delegation_not_supported` |
| R8 | (Center, 배포 때) `run_location=server`면 `requires.service_apps[].operations`가 모두 C11 manifest에서 `server_ok=true`이고 결정 수행을 지원한다 (리소스 목록 C7과 대조). 업로드 때는 경고만 | 배포 422 `operation_not_server_ok` / `operation_not_deterministic` |
| R4 | (없앴다 — 키 참조 칸이 없다, ADR-0102. 번호는 다시 쓰지 않는다) | — |
| R5 | `manifest.json`·BPMN 어디에도 키 값·비밀 값이 없다 (Studio 빌드가 보장한다) | — |
| R6 | `content_hash`가 실제 내용과 같다 (C2) | 422 `hash_mismatch` |

**R7은 없어졌다** — 툴팩 해시를 검사하던 규칙이고 툴팩 갈래가 사라졌다 ([ADR-0050](../decisions/0050-no-toolpack-kind.md)). **번호는 다시 쓰지 않는다** (오류 코드는 사람이 기억한다).
| R9 | `triggers[].kind`가 위 다섯 중 하나다 | 422 `unknown_trigger_kind` + 걸린 값 목록 |
| R10 | `requires.delegations`가 있으면 `run_location=server`다 — **PC 위임은 서버 BPM 프로세스만 한다** (PC 실행은 그 PC의 자리를 끝까지 쥐므로 PC가 PC를 기다리면 서로를 기다린다, [ADR-0014](../decisions/0014-one-bot-per-pc.md)). C14 B14가 그림에서 같은 것을 보지만 **매니페스트를 보는 쪽은 그림을 읽지 않는다** | 422 `delegation_not_from_pc` + 걸린 BPM 프로세스 목록 |
| R11 | `requires.settings`가 아는 값 중 하나다 (`llm`·`vlm`·`smtp`) — **R9와 같은 까닭**이다: 그림에서 기계가 옮기는 값이고(`bpm:email` → `smtp`) 읽는 쪽은 그 이름으로 「이 호스트가 갖췄나」를 본다(`core.preflight`). 모르는 이름은 그 점검을 **아무 말 없이 지나가** 준비되지 않은 BPM 프로세스가 실행된다 | 422 `unknown_setting` + 걸린 값 목록 |
| R12 | `requires.delegations`에 **자기 `id`가 없다** — 자기 자신에게 위임하지 않는다 (끝나지 않는 되부름이다, [ADR-0082](../decisions/0082-batch-start.md)). 그림은 자기 패키지 id를 모르므로 매니페스트가 본다 | 422 `delegation_to_self` + 그 항목 |
| R13 | `triggers[kind=timer].expression`을 **Center가 읽을 수 있다** — 5필드 cron(`*`·수·`a-b`·`/n`·쉼표, 일 칸 `L`, 요일 0~7) 또는 ISO `R[n]/<시작>/<기간>`·`R[n]/<기간>`(1분 이상). **R9와 같은 까닭**이다: 일정은 Center가 이 식으로 쓰므로(C5 §일정) 읽지 못하는 식은 그 BPM 프로세스를 **아무 말 없이 영영 돌지 않게** 한다. 읽는 함수는 `contracts.schedule` 하나다 ([ADR-0110](../decisions/0110-center-keeps-the-schedule.md)) | 422 `timer_expression_invalid` + 걸린 식과 까닭 |

**R2는 모르는 것을 막지 않는다.** 태스크 종류의 실행 위치는 **확장 정의만** 안다 (C13
`task_types[].run_locations`, ADR-0018) — 빌드하는 PC에 그 확장이 없거나 꺼져 있으면 Studio가
적을 값이 없다. 그래서 `run_locations`가 **없거나 비어 있으면 「모른다」**로 읽고 R2는
**선언된 것이 `server`를 빼놓았을 때만** 막는다. 모르는 것까지 막으면 확장을 깔지 않은
PC(빌드 기계도 그렇다)에서 만든 **올바른 패키지가 업로드에서 거부된다**. 확장이 **정말 없는**
경우는 따로 막힌다 — 배포 때 그 확장이 Center에 없으면 거부하고 (C7 `blocking_at_deploy`),
실행하는 쪽의 사전 점검도 `task_types_unsupported`로 시작 전에 말한다. C13은 확장이
`run_locations`를 비워 두는 것을 이미 금지하므로(`run_locations_missing`) 빈 목록이 선언에서
올 일은 없다.

**R9는 막는다 — 「모르는 것」이 아니라 빌드한 쪽의 흠이다.** 시작 방법은 그림에서 기계가
옮기는 값이라 사람이 적어 틀릴 자리가 없다. 모르는 값이 들어왔다면 **옮기는 쪽이 계약에 없는
이름을 쓴 것**이다. 경고로 두면 **올라간 뒤에 아무도 모르고**, 나중에 `triggers`를 읽는 화면이
`timer`를 기다리며 영영 못 만난다 — 실제로 그렇게 갈라져 있었다. 값이 늘어야 할 때는 이 문서의
다섯을 먼저 늘린다 — 뜻이 바뀌는 변경이라 `schema`도 함께 본다 (README 원칙 2).

## 예시

서버 BPM 프로세스 (기본):

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
    "service_apps": [
      {"app_id": "tax-invoice", "operations": ["issue"]}
    ],
    "resources": [],
    "task_types": [],
    "extensions": [],
    "libs": [],
    "delegations": [],
    "runtimes": [],
    "os": []
  },
  "human": {"approval_center": true, "approval_field": false, "confirmation": false},
  "inputs": [{"name": "대상월", "type": "string", "required": false, "description": "비우면 지난달"}],
  "outputs": ["invoice_no"],
  "built": {"by": "studio", "at": "2026-10-01T10:00:00+09:00", "core": "0.3.0", "spec_version": 1},
  "content_hash": "sha256:9f2c…"
}
```

PC BPM 프로세스 (현장 확인과 사내 확장 태스크가 있음 — 확장은 C13 예시의 가상 확장):

```json
{
  "schema": 1,
  "kind": "bpm_process",
  "id": "legal.contract-seal",
  "version": "2.1.0",
  "run_location": "pc",
  "entry": "process/main.bpmn",
  "process_id": "contract_seal",
  "triggers": [{"kind": "timer", "expression": "0 9 1 * *"}],
  "requires": {
    "domains": ["llm", "doc"],
    "service_apps": [
      {"app_id": "seal-check", "operations": ["compare"]}
    ],
    "resources": [{"type": "seal_specimen", "id": "hq.corporate-seal"}],
    "task_types": [{"id": "seal_check", "extension": "seal-check", "run_locations": ["pc", "server"]}],
    "extensions": [{"id": "seal-check", "version": ">=1.2,<1.3"}],
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
| 422 | 검사 규칙 위반(R1~R6·R9), 모르는(더 높은) `schema` | 응답 `detail[]`의 규칙 코드를 Studio 「실행 전 검사」와 같은 문구로 보인다 |

## 호환 규칙

- 받는 쪽이 모르는 **선택 필드**를 받으면: 보관하고 무시한다 (패키지 해시는 원문 그대로 유지).
- 받는 쪽보다 **높은 `schema`** 를 받으면: 거부한다 (아는 필드의 뜻이 바뀌었을 수 있다).
- `run_location`이 없는 매니페스트는 `server`로 읽는다. 단, Studio는 빌드할 때 **항상 명시**한다.
- M6까지 Center는 `run_location=server` 패키지의 **업로드는 받고 서버 배포는 거부**한다 (「서버 실행은 M7부터」, C5).

## 프로토타입과 달라진 것

| 프로토타입 | 여기 |
| --- | --- |
| `kind`: `employee` / `process-lib` / `toolpack` / `template` | `bpm_process` / `process_lib` (`toolpack`·`template` 없음 — 도구는 확장이 기여한다, [ADR-0050](../decisions/0050-no-toolpack-kind.md)) |
| 실행 위치 없음 (전부 PC) | `run_location` (기본 `server`) |
| `hitl.business` / `hitl.execution` | `human.approval_center` / `approval_field` / `confirmation` (서버 검사에 필요) |
| 서비스 앱·화면 의존 없음 | `requires.service_apps`, `requires.extensions`·`task_types`·`resources` |

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-31 | 1 | 칸은 그대로다. PC 예시를 UI 태스크 대신 사내 확장 태스크로 바꿨고, `domains`의 `web`·`desktop`은 낱말로만 남아 사전 점검이 막는다고 적었다 | [0114](../decisions/0114-remove-ui-automation.md) |
| 2026-10-30 | 1 | **타이머 일정을 Center가 `triggers`로 쓴다** — 「실행하는 쪽은 `triggers`로 일정을 잡지 않는다」를 그대로 두되 일정을 쥐는 자리가 Center임을 적었고, **R13**(타이머 식을 읽을 수 있다)을 더했다. 칸은 그대로다. 예제의 식은 모두 지난다(`0 18 L * *` 포함) | [0110](../decisions/0110-center-keeps-the-schedule.md) |
| 2026-10-29 | 1 | `requires.service_apps[].key_ref`·`task_key_refs`와 **R4를 걷었다** — 빌드가 적지 않고, 옛 패키지에 적혀 있으면 모르는 칸으로 받아 두고 보지 않는다(원칙 3). 선택 칸을 걷은 것이고 받는 쪽이 옛 칸을 거부하지 않으므로 **판을 올리지 않는다** (C4의 키 칸을 걷을 때와 같은 결) | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-29 | 1 | `key_ref`·`task_key_refs`는 옛 패키지를 읽는 칸으로만 남는다(키가 없다). `app_id`가 C15 토픽이고 배포된 Bot이 올려도 되는 토픽을 정한다 | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-26 | 1 | `inputs[].source?`(값 출처 — C14)를 옮긴다. 없으면 부르는 쪽이다 (옛 패키지와 같다) | [0099](../decisions/0099-input-value-source.md) |
| 2026-10-25 | 1 | `key_ref`는 Center가 내려 준 키를 찾는 이름(형식은 그대로), `operations`가 그 키의 허용 작업(비면 모든 작업), `task_key_refs`는 같은 키의 다른 이름, 적지 않으면 `default_key_ref`, 키를 받는 확장의 태스크도 줄이 된다 | [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 2026-10-25 | 1 | `requires.service_apps[].key_ref`를 **선택**으로 — 키를 받지 않는 외부 앱(C13 `auth` 없음)에는 빌드가 적지 않는다. 받는 쪽은 비어 있으면 묻지 않는다 | [0091](../decisions/0091-external-apps-without-auth-take-no-key.md) |
| 2026-10-20 | 1 | **R12**(자기 자신에게 위임하지 않는다)를 더했다. `requires.delegations`의 대상은 PC Bot만이 아니라 서버 Bot일 수도 있다 — 어디서 도는지는 대상 패키지가 정한다 | [0082](../decisions/0082-batch-start.md) |
| 2026-10-16 | 1 | **R11**을 더했다 — `requires.settings`가 아는 값인가. **값·칸은 그대로**이고 검사만 늘었다(R9와 같은 까닭: 기계가 옮기는 값이라 모르는 이름은 옮기는 쪽의 흠이다). 지금 Studio가 넣는 것은 `smtp` 하나뿐이라 **올라간 패키지는 다 지난다**. `built.by`는 **그대로 열린 문자열**이다 — 남의 도구로 만든 올바른 패키지를 거부하게 된다 | — |
| 2026-10-15 | 1 | **PC 위임**을 더했다 — `requires.delegations`(부르는 PC Bot `<id>@<version>?`)와 **R10**(위임은 `run_location=server`만), R3의 사유를 다시 적었다(**그 규칙은 그대로 거부다** — 복사해 넣은 PC 정의는 PC에서 돌릴 길이 없다). 선택 칸이라 **옛 패키지는 그대로 읽힌다** | [0062](../decisions/0062-pc-delegation.md) |
| 2026-10-12 | 1 | **툴팩 갈래를 뺐다** — `kind=toolpack`·`provides.tools`(`ProvidedTool`)·`requires.toolpacks`(`ToolpackRef`)·`requires.secrets`·**R7**. 툴팩은 처음부터 코드가 아니었고(용어집) 선언을 담을 자리가 계약에 없어 **이름표만 든 zip**이었다 — 도구는 확장이 기여하고 코드 있는 도구는 설치 파일로만 온다. **번호는 비워 둔다**(R8·R9는 그대로다 — 적어 둔 규칙 번호를 밀면 옛 응답의 `rule`이 다른 규칙을 가리킨다) | 0050 |
| 2026-10-12 | 1 | **`triggers`의 `kind`를 쓰는 쪽과 맞췄다.** 적어 둔 다섯(`none`·`message`·`timer`·`conditional`·`signal`)은 그대로 두고, 그림에서 옮기는 쪽(Studio)이 쓰던 `schedule`·`manual`을 `timer`·`none`으로 바꿨다 — 아무도 `kind`를 검사하지 않아 **올라간 모든 패키지가 계약에 없는 값을 담고 있었다**. 함께: 타이머 식을 `name`에 싣던 것을 **`expression` 칸**으로 갈랐고(`name`은 C12가 메시지 이름으로 읽는다), 조건·신호 시작을 `manual`로 뭉개던 것을 그린 대로 적게 했고, **R9**를 더해 다시 갈라지지 못하게 했다 | — |
| 2026-10-12 | 1 | **`libs/`에 결정표(.dmn)도 들어간다**고 적었다 — 정의만 복사하면 규칙 태스크를 쓰는 공유 BPM 프로세스가 **설치해도 돌지 않는다**(읽는 쪽이 `process/*.dmn`만 보고 있었다). 모양이 바뀐 것이 아니라 **적지 않았던 것을 적은 것**이다 (`libs/`는 처음부터 「복사해 넣은 공유 BPM 프로세스」였다) | 0048 |
| 2026-10-01 | 1 | 초안 | 0013, 0015, 0016 |
| 2026-10-11 | 1 | `requires.task_types[].run_locations`를 **선택 칸**으로 바꿨다 — 「모른다」를 적을 자리가 없어 Studio가 빈 목록을 썼고, `"server" not in []`이 참이라 **서버 Bot에 확장 태스크가 하나라도 있으면 업로드가 422**였다(그 확장이 서버를 지원해도). R2는 이제 **선언된 것이 `server`를 빼놓았을 때만** 막는다 | 0018, 0043 |
| 2026-10-07 | 1 | `inputs`(ManifestInput[])를 더했다 — 작업 지시 화면(CON-05)이 Bot이 받는 입력을 알 길이 없었다. Studio가 그림에서 모은다. 없으면 빈 목록 (옛 패키지와 호환) | — |
| 2026-10-01 | 1 | 검토 반영: `key_ref` 규칙 하나로(40자), 같은 해시 재업로드 200, R8 서버 작업 검사 | — |
| 2026-10-01 | 1 | 확장 반영: `requires.extensions`, R2를 확장 정의의 `run_locations`로 판정 | 0018 |
| 2026-10-01 | 1 | 확장 검토 반영: `ui_pages` → `resources{type,id}`, `task_types{id, extension, run_locations}`로 R2 판정, 외부 확장 `definition_hash` 고정 | 0018 |

# C15. Center API: 외부 작업 (부르는 쪽 ↔ Center ↔ 일꾼)

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-29) — Center(`api/external_tasks.py`, 15판)와 양쪽이 돈다: 부르는 쪽은 `core.services.CenterServiceCaller`(서버 실행기·실행기 자식·Studio)와 UI 자동화의 `worker/plans.py`·`client/registry_client.py`(`CenterOps`, 토픽 `ui-automation`), 일꾼은 `service_kit.consumer`(서비스 앱·모의 앱)와 어댑터 일꾼 `chk-adapter-consumer`(`apps/adapter_consumer`). `tests/test_center_external_tasks.py`·`test_c15_round_trip.py`·`test_service_kit_consumer.py`·`test_adapter_consumer.py`가 지킨다. 남은 것은 긴 작업(ADR-0102 조각 6)이다 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 서버 실행기·실행기 자식 프로세스·Studio·Worker·Tool UI → Center (올리기·기다리기), 일꾼 → Center (들이기·가져가기·끝내기) |
| 코드 위치 | `packages/contracts/external_task.py`, Center `api/external_tasks.py` |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0062](../decisions/0062-pc-delegation.md), [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md), [0102](../decisions/0102-calling-outside-is-pull.md) |
| 관련 화면 | CON-07 리소스 (일꾼 승인·토픽 상태), CON-01 (실행 상세의 서비스 호출) |

## 목적

BPM 프로세스가 네트워크 건너의 기능을 부를 때, 부르는 쪽이 그 기능의 **주소·키를 모르게** 한다. 부르는 쪽은 Center에 일감을 올리고, 기능 쪽의 일꾼이 가져가 끝낸다. 이 계약이 없으면 Center 콘솔과 현장이 바깥 기능의 주소·키를 들어야 한다 (ADR-0102 배경).

## 이 계약에서 먼저 알아야 할 셋

1. **최소 한 번 실행이다.** 일꾼이 일을 끝냈는데 「끝냈다」가 Center에 닿지 못하면 잠금이 지나 일감이 다시 나간다. **일꾼은 `idempotency`(C11과 같은 여섯 칸)로 스스로 한 번만 수행한다.** 같은 칸으로 다시 오면 저장해 둔 결과를 그대로 끝낸다(`replayed: true`). Center는 이것을 대신 지켜 줄 수 없다 — 바깥에서 일어난 일을 모른다.
2. **아무도 가져가지 않으면 기한에 실패한다** (`no_consumer`). 조용히 쌓아 두지 않는다 — 부르는 쪽 오류 경계가 받는다.
3. **업무 값은 결과를 부른 쪽이 받을 때까지만 있다.** 받으면(`ack`) 입력·출력을 지우고 누가·언제·성패만 남긴다. 못 받은 것은 7일에 지운다 (원칙 6의 예외 — PC 위임 결과와 같은 자리, ADR-0062).

## 전송

| 엔드포인트 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /api/v1/call-tokens` | Bot UI·Studio의 Center API 키 | 호출 토큰 받기 (24시간) |
| `POST /api/v1/external-tasks` | 호출 토큰 · Bot UI·서버 실행기·Studio의 Center API 키 | 일감 올리기 (멱등) |
| `GET /api/v1/external-tasks/{task_id}?wait_s=` | 올린 쪽 | 결과 기다리기 (롱폴링). 아직이면 `wait_s`(최대 25) 뒤 `state: pending` |
| `POST /api/v1/external-tasks/{task_id}/ack` | 올린 쪽 | 결과를 받았다 → 값을 지운다 |
| `POST /api/v1/external-tasks/{task_id}/cancel` | 올린 쪽 | 거두기 (실행이 취소됐다) |
| `POST /api/v1/consumers/enroll` | 없음 (요청 코드) | 일꾼 들이기 요청 — Bot UI 등록과 같은 승인 (ADR-0092 §1) |
| `POST /api/v1/consumers/fetch` | 일꾼 토큰 | 가져가기 (롱폴링, 최대 25초). 하트비트를 겸한다 |
| `POST /api/v1/consumers/tasks/{task_id}/complete` | 잠근 일꾼 | 끝냈다 + 출력 |
| `POST /api/v1/consumers/tasks/{task_id}/fail` | 잠근 일꾼 | 실패 + 사유 |
| `POST /api/v1/consumers/tasks/{task_id}/extend` | 잠근 일꾼 | 잠금 늘리기 |
| `PUT /api/v1/consumers/self/manifest` | 일꾼 토큰 | manifest 올리기 (C11 `ServiceAppManifest` 모양 그대로) |
| `PUT /api/v1/consumers/self/catalogs/{resource_type}` | 일꾼 토큰 | 기여 자원 카탈로그 올리기 (C13 §5 `Catalog`) |

- **연결은 늘 Center 쪽으로 나간다.** Center는 일꾼에게도, 부르는 쪽에게도 먼저 연결하지 않는다.
- 크기 한도: 입력·출력 각 1 MB (C11과 같다).
- 롱폴링 연결 상한: `CHK_CENTER__EXTERNAL_TASKS__MAX_WAITERS` (기본 200, 설정 모델에). 넘으면 503 `too_many_waiters` — 잠깐 쉬고 다시 건다.

## 모델

### 올리기 (`ExternalTaskCreate`)

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `topic` | str | ✓ | 앱 id. BPMN `chk:serviceCall.app_id`, UI 자동화는 `ui-automation` |
| `operation` | str | ✓ | 작업 이름 (manifest의 것) |
| `mode` | `autonomous` \| `deterministic` | ✓ | 수행 모드 (원칙 7). 자율 수행은 Studio에서만 받는다 |
| `idempotency` | object | ✓ | `{run_id, node_id, node_instance, attempt, call_seq}` — C11 멱등 키와 같다(`operation`을 더해 여섯 칸). **같은 칸이면 같은 일감**이다 (다른 본문이면 409 `idempotency_conflict`) |
| `caller` | object | ✓ | C11 `caller`와 같다 (`{type, host, bpm_process_id, version}`) |
| `business_key` | str | | C11과 같다 |
| `input` | object | ✓ | |
| `timeout_s` | int | | 기한. 올린 때부터 센다. 없으면 manifest의 작업 `timeout_s` (기본 60) |
| `want_result` | bool | | 기본 `true`. `false`면 결과를 기다리지 않는다(UI 보고처럼) — Center는 끝나면 값을 바로 지운다 |
| `origin` | `run` \| `test` | | 기본 `run`. Studio 시험 실행은 `test` — 일꾼이 시험 쪽으로 보낼지를 정한다 (ADR-0102 §6) |

응답 `{task_id, state}`. `task_id`는 멱등 칸에서 **Center가 짓는다**(같은 칸이면 같은 id) — 되살린 실행이 다시 올려도 같은 일감이다. **이미 받아 간(`ack`) 일감을 같은 본문으로 다시 올리면 다시 줄에 선다** — 값은 지웠으므로 옛 일감을 돌려주면 빈 결과가 된다. 일꾼이 멱등 칸으로 저장해 둔 결과를 다시 준다(반복 안의 UI 태스크가 차례마다 같은 칸으로 계획을 올린다 — 엔진은 반복 중에 `node_instance`를 올리지 않는다, ADR-0082).

Center가 받기 전에 보는 것 (「불러도 되나」, ADR-0102 §5):

| 검사 | 거절 |
| --- | --- |
| `run_id`가 이 호출자의 실행인가 (C3 소유. Studio는 `test_…`만) | 403 `run_not_owned` |
| 그 실행의 Bot이 이 토픽을 요구하는가 (배포된 C1) — **등록 세션은 예외**: Bot UI 쪽의 `run_id`가 `reg_…`(Tool UI 셀렉터 등록·그 시험)이면 Bot이 없으므로 이 검사 대신 **그 PC에 「셀렉터 등록」(CON-03)이 켜졌는가**를 본다 | 403 `topic_not_required` / `registration_off` |
| 이 토픽에 들인 일꾼의 manifest가 이 작업·모드를 받는가 | 422 `operation_not_found` / `mode_unsupported` |
| 작업이 `required_scopes`를 적었으면 그 호스트에 켜졌는가 (예: `registry_write` = CON-03 「셀렉터 등록」) | 403 `scope_missing` |
| 자율 수행인데 Studio가 아니다 | 403 `mode_not_allowed` |

### 결과 (`ExternalTaskResult`)

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `task_id` | str | |
| `state` | 아래 표 | |
| `output` | object | `completed`일 때만 |
| `mode_used` | str | C11과 같다 |
| `replayed` | bool | 일꾼이 저장해 둔 결과를 돌려줬다 |
| `usage` | object | C11·C3 `llm_usage`와 같다 |
| `error` | object | `failed`일 때 `{code, message, retryable, detail?}` — `detail`은 C11 오류의 `detail` 그대로다(예: C9 `has_links`의 끊길 경로). 업무 값을 넣지 않는다 |
| `deliveries` | int | 몇 번 나갔나 (잠금이 지나 다시 나가면 +1) |

| `state` | 뜻 | 부르는 쪽 |
| --- | --- | --- |
| `pending` | 아직 아무도 가져가지 않았다 | 다시 기다린다 |
| `locked` | 일꾼이 가져갔다 | 다시 기다린다 |
| `completed` | 끝났다 | 출력을 변수에 담고 `ack` |
| `failed` | 일꾼이 실패라고 했다 | `retryable`이면 C14 `retry`대로 `attempt`를 올려 **새 일감**, 아니면 업무 실패(`TaskFailed`, 오류 경계) |
| `expired` | 기한이 지났다 — `error.code`가 `no_consumer`(아무도 안 가져갔다) 또는 `timeout`(가져갔는데 안 끝났다) | 업무 실패 |
| `cancelled` | 올린 쪽이 거뒀다 | — |

C11 오류는 `error.code`로 그대로 온다. C14 `retry.on`의 HTTP 숫자는 이렇게 읽는다: 503 → `dependency_down`, 429 → `rate_limited`. 이 둘과 `timeout`만 `retryable: true`일 수 있다.

### 가져가기 (`FetchRequest` → `FetchResponse`)

요청 `{topics: [str], max_tasks: int, wait_s: int, lock_s: int}`. 일꾼은 **들일 때 승인받은 토픽만** 적을 수 있다(밖이면 403 `topic_not_granted`).

응답 `{tasks: [LockedTask], rotated_token?: str}`. 일감이 없으면 `wait_s`까지 물고 있다가 빈 목록을 준다.

`LockedTask`: `task_id`·`topic`·`operation`·`mode`·`origin`·`idempotency`·`caller`·`business_key`·`input`·`lock_until`·`deadline`·`delivery`(몇 번째로 나가는가, 1부터).

- 한 일감은 한 번에 **한 일꾼**에게만 잠긴다. 잠금 시간은 `lock_s`(기본 = 작업 `timeout_s`)이고 `deadline`을 넘지 않는다.
- 잠금이 지나면 일감은 `pending`으로 돌아가 다른 일꾼(또는 같은 일꾼)에게 다시 나간다.
- 가져가기가 **하트비트를 겸한다** — Center는 토픽마다 「마지막으로 가져간 때」와 일꾼 수를 보이고, 일꾼 토큰 만료 14일 전부터 `rotated_token`으로 갈아 준다(C4 키 회전과 같은 규칙).

### 끝내기

- `complete` `{output, mode_used, replayed, usage}` · `fail` `{code, message, retryable, detail?}` · `extend` `{lock_s}`.
- **먼저 끝낸 쪽이 이긴다.** 잠금이 지난 일꾼의 `complete`도 그 일감이 아직 끝나지 않았으면 받는다(값을 잃지 않으려고). 이미 끝났으면 409 `already_completed` — 일꾼은 버리면 된다(멱등이라 같은 일이다).
- 잠근 일꾼이 아니면 403 `not_locked_by_you`. 거둔 일감이면 409 `cancelled` — 일꾼은 하던 일을 멈춰도 된다.
- 일꾼이 쥔 일감이 오래 걸리면 `extend`로 늘린다 — `service_kit`은 잠금의 절반이 지날 때마다 늘린다.
- `output`에 manifest `output_schema.required`의 칸이 빠졌으면 Center가 422 `output_invalid`로 막는다 — 일꾼의 버그를 부르는 쪽의 업무 실패로 넘기지 않는다.

### 일꾼 들이기

`POST /api/v1/consumers/enroll` `{machine_id, name, os, versions, public_key, topics: [str], manifests: [ServiceAppManifest]}` — 일꾼 하나가 **토픽 여럿**을 맡을 수 있다(모의 앱 열셋, 어댑터 일꾼이 외부 확장 여럿을 맡는 것). manifest는 토픽마다 하나(`app_id` = 토픽)이고 외부 확장 토픽은 비워도 된다(작업 목록은 등록된 정의에서 온다). 관리자가 CON-07 「일꾼 승인 대기」에서 같은 요청 코드를 승인하면 일꾼 토큰을 그 공개키로 봉해 내려 준다(봉함·요청 코드는 `contracts.enrollment` 한 자리 — ADR-0092). 토픽은 **승인할 때** 정해진다(일꾼이 적은 것을 관리자가 줄일 수 있다). 외부 확장 토픽은 그 정의가 Center에 등록되어 있어야 한다(E6).

### manifest·카탈로그 올리기

- `PUT /api/v1/consumers/self/manifest` — 본문은 ServiceAppManifest 하나. 그 `app_id`가 승인된 토픽 밖이면 403 `topic_not_granted`. 같은 `app_id`의 것을 바꾼다. 판이 바뀌면 일꾼이 뜰 때 다시 올린다.
- `PUT /api/v1/consumers/self/catalogs/{resource_type}` `{app_id, catalog}` — C13 §5 `Catalog`. Center는 `revision`이 같으면 다시 쓰지 않는다(C7). 승인된 토픽의 것만 받는다. 이 카탈로그가 C7 기여 자원·Studio STU-13의 고를 거리가 된다 — **Center도 Studio도 앱의 주소를 모른다.**

## 부르는 쪽의 규칙

- **엔진은 모른다.** `ServiceCaller` 자리에 「Center에 올리고 기다리는」 구현이 들어갈 뿐이다. 기다리는 동안 부르는 쪽은 결과 기다리기를 되풀이한다. 서버 실행기가 기다리는 동안 스레드를 놓는 것은 아직이다 (ADR-0102 조각 6).
- **멱등 칸은 C11과 같은 규칙으로 짓는다** — 재시작 뒤에도 같은 값이 되게 한다(원칙 9). 그래서 되살린 실행은 새 일감이 아니라 **같은 일감의 결과**를 받는다.
- 실행이 취소되면 기다리던 일감을 `cancel`한다.
- 실행 기록(C3 `service_call`)은 지금과 같은 칸이다(업무 값 없음). `key_ref`는 빈 글이다(키가 없다).
- **누가 무엇으로 올리나**: 서버 실행기·Studio는 제 Center API 키, Bot UI의 실행기 자식 프로세스·Worker·Tool UI는 호출 토큰(아래 「정한 것」). Studio가 Worker를 빌려 UI 태스크 편집기를 시험할 때(STU-13)는 Studio가 **제 키로 호출 토큰을 청해** 세션에 넣는다 — 호출 토큰은 청한 키와 같은 신원이다(Studio면 `test_…`만).

## 예시

```json
{
  "schema": 1,
  "topic": "nowview-sc01",
  "operation": "submit_order",
  "mode": "deterministic",
  "idempotency": {"run_id": "run_8f2a", "node_id": "Task_submit", "node_instance": 1, "attempt": 1, "call_seq": 1},
  "caller": {"type": "server_runner", "host": "srv-01", "bpm_process_id": "bx-order", "version": "1.2.0"},
  "input": {"order_id": "PO-101"},
  "timeout_s": 600
}
```

일꾼이 받은 것:

```json
{
  "tasks": [
    {
      "task_id": "xt_3c9e0b7a",
      "topic": "nowview-sc01",
      "operation": "submit_order",
      "mode": "deterministic",
      "origin": "run",
      "idempotency": {"run_id": "run_8f2a", "node_id": "Task_submit", "node_instance": 1, "attempt": 1, "call_seq": 1},
      "caller": {"type": "server_runner", "host": "srv-01", "bpm_process_id": "bx-order", "version": "1.2.0"},
      "input": {"order_id": "PO-101"},
      "lock_until": "2026-10-28T05:10:00Z",
      "deadline": "2026-10-28T05:10:00Z",
      "delivery": 1
    }
  ]
}
```

## 오류

모든 오류 본문은 C11과 같다: `{"code", "message", "detail"}`.

| 상태 코드 | `code` | 언제 |
| --- | --- | --- |
| 401 | `token_missing` / `token_invalid` | 토큰 없음·모름 |
| 403 | `run_not_owned` / `topic_not_required` / `mode_not_allowed` / `scope_missing` | 「불러도 되나」 (위 표) |
| 403 | `topic_not_granted` / `not_locked_by_you` | 일꾼이 제 것이 아닌 것을 만짐 |
| 404 | `task_not_found` | 없는 일감이거나 남의 일감 (둘을 가르지 않는다) |
| 409 | `idempotency_conflict` | 같은 멱등 칸에 다른 본문 |
| 409 | `already_completed` / `cancelled` | 끝내기가 늦었다 |
| 422 | `operation_not_found` / `mode_unsupported` / `output_invalid` | manifest와 다름 |
| 503 | `too_many_waiters` | 롱폴링 상한 |

## 정한 것 (처음에 미정이던 셋)

- **호출 토큰은 Bot UI(또는 Studio)가 제 Center API 키로 청한다** — `POST /api/v1/call-tokens` → `{token, expires_at}`(수명 24시간). 봉하지 않는다: 청하는 길이 이미 그 Bot UI의 키로 인증된 연결이라 다른 응답과 같은 길로 온다(환경변수 키처럼 **공개키가 없는 Bot UI도** 받을 수 있어야 한다 — 하트비트 봉함으로는 그 Bot UI가 못 받는다). Bot UI는 실행을 띄울 때 하나 청해 실행기 자식에게 제어 파일로 넘기고(만료 2시간 전부터 새것을 같은 길로 넣는다), Worker에는 C10 세션으로, Tool UI에는 Bot UI 비밀 저장소의 `call_token`으로 준다. **호출 토큰으로 부르면 Center는 그 Bot UI의 Center API 키로 부른 것과 같이 본다** — 소유(C3)·배포 대조가 같은 신원으로 돈다. 호출 토큰은 `/api/v1/external-tasks`와 **리소스 목록 읽기**(`GET /api/v1/resources…` — 도구·편집기가 C9 카탈로그를 읽는 자리) 밖을 모두 403 `call_token_scope`로 막는다. 서버 실행기·Studio는 제 프로세스 안에서 부르므로 제 Center API 키를 쓴다.
- **롱폴링 상한은 설정의 기본 200** (`CHK_CENTER__EXTERNAL_TASKS__MAX_WAITERS` — 올리는 쪽·일꾼의 기다림을 함께 센다). 한 번 가져가기에 잠글 수 있는 수는 **10건까지**(`max_tasks`가 그보다 크면 10으로 깎는다).
- **어댑터 일꾼은 C13 「전송」의 바깥 앱 명부를 일꾼 토큰으로 받는다** (조각 3) — 승인된 토픽의 외부 확장 정의·봉투만 준다. 받은 쪽은 봉투를 다시 검증한다(E6).
- 출력 검사는 **`output_schema.required`의 칸이 다 있는가**까지다 — 계약 패키지에 JSON Schema 검증기를 두지 않는다(입력 쪽도 그렇다). 더 깊은 모양은 일꾼과 엔진의 `output` 매핑이 본다.

> 제안: CON-07 토픽 상태 — 일꾼 수 · 마지막으로 가져간 때 · 쌓인 일감 · 가장 오래 기다린 일감 (조각 5).

## 호환 규칙

- 받는 쪽은 모르는 필드를 무시한다. `state`·`error.code`는 열린 문자열이다 (원칙 10).
- `schema`가 더 높은 요청은 422 `schema_unsupported`.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-29 | 1 | **구현됨** — 부르는 쪽(서버 실행기·실행기 자식·Studio·Worker·Tool UI)과 일꾼(`service_kit`·어댑터 일꾼)이 붙었다. 옛 Push 길(C11 `/v1/ops`·어댑터 직접 호출·서비스 앱 키 배달)은 걷었다 | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-28 | 1 | 처음 씀 (초안) | [0102](../decisions/0102-calling-outside-is-pull.md) |

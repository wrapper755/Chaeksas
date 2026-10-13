# C12. Center API: 서버 실행기

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-13) — **등록·하트비트는 양쪽이 돌고 시험이 지킨다** (`apps/server_runner` ↔ Center). 남은 것은 메시지 API와 실행(작업·배포를 **받아 두고 돌리지 않는다** — `SERVER_RUNNER_AVAILABLE`이 꺼져 있다) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 서버 실행기 ↔ Center, 외부 시스템 → Center (메시지) |
| 코드 위치 | `packages/contracts/server_runner.py` |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0038](../decisions/0038-approval-request-channel.md), [0054](../decisions/0054-server-run-state-and-concurrency.md) |
| 관련 화면 | CON-12 서버 실행, CON-05, CON-04, CON-11 |

## 목적

서버 실행기가 C4와 같은 틀로 Center에 등록하고 하트비트를 보낸다. 서버 Bot을 **여러 건 동시에** 실행하고, 결재·메시지를 기다리는 실행은 상태를 저장한 채 쉬게 한다 (ADR-0015).

**C4(Bot UI)와 다른 점:**

| | C4 Bot UI | C12 서버 실행기 |
| --- | --- | --- |
| 동시 실행 | 1건 | 상한까지 여러 건 |
| 대기열 | Bot UI가 가짐 | **Center가 가짐.** 실행기는 빈자리만큼만 받는다 |
| 기다리는 실행 | 실행 자리를 쥠 | 상태 저장, 상한에 세지 않음 (`waiting[]`) |
| 결재 창구 | 현장 창 또는 Center | Center만 |
| 메시지 시작·이어 가기 | Bot UI 메시지 수신(8790) | Center 메시지 API → 하트비트 응답 |

## 전송

- 경로:
  - `POST /api/v1/server-runner/register`
  - `POST /api/v1/server-runner/heartbeat` — 기본 10초 (응답의 `next_heartbeat_s`를 따른다)
- 인증: Center API 키 (종류 「서버 실행기용」, CON-11). 다른 종류의 키는 403 `wrong_key_type`.
- 키 묶기는 C4와 같다 — 키 하나 ↔ 서버 하나 ↔ 실행기 행 하나이고, 같은 `machine_id`를 다른 키가 등록하면 409 `machine_already_registered`다 (C4 「키 묶기」). **규칙은 코드로도 한 자리다** (`center/host_keys.py`) — C4와 C12가 같은 함수를 쓴다. `machine_id`를 만드는 쪽도 하나다 (`core.machine`).
- 등록은 **멱등**이고, 등록·하트비트가 오면 운영자가 해 둔 「유실 처리」를 지운다 — 돌아온 실행기를 오프라인으로 보이게 두지 않는다 (CON-12).
- 이벤트(C3)와 결재(C6)는 Bot UI와 같은 API를 쓴다.

**지금 도는 것**: 등록·하트비트·운영 API 셋과, 하트비트 응답의 `deployments`·`jobs`·
`cancel_jobs`·`approvals`·`paused`·`key_expires_at`. 실행기는 **지시를 받아 두고 돌리지
않는다** (M7 기준 둘째) — 그래서 `started` ack를 보내지 않고 `capacity.running`은 0이다.
`messages[]`는 늘 비어 있다 (메시지 API가 아직 없다). 서버 대상 작업·배포를 **만들 수** 없게
막는 스위치(`SERVER_RUNNER_AVAILABLE`)는 그대로 꺼져 있다 — 켜는 것은 실행이 붙는 조각이다.

**운영 API (콘솔 CON-12, 관리자 토큰):**

| 경로 | 뜻 |
| --- | --- |
| `GET /api/v1/server-runners` | 목록 (상태·용량·실행 중·기다리는 실행·대기열) |
| `POST /api/v1/server-runners/{id}/pause` / `resume` | 일시 중지·다시 시작. 다음 하트비트 응답의 `paused`로 전달된다 |
| `POST /api/v1/server-runners/{id}/mark-lost` | 유실 처리. 오프라인인 실행기만 (온라인이면 409 `runner_online`). 그 실행기의 실행을 `failed`(`runner_lost`)로 닫고 결재를 회수한다 (C6 `host_lost`) |

## 모델

### RegisterRequest

`{schema, machine_id, name, os, versions{core, server_runner}, max_concurrency, extensions: [{id, version, definition_hash, enabled}]}`.

`max_concurrency`는 설정값 `CHK_SERVER_RUNNER__MAX_CONCURRENCY`이고 기본 10이다.

→ `{server_runner_id: "srv_<hex8>", admin_keys, heartbeat_interval_s: 10, server_time}`

### HeartbeatRequest

| 필드 | 뜻 |
| --- | --- |
| `schema`, `status` | `status`는 열린 문자열. 알려진 값: `running`, `paused`, `draining`, `error` |
| `capacity` | `{max, running}`. `running`은 기다리는 실행을 뺀 수 |
| `running[]` | `{run_id, bpm_process_id, version, node_id, started_at, job_id?}` |
| `waiting[]` | `{run_id, bpm_process_id, version, waiting_for: "approval" \| "message" \| "timer", request_id?, message_name?, correlation?, until?, since}` |
| `job_acks[]` | C4와 같은 모양. `result`: `started`, `rejected`, `expired`, `cancelled`, `cancel_refused` |
| `approval_acks[]`, `deployment_results[]` | C4와 같다 |
| `readiness[]` | 배포된 서버 Bot별 준비 상태 (C4 Readiness와 같은 모양: 빠진 키 참조·확장). 바뀌었을 때만 |
| `message_acks[]` | `{message_id, accepted, run_id?, reason?}` |
| `extensions[]` | 바뀌었을 때만 (C4와 같은 모양) |
| `restored[]` | 재시작 직후 저장소에서 되살려 **정말 이어 가는** 실행 `run_id` (첫 하트비트에만). 되살리지 못한 것은 여기 넣지 않고 C5 `run_status`에 사유와 함께 적는다 |
| `unsent_events` | |

**`waiting[]`의 짝 칸은 비울 수 없다** — `approval`이면 `request_id`, `message`면
`message_name`, `timer`면 `until`이다. 같은 실행이 `running[]`과 `waiting[]`에 함께 있을 수도
없다(쥐면서 놓을 수는 없다 — 자리 셈이 틀어진다). `capacity.running`은 `running[]`의 길이와
같아야 한다. 보내는 쪽과 받는 쪽이 **같은 함수**로 본다 (`validate_heartbeat()`).

### HeartbeatResponse

| 필드 | 뜻 |
| --- | --- |
| `server_time`, `next_heartbeat_s` | |
| `deployments[]` | `target.type=server_runner`이고 `id`가 이 실행기 또는 `"*"`인 활성 배포 봉투 (C2) |
| `admin_keys` | 바뀌었을 때만 |
| `jobs[]` | **빈자리만큼만** 싣는다. C4 JobDispatch와 같은 모양 |
| `cancel_jobs[]` | |
| `approvals[]` | 답이 정해진 결재. 기다리던 실행이 이어 간다 |
| `messages[]` | `{message_id, name, correlation?, payload, received_at}` — 기다리는 실행을 깨우거나 메시지 시작 이벤트로 새 실행을 만든다 |
| `paused` | true면 새 작업을 받지 않는다 (CON-12 「일시 중지」). 실행 중인 것은 끝까지 간다 |

### Center가 작업을 나누는 규칙

1. 서버 대상 작업(`target.type=server_runner`)은 Center 대기열(`queued`)에 쌓인다. 순서는 들어온 순서다.
2. 하트비트마다 Center는 실행기의 빈자리를 계산한다: `capacity.max - capacity.running`, `paused`면 0.
3. 대기열 앞에서부터 실어 보내되, **BPM 프로세스별 상한**(배포의 `max_concurrency`, 기본 5)을 넘는 작업은 건너뛰고 다음 것을 본다. 건너뛴 작업의 `state_reason`은 `per_bot_limit`으로 표시한다 (CON-12 「대기 이유」).
4. 실행기가 여럿이면 빈자리가 많은 쪽부터 준다. **한 실행은 시작한 실행기에 끝까지 머문다** (상태가 그 실행기 저장소에 있으므로).

빈자리는 `free_slots()`가, 고르는 것은 `pick_jobs()`가 센다 — **건너뛰고 다음 것을 본다**
(막아 세우면 상한에 걸린 Bot 하나가 대기열 전체를 멈춘다). CON-12의 「대기 이유」에서
**`per_bot_limit`만 사유가 붙고**, 사유 없이 남은 작업은 「전체 상한」이다 (빈자리가 없어
아직 보지 않은 것이다 — 나중에 빈자리가 생기면 순서대로 간다).

### 메시지 (외부 시스템 → Center)

`POST /api/v1/messages`, 연동용 키 또는 관리자 토큰으로 부른다.

| 필드 | 뜻 |
| --- | --- |
| `name` | 메시지 이름. C1 `triggers[].name` 또는 ReceiveTask의 메시지 이름 |
| `correlation` | 기다리는 실행을 찾는 키 (예: 주문 번호). 없으면 메시지 시작만 |
| `payload` | object |
| `idempotency_key` | C5와 같은 규칙 |

Center는 메시지를 이렇게 처리한다.

- `correlation`이 맞는 `waiting` 실행이 있으면 그 실행기에게 전달한다.
- 없고, `name`이 어떤 서버 Bot의 메시지 시작 트리거면 새 작업을 만든다.
- 둘 다 아니면 422 `no_receiver`.
- 응답: `{message_id, delivered_to: "run" | "new_job", run_id?, job_id?}`.

### 재시작과 유실

세부는 [ADR-0054](../decisions/0054-server-run-state-and-concurrency.md)가 정했다. 계약이 보는 것만 여기 적는다.

- 서버 실행기는 기다리는 실행의 상태를 **자기 저장소(SQLite)에 JSON 한 덩이로** 둔다.
  **적는 때는 둘**(실행을 시작할 때·멈출 때)이고 **끝나면 지운다** — 시작할 때 적지 않으면
  다시 뜬 실행기가 죽은 실행을 알지 못해 작업이 `accepted`로 영원히 남는다.
- **그림은 담지 않는다** — 설치된 패키지에서 다시 읽는다. 담은 `bpm_process_id`·`version`과
  다르면 **되살리지 않는다**(`runner_version_changed`). 실행 기록도 담지 않는다 — 파일이
  원본이다 (C3).
- 되살리면 **마지막 기다림 이후를 다시 한다.** 서비스 앱 호출은 C11 멱등 키로 한 번만
  반영되고, **`node_instance`·`call_seq`가 상태와 함께 되돌아가 키가 같은 값으로 다시
  만들어지므로** 호출 전에 따로 적어 둘 것이 없다.
- **기다린 적이 없는 실행은 되살리지 않는다** — `runner_restarted`로 닫는다. 보내기(메일·웹훅)는
  멱등이 아니라 처음부터 다시 돌리면 두 번 보낸다. 다시 돌릴지는 **운영자가** 작업을 다시 내 정한다.
  판정은 `restorable()`이 한다 (실행기와 Center가 같은 말을 쓴다).
- **기한은 Center가 꺼져 있어도 간다.** 경계 타이머는 실행기의 로컬 시계로 재므로, 결재가
  Center 결재함에 `open`으로 떠 있는 동안에도 마감이 지나면 실행기가 혼자 닫는다
  (기한은 업무 규칙이지 전송 규칙이 아니다). 그때 갈 곳 없이 남은 결재는 C6의 `run_ended`
  자동 회수가 받는다.
- **맞추기 규칙은 C4와 같고 사유만 다르다** — 두 주기 연속 `running[]`·`waiting[]`에 보이지
  않고 ack도 없는 작업은 `rejected`이고, 그 `state_reason`은 **`runner_lost`**다 (C4의
  `bot_ui_lost`가 아니다 — 뭉개면 CON-12가 서버에 「bot_ui_lost」라고 적는다). 그 실행의
  결재는 회수된다 (C6 `host_lost`).
- 하트비트가 3분 동안 없으면 Center는 그 실행기를 「오프라인」으로 표시한다. 실행은 유실로 보지 않고 기다린다. 운영자가 CON-12에서 「유실 처리」를 하면 그때 그 실행기의 실행을 `failed`(`runner_lost`)로 닫고, 결재를 회수한다 (C6 `host_lost`).

## 예시

```json
{
  "schema": 1, "status": "running",
  "capacity": {"max": 10, "running": 1},
  "running": [{"run_id": "run_20261001_110000_aa11bb", "bpm_process_id": "finance.invoice-issue", "version": "1.0.0", "node_id": "Task_issue", "started_at": "2026-10-01T11:00:00+09:00", "job_id": "job_1c2d3e4f"}],
  "waiting": [{"run_id": "run_20261001_103000_d4e5f6", "bpm_process_id": "finance.invoice-issue", "version": "1.0.0", "waiting_for": "approval", "request_id": "apr_run_20261001_103000_d4e5f6_Task_approve_1", "since": "2026-10-01T10:31:10+09:00"}],
  "job_acks": [{"job_id": "job_1c2d3e4f", "result": "started", "run_id": "run_20261001_110000_aa11bb"}]
}
```

## 오류

C4와 같다 (401, 403 `key_revoked`·`wrong_key_type`, 409 `machine_mismatch`·`machine_already_registered`·`not_registered`, 422, 5xx). 메시지 API에는 다음이 더 있다.

- 422 `no_receiver`
- 409 `idempotency_conflict`

되살리지 못한 실행의 사유는 오류가 아니라 **C5 `run_status`의 `error_code`**로 간다 —
`runner_restarted`·`runner_version_changed`·`snapshot_unreadable` (ADR-0054).

## 호환 규칙

- C4와 같다. 모든 값 목록은 열린 문자열이다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (M7) | 0015, 0016 |
| 2026-10-01 | 1 | 화면 검토 반영: 운영 API(목록·일시 중지·유실 처리), `readiness` | — |
| 2026-10-13 | 1 | 스파이크 s10 뒤 **합의**로 올림. 모델·검사가 코드로 생겼다(`validate_heartbeat`·`free_slots`·`pick_jobs`·`restorable`). §재시작과 유실을 다시 썼다 — 적는 때 둘·그림은 담지 않음·마지막 기다림 이후를 다시 함(멱등 키가 같은 값으로 다시 만들어지므로 호출 전 저장이 필요 없다)·기다린 적 없는 실행은 되살리지 않음·**기한은 Center가 꺼져 있어도 간다** | 0054 |
| 2026-10-13 | 1 | **등록·하트비트가 양쪽에서 돈다** — `apps/server_runner`(등록·하트비트·SIGTERM)와 Center(`api/server_runner.py` + 운영 API 셋). 키 묶기 규칙을 C4와 **한 코드로** 모았고(`center/host_keys.py`), `machine_id`도 한 자리다(`core.machine`). 작업 나누기(`free_slots`·`pick_jobs`)가 붙었고 **`waiting[]`의 작업은 `run_id`로 되짚는다**(그 칸에 `job_id`가 없다 — 안 되짚으면 결재를 기다리는 실행을 `runner_lost`로 닫는다). 남은 것은 메시지 API와 실행이다 | 0054 |

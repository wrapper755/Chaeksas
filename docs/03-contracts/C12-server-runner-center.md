# C12. Center API: 서버 실행기

| 항목 | 값 |
| --- | --- |
| 상태 | 초안 (2026-10-01) — **M7에서 구현.** 서버 실행 세부 구현은 M7 스파이크 뒤 ADR로 확정 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 서버 실행기 ↔ Center, 외부 시스템 → Center (메시지) |
| 코드 위치 | `packages/contracts/server_runner.py` |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md) |
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
- 키는 처음 등록한 서버(`machine_id`)에 묶인다 (C4와 같다).
- 이벤트(C3)와 결재(C6)는 Bot UI와 같은 API를 쓴다.

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
| `restored[]` | 재시작 직후 저장소에서 되살린 실행 `run_id` (첫 하트비트에만) |
| `unsent_events` | |

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

- 서버 실행기는 기다리는 실행의 상태를 자기 저장소(SQLite로 시작)에 둔다. 다시 뜨면 `restored[]`로 알리고 이어 간다.
- 실행 중이던 태스크는 처음부터 다시 한다. 서비스 앱 호출은 C11 멱등 키로 한 번만 반영된다. `node_instance`와 `attempt`는 호출 전에 저장해 둔다.
- 하트비트가 3분 동안 없으면 Center는 그 실행기를 「오프라인」으로 표시한다. 실행은 유실로 보지 않고 기다린다. 운영자가 CON-12에서 「유실 처리」를 하면 그때 그 실행기의 실행을 `failed`(`runner_lost`)로 닫고, 결재를 회수한다 (C6 `host_lost`).

## 예시

```json
{
  "schema": 1, "status": "running",
  "capacity": {"max": 10, "running": 3},
  "running": [{"run_id": "run_20261001_110000_aa11bb", "bpm_process_id": "finance.invoice-issue", "version": "1.0.0", "node_id": "Task_issue", "started_at": "2026-10-01T11:00:00+09:00", "job_id": "job_1c2d3e4f"}],
  "waiting": [{"run_id": "run_20261001_103000_d4e5f6", "bpm_process_id": "finance.invoice-issue", "version": "1.0.0", "waiting_for": "approval", "request_id": "apr_run_20261001_103000_d4e5f6_Task_approve_1", "since": "2026-10-01T10:31:10+09:00"}],
  "job_acks": [{"job_id": "job_1c2d3e4f", "result": "started", "run_id": "run_20261001_110000_aa11bb"}]
}
```

## 오류

C4와 같다 (401, 403 `key_revoked`·`wrong_key_type`, 409 `key_bound_elsewhere`, 422, 5xx). 메시지 API에는 다음이 더 있다.

- 422 `no_receiver`
- 409 `idempotency_conflict`

## 호환 규칙

- C4와 같다. 모든 값 목록은 열린 문자열이다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (M7) | 0015, 0016 |
| 2026-10-01 | 1 | 화면 검토 반영: 운영 API(목록·일시 중지·유실 처리), `readiness` | — |

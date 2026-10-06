# C4. Center API: Bot UI 등록·하트비트

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Bot UI ↔ Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/bot_ui.py` (import `chaeksas.contracts.bot_ui`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c4-register-request.json`](../../packages/contracts/schemas/c4-register-request.json) · [`c4-register-response.json`](../../packages/contracts/schemas/c4-register-response.json) · [`c4-heartbeat-request.json`](../../packages/contracts/schemas/c4-heartbeat-request.json) · [`c4-heartbeat-response.json`](../../packages/contracts/schemas/c4-heartbeat-response.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0012](../decisions/0012-bot-ui.md), [0013](../decisions/0013-api-keys.md), [0014](../decisions/0014-one-bot-per-pc.md) |
| 관련 화면 | BUI-01·03·04·09, CON-03·05·11 |

## 목적

Bot UI가 Center API 키로 자기를 등록하고, 30초마다 상태(실행 중 Bot 1건, 대기열, Worker 프로세스, 준비 상태)를 보고하며, 그 응답으로 배포·작업·결재 답·취소 지시를 받는다. **연결은 항상 Bot UI → Center**다 (ADR-0007).

## 전송

- 방식:
  - `POST /api/v1/bot-ui/register` — 처음 한 번, 그리고 정보(이름·버전)가 바뀔 때.
  - `POST /api/v1/bot-ui/heartbeat` — 30초마다 (응답의 `next_heartbeat_s`를 따름).
- 인증: `Authorization: Bearer <Center API 키>` (종류 「Bot UI용」, CON-11). **Bot UI의 신원은 키로 정한다.** 경로·본문에 `bot_ui_id`를 넣지 않는다.
- 키 묶기: 키는 처음 `register`한 PC(`machine_id`)에 묶인다. 다른 `machine_id`로 같은 키를 쓰면 409. PC를 다시 설치해 `machine_id`가 바뀌면 운영자가 CON-11에서 「PC 묶음 풀기」를 한다.
- 키 종류: 「Bot UI용」 키만 받는다. Studio용·서버 실행기용 키로 부르면 403 `wrong_key_type`.
- 키 형식: `chk_ctr_<무작위 40자>`, 앞자리 16자만 화면에 (C11과 같은 규칙).
- 멱등성: `register`는 같은 키·같은 `machine_id`면 같은 `bot_ui_id`를 돌려준다 (정보만 갱신). `heartbeat`는 매번 상태를 덮어쓴다. `job_acks`·`approval_acks`는 같은 것을 다시 보내도 한 번만 반영한다.
- 크기 한도: 요청 256 KB.
- **`current_run`은 비어 있어도 `null`로 싣는다.** 「필수이지만 비어 있을 수 있는」 필드라서, `None`인 선택 필드처럼 빼 버리면 받는 쪽이 「필수 필드 누락」으로 422를 돌려준다 (`ContractModel.to_json_dict()`가 필수 필드의 `null`은 남긴다).
- 온라인 판정: 마지막 하트비트가 90초 이내면 「● 온라인」 (CON-03).

## 모델

### RegisterRequest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `machine_id` | str | ✓ | PC 고유값의 SHA-256 (Windows MachineGuid / Linux `/etc/machine-id`). 원값은 보내지 않는다 |
| `name` | str | ✓ | 표시 이름 (기본: PC 이름) |
| `os` | str | ✓ | 예: `windows-11-23H2`, `ubuntu-24.04` |
| `versions` | object | ✓ | `{bot_ui, core, worker}` |
| `runtimes` | object | | `{browsers: ["chromium-130"], desktop_backend: "uia", extensions: [{id, version, enabled}]}` — 설치된 확장 (C13) |

### RegisterResponse

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `bot_ui_id` | str | `bui_<hex8>` |
| `admin_keys` | AdminKey[] | 배포 서명 검증용 Admin 공개키 (C2). 철회된 키도 `revoked_at`과 함께 |
| `heartbeat_interval_s` | int | 기본 30 |
| `server_time` | str | 시계 차이 확인용 |

### HeartbeatRequest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `status` | str | ✓ | **열린 문자열.** 알려진 값: `idle` `running` `waiting_approval` `waiting_confirmation` `selector_registration` `error` |
| `versions` | object | | 바뀌었을 때만 |
| `current_run` | CurrentRun \| null | ✓ | 실행 자리. **최대 1건** (ADR-0014) |
| `queue` | Queue | ✓ | 대기열 |
| `worker` | WorkerState | ✓ | Worker 프로세스 상태 |
| `readiness` | Readiness[] | | 설치된 Bot별 준비 상태 (바뀌었을 때만 보내도 됨) |
| `job_acks` | JobAck[] | | 이번 주기에 처리한 작업 |
| `deployment_results` | DeploymentResult[] | | 배포 적용 결정 (CON-03 「최근 배치 결정」) |
| `extensions` | `{id, version, definition_hash, enabled}`[] | | 설치된 확장. 바뀌었을 때만 (C13) |
| `approval_acks` | ApprovalAck[] | | 받아 간 결재 답 |
| `unsent_events` | int | | 아직 못 보낸 실행 이벤트 줄 수 (C3) |

| 모델 | 필드 |
| --- | --- |
| CurrentRun | `run_id`, `bpm_process_id`, `version`, `node_id`, `state`(열린 문자열: `running` `waiting_approval` `waiting_confirmation`), `started_at`, `source`(`job`\|`manual`\|`watch`\|`schedule`\|`message`, 예약: `delegation`), `job_id`? |
| Queue | `max`(int), `items`: `{queue_id, source, bpm_process_id, version?, job_id?, requested_at, expires_at?}`[] (순서대로) |
| WorkerState | `state`(`running`\|`off`(필요할 때 시작, 아직 안 띄움)\|`restarting`\|`stopped`), `reserved_for`?(C10 예약 `run_id`), `version`, `restarts`(연속 재시작 횟수), `session`(`idle`\|`bot`\|`studio`\|`selector_registration`) |
| Readiness | `bpm_process_id`, `version`, `ready`(bool), `missing_key_refs`(str[]), `blocked`(str[] — 사전 점검 막힘 코드) |
| JobAck | `job_id`, `result`(`queued`\|`started`\|`rejected`\|`expired`\|`cancelled`\|`cancel_refused`), `position`?(queued일 때 대기열 순번), `run_id`?(started일 때), `reason`?(rejected일 때: `queue_full` `no_deployment` `not_ready` `bot_ui_shutdown` `server_location` `cancelled_on_pc`(현장에서 대기열 항목을 취소함); `cancel_refused`일 때: `already_started`) |
| ApprovalAck | `request_id`, `accepted`(bool), `reason`? |
| DeploymentResult | `deployment_id`, `bpm_process_id`, `version`, `result`(`applied`\|`rejected`), `reason`?, `at` |

> 모든 값 목록(`status`, `state`, `source`, `result`, `reason`, `session` 등)은 **열린 문자열**이다. 위의 값은 알려진 값일 뿐이다 (README 원칙 10).

### HeartbeatResponse

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `server_time` | str | |
| `next_heartbeat_s` | int | 다음 하트비트까지 (기본 30, Center가 부하에 따라 늘릴 수 있음) |
| `deployments` | Envelope[] | 이 Bot UI의 **활성 배포 봉투 전체**를 저장된 JSON 그대로 (재직렬화하면 서명이 깨진다). Bot UI는 목록과 설치 상태를 맞춘다 |
| `admin_keys` | AdminKey[] | 바뀌었을 때만 (생략 = 그대로) |
| `jobs` | JobDispatch[] | 아직 ack되지 않은 작업. **ack가 올 때까지 매번 실린다** |
| `cancel_jobs` | str[] | 콘솔에서 취소된 작업 id. 대기열에 있으면 빼고 `cancelled`로 ack. **이미 시작했으면 멈추지 않고** `cancel_refused` + `already_started`로 ack. 작업은 Center에서 `accepted` 그대로 남는다 (C5, 실행 중 Bot을 멈추는 것은 schema 1 범위 밖) |
| `approvals` | ApprovalDispatch[] | 답이 정해졌고 아직 ack되지 않은 결재 (C6) |
| `disabled` | bool | true면 Bot UI는 새 작업·배포를 받지 않는다. 하트비트는 계속 받으므로 실행 중 Bot과 대기열은 콘솔에 계속 보인다 (CON-03 「비활성화」) |

| 모델 | 필드 |
| --- | --- |
| JobDispatch | `job_id`, `bpm_process_id`, `version`?(없으면 배포된 버전), `inputs`(object), `requested_by`(사람, 예약: `server_bot:<run_id>` — PC 위임), `requested_at`, `expires_at`?, `note` |
| ApprovalDispatch | `request_id`, `state`(`answered`\|`expired`\|`withdrawn`, C6), `answer`, `answered_by`, `answered_at` |

### 작업 상태 흐름 (Center 쪽, CON-05)

```
pending ──(하트비트 응답에 실림)──▶ dispatched ──ack queued──▶ queued ──ack started──▶ accepted(run_id)
   │                                   │                        │
   └─ 콘솔 취소 ─▶ cancelled             ├─ ack rejected ─▶ rejected(reason)
                                       └─ ack expired / 만료 ─▶ expired
```

- `queued` = 화면 표기 「대기열」. Bot UI 대기열에 들어갔다는 뜻.
- 실행 자리가 비어 있으면 Bot UI는 `queued`를 건너뛰고 바로 `started`를 보내도 된다.
- 대기열이 가득 차면 `rejected` + `queue_full` (ADR-0014).
- `run_location=server`인 BPM 프로세스의 작업이 Bot UI에 오면 `rejected` + `server_location` (Center 버그 방어).

### 작업이 사라지지 않게 (맞추기 규칙)

- **Bot UI:** 받은 `job_id`와 아직 Center가 확인하지 않은 ack를 디스크에 저장한다. 이미 받은(대기열에 있거나, 실행했거나, 실행 중인) `job_id`가 다시 오면 무시하고 마지막 ack를 다시 보낸다. 대기열 자체도 디스크에 저장해, Bot UI를 다시 켜면 이어 간다.
- **Center:** 받은 `deployment_results`를 **쌓아 둔다** (CON-03 「최근 배치 결정」, C5 `BotUiInfo.deployment_results`). 하트비트 한 주기만 올라오는 값이라 흘려보내면 「왜 설치가 안 됐나」가 영영 남지 않는다. 같은 `(deployment_id, at)`은 **한 번만** 반영한다 (Bot UI가 다시 보내도 쌓이지 않게).
- **Center:** 하트비트마다 자기 기록의 `queued`·`accepted`(실행 중) 작업을 `queue.items`·`current_run`과 비교한다. 두 번 연속 하트비트에서 보이지 않고 ack도 없으면 `rejected` + `bot_ui_lost`로 바꾼다 (Bot UI가 비정상 종료로 대기열을 잃은 경우). 실행 결과는 C3 `run_finished`로 따로 확정된다.

## 예시

하트비트 요청:

```json
{
  "schema": 1,
  "status": "running",
  "current_run": {"run_id": "run_20261001_101500_a1b2c3", "bpm_process_id": "erp.order-entry",
                  "version": "2.1.0", "node_id": "Task_fill_order", "state": "running",
                  "started_at": "2026-10-01T10:15:00+09:00", "source": "job", "job_id": "job_8f3e"},
  "queue": {"max": 20, "items": [
    {"queue_id": "q_01", "source": "job", "bpm_process_id": "erp.order-entry", "job_id": "job_9a10",
     "requested_at": "2026-10-01T10:16:05+09:00", "expires_at": "2026-10-01T18:00:00+09:00"}]},
  "worker": {"state": "running", "version": "0.3.0", "restarts": 0, "session": "bot"},
  "readiness": [{"bpm_process_id": "erp.order-entry", "version": "2.1.0", "ready": true,
                 "missing_key_refs": [], "blocked": []}],
  "job_acks": [{"job_id": "job_9a10", "result": "queued", "position": 1}],
  "unsent_events": 0
}
```

응답:

```json
{
  "server_time": "2026-10-01T10:16:30+09:00",
  "next_heartbeat_s": 30,
  "deployments": [{"schema": 1, "payload": {"kind": "deployment", "deployment_id": "dep_3f9a1c07", "…": "…"}, "key_id": "7c1e0b9f4a2d6e83", "alg": "ed25519", "sig": "…", "signed_at": "2026-10-01T11:00:00+09:00"}],
  "jobs": [],
  "cancel_jobs": [],
  "approvals": [],
  "disabled": false
}
```

## 오류

| 상태 코드 | 언제 | Bot UI가 할 일 |
| --- | --- | --- |
| 401 | 키 없음·틀림 | 트레이 「등록 전」, BUI-03 「키가 거부되었습니다」. 실행 중 Bot은 계속, 기록은 쌓음 |
| 403 | 키 폐기·만료 (`detail.code`=`key_revoked`\|`key_expired`), 키 종류가 다름 (`wrong_key_type`) | 알림 「Center가 이 PC의 키를 거부했습니다」. 하트비트 간격을 5분으로 늘림. 실행 중 Bot은 끝까지, 기록은 쌓음 |
| 409 | 키가 다른 PC에 묶여 있음 (`key_bound_elsewhere`, `detail.machine_name`) | BUI-03에 「이 키는 <PC>에서 쓰고 있습니다」 |
| 422 | 필수 필드 누락, 더 높은 `schema` | Bot UI 업데이트 필요 안내 |
| 5xx / 연결 실패 | | 트레이 「연결 끊김」. 30초 간격 재시도 (최대 5분까지 늘림). 실행·대기열은 계속 |

## 호환 규칙

- 모든 값 목록(`status`, `CurrentRun.state`·`source`, `Queue.items[].source`, `WorkerState.state`·`session`, `JobAck.result`·`reason`, `DeploymentResult.result`)은 **열린 문자열**이다. Center는 모르는 값도 저장하고 화면에 그대로 보인다. 모르는 값 하나로 하트비트 전체를 422로 거부하지 않는다 (프로토타입 결함).
- 모르는 선택 필드는 무시한다. 더 높은 `schema`는 거부한다.
- Center는 `current_run`이 2건 이상 오는 경우를 받지 않는다 — 모델이 단일 객체라 표현할 수 없다 (ADR-0014를 계약으로 강제).

## 프로토타입과 달라진 것

| 프로토타입 | 여기 |
| --- | --- |
| `POST /api/bots/enroll` + 공용 enroll 토큰, `bot_id`를 경로로 | `register` + Bot UI별 Center API 키, 신원은 키로 |
| `current_runs[]` (여러 건) | `current_run` 1건 + `queue` |
| Worker 상태 없음 | `worker` |
| 준비 상태 없음 | `readiness` (서비스 앱 키 참조 누락 포함) |
| 작업 `pending/dispatched/accepted/rejected` | `queued`·`expired`·`cancelled` 추가, 취소 지시 `cancel_jobs` |
| 상태 닫힌 목록 → 422 | 열린 문자열 |

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 | 0012, 0013, 0014 |
| 2026-10-01 | 1 | 검토 반영: 맞추기 규칙(`bot_ui_lost`), 시작한 작업 취소 거절, `disabled`는 200으로만, 모든 값 목록 열린 문자열, `deployment_results`, `wrong_key_type`, PC 묶음 풀기 | — |
| 2026-10-01 | 1 | C5 검토 반영: 시작된 작업의 취소 거절은 `cancel_refused`(작업은 `accepted` 유지), 예시 봉투를 C2 필드로 | — |
| 2026-10-01 | 1 | 확장 반영: `runtimes.extensions` | 0018 |
| 2026-10-01 | 1 | 확장 검토 반영: 하트비트 `extensions` | 0018 |
| 2026-10-01 | 1 | 화면 검토 반영: Worker `off`·`reserved_for`, 현장 취소 `cancelled_on_pc` | — |
| 2026-10-06 | 1 | Center가 `deployment_results`를 쌓아 둔다고 적었다 (멱등은 `(deployment_id, at)`) — CON-03을 붙이다 Center가 그것을 버리고 있는 것이 드러났다 | — |

# C3. 실행 이벤트

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Bot UI(실행 중 Bot)·서버 실행기·Studio(선택) → Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/events.py` (import `chaeksas.contracts.events`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c3-run-event.json`](../../packages/contracts/schemas/c3-run-event.json) · [`c3-event-batch-response.json`](../../packages/contracts/schemas/c3-event-batch-response.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md) |

## 목적

실행 한 번(`run_id`)에서 일어난 일을 한 형식으로 남긴다. 같은 이벤트가 Studio 로그 탭, Bot UI 「실행 기록」, Center 콘솔 실행 로그(CON-01)·Bot 현황 준비도(CON-02)에 쓰인다. 실행하는 쪽은 로컬 파일(`runs/<run_id>.jsonl`)에 먼저 쓰고, Center에 닿을 때 묶어서 보낸다.

## 전송

- 방식: HTTP `POST /api/v1/runs/{run_id}/events`, 본문은 이벤트 배열 (로컬 jsonl의 줄들).
- 인증: `Authorization: Bearer <Center API 키>`. **보낸 쪽(Bot UI / 서버 실행기 / Studio)은 키로 정해진다.** 프로토타입처럼 `bot_id`를 쿼리로 받지 않는다 (사칭 방지).
- 소유: Center는 `run_id`를 **처음 이벤트를 보낸 키**에 묶는다. 다른 키로 같은 `run_id`에 보내면 403 `run_owner_mismatch` (다른 Bot UI의 실행 기록을 덮지 못하게).
- 멱등성: `(run_id, seq)`가 키. 같은 줄을 다시 보내면 무시하고 `duplicates`로 센다. 그래서 보내는 쪽은 실패하면 같은 배치를 그대로 다시 보내면 된다.
- 크기 한도: 한 배치 500줄, 1 MB. 넘으면 413.
- 순서: 한 `run_id` 안에서 `seq`는 1부터 1씩 는다. 빠진 번호가 있어도 받는다 (나중에 채워질 수 있음).

## 모델

### RunEvent

| 필드 | 타입 | 필수 | 뜻 | 추가된 schema |
| --- | --- | --- | --- | --- |
| `schema` | int | ✓ | 1 | 1 |
| `run_id` | str | ✓ | `run_<YYYYMMDD>_<HHMMSS>_<hex6>` (운영), `test_<YYYYMMDD>_<HHMMSS>_<hex6>` (Studio 시험 실행). 실행하는 쪽이 만든다 | 1 |
| `seq` | int | ✓ | 실행 안에서 1부터 단조 증가 | 1 |
| `ts` | str | ✓ | ISO 8601, 시간대 포함 | 1 |
| `kind` | str | ✓ | 이벤트 종류. **열린 문자열** — 받는 쪽은 모르는 종류도 저장한다 (아래) | 1 |
| `node_id` | str | | BPMN 노드 id (노드에 속한 이벤트일 때) | 1 |
| `data` | object | | 종류별 내용. **업무 값·결재 답·비밀·스크린샷 없음** | 1 |

### 종류(`kind`)와 `data`

| kind | 언제 | `data` 필수 키 | `data` 선택 키 |
| --- | --- | --- | --- |
| `run_started` | 실행 시작 (항상 seq 1) | `bpm_process_id`, `version`, `run_location`(`pc`\|`server`), `executor`(`bot_ui`\|`server_runner`\|`studio`), `mode`(`autonomous`\|`deterministic`), `source`(시작 출처, C4 `source`와 같은 값: `job`\|`manual`\|`watch`\|`schedule`\|`message`\|`test`, 예약: `delegation`) | `job_id`, `parent_run_id`(예약 — PC 위임, ADR-0016 §3 제안), `queued_s`(대기열에서 기다린 초, PC), `case_id`(Studio) |
| `node_state` | 노드 상태가 바뀜 | `state`(`started`\|`completed`\|`failed`\|`skipped`\|`replayed`\|`waiting`) | `task_type`(`ai_task`\|`ui_task`\|`service_task`\|`approval`\|…), `error_code`, `message`(한 줄) |
| `log` | 사람이 읽는 한 줄 | `level`(`info`\|`warn`\|`error`), `message` | |
| `agent` | AI 태스크의 단계 하나 | `step`, `action`(`plan`\|`tool`\|`extract`\|`finish`) | `tool`, `summary`(값 제외) |
| `llm_usage` | AI 태스크가 모델을 쓴 양 | `model`, `input_tokens`, `output_tokens` | `provider`. **금액은 넣지 않는다** (Center가 가격표로 계산) |
| `ui_session` | UI 태스크 한 번이 끝남 (Worker 보고 요약) | `business_key`(`<run_id>:<node_id>:<node_instance>:<attempt>`, C10), `page_id`, `result`(`success`\|`escalated`\|`failed`), `steps`, `fallback_depth_max`, `healed` | `session_id` |
| `service_call` | 서비스 앱 작업 호출이 끝남 | `app_id`, `operation`, `mode`, `mode_used`, `status`(HTTP 코드), `duration_ms`, `key_ref`, `node_instance`, `attempt`, `call_seq` | `error_code`, `replayed`, `model`, `input_tokens`, `output_tokens` (C11 `usage`와 같은 이름) |
| `human_requested` | 결재·확인 요청 | `layer`(`approval`\|`confirmation`), `request_id`(C6과 같은 id), `where`(`center`\|`field`) | `form_key`, `expires_at` |
| `human_answered` | 답을 받음 (값 없음) | `request_id`, `answered_by` | |
| `human_timeout` | 시간 초과 | `request_id` | |
| `run_waiting` | (서버) 상태를 저장하고 기다리기 시작 | `waiting_for`(`approval`\|`message`\|`timer`, 예약: `delegation`) | `request_id`, `until` |
| `run_resumed` | (서버) 저장된 실행을 이어 감 | `after_s` | `reason`(`answer`\|`message`\|`timer`\|`restart`) |
| `run_finished` | 실행 끝 (항상 마지막) | `status`(`success`\|`failed`\|`cancelled`), `duration_s`, `ai_tasks`, `replayed_tasks`, `ui_tasks`, `service_calls`, `human_requests` | `error_code`, `error_message`(한 줄) |

- 배포 적용 결정은 실행이 아니므로 실행 이벤트로 보내지 않는다 → C4 하트비트의 `deployment_results` (CON-03 「최근 배치 결정」).
- `kind`와 `data`의 값 목록(`state`, `source`, `layer`, `status` 등)은 모두 **열린 문자열**이다 (README 원칙 10).
- PC Bot은 결재·확인을 기다리는 동안 `node_state: waiting`만 남긴다 (`run_waiting`은 서버만 쓴다 — 실행 자리를 쥐고 있으므로).
- 업무 값 기록은 기본으로 끈다. 실행 설정에서 명시적으로 켠 경우에만 `kind: "data"`(`data.vars`: 이름→값)를 보낸다 (principle 6).

## 예시

```json
[
  {"schema": 1, "run_id": "run_20261001_101500_a1b2c3", "seq": 1, "ts": "2026-10-01T10:15:00+09:00",
   "kind": "run_started",
   "data": {"bpm_process_id": "erp.order-entry", "version": "2.1.0", "run_location": "pc",
            "executor": "bot_ui", "mode": "deterministic", "source": "job", "job_id": "job_8f3e", "queued_s": 42}},
  {"schema": 1, "run_id": "run_20261001_101500_a1b2c3", "seq": 2, "ts": "2026-10-01T10:15:01+09:00",
   "kind": "node_state", "node_id": "Task_fill_order", "data": {"state": "started", "task_type": "ui_task"}},
  {"schema": 1, "run_id": "run_20261001_101500_a1b2c3", "seq": 3, "ts": "2026-10-01T10:15:20+09:00",
   "kind": "ui_session", "node_id": "Task_fill_order",
   "data": {"business_key": "run_20261001_101500_a1b2c3:Task_fill_order:1:1", "page_id": "erp.order.form",
            "result": "success", "steps": 6, "fallback_depth_max": 1, "healed": false}}
]
```

응답:

```json
{"run_id": "run_20261001_101500_a1b2c3", "accepted": 3, "duplicates": 0, "rejected": []}
```

## 오류

| 상태 코드 | 언제 | 보내는 쪽이 할 일 |
| --- | --- | --- |
| 400 | 본문의 `run_id`가 경로와 다름 | 버그. 그 배치를 로컬에 남기고 「보내지 못한 기록」으로 표시 |
| 401 / 403 | 키 없음·틀림 / 폐기·비활성 | 보내기를 멈추고 기록은 쌓아 둔다. 화면에 키 문제 표시 (BUI-05) |
| 413 | 배치가 너무 큼 | 나눠서 다시 보낸다 |
| 200 + `rejected[]` | 일부 줄만 문제 (필수 필드 누락, 더 높은 `schema`) — 나머지는 받는다. `rejected: [{seq, code}]` | 거부된 줄만 「보내지 못한 기록」에 남기고 계속 보낸다 (한 줄이 실행 전체를 막지 않게) |
| 403 `run_owner_mismatch` | 다른 키가 만든 `run_id` | 버그. 그 실행 기록은 로컬에 남김 |
| 422 | 배치 전체가 문제 (배열이 아님, 모든 줄이 다른 `run_id`) | 버그. 로컬에 남김 |
| 5xx / 연결 실패 | Center 문제 | 같은 배치를 그대로 다시 보낸다 (멱등). 간격은 30초부터 최대 10분 |

## 호환 규칙

- **모르는 `kind`는 거부하지 않고 저장만 한다.** 하나를 거부하면 배치 전체가 거부되고, `seq`가 단조라서 그 실행의 기록이 영원히 막힌다 (프로토타입에서 실제로 일어남).
- 모르는 `data` 키·최상위 선택 필드: 저장하고 무시한다.
- 더 높은 `schema`: 거부한다 (아는 필드의 뜻이 바뀌었을 수 있음).
- 새 `kind` 이름은 짧게 (Center 저장 열 50자).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (프로토타입 이벤트에서 `hitl_*` → `human_*`, `ui_session`·`service_call`·`run_waiting` 추가, 보낸 쪽은 키로 식별) | 0013, 0014, 0015 |
| 2026-10-01 | 1 | 검토 반영: `trigger` → `source`, `test_` 실행 id, 배포 결정은 C4로, 줄 단위 거부, `run_id` 소유, `service_call.mode_used`·토큰 이름 통일 | — |
| 2026-10-01 | 1 | C10 검토 반영: `business_key` 4단 형식 | — |
| 2026-10-01 | 1 | 확장 검토 반영: `service_call.call_seq` | 0018 |

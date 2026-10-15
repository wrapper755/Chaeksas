# C12. Center API: 서버 실행기

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-14) — 등록·하트비트·운영 API·배포 설치·작업 실행·기다리는 실행의 저장·재개·결재·**메시지**가 양쪽에서 돌고 시험이 지킨다 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 서버 실행기 ↔ Center, 외부 시스템 → Center (메시지) |
| 코드 위치 | `packages/contracts/server_runner.py` |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0038](../decisions/0038-approval-request-channel.md), [0054](../decisions/0054-server-run-state-and-concurrency.md), [0056](../decisions/0056-bounded-seen-maps.md), [0057](../decisions/0058-absorbed-messages-travel-with-the-snapshot.md) |
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
  - `POST /api/v1/server-runner/delegations` — **PC 위임을 맡긴다** (§PC 위임)
- 인증: Center API 키 (종류 「서버 실행기용」, CON-11). 다른 종류의 키는 403 `wrong_key_type`.
- 키 묶기는 C4와 같다 — 키 하나 ↔ 서버 하나 ↔ 실행기 행 하나이고, 같은 `machine_id`를 다른 키가 등록하면 409 `machine_already_registered`다 (C4 「키 묶기」). **규칙은 코드로도 한 자리다** (`center/host_keys.py`) — C4와 C12가 같은 함수를 쓴다. `machine_id`를 만드는 쪽도 하나다 (`core.machine`).
- 등록은 **멱등**이고, 등록·하트비트가 오면 운영자가 해 둔 「유실 처리」를 지운다 — 돌아온 실행기를 오프라인으로 보이게 두지 않는다 (CON-12).
- 이벤트(C3)와 결재(C6)는 Bot UI와 같은 API를 쓴다.

**지금 도는 것**: 등록·하트비트·운영 API 셋, **배포 설치**(C2 V1~V7 — Bot UI와 `core.deploy`를
같이 쓴다), `deployment_results`·`readiness` 보고, 그리고 **작업 실행** — 받은 작업을 스레드
하나로 돌려(ADR-0054 §5) 실행 기록을 하트비트 **뒤에** 보낸다 (C3 §전송). 서버 대상 배포·작업을
막던 스위치(`SERVER_RUNNER_AVAILABLE`)는 **켰다**.

**기다리는 실행은 담아 두고 자리를 놓는다** (ADR-0054 §3) — 결재를 Center 결재함에 올리고
(C6 — 서버의 창구는 Center만이다) 하트비트로 내려온 답으로 **되살려 이어 간다**. **재시작도
같은 저장소가 넘긴다** — 다시 뜨면 담아 둔 것을 훑어 되살리고 `restored[]`로 알린다.
되살리지 않는 둘은 `restorable()`이 가른다 (판이 다름·기다린 적 없음).

**메시지도 돈다** (§메시지) — 외부 시스템이 `POST /api/v1/messages`로 넣으면 Center가 받는
곳을 찾아 하트비트 `messages[]`로 내려 주고, 기다리던 실행이 이어 가거나 새 작업이 생긴다.
**받는 곳을 Center가 고르지만 실행기가 다시 찾는다** — 둘 사이에 하트비트 한 주기가 있어
그동안 그 실행이 타이머로 지나갔을 수 있다 (그때는 `no_receiver`로 돌려보낸다).

**설치는 Bot UI와 같은 코드다** (`core.deploy`·`core.packages`) — 다른 것은 `host_kind`뿐이고,
그래서 서버는 `"*"` 대상 배포도 받는다 (ADR-0046). **Admin 공개키가 아직 없으면 설치하지
않고 기다린다** — 서명을 볼 수 없는데 설치하면 관문이 없는 것과 같고, 거부로 보고하면 멀쩡한
배포가 영원히 닫힌다 (공개키는 하트비트가 준다).

**운영 API (콘솔 CON-12, 관리자 토큰):**

| 경로 | 뜻 |
| --- | --- |
| `GET /api/v1/server-runners` | 목록 (상태·용량·실행 중·기다리는 실행·대기열·준비 상태·확장·최근 배치 결정·**키 앞자리와 만료**). **콘솔 토큰만** — Center API 키로는 볼 수 없다 (C5 권한표) |
| `POST /api/v1/server-runners/{id}/pause` / `resume` | 일시 중지·다시 시작. 다음 하트비트 응답의 `paused`로 전달된다 |
| `POST /api/v1/server-runners/{id}/mark-lost` | 유실 처리. 오프라인인 실행기만 (온라인이면 409 `runner_online`). 그 실행기의 실행을 `failed`(`runner_lost`)로 닫고 결재를 회수한다 (C6 `host_lost`) |

## 모델

### RegisterRequest

`{schema, machine_id, name, os, versions{core, server_runner}, max_concurrency, extensions: [{id, version, definition_hash, enabled}]}`.

`max_concurrency`는 설정값 `CHK_SERVER_RUNNER__MAX_CONCURRENCY`이고 기본 10이다.

→ `{server_runner_id: "srv_<hex8>", admin_keys, heartbeat_interval_s: 10, server_time}`

`admin_keys`는 **등록 응답에도 찬다** (하트비트와 같은 목록이다). 실행기는 공개키를 메모리에만
두고 다시 뜨면 **첫 하트비트보다 먼저** 담아 둔 실행을 되살리므로(ADR-0054), 여기가 비면 되살린
실행이 외부 확장의 봉투를 한 번도 검증할 수 없다 (C13 E6 — 「전송」).

### HeartbeatRequest

| 필드 | 뜻 |
| --- | --- |
| `schema`, `status` | `status`는 열린 문자열. 알려진 값: `running`, `paused`, `draining`, `error` |
| `capacity` | `{max, running}`. `running`은 기다리는 실행을 뺀 수 |
| `running[]` | `{run_id, bpm_process_id, version, node_id, started_at, job_id?}` |
| `waiting[]` | `{run_id, bpm_process_id, version, waiting_for: "approval" \| "message" \| "timer" \| "delegation", request_id?, message_name?, correlation?, until?, job_id?, since}` |
| `job_acks[]` | C4와 같은 모양. `result`: `started`, `rejected`, `expired`, `cancelled`, `cancel_refused` |
| `approval_acks[]`, `deployment_results[]` | C4와 같다 |
| `readiness[]` | 배포된 서버 Bot별 준비 상태 (C4 Readiness와 같은 모양: 빠진 키 참조·확장). 바뀌었을 때만 |
| `message_acks[]` | `{message_id, accepted, run_id?, reason?}` |
| `delegation_acks[]` | `{job_id, accepted}` — **위임 결과를 받았다** (§PC 위임). 받으면 Center가 그 값을 지운다 |
| `extensions[]` | 바뀌었을 때만 (C4와 같은 모양) |
| `restored[]` | 재시작 직후 저장소에서 되살려 **정말 이어 가는** 실행 `run_id` (첫 하트비트에만). 되살리지 못한 것은 여기 넣지 않고 C5 `run_status`에 사유와 함께 적는다 |
| `unsent_events` | |

**`waiting[]`의 짝 칸은 비울 수 없다** — `approval`이면 `request_id`, `message`면
`message_name`, `timer`면 `until`, **`delegation`이면 `job_id`**다 (§PC 위임). 같은 실행이 `running[]`과 `waiting[]`에 함께 있을 수도
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
| `messages[]` | `{message_id, name, correlation?, payload, received_at}` — **기다리는 실행에 넣을 것만** 내려온다. 메시지 시작은 Center가 작업으로 바꿔 `jobs[]`로 보낸다 (§메시지) |
| `delegations[]` | **끝난 PC 위임의 결과** — `{job_id, run_id, state, outputs?, reason?}` (§PC 위임). ack가 올 때까지 다시 싣는다 |
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

**받는 곳을 고르는 규칙은 엔진의 것이다** (C14 — 이름이 같고, 둘 중 한쪽이라도 상관 키가
없으면 맞는 것으로 본다). Center는 보고된 `waiting[]` 줄에 **같은 규칙**을 적용하고, 실행기는
그 실행의 `waits`에 적용한다 — 베끼지 않도록 판정은 계약의 `message_matches()` 하나이고,
엔진의 `Engine.message_target()`과 **같은 답을 내는지** 시험이 대조한다. 어긋나면 Center가
「전달했다」고 하고 실행기가 `no_receiver`로 돌려보낸다.

- **`correlation`이 없는 메시지는 기다리는 실행을 찾지 않는다** (위 표) — 메시지 시작만이다.
  이것은 *고를 것인가*의 규칙이라 **Center에 있고 판정 함수에는 없다** — 넣으면 엔진과 규칙이
  갈라져 Center가 고른 실행에 실행기가 넣지 못한다. 상관 키 없이 고르면 같은 이름을 기다리는
  실행이 여럿일 때 **엉뚱한 실행**이 깨어난다 (주문 번호 없는 「입금됐다」가 아무 주문이나
  깨우는 꼴이다).
- **기다리는 실행이 여럿 맞으면 가장 오래 기다린 것**에 준다 (`since`가 이른 것). 한 메시지는
  **한 실행에만** 간다.
- 메시지 시작 트리거가 **서버 Bot 둘 이상**에 걸리면 422 `receiver_ambiguous`다 — Center가
  고르지 않는다 (C5의 `version_ambiguous`와 같은 결). 부르는 쪽이 `POST /jobs`로 어느 Bot을
  돌릴지 정하면 된다.
- **메시지 시작은 작업을 거친다** — Center가 `POST /jobs`와 **같은 함수**로 작업을 만들므로
  배포되지 않은 Bot은 메시지로도 돌지 않고, 빈자리·Bot별 상한도 그대로 지켜진다. `payload`가
  그 작업의 `inputs`가 된다.
- 멱등은 C5와 같다 — 같은 주인이 같은 `idempotency_key`로 7일 안에 다시 부르면 **같은 응답**
  (200)이고, 다른 본문이면 409 `idempotency_conflict`다.

**내려 주기와 ack** (실행으로 가는 메시지만 — 새 작업으로 간 것은 그 자리에서 끝난다):

- 작업과 같다 (ADR-0007) — **ack가 올 때까지 매번 다시 싣는다.** 그래서 실행기는 **지금 넣을
  수 없는 메시지를 ack하지 않고 그냥 둔다** (빈자리가 없거나 아직 되살리지 못했다) — 다음
  주기에 다시 온다. 거절로 적으면 멀쩡한 메시지가 버려진다.
- `accepted: true`면 끝이다 (`run_id`를 함께 싣는다 — Center가 고른 실행과 다를 수 있다).
- `accepted: false`는 **다시 보내지 않는다.** 사유는 `no_receiver`(그 사이 지나갔다)·
  `run_ended`·`not_waiting`·`duplicate`다. 여기서 다시 싣기로 하면 영원히 도는 메시지가 된다.
- 받을 실행기가 **유실 처리**되면 그 실행기로 가던 메시지는 `host_lost`로 닫는다 (결재가
  회수되는 것과 같은 자리다 — C6 `host_lost`).

### PC 위임 (서버 Bot → PC Bot)

서버 Bot이 화면 조작·현장 확인이 필요한 한 부분을 **따로 배포된 PC Bot**에 맡긴다 ([ADR-0062](../decisions/0062-pc-delegation.md)). 그림은 C14 `chk:call.delegate`, 매니페스트는 C1 `requires.delegations`다.

**`POST /api/v1/server-runner/delegations`** (실행기 키만)

| 필드 | 뜻 |
| --- | --- |
| `run_id` | 맡기는 **서버 실행**. **보낸 키의 실행이어야 한다** (C3 소유와 같은 대조) — 남의 실행 이름으로 작업을 만들 수 없다 |
| `node_id`, `node_instance` | 그 실행 안의 호출 자리. 멱등 키를 여기서 짓는다 |
| `bpm_process_id`, `version?` | 부를 PC Bot. 판을 비우면 **배포된 판**(둘 이상이면 422 `version_ambiguous`) |
| `bot_ui?` | **그 PC로만** 보낸다 (그림의 `bot_ui` 식을 실행기가 값으로 풀어 보낸다). 비우면 Center가 고른다 |
| `inputs` | 그 Bot에 줄 입력 (C14 `chk:call.input`을 실행기가 값으로 푼 것) |

- 응답은 `{job_id, bot_ui_id, state}`다. **201이 새 작업, 200이 이미 만든 것**이다.
- **멱등 키는 Center가 짓는다** — `dlg_<run_id>_<node_id>_<node_instance>`. 본문에서 받지 않는다(`requested_by`와 같은 결) — 부르는 쪽마다 짓는 규칙이 갈라지면 되살린 실행이 **작업을 두 번 만든다**. 그래서 ADR-0054의 「마지막 기다림 이후를 다시 한다」가 그대로 성립한다: 다시 요청하면 **같은 작업이 돌아온다**.
- **`requested_by`는 Center가 적는다** — `server_bot:<run_id>`(C5 예약값). 본문에서 받지 않으므로 그 이름을 지어낼 수 없다.
- **고른 뒤에는 `POST /jobs`와 같은 함수로 작업이 된다** — 배포 검사·대상 검사·대기열이 한 자리에 남는다 (메시지 시작이 이미 그렇다, §메시지).

**어느 PC인가 — Center가 고른다** (그림에 PC id를 적지 않는다: 「PC에서 무엇을 돌려도 되는가」를 정하는 것은 배포다, [ADR-0049](../decisions/0049-deployment-target-must-exist.md))

1. 그 `<id>@<version>`이 **살아 있는 배포로 걸린 PC** 중에서 고른다 (PC 배포는 대상이 `bot_ui_id` 하나씩이다 — [ADR-0046](../decisions/0046-no-wildcard-pc-deployment.md)).
2. **활성인 PC만**, 그중 **대기열이 가장 짧은 곳**. 같으면 `bot_ui_id` 순서다.
3. 고를 곳이 없으면 **거부**다 (404 `no_deployment`). **기다리지 않는다** — 배포되지 않은 것을 기다리는 것은 업무가 아니라 설정 잘못이고, 오류 경계가 받아야 사람이 안다.
4. `bot_ui`를 적었으면 **그 PC만** 본다 (배포되지 않았거나 없으면 역시 `no_deployment`).

**결과가 돌아오는 길** (원칙 6의 명시한 예외 — C6 `review`·`answer`와 같은 모양)

| 항목 | 정한 것 |
| --- | --- |
| 올라오는 쪽 | PC Bot UI의 작업 ack에 **그 Bot이 선언한 `outputs`만** 싣는다 (C4·C1) |
| 내려가는 쪽 | 하트비트 응답 `delegations[]`. **그 작업을 낸 실행기에게만** 내려간다 |
| 다시 싣기 | **ack(`delegation_acks[]`)가 올 때까지 매번 다시 싣는다** (작업·메시지와 같다) |
| 지우기 | **ack가 오면 값을 바로 지운다.** 못 받은 것은 **작업 멱등 기간(7일)**에 지운다 — 기간을 새로 만들지 않는다. 누가·언제·성패는 남는다 |
| 화면 | **값을 보이지 않는다** (CON-05가 작업 입력을 키만 보이는 것과 같다) |

- `state`는 **열린 문자열**이고 알려진 값은 작업 ack와 같다: `finished`·`failed`·`cancelled`·`expired`·`rejected`. 실행기는 `finished`가 아니면 **오류 경계로 넘긴다** (C14 — 업무 실패다).
- 기다리는 동안 그 실행은 **자리를 쥐지 않는다** (`waiting[]`의 `delegation` 갈래, 짝 칸은 `job_id`). **PC 쪽은 ADR-0014 그대로** — 하나씩, 끝날 때까지.
- 서버 실행이 취소되면 **그 위임 작업도 취소한다**. 이미 시작된 PC 실행은 끝까지 가고(C5 — 「시작된 작업의 취소는 거절」) 그 결과는 받는 쪽이 없으므로 **버린다**.
- **배포 때 한 가지를 더 본다** — `requires.delegations`의 Bot이 **승인된 패키지로 Center에 있어야** 한다 (422 `delegation_not_approved`. C1 R8처럼 배포 시점에 본다 — 매니페스트만으로는 알 수 없다). 판을 비운 위임은 **승인된 판이 하나라도 있으면** 통과다. **PC에 배포됐는가는 묻지 않는다**: 서버 Bot을 먼저 배포하는 순서를 막으면 안 되고, 실제 관문은 위임을 요청할 때다.

### 재시작과 유실

세부는 [ADR-0054](../decisions/0054-server-run-state-and-concurrency.md)가 정했다. 계약이 보는 것만 여기 적는다.

- 서버 실행기는 기다리는 실행의 상태를 **자기 저장소(SQLite)에 JSON 한 덩이로** 둔다.
  **적는 때는 둘**(실행을 시작할 때·멈출 때)이고 **끝나면 지운다** — 시작할 때 적지 않으면
  다시 뜬 실행기가 죽은 실행을 알지 못해 작업이 `accepted`로 영원히 남는다.
- **그림은 담지 않는다** — 설치된 패키지에서 다시 읽는다. 담은 `bpm_process_id`·`version`과
  다르면 **되살리지 않는다**(`runner_version_changed`). 실행 기록도 담지 않는다 — 파일이
  원본이다 (C3).
- **기다림은 실행 기록에도 남는다** — 멈출 때 C3 `run_waiting`, 이어 갈 때 `run_resumed`다.
  이 계약의 `waiting[]`은 **지금 모습**이라 기다림이 끝나면 사라지므로, 지나간 기다림은 그
  두 줄에만 있다 (CON-01 「이어 돈 기록」). 되살려 이어 가는 것도 `reason: restart`로 남는다.
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
  - **기한은 「그 시각 이후」다 — 일찍 가지 않고, 늦을 수 있다** ([ADR-0061](../decisions/0061-waking-runs-whose-timer-is-due.md)).
    기다리는 실행은 스레드를 놓으므로 시각이 된 것을 **하트비트 주기마다 쓸어서** 깨운다 —
    그래서 **주기(기본 10초)만큼 늦을 수 있고 초 단위 기한을 약속하지 않는다**. 빈자리가
    없으면 **다음 주기에 깨운다**(상한을 넘겨 돌지 않는다) — 밀린 것은 `waiting[].until`이
    지난 시각으로 올라가 CON-12에 보인다.
- **맞추기 규칙은 C4와 같고 사유만 다르다** — 두 주기 연속 `running[]`·`waiting[]`에 보이지
  않고 ack도 없는 작업은 `rejected`이고, 그 `state_reason`은 **`runner_lost`**다 (C4의
  `bot_ui_lost`가 아니다 — 뭉개면 CON-12가 서버에 「bot_ui_lost」라고 적는다). 그 실행의
  결재는 회수된다 (C6 `host_lost`).
- 하트비트가 3분 동안 없으면 Center는 그 실행기를 「오프라인」으로 표시한다. 실행은 유실로 보지 않고 기다린다. 운영자가 CON-12에서 「유실 처리」를 하면 그때 그 실행기의 실행을 `failed`(`runner_lost`)로 닫고, 결재를 회수한다 (C6 `host_lost`).
- **「이미 봤다」를 들고 있는 동안은 정해져 있다** ([ADR-0056](../decisions/0056-bounded-seen-maps.md)) —
  받는 쪽은 작업·메시지의 마지막 ack를 기억해 **같은 지시가 다시 와도 두 번 돌리지 않고 그
  ack를 되돌려 보낸다**(C4 멱등). 그 기억은 **ack가 닿은 뒤 두 주기**까지이고, **닿지 않은
  ack는 버리지 않는다** — 버리면 다시 내려온 지시가 「처음 본 것」이 되어 메시지가 실행에
  두 번 들어가거나 같은 작업으로 실행이 둘 생긴다. 「닿았다」는 **그 ack를 실은 하트비트가
  200을 받은 것**이다 (Center가 같은 요청에서 반영한다).
- **빨아들인 메시지는 상태와 함께 담긴다** ([ADR-0058](../decisions/0058-absorbed-messages-travel-with-the-snapshot.md)) —
  그 기억은 메모리라 재시작을 못 넘으므로, 실행에 넣은 `message_id`를 **스냅샷과 한
  트랜잭션에** 적는다. 그래서 되살린 실행이 **같은 이름·상관 키를 다시 기다리더라도**(받고 또
  기다리는 그림이 있다) Center가 다시 실은 그 메시지가 두 번 들어가지 않고 **마지막 ack가
  되돌아간다**. **따로 담지 않는 것이 요점이다** — 넣은 뒤 담기 전에 죽는 틈에서 기억과 상태가
  갈라지면 그 메시지를 영영 잃는다. 실행이 끝나면 그 기억도 함께 지워지므로, 그 뒤에 다시 온
  같은 메시지는 `no_receiver`다 (업무는 한 번만 일어났고 접수는 실행 기록에 남는다 — C3).

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

메시지를 넣는 쪽 (`POST /api/v1/messages` — 외부 시스템).

```json
{
  "schema": 1,
  "name": "bid_quote",
  "correlation": "BID-2610-01",
  "payload": {"견적": {"공급사": "가나상사", "단가": 1002, "회신메일": "q2@example.com"}},
  "idempotency_key": "po-77"
}
```

## 오류

C4와 같다 (401, 403 `key_revoked`·`wrong_key_type`, 409 `machine_mismatch`·`machine_already_registered`·`not_registered`, 422, 5xx). 메시지 API에는 다음이 더 있다.

- 422 `no_receiver`
- 422 `receiver_ambiguous` — 메시지 시작 트리거가 서버 Bot 둘 이상에 걸렸다
- 409 `idempotency_conflict`

위임 요청에는 다음이 더 있다.

- 404 `no_deployment` — 그 판이 배포된 활성 PC가 없다 (지정한 PC가 없거나 그 판이 없는 경우도 같다)
- 403 `run_owner_mismatch` — 남의 실행 이름으로 맡기려 했다 (C3 소유와 같은 대조)
- 422 `version_ambiguous` — 판을 비웠는데 배포된 판이 둘 이상이다

되살리지 못한 실행의 사유는 오류가 아니라 **C5 `run_status`의 `error_code`**로 간다 —
`runner_restarted`·`runner_version_changed`·`snapshot_unreadable` (ADR-0054).

## 호환 규칙

- C4와 같다. 모든 값 목록은 열린 문자열이다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-15 | 1 | **PC 위임**을 더했다 — 요청 경로(`POST …/delegations`), `waiting[]`의 `delegation` 갈래와 짝 칸 `job_id`, 하트비트의 `delegations[]`·`delegation_acks[]`, 그리고 배포 때 「그 Bot이 승인되어 있나」. **어느 PC인가는 Center가 고르고**(배포된·활성·대기열이 짧은 곳) **멱등 키·`requested_by`는 Center가 짓는다**(본문에서 받지 않는다). 선택 칸이라 **옛 실행기는 그대로 돈다** | [0062](../decisions/0062-pc-delegation.md) |
| 2026-10-01 | 1 | 초안 (M7) | 0015, 0016 |
| 2026-10-01 | 1 | 화면 검토 반영: 운영 API(목록·일시 중지·유실 처리), `readiness` | — |
| 2026-10-13 | 1 | 스파이크 s10 뒤 **합의**로 올림. 모델·검사가 코드로 생겼다(`validate_heartbeat`·`free_slots`·`pick_jobs`·`restorable`). §재시작과 유실을 다시 썼다 — 적는 때 둘·그림은 담지 않음·마지막 기다림 이후를 다시 함(멱등 키가 같은 값으로 다시 만들어지므로 호출 전 저장이 필요 없다)·기다린 적 없는 실행은 되살리지 않음·**기한은 Center가 꺼져 있어도 간다** | 0054 |
| 2026-10-13 | 1 | **등록·하트비트가 양쪽에서 돈다** — `apps/server_runner`(등록·하트비트·SIGTERM)와 Center(`api/server_runner.py` + 운영 API 셋). 키 묶기 규칙을 C4와 **한 코드로** 모았고(`center/host_keys.py`), `machine_id`도 한 자리다(`core.machine`). 작업 나누기(`free_slots`·`pick_jobs`)가 붙었고 **`waiting[]`의 작업은 `run_id`로 되짚는다**(그 칸에 `job_id`가 없다 — 안 되짚으면 결재를 기다리는 실행을 `runner_lost`로 닫는다). 남은 것은 메시지 API와 실행이다 | 0054 |
| 2026-10-13 | 1 | **배포 설치와 준비 상태가 돈다** — 설치는 Bot UI와 **같은 코드**로 모았고(`core.deploy`·`core.packages` — `host_kind`만 다르다) 실행기가 `deployment_results`·`readiness`를 보고한다. `ServerRunnerInfo`에 그 셋(+확장)이 생겨 CON-12가 읽을 자리가 찼다. **내려받기 관문이 서버 실행기를 알아본다** — 「등록은 M7부터다」로 막고 있었는데 등록은 지난 조각에서 생겼다 | 0054 |
| 2026-10-13 | 1 | **작업 실행이 돈다** — 받은 작업을 스레드 하나로 돌려(ADR-0054 §5) 실행 기록을 하트비트 뒤에 보낸다. **`SERVER_RUNNER_AVAILABLE`을 켰다** — 서버 대상 배포·작업이 만들어진다. `id`를 비운 작업은 Center가 고르고(`server_versions`) 고른 뒤엔 그 실행기에 머문다 | 0054 |
| 2026-10-13 | 1 | **기다리는 실행을 담고 되살리고 결재로 이어 간다** (M7 기준 셋째) — 담는 길은 `core.run_snapshot`(칸을 셋으로 가르고 **칸이 늘면 시험이 묻는다**), 저장소는 실행기의 SQLite 한 파일. 결재를 C6으로 올리고 하트비트 답으로 잇는다. 붙이다 드러난 것 둘: **`_host_of`가 서버 실행기를 몰라** 답이 영영 내려가지 않았고(`host_id`가 키 id였다), 하트비트의 `running[]`·`waiting[]`이 **빈 채로 나가고 있었다**(#109) — 그러면 CON-12가 못 보이고 Center가 상한을 넘겨 보내고 맞추기가 멀쩡한 실행을 닫는다. 남은 것은 §메시지 하나다 | 0054 |
| 2026-10-14 | 1 | **메시지가 돈다 → 「구현됨」** — `POST /api/v1/messages`(`center/api/messages.py`)·하트비트 `messages[]`·`message_acks[]`가 양쪽에 생겼다. 받는 곳을 고르는 규칙은 **엔진의 것 하나**이고(`message_matches()` ↔ `Engine.message_target()`, 시험이 대조한다) **상관 키가 없으면 찾지 않는 것**은 *고를 것인가*의 판단이라 Center에 둔다. 메시지 시작은 **`POST /jobs`와 같은 함수**로 작업이 되고(배포 검사·상한이 한 자리에 남는다), 둘 이상이면 422 `receiver_ambiguous`다. 작업과 같이 **ack가 올 때까지 다시 싣고** 실행기는 넣을 수 없는 것을 **ack하지 않고 둔다**. 거절은 다시 싣지 않는다. 「유실 처리」가 가던 메시지도 닫는다 | 0054 |
| 2026-10-14 | 1 | **멱등 기억이 무한히 자라지 않는다** ([ADR-0056](../decisions/0056-bounded-seen-maps.md)) — 이미 본 작업·메시지의 마지막 ack는 **닿은 뒤 두 주기**까지 들고 있다가 잊고, **닿지 않은 ack는 버리지 않는다**(버리면 다시 내려온 지시가 「처음 본 것」이 되어 업무가 두 번 일어난다). 자리는 하나다(`seen.py`) — 작업과 메시지가 같은 까닭으로 있으므로 규칙을 갈라 두면 한쪽만 고친다 | 0056 |
| 2026-10-14 | 1 | **CON-12가 이것을 읽는다** — `ServerRunnerInfo`에 `key_prefix`가 생겼다(만료만 보이면 CON-11의 어느 줄인지 못 찾는다 — 키가 여럿이면 만료일이 겹친다. 원문·해시는 그대로 주지 않는다). 읽는 자리는 **키 하나에서 둘을 함께** 꺼낸다 (`_key_of` — 앞자리만 있고 만료가 없으면 화면이 「무기한」을 거짓으로 말한다) | — |
| 2026-10-14 | 1 | **재시작을 건너서도 메시지가 두 번 들어가지 않는다** ([ADR-0058](../decisions/0058-absorbed-messages-travel-with-the-snapshot.md)) — ADR-0056이 「재 보지 않았다」고 적어 둔 자리를 BX-11로 재 보니 **정말 두 번 들어갔다**(견적 하나가 두 번 접수). 빨아들인 `message_id`를 **스냅샷과 한 트랜잭션에** 담아 다시 뜰 때 멱등 기억을 되살린다. **따로 담지 않는 것이 요점이다** — 넣은 뒤 담기 전에 죽는 틈에서 갈라지면 그 메시지를 영영 잃는다. `message_id`는 엔진에 넘기지 않는다(전송 이름이다) | 0058 |

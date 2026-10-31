# C4. Center API: PC 실행기 등록·하트비트

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-10, [09-gaps](../09-gaps.md) §1 대조 — 등록·하트비트·배포·작업·결재·`readiness`까지 양쪽이 쓴다) — **§등록 요청과 승인·키 회전도 양쪽이 쓴다** (2026-10-25, [ADR-0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md)) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | PC 실행기 ↔ Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/bot_ui.py` (import `chaeksas.contracts.bot_ui`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c4-register-request.json`](../../packages/contracts/schemas/c4-register-request.json) · [`c4-register-response.json`](../../packages/contracts/schemas/c4-register-response.json) · [`c4-heartbeat-request.json`](../../packages/contracts/schemas/c4-heartbeat-request.json) · [`c4-heartbeat-response.json`](../../packages/contracts/schemas/c4-heartbeat-response.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0012](../decisions/0012-bot-ui.md), [0013](../decisions/0013-api-keys.md), [0014](../decisions/0014-one-bot-per-pc.md), [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md), [0094](../decisions/0094-service-app-keys-ride-the-deployment.md), [0114](../decisions/0114-remove-ui-automation.md) |
| 관련 화면 | BUI-01·03·04·05, CON-03·05·11 |

## 목적

PC 실행기가 **등록 요청**을 보내 관리자의 승인으로 Center API 키를 받고(§등록 요청과 승인), 그 키로 자기를 등록하고, 30초마다 상태(실행 중 BPM 프로세스 1건, 대기열, 준비 상태)를 보고하며, 그 응답으로 배포·작업·결재 답·취소 지시를 받는다. **연결은 항상 PC 실행기 → Center**다 (ADR-0007).

## 전송

- 방식:
  - `POST /api/v1/bot-ui/enroll` — 키가 없을 때 **등록 요청**을 보낸다 (§등록 요청과 승인, 인증 없음).
  - `GET /api/v1/bot-ui/enroll/{enrollment_id}` — 그 요청이 승인됐나 묻는다 (인증 없음).
  - `POST /api/v1/bot-ui/register` — 처음 한 번, 그리고 정보(이름·버전)가 바뀔 때.
  - `POST /api/v1/bot-ui/heartbeat` — 30초마다 (응답의 `next_heartbeat_s`를 따름).
- 인증: `Authorization: Bearer <Center API 키>` (종류 「PC 실행기용」 — 승인이 만든 키, 또는 자동화·시험용으로 관리자 토큰이 발급한 키). **등록 요청 두 경로만 인증이 없다.** **PC 실행기의 신원은 키로 정한다.** 경로·본문에 `bot_ui_id`를 넣지 않는다.
- 키 묶기: **키 하나 ↔ PC 하나 ↔ PC 실행기 행 하나**다 (아래 [키 묶기](#키-묶기)).
- 키 종류: 「PC 실행기용」 키만 받는다. Studio용·서버 실행기용 키로 부르면 403 `wrong_key_type`.
- 키 형식: `chk_ctr_<무작위 40자>`, 앞자리 16자만 화면에 (C11과 같은 규칙).
- 멱등성: `register`는 같은 키·같은 `machine_id`면 같은 `bot_ui_id`를 돌려준다 (정보만 갱신). `heartbeat`는 매번 상태를 덮어쓴다. `job_acks`·`approval_acks`는 같은 것을 다시 보내도 한 번만 반영한다.
- 크기 한도: 요청 256 KB.
- **`current_run`은 비어 있어도 `null`로 싣는다.** 「필수이지만 비어 있을 수 있는」 필드라서, `None`인 선택 필드처럼 빼 버리면 받는 쪽이 「필수 필드 누락」으로 422를 돌려준다 (`ContractModel.to_json_dict()`가 필수 필드의 `null`은 남긴다).
- 온라인 판정: 마지막 하트비트가 90초 이내면 「● 온라인」 (CON-03).

## 등록 요청과 승인

> 상태: **돈다** (2026-10-25, [ADR-0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md)) — Center `center/enrollments.py`·`api/enrollments.py`, PC 실행기 `agent.request_enrollment()`·`enroll_step()`, 봉함·요청 코드는 `chaeksas.contracts.enrollment` 한 자리다. 시험: `tests/test_center_enrollment.py`·`tests/test_bot_ui_agent.py`. 개발·CI의 환경변수 길(`CHK_BOT_UI__CENTER_API_KEY`)은 그대로 남는다.

설치하는 사람은 **Center 주소만** 넣는다. 키를 만드는 것도 내려 주는 것도 Center이고, 사람은 **이 PC를 들일지 승인만** 한다.

| 차례 | 누가 | 무엇을 |
| --- | --- | --- |
| 1 | PC 실행기 | 키가 없으면 키 쌍(X25519)을 만들어 비밀 반쪽을 OS 비밀 저장소에 두고 `POST …/enroll`을 보낸다 |
| 2 | Center | 요청을 「승인 대기」로 두고 `enrollment_id`와 **요청 코드**를 돌려준다 |
| 3 | PC 실행기 | 요청 코드를 **스스로 다시 계산해** 맞을 때만 BUI-03·트레이에 띄운다. `poll_after_s`마다 `GET …/enroll/{id}`로 묻는다 |
| 4 | 관리자 | CON-03 「승인 대기」에서 **같은 코드**를 확인하고 「승인」 (C5 §등록 승인) |
| 5 | Center | 「PC 실행기용」 키를 만들어 **그 `machine_id`에 미리 묶고**, 요청의 공개키로 봉해 둔다 |
| 6 | PC 실행기 | 다음에 물을 때 봉한 키를 받아 열고 OS 비밀 저장소에 둔 뒤 `register`를 부른다 (그다음은 지금과 같다) |
| 7 | Center | 그 키로 `register`가 성공하면 **봉해 둔 것을 지운다** — 그것이 받았다는 표시다 |

- **환경변수로 키가 오면**(`CHK_BOT_UI__CENTER_API_KEY` — 개발·CI) 등록 요청을 보내지 않는다.
- **요청 코드**: `SHA-256(public_key ‖ enrollment_id)`를 base32(RFC 4648, 대문자, 덧붙임 없음)로 적은 앞 8자를 `XXXX-XXXX`로 보인다. 공개키와 Center가 준 id 둘로 정해지므로 **사람이 지어 맞출 수 없고**, 가운데서 응답을 바꿔치면 PC 실행기가 계산한 값과 어긋나 띄우지 않는다. 같은 PC가 다시 요청하면 코드도 바뀐다.
- **승인 대기는 24시간**이다. 지나면 `expired`이고 PC 실행기는 새 요청을 보낸다(코드가 바뀐다). 같은 `machine_id`가 대기 중에 다시 요청하면 **옛 요청을 닫고** 새것만 남긴다 — CON-03에 같은 PC가 두 줄 서지 않는다.
- **승인된 키를 24시간 안에 `register`로 쓰지 않으면** Center가 그 키를 폐기하고 요청을 `expired`로 닫는다.
- **묻는 길에 인증이 없어도 된다.** 내려 주는 키는 그 요청의 공개키로 봉해 있어 남이 받아도 열지 못한다. `enrollment_id`는 `enr_` + 무작위 32자라 짐작할 수 없다.
- **막는 것**: 같은 원격 주소에서 10분에 10건까지(429 `enroll_rate_limited`), 대기 중인 요청은 Center 전체에 200건까지(429 `enroll_queue_full`).
- **거절**되면 `rejected`와 사유를 돌려주고 PC 실행기는 그것을 보인다. 다시 요청할 수 있다(관리자가 또 거절할 뿐이다).
- 승인은 **키 묶기 규칙을 그대로 따른다** (아래). 그 `machine_id`가 이미 다른 키로 등록돼 있으면 승인 화면이 그것을 말하고, 승인하면 **옛 키를 폐기하고 그 `bot_ui_id`를 이어받는다** — 「PC 묶음 풀기」가 하던 일을 승인이 한다(PC를 다시 설치한 경우).

### 봉함

받는 쪽 공개키로만 열리는 한 덩이다. 승인으로 받는 키와 아래 키 회전이 **같은 봉함**을 쓴다 (C15 일꾼 토큰도 같다).

| 칸 | 뜻 |
| --- | --- |
| `alg` | `x25519-hkdf-sha256-chacha20poly1305` (지금은 이것 하나) |
| `epk` | Center가 봉할 때마다 만든 X25519 공개키 (base64url, 32바이트) |
| `nonce` | 12바이트 (base64url) |
| `ciphertext` | 키 원문을 봉한 것 (base64url). HKDF의 `info`는 `chaeksas-seal-v1`, `salt`는 `enrollment_id`(회전이면 `bot_ui_id`) |

### EnrollRequest

`RegisterRequest`와 같은 칸(`schema`·`machine_id`·`name`·`os`·`versions`·`runtimes`)에 하나를 더한다.

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `public_key` | str | ✓ | X25519 공개키 (base64url, 32바이트). 틀리면 422 `public_key_invalid` |

### EnrollResponse · EnrollStatus

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `enrollment_id` | str | `enr_<무작위 32자>` |
| `state` | str | **열린 문자열.** 알려진 값: `pending` `approved` `rejected` `expired` |
| `code` | str | 요청 코드 `XXXX-XXXX` |
| `poll_after_s` | int | 다음에 물을 때까지 (기본 10) |
| `expires_at` | str | 승인 대기가 끝나는 때 |
| `sealed_key` | Sealed? | `approved`일 때만. 봉한 Center API 키 |
| `key_expires_at` | str? | `approved`일 때만. 받은 키의 만료 |
| `key_name` | str? | `approved`일 때만. 승인할 때 붙인 키 이름 — Studio가 「「<이름>」으로 들어와 있습니다」로 보인다 (ADR-0093) |
| `reason` | str? | `rejected`일 때 관리자가 적은 사유 |

`POST …/enroll`은 `EnrollResponse`(`state: pending`), `GET …/enroll/{id}`는 같은 모양의 `EnrollStatus`를 돌려준다. 없는 id는 404 `not_found`다.

### 키 회전

- 공개키를 아는 PC 실행기(등록 요청으로 들어왔거나 `RegisterRequest.public_key`를 보낸 것)에는 **만료 14일 전부터** 하트비트 답에 `rotated_key`가 실린다.
- PC 실행기는 열어서 OS 비밀 저장소의 키를 바꾸고 **다음 요청부터 새 키**를 쓴다. Center는 새 키로 첫 요청이 오면 옛 키를 폐기한다 — 그것이 받았다는 표시다. 그 전까지는 주기마다 같은 것을 싣는다.
- 새 키의 만료는 그때부터 1년이고 묶인 PC·`bot_ui_id`는 그대로다.
- 공개키를 모르는 PC 실행기(환경변수로 키를 받은 것)는 회전하지 않는다.

### 서비스 앱 키 전달 — 없다

BPM 프로세스는 서비스 앱을 C15 외부 작업으로 부르므로 **현장은 서비스 앱 키를 받지 않는다** ([ADR-0102](../decisions/0102-calling-outside-is-pull.md)). 하트비트에 `service_keys[]`·`drop_service_keys[]`·`service_key_acks[]`는 없다 — 옛 PC 실행기가 `service_key_acks[]`를 보내도 받는 쪽은 모르는 칸으로 무시하고(원칙 3), 옛 Center가 보내도 새 PC 실행기가 무시한다. 선택 칸을 걷은 것이라 판을 올리지 않는다.

### 호출 토큰

실행 프로세스가 외부 작업을 올릴 때 쓰는 토큰은 PC 실행기가 **제 Center API 키로** `POST /api/v1/call-tokens`를 불러 받는다 (C15 「정한 것」). 하트비트에 싣지 않는다 — 공개키가 없는 PC 실행기(환경변수 키)도 받아야 한다. PC 실행기는 그 토큰을 **메모리에만** 들고 비밀 저장소에 두지 않는다.

## 키 묶기

**`machine_id` 하나에 PC 실행기 행도 하나다.** 두 방향을 모두 본다.

- **키 → PC.** 키는 처음 `register`한 PC(`machine_id`)에 묶인다. 묶인 키를 다른 `machine_id`로 쓰면 409 `machine_mismatch` — 키가 새어도 다른 PC 실행기를 사칭할 수 없다.
- **PC → 키.** 같은 `machine_id`를 다른 키가 등록하면 409 `machine_already_registered`. **키가 혼자서 남의 PC 자리를 가져가지 못한다** — 관문은 운영자다. 옛 키의 「PC 묶음 풀기」(CON-11, C7 `POST /center-keys/{id}/unbind`)를 먼저 해야 한다.
- **묶음을 풀면 그 PC 실행기 자리도 놓인다.** 새 키가 같은 `machine_id`로 등록하면 그 `bot_ui_id`를 **이어받는다** — 배포·작업·결재·배치 결정이 그 id를 가리키고 있어서, 새 행을 만들면 CON-03에 유령 한 줄이 남고 C7 리소스의 PC 수가 부푼다. 이어받은 자리의 **상태는 비운다** (`status`·`current_run`·`queue`·`readiness`는 옛 키가 보고한 것이다 — 다음 하트비트가 채운다). 옛 키는 그 자리를 잃어, 그 키의 `heartbeat`는 409 `not_registered`가 된다.
- **이어받기는 행이 없는 키만 한다.** 이미 다른 PC로 등록된 키(묶음을 푼 뒤 아직 그 행을 가진 키)가 남의 놓인 자리를 가져가려 하면 409 `machine_already_registered` + `detail.reason`=`key_has_another_pc`. 어느 쪽 이력을 버릴지 Center가 짐작하지 않는다 — 그 PC에는 새 키를 발급한다.

`register`가 보는 순서와 결과:

| 부르는 키 | 보낸 `machine_id` | 결과 |
| --- | --- | --- |
| 묶인 키 | 묶인 PC와 다르다 | 409 `machine_mismatch` (`detail.bound_to`) |
| 아무 키 | **묶여 있는** 다른 키의 PC | 409 `machine_already_registered` (`reason`=`bound_elsewhere`) |
| 행이 **없는** 키 | 묶음이 **풀린** 키의 PC | 200 — 그 `bot_ui_id`를 이어받고 상태를 비운다 |
| 행이 **있는** 키 (묶음을 푼 키) | 묶음이 **풀린** 다른 키의 PC | 409 `machine_already_registered` (`reason`=`key_has_another_pc`) |
| 묶음을 푼 키 | 아무도 안 쓰는 PC | 200 — 그 키의 PC 실행기가 새 PC로 옮겨진다 (PC를 다시 설치한 경우) |
| 묶인 키 | 묶인 PC와 같다 | 200 — 같은 `bot_ui_id`, 정보만 갱신 (멱등) |
| 새 키 | 아무도 안 쓰는 PC | 200 — 새 `bot_ui_id` |

**거부된 등록은 키를 묶지 않는다.** 409로 막힌 키는 CON-11에서 「등록 전」으로 남는다 — 실패한 등록이 키를 묶어 버리면 운영자가 그 키의 묶음까지 풀어야 한다.

## 모델

### RegisterRequest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `machine_id` | str | ✓ | PC 고유값의 SHA-256 (Windows MachineGuid / Linux `/etc/machine-id`). 원값은 보내지 않는다 |
| `name` | str | ✓ | 표시 이름 (기본: PC 이름) |
| `os` | str | ✓ | 예: `windows-11-23H2`, `ubuntu-24.04` |
| `versions` | object | ✓ | `{bot_ui, core, build?}`. `bot_ui`는 **산출물의 판**이고 묶은 앱이면 빌드가 찍은 판이다 ([ADR-0067](../decisions/0067-build-stamp.md) — 태그면 `0.2.0`, 태그 없이 묶었으면 `0.1.0+g<커밋>`). `build`(`{commit, built_at}`)는 **묶은 것에서 돈다**는 표시이고 **없으면 묶지 않은 것**(소스·`uv sync`)에서 돈다 — 「모른다」가 아니다 |
| `runtimes` | object | | `{browsers: ["chromium-130"], desktop_backend: "uia", extensions: [{id, version, enabled, off}]}` — 설치된 확장 (C13) |
| `public_key` | str? | | X25519 공개키 (base64url). 보내면 Center가 이 PC의 키를 **회전해 준다** (§키 회전). 등록 요청으로 들어온 PC는 Center가 이미 안다 |

### RegisterResponse

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `bot_ui_id` | str | `bui_<hex8>` |
| `admin_keys` | AdminKey[] | 배포 서명 검증용 공개키 — Center 서명 키와 사람이 서명하던 때의 옛 Admin 키 (C2). 철회된 키도 `revoked_at`과 함께 |
| `heartbeat_interval_s` | int | 기본 30 |
| `server_time` | str | 시계 차이 확인용 |
| `key_expires_at` | str? | **이 키가 언제 만료되나** (C7). 없으면 만료가 없는 키다 — 「모른다」가 아니다 |

### HeartbeatRequest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `status` | str | ✓ | **열린 문자열.** 알려진 값: `idle` `running` `waiting_approval` `waiting_confirmation` `error` |
| `versions` | object | | 바뀌었을 때만 |
| `current_run` | CurrentRun \| null | ✓ | 실행 자리. **최대 1건** (ADR-0014) |
| `queue` | Queue | ✓ | 대기열 |
| `readiness` | Readiness[] | | 설치된 BPM 프로세스별 준비 상태 (바뀌었을 때만 보내도 됨) |
| `job_acks` | JobAck[] | | 이번 주기에 처리한 작업 |
| `deployment_results` | DeploymentResult[] | | 배포 적용 결정 (CON-03 「최근 배치 결정」) |
| `extensions` | `{id, version, definition_hash, enabled, off}`[] | | 설치된 확장. 바뀌었을 때만 (C13) |
| `approval_acks` | ApprovalAck[] | | 받아 간 결재 답 |
| `unsent_events` | int | | 아직 못 보낸 실행 이벤트 줄 수 (C3) |

| 모델 | 필드 |
| --- | --- |
| CurrentRun | `run_id`, `bpm_process_id`, `version`, `node_id`, `state`(열린 문자열: `running` `waiting_approval` `waiting_confirmation`), `started_at`, `source`(`job`\|`manual`\|`watch`\|`schedule`\|`message`, 예약: `delegation`), `job_id`? |
| Queue | `max`(int), `items`: `{queue_id, source, bpm_process_id, version?, job_id?, requested_at, expires_at?}`[] (순서대로) |
| Readiness | `bpm_process_id`, `version`, `ready`(bool), `missing_key_refs`(str[] — **늘 비어 있다**: 서비스 앱 키가 없어졌다, ADR-0102. 옛 Center가 읽어도 깨지지 않게 칸은 둔다), `blocked`(str[] — 사전 점검 막힘 코드. 열린 문자열이고 플랫폼 코드에 `deployment_withdrawn`(덮는 배포가 없다)·`deployment_expired`(덮는 배포의 기한이 지났다)가 있다 — C2 §검증 규칙) |
| JobAck | `job_id`, `result`(`queued`\|`started`\|`rejected`\|`expired`\|`cancelled`\|`cancel_refused`), `position`?(queued일 때 대기열 순번), `run_id`?(started일 때), `reason`?(rejected일 때: `queue_full` `no_deployment` `not_ready` `bot_ui_shutdown` `server_location` `cancelled_on_pc`(현장에서 대기열 항목을 취소함); `cancel_refused`일 때: `already_started`), `outputs?`(**PC 위임이 돌려주는 값** — 아래) |
| ApprovalAck | `request_id`, `accepted`(bool), `reason`? |
| DeploymentResult | `deployment_id`, `bpm_process_id`, `version`, `result`(`applied`\|`rejected`), `reason`?, `at` |

> 모든 값 목록(`status`, `state`, `source`, `result`, `reason`, `session` 등)은 **열린 문자열**이다. 위의 값은 알려진 값일 뿐이다 (README 원칙 10).

**`JobAck.outputs`는 위임만 쓴다** (C12 §PC 위임, [ADR-0062](../decisions/0062-pc-delegation.md)). 원칙 6의 **명시한 예외**라 좁게 쓴다. 서버 실행기도 C12 `job_acks[]`의 같은 칸을 같은 규칙으로 쓴다 ([ADR-0082](../decisions/0082-batch-start.md)).

- **그 BPM 프로세스가 선언한 `outputs`만** 싣는다 (C1 `outputs`) — 그 선언이 곧 「부르는 쪽이 받을 것」이고, 호출의 매핑(C14 `chk:call.output`)은 서버 그림에만 있어 PC는 모른다. 선언이 없으면 **아무것도 싣지 않는다**.
- **끝났을 때만** 싣는다 (`finished`·`failed`… — 작업 상태를 옮기는 ack가 아닌 것들). `started`에 실어 보내면 기다리는 서버 실행이 **빈 값으로 이어 간다**.
- **위임으로 받은 작업만**이다 (`requested_by`가 `server_bot:<run_id>`). 평범한 작업에 실어 보내도 **Center가 버린다** — 받을 쪽이 없다.
- Center는 받은 값을 그 서버 실행기에게 **하트비트로 내려 주고 ack가 오면 지운다** (C12).
- **현장에서 값이 올라오는 길은 파일 하나다** ([ADR-0062](../decisions/0062-pc-delegation.md) §4, ADR-0038과 같은 결) — 실행 변수를 아는 것은 PC 실행기의 **자식 프로세스**이고 올라오는 길은 실행 기록뿐인데 거기엔 업무 값이 없다 (원칙 6). 그래서 실행기가 끝날 때 `runs/<run_id>.outputs.json`에 **한 번** 쓰고(위임으로 받은 작업·**성공했을 때만**), PC 실행기가 거두며 **읽고 그 자리에서 지운다**. **PC 실행기는 내용을 짓지 않고 나르기만 한다** — 거르는 것은 실행기다. 그 파일은 C3가 아니라 실행 기록 전송이 건너뛴다 (제어·요청·현장 요청 파일과 같다).
- 그 PC 실행의 `run_started`에는 **`source: delegation`과 `parent_run_id`**가 있다 (C3) — 「이 작업이 위임인가」는 **작업의 `requested_by`** 하나가 말해 준다 (`server_bot:<run_id>`, Center가 짓는 예약값이라 지어낼 수 없다). 그 값을 PC 실행기 안에만 두고 **`QueueItem`에 칸을 더하지 않는다**(Center는 이미 안다).

### HeartbeatResponse

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `server_time` | str | |
| `next_heartbeat_s` | int | 다음 하트비트까지 (기본 30, Center가 부하에 따라 늘릴 수 있음) |
| `deployments` | Envelope[] | 이 PC 실행기의 **활성 배포 봉투 전체**를 저장된 JSON 그대로 (재직렬화하면 서명이 깨진다). 활성은 철회되지 않았고 패키지가 `approved`·`deprecated`인 배포다 (지원 종료는 새 배포만 막는다, C5). PC 실행기는 목록과 설치 상태를 맞춘다 — 받은 것은 설치하고, **목록에 덮는 봉투가 없는** 「Center 배포」 설치는 파일을 두고 「실행 불가」로 돌린다 (C2 §검증 규칙, ADR-0113). 빈 목록도 목록이다 — 맞추지 않는 것은 답이 없을 때뿐이다 |
| `admin_keys` | AdminKey[] | 바뀌었을 때만 (생략 = 그대로) |
| `jobs` | JobDispatch[] | 아직 ack되지 않은 작업. **ack가 올 때까지 매번 실린다** |
| `cancel_jobs` | str[] | 콘솔에서 취소된 작업 id. 대기열에 있으면 빼고 `cancelled`로 ack. **이미 시작했으면 멈추지 않고** `cancel_refused` + `already_started`로 ack. 작업은 Center에서 `accepted` 그대로 남는다 (C5, 실행 중 BPM 프로세스를 멈추는 것은 schema 1 범위 밖) |
| `approvals` | ApprovalDispatch[] | 답이 정해졌고 아직 ack되지 않은 결재 (C6) |
| `disabled` | bool | true면 PC 실행기는 새 작업·배포를 받지 않는다. 하트비트는 계속 받으므로 실행 중 BPM 프로세스와 대기열은 콘솔에 계속 보인다 (CON-03 「비활성화」) |
| `rotated_key` | `{sealed_key, expires_at}`? | 만료 14일 전부터 새 키 (§키 회전). 새 키로 첫 요청이 올 때까지 주기마다 싣는다 |
| `key_expires_at` | str? | 등록 응답과 같은 값. **주기마다 싣는다** — 운영자가 키 기간을 늘려 주면 다음 주기에 바로 안다 (「생략 = 그대로」로 두면 늘어난 것을 모른다) |

**키 만료일은 Center만 안다** — 그래서 내려 준다. 받는 쪽은 그것으로 BUI-05 「Center API 키 만료 임박」을 띄우고(**회전을 받는 PC는 7일 전까지 새 키가 오지 않았을 때만** — Center에 닿지 못했다는 뜻이다. 회전하지 않는 PC는 14일 전부터. 둘 다 **하루 한 번** — 주기마다 띄우면 30초에 한 번 같은 말을 한다), 이미 만료된 키는 **알리지 않는다**(그때는 Center가 거부하고 「키 거부」가 말한다). 값이 **없는 것은 「만료가 없다」는 뜻**이고 「모른다」가 아니다 — Center는 만료 없는 키도 발급한다 (C7).

| 모델 | 필드 |
| --- | --- |
| JobDispatch | `job_id`, `bpm_process_id`, `version`?(없으면 배포된 버전), `inputs`(object), `requested_by`(사람, 예약: `server_bot:<run_id>` — PC 위임), `requested_at`, `expires_at`?, `note`, `virtual_worker`?(`{id, name, supervisors}` — **서버 작업에만** 실린다, C12. PC 실행기에는 오지 않고 PC 실행기는 읽지 않는다 — PC 자식에 나르는 것은 미정이다, [ADR-0099](../decisions/0099-input-value-source.md) §3) |
| ApprovalDispatch | `request_id`, `state`(`answered`\|`expired`\|`withdrawn`, C6), `answer`, `answered_by`, `answered_at`, `answered_via`?(대리 답이면 키 이름 — C6, [ADR-0081](../decisions/0081-answering-on-behalf.md)) |

### 작업 상태 흐름 (Center 쪽, CON-05)

```
pending ──(하트비트 응답에 실림)──▶ dispatched ──ack queued──▶ queued ──ack started──▶ accepted(run_id)
   │                                   │                        │
   └─ 콘솔 취소 ─▶ cancelled             ├─ ack rejected ─▶ rejected(reason)
                                       └─ ack expired / 만료 ─▶ expired
```

- `queued` = 화면 표기 「대기열」. PC 실행기 대기열에 들어갔다는 뜻.
- 실행 자리가 비어 있으면 PC 실행기는 `queued`를 건너뛰고 바로 `started`를 보내도 된다.
- 대기열이 가득 차면 `rejected` + `queue_full` (ADR-0014).
- `run_location=server`인 BPM 프로세스의 작업이 PC 실행기에 오면 `rejected` + `server_location` (Center 버그 방어).

### 작업이 사라지지 않게 (맞추기 규칙)

- **PC 실행기:** 받은 `job_id`와 아직 Center가 확인하지 않은 ack를 디스크에 저장한다. 이미 받은(대기열에 있거나, 실행했거나, 실행 중인) `job_id`가 다시 오면 무시하고 마지막 ack를 다시 보낸다. 대기열 자체도 디스크에 저장해, PC 실행기를 다시 켜면 이어 간다.
- **Center:** 받은 `deployment_results`를 **쌓아 둔다** (CON-03 「최근 배치 결정」, C5 `BotUiInfo.deployment_results`). 하트비트 한 주기만 올라오는 값이라 흘려보내면 「왜 설치가 안 됐나」가 영영 남지 않는다. 같은 `(deployment_id, at)`은 **한 번만** 반영한다 (PC 실행기가 다시 보내도 쌓이지 않게).
- **Center:** 하트비트마다 자기 기록의 `queued`·`accepted`(실행 중) 작업을 `queue.items`·`current_run`과 비교한다. 두 번 연속 하트비트에서 보이지 않고 ack도 없으면 `rejected` + `bot_ui_lost`로 바꾼다 (PC 실행기가 비정상 종료로 대기열을 잃은 경우). 실행 결과는 C3 `run_finished`로 따로 확정된다.

## 예시

하트비트 요청:

```json
{
  "schema": 1,
  "status": "running",
  "current_run": {"run_id": "run_20261001_101500_a1b2c3", "bpm_process_id": "legal.contract-seal",
                  "version": "2.1.0", "node_id": "Task_check_original", "state": "running",
                  "started_at": "2026-10-01T10:15:00+09:00", "source": "job", "job_id": "job_8f3e"},
  "queue": {"max": 20, "items": [
    {"queue_id": "q_01", "source": "job", "bpm_process_id": "legal.contract-seal", "job_id": "job_9a10",
     "requested_at": "2026-10-01T10:16:05+09:00", "expires_at": "2026-10-01T18:00:00+09:00"}]},
  "readiness": [{"bpm_process_id": "legal.contract-seal", "version": "2.1.0", "ready": true,
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

| 상태 코드 | 언제 | PC 실행기가 할 일 |
| --- | --- | --- |
| 401 | 키 없음·틀림 | 트레이 「등록 전」, BUI-03 「키가 거부되었습니다」. 실행 중 BPM 프로세스는 계속, 기록은 쌓음 |
| 403 | 키 폐기·만료 (`detail.code`=`key_revoked`\|`key_expired`), 키 종류가 다름 (`wrong_key_type`) | 알림 「Center가 이 PC의 키를 거부했습니다」. 하트비트 간격을 5분으로 늘림. 실행 중 BPM 프로세스는 끝까지, 기록은 쌓음 |
| 409 | 키가 다른 PC에 묶여 있음 (`machine_mismatch`, `detail.bound_to`) | BUI-03에 「이 키는 <PC>에서 쓰고 있습니다」. 트레이 「등록 전」 |
| 409 | 이 PC가 이미 다른 키로 등록돼 있음 (`machine_already_registered`, `detail.reason`·`bot_ui_id`·`name`) | BUI-03에 Center가 준 말 그대로. 트레이 「등록 전」. **다시 시도해도 같다** — 등록 요청을 보내 승인받으면 그 자리를 이어받는다 (자동화 키라면 운영자가 옛 키의 묶음을 풀어야 한다) |
| 422 | 등록 요청의 공개키가 틀림 (`public_key_invalid`) | 키 쌍을 새로 만들어 다시 요청한다 |
| 429 | 등록 요청이 너무 잦음 (`enroll_rate_limited`) / 대기 줄이 가득 참 (`enroll_queue_full`) | `Retry-After`만큼 기다렸다 다시 요청한다. BUI-03에 「Center가 지금 등록 요청을 받지 않습니다」 |
| 409 | 등록하기 전에 `heartbeat` (`not_registered`) | `register`를 먼저 부른다 (자리를 다른 키가 이어받은 경우도 이 코드다) |
| 422 | 필수 필드 누락, 더 높은 `schema` | PC 실행기 업데이트 필요 안내 |
| 5xx / 연결 실패 | | 트레이 「연결 끊김」. 30초 간격 재시도 (최대 5분까지 늘림). 실행·대기열은 계속 |

## 호환 규칙

- 모든 값 목록(`status`, `CurrentRun.state`·`source`, `Queue.items[].source`, `JobAck.result`·`reason`, `DeploymentResult.result`)은 **열린 문자열**이다. Center는 모르는 값도 저장하고 화면에 그대로 보인다. 모르는 값 하나로 하트비트 전체를 422로 거부하지 않는다 (프로토타입 결함).
- 모르는 선택 필드는 무시한다. 더 높은 `schema`는 거부한다.
- Center는 `current_run`이 2건 이상 오는 경우를 받지 않는다 — 모델이 단일 객체라 표현할 수 없다 (ADR-0014를 계약으로 강제).

## 프로토타입과 달라진 것

| 프로토타입 | 여기 |
| --- | --- |
| `POST /api/bots/enroll` + 공용 enroll 토큰, `bot_id`를 경로로 | `register` + PC 실행기별 Center API 키, 신원은 키로 |
| `current_runs[]` (여러 건) | `current_run` 1건 + `queue` |
| 준비 상태 없음 | `readiness` |
| 작업 `pending/dispatched/accepted/rejected` | `queued`·`expired`·`cancelled` 추가, 취소 지시 `cancel_jobs` |
| 상태 닫힌 목록 → 422 | 열린 문자열 |

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-31 | 1 | 하트비트의 **`worker`(WorkerState)**·`versions.worker`·상태 값 `selector_registration`을 걷었다 — Worker 프로세스를 띄우는 확장이 없다. 옛 PC 실행기가 보내도 받는 쪽은 모르는 칸·모르는 값으로 받아 두므로(원칙 3·10) **판을 올리지 않는다**. 호출 토큰은 PC 실행기 메모리에만 있다 | [0114](../decisions/0114-remove-ui-automation.md) |
| 2026-10-31 | 1 | `deployments`의 「맞춘다」를 풀어 적었다 — 덮는 봉투가 없는 설치는 「실행 불가」, `readiness.blocked`에 `deployment_withdrawn`·`deployment_expired`. 활성에 `deprecated`가 든다(전에도 계약은 그랬고 Center가 어겼다, 09-gaps §3-22). 칸은 그대로다 | [0113](../decisions/0113-field-follows-withdrawn-deployments.md) |
| 2026-10-30 | 1 | `source: schedule` — Center의 일정이 만든 작업(`requested_by` `timer:<식>`)을 대기열에 넣을 때 쓴다(C5 §일정). 값은 처음부터 있었다 | [0110](../decisions/0110-center-keeps-the-schedule.md) |
| 2026-10-29 | 1 | §서비스 앱 키 전달을 걷었다(`service_keys[]`·`drop_service_keys[]`·`service_key_acks[]`), §호출 토큰(`POST /call-tokens`), `missing_key_refs`는 늘 빈다. 선택 칸을 걷은 것이라 판을 올리지 않는다 | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-26 | 1 | `JobDispatch.virtual_worker?`를 적었다 — 모델이 C12와 같아 보일 뿐 Bot UI에는 실리지 않는다 | [0099](../decisions/0099-input-value-source.md) |
| 2026-10-25 | 1 | §서비스 앱 키 전달 — 응답 `service_keys[]`·`drop_service_keys[]`, 요청 `service_key_acks[]`, `missing_key_refs`의 뜻이 「받지 못함」으로. 선택 칸이라 옛 Bot UI는 그대로 돈다 | [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 2026-10-25 | 1 | **등록 요청과 승인** — `POST/GET …/enroll`(인증 없음, 요청 코드·봉함), `RegisterRequest.public_key?`, `HeartbeatResponse.rotated_key?`, 오류 `public_key_invalid`·`enroll_rate_limited`·`enroll_queue_full`. 선택 칸·새 경로라 옛 Bot UI는 그대로 돈다 | [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md) |
| 2026-10-20 | 1 | `ApprovalDispatch.answered_via?` — 대리 답이면 그 키 이름이 실행하는 쪽까지 내려가 C3 `human_answered`에 남는다 | [0081](../decisions/0081-answering-on-behalf.md) |
| 2026-10-17 | 1 | **`versions.build`를 더했다** (`{commit, built_at}`, 선택) — 묶은 산출물에서 도는지와 어느 커밋인지. `bot_ui`는 빌드가 찍은 판이다(묶은 앱이 `0.0.0`을 올리던 흠을 고쳤다). 선택 칸이라 옛 Bot UI는 그대로 읽힌다 | [0067](../decisions/0067-build-stamp.md) |
| 2026-10-15 | 1 | **현장에서 값을 올리는 쪽이 생겼다** — 실행기가 끝날 때 `runs/<run_id>.outputs.json`에 쓰고(위임·성공만) Bot UI가 거두며 **읽고 그 자리에서 지운다**. 「이 작업이 위임인가」는 **`requested_by`** 하나로 가르고(`server_bot:<run_id>`), 그 실행의 `run_started`에 `source: delegation`·`parent_run_id`가 붙는다. 형식은 그대로다 | [0062](../decisions/0062-pc-delegation.md) |
| 2026-10-15 | 1 | `JobAck`에 선택 칸 **`outputs`**를 더했다 — **PC 위임이 돌려주는 값**이다 (원칙 6의 명시한 예외: 선언한 `outputs`만·끝난 ack만·위임 작업만). 선택 칸이라 **옛 Bot UI는 그대로 돈다** | [0062](../decisions/0062-pc-delegation.md) |
| 2026-10-14 | 1 | **Bot UI의 멱등 기억도 서버 실행기와 같은 규칙이다** ([ADR-0057](../decisions/0057-shared-seen-map.md)·[0056](../decisions/0056-bounded-seen-maps.md)) — 이미 본 작업의 마지막 ack는 **닿은 뒤 두 주기**에 잊고 **닿지 않은 ack는 버리지 않는다**. 전에는 넣은 순서로 잘라, 한 주기에 상한을 넘게 받으면 올리지 못한 ack가 버려지고 다시 내려온 작업이 「처음 본 것」이 되어 **대기열에 두 번** 들어갈 수 있었다. 계약 본문은 그대로다 (받는 쪽 규칙) | 0057 |
| 2026-10-11 | 1 | 등록·하트비트 응답에 **`key_expires_at`**을 더했다 — 키 만료일은 Center만 알아 BUI-05 「Center API 키 만료 임박」이 띄울 값이 없었다 (09-gaps §4-8). 선택 칸이고 **주기마다 싣는다**(늘어난 기간을 바로 알게). 없으면 「만료 없음」이다 | 0013 |
| 2026-10-01 | 1 | 초안 | 0012, 0013, 0014 |
| 2026-10-01 | 1 | 검토 반영: 맞추기 규칙(`bot_ui_lost`), 시작한 작업 취소 거절, `disabled`는 200으로만, 모든 값 목록 열린 문자열, `deployment_results`, `wrong_key_type`, PC 묶음 풀기 | — |
| 2026-10-01 | 1 | C5 검토 반영: 시작된 작업의 취소 거절은 `cancel_refused`(작업은 `accepted` 유지), 예시 봉투를 C2 필드로 | — |
| 2026-10-01 | 1 | 확장 반영: `runtimes.extensions` | 0018 |
| 2026-10-01 | 1 | 확장 검토 반영: 하트비트 `extensions` | 0018 |
| 2026-10-01 | 1 | 화면 검토 반영: Worker `off`·`reserved_for`, 현장 취소 `cancelled_on_pc` | — |
| 2026-10-06 | 1 | Center가 `deployment_results`를 쌓아 둔다고 적었다 (멱등은 `(deployment_id, at)`) — CON-03을 붙이다 Center가 그것을 버리고 있는 것이 드러났다 | — |
| 2026-10-10 | 1 | `ExtensionState.off`를 더했다 — 「사람이 껐다」와 「흠이 있다」가 `enabled` 한 칸에 뭉쳐 있어 CON-03·CON-07이 「꺼짐」과 「호환 안 됨」을 가르지 못했다 ([ADR-0043](../decisions/0043-turned-off-extensions.md)) | 0043 |
| 2026-10-08 | 1 | 키 묶기를 **두 방향**으로 적었다 (`machine_already_registered`·놓인 자리 이어받기) — 키 → PC만 보던 탓에 같은 PC에 두 번째 키를 발급하면 Bot UI 행이 둘 생겨 CON-03·C7 집계가 부풀고 작업이 조용한 쪽으로 갈 수 있었다. 409 코드 이름도 코드에 맞췄다 (`key_bound_elsewhere` → `machine_mismatch`) | — |

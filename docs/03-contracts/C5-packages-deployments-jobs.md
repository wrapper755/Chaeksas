# C5. Center API: 패키지·배포·작업

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Studio·Admin·Center 콘솔·외부 시스템·Bot UI·서버 실행기 ↔ Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/center_api.py` (import `chaeksas.contracts.center_api`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c5-package-info.json`](../../packages/contracts/schemas/c5-package-info.json) · [`c5-deployment-info.json`](../../packages/contracts/schemas/c5-deployment-info.json) · [`c5-job-create-request.json`](../../packages/contracts/schemas/c5-job-create-request.json) · [`c5-job-info.json`](../../packages/contracts/schemas/c5-job-info.json) · [`c5-error-body.json`](../../packages/contracts/schemas/c5-error-body.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0013](../decisions/0013-api-keys.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0017](../decisions/0017-web-nextjs-design-system.md) |
| 관련 화면 | STU-01(올리기), CON-02·05·06·11·12, ADM |

## 목적

Center 쪽에서 BPM 프로세스가 실행되기까지의 흐름을 정한다.

1. 패키지를 올린다 (후보).
2. 승인 서명을 붙인다.
3. 배포 서명으로 실행할 대상에 배치한다.
4. 작업 지시로 실행시킨다.

실행하는 쪽(Bot UI·서버 실행기)은 이 API로 패키지를 내려받는다. 배포와 작업은 하트비트 응답으로 받는다 (C4·C12).

> 상태: **패키지 승인·철회, Admin 키, 배포**(`POST/DELETE/GET /deployments`)가 돈다 — 하트비트가 활성 배포 봉투와 Admin 키를 내려 주고 Bot UI가 설치한다 (C2 V1~V7). **작업 지시(`/jobs`)도 돈다** — 만들기·목록·하나·취소와 하트비트의 `jobs`·`cancel_jobs`·`job_acks`, 맞추기 규칙(`bot_ui_lost`)까지. 서버 실행기 대상은 422 `server_runner_not_available`이다 (M7). 다음은 콘솔 화면(CON-05)이다.

## 전송 공통

- 기본 경로는 `/api/v1`. 본문은 JSON이고, 업로드만 multipart다.
- 목록 요청은 `limit`(기본 100, 최대 1000)과 `offset`을 쓴다. 시각은 시간대를 포함한 ISO 8601이다.
- 오류 본문: `{"code": "...", "message": "...", "detail": {...}}` (C11과 같은 형식).
- **행위자:** `requested_by`, `answered_by`, `uploaded_by`는 본문에서 받지 않는다. 키로 부르면 키 이름으로 채운다. 콘솔에서 부르면 콘솔 서버(BFF)가 로그인 세션의 사용자 이름을 `X-CHK-Actor` 헤더로 실어 보낸다. 이 헤더는 관리자·읽기 토큰으로 부를 때만 믿는다.
  - **값은 UTF-8을 퍼센트 인코딩해서** 넣는다 (`운영자 김` → `%EC%9A%B4%EC%98%81%EC%9E%90%20%EA%B9%80`). HTTP 헤더 값에는 ASCII 밖의 글자를 넣을 수 없어서(보내는 쪽 HTTP 라이브러리가 거부한다), 한글 이름을 그대로 실으면 요청 자체가 나가지 않는다. 받는 쪽은 디코딩하고, 디코딩이 실패하면 받은 문자열을 그대로 쓴다.

### 인증

| 인증 수단 | 누가 쓰나 | 어디까지 쓸 수 있나 |
| --- | --- | --- |
| 읽기 토큰 | 콘솔 「보기 전용」 | **GET만** |
| 관리자 토큰 | 콘솔 「관리자」 모드, Admin 명령 | 쓰기 전부. 단 서명이 필요한 동작은 봉투도 함께 (C2) |
| Center API 키 — Studio용 | Studio | 패키지 업로드, 패키지·리소스 읽기 |
| Center API 키 — Bot UI용 / 서버 실행기용 | 실행하는 쪽 | **자기에게 배포된** BPM 프로세스 패키지와, 그 패키지의 `requires.toolpacks`만 내려받기 |
| Center API 키 — 연동용 (신규, CON-11) | 외부 시스템 | 작업 만들기(`POST /jobs`)와 자기가 만든 작업 읽기·취소 |

### 엔드포인트별 권한

| 엔드포인트 | 읽기 토큰 | 관리자 토큰 | Studio 키 | Bot UI·서버 실행기 키 | 연동용 키 |
| --- | --- | --- | --- | --- | --- |
| `GET /packages…` (목록·정보) | ✓ | ✓ | ✓ | — | — |
| `GET /packages/{id}/{v}` (내려받기) | — | ✓ | ✓ | 자기 배포분만 | — |
| `POST /packages` | — | ✓ | ✓ | — | — |
| `PUT …/signature`, `POST …/revoke` (봉투) | — | ✓ | — | — | — |
| `PUT …/status` (지원 종료), `DELETE /packages/…` | — | ✓ | — | — | — |
| `POST/DELETE /deployments` (봉투), `POST/DELETE /admin-keys` (봉투) | — | ✓ | — | — | — |
| `GET /deployments`, `GET /admin-keys` | ✓ | ✓ | — | — | — |
| `GET /resources…` (C7·C13, 확장 정의 포함) | ✓ | ✓ | ✓ | ✓ | — |
| `POST/PUT/DELETE /resources/service-apps…`, `POST /resources/refresh` | — | ✓ | — | — | — |
| `POST/DELETE /resources/extensions` (C2 `extension` 봉투) | — | ✓ | — | — | — |
| `GET /server-runners` | ✓ | ✓ | — | — | — |
| `POST /server-runners/{id}/pause·resume·mark-lost` (C12) | — | ✓ | — | — | — |
| `GET /bot-uis…` (CON-03), `POST /bot-uis/{id}/disable·enable` | GET만 ✓ | ✓ | — | — | — |
| `POST /jobs` | — | ✓ | — | — | ✓ |
| `GET /jobs…` | ✓ | ✓ | — | — | 자기 것만 |
| `DELETE /jobs/{id}` | — | ✓ | — | — | 자기 것만 |

## 패키지

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /packages` (multipart `file`) | 업로드. Center가 zip 안전 검사(경로 탈출·크기), C1 검사 R1~R7, 해시 재계산을 한다 | 201 새로 / 200 같은 id·버전·해시 (재시도) |
| `GET /packages?kind=&status=&id=` | 목록 | 200 PackageInfo[] |
| `GET /packages/{id}/{version}/info` | 정보 (매니페스트, 상태, 사전 점검 요약, 누락 리소스) | 200 |
| `GET /packages/{id}/{version}` | 내려받기. 승인된 패키지면 zip에 `SIGNATURE`를 넣어 준다 (C2). 헤더 `X-Content-Hash` | 200 zip / 410 철회됨 |
| `PUT /packages/{id}/{version}/signature` | 승인 봉투(C2 `package`). 상태가 `approved`가 된다 | 200 |
| `POST /packages/{id}/{version}/revoke` | 승인 철회 봉투(C2 `package_revoke`). 상태가 `revoked`가 되고 배포가 모두 무효가 된다 | 200 |
| `PUT /packages/{id}/{version}/status` `{status: "deprecated"}` | 지원 종료 표시. 새 배포를 막는다. 서명이 필요 없다 (실행을 허용하는 쪽이 아니라 막는 쪽이라서) | 200 |
| `GET /packages/{id}/{version}/dependents` | 이 패키지를 `requires`로 쓰는 패키지 | 200 |
| `DELETE /packages/{id}/{version}` | 삭제. 배포나 다른 패키지가 참조하면 409 | 204 |

PackageInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `id`, `version`, `kind`, `name` | |
| `run_location` | `bpm_process`에만 있다 |
| `status` | `candidate` / `approved` / `deprecated` / `revoked` (열린 문자열) |
| `content_hash` | |
| `uploaded_by`, `uploaded_at` | |
| `signed_by`?, `signed_at`? | 승인 서명 |
| `preflight` | `{warnings, blocked}` |
| `manifest` | C1 매니페스트 |
| `missing_resources` | `[{type: toolpack \| ui_page \| service_app \| operation, id, reason}]`. 읽을 때 C7과 대조해 계산한다 |

## 배포

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /deployments` (본문 = C2 `deployment` 봉투) | 배포. 아래 항목을 검사한다 | 201 / 200 같은 봉투 재전송 |
| `DELETE /deployments/{id}` (본문 = C2 `revoke` 봉투) | 철회. 행은 지우지 않고 `revoked_at`을 찍는다 | 200 |
| `GET /deployments?target_type=&target_id=&bpm_process_id=&active=` | 목록 | 200 DeploymentInfo[] |

배포할 때 Center가 검사하는 것:

- 서명 (C2 V1~V5a). `not_before`가 미래인 예약 배포도 받는다.
- 패키지가 `approved`이고 `deprecated`가 아니다.
- 봉투의 해시가 패키지와 같다.
- 대상이 존재한다.
- `target.type`이 패키지의 `run_location`과 맞다.
- 서버 배포면 C1 R8을 통과한다.

DeploymentInfo 필드: `deployment_id`, `target{type,id}`, `bpm_process_id`, `version`, `content_hash`, `max_concurrency`?, `signed_by`, `signed_at`, `not_before`?, `expires_at`?, `revoked_at`?, `last_result`?. `last_result`는 C4 `deployment_results`의 마지막 값이다.

- **M6까지:** `target.type=server_runner` 배포는 422 `server_runner_not_available` (서버 실행은 M7부터, ADR-0016).

## 작업 (job)

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /jobs` | 작업 만들기 | 201 JobInfo / 200 같은 `idempotency_key` |
| `GET /jobs?state=&target_type=&target_id=&bpm_process_id=` | 목록 | 200 |
| `GET /jobs/{id}` | 하나 (연결된 실행 상태 포함) | 200 |
| `DELETE /jobs/{id}` | 취소 (아래 표) | 200 / 202 / 409 |

JobCreateRequest:

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `bpm_process_id` | str | ✓ | |
| `version` | str | | 비우면 대상에 배포된 버전. 같은 대상에 그 Bot의 활성 배포가 둘 이상이면 422 `version_ambiguous` |
| `target` | object | ✓ | `{type: "bot_ui", id}` 또는 `{type: "server_runner", id?}`. 서버 실행기 `id`를 비우거나 `"*"`면 Center가 고른다 |
| `inputs` | object | ✓ | 진입 정의가 기대하는 입력. JSON 객체가 아니면 422 |
| `expires_at` | str | | 이 시각까지 시작하지 못하면 `expired` |
| `note` | str | | 500자 이내 |
| `idempotency_key` | str | | 부른 쪽 키(또는 행위자)마다 따로 7일간 기억한다. 같은 키에 같은 본문이면 기존 작업(200), 다른 본문이면 409 `idempotency_conflict` |

JobInfo는 위 필드에 다음을 더한다.

| 필드 | 뜻 |
| --- | --- |
| `job_id` | `job_<hex8>` |
| `requested_by` | 사람 이름, 키 이름, 또는 예약값 `server_bot:<run_id>` (PC 위임 제안) |
| `requested_at` | |
| `state`, `state_reason`? | 아래 상태 표 |
| `cancel_requested` | bool |
| `cancel_result`? | `cancelled` 또는 `refused_already_started` |
| `queue_position`? | PC 대기열 순번 (C4) |
| `dispatched_at`?, `run_id`?, `run_status`? | |

### 작업 상태 (열린 문자열, 알려진 값)

| state | 화면 표기 (CON-05) | 뜻 |
| --- | --- | --- |
| `pending` | 대기 | Center가 아직 전달하지 않음 |
| `dispatched` | 전달됨 | 하트비트 응답에 실었고 ack 전 |
| `queued` | 대기열 | PC: Bot UI 대기열에 들어감. 서버: 동시 실행 상한 때문에 Center 대기열에서 기다림 |
| `accepted` | 수락 | 실행 시작 (`run_id` 있음) |
| `rejected` | 거절 | 이유는 `state_reason` (아래) |
| `expired` | 만료 | `expires_at`까지 시작하지 못함 |
| `cancelled` | 취소됨 | 취소 완료 |

`rejected`의 `state_reason`: `queue_full`, `no_deployment`, `not_ready`, `bot_ui_shutdown`, `bot_ui_lost`, `server_location`, `cancelled_on_pc`(현장 Bot UI에서 취소).
`queued`(서버)의 `state_reason`: `global_limit`(서버 실행기 빈자리 없음), `per_bot_limit`(BPM 프로세스별 상한), `paused` (C12).

### 취소

| 지금 상태 | 응답 | 결과 |
| --- | --- | --- |
| `pending` | 200 | 바로 `cancelled` |
| `dispatched` / `queued` | **202** `cancel_requested: true` | 다음 하트비트에 Bot UI가 빼내고 `cancelled`로 ack하면 `cancelled`. 그사이 실행을 시작했으면 Bot UI가 `cancel_refused`로 ack하고, 작업은 **`accepted` 그대로**, `cancel_result: refused_already_started` |
| `accepted` | 409 `already_started` | 실행 중인 Bot을 멈추는 것은 schema 1 범위 밖 |
| 그 밖 | 409 `not_cancellable` | |

- 실행의 성공·실패는 작업 상태가 아니다. C3 `run_finished`로 정해지고 `run_status`에 보인다.

## Bot UI 현황 (CON-03)

콘솔이 PC마다 하나인 Bot UI의 상태를 본다. 값은 **Bot UI가 하트비트로 보고한 그대로**이고 (C4),
Center는 온라인 판정과 키 정보만 더한다. 보기 전용이다 — 대기열 항목을 취소하는 것은 작업
쪽(CON-05)이다.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /bot-uis` | 읽기·관리자 토큰 | 목록 (BotUiInfo[]) |
| `POST /bot-uis/{bot_ui_id}/disable` | 관리자 토큰 | 새 작업·배포를 보내지 않는다. **하트비트는 계속 받는다** (C4 `disabled`) |
| `POST /bot-uis/{bot_ui_id}/enable` | 관리자 토큰 | 되돌리기 |

BotUiInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `bot_ui_id` | `bui_<hex8>` |
| `name`, `os`, `machine_id` | 등록할 때 받은 것 (C4 `register`) |
| `versions` | C4와 같은 모양 (등록할 때 반드시 받으므로 늘 있다). `runtimes`는 선택 |
| `registered_at`, `last_seen_at` | 처음 등록·마지막 하트비트 |
| `online` | 마지막 하트비트가 **90초 이내**인가 (C4 「온라인 판정」). 오프라인이면 화면이 「마지막 보고 <시각> 기준」을 붙인다 (U8) |
| `disabled` | 비활성화됨 |
| `status`, `current_run`, `queue`, `worker`, `readiness`, `extensions` | 마지막 하트비트의 내용 (C4). 아직 하트비트가 없으면 비어 있다 |
| `key` | 그 Bot UI가 쓰는 Center API 키 `{prefix, expires_at, state}` — **원문·해시는 주지 않는다** (C7) |

## 오류

| 상태 코드 | `code` | 언제 |
| --- | --- | --- |
| 400 | `bad_zip` / `no_manifest` / `bad_envelope` | 형식 오류 |
| 401 / 403 | `key_invalid` / `forbidden` | 인증 실패, 권한 밖 (예: Bot UI가 자기에게 배포되지 않은 패키지를 요청) |
| 404 | `not_found` | |
| 409 | `version_exists` | 같은 버전인데 내용이 다름 |
| 409 | `in_use` | 참조 중인 패키지 삭제 |
| 409 | `already_started` / `not_cancellable` | 취소할 수 없는 작업 |
| 409 | `deployment_conflict` / `deployment_revoked` | C2 |
| 409 | `idempotency_conflict` | 같은 `idempotency_key`에 다른 본문 |
| 410 | `revoked` | 철회된 패키지 내려받기 |
| 413 | `too_large` | 패키지 50 MB 초과 |
| 422 | C1 규칙 코드, `not_approved`, `deprecated`, `hash_mismatch`, `target_mismatch`, `server_runner_not_available`, `no_deployment`, `version_ambiguous`, `inputs_not_object` | 검사 실패 |

## 호환 규칙

- 상태·사유 값은 열린 문자열이다 (README 원칙 10). 콘솔은 모르는 값을 그대로 보인다.
- 모르는 요청 필드는 무시한다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 | 0013~0016 |
| 2026-10-03 | 1 | `X-CHK-Actor`는 UTF-8 퍼센트 인코딩으로 보낸다 — 한글 이름을 그대로 실으면 HTTP 헤더에 넣을 수 없어 요청이 나가지 않는다 (콘솔을 붙이다 드러났다) | 0017 |
| 2026-10-03 | 1 | `GET /bot-uis`(CON-03)의 응답 모델 `BotUiInfo`를 적었다 — 엔드포인트만 권한표에 있고 모양이 없어서 콘솔이 타입을 손으로 쓸 수밖에 없었다 | 0017 |
| 2026-10-01 | 1 | 검토 반영: 엔드포인트별 권한표(읽기 토큰은 GET만, 연동용 키 신설), 행위자는 키·`X-CHK-Actor`에서, 취소는 202와 `cancel_result`(시작된 작업은 `accepted` 유지), 대상 이름 `server_runner`로 통일, `idempotency_key` 범위·충돌, `version_ambiguous`, 패키지 철회·지원 종료 엔드포인트, 툴팩만 따로 내려받기 | 0017 |
| 2026-10-01 | 1 | 확장 반영: 리소스·확장 경로 권한 | 0018 |
| 2026-10-01 | 1 | 화면 검토 반영: `cancelled_on_pc`, 서버 실행기·Bot UI 운영 경로 권한 | — |

# C5. Center API: 패키지·배포·작업

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-10, [09-gaps](../09-gaps.md) §1 대조 — 지원 종료·참조·삭제까지) — **§등록 승인도 돈다** (2026-10-25, [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md)). **§Studio 등록 요청은 초안이다** ([0093](../decisions/0093-studio-is-let-in-by-approval.md), 코드 아직 — 지금 코드는 계정 로그인) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Studio·Center 콘솔·외부 시스템·Bot UI·서버 실행기 ↔ Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/center_api.py`, `…/accounts.py` (import `chaeksas.contracts.center_api`·`chaeksas.contracts.accounts`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c5-package-info.json`](../../packages/contracts/schemas/c5-package-info.json) · [`c5-dependent-info.json`](../../packages/contracts/schemas/c5-dependent-info.json) · [`c5-deployment-info.json`](../../packages/contracts/schemas/c5-deployment-info.json) · [`c5-job-create-request.json`](../../packages/contracts/schemas/c5-job-create-request.json) · [`c5-job-info.json`](../../packages/contracts/schemas/c5-job-info.json) · [`c5-deployment-request.json`](../../packages/contracts/schemas/c5-deployment-request.json) · [`c5-login-request.json`](../../packages/contracts/schemas/c5-login-request.json) · [`c5-session-info.json`](../../packages/contracts/schemas/c5-session-info.json) · [`c5-account-info.json`](../../packages/contracts/schemas/c5-account-info.json) · [`c5-error-body.json`](../../packages/contracts/schemas/c5-error-body.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0013](../decisions/0013-api-keys.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0017](../decisions/0017-web-nextjs-design-system.md), [0046](../decisions/0046-no-wildcard-pc-deployment.md), [0047](../decisions/0047-one-deployment-gate.md), [0049](../decisions/0049-deployment-target-must-exist.md), [0090](../decisions/0090-center-admin-accounts.md), [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md) |
| 관련 화면 | STU-01(올리기), CON-00(로그인)·02·03·05·06·11·12·14·15 |

## 목적

Center 쪽에서 BPM 프로세스가 실행되기까지의 흐름을 정한다.

1. 패키지를 올린다 (후보).
2. 관리자가 승인한다 — Center가 승인 봉투에 서명한다 (C2).
3. 관리자가 실행할 대상에 배포한다 — Center가 배포 봉투에 서명한다.
4. 작업 지시로 실행시킨다.

실행하는 쪽(Bot UI·서버 실행기)은 이 API로 패키지를 내려받는다. 배포와 작업은 하트비트 응답으로 받는다 (C4·C12).

> 상태: **돈다 — 남은 기능이 없다.** **관리자 계정·로그인 세션**(ADR-0090), 패키지 승인·철회·지원 종료(`PUT …/status`), 배포(`POST/DELETE/GET /deployments`)가 돈다 — 승인·배포 봉투는 Center가 서명하고, 하트비트가 활성 배포 봉투와 믿는 키(`admin_keys`)를 내려 주고 Bot UI가 설치한다 (C2 V1~V7). **작업 지시(`/jobs`)도 돈다** — 만들기·목록·하나·취소와 하트비트의 `jobs`·`cancel_jobs`·`job_acks`, 맞추기 규칙(`bot_ui_lost`)까지. **참조·삭제(`GET …/dependents`·`DELETE /packages/…`)도 돈다** — CON-06이 읽고 지운다. 콘솔 화면(CON-05·CON-06)도 돈다. 서버 실행기 대상은 422 `server_runner_not_available`이다 (M7).

## 전송 공통

- 기본 경로는 `/api/v1`. 본문은 JSON이고, 업로드만 multipart다.
- 목록 요청은 `limit`(기본 100, 최대 1000)과 `offset`을 쓴다. 시각은 시간대를 포함한 ISO 8601이다.
- 오류 본문: `{"code": "...", "message": "...", "detail": {...}}` (C11과 같은 형식).
- **행위자:** `requested_by`, `answered_by`, `uploaded_by`, `approved_by`, `deployed_by`, `revoked_by`는 본문에서 받지 않는다. **세션으로 부르면 계정 아이디**다(로그인이 정한 신원이라 `X-CHK-Actor`를 듣지 않는다, ADR-0090). 키로 부르면 키 이름이다(Studio 키는 **승인할 때 붙인 이름** — §Studio 등록 요청과 승인). 관리자·읽기 토큰(자동화)으로 부르면 `X-CHK-Actor` 헤더의 이름이고, 없으면 「관리자 토큰」·「보기 전용」이다 — 이 헤더는 **토큰으로 부를 때만** 믿는다.
  - **사람 대신 부르는 키는 `X-CHK-On-Behalf-Of`를 싣는다** ([ADR-0081](../decisions/0081-answering-on-behalf.md)). 대리 답용 키는 결재에 **반드시**(C6), 연동용 키는 `POST /jobs`·`POST /messages`에 **실어도 된다**. 작업에서는 **`on_behalf_of`로 적기만** 하고 `requested_by`는 그대로 키 이름이다 — `requested_by`는 권한의 주인이고 Bot UI가 그 앞머리 `server_bot:`로 위임 작업을 가르므로, 바깥에서 온 글을 그 칸에 넣지 않는다. 대조할 담당자가 없으니 **주장일 뿐**이고 권한을 바꾸지 않는다. 비었거나 200자를 넘거나 예약 앞머리로 시작하면 422 `on_behalf_invalid`.
  - **값은 UTF-8을 퍼센트 인코딩해서** 넣는다 (`운영자 김` → `%EC%9A%B4%EC%98%81%EC%9E%90%20%EA%B9%80`). HTTP 헤더 값에는 ASCII 밖의 글자를 넣을 수 없어서(보내는 쪽 HTTP 라이브러리가 거부한다), 한글 이름을 그대로 실으면 요청 자체가 나가지 않는다. 받는 쪽은 디코딩하고, 디코딩이 실패하면 받은 문자열을 그대로 쓴다.

### 인증

| 인증 수단 | 누가 쓰나 | 어디까지 쓸 수 있나 |
| --- | --- | --- |
| 세션 토큰 — 보기 전용 계정 | 콘솔 | **GET만** (계정 목록은 빼고) |
| 세션 토큰 — 관리자 계정 | 콘솔 | 쓰기 전부. 승인·배포·외부 확장은 Center가 서명한다 (C2) |
| 읽기 토큰 | 자동화 (선택 — 비우면 닫힌다) | 보기 전용 계정과 같다 |
| 관리자 토큰 | 자동화 (선택 — 비우면 닫힌다) | 관리자 계정과 같다. 자기 비밀번호 바꾸기만 없다 (계정이 없다) |
| 인증 없음 | 키가 아직 없는 Bot UI·서버 실행기 | **등록 요청을 보내고 그 답을 묻는 것뿐** (C4·C12 §등록 요청과 승인 — 내려 주는 키는 요청의 공개키로 봉해 있다) |
| Center API 키 — Studio용 | Studio (등록 요청을 관리자가 승인해 받은 키, 자동화용은 관리자 토큰으로 발급) | 패키지 업로드, 패키지·리소스 읽기 |
| Center API 키 — Bot UI용 / 서버 실행기용 | 실행하는 쪽 | **자기에게 배포된** BPM 프로세스 패키지만 내려받기 (공유 BPM 프로세스는 그 안 `libs/`에 들어 있다) |
| Center API 키 — 연동용 (신규, CON-11) | 외부 시스템 | 작업 만들기(`POST /jobs`)와 자기가 만든 작업 읽기·취소, 메시지 넣기(`POST /messages` — C12 §메시지) |
| Center API 키 — 대리 답용 (`relay`) | 사람 대신 결재하는 연동 (대화 창구) | **결재 읽기·답뿐**이고 담당인 것만 (C6). 이 표의 엔드포인트는 하나도 부르지 못한다 |

### 엔드포인트별 권한

아래 표의 「읽기」는 보기 전용 계정·읽기 토큰, 「관리자」는 관리자 계정·관리자 토큰이다.

| 엔드포인트 | 읽기 | 관리자 | Studio 키 | Bot UI·서버 실행기 키 | 연동용 키 |
| --- | --- | --- | --- | --- | --- |
| `GET /packages…` (목록·정보) | ✓ | ✓ | ✓ | — | — |
| `GET /packages/{id}/{v}` (내려받기) | — | ✓ | ✓ | 자기 배포분만 | — |
| `POST /packages` | — | ✓ | ✓ | — | — |
| `POST /auth/login` | 인증 없음 | | | | |
| `POST /auth/logout`, `GET /auth/me` | ✓ | ✓ | — | — | — |
| `PUT /auth/password` (자기 비밀번호) | 세션만 | 세션만 | — | — | — |
| `GET/POST /accounts`, `PUT /accounts/{username}` | — | ✓ | — | — | — |
| `PUT …/signature`, `POST …/revoke` (Center가 서명) | — | ✓ | — | — | — |
| `PUT …/status` (지원 종료), `DELETE /packages/…` | — | ✓ | — | — | — |
| `POST/DELETE /deployments` (Center가 서명) | — | ✓ | — | — | — |
| `GET /deployments`, `GET /admin-keys` | ✓ | ✓ | — | — | — |
| `GET /resources…` (C7·C13, 확장 정의 포함) | ✓ | ✓ | ✓ | ✓ | — |
| `POST/PUT/DELETE /resources/service-apps…`, `POST /resources/refresh` | — | ✓ | — | — | — |
| `POST/DELETE /resources/extensions` (Center가 C2 `extension` 봉투에 서명) | — | ✓ | — | — | — |
| `GET /server-runners` | ✓ | ✓ | — | — | — |
| `POST /server-runners/{id}/pause·resume·mark-lost` (C12) | — | ✓ | — | — | — |
| `GET /bot-uis…` (CON-03), `POST /bot-uis/{id}/disable·enable` | GET만 ✓ | ✓ | — | — | — |
| `POST /bot-ui/enroll`, `POST /server-runner/enroll`, `GET …/enroll/{id}` (C4·C12) | 인증 없음 | | | | |
| `GET /enrollments` (§등록 승인) | ✓ | ✓ | — | — | — |
| `POST /enrollments/{id}/approve·reject` | — | ✓ | — | — | — |
| `POST /jobs` | — | ✓ | — | — | ✓ |
| `GET /jobs…` | ✓ | ✓ | — | — | 자기 것만 |
| `DELETE /jobs/{id}` | — | ✓ | — | — | 자기 것만 |
| `POST /messages` (C12 §메시지) | — | ✓ | — | — | ✓ |
| `GET /virtual-workers…` (CON-13) | ✓ | ✓ | — | — | — (대리 답용 키는 감독하는 것만) |
| `POST/PUT/DELETE /virtual-workers…` | — | ✓ | — | — | — |

## 관리자 계정 ([ADR-0090](../decisions/0090-center-admin-accounts.md))

콘솔은 **계정으로만** 들어온다. Center가 비밀번호를 확인하고 **세션 토큰**을 주면 콘솔 서버(BFF)가 그것을 들고 부른다 — 브라우저는 모른다 (ADR-0017).

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /auth/login` `{username, password}` | 로그인. **토큰은 이 응답에만** 실린다 | 200 SessionInfo `{token, username, role, expires_at}` |
| `POST /auth/logout` | 그 세션을 지운다 | 204 |
| `GET /auth/me` | 지금 부르는 쪽 `{actor, role, account?}` | 200 WhoAmI |
| `PUT /auth/password` `{current_password, new_password}` | 자기 비밀번호. 그 계정의 세션이 **모두** 끝난다 | 200 AccountInfo |
| `GET /accounts` | 계정 목록 (비밀번호 해시는 나가지 않는다) | 200 AccountInfo[] |
| `POST /accounts` `{username, password, role}` | 만들기 | 201 AccountInfo |
| `PUT /accounts/{username}` `{role?, disabled?, password?}` | 역할 바꾸기·멈추기·다시 쓰기·비밀번호 새로 정하기. 바뀌면 그 계정의 세션이 **모두** 끝난다 | 200 AccountInfo |

- **역할은 둘**이다 — `admin`(관리자)·`viewer`(보기 전용).
- **아이디**는 영문 소문자·숫자·`.`·`_`·`-` 3~32자(영문 소문자나 숫자로 시작) — 아니면 422 `username_invalid`. 이미 있으면 409 `account_exists`.
- **비밀번호**는 12자 이상이고 영문과 숫자를 모두 넣는다 — 아니면 422 `password_weak`. Center는 `scrypt` 해시만 둔다.
- **계정은 지우지 않고 멈춘다** (`disabled`). 기록에 남은 이름이 가리킬 곳이 사라지지 않게 한다. 멈춘 계정은 로그인이 403 `account_disabled`이고 세션도 곧바로 끝난다.
- **마지막 남은 관리자는 멈추거나 보기 전용으로 바꿀 수 없다** — 409 `last_admin`.
- 로그인이 틀리면 401 `login_failed` 하나다(「아이디가 없다」와 「비밀번호가 틀렸다」를 가르지 않는다). **같은 아이디로 5번 연달아** 틀리면 5분 동안 429 `login_locked`다.
- 세션은 **12시간** 뒤 끝난다 — 그 뒤에 부르면 401 `session_expired`. 토큰은 `chk_ses_`로 시작하고 Center는 해시만 둔다.
- **첫 관리자**는 Center 설정(`CHK_CENTER__FIRST_ADMIN__*`, `docs/04-setup.md` §5)이 계정이 하나도 없을 때 한 번 만든다.

AccountInfo 필드: `username`, `role`, `state`(`active` / `disabled`), `created_at`, `created_by`, `password_changed_at`, `disabled_at`?, `last_login_at`?.

## 패키지

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /packages` (multipart `file`) | 업로드. Center가 zip 안전 검사(경로 탈출·크기), C1 검사(R1~R6·R9), 해시 재계산을 한다 | 201 새로 / 200 같은 id·버전·해시 (재시도) |
| `GET /packages?kind=&status=&id=` | 목록 | 200 PackageInfo[] |
| `GET /packages/{id}/{version}/info` | 정보 (매니페스트, 상태, 사전 점검 요약, 누락 리소스) | 200 |
| `GET /packages/{id}/{version}` | 내려받기. 승인된 패키지면 zip에 `SIGNATURE`를 넣어 준다 (C2). 헤더 `X-Content-Hash` | 200 zip / 410 철회됨 |
| `PUT /packages/{id}/{version}/signature` (본문 없음) | 승인. **Center가 C2 `package` 봉투에 서명한다**. 상태가 `approved`가 되고 `approved_by`가 남는다. 이미 승인됐으면 그대로 200, 철회된 것은 409 `package_revoked` | 200 |
| `POST /packages/{id}/{version}/revoke` `{reason?}` | 승인 철회. Center가 C2 `package_revoke` 봉투에 서명한다. 상태가 `revoked`가 되고 배포가 모두 무효가 된다. **되살릴 수 없다** | 200 |
| `PUT /packages/{id}/{version}/status` `{status: "deprecated"}` | 지원 종료 표시. 새 배포를 막는다. 서명이 필요 없다 (실행을 허용하는 쪽이 아니라 막는 쪽이라서) | 200 |
| `GET /packages/{id}/{version}/dependents` | 이 패키지를 `requires`로 쓰는 패키지 | 200 DependentInfo[] |
| `DELETE /packages/{id}/{version}` | 삭제. 배포나 다른 패키지가 참조하면 409 `in_use` | 204 |

지원 종료(`PUT …/status`) 규칙:

- **받는 값은 `deprecated` 하나뿐이다.** 되돌리는 것은 「다시 허용」이고 그 길은 승인(`PUT …/signature`)이다. 다른 값을 주면 422 `input_invalid`.
- **`revoked`는 끝이다** — 철회된 것은 되살아나지 않고 더 막을 것도 없다 (409 `package_revoked`).
- 어느 상태에서든 지원 종료로 갈 수 있고(`candidate`도 — 새 배포를 막는 뜻이다), **두 번 해도 같은 답**이다.
- **이미 배포된 것은 그대로 돈다** — 내려받기도 그대로 된다 (철회면 410이다). 돌고 있는 것을 세우는 것은 배포 철회다.

PackageInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `id`, `version`, `kind`, `name` | |
| `run_location` | `bpm_process`에만 있다 |
| `status` | `candidate` / `approved` / `deprecated` / `revoked` (열린 문자열) |
| `content_hash` | |
| `uploaded_by`, `uploaded_at` | |
| `signed_by`?, `signed_at`? | 승인 봉투의 서명 키 id·시각 (지금은 늘 Center 키다) |
| `approved_by`? | 승인한 사람 — 계정 아이디 (ADR-0090). 사람이 서명하던 때의 승인에는 없다 |
| `preflight` | `{warnings, blocked}` |
| `manifest` | C1 매니페스트 |
| `missing_resources` | `[{type: extension \| service_app \| operation \| resource, id, reason}]`. 읽을 때 C7과 대조해 계산한다 (확장 기여 자원은 `resource`이고 id가 `<종류>:<id>`다 — 예: `ui_page:erp.order.form`) |
| `download_count` | **내어 준 횟수** (기본 0). 관문(권한·배포 대조)을 지나 파일을 내어 줄 때 하나 센다 — **같은 곳이 다시 받아도 센다**(설치를 다시 하거나 캐시를 잃은 경우). 「몇 곳이 쓰나」가 아니라 「얼마나 받아 갔나」다. 쓰는 곳은 `dependents`·배포 목록이 말한다 |
| `last_downloaded_at`? | 마지막으로 내어 준 때. 한 번도 받지 않았으면 없다 |

### 참조하는 패키지 (`dependents`)

DependentInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `id`, `version`, `kind`, `name` | 참조하는 쪽 패키지 |
| `status` | 그 패키지의 상태 |
| `relation` | 어느 칸으로 참조하나 — 지금은 `lib`(C1 `requires.libs`)뿐이다 (열린 문자열) |
| `pinned_hash` | 참조하는 쪽이 **고정한** 해시. `lib`은 `<id>@<version>`으로만 가리키므로 **늘 `null`**이다 |

- **읽을 때 센다.** 참조 그래프를 따로 저장하지 않는다 — 저장해 두면 패키지가 올라오고 지워질 때마다 낡는다 (`missing_resources`와 같은 결).
- 참조는 **버전까지 같아야** 센다. `requires.libs`의 `<id>@<version>`을 그대로 맞춰 본다.
- `pinned_hash`가 이 패키지의 `content_hash`와 다르면 **그래도 센다** — 참조하는 쪽이 낡은 해시를 고정해 둔 것이고, 그 패키지의 실행은 C1 R7·설치 검사에서 걸린다. 삭제를 막는 쪽에서는 「쓰는 데가 있다」가 맞다.
- 자기 자신은 세지 않는다.

### 삭제 (`DELETE`)

참조가 있으면 **아무것도 지우지 않고** 409 `in_use`를 돌려준다. `detail`에 막은 것을 담는다:

| `detail` 칸 | 뜻 |
| --- | --- |
| `deployments` | 이 패키지를 가리키는 배포 id 목록. **철회된 배포는 세지 않는다** (행은 남지만 실행을 허용하지 않는다) |
| `dependents` | `<id>@<version>` 목록 (위 `dependents`와 같은 셈) |

- 승인 봉투·철회 봉투가 붙어 있는 것은 **막지 않는다** — 봉투는 그 패키지에 딸린 것이라 함께 지운다.
- 지우는 것은 패키지 행·봉투·zip 파일이다. 그 패키지로 돌았던 **실행 기록은 지우지 않는다** (C3가 원본이고 패키지를 가리키는 이름만 남는다).
- 없는 패키지는 404. 되돌릴 수 없으므로 화면은 확인 창을 먼저 띄운다 (CON-06).

## 배포

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /deployments` `{target, bpm_process_id, version, not_before?, expires_at?, max_concurrency?}` (DeploymentRequest) | 배포. **Center가 `deployment_id`(`dep_<hex8>`)와 `content_hash`(그 패키지의 것)를 채워 C2 `deployment` 봉투에 서명하고** 아래 항목을 검사한다. 누를 때마다 새 배포다 | 200 DeploymentInfo |
| `DELETE /deployments` `{deployment_id, reason?}` | 철회. Center가 C2 `revoke` 봉투에 서명한다. 행은 지우지 않고 `revoked_at`을 찍는다. **되살릴 수 없다** | 200 |
| `GET /deployments?target_type=&target_id=&bpm_process_id=&active=` | 목록 | 200 DeploymentInfo[] |

배포할 때 Center가 검사하는 것 — **규칙은 계약의 `validate_deployment()` 하나이고 Center가 그것을 부른다** ([ADR-0047](../decisions/0047-one-deployment-gate.md)). 상태 코드는 같은 자리의 `DEPLOYMENT_REFUSAL_STATUS` 표가 정한다:

| 검사 | 거절 | 상태 |
| --- | --- | --- |
| 그 패키지가 있다 | `not_found` | 404 |
| 지은 봉투의 서명·시간 (C2 V1~V5a — 지난 `expires_at`이면 `expired`). `not_before`가 미래인 예약 배포도 받는다 | C2의 사유 코드 | 403 |
| 패키지가 `approved`다 | `not_approved` | 409 |
| 지원 종료가 아니다 — **따로 알린다**, 승인은 되어 있고 새 배포만 막힌 것이다 | `deprecated` | 409 |
| 봉투의 해시가 패키지와 같다 | `hash_mismatch` | 409 |
| `target.type`이 패키지의 `run_location`과 맞다 | `wrong_target` | 409 |
| **PC 배포의 `target.id`가 `"*"`가 아니다** ([ADR-0046](../decisions/0046-no-wildcard-pc-deployment.md)). `"*"`는 서버 실행기 배포만 쓴다 (C2 §배포 대상 규칙) | `wrong_target` | 409 |
| **대상 PC가 등록되어 있다** ([ADR-0049](../decisions/0049-deployment-target-must-exist.md)) — `bot_uis`를 **Center가 읽어** 계약에 넘긴다 | `target_not_found` | 404 |
| 서버 실행기 대상이 아니다 (M7까지, ADR-0016) | `server_runner_not_available` | 422 |

- **대상이 틀린 두 가지는 코드가 하나다** (`wrong_target`) — C2 V6이 같은 조건에 쓰는 이름이고, 둘 다 받아 두면 **모든 PC가 V6으로 거부할** 봉투라 운영자가 할 일도 같다(대상을 하나 제대로 적는다). `target_mismatch`는 **작업 지시 쪽 코드**다 (모르는 대상 종류, 422).
- **「대상이 틀렸다」가 「대상이 없다」를 이긴다** — PC 배포에 `"*"`가 오면 그 id도 등록되어 있지 않지만 답은 `wrong_target`이다 (운영자가 할 일은 「대상을 하나 적는다」이고, 「`*`라는 PC가 없다」는 엉뚱한 말이다). 그래서 등록 검사는 **대상 검사 뒤에** 온다.
- **`target_not_found`는 `not_found`와 다른 코드다** — 한 요청에서 없을 수 있는 것이 둘(패키지·PC)이라 뭉치면 운영자가 어느 쪽을 고칠지 모른다. **작업 지시도 같은 코드로 답한다** — 같은 조건에 두 이름을 두는 것이 ADR-0047이 고친 흠이다.
- Center가 자기 저장소를 봐야 하는 **읽기**는 계약이 하지 않는다. 읽어서 **넘기는** 것은 계약이 판정한다 (지금 `package`와 대상 등록 여부가 그렇다, [ADR-0047](../decisions/0047-one-deployment-gate.md) §다시 볼 조건 ②). 계약이 판정하지 않고 Center에 남은 것: 그 패키지가 있나(404 `not_found`), 그리고 배포를 막는 리소스 누락과 C1 R8(422, C7 §누락 검사).
- **등록되지 않은 PC에 미리 배포해 두는 길은 없다** — `bot_ui_id`는 Center가 **첫 등록에서 만든다**(C4 「키 묶기」). 등록 전에는 대상에 적을 id가 없으므로, 등록되지 않은 id가 오면 오타이거나 낡은 id다. 행은 지워지지 않으니(「PC 묶음 풀기」는 키만 푼다) **한번 통과한 배포의 대상은 사라지지 않는다**.

DeploymentInfo 필드: `deployment_id`, `target{type,id}`, `bpm_process_id`, `version`, `content_hash`, `max_concurrency`?, `signed_by`, `signed_at`, `not_before`?, `expires_at`?, `revoked_at`?, `last_result`?, `deployed_by`?, `revoked_by`?. `last_result`는 C4 `deployment_results`의 마지막 값이다. `deployed_by`·`revoked_by`는 **누른 계정**이다 (ADR-0090 — 사람이 서명하던 때의 배포에는 없다).

- `signed_by`·`signed_at`·`not_before`·`expires_at`·`max_concurrency`는 **봉투에서 읽는다** (Center가 따로 짓지 않는다). `signed_by`는 서명한 키의 `key_id`다 (지금은 늘 Center 키라 사람을 말하지 않는다 — 사람은 `deployed_by`다).
- `revoked_at`은 철회 봉투의 `revoked_at`이다. 행은 지우지 않으므로 철회된 배포도 목록에 남는다 (`active=true`로 거른다).

- **M6까지:** `target.type=server_runner` 배포는 422 `server_runner_not_available` (서버 실행은 M7부터, ADR-0016). 작업 지시도 같은 코드로 막고 **스위치는 한 자리다** (`SERVER_RUNNER_AVAILABLE` — 한쪽만 켜면 「작업은 만들어지는데 배포가 없다」가 된다).

## 작업 (job)

| 메서드·경로 | 뜻 | 성공 |
| --- | --- | --- |
| `POST /jobs` | 작업 만들기 | 201 JobInfo / 200 같은 `idempotency_key` |
| `GET /jobs?state=&target_type=&target_id=&bpm_process_id=&virtual_worker=&limit=` | 목록 (최신순). `state`는 쉼표로 여럿 (`pending,dispatched`). `virtual_worker`는 그 접수 Bot의 작업과 그 자식 작업 (§가상 직원) | 200 |
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
| `requested_by` | 사람 이름, 키 이름, 또는 예약값 `server_bot:<run_id>` (PC 위임) |
| `on_behalf_of`? | 연동용 키가 `X-CHK-On-Behalf-Of`로 실어 보낸 사람 이름 (**주장** — Center가 대조하지 않는다). 메시지 시작으로 만든 작업에는 그 메시지의 것을 옮긴다 (ADR-0081) |
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

`rejected`의 `state_reason`: `queue_full`, `no_deployment`, `not_ready`, `bot_ui_shutdown`, `bot_ui_lost`, `server_location`, `cancelled_on_pc`(현장 Bot UI에서 취소), **`runner_lost`**(서버 실행기를 잃음 — 맞추기 규칙이나 CON-12 「유실 처리」, C12).

`queued`(서버)의 `state_reason`: `global_limit`(서버 실행기 빈자리 없음), `per_bot_limit`(BPM 프로세스별 상한), `paused` (C12).

**맞추기 규칙의 사유는 호스트마다 다르다** — PC는 `bot_ui_lost`, 서버 실행기는 `runner_lost`다. 뭉개면 CON-12가 서버에 「bot_ui_lost」라고 적어 운영자가 PC를 찾아 헤맨다.

### 취소

| 지금 상태 | 응답 | 결과 |
| --- | --- | --- |
| `pending` | 200 | 바로 `cancelled` |
| `dispatched` / `queued` | **202** `cancel_requested: true` | 다음 하트비트에 Bot UI가 빼내고 `cancelled`로 ack하면 `cancelled`. 그사이 실행을 시작했으면 Bot UI가 `cancel_refused`로 ack하고, 작업은 **`accepted` 그대로**, `cancel_result: refused_already_started` |
| `accepted` + 대상 **서버 실행기** | **202** `cancel_requested: true` | 실행기가 다음 하트비트에 **그 실행을 닫고**(기다리는 실행도) `cancelled`로 ack한다. 이미 끝나 가던 것은 `cancel_refused`다 — 현장이 옳다 ([ADR-0063](../decisions/0063-stopping-a-running-server-run.md)) |
| `accepted` + 대상 **PC** | 409 `already_started` | **PC 실행은 Center에서 멈추지 않는다** — 자리를 끝까지 쥐고(ADR-0014) 화면을 만지는 중일 수 있어, 도중에 끊으면 화면이 반쯤 바뀐 채 남는다. 현장 사람이 BUI-04 「중지」로 멈춘다 (그 사람은 화면을 보고 있다) |
| 그 밖 | 409 `not_cancellable` | |

- 실행의 성공·실패는 작업 상태가 아니다. C3 `run_finished`로 정해지고 `run_status`에 보인다.
- **가르는 것은 대상 종류 하나다** — 판정은 계약이 쥔다 (`cancel_outcome(state, target_type)`). 서버 실행은 **화면을 만지지 않으므로**(R2가 UI 태스크를 막는다) 엔진 취소가 곧 `cancelled` 기록이다.
- **Center가 혼자 `cancelled`로 적지 않는다** (`dispatched`와 같은 결) — 정말 멈췄는지는 현장만 안다. 실행기가 오프라인이면 취소 요청은 남고 **돌아오면 반영된다**; 돌아오지 않으면 CON-12 「유실 처리」가 닫는다 (C12).
- 서버 실행이 취소되면 **그 실행이 맡긴 PC 위임도 거둬진다** ([ADR-0062](../decisions/0062-pc-delegation.md) §5).

## 등록 승인 (CON-03·CON-12·CON-11)

> 상태: **돈다** (2026-10-25, [ADR-0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md)) — `center/enrollments.py`. 콘솔은 CON-03·CON-12 「승인 대기」(`components/Enrollments.tsx`).

PC(Bot UI)·서버 실행기·**Studio**가 보낸 **등록 요청**(C4·C12 §등록 요청과 승인, 아래 §Studio 등록 요청과 승인)을 관리자가 보고 들인다. 사람은 키를 보지 않는다 — 승인하면 Center가 키를 만들어 그 요청의 공개키로 봉해 둔다.

| 메서드·경로 | 뜻 |
| --- | --- |
| `GET /enrollments?type=bot_ui\|server_runner\|studio&state=pending` | 요청 목록 (`state`는 쉼표로 여럿, 기본 `pending`) |
| `POST /enrollments/{enrollment_id}/approve` `{name?}` | 승인. `name`을 비우면 요청의 `name`을 쓴다 |
| `POST /enrollments/{enrollment_id}/reject` `{reason?}` | 거절. 사유는 요청한 쪽에 그대로 보인다 (200자까지) |

EnrollmentInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `enrollment_id`, `type` | `type`은 `bot_ui` / `server_runner` |
| `code` | 요청 코드 `XXXX-XXXX` — 현장 화면(서버는 로그)과 맞춰 보는 값 |
| `name`, `os`, `versions` | 요청이 보낸 그대로 |
| `machine_id_prefix` | `machine_id` 앞 12자 (같은 PC인지 알아볼 만큼만) |
| `remote_addr` | 요청이 온 주소 (Center가 본 그대로) |
| `requested_at`, `expires_at` | |
| `state` | **열린 문자열.** 알려진 값: `pending` `approved` `rejected` `expired`. 화면 표기는 `status_map` 「등록 요청」 |
| `existing`? | 그 `machine_id`가 이미 등록돼 있으면 `{id, name, key_prefix, last_seen}` — 승인하면 **이 자리를 이어받고 그 키는 폐기된다** (C4 키 묶기) |
| `decided_by`?, `decided_at`?, `reason`? | 승인·거절한 계정과 때, 거절 사유 |
| `key_id`? | 승인이 만든 키 (C7 `CenterKeyInfo`) |

- 승인 응답은 `{key_id, host_id, replaced_key_id?}`다 (`host_id`는 이어받았으면 그 `bot_ui_id`·`server_runner_id`, 새 자리면 첫 `register`가 만든다 — 그때까지 `null`).
- **이미 결정된·만료된 요청은 다시 결정하지 못한다** (409 `enrollment_closed`).
- 승인은 **행위자를 남긴다** (`decided_by` — 세션이면 계정, 토큰이면 `X-CHK-Actor`).
- 승인·거절은 되돌리지 않는다. 잘못 들였으면 CON-03 「비활성화」 또는 그 키를 폐기한다 (C7).

### Studio 등록 요청과 승인 ([ADR-0093](../decisions/0093-studio-is-let-in-by-approval.md))

> 상태: **초안** — 코드 아직. 지금 코드는 Studio가 Center 계정(아이디·비밀번호)으로 로그인해 키를 받는다(`POST /auth/studio-login`) — 이 결정으로 걷어 낸다.

Studio도 Bot UI와 **같은 길**로 들어온다 (C4 §등록 요청과 승인 — 요청 코드·봉함·24시간 대기·막기·같은 PC의 옛 요청 닫기가 같은 규칙, 같은 코드다). 아이디·비밀번호로 들어오는 길은 없다.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /studio/enroll` | 없음 | 등록 요청. 본문은 `{schema, machine_id, name, os, versions{studio, core}, public_key}`, 응답은 C4 `EnrollStatus` |
| `GET /studio/enroll/{enrollment_id}` | 없음 | 그 요청이 승인됐나. 승인됐으면 봉한 Studio 키가 실려 온다 |

- 승인하면 Center가 종류 `studio`의 키를 만든다. **이름은 승인할 때 정하고**(기본은 요청의 `name` — PC 이름) **그 키의 이름이 「누가」다**(`uploaded_by` 등). 그 PC(`machine_id`)에 묶어 두고, **같은 PC를 다시 승인하면 옛 Studio 키를 폐기한다**(`EnrollmentInfo.existing`에 그 키가 보인다).
- **만료는 1년이고 회전하지 않는다** — Studio에는 하트비트가 없다. 만료 14일 전부터 Studio가 알리고, 만료·폐기되면 새로 요청해 승인받는다.
- 봉함을 받았다는 표시는 **그 키로 처음 부른 것**이다 (Bot UI의 `register` 자리) — 그때 Center가 봉해 둔 것을 지운다. 24시간 안에 부르지 않으면 키를 폐기한다 (C4와 같다).
- 자동화·CI가 쓰는 Studio용 키는 관리자 토큰으로 발급한다(C7 `POST /center-keys`) — 화면에는 없다.

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
| `deployment_results` | 그 Bot UI가 보고한 **최근 배치 결정** (C4 `DeploymentResult`, 최신순 최대 20건). CON-03 「최근 배치 결정」. 마지막 하트비트만이 아니라 **Center가 쌓아 둔 것**이다 — 한 주기 뒤면 사라지는 값을 운영자가 보지 못하면 「왜 설치가 안 됐나」를 영영 알 수 없다 |
| `key` | 그 Bot UI가 쓰는 Center API 키 `{prefix, expires_at, state}` — **원문·해시는 주지 않는다** (C7) |

## 가상 직원 (CON-13)

사람이 아닌 업무 주체 — 접수 Bot·감독자를 묶는다 ([ADR-0085](../decisions/0085-virtual-worker-resource.md), 용어집 §2-1). **일괄은 자원이 아니다** — 접수 Bot 실행 한 번이고(ADR-0079) 여기서는 **읽을 때** 이어 붙인다.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /virtual-workers` | 관리자 토큰 | 등록 (`VirtualWorkerRequest`). 201 |
| `GET /virtual-workers?supervisor=` | 읽기·관리자 토큰 / 대리 답용 키 (**감독하는 것만**) | 목록 (`VirtualWorkerInfo[]`, `batches`는 비어 있다) |
| `GET /virtual-workers/{id}` | 같음 (아니면 404) | 하나 + **최근 일괄** |
| `PUT /virtual-workers/{id}` | 관리자 토큰 | 바꾸기 (본문 전체, `id`는 경로가 이긴다) |
| `DELETE /virtual-workers/{id}` | 관리자 토큰 | 등록만 지운다 — 실행·작업은 남는다 |

VirtualWorkerRequest:

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `id` | str | ✓ | `^[a-z0-9][a-z0-9._-]{0,63}$`. 주체 이름은 `vw:<id>` |
| `name` | str | ✓ | 화면 이름 |
| `supervisors` | str[] | | 감독자 이름들 (C6 담당자와 같은 정규화). **결재 담당자와 맞춰 보지 않는다** — 담당자는 그림이 정한다 |
| `intake` | str | ✓ | 접수 Bot의 **패키지 id** (판은 배포가 정한다) |
| `state` | str | | `active`(기본) / `stopped` — 열린 문자열. **새 작업을 막지 않는다**(보이기 위한 칸이다) |

VirtualWorkerInfo는 위에 `created_at`·`updated_at`과 **`batches[]`**(최근 일괄 20개, 하나에서만)를 더한다:

| 필드 | 뜻 |
| --- | --- |
| `run_id` | 일괄 id = 접수 Bot 실행 |
| `status` | 그 실행의 C3 상태 (`running`·`waiting`·`success`·`failed`·`cancelled` — `RunInfo.status`와 같다) |
| `started_at` | |
| `children` | 그 실행이 기동한 자식 실행 수 (`parent_run_id`로 모은다) |
| `children_by_status` | `{상태: 수}` |
| `open_approvals` | 그 실행의 열린 결재 `request_id`들 (일괄 결재가 아직이면 여기 있다) |

**관문 — 결재 없는 일괄 기동이 없어야 묶인다** ([ADR-0085](../decisions/0085-virtual-worker-resource.md) §2):

- 등록·`intake` 바꾸기: 그 패키지의 **승인된 판이 하나 이상**(아니면 422 `intake_unknown`), 실행 위치 `server`(아니면 422 `intake_not_server`), **승인된 판마다** 진입 그림에 C14 **B16이 없다**(아니면 422 `intake_not_gated` + `detail.violations`).
- 배포: 활성 가상 직원의 접수 Bot이면 그 판의 진입 그림에 B16이 없어야 한다 — 아니면 409 `intake_not_gated`.
- 그림은 Center가 저장된 zip에서 읽는다(`contracts.bpmn_ext` — 내보낸 쪽을 믿지 않는다). B16만 본다.

**이어 붙이기** — `GET /runs?virtual_worker=<id>`(C3)·`GET /jobs?virtual_worker=<id>`는 접수 Bot의 것과 **그 자식**(실행은 `parent_run_id`, 작업은 `requested_by = server_bot:<접수 실행>`)을 함께 준다. 「접수 Bot의 실행」은 실행 기록의 `bpm_process_id`가 **그 패키지 id**인 것이다 (C3 — 실행 기록도 패키지 id로 말한다, [ADR-0086](../decisions/0086-run-identity-is-the-package-id.md)). 저장하지 않고 읽을 때 모은다. **`requested_by`는 바꾸지 않는다** — 접수 Bot 작업을 부른 키가 그대로 적힌다.

```json
{
  "id": "finance-intake",
  "name": "재무 가상 직원",
  "supervisors": ["김감독"],
  "intake": "fx24-batch-intake",
  "state": "active",
  "created_at": "2026-10-20T09:00:00+09:00",
  "updated_at": "2026-10-20T09:00:00+09:00",
  "batches": [
    {"run_id": "run_20261020_091500_a1b2c3", "status": "success", "started_at": "2026-10-20T09:15:00+09:00",
     "children": 3, "children_by_status": {"success": 3}, "open_approvals": []}
  ]
}
```

## 오류

| 상태 코드 | `code` | 언제 |
| --- | --- | --- |
| 401 | `login_failed` / `session_expired` | 아이디·비밀번호가 맞지 않음 / 로그인이 끝남 (다시 로그인한다) |
| 403 | `account_disabled` / `admin_only` / `password_wrong` | 멈춘 계정 / 관리자만 / 자기 비밀번호 바꾸기의 지금 비밀번호가 틀림 |
| 429 | `login_locked` | 같은 아이디로 5번 연달아 틀림 — 5분 뒤 |
| 422 | `username_invalid` / `password_weak` / `role_unknown` | 계정 규칙 |
| 409 | `account_exists` / `last_admin` | 같은 아이디 / 마지막 관리자를 멈추거나 내리려 함 |
| 401 / 403 | `key_invalid` / `forbidden` | 인증 실패, 권한 밖 (예: Bot UI가 자기에게 배포되지 않은 패키지를 요청) |
| 404 | `not_found` | |
| 404 | `target_not_found` | 배포·작업 지시의 대상 PC가 **등록되어 있지 않다** (ADR-0049). `not_found`(패키지가 없다)와 **가른다** — 한 요청에서 없을 수 있는 것이 둘이라 뭉치면 어느 쪽을 고칠지 모른다 |
| 409 | `version_conflict` | 같은 버전인데 내용이 다름 |
| 409 | `in_use` | 참조 중인 패키지 삭제 |
| 409 | `already_started` / `not_cancellable` | 취소할 수 없는 작업 |
| 409 | `not_approved` / `deprecated` / `hash_mismatch` / `wrong_target` | 배포가 가리키는 **패키지의 상태**가 요청과 어긋난다. 「본문이 잘못됐다」가 아니라 **상태 충돌**이라 409다 (`deployment_conflict`과 같은 결). 지원 종료는 `not_approved`로 뭉개지 않는다 — 승인은 되어 있고 새 배포만 막힌 것이다. `wrong_target`은 **대상이 틀린 것 전부**다 — `target.type` ↔ `run_location` 어긋남과 **PC 배포의 `"*"`** (ADR-0046·0047) |
| 409 | `package_revoked` | 철회된 패키지를 승인하거나 지원 종료로 바꾸려 함 (끝난 일이다) |
| 409 | `idempotency_conflict` | 같은 `idempotency_key`에 다른 본문 |
| 409 | `enrollment_closed` | 이미 승인·거절됐거나 만료된 등록 요청을 다시 결정하려 함 |
| 410 | `revoked` | 철회된 패키지 내려받기 |
| 413 | `too_large` | 패키지 50 MB 초과 |
| 422 | C1 규칙 코드, `target_mismatch`(모르는 대상 종류), `no_deployment`, `version_ambiguous`, `inputs_not_object` | 검사 실패. 모두 **작업 지시(`/jobs`)** 쪽이다 — 배포 쪽 상태 충돌은 위의 409다 |
| 422 | `intake_unknown` / `intake_not_server` / `intake_not_gated` | 가상 직원의 접수 Bot이 승인된 판이 없거나·서버 Bot이 아니거나·결재 없는 일괄 기동이 있다 (C14 B16, ADR-0085). 배포 쪽의 `intake_not_gated`는 409다 |
| 409 | `id_conflict` | 같은 `id`의 가상 직원이 있다 |
| 422 | `on_behalf_invalid` | `X-CHK-On-Behalf-Of`가 비었거나 200자를 넘거나 예약 앞머리로 시작함 (ADR-0081) |
| 422 | `server_runner_not_available` | 서버 실행기 대상 (M7까지, ADR-0016). **배포와 작업 지시가 같다** — 상태 충돌이 아니라 **아직 없는 기능**이라 배포 쪽에서도 422다 |
| 422 | `not_a_zip`, `manifest_missing`, `manifest_invalid`, `zip_too_many_entries`, `zip_unsafe_path`, `zip_too_large` | 업로드한 zip의 형식 오류. **400이 아니라 422다** — 본문은 읽혔고 내용이 계약과 맞지 않는다 |

## 호환 규칙

- 상태·사유 값은 열린 문자열이다 (README 원칙 10). 콘솔은 모르는 값을 그대로 보인다.
- 모르는 요청 필드는 무시한다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-25 | 1 | **초안: Studio 등록 요청과 승인** — `POST/GET /studio/enroll`, `GET /enrollments?type=studio`. 계정 권한·Studio 로그인(바로 아래 줄)을 걷어 낸다 | [0093](../decisions/0093-studio-is-let-in-by-approval.md) |
| 2026-10-25 | 1 | **계정 권한과 Studio 로그인** (0093이 걷어 낸다) — `AccountInfo.permissions`·`studio_logins`, `POST /auth/studio-login`·`studio-logout`, 오류 `permission_missing` | [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md) |
| 2026-10-25 | 1 | **등록 승인** — `GET /enrollments`·`POST …/approve·reject`, 권한표의 「인증 없음」 줄(등록 요청 두 경로), 오류 `enrollment_closed` | [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md) |
| 2026-10-24 | 1 | **관리자 계정과 로그인 세션**을 더했다(`/auth/*`·`/accounts`). 승인·승인 철회·배포·배포 철회는 **봉투 대신 요청을 받고 Center가 서명한다** — 본문이 바뀌었다(`DeploymentRequest`·`{deployment_id, reason}`·`{reason}`). `approved_by`·`deployed_by`·`revoked_by`를 더했다. `POST/DELETE /admin-keys`를 없앴다. 관리자·읽기 토큰은 자동화용으로 남는다. 배포 철회 경로를 코드대로 `DELETE /deployments`(본문에 id)로 고쳐 적었다 | [0090](../decisions/0090-center-admin-accounts.md) |
| 2026-10-20 | 1 | **가상 직원**(§가상 직원, CON-13) — 등록·읽기·관문(B16, 묶을 때와 배포할 때)·`?virtual_worker=` 이어 붙이기. 새 엔드포인트라 옛 쪽은 영향이 없다 | [0085](../decisions/0085-virtual-worker-resource.md) |
| 2026-10-20 | 1 | **사람 대신 부르는 길** — `X-CHK-On-Behalf-Of`, `JobInfo.on_behalf_of`(주장, `requested_by`는 그대로), 대리 답용 키 줄, 오류 `on_behalf_invalid` | [0081](../decisions/0081-answering-on-behalf.md) |
| 2026-10-17 | 1 | **`download_count`·`last_downloaded_at`을 더했다** — 내어 준 횟수와 마지막 때(CON-06 「내려받은 횟수」). 셀 열을 더할 수단이 없어 화면에서 뺐던 것을 저장소 옮기기 단계(4판)로 되살렸다. 선택 칸이라 옛 응답을 읽는 쪽은 영향이 없다 | [0065](../decisions/0065-center-schema-migrations.md) |
| 2026-10-12 | 1 | **툴팩 갈래가 사라졌다** ([ADR-0050](../decisions/0050-no-toolpack-kind.md)) — 내려받기 범위에서 `requires.toolpacks`가 빠지고(공유 BPM 프로세스는 패키지 안 `libs/`로 오므로 **따로 받는 것이 없다**), `dependents.relation`은 `lib` 하나이고 `pinned_hash`는 늘 `null`이다 | 0050 |
| 2026-10-12 | 1 | **배포 대상은 등록된 PC여야 한다** (404 `target_not_found`). 「대상이 존재한다」를 어느 쪽도 보지 않아 **오타 하나가 201을 받고** 아무에게도 가지 않는 배포로 남았다 — `envelopes_for`는 `target_id`로 맞추고 CON-03에는 그 PC 줄이 없어 보여 줄 자리도 없다. 미리 배포해 두는 길이 막히는 것이 아니다: `bot_ui_id`는 Center가 **첫 등록에서 만들어** 등록 전에는 적을 id가 없다. 읽는 것은 Center, 판정은 계약이다 (ADR-0047 §다시 볼 조건 ②). **작업 지시의 같은 404도 `target_not_found`로 바꿨다** — 같은 조건에 두 이름을 두지 않는다 | 0049 |
| 2026-10-12 | 1 | **배포 관문을 하나로 모았다.** 같은 검사가 계약(`validate_deployment()`)과 Center에 두 벌 있었고 **답이 갈려 있었다** — 대상 어긋남이 계약에서 `target_mismatch`(422), Center에서 `wrong_target`(409)이었고, 서버 배포를 막는 `server_runner_not_available`은 **계약에만** 있어서 Center가 M7 배포를 받아 두고 있었다. 이제 Center가 그 함수를 부르고 코드마다 상태는 `DEPLOYMENT_REFUSAL_STATUS` 한 표에 있다. **배포 쪽 `target_mismatch`는 없어졌다** — 대상이 틀린 것은 `wrong_target`(409) 하나다 | 0047 |
| 2026-10-11 | 1 | **PC 배포의 `"*"`를 적어 막았다.** C2는 `"*"`를 서버 배포에만 주고 V6도 그랬는데, Center가 네 자리에서 대상 종류를 가리지 않고 `"*"`를 풀어 **모든 PC가 거부할 봉투를 내려줄 수 있었다**. `POST /deployments`가 409 `wrong_target`으로 거절하고 고르는 조건은 한 함수가 짓는다. CON-02의 「배포된 Bot UI」가 이 덕에 **정확한 PC 수**로 닫혔다 | 0046 |
| 2026-10-11 | 1 | **권한표를 코드가 따라갔다** (문서는 그대로다). 업로드가 `require_admin`이어서 Studio 키로는 403이었고, 패키지 목록·정보·내려받기가 「키면 무엇이든」이라 Bot UI 키가 전부 받고 연동용 키도 목록을 봤다. 이제 올리기·목록·정보는 **Studio 키만**이고, 내려받기는 **읽기 토큰 없음·실행하는 쪽은 자기 배포분과 그 패키지의 `requires.toolpacks`만**이다. 「없다」와 「내 것이 아니다」는 **같은 403 `forbidden`**이다 — 404로 가르면 그것이 곧 목록이 된다 | 0013 |
| 2026-10-09 | 1 | 배포 쪽 상태 충돌(`not_approved`·`deprecated`·`hash_mismatch`·`wrong_target`)을 **409**로 적었다 — 코드가 처음부터 그렇게 답했고 표만 422로 남아 있었다. `package_revoked`도 더했다 | — |
| 2026-10-09 | 1 | 지원 종료(`PUT …/status`)에 규칙을 적고 구현했다 — `deprecated`만 받고, 철회된 것은 거부하고, 두 번 해도 같은 답이며 내려받기는 그대로 된다 | — |
| 2026-10-01 | 1 | 초안 | 0013~0016 |
| 2026-10-07 | 1 | `GET /jobs`의 `state`가 쉼표로 여럿을 받는다 — CON-05의 상태 필터가 여러 개를 고른다 | 0017 |
| 2026-10-10 | 1 | `GET …/dependents`의 응답 모양(DependentInfo)과 `DELETE /packages/…`의 409 `in_use` `detail`을 적었다 — 표에 줄만 있고 모양이 없어 CON-06을 만들 수 없었다 | — |
| 2026-10-06 | 1 | `BotUiInfo.deployment_results`를 더했다 — 배치 결정은 하트비트 한 주기만 올라오고 Center가 버리고 있어서, CON-03 「최근 배치 결정」이 그릴 것이 없었다. `DeploymentInfo`의 봉투 유래 칸(`signed_by`·`signed_at`·`not_before`·`expires_at`·`revoked_at`)을 어디서 읽는지 적었다 | 0017 |
| 2026-10-03 | 1 | `X-CHK-Actor`는 UTF-8 퍼센트 인코딩으로 보낸다 — 한글 이름을 그대로 실으면 HTTP 헤더에 넣을 수 없어 요청이 나가지 않는다 (콘솔을 붙이다 드러났다) | 0017 |
| 2026-10-03 | 1 | `GET /bot-uis`(CON-03)의 응답 모델 `BotUiInfo`를 적었다 — 엔드포인트만 권한표에 있고 모양이 없어서 콘솔이 타입을 손으로 쓸 수밖에 없었다 | 0017 |
| 2026-10-15 | 1 | **도는 서버 실행을 멈출 수 있다** — 취소 표의 `accepted` 줄이 **대상 종류로 갈린다**(서버는 202, PC는 그대로 409 `already_started`). 판정은 `cancel_outcome(state, target_type)` 한 함수가 쥐고, 대상을 주지 않으면 **옛 규칙대로** 본다. PC 쪽 규칙과 C4는 **바뀌지 않는다** | [0063](../decisions/0063-stopping-a-running-server-run.md) |
| 2026-10-01 | 1 | 검토 반영: 엔드포인트별 권한표(읽기 토큰은 GET만, 연동용 키 신설), 행위자는 키·`X-CHK-Actor`에서, 취소는 202와 `cancel_result`(시작된 작업은 `accepted` 유지), 대상 이름 `server_runner`로 통일, `idempotency_key` 범위·충돌, `version_ambiguous`, 패키지 철회·지원 종료 엔드포인트, 툴팩만 따로 내려받기 | 0017 |
| 2026-10-01 | 1 | 확장 반영: 리소스·확장 경로 권한 | 0018 |
| 2026-10-01 | 1 | 화면 검토 반영: `cancelled_on_pc`, 서버 실행기·Bot UI 운영 경로 권한 | — |

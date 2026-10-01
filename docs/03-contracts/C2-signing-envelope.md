# C2. 해시·서명 봉투

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Admin(서명) → Center(검증·보관) → Bot UI·서버 실행기(다시 검증) |
| 코드 위치 | `packages/contracts/signing.py`, `packages/contracts/hashing.py` |
| 관련 ADR | [0006](../decisions/0006-single-contracts-package.md), [0015](../decisions/0015-run-location.md) |
| 관련 화면 | ADM(명령), CON-02·CON-03 「최근 배치 결정」, CON-06 |

## 목적

다음 일을 **Admin의 개인키 서명**으로만 할 수 있게 한다.

- 패키지 승인·철회
- 배포·배포 철회
- Admin 공개키 추가·철회

관리자 토큰이나 Center API 키가 새도 배포를 만들거나 서명 키를 바꿔치기할 수 없게 하는 마지막 관문이다. Center와 실행하는 쪽은 공개키만 가진다.

## 전송

- 방식: JSON 봉투.
  - 승인 봉투: C5 `PUT /packages/{id}/{version}/signature`로 올린다. Center는 패키지를 내려줄 때 이 봉투를 zip 안 `SIGNATURE` 파일로 **넣어서** 준다. `content_hash`는 `SIGNATURE`를 빼고 계산하므로 해시는 바뀌지 않는다.
  - 배포·철회 봉투: C5로 올린다. 실행하는 쪽에는 C4 하트비트 응답 `deployments[]`로 전달한다.
  - Admin 키 봉투: C5 `POST/DELETE /admin-keys`로 올린다.
- 인증: 봉투 자체가 증명이다. 올리는 HTTP 요청에는 관리자 토큰도 함께 필요하다 (C5). 다만 **토큰만으로는 아무것도 바뀌지 않는다.**
- 멱등성:
  - 같은 봉투를 다시 올리면 200을 돌려준다.
  - 같은 `deployment_id`에 다른 내용이 오면 409 `deployment_conflict`.
  - **철회된 `deployment_id`는 영구히 철회 상태다.** 같은 배포 봉투를 다시 올려도 되살아나지 않고 409 `deployment_revoked`.
- 바이트 보존: Center는 받은 봉투 JSON을 그대로 저장·전달한다 (감사 추적).

## 모델

### 해시

| 이름 | 규칙 |
| --- | --- |
| `canonical_json(x)` | 키 정렬, 구분자 `,` `:` (공백 없음), UTF-8, `ensure_ascii=false`. **서명 대상(`payload`)의 값은 문자열·정수·불리언·null·배열·객체만** 쓴다. 실수는 쓰지 않는다 (언어마다 `1.0`/`1` 표기가 달라 서명이 깨진다) |
| `content_hash(패키지)` | 패키지 안 모든 일반 파일을 상대 경로(`/` 구분) 정렬 순으로 처리한다. 파일마다 `경로` + `\0` + `sha256(내용) hex` + `\n`을 이어 붙이고, 전체를 SHA-256으로 해시한다. `SIGNATURE`는 제외한다. `manifest.json`은 `content_hash` 필드를 뺀 뒤 `canonical_json`으로 바꿔 해시한다. 결과는 `sha256:<hex>` |

### Envelope

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `payload` | Claim | ✓ | 서명 대상 (`kind`로 구분) |
| `key_id` | str | ✓ | 서명한 Admin 키 id. 공개키 raw 32바이트의 SHA-256 앞 16 hex |
| `alg` | `"ed25519"` | ✓ | 다른 값은 거부 |
| `sig` | str | ✓ | base64( Ed25519 서명( sha256( canonical_json(payload) ) ) ) |
| `signed_at` | str | ✓ | ISO 8601 |

### Claim

| kind | 필드 | 뜻 |
| --- | --- | --- |
| `package` | `id`, `version`, `content_hash` | 승인 |
| `package_revoke` | `id`, `version`, `reason`, `revoked_at` | 승인 철회. 이 패키지의 배포가 모두 무효가 되고 내려받기는 410 |
| `deployment` | `deployment_id`(`dep_<hex8>`), `target`, `bpm_process_id`, `version`, `content_hash`, `not_before`?, `expires_at`?, `max_concurrency`? | 배포. 필드별 규칙은 아래 |
| `revoke` | `deployment_id`, `reason`, `revoked_at` | 배포 철회 |
| `extension` | `id`, `version`, `definition_hash` | 외부 확장 정의 승인 (C13). 정의가 서비스 앱 키를 어느 주소로 보낼지 정하므로 배포와 같은 관문을 둔다 |
| `extension_revoke` | `id`, `version`, `reason`, `revoked_at` | 외부 확장 승인 철회. 그 정의를 쓰는 Bot은 실행 불가가 된다 |
| `admin_key` | `key_id`, `public_key`(raw 32바이트 base64), `label` | Admin 공개키 추가. **이미 등록된, 철회되지 않은 다른 Admin 키**가 서명한다 |
| `admin_key_revoke` | `key_id`, `reason`, `revoked_at` | Admin 공개키 철회. 철회되지 않은 Admin 키가 서명한다 (자기 자신도 가능) |

`deployment` 필드 규칙:

- `target`: `{type: "bot_ui" | "server_runner", id}`.
- `not_before`: 없으면 즉시.
- `expires_at`: 없으면 무기한.
- `max_concurrency`: 서버 배포에만 쓴다. 기본 5.

**배포 대상 규칙:**

- `target.type`은 패키지의 `run_location`과 맞아야 한다: `pc`면 `bot_ui`, `server`면 `server_runner`.
- 서버 배포는 `id`에 `"*"`를 쓸 수 있다. 뜻은 Center가 관리하는 모든 서버 실행기다.
- 공유 BPM 프로세스는 패키지 안 `libs/`에 복사되어 들어가므로 따로 배포하지 않는다 (C1).
- 툴팩도 따로 배포하지 않는다. BPM 프로세스 패키지가 `requires.toolpacks[].content_hash`로 해시를 고정하고, 실행하는 쪽이 그 해시로 내려받아 승인 서명을 확인한다.

### Admin 키 처음 등록 (부트스트랩)

- Admin 키가 하나도 없을 때만, **서버에서** 명령으로 첫 키를 넣는다: `chk-center admin-keys bootstrap <public.pem>`. 이 명령은 서버 셸 접근이 있어야 쓸 수 있다.
- 키가 하나라도 있으면 이 명령은 거부되고, 그다음부터는 `admin_key` 봉투로만 추가한다.
- 마지막 남은 Admin 키는 철회할 수 없다 (409 `last_admin_key`). 잠겨서 아무도 서명할 수 없게 되는 것을 막는다.

## 검증 규칙

Center, Bot UI, 서버 실행기가 같은 함수(`contracts.signing.verify`)를 쓴다.

| # | 규칙 | 실패 사유 코드 | 누가 검사 |
| --- | --- | --- | --- |
| V1 | `alg`가 `ed25519`다 | `unsupported_alg` | 모두 |
| V2 | `key_id`가 알려져 있고 철회되지 않았다 | `unknown_key` / `revoked_key` | 모두 |
| V3 | 서명이 `canonical_json(payload)`와 맞는다 | `bad_signature` | 모두 |
| V4 | 기대한 `kind`다 | `wrong_kind` | 모두 |
| V5a | (deployment) `expires_at`이 지나지 않았다 | `expired` | 모두 |
| V5b | (deployment) 지금이 `not_before` 이후다 | `not_yet` | **실행하는 쪽만**, 적용할 때. Center는 예약 배포를 받아 둔다 |
| V6 | (deployment) `target`이 나 자신이다 (`server_runner`의 `"*"`는 모든 서버 실행기와 맞음) | `wrong_target` | 실행하는 쪽 |
| V7 | (deployment) 받은 패키지의 실제 `content_hash`가 봉투와 같고, 패키지 `SIGNATURE`(package claim)도 V1~V3을 통과한다 | `hash_mismatch` / `unsigned_package` | 실행하는 쪽 |
| V8 | (admin_key) 서명 키가 추가하려는 키 자신이 아니다 | `self_signed_key` | Center |

- 실패하면 실행하는 쪽은 설치하지 않는다. C4 `deployment_results`에 `rejected`와 사유 코드를 보낸다 (CON-03 「⛔ 거부」).
- Admin 키나 패키지 승인이 철회되면, 실행하는 쪽은 다음 하트비트에서 해당 Bot을 비활성으로 돌린다. 패키지 파일은 지우지 않는다.

## 예시

```json
{
  "schema": 1,
  "payload": {
    "kind": "deployment",
    "deployment_id": "dep_3f9a1c07",
    "target": {"type": "bot_ui", "id": "bui_a81c22d0"},
    "bpm_process_id": "erp.order-entry",
    "version": "2.1.0",
    "content_hash": "sha256:41ab…",
    "not_before": null,
    "expires_at": "2027-03-31T23:59:59+09:00"
  },
  "key_id": "7c1e0b9f4a2d6e83",
  "alg": "ed25519",
  "sig": "MEUCIQ…",
  "signed_at": "2026-10-01T11:00:00+09:00"
}
```

## 오류

| 상태 코드 | 언제 | 보내는 쪽(Admin)이 할 일 |
| --- | --- | --- |
| 400 | V1~V5a, V8 실패 (`detail.code`) | 키·시각을 확인하고 다시 서명한다 |
| 409 | `deployment_conflict` (같은 id, 다른 내용), `deployment_revoked`, `last_admin_key` | 새 id로 서명한다, 또는 다른 키를 먼저 추가한다 |
| 422 | `not_approved` (패키지가 승인 상태가 아님), `hash_mismatch`, `target_mismatch` (`target.type` ↔ `run_location`), `server_runner_not_available` (M7 전 서버 배포), `float_in_payload` | 메시지대로 고친다 |

## 호환 규칙

- `payload`에 모르는 필드가 있어도 서명 대상이므로 **그대로 보존**한다. 뜻은 무시한다.
- `alg`를 바꾸려면 `schema`를 올린다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (배포 대상 `target{type,id}`, 서버 배포의 `max_concurrency`) | 0015 |
| 2026-10-01 | 1 | 검토 반영: Admin 키 추가·철회도 서명으로 (부트스트랩은 서버 명령), `not_before`는 실행하는 쪽만 검사, `SIGNATURE`는 Center가 내려줄 때 넣음, 툴팩만 해시 고정, 철회된 배포는 되살리지 않음, `package_revoke`, 서명 대상에 실수 금지 | — |
| 2026-10-01 | 1 | 확장 반영: `extension`·`extension_revoke` claim | 0018 |

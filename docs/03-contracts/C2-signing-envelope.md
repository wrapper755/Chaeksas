# C2. 해시·서명 봉투

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-09, [09-gaps](../09-gaps.md) §1 대조) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Center(관리자가 누르면 서버의 키로 서명·보관) → PC 실행기·서버 실행기(다시 검증) |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/signing.py`, `…/hashing.py` (import `chaeksas.contracts.signing`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c2-envelope.json`](../../packages/contracts/schemas/c2-envelope.json) · [`c2-claim-deployment.json`](../../packages/contracts/schemas/c2-claim-deployment.json) · [`c2-claim-package.json`](../../packages/contracts/schemas/c2-claim-package.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0006](../decisions/0006-single-contracts-package.md), [0015](../decisions/0015-run-location.md), [0046](../decisions/0046-no-wildcard-pc-deployment.md), [0047](../decisions/0047-one-deployment-gate.md), [0090](../decisions/0090-center-admin-accounts.md) |
| 관련 화면 | CON-02·CON-06 「승인」, CON-15 「배포」, CON-07 「확장 추가」, CON-03 「최근 배치 결정」 |

## 목적

다음 일을 **서명 봉투**로 남겨, 실행하는 쪽이 Center를 거쳐 받은 것이 **그때 승인·배포한 그것**인지 다시 확인하게 한다.

- 패키지 승인·철회
- 배포·배포 철회
- 외부 확장 등록·철회

**서명하는 것은 Center다** ([ADR-0090](../decisions/0090-center-admin-accounts.md)) — 관리자 계정이 콘솔에서 누르면 Center가 봉투를 지어 **서버에 둔 키**로 서명한다. 실행하는 쪽은 공개키만 가진다(하트비트의 `admin_keys`). 그래서 서명은 **전송 중·보관 중 변조**와 **철회**를 지킨다. 「Center를 쥔 사람도 배포를 못 만든다」는 지키지 않는다 — 대신 승인·배포마다 **누가** 했는지 계정 이름이 남는다 (C5).

## 전송

- 방식: JSON 봉투.
  - 승인 봉투: C5 `PUT /packages/{id}/{version}/signature`를 관리자가 부르면 Center가 짓는다. Center는 패키지를 내려줄 때 이 봉투를 zip 안 `SIGNATURE` 파일로 **넣어서** 준다. `content_hash`는 `SIGNATURE`를 빼고 계산하므로 해시는 바뀌지 않는다.
  - 배포·철회 봉투: C5 `POST·DELETE /deployments`에서 Center가 짓는다. 실행하는 쪽에는 C4 하트비트 응답 `deployments[]`로 전달한다.
  - 외부 확장 봉투: C7 `POST·DELETE /resources/extensions`에서 Center가 짓는다 (C13 E6).
  - **바깥에서 서명한 봉투를 받는 길은 없다.**
- 인증: 관리자(계정 세션 또는 관리자 토큰)만 부를 수 있다 (C5 권한표).
- 멱등성:
  - 이미 승인된 판을 다시 승인하면 그대로 200이다. 배포는 누를 때마다 새 `deployment_id`다.
  - **철회는 영구하다.** 철회된 배포·패키지 승인·외부 확장은 되살아나지 않는다 (409 `deployment_revoked`·`package_revoked`·`extension_revoked`).
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
| `key_id` | str | ✓ | 서명한 키 id (Center 서명 키, 또는 사람이 서명하던 때의 옛 Admin 키). 공개키 raw 32바이트의 SHA-256 앞 16 hex |
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
| `extension` | `id`, `version`, `definition_hash` | 외부 확장 정의 승인 (C13). 정의가 외부 앱을 부르는 길(허용 호스트·인증 방식·작업)을 정하므로 배포와 같은 관문을 둔다 |
| `extension_revoke` | `id`, `version`, `reason`, `revoked_at` | 외부 확장 승인 철회. 그 정의를 쓰는 BPM 프로세스는 실행 불가가 된다 |
| `service_key` | — | **더 만들지 않는다** ([ADR-0102](../decisions/0102-calling-outside-is-pull.md) — 서비스 앱 키가 없어졌다). 이름은 남겨 둔다 — 옛 감사 기록을 읽을 수 있게 |
| `admin_key` · `admin_key_revoke` | — | **더 만들지 않는다** (ADR-0090 — 믿는 키는 Center가 서버 셸 명령으로 다룬다). 이름은 남겨 둔다 — 옛 감사 기록을 읽을 수 있게 |

`deployment` 필드 규칙:

- `target`: `{type: "bot_ui" | "server_runner", id}`.
- `not_before`: 없으면 즉시.
- `expires_at`: 없으면 무기한.
- `max_concurrency`: 서버 배포에만 쓴다. 기본 5.

**배포 대상 규칙:**

- `target.type`은 패키지의 `run_location`과 맞아야 한다: `pc`면 `bot_ui`, `server`면 `server_runner`.
- 서버 배포는 `id`에 `"*"`를 쓸 수 있다. 뜻은 Center가 관리하는 모든 서버 실행기다.
- **PC 배포에는 `"*"`가 없다** — 봉투 하나는 **PC 하나**를 가리킨다 ([ADR-0046](../decisions/0046-no-wildcard-pc-deployment.md)). `{bot_ui, "*"}`는 V6이 `wrong_target`으로 거부하고, **Center도 받아 두지 않는다**(409 `wrong_target` — 받아 두면 모든 PC가 거부해 CON-03이 거짓 ⛔로 찬다). 한쪽만 적어 두면 「적지 않았을 뿐」으로 읽히므로 **없다는 것을 적는다**.
- 공유 BPM 프로세스는 패키지 안 `libs/`에 복사되어 들어가므로 따로 배포하지 않는다 (C1).
- 도구 묶음(툴팩)은 **패키지가 아니다** — 도구는 확장이 기여하고, 코드 있는 도구는 설치 파일로만 온다 ([ADR-0050](../decisions/0050-no-toolpack-kind.md)). 외부 확장 정의는 `extension` 봉투로 등록한다 (아래).

### 믿는 키 (`admin_keys`)

- 믿는 키는 **Center 서명 키**와 사람이 서명하던 때 들어온 **옛 Admin 키**다. Center가 C4·C12 하트비트로 그대로 내려 준다 (`AdminKey` — 「Center」라는 이름이 붙은 것이 Center 키다).
- Center 서명 키는 **Center가 처음 뜰 때 만들어 DB에 둔다**. 서버 셸의 `chk-center signing-key rotate`로 바꾸면 새 키가 그 뒤를 서명하고 **옛 키는 믿는 목록에 남는다**(이미 나간 승인·배포가 산다).
- 키를 믿지 않게 하는 것은 `chk-center signing-key retire <key_id>`뿐이다 — `revoked_at`이 붙고, 그 키가 서명한 승인·배포는 실행하는 쪽에서 V2 `revoked_key`로 거부된다. **지금 서명하는 키는 버릴 수 없다**(먼저 바꾼다).

## 검증 규칙

Center, PC 실행기, 서버 실행기가 같은 함수(`contracts.signing.verify`)를 쓴다.

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
| V8 | (admin_key) 서명 키가 추가하려는 키 자신이 아니다 | `self_signed_key` | **쓰지 않는다** (`admin_key`를 더 만들지 않는다, ADR-0090) |

- 실패하면 실행하는 쪽은 설치하지 않는다. C4 `deployment_results`에 `rejected`와 사유 코드를 보낸다 (CON-03 「⛔ 거부」).
- 서명 키를 버리거나 패키지 승인이 철회되면, 실행하는 쪽은 다음 하트비트에서 해당 BPM 프로세스를 비활성으로 돌린다. 패키지 파일은 지우지 않는다. 배포 철회도 같다 ([ADR-0113](../decisions/0113-field-follows-withdrawn-deployments.md)):
  - **맞추는 것은 Center가 답한 하트비트뿐이다** — 닿지 못하거나 키가 거부되면 아무것도 바꾸지 않는다 (ADR-0007). 답의 `deployments`(C4·C12)는 활성 배포 **전체**라 빈 목록도 목록이다.
  - 「Center 배포」로 설치된 `(id, version)`마다 **지금 설치를 허락할 봉투**(V1~V4·V5a·V5b·V6을 지난 것)가 하나라도 있으면 덮였다. 없으면 비활성이다 — V2 `revoked_key`로 빠진 것도 같다. 같은 판을 다시 배포하면 새 봉투가 다시 덮는다.
  - 덮는 봉투의 `expires_at`은 **실행하는 쪽이 제 시각으로** 계속 본다(가장 늦은 것, 하나라도 없으면 기한 없음) — 지나면 Center 없이도 비활성이다.
  - 비활성은 **새로 시작하지 않는다**는 뜻이다(사전 점검 `deployment_withdrawn`·`deployment_expired`, C4 `readiness`). 도는·기다리는 실행은 그대로이고, 세우는 것은 작업 취소다 (ADR-0063).
  - 「수동 설치」·출처를 모르는 설치는 다루지 않는다 — Center 목록이 들인 것이 아니다.

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

봉투를 짓는 것이 Center라 V1~V4가 실패할 일은 없다 — 받아들이는 규칙은 C5(승인·배포)·C13(외부 확장)이 같은 코드로 보고 같은 코드로 답한다.

| 상태 코드 | 언제 | 부르는 쪽(관리자)이 할 일 |
| --- | --- | --- |
| 409 | `deployment_revoked`·`package_revoked`·`extension_revoked` (철회된 것은 되살아나지 않는다) | 버전을 올려 새로 올린다 |
| 409 | `not_approved` (패키지가 승인 상태가 아님), `deprecated`, `wrong_target` (`target.type` ↔ `run_location`, 또는 **PC 배포의 `"*"`** — ADR-0046) | 승인·버전·대상을 보고 다시 누른다 |
| 404 | `not_found` (가리키는 패키지가 Center에 없다), `target_not_found` (**등록되지 않은 PC**, [ADR-0049](../decisions/0049-deployment-target-must-exist.md)) | 패키지를 먼저 올린다 / 대상을 확인한다 — **`bot_ui_id`는 그 PC가 한 번 등록한 뒤에 생긴다**(C4). 미리 배포해 둘 수는 없다 |
| 422 | `server_runner_not_available` (M7 전 서버 배포) | 메시지대로 고친다 |

## 호환 규칙

- `payload`에 모르는 필드가 있어도 서명 대상이므로 **그대로 보존**한다. 뜻은 무시한다.
- `alg`를 바꾸려면 `schema`를 올린다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-31 | 1 | §검증 규칙의 「비활성으로 돌린다」를 풀어 적었다 — 언제 믿나(답한 하트비트만)·무엇이 덮나·기한은 현장이 본다·도는 실행은 그대로. 배포 철회도 같다 | [0113](../decisions/0113-field-follows-withdrawn-deployments.md) |
| 2026-10-29 | 1 | Claim `service_key`를 더 만들지 않는다 — 서비스 앱 키가 없어졌다 (Center가 앱에 키를 맡기지 않는다) | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-25 | 1 | Claim `service_key` — Center가 서비스 앱에 키를 맡기는 봉투 (C11) | [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 2026-10-24 | 1 | **서명하는 것이 Center가 됐다.** 관리자 계정이 누르면 Center가 서버의 키로 봉투를 짓는다. 바깥 봉투를 받는 길·Admin 키 추가·철회(`admin_key`·`admin_key_revoke`, V8)·첫 키 부트스트랩을 없앴다. 봉투 모양과 V1~V7, 현장의 검증은 **그대로**다 — 믿는 키 목록에 Center 키가 들어갔을 뿐이다 | 0090 |
| 2026-10-12 | 1 | **404 행을 적었다** — 배포 봉투가 없는 패키지(`not_found`)나 **등록되지 않은 PC**(`target_not_found`)를 가리킬 때 받는 답이다. 뒤쪽은 받아 두고 있었다 | 0049 |
| 2026-10-12 | 1 | **배포 봉투를 거절하는 코드·상태를 C5와 맞췄다.** 여기 422 행에 `not_approved`·`hash_mismatch`·`target_mismatch`가 있었는데 Center는 처음부터 409 `not_approved`·`hash_mismatch`·`wrong_target`으로 답했다 (C5는 2026-10-09에 409로 고쳤고 이 표만 남아 있었다). 대상 어긋남의 이름은 **V6과 같은 `wrong_target`**이다 | 0047 |
| 2026-10-11 | 1 | **PC 배포에 `"*"`가 없다는 것을 적었다.** 규칙은 처음부터 「서버 배포는 쓸 수 있다」뿐이었고 V6·`matches`도 그랬지만, 없다는 것을 적지 않아 Center·콘솔이 **PC 쪽 `"*"`를 풀고 있었다**. 한쪽만 적으면 「적지 않았을 뿐」으로 읽힌다 | 0046 |
| 2026-10-01 | 1 | 초안 (배포 대상 `target{type,id}`, 서버 배포의 `max_concurrency`) | 0015 |
| 2026-10-01 | 1 | 검토 반영: Admin 키 추가·철회도 서명으로 (부트스트랩은 서버 명령), `not_before`는 실행하는 쪽만 검사, `SIGNATURE`는 Center가 내려줄 때 넣음, 툴팩만 해시 고정, 철회된 배포는 되살리지 않음, `package_revoke`, 서명 대상에 실수 금지 | — |
| 2026-10-01 | 1 | 확장 반영: `extension`·`extension_revoke` claim | 0018 |

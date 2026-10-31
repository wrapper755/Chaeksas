# C7. Center API: 리소스 목록과 Center API 키 관리

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-10, [09-gaps](../09-gaps.md) §1 대조 — 상태는 토픽에서 온다, C15) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Center ↔ 서비스 앱(공개 정보 읽기), Studio·PC 실행기·서버 실행기·Center 콘솔 → Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/resources.py`, `…/center_keys.py` (import `chaeksas.contracts.resources`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | 리소스 [`c7-extension-resource.json`](../../packages/contracts/schemas/c7-extension-resource.json) · [`c7-service-app-resource.json`](../../packages/contracts/schemas/c7-service-app-resource.json) · [`c7-contributed-resource.json`](../../packages/contracts/schemas/c7-contributed-resource.json) · [`c7-runtime-resource.json`](../../packages/contracts/schemas/c7-runtime-resource.json) / 키 [`c7-center-key-create-request.json`](../../packages/contracts/schemas/c7-center-key-create-request.json) · [`c7-center-key-info.json`](../../packages/contracts/schemas/c7-center-key-info.json) · [`c7-center-key-created.json`](../../packages/contracts/schemas/c7-center-key-created.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0010](../decisions/0010-service-apps.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0018](../decisions/0018-extensions.md), [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md), [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 관련 화면 | CON-07 리소스, CON-11 Center API 키, STU-03 리소스 탐색기, STU-14·15, BUI-11 |

> [ADR-0102](../decisions/0102-calling-outside-is-pull.md) (2026-10-29): 서비스 앱 주소 등록·`/manifest`·`/healthz` 읽기, 외부 앱 키(운영·시험용), 외부 확장 주소 덮어쓰기는 **없다**. 주소·키는 일꾼만 들고, manifest·카탈로그는 일꾼이 올리며(C15 `PUT …/consumers/self/manifest`) 상태는 「마지막으로 가져간 때」가 말한다.

## 목적

이 계약은 두 가지를 정한다.

**1. 리소스 목록.** BPM 프로세스가 실행에 필요로 하는 바깥 자원을 Center 한곳에서 보이게 한다. 자원 종류는 다음과 같다.

- 확장
- 서비스 앱(확장의 서버 부분)과 그 작업
- **확장이 기여한 자원** (예: 사내 확장의 인감 견본)
- 런타임

이 목록은 세 곳에서 쓴다.

- Studio: 리소스 탐색기와 태스크 편집기
- Center: 배포 전 누락 검사
- 운영자: CON-07

**2. Center API 키 관리** (CON-11).

> 상태: **돈다.** 2026-10-29부터 **Center는 바깥 기능을 읽으러 가지 않는다** ([ADR-0102](../decisions/0102-calling-outside-is-pull.md)) — 서비스 앱은 C15 **일꾼**으로 들어와 manifest·카탈로그를 **올리고**, 살아 있음은 「마지막으로 가져간 때」가 말한다. 외부 확장은 정의를 등록하고(관리자 — Center가 봉투에 서명한다, C13 E6·ADR-0090) 그 토픽을 **어댑터 일꾼**이 가져간다. **런타임·확장은 따로 등록받지 않는다** — C4·C12 보고와 일꾼이 올린 manifest에서 모은다. Center API 키 관리는 M2부터 돈다.

**플랫폼 계약은 특정 확장을 모른다** (ADR-0018). 확장이 기여한 자원은 C13 §5의 **공통 카탈로그 형식**으로만 다룬다. 자원의 모양(`data`)은 그 확장이 정하고, Center는 해석하지 않고 넘긴다.

**Center는 바깥 기능의 주소도 키도 들지 않는다** (ADR-0102). 서비스 앱 키는 없어졌고(「누가 불러도 되나」는 배포가 가린다 — C15 §올리기), 외부 앱의 주소·키는 어댑터 일꾼의 설정에만 있다. Center에서 나가는 연결도 없다 — 일꾼이 Center로 들어온다.

## 리소스 모으는 방식

| 종류 | 출처 | 갱신 |
| --- | --- | --- |
| 확장 | 내장·사내: 일꾼 manifest의 `extension` 필드와 실행하는 쪽의 보고(C4·C12 `extensions`). 외부: **그 토픽의 일꾼이 올린 정의**(C15 `PUT …/consumers/self/extension`, Center가 서명 — C13, ADR-0122) | 보고·manifest·정의 올림 때, Center가 뜰 때(일꾼이 빠진 확장 철회) |
| 서비스 앱 | 내장·사내: 그 앱 id를 토픽으로 맡은 **일꾼이 올린 manifest** (C15). 외부: 외부 확장 등록과 함께 생기고 작업 목록은 정의의 어댑터 작업에서 만든다 | 일꾼이 올릴 때 |
| 확장 기여 자원 | **일꾼이 올린 카탈로그** (C15 `PUT …/consumers/self/catalogs/{type}`) — 내장·사내는 서비스 앱이, 외부는 어댑터 일꾼이 정의의 `contributes.resources[].catalog_url`을 읽어 올린다. Center가 외부 주소를 읽지 않는다 | 올릴 때. `revision`이 같으면 다시 쓰지 않는다 |
| 런타임 | PC 실행기 등록·하트비트(C4), 서버 실행기(C12) | 하트비트 때 |

- **상태는 토픽이 말한다** — 그 앱 id를 가져가는 일꾼이 하나라도 있고 마지막으로 가져간 지 90초 안이면 `ok`, 일꾼은 있는데 그보다 오래면 `unreachable`, 들인 일꾼이 없으면 `unknown`(「확인 전」). 외부 확장도 같다(어댑터 일꾼).

## 전송

기본 경로는 `/api/v1`. 권한은 C5 권한표를 따른다. 리소스 읽기는 읽기·관리자 토큰, Studio·PC 실행기·서버 실행기 키가 할 수 있다.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /resources?type=extension\|service_app\|contributed\|runtime[&resource_type=<종류>]` | 읽기 | 목록 |
| `GET /resources/extensions/{id}` | 읽기 | 확장 하나 (C13) |
| `GET /resources/consumer-folder` | 읽기 | Center가 **마지막으로 뜰 때** 일꾼 폴더를 읽은 결과 (`ConsumerFolderScan`, ADR-0122) |
| `GET /resources/service-apps/{app_id}` | 읽기 | 서비스 앱 하나 (manifest 전체) |
| `GET /resources/contributed/{resource_type}/{id}` | 읽기 | 확장 기여 자원 하나 |
| `GET /signing-keys` | **없음** (공개키다) | 믿는 키 목록 (C2 `AdminKey[]` — 하트비트의 `admin_keys`와 같은 것). 어댑터 일꾼이 외부 확장 봉투를 다시 검증하려고 받는다 |

외부 확장은 **그 토픽의 일꾼이 정의를 올린다**(C15 `PUT …/consumers/self/extension` — Center가 봉투에 서명한다, ADR-0122). 콘솔·API로 등록·해제하는 길은 없다. 서비스 앱을 **등록하는 길도 없다** — 일꾼 폴더의 일꾼 파일(C15 §일꾼 들이기)이 그 자리다.

## 모델

### ExtensionResource

| 필드 | 뜻 |
| --- | --- |
| `id`, `version`, `name`, `publisher`, `tier`, `definition_hash` | C13 |
| `protocol` | `chk-c11` / `http-adapter` / 없음 (클라이언트 기여만) |
| `contributes_summary` | 기여 지점별 이름 (예: `task_types: [seal_check]`) |
| `service_app_id`? | 서버 부분 |
| `installed_on` | 이 확장을 가진 PC 실행기·서버 실행기 수와 버전 분포 (C4·C12 보고. Studio는 세지 않음) |
| `status` | 서버 부분 상태. 값은 `ServiceAppResource.status`와 같고 **서버 부분이 아예 없으면 `n/a`**다. 그 토픽을 가져가는 일꾼으로 본다 (§리소스 모으는 방식) |
| `status_reasons`, `checked_at`? | 상태의 사유와 마지막으로 본 때. 서버 부분이 없으면 비어 있다 |
| `definition`, `envelope` | 외부 확장만. 실행하는 쪽이 받아 검증한다 |

### ConsumerFolderScan (일꾼 폴더)

일꾼 폴더(`CHK_CENTER__CONSUMERS_DIR`, 기본 `<데이터>/consumers`)의 일꾼 파일(`<이름>.consumer.json`, C15 §일꾼 들이기)을 Center가 뜰 때 한 번 읽은 결과다 (ADR-0122). 맡은 일꾼이 없어져 거둔 외부 확장도 함께 싣는다. 결과는 메모리에만 있고 다시 뜨면 새로 읽는다.

| 필드 | 뜻 |
| --- | --- |
| `configured` | 폴더가 있나(사람이 적었으면 늘 `true`). `false`면 나머지는 비어 있다 |
| `dir`?, `scanned_at`? | 읽은 폴더와 때 |
| `problem`? | 폴더 자체를 읽지 못한 까닭(없음·폴더가 아님). 있으면 `items`는 비어 있다 |
| `items[]` | 하나마다 `{kind, file?, id?, version?, outcome, code?, message?}`. `kind`: `consumer`(`id`가 일꾼 이름) / `key`(키 파일의 키, `id`가 키 이름 — §폴더 키) / `extension`(맡은 일꾼이 없어 거둔 외부 확장). `outcome`: `registered`(들였다·바꿨다) / `unchanged`(그대로) / `refused`(`unreadable`·`input_invalid`·`token_revoked`·`token_in_use`) / `revoked`(**빠져서** 거뒀다 — `file`이 없다) |

```json
{
  "configured": true,
  "dir": "/consumers",
  "scanned_at": "2026-10-31T09:00:00+09:00",
  "items": [
    {"kind": "consumer", "file": "worker.consumer.json", "id": "worker", "outcome": "unchanged"},
    {"kind": "key", "file": "nowview.key.json", "id": "nowview", "outcome": "registered"},
    {"kind": "consumer", "id": "old-worker", "outcome": "revoked", "message": "폴더에서 빠져 키를 폐기했습니다"},
    {"kind": "extension", "id": "ext-ocr", "version": "1.0.0", "outcome": "revoked",
     "message": "맡은 일꾼이 없어 등록을 해제했습니다"}
  ]
}
```

### ServiceAppResource

| 필드 | 뜻 |
| --- | --- |
| `app_id`, `name`, `version`, `category` | C11 manifest (외부는 C13 정의) |
| `extension_id` | 어느 확장의 서버 부분인가 |
| `base_url` | **없다**(빈 값) — Center는 서비스 앱의 주소를 모른다. 옛 읽는 쪽이 깨지지 않게 칸은 둔다 |
| `console_url` | http(s)만 — 일꾼이 올린 manifest의 값 |
| `operations` | C11 Operation 목록 (외부는 어댑터 Operation에서 만든 같은 모양) |
| `status` | `ok` / `degraded` / `unreachable` / `unknown` (열린 문자열). 화면 표기는 「정상」 / 「저하」 / 「응답 없음」 / 「확인 전」 |
| `status_reasons`, `checked_at`, `manifest_at` | `checked_at`은 마지막으로 가져간 때, `manifest_at`은 manifest를 올린 때 |
| `consumers` | 이 토픽을 가져가는 일꾼 수 |
| `used_by` | 이 앱을 쓰는 BPM 프로세스 (`id@version`, 승인·배포된 것) |

### ContributedResource (확장 기여 자원)

| 필드 | 뜻 |
| --- | --- |
| `resource_type` | 확장이 정한 종류 (예: `seal_specimen`) |
| `id`, `name`, `summary`, `updated_at` | 카탈로그 항목 (C13 §5) |
| `extension_id` | 이 자원을 기여한 확장 |
| `revision` | 카탈로그 판 번호 |
| `data` | 확장 고유 내용. Center는 해석하지 않는다 |
| `used_by` | 이 자원을 쓰는 BPM 프로세스 (C1 `requires.resources`와 대조) |

### RuntimeResource

| 모델 | 필드 |
| --- | --- |
| RuntimeResource | `host{type: bot_ui \| server_runner, id, name}`, `os`, `versions{bot_ui?, core}`, `browsers[]`, `desktop_backend`?, `extensions[]` |

### 목록 응답 공통

`{items: [...], fetched_at}`. Studio는 마지막으로 받은 목록을 캐시하고, 오프라인이면 「(오프라인 — 마지막 확인 <fetched_at>)」을 붙인다 (U8).

## 누락 검사

`contracts.resources.missing(manifest, resources)`가 C1 `requires`를 리소스 목록과 대조한다. 확장 종류를 가리지 않는 같은 규칙이다.

| 검사 | 결과 `type` / `reason` |
| --- | --- |
| `requires.extensions[]`가 있고 버전 범위가 맞나 (외부면 `definition_hash`도) | `extension` / `not_found` / `version_mismatch` / `hash_mismatch` |
| `requires.service_apps[].app_id`가 등록되어 있나 — 서비스 앱(C11)이거나 **같은 id의 외부 확장(HTTP 어댑터)**이면 등록된 것이다 (`chk:serviceCall`은 둘을 가리지 않는다 — C13 §4) | `service_app` / `not_registered` |
| 그 작업이 있나, 결정 수행을 지원하나, 서버 BPM 프로세스면 `server_ok`인가 — 외부 확장이면 어댑터의 `operations[]`에서 본다 | `operation` / `not_found` / `not_deterministic` / `not_server_ok` |
| `requires.resources[]` (`{type, id}`)가 확장 기여 자원에 있나 | `resource` / `not_found` |

- 업로드할 때는 경고만 한다 (CON-02 띠).
- **배포할 때는** C1 R8에 걸리는 것(서버 BPM 프로세스의 작업)과 확장 누락·해시 불일치만 거부한다. 서비스 앱이 잠시 응답이 없다고 배포를 막지는 않는다.

## 외부 앱 키 · 외부 확장 주소 — 없다

외부 앱의 키와 주소는 **어댑터 일꾼의 설정**에만 있다 ([ADR-0102](../decisions/0102-calling-outside-is-pull.md), C13 §4) — Center에 넣는 칸(`PUT …/app-key`·`…/app-key/test`·`…/address`)은 없다. 시험용 키라는 것도 없다: Studio 시험 실행의 일감은 `origin: test`이고, 어댑터 일꾼이 확장마다 시험 쪽 주소·키를 따로 둘 수 있다 (ADR-0102 §6).

## Center API 키 관리 (CON-11)

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /center-keys` `{name, type, expires_at?}` | 관리자 토큰 | 발급. 응답에 **원문 `key`가 한 번만** 실린다 |
| `GET /center-keys?type=&state=` | 읽기·관리자 토큰 | 목록 (원문 없음) |
| `DELETE /center-keys/{key_id}` | 관리자 토큰 | 폐기 |
| `POST /center-keys/{key_id}/unbind` | 관리자 토큰 | PC 묶음 풀기 (PC 실행기용·서버 실행기용) |
| `POST /center-keys/{key_id}/purge` | 관리자 토큰 | **폐기된 키**의 행을 지운다 (204). 폐기되지 않았으면 409 `not_revoked` — 폐기 → 삭제 두 걸음이다 ([0095](../decisions/0095-deleting-revoked-center-keys.md)). 묶였던 PC·서버 자리는 「묶음 풀기」처럼 놓인 자리가 되고, 실행 기록·결재의 `owner_key_id`는 글자로 남는다 |

`type`: `bot_ui`, `studio`, `server_runner`, `integration`, `relay` (열린 문자열이지만 Center는 이 다섯만 발급한다).

- **`bot_ui`·`server_runner`·`studio` 키는 등록 승인이 만든다** (`studio`는 [0093](../decisions/0093-studio-is-let-in-by-approval.md)) (C5 §등록 승인, [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md)). 이 경로로 그 둘을 발급하는 길은 **자동화·시험용**으로 남고(관리자 토큰) CON-11 화면에는 없다. 승인이 만든 키는 `enrollment_id`를 가진다.

- `relay`(**대리 답용 키**, CON-11 표기 「대리 답용」)는 연동하는 쪽이 **사람 대신 결재에 답할 때만** 쓴다 — 결재 읽기·답뿐이고, 그 사람이 담당자일 때만 받는다 (C6, [ADR-0081](../decisions/0081-answering-on-behalf.md)). 연동용 키에 그 권한을 더하지 않은 것은 연동용 키가 **작업을 만드는 바깥 시스템 모두**에 나가기 때문이다. Center는 이 키를 `require_read`·작업·실행 기록 올리기에서 막는다.

CenterKeyInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `key_id` | `ck_<hex8>` |
| `name`, `type` | |
| `prefix` | 앞자리 16자 (`chk_ctr_` + 무작위 8자) |
| `bound_to`? | `{type, id, name, machine_name?, first_seen}` |
| `enrollment_id`? | 등록 승인이 만든 키면 그 요청 (C5 §등록 승인). 없으면 사람이·자동화가 발급한 키다 |
| `created_at`, `expires_at`?, `last_used_at`?, `revoked_at`? | |
| `state` | `active` / `expired` / `revoked`. 화면 표기는 「사용 중」 / 「만료」 / 「폐기됨」 |

- 키 원문은 `chk_ctr_<무작위 40자>`이고, Center는 해시만 저장한다.
- **연동용·대리 답용 키는 일꾼 폴더의 키 파일로도 들인다** (§폴더 키).

### 폴더 키

함께 설치되는 연동 시스템의 키는 설치가 짓는다 ([0123](../decisions/0123-folder-keys.md)) — 일꾼 폴더(`CHK_CENTER__CONSUMERS_DIR`, C15 §일꾼 들이기)의 `<이름>.key.json`(`FolderKey`)을 Center가 **뜰 때 한 번** 읽는다. 원문은 폴더에 없다.

```json
{"name": "nowview", "type": "integration", "token_sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"}
```

| 필드 | 뜻 |
| --- | --- |
| `name` | CON-11에 보이는 키 이름 |
| `type` | `integration` / `relay`만. 다른 것은 `input_invalid` |
| `token_sha256` | 키 원문(UTF-8)의 SHA-256, 소문자 16진 64자. 원문의 권장 꼴은 위 키 원문과 같다(`chk_ctr_` + 40자) — Center는 해시만 맞춘다 |

- **권한은 종류가 정한다** — `POST /center-keys`로 발급한 같은 종류의 키와 같다(C5 권한표). 앞자리(`prefix`)는 빈 글이고(CON-11 「—」) 만료·회전이 없다.
- 키의 자리는 **파일 이름**(확장자 앞)이다. 해시가 바뀌면 옛 키를 폐기하고 새 키를 만든다. **폐기된 토큰은 되살아나지 않고**(`token_revoked`), 다른 키(일꾼 키 포함)가 쓰는 해시는 `token_in_use`다. **파일이 빠지면 폐기한다**(행은 남는다). 읽지 못한 파일은 자리를 지킨다.
- 결과는 `ConsumerFolderScan.items[]`의 `kind: key` 줄이다. `chk-center key-file <이름> --type integration|relay [--dir 폴더]`가 파일을 짓고 원문을 한 번 찍는다.

- 기본 만료는 1년. 만료 14일 전부터 CON-11에 보인다. **등록 승인이 만든 키는 Center가 그때부터 회전한다** (C4 §키 회전) — PC 실행기 알림(BUI-05)은 회전이 7일 전까지 닿지 않았을 때만, 회전하지 않는 키는 14일 전부터다.

## 오류

| 상태 코드 | `code` | 언제 |
| --- | --- | --- |
| 404 | `not_found` | |
| 409 | `not_revoked` | 폐기되지 않은 키를 지우려 함 (`POST /center-keys/{key_id}/purge`) |
| 409 | `id_conflict` | 같은 `id`가 이미 있음 (확장과 서비스 앱이 같은 이름 공간) |
| 422 | `manifest_invalid` | 일꾼이 올린 manifest가 C11과 맞지 않음 |
| 422 | `host_not_allowed` | 외부 주소가 `allowed_hosts` 밖이거나 사설망 |
| 422 | `key_type_unknown` | |

## 호환 규칙

- 상태·종류 값은 열린 문자열이다. 모르는 manifest·카탈로그 필드는 보관하고 무시한다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-11-01 | 1 | §폴더 키 — 일꾼 폴더의 `<이름>.key.json`(`FolderKey`)으로 연동용·대리 답용 키를 들인다. `ConsumerFolderItem.kind`에 `key`. 선택 칸이라 schema는 그대로다 | [0123](../decisions/0123-folder-keys.md) |
| 2026-10-31 | 1 | 일꾼 폴더 — `GET /resources/consumer-folder`(`ConsumerFolderScan`). 외부 확장의 출처가 **일꾼이 올린 정의**가 되었다(C15 `PUT …/self/extension`) — 등록·해제 경로는 C13에서 걷었다. 선택 칸이라 schema는 그대로다 | [0122](../decisions/0122-consumer-folder.md) |
| 2026-10-31 | 1 | 칸은 그대로다. 확장 기여 자원의 예(UI 화면)를 걷고 `RuntimeResource.versions`에서 `worker`를 뺐다 — UI 자동화 확장이 없다 | [0114](../decisions/0114-remove-ui-automation.md) |
| 2026-10-29 | 1 | **Center는 바깥 기능을 읽으러 가지 않는다** — 서비스 앱 등록·주소·해제·`/manifest`·`/healthz`·`trust` 읽기, 외부 앱 키(운영·시험용), 외부 확장 주소 덮어쓰기, 어댑터 `health` 두드리기를 걷었다. 서비스 앱·기여 자원은 일꾼이 올리고 상태는 토픽이 말한다(`consumers` 칸). `base_url`은 빈다 | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-25 | 1 | §외부 확장 주소 — `PUT/DELETE …/extensions/{id}/address`, `ExtensionResource.address{base_url, set_at, set_by}`, 사유 `address_outside_definition`. 선택 칸이라 schema는 그대로다 | [0097](../decisions/0097-external-extension-address-from-center.md) |
| 2026-10-25 | 1 | `GET /signing-keys`(인증 없음), §외부 앱 키(운영 `PUT/DELETE …/extensions/{id}/app-key`·시험용 `…/app-key/test`, `ExtensionResource.app_key{run, test}`), `trust`의 `pin_mismatch`, `ServiceAppResource.trust` | [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 2026-10-25 | 1 | `bot_ui`·`server_runner` 키는 등록 승인이 만든다 — `CenterKeyInfo.enrollment_id?`. 이 경로로 발급하는 길은 자동화·시험용으로 남는다 | [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md) |
| 2026-10-20 | 1 | 키 종류 **`relay`(대리 답용 키)**를 더했다 — CON-11에서 발급한다 | [0081](../decisions/0081-answering-on-behalf.md) |
| 2026-10-12 | 1 | **툴팩 리소스를 뺐다** (`ToolpackResource`·`?type=toolpack`·누락 검사의 `toolpack`) — 툴팩이라는 패키지 갈래가 사라졌다. 고정 종류는 **넷**이다 (확장·서비스 앱·확장 기여 자원·런타임). 도구는 확장이 기여한다 | 0050 |
| 2026-10-01 | 1 | 초안 | 0010, 0013, 0015 |
| 2026-10-01 | 1 | 확장 반영·검토 반영 (아래) | 0018 |

확장 반영·검토 반영 내용:

- 확장 리소스를 더했다.
- UI 화면을 **확장 기여 자원**(공통 카탈로그)으로 일반화했다.
- 외부 앱 상태는 어댑터 `health`로 본다.
- 주소 출처를 하나로 했다 (`PUT …/service-apps`).
- 이름 공간을 하나로 했다.
- 읽기 권한에 PC 실행기·서버 실행기 키를 더했다.
- `installed_on`에서 Studio를 뺐다.
- 누락 검사가 확장 종류를 가리지 않게 했다.

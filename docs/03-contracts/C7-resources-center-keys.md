# C7. Center API: 리소스 목록과 Center API 키 관리

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-10, [09-gaps](../09-gaps.md) §1 대조 — 외부 확장은 어댑터 `health`로 본다) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Center ↔ 서비스 앱(공개 정보 읽기), Studio·Bot UI·서버 실행기·Center 콘솔 → Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/resources.py`, `…/center_keys.py` (import `chaeksas.contracts.resources`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | 리소스 [`c7-extension-resource.json`](../../packages/contracts/schemas/c7-extension-resource.json) · [`c7-service-app-resource.json`](../../packages/contracts/schemas/c7-service-app-resource.json) · [`c7-contributed-resource.json`](../../packages/contracts/schemas/c7-contributed-resource.json) · [`c7-runtime-resource.json`](../../packages/contracts/schemas/c7-runtime-resource.json) / 키 [`c7-center-key-create-request.json`](../../packages/contracts/schemas/c7-center-key-create-request.json) · [`c7-center-key-info.json`](../../packages/contracts/schemas/c7-center-key-info.json) · [`c7-center-key-created.json`](../../packages/contracts/schemas/c7-center-key-created.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0010](../decisions/0010-service-apps.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0018](../decisions/0018-extensions.md), [0092](../decisions/0092-keys-are-issued-and-delivered-by-center.md), [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 관련 화면 | CON-07 리소스, CON-11 Center API 키, STU-03 리소스 탐색기, STU-13·14·15, BUI-11, TOL-03 |

## 목적

이 계약은 두 가지를 정한다.

**1. 리소스 목록.** BPM 프로세스가 실행에 필요로 하는 바깥 자원을 Center 한곳에서 보이게 한다. 자원 종류는 다음과 같다.

- 확장
- 서비스 앱(확장의 서버 부분)과 그 작업
- **확장이 기여한 자원** (예: UI 화면)
- 런타임

이 목록은 세 곳에서 쓴다.

- Studio: 리소스 탐색기와 태스크 편집기
- Center: 배포 전 누락 검사
- 운영자: CON-07

**2. Center API 키 관리** (CON-11).

> 상태: **고정 네 종류와 CON-07이 돈다** (M5 조각 8) — 서비스 앱 등록·주소 바꾸기·해제·새로 고침, `GET /resources`의 확장·서비스 앱·확장 기여 자원·런타임, 누락 검사를 패키지 정보(`missing_resources`)와 배포 거부에 이었다. **런타임·확장은 따로 등록받지 않는다** — Center가 이미 가진 것(C4 보고, 서비스 앱 manifest)에서 모은다. **외부 확장 등록·해제도 돈다** (조각 9 — 관리자가 정의를 올리면 Center가 봉투에 서명한다, C13 E6·ADR-0090). Center API 키 관리는 M2부터 돈다.
>
> **외부 확장의 상태도 돈다** — 어댑터 `health`를 선언한 대로(`{path, expect_status}`) 두드리고, **선언이 없으면 두드리지 않고 「확인 전」으로 둔다** (C11의 `/healthz`를 외부 앱에 들이대지 않는다). 나갈 때는 **어댑터와 같은 관문**(C13 §4-3 1~4)을 지난다 — Center는 `core`를 import할 수 없어 `contracts`의 `resolve_host`를 양쪽이 함께 쓴다. 등록 때 E3가 「허용 호스트 밖·http」를 이미 막으므로, 이 관문이 실제로 잡는 것은 **허용된 이름이 사설 IP로 풀리는 경우**다.
>
> **확장이 기여한 자원도 돈다** (조각 10) — Center가 카탈로그를 읽어 쌓고 CON-07에 종류마다 탭이 생긴다. **출처는 둘이고 모양은 같다**: 내장·사내는 C11 manifest의 `resources`(그 칸을 이 조각에서 더했다 — 정의가 Center에 없기 때문이다), 외부는 등록된 정의의 `contributes.resources`. **`revision`이 같으면 항목을 다시 쓰지 않고**(계획 캐시를 공연히 버리지 않게), **닿지 못하면 들고 있던 것을 지우지 않는다**(사유만 남긴다). 서비스 앱을 등록·주소 변경하는 그 자리에서 카탈로그도 읽는다 — 그래야 「등록했는데 왜 경고가 그대로인가」가 생기지 않는다. `requires.resources` 누락 검사가 이제 실제로 돈다 (배포는 막지 않는다).

**플랫폼 계약은 특정 확장을 모른다** (ADR-0018). 확장이 기여한 자원은 C13 §5의 **공통 카탈로그 형식**으로만 다룬다. 예를 들어 「UI 화면」의 모양은 UI 자동화 확장(C9)이 정하고, Center는 해석하지 않고 넘긴다.

**Center는 서비스 앱 키를 지어 앱에는 해시만 맡긴다** ([ADR-0094](../decisions/0094-service-app-keys-ride-the-deployment.md), C11 §Center가 발급하는 키). 원문은 짓는 자리에서 배포 대상에 봉하고 버리므로 Center DB에는 봉한 덩이가 ack까지만 남는다. **원문을 오래 드는 것은 외부 앱 키뿐**이다(§외부 앱 키). 서비스 앱에서 읽는 것은 인증이 필요 없는 공개 정보다.

- C11 `/healthz`, `/manifest`, `/center/v1/trust`
- 외부 확장 어댑터의 `health`
- 확장의 공개 카탈로그

앱에 보내는 것은 Center가 서명한 봉투(`POST /center/v1/keys`)뿐이다.

## 리소스 모으는 방식

| 종류 | 출처 | 갱신 |
| --- | --- | --- |
| 확장 | 내장·사내: 서비스 앱 `/manifest`의 `extension` 필드와 실행하는 쪽의 보고(C4·C12 `extensions`). 외부: 서명된 정의 등록(C13) | 등록·보고 때 |
| 서비스 앱 | 내장·사내: 운영자가 CON-07에서 주소를 등록하고 Center가 `/manifest`·`/healthz`를 읽는다. 외부: 외부 확장 등록과 함께 생기고, 상태는 어댑터 `health`로 본다 (없으면 「확인 전」) | 상태 60초, manifest 10분, 「새로 고침」 즉시 (`CHK_CENTER__RESOURCE__POLL_S`) |
| 확장 기여 자원 | 확장 정의의 `resources[].catalog_url` (C13 §5) | 5분마다, 「새로 고침」. `revision`이 같으면 건너뛴다 |
| 런타임 | Bot UI 등록·하트비트(C4), 서버 실행기(C12) | 하트비트 때 |

- 서버끼리의 연결(Center → 서비스 앱)은 서버망 안의 일이라 ADR-0007(현장 PC → 서버)과 부딪히지 않는다.
- Center가 외부 주소를 읽을 때도 C13 §4-3의 호출 규칙을 지킨다: `allowed_hosts`, https, 리다이렉트 금지, 사설망 차단, 크기 상한.

## 전송

기본 경로는 `/api/v1`. 권한은 C5 권한표를 따른다. 리소스 읽기는 읽기·관리자 토큰, Studio·Bot UI·서버 실행기 키가 할 수 있다.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /resources?type=extension\|service_app\|contributed\|runtime[&resource_type=ui_page]` | 읽기 | 목록 |
| `GET /resources/extensions/{id}` | 읽기 | 확장 하나 (C13) |
| `GET /resources/service-apps/{app_id}` | 읽기 | 서비스 앱 하나 (manifest 전체) |
| `GET /resources/contributed/{resource_type}/{id}` | 읽기 | 확장 기여 자원 하나 |
| `POST /resources/service-apps` `{base_url}` | 관리자 토큰 | 내장·사내 서비스 앱 등록. Center가 바로 manifest를 읽어 본다 |
| `PUT /resources/service-apps/{app_id}` `{base_url}` | 관리자 토큰 | 주소 바꾸기 (환경별 주소의 유일한 출처) |
| `DELETE /resources/service-apps/{app_id}` | 관리자 토큰 | 등록 해제. 쓰는 Bot이 있으면 409 `in_use` |
| `POST /resources/refresh` `{type?, id?}` | 관리자 토큰 | 바로 다시 읽기 |

외부 확장의 등록·해제는 C13 경로(관리자만 — Center가 봉투에 서명한다)로 한다.

**ADR-0094** —

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /signing-keys` | **없음** (공개키다) | 믿는 키 목록 (C2 `AdminKey[]` — 하트비트의 `admin_keys`와 같은 것). 서비스 앱이 Center를 믿으려고 받는다 (C11) |
| `PUT /resources/extensions/{id}/app-key` `{key}` | 관리자 (계정 세션·관리자 토큰) | 외부 앱 **운영 키** 넣기·바꾸기 (§외부 앱 키). 응답에 원문은 없다 |
| `DELETE /resources/extensions/{id}/app-key` | 관리자 | 운영 키 지우기 |
| `PUT /resources/extensions/{id}/app-key/test` `{key}`, `DELETE …/app-key/test` | 관리자 | **시험용 키** 넣기·바꾸기·지우기 — Studio 시험 실행에만 간다 (§외부 앱 키) |

**ADR-0097** —

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `PUT /resources/extensions/{id}/address` `{base_url}` | 관리자 (계정 세션·관리자 토큰) | 외부 확장 **주소 덮어쓰기** (§외부 확장 주소). 정의의 허용 호스트 밖이면 422 `host_not_allowed` |
| `DELETE /resources/extensions/{id}/address` | 관리자 | 덮어쓴 주소를 지운다 — 정의의 `base_url`(기본값)로 돌아간다 |

## 모델

### ExtensionResource

| 필드 | 뜻 |
| --- | --- |
| `id`, `version`, `name`, `publisher`, `tier`, `definition_hash` | C13 |
| `protocol` | `chk-c11` / `http-adapter` / 없음 (클라이언트 기여만) |
| `contributes_summary` | 기여 지점별 이름 (예: `task_types: [ui_task]`) |
| `service_app_id`? | 서버 부분 |
| `installed_on` | 이 확장을 가진 Bot UI·서버 실행기 수와 버전 분포 (C4·C12 보고. Studio는 세지 않음) |
| `status` | 서버 부분 상태. 값은 `ServiceAppResource.status`와 같고 **서버 부분이 아예 없으면 `n/a`**다. C11 앱은 그 앱의 `/healthz`, 외부 확장은 **어댑터 `health`**(C13 §4-1)로 본다 — 선언이 없으면 `unknown`(「확인 전」)이다 |
| `status_reasons`, `checked_at`? | 상태의 사유와 마지막으로 본 때. 서버 부분이 없으면 비어 있다 |
| `definition`, `envelope` | 외부 확장만. 실행하는 쪽이 받아 검증한다 |
| `app_key` | 외부 확장이고 키를 받는 앱일 때만(ADR-0091 `takes_key()`). `{run: KeySlot, test: KeySlot}` — KeySlot은 `{set: bool, set_at?, set_by?}`. **원문·앞자리는 없다** (§외부 앱 키) |
| `address`? | 외부 확장이고 **Center가 주소를 덮어썼을 때만** `{base_url, set_at, set_by}` (§외부 확장 주소). 없으면 정의의 `service.base_url`을 쓴다 |

외부 확장의 상태를 볼 때 Center는 **어댑터와 같은 관문을 지난다** (C13 §4-3 1~4 — 허용 호스트·사설망·https·DNS 고정). 규칙이 갈라지지 않게 `contracts`의 같은 함수(`resolve_host`)를 쓴다. 관문에 걸리면 두드리지 않고 `unreachable`에 사유를 남긴다 — **정의가 적은 주소라고 해서 Center가 아무 데나 나가지 않는다.**

### ServiceAppResource

| 필드 | 뜻 |
| --- | --- |
| `app_id`, `name`, `version`, `category` | C11 manifest (외부는 C13 정의) |
| `extension_id` | 어느 확장의 서버 부분인가 |
| `base_url` | **주소의 유일한 출처** (C13 Service) |
| `console_url` | http(s)만 |
| `operations` | C11 Operation 목록 (외부는 어댑터 Operation에서 만든 같은 모양) |
| `status` | `ok` / `degraded` / `unreachable` / `unknown` (열린 문자열). 화면 표기는 「정상」 / 「저하」 / 「응답 없음」 / 「확인 전」 |
| `status_reasons`, `checked_at`, `manifest_at` | |
| `used_by` | 이 앱을 쓰는 BPM 프로세스 (`id@version`, 승인·배포된 것) |
| `trust` | `{state, checked_at?}` — 이 앱이 Center 발급을 받나 (C11 `GET /center/v1/trust`를 상태와 같이 60초마다 본다). `state`는 열린 문자열, 알려진 값 `trusted`(이 Center의 지금 서명 키를 믿는다) `not_configured`(앱에 `CENTER__URL`이 없다) `other_center`(다른 주소를 믿는다) `stale_key`(지금 서명 키를 아직 모른다) `pin_mismatch`(앱의 `KEY_PIN`이 이 Center의 키와 다르다 — 서명 키를 바꾼 뒤 앱 설정을 고치지 않았다) `unknown`(묻지 못했다·외부 앱). `trusted`가 아니면 Center는 그 앱의 키를 짓지 않고 CON-07 「할 일」로 말한다 |

### ContributedResource (확장 기여 자원)

| 필드 | 뜻 |
| --- | --- |
| `resource_type` | 예: `ui_page` |
| `id`, `name`, `summary`, `updated_at` | 카탈로그 항목 (C13 §5) |
| `extension_id` | 이 자원을 기여한 확장 |
| `revision` | 카탈로그 판 번호 |
| `data` | 확장 고유 내용. Center는 해석하지 않는다 (UI 화면이면 C9 카탈로그 항목) |
| `used_by` | 이 자원을 쓰는 BPM 프로세스 (C1 `requires.resources`와 대조) |

### ToolpackResource, RuntimeResource

| 모델 | 필드 |
| --- | --- |
| ToolpackResource | `id`, `version`, `status`, `tools`(`[{name, domain, description}]`), `content_hash` |
| RuntimeResource | `host{type: bot_ui \| server_runner, id, name}`, `os`, `versions{bot_ui?, core, worker?}`, `browsers[]`, `desktop_backend`?, `extensions[]` |

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

## 외부 앱 키

> 상태: **돈다** (2026-10-25, [ADR-0094](../decisions/0094-service-app-keys-ride-the-deployment.md) §7, ADR-0092 §4).

외부 앱의 키는 우리가 발급할 수 없어서 관리자가 CON-07에서 **한 번** 넣는다.

- 받는 것은 키를 받는 외부 확장(`takes_key()`)뿐이다. 아니면 422 `takes_no_key`. 키는 ASCII여야 한다(어댑터가 거절한다 — C13 §4) — 아니면 422 `key_not_ascii`.
- Center는 **서명 키와 같은 자리에 암호화해** 둔다. 응답·목록·화면 어디에도 원문이 다시 나오지 않는다 — `app_key`에는 넣었는지·언제·누가만 있다.
- 그 확장을 쓰는 Bot의 **배포 대상마다** 같은 원문을 봉해 하트비트로 내려 준다 (C4 §서비스 앱 키 전달 `source: external`). 바꾸면 모든 대상에 새로 내려 주고(옛 것은 `replaces`), 지우면 `drop_service_keys`로 보낸다.
- **운영 키는 Studio에 내려 주지 않는다** (ADR-0094 §7).
- **시험용 키는 따로 넣는다** — 같은 보관·같은 규칙(ASCII·원문 다시 안 보임)이고 **Studio에만** 간다(C5 §Studio 개발 키). 배포 대상에는 늘 운영 키가 간다. 시험용 키가 없으면 Studio가 「관리자가 시험용 키를 넣지 않았습니다」라고 말하고, 환경변수 `CHK_STUDIO__SVC__<참조>`가 있으면 그것이 이긴다.
- 외부 확장을 등록 해제하면 그 키도 지운다.

## 외부 확장 주소

> 상태: **돈다** (2026-10-25, [ADR-0097](../decisions/0097-external-extension-address-from-center.md)).

C13은 「Center 리소스 등록의 `base_url`이 이긴다」고 적었다. 서비스 앱은 등록이 곧 주소이고, **외부 확장은 이 칸으로 덮어쓴다** — 정의를 한 벌로 두고 환경(= 연결한 Center)마다 주소를 고르게 하려고다.

- 받는 것은 **등록된 외부 확장**(`http-adapter`)뿐이다. 아니면 404 `not_found`.
- **정의를 넓히지 않는다.** 주소는 그 정의의 `allowed_hosts`·`allow_private_network`로 **어댑터와 같은 관문**(`contracts.extension.resolve_host`)을 지나야 받는다 — 허용 호스트 밖·사설망·`https`가 아닌 공용 주소는 422 `host_not_allowed`. Center에서 이름이 풀리지 않는 것(DNS)만은 막지 않는다 — 부르는 곳(PC·서버)에서는 풀릴 수 있고, 부를 때 같은 관문이 다시 본다. 경로·쿼리는 받지 않는다(어댑터가 `base_url`의 경로를 버린다) — 422 `host_not_allowed`.
- 실행하는 쪽(Bot UI·서버 실행기·Studio)은 `ExtensionResource.address.base_url`을 **명부의 주소**로 넣는다(`core.app_directory`). 그래서 어댑터가 정의의 값보다 먼저 쓴다 — 코드가 하나다. **부를 때도 그 정의의 허용 호스트로 다시 본다** — Center가 틀린 주소를 주어도 서명된 정의 밖으로는 나가지 않는다.
- Center의 상태 점검(어댑터 `health`)도 덮어쓴 주소로 간다.
- **새 판을 등록해 허용 호스트가 바뀌어 덮어쓴 주소가 밖이 되면** Center는 그 주소를 **내려 주지 않고**(정의의 기본값이 쓰인다) `status_reasons`에 `address_outside_definition`을 남긴다. 지우지는 않는다(다음 판에서 다시 맞을 수 있다 — 사람이 지운다).
- 외부 확장을 등록 해제하면 덮어쓴 주소도 지운다.

## Center API 키 관리 (CON-11)

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /center-keys` `{name, type, expires_at?}` | 관리자 토큰 | 발급. 응답에 **원문 `key`가 한 번만** 실린다 |
| `GET /center-keys?type=&state=` | 읽기·관리자 토큰 | 목록 (원문 없음) |
| `DELETE /center-keys/{key_id}` | 관리자 토큰 | 폐기 |
| `POST /center-keys/{key_id}/unbind` | 관리자 토큰 | PC 묶음 풀기 (Bot UI용·서버 실행기용) |
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
- 기본 만료는 1년. 만료 14일 전부터 CON-11에 보인다. **등록 승인이 만든 키는 Center가 그때부터 회전한다** (C4 §키 회전) — Bot UI 알림(BUI-05)은 회전이 7일 전까지 닿지 않았을 때만, 회전하지 않는 키는 14일 전부터다.

## 오류

| 상태 코드 | `code` | 언제 |
| --- | --- | --- |
| 404 | `not_found` | |
| 409 | `in_use` | 쓰는 서비스 앱·확장 해제 |
| 409 | `not_revoked` | 폐기되지 않은 키를 지우려 함 (`POST /center-keys/{key_id}/purge`) |
| 409 | `id_conflict` | 같은 `id`가 이미 있음 (확장과 서비스 앱이 같은 이름 공간) |
| 422 | `manifest_unreachable` / `manifest_invalid` | 등록 때 manifest를 읽지 못하거나 C11과 맞지 않음 |
| 422 | `host_not_allowed` | 외부 주소가 `allowed_hosts` 밖이거나 사설망 |
| 422 | `key_type_unknown` | |
| 422 | `takes_no_key` / `key_not_ascii` | 키를 받지 않는 외부 앱에 키를 넣음 / ASCII가 아닌 키 (§외부 앱 키) |

## 호환 규칙

- 상태·종류 값은 열린 문자열이다. 모르는 manifest·카탈로그 필드는 보관하고 무시한다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
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
- 읽기 권한에 Bot UI·서버 실행기 키를 더했다.
- `installed_on`에서 Studio를 뺐다.
- 누락 검사가 확장 종류를 가리지 않게 했다.

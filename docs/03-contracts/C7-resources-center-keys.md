# C7. Center API: 리소스 목록과 Center API 키 관리

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Center ↔ 서비스 앱(공개 정보 읽기), Studio·Bot UI·서버 실행기·Center 콘솔 → Center |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/resources.py`, `…/center_keys.py` (import `chaeksas.contracts.resources`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | 리소스 [`c7-extension-resource.json`](../../packages/contracts/schemas/c7-extension-resource.json) · [`c7-service-app-resource.json`](../../packages/contracts/schemas/c7-service-app-resource.json) · [`c7-contributed-resource.json`](../../packages/contracts/schemas/c7-contributed-resource.json) · [`c7-toolpack-resource.json`](../../packages/contracts/schemas/c7-toolpack-resource.json) · [`c7-runtime-resource.json`](../../packages/contracts/schemas/c7-runtime-resource.json) / 키 [`c7-center-key-create-request.json`](../../packages/contracts/schemas/c7-center-key-create-request.json) · [`c7-center-key-info.json`](../../packages/contracts/schemas/c7-center-key-info.json) · [`c7-center-key-created.json`](../../packages/contracts/schemas/c7-center-key-created.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0010](../decisions/0010-service-apps.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0018](../decisions/0018-extensions.md) |
| 관련 화면 | CON-07 리소스, CON-11 Center API 키, STU-03 리소스 탐색기, STU-13·14·15, BUI-06·11 |

## 목적

이 계약은 두 가지를 정한다.

**1. 리소스 목록.** BPM 프로세스가 실행에 필요로 하는 바깥 자원을 Center 한곳에서 보이게 한다. 자원 종류는 다음과 같다.

- 확장
- 서비스 앱(확장의 서버 부분)과 그 작업
- **확장이 기여한 자원** (예: UI 화면)
- 툴팩
- 런타임

이 목록은 세 곳에서 쓴다.

- Studio: 리소스 탐색기와 태스크 편집기
- Center: 배포 전 누락 검사
- 운영자: CON-07

**2. Center API 키 관리** (CON-11).

**플랫폼 계약은 특정 확장을 모른다** (ADR-0018). 확장이 기여한 자원은 C13 §5의 **공통 카탈로그 형식**으로만 다룬다. 예를 들어 「UI 화면」의 모양은 UI 자동화 확장(C9)이 정하고, Center는 해석하지 않고 넘긴다.

**Center는 서비스 앱 키를 갖지 않는다** (ADR-0013). 서비스 앱에서 읽는 것은 인증이 필요 없는 공개 정보뿐이다.

- C11 `/healthz`, `/manifest`
- 외부 확장 어댑터의 `health`
- 확장의 공개 카탈로그

## 리소스 모으는 방식

| 종류 | 출처 | 갱신 |
| --- | --- | --- |
| 확장 | 내장·사내: 서비스 앱 `/manifest`의 `extension` 필드와 실행하는 쪽의 보고(C4·C12 `extensions`). 외부: 서명된 정의 등록(C13) | 등록·보고 때 |
| 서비스 앱 | 내장·사내: 운영자가 CON-07에서 주소를 등록하고 Center가 `/manifest`·`/healthz`를 읽는다. 외부: 외부 확장 등록과 함께 생기고, 상태는 어댑터 `health`로 본다 (없으면 「확인 전」) | 상태 60초, manifest 10분, 「새로 고침」 즉시 (`CHK_CENTER__RESOURCE__POLL_S`) |
| 확장 기여 자원 | 확장 정의의 `resources[].catalog_url` (C13 §5) | 5분마다, 「새로 고침」. `revision`이 같으면 건너뛴다 |
| 툴팩 | Center에 올라온 `kind=toolpack` 패키지 (C5) | 업로드·승인 때 |
| 런타임 | Bot UI 등록·하트비트(C4), 서버 실행기(C12) | 하트비트 때 |

- 서버끼리의 연결(Center → 서비스 앱)은 서버망 안의 일이라 ADR-0007(현장 PC → 서버)과 부딪히지 않는다.
- Center가 외부 주소를 읽을 때도 C13 §4-3의 호출 규칙을 지킨다: `allowed_hosts`, https, 리다이렉트 금지, 사설망 차단, 크기 상한.

## 전송

기본 경로는 `/api/v1`. 권한은 C5 권한표를 따른다. 리소스 읽기는 읽기·관리자 토큰, Studio·Bot UI·서버 실행기 키가 할 수 있다.

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /resources?type=extension\|service_app\|contributed\|toolpack\|runtime[&resource_type=ui_page]` | 읽기 | 목록 |
| `GET /resources/extensions/{id}` | 읽기 | 확장 하나 (C13) |
| `GET /resources/service-apps/{app_id}` | 읽기 | 서비스 앱 하나 (manifest 전체) |
| `GET /resources/contributed/{resource_type}/{id}` | 읽기 | 확장 기여 자원 하나 |
| `POST /resources/service-apps` `{base_url}` | 관리자 토큰 | 내장·사내 서비스 앱 등록. Center가 바로 manifest를 읽어 본다 |
| `PUT /resources/service-apps/{app_id}` `{base_url}` | 관리자 토큰 | 주소 바꾸기 (환경별 주소의 유일한 출처) |
| `DELETE /resources/service-apps/{app_id}` | 관리자 토큰 | 등록 해제. 쓰는 Bot이 있으면 409 `in_use` |
| `POST /resources/refresh` `{type?, id?}` | 관리자 토큰 | 바로 다시 읽기 |

외부 확장의 등록·해제는 C13 경로(서명 봉투 필요)로 한다.

## 모델

### ExtensionResource

| 필드 | 뜻 |
| --- | --- |
| `id`, `version`, `name`, `publisher`, `tier`, `definition_hash` | C13 |
| `protocol` | `chk-c11` / `http-adapter` / 없음 (클라이언트 기여만) |
| `contributes_summary` | 기여 지점별 이름 (예: `task_types: [ui_task]`) |
| `service_app_id`? | 서버 부분 |
| `installed_on` | 이 확장을 가진 Bot UI·서버 실행기 수와 버전 분포 (C4·C12 보고. Studio는 세지 않음) |
| `status` | 서버 부분 상태 (없으면 `n/a`) |
| `definition`, `envelope` | 외부 확장만. 실행하는 쪽이 받아 검증한다 |

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
| `requires.service_apps[].app_id`가 등록되어 있나 | `service_app` / `not_registered` |
| 그 작업이 있나, 결정 수행을 지원하나, 서버 BPM 프로세스면 `server_ok`인가 | `operation` / `not_found` / `not_deterministic` / `not_server_ok` |
| `requires.resources[]` (`{type, id}`)가 확장 기여 자원에 있나 | `resource` / `not_found` |
| `requires.toolpacks[]`의 해시가 Center의 승인된 툴팩과 같나 | `toolpack` / `not_found` / `hash_mismatch` / `not_approved` |

- 업로드할 때는 경고만 한다 (CON-02 띠).
- **배포할 때는** C1 R8에 걸리는 것(서버 BPM 프로세스의 작업)과 확장 누락·해시 불일치만 거부한다. 서비스 앱이 잠시 응답이 없다고 배포를 막지는 않는다.

## Center API 키 관리 (CON-11)

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /center-keys` `{name, type, expires_at?}` | 관리자 토큰 | 발급. 응답에 **원문 `key`가 한 번만** 실린다 |
| `GET /center-keys?type=&state=` | 읽기·관리자 토큰 | 목록 (원문 없음) |
| `DELETE /center-keys/{key_id}` | 관리자 토큰 | 폐기 |
| `POST /center-keys/{key_id}/unbind` | 관리자 토큰 | PC 묶음 풀기 (Bot UI용·서버 실행기용) |

`type`: `bot_ui`, `studio`, `server_runner`, `integration` (열린 문자열이지만 Center는 이 넷만 발급한다).

CenterKeyInfo 필드:

| 필드 | 뜻 |
| --- | --- |
| `key_id` | `ck_<hex8>` |
| `name`, `type` | |
| `prefix` | 앞자리 16자 (`chk_ctr_` + 무작위 8자) |
| `bound_to`? | `{type, id, name, machine_name?, first_seen}` |
| `created_at`, `expires_at`?, `last_used_at`?, `revoked_at`? | |
| `state` | `active` / `expired` / `revoked`. 화면 표기는 「사용 중」 / 「만료」 / 「폐기됨」 |

- 키 원문은 `chk_ctr_<무작위 40자>`이고, Center는 해시만 저장한다.
- 기본 만료는 1년. 만료 14일 전부터 CON-11과 해당 Bot UI 알림(BUI-05)에 보인다.

## 오류

| 상태 코드 | `code` | 언제 |
| --- | --- | --- |
| 404 | `not_found` | |
| 409 | `in_use` | 쓰는 서비스 앱·확장 해제 |
| 409 | `id_conflict` | 같은 `id`가 이미 있음 (확장과 서비스 앱이 같은 이름 공간) |
| 422 | `manifest_unreachable` / `manifest_invalid` | 등록 때 manifest를 읽지 못하거나 C11과 맞지 않음 |
| 422 | `host_not_allowed` | 외부 주소가 `allowed_hosts` 밖이거나 사설망 |
| 422 | `key_type_unknown` | |

## 호환 규칙

- 상태·종류 값은 열린 문자열이다. 모르는 manifest·카탈로그 필드는 보관하고 무시한다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
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

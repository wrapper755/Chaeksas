# C13. 확장 정의 (extension.json)

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-12). 모델·검사 규칙(E1~E7)과 **기여 지점마다 읽는 쪽**이 있다 — 확장 호스트(`core.extensions`), Studio(팔레트·편집기·`studio.resource_views`), PC 실행기(확장별 설정·사전 점검), 콘솔(`console.pages` 생성물), Center(외부 확장 등록). **지금 설치 파일에 든 내장 확장은 없다** — 호스트 규칙은 시험용 가짜 확장으로 본다 ([ADR-0114](../decisions/0114-remove-ui-automation.md)) |
| schema | 2 (1은 옛 기여 지점의 명령 배열을 쓰던 것 — 아래 변경 이력) |
| 보내는 쪽 → 받는 쪽 | 확장 작성자 → Studio·PC 실행기·실행기·서버 실행기(확장 호스트), Center(리소스 목록·검사), 관리 콘솔 |
| 코드 위치 | `chaeksas.contracts.extension`, 인터페이스 `packages/extension_api/`, 호스트 `chaeksas.core.extensions` |
| 관련 ADR | [0018](../decisions/0018-extensions.md), [0010](../decisions/0010-service-apps.md), [0013](../decisions/0013-api-keys.md), [0041](../decisions/0041-extension-run-events.md), [0042](../decisions/0042-extension-contributed-panels.md), [0112](../decisions/0112-escalation-review-from-extensions.md), [0114](../decisions/0114-remove-ui-automation.md) |
| 관련 화면 | BUI-03·11, STU-03·14·15, CON-07, SVC-00 |

> 상태: **외부 확장 등록·해제가 돈다** (M5 조각 9) — `POST/DELETE /resources/extensions`를 **관리자가 부르면** E1·E2·E3을 검사하고 **Center가 C2 `extension`·`extension_revoke` 봉투에 서명해**(ADR-0090) 정의와 봉투를 **그대로** 보관한다 — 실행하는 쪽이 다시 검증한다(E6). CON-07 「확장」 탭에서 정의 파일 하나를 올린다. **E4는 외부 확장으로 띄울 수 없다** — `task_types`가 `entry`(코드)를 요구하고 E1이 그것을 먼저 막기 때문이다. 그 겹침은 설치된 확장들 사이에서만 생기고 확장 호스트가 본다.
>
> `contributes.resources[].catalog_url`은 Center가 읽어 쌓는다 (M5 조각 10) — 내장 확장의 정의가 Center에 없어 `catalog_url`을 찾을 길이 없던 구멍은 **C11에 카탈로그 칸을 더해** 메웠다 (C11 §모델 연결 아래 `resources`).
>
> **HTTP 어댑터 해석기(§4-2·§4-3)가 돈다** (M5 조각 11) — `chaeksas.core.http_adapter`. 템플릿은 위치마다 다르게 채우고(경로는 조각 하나로 퍼센트 인코딩, 헤더는 제어 문자·`Authorization`/`Host`/`Cookie` 거부, 본문은 **칸 전체가 슬롯이면 값 그대로**), 나가기 전에 `allowed_hosts` → **DNS 한 번 풀어 그 IP로** → 사설·루프백 → https를 본다. 리다이렉트를 따라가지 않고, `max_response_kb`는 **읽는 동안** 끊는다. 키는 참조 이름으로 받아 이 PC에서 풀고 **ASCII가 아니면 거절한다**(헤더에 넣을 수 없다). `AdapterCaller`가 `ServiceCaller` 자리에 들어가므로 **엔진은 서비스 앱인지 외부 앱인지 모른다**.
>
> **실행하는 쪽은 정의만 본다** ([ADR-0102](../decisions/0102-calling-outside-is-pull.md)) — 외부 앱을 **부르는 것은 어댑터 일꾼**이고 실행하는 쪽은 C15로 올린다. 그래도 PC 실행기·서버 실행기·Studio는 BPM 프로세스를 띄우기 **전에** `GET /resources/extensions/{id}`(정의·봉투)를 받아 `chaeksas.core.app_directory`로 **봉투를 다시 검증하고**(E6) **패키지가 고정한 `definition_hash`와 대조해**(C1) 다르면 **시작조차 하지 않는다** — 중간에 알면 이미 한 일을 되돌릴 수 없다. 닿지 못하면 들고 있던 것을 쓰고(ADR-0007), 404는 버린다(철회는 보안 동작이다). 묻는 대상은 매니페스트의 `requires.extensions` **전부**이고 어느 것이 외부인가는 Center의 답이 말해 준다. **서비스 앱 주소는 받지 않는다** — 누구도 들지 않는다.
>
> **어댑터 일꾼**(`chk-adapter-consumer`, `apps/adapter_consumer`)은 같은 정의를 일꾼 토큰으로 받아 봉투를 다시 검증하고 §4를 돌린다. **주소·키는 그 일꾼의 설정이 쥔다** — 확장마다 `CHK_ADAPTER__EXT__<확장>__BASE_URL`(없으면 정의의 `base_url`)·`…__KEY`(키를 받는 앱만)·`…__TEST_BASE_URL`·`…__TEST_KEY`(시험 일감 — `origin: test` — 에 쓴다, 없으면 운영 쪽)·`CHK_ADAPTER__ALLOW_PRIVATE_NETWORK`(정의가 허용해도 일꾼 설정이 또 열어야 사설 IP로 나간다 — 기본 닫힘). OAuth·mTLS 같은 인증을 늘리는 일도 이 일꾼 안의 일이다.



## 목적

확장 하나가 무엇을 더하는지 선언한다. 플랫폼은 이 파일만 보고 기여를 끼워 넣는다. 특정 확장 이름을 플랫폼 코드에 쓰지 않는다.

## 전송

### 내장·사내 확장

- 확장 패키지 안에 `extension.json`을 둔다. 확장 호스트가 엔트리 포인트 `chaeksas.extensions`로 찾는다.
  - **파이썬 패키지 안**이다 (`extensions/<id>/src/chaeksas/ext/<id>/extension.json`). 호스트가 `importlib.resources`로 읽으므로, 패키지 밖에 두면 설치 파일로 묶은 뒤 사라진다 ([ADR-0024](../decisions/0024-desktop-packaging-extensions.md)).
- 정의는 설치 파일에 들어 있으므로 서명된 설치 파일이 곧 신뢰의 근거다.
- 실행하는 쪽(PC 실행기, 서버 실행기)은 설치된 확장의 `{id, version, definition_hash}`를 Center에 보고한다 (C4·C12 `extensions`).
- 서버 부분이 있으면 그 서비스 앱의 `/manifest`가 `extension: {id, version, definition_hash}`를 싣는다 (C11).

### 외부 확장

외부 확장은 정의 파일만 있다. **서명된 봉투 없이는 쓰이지 않는다.**

정의가 외부 앱을 부르는 길(허용 호스트·인증 방식·작업)을 정하기 때문에, 배포와 같은 관문을 둔다 — **관리자만** 등록하고, 등록하면 Center가 C2 `extension` claim(`{id, version, definition_hash}`)에 서명한다 ([ADR-0090](../decisions/0090-center-admin-accounts.md)). 실행하는 쪽은 봉투로 「Center가 등록한 그 정의인가」를 다시 본다.

1. 관리자가 CON-07 「확장 추가」에서 정의 파일을 올린다. **또는** 배포가 정의 파일(`*.extension.json`)을 Center의 **확장 폴더**(`CHK_CENTER__EXTENSIONS_DIR`)에 복사해 두면 Center가 **뜰 때** 들인다 ([ADR-0121](../decisions/0121-extension-folder.md) — 폴더에 쓸 수 있는 사람을 관리자로 본다. 파일에는 정의만 있다).
2. Center가 E1·E2·E3·E4를 보고, 지나면 봉투에 서명해 정의와 함께 둔다. 두 길이 **같은 관문**이다.

확장 폴더는 덮어쓰지도 되돌리지도 않는다 — 같은 판·같은 내용은 그대로, 같은 판에 다른 내용·철회된 판은 거절, **더 높은 판이 이미 있으면 건너뛴다**. 폴더에서 지운 파일의 등록은 남는다(해제는 사람이 한다). 잘못된 파일은 Center를 막지 않고 사유가 C7 `GET /resources/extension-folder`로 나온다.

| 경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /api/v1/resources/extensions` `{definition}` | 관리자 (계정·토큰) — Center가 C2 `extension` 봉투에 서명한다 | 외부 확장 등록 |
| `GET /api/v1/resources?type=extension` | 읽기·관리자 토큰, Studio·PC 실행기·서버 실행기 키 (C5 권한표) | 목록 |
| `GET /api/v1/resources/extensions/{id}` | 같음 | 하나 (외부면 정의와 봉투 포함) |
| `DELETE /api/v1/resources/extensions` `{id, version, reason?}` | 관리자 — Center가 C2 `extension_revoke` 봉투에 서명한다 | 해제. **쓰는 BPM 프로세스가 있어도 막지 않는다** (아래) |

- **실행하는 쪽은 받은 외부 정의의 봉투를 다시 검증한다** (C2 V1~V3, `definition_hash` 일치). 검증되지 않은 정의는 쓰지 않는다.
- **해제는 쓰는 BPM 프로세스가 있어도 막지 않는다.** 서비스 앱 등록 해제(C7 `in_use`)와 다르다 — 그쪽은 운영자의 장부 정리지만, 확장 해제는 **정의에 문제가 있어 거두는 보안 동작**이다 (관리자만 하는 이유도 그것이다). 쓰는 BPM 프로세스가 있다고 남겨 두면 그게 더 위험하다. 몇 개가 실행 불가가 되는지는 화면이 미리 말한다 (CON-07). 철회된 `id`·`version`은 **되살아나지 않는다** — 고치려면 버전을 올린다.
- 같은 `id`·`version`·같은 내용이면 200, 같은 `id`·`version`인데 내용이 다르면 409 `version_conflict`. 내용을 바꾸려면 버전을 올린다.
- **이름 공간은 하나다.** 확장 `id`는 서비스 앱 `app_id`와 같은 공간을 쓴다. 이미 있는 확장·서비스 앱과 `id`가 같으면 409 `id_conflict`.
- BPM 프로세스 매니페스트(C1)의 `requires.extensions[]`는 외부 확장이면 `definition_hash`까지 고정한다. 정의가 바뀌면 BPM 프로세스를 다시 승인·배포해야 한다.
- 크기 한도: 256 KB.

`definition_hash` = `sha256:<hex>` of `canonical_json(정의)` (C2 규칙).

## 모델

### ExtensionManifest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 2 |
| `id` | str | ✓ | `^[a-z][a-z0-9-]{1,49}$`. 서버 부분이 있으면 그 `app_id`와 같다 (예: `seal-check`) |
| `version` | str | ✓ | SemVer |
| `name` | str | ✓ | 화면 표시 이름 |
| `description` | str | | 화면 표시 설명 |
| `publisher` | str | ✓ | 화면 표시 제공자 |
| `tier` | `builtin` \| `internal` \| `external` | ✓ | 등급 (ADR-0018 §3) |
| `api` | str | 내장·사내 ✓ | 필요한 `extension_api` 버전 범위 (예: `>=2,<3`) |
| `service` | Service | | 서버 부분 (아래) |
| `contributes` | Contributes | ✓ | 기여 (아래) |
| `requires_keys` | KeyNeed[] | | 이 확장이 제 앱을 부르나 (이름은 옛것이다 — 키는 없다, 아래 KeyNeed) |
| `docs_url`, `console_url` | str | | `http(s)://`만 (콘솔이 링크로 보이므로) |

### Service

| 필드 | 뜻 |
| --- | --- |
| `protocol` | `chk-c11`(C11을 따르는 서비스 앱) 또는 `http-adapter`(외부 앱, §4) |
| `base_url` | 기본 주소. **쓰는 쪽은 그 서버 부분을 부르는 일꾼 하나다** — C11 앱은 제 자리에 떠 있고(누구도 이 주소로 부르지 않는다, 참고로만 남는다), 외부 앱은 어댑터 일꾼이 쓰되 **일꾼 설정의 `BASE_URL`이 이긴다**(정의의 `allowed_hosts`·`allow_private_network` 안에서만, ADR-0102) |
| `adapter` | `protocol=http-adapter`일 때만 (§4) |

### Contributes

| 키 | 모양 | 누가 쓰나 | 외부 확장 |
| --- | --- | --- | --- |
| `task_types` | `[{id, label, icon, bpmn: "serviceTask", editor, executor, run_locations}]` | Studio 팔레트·속성 패널, 실행기 | 불가 (서비스 앱 태스크로 씀) |
| `studio.editors` | `[{task_type, entry}]` | Studio | 불가 (자동 폼) |
| `studio.resource_views` | `[{id, label, resource_type, creates_task_type?, creates_task_field?}]` | STU-03 | 가능 (선언) |
| `configuration` | `[{key, label, scope, schema, secret}]` | 설정 화면 칸 (BUI-03 「확장별 설정」, STU-10, 서버 실행기 설정) | 불가 |
| `preflight` | `[{id, entry}]` | Studio·PC 실행기·서버 실행기 사전 점검 | 불가 |
| `console.pages` | `[{id, label, module}]` | 서비스 앱 관리 콘솔 | 불가 (자기 콘솔 링크만) |
| `resources` | `[{type, label, catalog_url}]` | Center 리소스 목록 (C7) | 가능 |

**걷은 기여 지점** — `bot_ui.utilities`·`tool_ui.tools`·`bot_ui.panels`·`bot_ui.local_runtimes`·`agent_environments`는 아무 호스트도 읽지 않는다 ([ADR-0114](../decisions/0114-remove-ui-automation.md)). 정의에 적혀 있으면 호스트가 **경고 한 줄**을 남기고(`LEGACY_CONTRIBUTION_KEYS` — 모르는 열쇠라고 조용히 사라지지 않게) 그 열쇠만 읽지 않는다. 그 열쇠 하나로 확장을 끄지는 않는다.

필드 설명:

- `run_locations`: 이 태스크 종류를 쓸 수 있는 실행 위치 (`pc`·`server`).
  - **`server`를 적는 것은 「화면도, 그 PC에만 있는 자원도 필요 없다」는 약속이다** ([ADR-0064](../decisions/0064-extension-tasks-on-the-server.md)) — 서버 실행기는 동시 실행이 기본이고 현장 사람이 없다. 확장 저자만 아는 사실이라 플랫폼은 집행하지 못한다.
  - 실행하는 쪽은 **제 실행 위치를 적지 않은 종류의 수행기를 내지 않는다.** 그런 BPM 프로세스는 시작 전에 사전 점검이 `task_types_wrong_location`으로 막는다 — 「그 확장이 없다」(`task_types_unsupported`)와 **다른 점검**이다(고치는 길이 다르다: 실행 위치를 PC로 바꾸거나 PC 위임으로 보낸다).
- `studio.resource_views`: 리소스 탐색기(STU-03)의 뿌리 하나. 목록은 **C7 기여 자원**(`resource_type`)에서 오고, Studio는 항목의 `name`·`summary`만 그린다 — **`data`를 해석하지 않는다** (§5). 그래서 기여 뿌리는 **한 단계**다.
  - `creates_task_type`(선택): 「캔버스에 추가」(끌어다 놓기)가 만들 **태스크 종류 id**. 없으면 그 뿌리에서 태스크를 만들 수 없다.
  - `creates_task_field`(선택): 새 태스크의 `data`에서 **자원 id를 받을 칸 이름**. 선언하면 Studio가 `{"<creates_task_field>": "<자원 id>"}`만 넣고 그 밖은 비운다 — 선언이 없으면 `data`를 비운 채 만들고 사람이 편집기에서 고른다. **플랫폼은 `data`의 모양을 모른다** — 선언대로만 넣는다.
- **호스트가 채우는 예약 설정 키** — 호스트만 아는 자리는 **확장이 설정으로 받는다** (`ctx.setting(…)`). 확장이 데이터 폴더·Center 주소를 다시 계산하거나 추측하지 않게 한다.

  | 키 | 값 |
  | --- | --- |
  | `storage.dir` | 이 확장이 **자기 파일을 둘 폴더** (호스트가 **제 데이터 폴더 아래에** 만들어 준다 — 앱마다 다른 자리다). 밀린 큐처럼 확장이 혼자 들고 있어야 하는 것을 여기 둔다. **비밀은 두지 않는다** (OS 비밀 저장소로 간다) |
  | `center.url` | **Center 주소** — 확장 클라이언트가 외부 작업(C15)을 올리는 곳 (ADR-0102). 서버 부분의 주소는 없다 |
  | `center.call_token` | 비밀이라 설정이 아니라 **`ctx.secret("call_token")`**으로 푼다 — 호출 토큰 (C15). PC 실행기는 PC 실행기가 청한 것, Studio는 Studio가 청한 것 |

  `center.`·`storage.`로 시작하는 키는 **호스트가 소유한다** — 확장이 `configuration`에 같은 이름을 선언하면 거부한다 (E7). 옛 머리 `service.`·`runtime.`도 계속 막는다 — 옛 확장이 그 이름으로 칸을 선언해 호스트의 값과 섞이지 않게.
- `configuration`의 `scope`: `bot_ui`, `studio`, `server_runner` 중 하나. 그 밖의 값은 검사 오류 `unknown_scope`다.
- `configuration`의 `schema`: JSON Schema. 확장이 설정 칸을 이것으로 선언한다.
- **`secret: true`인 칸은 OS 비밀 저장소에 둔다** (ADR-0013). 설정 파일·로그에는 남기지 않는다. 서비스 앱 키는 없다 (ADR-0102, 아래 KeyNeed) — 비밀 칸은 바깥 도구의 암호 같은 것에만 쓴다.
- `editor`: 두 가지 중 하나다.
  - `{"kind": "builtin", "entry": "…"}`: 확장이 준 편집기.
  - `{"kind": "schema"}`: 입력 JSON Schema로 만든 자동 폼 (STU-14 방식).
- `executor`: `{"entry": "…"}`. `extension_api.TaskExecutor`를 구현한다.
  - **실행 기록에 남기려면 `TaskOutcome.events[]`에 담는다** (C3 §확장이 남기는 이벤트, [ADR-0041](../decisions/0041-extension-run-events.md)). 확장은 `ExtensionEvent{kind, data}`만 주고 **줄은 엔진이 쓴다** — `run_id`·`seq`·`ts`·`node_id`는 엔진이 붙이고, `data`는 엔진이 거른다(원칙 6). 실패했을 때 남길 것은 `TaskFailed(…, events=[…])`에 싣는다. 알려진 `kind`인데 필수 키가 빠지면 **그 줄만 버려진다** (업무는 깨지지 않는다). 확장이 파일이나 `seq`를 만지는 길은 없다.
  - **전환할 때 사람에게 보일 것은 `TaskFailed(…, escalate="confirmation", review={…})`에 싣는다** ([ADR-0112](../decisions/0112-escalation-review-from-extensions.md), `extension_api` 1.5). 모양은 C6 `review`(이름 → 값)이고 표는 `review_table(headers, rows)`로 짓는다(C6 표 값). 엔진은 PC 확인 요청의 `review`로 **옮기기만** 하고 실행 기록에는 쓰지 않는다. 오류 경계로 가면(서버·`ESCALATED`를 이름으로 받는 경계) 버린다. `escalate`가 없으면 쓰지 않는다. 비밀은 넣지 않는다 — 결재 요청 파일에 그대로 간다.
- **`entry` 형식: `"<모듈>:<이름>"`.** 모듈은 확장 이름 공간(`chaeksas.ext`) 밑에서 찾는다 — `seal_check.client:SealCheckExecutor`는 `chaeksas.ext.seal_check.client.SealCheckExecutor`다 ([ADR-0019](../decisions/0019-package-names.md)). 가리키는 것은 **인자 없이 만들 수 있는 클래스**(또는 이미 만들어진 객체)이고, 확장 호스트가 만들어 `extension_api`의 모양인지 확인한 뒤 켠다.
  - 확장 호스트는 **그 확장의 패키지 안**만 허용한다. 정의가 다른 모듈(`os:getcwd` 같은 것)을 가리켜 import시킬 수 없다.
- `console.pages`: 그 서비스 앱 관리 콘솔(SVC-00 왼쪽 탐색)에 붙는 **앱 고유 화면**이다. 콘솔은 접속한 앱의 `app_id`(C11 `/admin/v1/status`)로 어느 확장의 기여인지 고른다 — 콘솔 한 벌이 모든 서비스 앱을 그리기 때문이다.
  - `module`: **`web/` 워크스페이스 안의 화면 모듈 이름.** 콘솔이 **빌드 시점 레지스트리**로 잇는다 (바깥 주소로 동적 `import()`를 열지 않는다 — [ADR-0017](../decisions/0017-web-nextjs-design-system.md)의 「브라우저가 토큰·주소를 모른다」).
  - 그래서 화면 모듈은 **모노레포 안 내장·사내 확장만** 올릴 수 있다 (Next.js 번들에 들어가야 한다). 외부 확장은 코드를 기여할 수 없고(E1) 자기 콘솔 **링크만** CON-07에 보인다.
  - 레지스트리에 그 `module`이 없으면 콘솔은 **줄을 끄고 이유를 가까이에 적는다** (U3 — 없는 것은 끈다). 줄 자체는 기여에서 오므로 **확장을 더하면 줄이 생긴다.**
- `resources[].catalog_url`: 상대 경로(서버 부분 기준) 또는 `allowed_hosts` 안의 주소. 응답은 §5 공통 카탈로그 형식이다.

### KeyNeed

| 필드 | 뜻 |
| --- | --- |
| `purpose` | 키를 어디에 쓰나. `run` 하나다 (아래) |
| `extra_scopes` | 그 부르기에 필요한 추가 권한 (C11 `required_scopes`와 짝). **지금 Center에는 이 권한을 켜 줄 길이 없다** — 그런 작업은 C15 올리기에서 403 `scope_missing`이다 |
| `config_key` | 옛 칸. **쓰지 않는다** — 있어도 무시한다 (호환) |

`purpose` 값:

- `run`: BPM 프로세스(그 확장의 태스크)가 작업을 부를 때. 그 밖의 값은 검사 오류 `unknown_purpose`다.

> [ADR-0102](../decisions/0102-calling-outside-is-pull.md): **키는 없다 — 선언은 「이 확장이 제 앱을 부른다」는 뜻으로만 남는다.** 바깥 기능은 C15 외부 작업으로 부르므로 아무도 키를 받지 않는다.
> - `run` — 빌드가 그 확장의 태스크를 쓰는 BPM 프로세스의 `requires.service_apps`에 그 확장 id로 줄을 적는다(C1). Center는 그 줄로 그 BPM 프로세스가 그 토픽에 올려도 되는지 본다(C15 `topic_not_required`).

## 4. HTTP 어댑터 (`protocol: "http-adapter"`, 외부 확장)

### 4-1. 필드

| 필드 | 뜻 |
| --- | --- |
| `allowed_hosts` | 부를 수 있는 호스트 목록 (정확한 이름, 와일드카드 없음). `base_url`·`catalog_url`·`health`의 호스트가 모두 이 안에 있어야 한다 |
| `allow_private_network` | 기본 false. 사설망·루프백·링크 로컬 주소를 부르려면 true여야 하고, 이것도 서명 대상이다 |
| `auth` | `{type: "bearer" \| "header", name?}`. 값은 어댑터 일꾼 설정의 키(`CHK_ADAPTER__EXT__<확장>__KEY`). **쿼리 문자열 인증은 없다** (주소·로그에 키가 남는다). 템플릿에서는 키를 쓸 수 없다 **없으면 키를 받지 않는 앱이다** ([ADR-0091](../decisions/0091-external-apps-without-auth-take-no-key.md)) — 어댑터 일꾼은 키를 싣지 않는다. 그래서 `requires_keys`에 `purpose: run`을 적으면 `auth`도 있어야 한다 (E3) |
| `limits` | `{timeout_s: 60, max_response_kb: 1024}` |
| `health` | 선택. `{path, expect_status: 200}`. **지금 읽는 쪽이 없다** — Center는 외부 앱을 두드리지 않고 상태를 토픽에서 읽는다(C7·C15, [ADR-0102](../decisions/0102-calling-outside-is-pull.md)). 받아 두기만 한다 |
| `operations` | 아래 Operation[] |

Operation:

| 필드 | 뜻 |
| --- | --- |
| `name`, `description` | C11과 같은 이름 규칙 |
| `modes` | 허용 수행 모드. 외부 확장의 **기본값은 `["autonomous"]`.** 결정 수행에서 부르려면 `deterministic`을 명시해야 하고, 이것도 서명 대상이다 |
| `server_ok` | 기본 true |
| `idempotent` | 기본 **false**. false면 결과를 모르는 실패(시간 초과, 연결 끊김)를 자동으로 다시 부르지 않는다 |
| `retry_on` | 요청이 처리되지 않았다는 뜻의 상태 코드 (예: `[429, 503]`). 이것만 다시 부른다 |
| `input_schema`, `output_schema` | JSON Schema (STU-14 자동 폼) |
| `request` | `{method, path, query?, headers?, body?}` |
| `response` | `{output: {<출력 필드>: "<경로>"}, error_when?: {path, equals? \| not_equals? \| exists?}}` |

`idempotent: false`인 작업이 결과를 모르는 실패를 만나면 이렇게 처리한다.

- PC: 확인(`confirmation`)으로 넘긴다. 「계속」은 `attempt`를 올려 다시 부르고, 「중단」은 업무 실패(`TASK_FAILED`)다.
- 서버: 실행 실패 또는 오류 경계 이벤트로 보낸다(`TASK_FAILED`).

어댑터 일꾼은 요청을 **보낸 뒤** 답을 받지 못한 실패(읽기 시간 초과·끊김)를 C15 `fail`에 `code: unreachable`·`outcome_unknown: true`로 올린다 — 연결 단계에서 실패해 요청이 나가지 않았으면 모름이 아니다. 부르는 쪽(`chk:serviceCall`)이 그 칸을 보고 위처럼 가른다 (C15 「결과 모름」, [ADR-0107](../decisions/0107-outcome-unknown-asks-a-person.md)). **확장 로컬 수행기**가 `TaskFailed(escalate="confirmation")`로 올리는 것도 같은 결이다 — PC는 확인, 서버는 오류 경계 `ESCALATED` ([ADR-0106](../decisions/0106-pc-escalation-asks-a-person.md)).

### 4-2. 템플릿 규칙 (주입 막기)

| 위치 | 쓸 수 있는 것 | 처리 |
| --- | --- | --- |
| `path` | 고정 문자열 + `{{input.<필드>}}` | 반드시 `/`로 시작. 값은 **경로 조각 하나로 퍼센트 인코딩**한다 (`/`, `..`, `@`, `?`, `#`도 인코딩) |
| `query` | `{이름: 템플릿}` | 값마다 인코딩 |
| `headers` | 고정 이름 → 템플릿 | 값에 CR·LF·제어 문자가 있으면 거부. `Authorization`·`Host`·`Cookie`는 템플릿으로 못 쓴다 |
| `body` | JSON 템플릿 | 값은 JSON 값으로 넣는다 (문자열 이어 붙이기 없음) |

- 쓸 수 있는 변수: `{{input.<필드>}}`, `{{run_id}}`, `{{node_id}}`, `{{idempotency_key}}`(C11 멱등 키 문자열). 그 밖의 변수·식은 정의 검사에서 거부한다.
- 출력 경로와 `error_when`의 `path`는 **제한된 JSONPath**만 쓴다: `$`, `.이름`, `[숫자]`. 필터·식·와일드카드는 쓸 수 없다.

### 4-3. 호출 규칙 (해석기 `core.http_adapter` — 어댑터 일꾼이 돌린다)

1. 주소를 만든다: 어댑터 일꾼 설정의 `BASE_URL`(시험 일감이면 `TEST_BASE_URL`, 없으면 정의의 `base_url`) + `path`.
2. **https만 쓴다.** `allow_private_network: true`이고 호스트가 사설 주소인 경우만 http를 허용한다.
3. 호스트가 `allowed_hosts`에 있는지 본다.
4. **DNS를 한 번 풀고 그 IP로 접속한다** (DNS 재바인딩 방지). `allow_private_network=false`면 루프백(127.0.0.0/8, ::1), 사설(10/8, 172.16/12, 192.168/16, fc00::/7), 링크 로컬(169.254/16, fe80::/10)을 거부한다. 이 규칙은 같은 PC의 로컬 서버(127.0.0.1)도 막는다.
5. **리다이렉트를 따라가지 않는다.** 3xx는 오류(`redirect_not_allowed`)로 처리한다.
6. 응답은 **읽는 동안** `max_response_kb`를 넘으면 끊는다.
7. 결과를 C3 `service_call`로 남긴다 (`app_id` = 확장 `id`). 요청·응답 본문은 남기지 않는다.

## 5. 공통 카탈로그 형식 (`resources[].catalog_url`)

확장이 Center 리소스 목록에 올리는 자원은 모두 이 형식으로 준다. 플랫폼(C7)은 이 형식만 안다.

```json
{
  "schema": 1,
  "revision": 482,
  "items": [{"type": "seal_specimen", "id": "hq.corporate-seal", "name": "본사 법인 인감",
             "summary": "견본 3장 · 사용 중 2", "updated_at": "…", "data": {"…": "확장 고유 내용"}}]
}
```

- `data`의 모양은 확장이 정한다. Center는 `data`를 해석하지 않고 그대로 Studio에 넘긴다.
- **비밀·업무 값을 넣지 않는다.** 카탈로그는 서버망 안에서만 연다 (역방향 프록시에서 바깥 노출을 막는다).

## 예시

### 사내 확장 (요약, 가상의 예)

지금 설치 파일에 든 확장은 없다 (ADR-0114). 아래는 모양을 보이려는 가상의 사내 확장이다.

```json
{
  "schema": 2, "id": "seal-check", "version": "1.2.0", "name": "인감 대조", "publisher": "사내 IT",
  "tier": "internal", "api": ">=2,<3",
  "service": {"protocol": "chk-c11", "base_url": "http://svc-seal:8000"},
  "contributes": {
    "task_types": [{"id": "seal_check", "label": "인감 대조", "icon": "stamp", "bpmn": "serviceTask",
                    "editor": {"kind": "schema"},
                    "executor": {"entry": "seal_check.client:SealCheckExecutor"}, "run_locations": ["pc", "server"]}],
    "studio.resource_views": [{"id": "seal-specimens", "label": "인감 견본", "resource_type": "seal_specimen",
                               "creates_task_type": "seal_check", "creates_task_field": "specimen_id"}],
    "configuration": [{"key": "scan_dir", "label": "스캔 폴더", "scope": "bot_ui",
                       "schema": {"type": "string"}, "secret": false}],
    "preflight": [{"id": "specimens-registered", "entry": "seal_check.client:SpecimensRegisteredCheck"}],
    "console.pages": [{"id": "overview", "label": "개요", "module": "seal-check/overview"}],
    "resources": [{"type": "seal_specimen", "label": "인감 견본", "catalog_url": "/v1/catalog"}]
  },
  "requires_keys": [{"purpose": "run", "extra_scopes": []}]
}
```

### 외부 확장 (외부 앱)

```json
{
  "schema": 2, "id": "ext-ocr", "version": "1.0.0", "name": "외부 OCR", "publisher": "외부 업체",
  "tier": "external",
  "service": {"protocol": "http-adapter", "base_url": "https://ocr.example.com",
    "adapter": {
      "allowed_hosts": ["ocr.example.com"],
      "auth": {"type": "bearer"},
      "limits": {"timeout_s": 30, "max_response_kb": 512},
      "health": {"path": "/health", "expect_status": 200},
      "operations": [{
        "name": "read_invoice", "description": "세금계산서 이미지에서 항목 추출",
        "modes": ["autonomous", "deterministic"], "idempotent": false, "retry_on": [429, 503],
        "input_schema": {"type": "object", "required": ["file_url"], "properties": {"file_url": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"biz_no": {"type": "string"}, "amount": {"type": "integer"}}},
        "request": {"method": "POST", "path": "/v2/invoice", "body": {"url": "{{input.file_url}}", "ref": "{{run_id}}"}},
        "response": {"output": {"biz_no": "$.result.bizNo", "amount": "$.result.total"},
                     "error_when": {"path": "$.status", "not_equals": "ok"}}
      }]}},
  "requires_keys": [{"purpose": "run", "extra_scopes": []}],
  "contributes": {}
}
```

## 검사 규칙

| # | 규칙 | 위반 |
| --- | --- | --- |
| E1 | `tier=external`이면 `entry`가 있는 기여와 `configuration`·`task_types`가 없다 | 422 `external_code_not_allowed` |
| E2 | `tier=builtin`·`internal`은 설치 파일에 든 확장만. Center에 외부로 등록할 수 없다 | 409 `id_conflict` |
| E3 | `http-adapter`: `allowed_hosts`·https·템플릿 변수·경로 시작 `/`·제한 JSONPath·금지 헤더 규칙(§4). `requires_keys`에 `purpose: run`이 있으면 `adapter.auth`가 있다 (키를 실을 자리 — ADR-0091) | 422 `adapter_invalid` (`detail`에 칸별 사유) |
| E4 | `task_types[].id`는 확장 사이에 겹치지 않는다 | 409 `task_type_conflict` |
| E5 | 확장 호스트는 `api` 범위가 맞지 않는 확장을 켜지 않는다 (목록에 「호환 안 됨」) | — |
| E6 | 외부 정의의 봉투(C2 `extension`)가 검증되고 `definition_hash`가 맞는다 | 400 `bad_envelope` / `hash_mismatch` |
| E7 | `configuration[].key`가 `center.`·`storage.`(호스트가 쓰는 이름)와 옛 머리 `service.`·`runtime.`으로 시작하지 않는다 | 422 `reserved_config_key` |

Studio 「확장」(STU-15)의 「정의 파일 열기...」는 E1·E3을 로컬에서 먼저 돌려 보여 준다.

## 호환 규칙

- 모르는 `contributes` 키는 무시한다. 새 기여 지점은 `extension_api` 버전을 올려 추가한다.
- `tier`·`protocol` 값은 열린 문자열이지만, 확장 호스트는 아는 값만 켠다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-31 | 2 | 외부 확장은 **확장 폴더**로도 들어온다 — Center가 뜰 때 읽고 콘솔 등록과 같은 관문을 지난다. 모양은 그대로다 | [0121](../decisions/0121-extension-folder.md) |
| 2026-10-31 | 2 | 기여 지점 `tool_ui.tools`·`bot_ui.panels`·`bot_ui.local_runtimes`·`agent_environments`, **E8**, 예약 키 `runtime.<id>.*`, `scope: tool_ui`, `requires_keys[].purpose: utility`를 걷었다 — UI 자동화 확장과 함께. 걷은 열쇠는 호스트가 경고하고 읽지 않는다(`LEGACY_CONTRIBUTION_KEYS`), E7은 옛 머리도 막는다. 열쇠가 모두 선택이라 schema는 그대로이고 `extension_api`는 **2.0.0**이다(이름을 지웠다 — 예시의 `api`는 `>=2,<3`) | [0114](../decisions/0114-remove-ui-automation.md) |
| 2026-10-30 | 2 | 수행기가 전환할 때 **사람에게 보일 검토 자료**(`TaskFailed(review=…)`)를 넘긴다 — `extension_api` **1.5**. 정의는 그대로다 | [0112](../decisions/0112-escalation-review-from-extensions.md) |
| 2026-10-29 | 2 | `requires_keys`에 키가 없다 — `run`은 빌드가 `requires.service_apps` 줄을 적는 뜻, `extra_scopes`는 Center가 PC 스위치로 건다. 외부 앱은 **어댑터 일꾼**이 부른다 — 주소·키는 그 일꾼 설정(`CHK_ADAPTER__EXT__<확장>__*`), 실행하는 쪽은 정의 검증·고정만. 예약 키 `service.base_url`·`service.key_ref` → `center.url`·`call_token` 비밀, `CHK_RUNTIME__SERVICE_URL` → `CHK_RUNTIME__CENTER_URL`. 예약 접두 `service.` → `center.` | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-25 | 1 | `requires_keys`의 키는 Center가 내려 준다 — `run`은 배포 대상마다, `utility`는 CON-03 「셀렉터 등록」을 켠 PC에. `config_key`는 무시한다(호환), 호스트가 `ctx.secret("utility")`로 준다 | [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 2026-10-25 | 2 | `adapter.auth`가 없는 외부 앱은 **키를 받지 않는 앱**이라고 적었다. E3가 `run` 키를 적고 `auth`가 없는 정의를 거부한다 — 키를 실을 자리 없이 키를 요구하던 모순이었다. 칸은 그대로라 schema도 그대로다 | [0091](../decisions/0091-external-apps-without-auth-take-no-key.md) |
| 2026-10-24 | 2 | 외부 확장 등록·해제는 **봉투 대신 정의(해제는 `{id, version}`)를 받고 Center가 서명한다**. `DELETE …/extensions/{id}` 꼴을 없앴다 | [0090](../decisions/0090-center-admin-accounts.md) |
| 2026-10-20 | 2 | 기여 지점 `tool_ui.tools`와 `configuration.scope`의 `tool_ui`를 더하고 `bot_ui.utilities`를 걷었다 — 확장의 도구는 Tool UI가 띄우고 런타임은 Bot UI 것을 빌려 쓴다. 열쇠가 모두 선택이라 schema는 그대로이고 `extension_api`는 **1.4**다(`ToolUiTool`·`HOST_TOOL_UI` — 옛 `BotUiUtility`는 같은 모양의 이름으로 남겼다. 큰 판 2.0으로 올리면 `api: ">=1,<2"`인 확장이 모두 꺼진다) | 0077 |
| 2026-10-18 | 2 | 예약 설정 키에 `service.key_ref`를 더했다 — Studio 편집기가 「BPM 프로세스 설정을 따름」의 키 참조를 안다(STU-13 시험·계획 굳히기). 머리 `service.`는 이미 예약이라 E7이 그대로다. 호스트가 주는 값이라 schema는 그대로 | 0074 |
| 2026-10-09 | 2 | `bot_ui.panels`(플랫폼 화면의 한 칸)를 더하고 `console.pages[].module`이 어떻게 화면이 되는지 적었다 — `extension_api` **1.3**. 기여 지점 추가라 기존 확장은 영향이 없다 | 0042 |
| 2026-10-09 | 2 | 태스크 수행기가 **실행 기록에 남기는 길**을 적었다 (`TaskOutcome.events[]`) — `extension_api` **1.2**. 정의(`extension.json`)는 바뀌지 않으므로 `api: ">=1,<2"`인 확장은 그대로 돈다 | 0041 |
| 2026-10-09 | 2 | `bot_ui.local_runtimes[].status`·`shutdown`(상태 묻기·곱게 끄기)을 더했다 — Bot UI가 BUI-09의 「예약」·「밀린 보고」를 보이고 종료 순서에서 런타임에게 닫을 틈을 준다. 선택 칸이라 기존 확장은 영향이 없다 | 0018, 0023 |
| 2026-10-06 | 2 | `bot_ui.local_runtimes[].reserve`(실행 예약 방법)를 더했다 — Bot UI가 런타임의 계약을 모른 채 실행 동안 런타임을 그 실행에 묶는다. 선택 칸이라 기존 확장은 영향이 없다 | 0014 |
| 2026-10-05 | 2 | `agent_environments`(AI 태스크의 `web`·`desktop` 환경)를 더했다. 모르는 열쇠는 무시하므로 기존 호스트는 영향이 없다 | 0037 |
| 2026-10-01 | 1 | 초안 | 0018 |
| 2026-10-01 | 1 | 검토 반영 (아래) | — |
| 2026-10-08 | 2 | 외부 확장 **해제가 `in_use`로 막히지 않는다**고 바로잡았다 — 정의에 문제가 있어 거두는 보안 동작이라 쓰는 Bot이 있을 때 더 거둬야 한다. 해제 경로의 `{id}`는 선택이다 (봉투가 원본). 구현하며 드러났다 | 0018 |
| 2026-10-02 | 1 | 구현하며 명시한 것: `entry` 형식과 그 확장 패키지 안으로 제한, 예시의 편집기·유틸리티 entry를 `client`로 (ADR-0018 §6 폴더 구성) | 0018 |
| 2026-10-02 | 1 | 설치 파일로 묶어 보고 명시한 것: `extension.json`은 파이썬 패키지 안 | 0024 |
| 2026-10-05 | 2 | 예약 설정 키에 `storage.dir`을 더했다 — 확장이 자기 파일을 둘 폴더 (밀린 등록 큐 등) | 0018 |
| 2026-10-05 | 2 | 예약 설정 키에 `service.base_url`을 더했다 — 서버 주소의 출처를 하나로 (Center 리소스 등록 > 정의) | 0013, 0018 |
| 2026-10-05 | 2 | 호스트가 채우는 **예약 설정 키**(`runtime.<id>.port`·`token_dir`·`state`)를 적었다 — 유틸리티가 띄워진 런타임을 설정으로 받는다. 같은 이름을 확장이 선언하면 거부한다 (E7). 새 칸이 아니라 호스트가 주는 값이라 schema는 그대로 | 0018, 0024 |
| 2026-10-03 | **2** | `bot_ui.local_runtimes`의 `command`(명령 배열)를 **`entry`**(진입점 문자열)로 **바꿨다.** 명령줄은 Bot UI가 만들고, 자기 실행 파일을 자식으로 다시 띄운다. 필드의 뜻이 바뀌었으므로 schema를 올린다 | 0024 |
| 2026-10-29 | 2 | §4-1 「결과 모름 → PC는 확인」이 어댑터 길(C15)에서는 아직 없다고 「미정」으로 적었다. 확장 수행기의 `escalate: confirmation`은 그대로 돈다 | [0106](../decisions/0106-pc-escalation-asks-a-person.md) |
| 2026-10-29 | 2 | §4-1의 어댑터 길을 닫았다 — 어댑터 일꾼이 C15 `outcome_unknown`을 싣고 PC는 확인 뒤 다시 부른다(「중단」은 `TASK_FAILED`). 연결 단계 실패는 모름이 아니다 | [0107](../decisions/0107-outcome-unknown-asks-a-person.md) |

검토 반영 내용:

- 외부 정의는 서명된 봉투(C2 `extension` — Center가 등록할 때 서명한다)가 있어야 쓰이고, C1에 `definition_hash`로 고정한다.
- 어댑터 안전 규칙을 더했다: https만, 리다이렉트 금지, 사설망 차단, DNS 고정, 위치별 인코딩, 쿼리 인증 제거, 제한 JSONPath, 읽는 동안 크기 상한.
- `configuration` 기여 지점(비밀 칸은 OS 비밀 저장소)을 더했다.
- 주소 출처를 하나로 했다.
- 이름 공간을 하나로 했다.
- 외부 작업의 기본 모드를 자율 수행으로 했다.
- 공통 카탈로그 형식을 정했다.

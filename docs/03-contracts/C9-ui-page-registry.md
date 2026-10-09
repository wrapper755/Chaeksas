# C9. UI 자동화 앱: 화면 레지스트리

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | UI 자동화 확장의 Bot UI 유틸리티 「UI 셀렉터 등록」(직접 호출) → UI 자동화 앱, UI 자동화 앱 관리 콘솔(UIA-02) → UI 자동화 앱, Center(공개 카탈로그 읽기) → UI 자동화 앱 |
| 코드 위치 | `extensions/ui_automation/contracts/` (registry.py) — UI 자동화 확장이 소유 ([ADR-0018](../decisions/0018-extensions.md)) |
| 관련 ADR | [0010](../decisions/0010-service-apps.md) §5, [0012](../decisions/0012-bot-ui.md), [0013](../decisions/0013-api-keys.md), [0033](../decisions/0033-desktop-app-and-window.md)(데스크톱 창), [0042](../decisions/0042-extension-contributed-panels.md)(콘솔 화면) |
| 관련 화면 | BUI-06·07·08, UIA-01·02·03, CON-07 「UI 화면」, STU-03·13 |

## 목적

자동화할 화면과 그 요소(시맨틱 키), 요소마다의 로케이터 사다리를 등록·조회·삭제한다. 결과물은 UI 자동화 앱이 소유한다. 통계·승격·폐기 판단이 거기 있기 때문이다 (C8).

> 상태: 네 작업과 공개 카탈로그가 **돈다** (`extensions/ui_automation/service/app.py`, 저장은 SQLite 한 파일). 부르는 쪽은 `client/registry_client.py`다. 추가 권한은 작업이 `required_scopes`로 선언하고 `service_kit`이 건다 (C11). **관리 콘솔이 읽는 길도 돈다** — 경로 다섯(UIA-01~03)과 UI 세션 기록이다 (아래).

## 전송

| 경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /v1/catalog` | **없음** | 공개 카탈로그. **셀렉터 없음.** Center 리소스 목록(C7)이 읽는다 |
| `POST /v1/ops/registry_list_pages` | 서비스 앱 키 (아무 권한) | 화면 목록 (BUI-06 「화면 ID」 콤보) |
| `POST /v1/ops/registry_get_page` | 서비스 앱 키 + **`registry_write`** | 화면 하나 전체. 로케이터 포함 |
| `POST /v1/ops/registry_register` | 서비스 앱 키 + `registry_write` | 등록·추가 |
| `POST /v1/ops/registry_delete` | 서비스 앱 키 + `registry_write` | 삭제 |

- **누가 부르나:** 레지스트리 작업은 **UI 자동화 확장의 Bot UI 유틸리티(클라이언트 코드)가 UI 자동화 앱을 직접** 부른다 (`caller.type: bot_ui`). 키는 확장 설정의 등록 담당자 키(C13 `configuration` 비밀 칸)를 쓴다. Worker는 브라우저 일(열기·분석·고르기·검증, C10 §5)만 하고 레지스트리를 부르지 않는다.
- **멱등 키:** 등록·삭제 **동작마다** 새 `run_id` `reg_<hex8>`를 만든다 (`node_id: "registry"`, `node_instance: 1`, `attempt`는 재시도마다 +1, `call_seq: 1`).
- 작업 호출은 C11을 따른다. `mode`는 `deterministic`로 보낸다 (등록은 LLM을 쓰지 않는다). manifest에는 두 모드를 모두 선언한다.
- `registry_write`는 SVC-02에서 키를 발급할 때 고르는 추가 권한이다. 등록 담당자 개인 키(BUI-03)에만 준다. **운영용 Bot 키에는 주지 않는다.**
- 셀렉터(물리 정보)는 `registry_get_page`와 `registry_register`에만 나온다. 둘 다 `registry_write` 권한이 있는 키만 부를 수 있다. 공개 카탈로그와 C7 리소스 목록에는 셀렉터가 나오지 않는다.

## 모델

### 이름 규칙

| 이름 | 규칙 | 예 |
| --- | --- | --- |
| `page_id` | `^[a-z][a-z0-9_.-]{0,99}$` | `erp.order.form` |
| `semantic_key` | `^[a-z][a-z0-9_.]{0,79}$` (화면 안에서 유일) | `customer.name`, `submit` |

### PageRegistration (등록 단위 = 화면 하나)

| 필드 | 필수 | 뜻 |
| --- | --- | --- |
| `page_id` | ✓ | |
| `platform` | | `web`(기본) \| `desktop` |
| `name` | | 사람이 읽는 이름 |
| `url_pattern` | | 이 화면을 알아보는 주소 패턴 (웹) |
| `app` | | 데스크톱만. **앱 이름** (예: `ERP Client`). Worker가 이 이름으로 그 PC의 실행 명령을 찾는다 — 실행 파일 경로는 여기 두지 않는다 (PC마다 다르다, [ADR-0033](../decisions/0033-desktop-app-and-window.md)) |
| `window` | 데스크톱이면 ✓ | 데스크톱만. **이 화면인 창을 알아보는 조건** (WindowSpec, 아래). Worker는 이 창 **안에서만** 찾는다 |
| `locators` | ✓ | `{semantic_key: LocatorSpec[]}` (C8). 요소마다 1개 이상 |
| `elements` | | `{semantic_key: ElementHint}` — `{description, role, name, kind}`. `kind`: `control` \| `list` \| `table` \| `text` (BUI-06 「종류」). 치유·계획에 쓴다 |
| `catalog` | | `{semantic_key: CatalogEntry}` — `{actions[], depends_on[], concepts[], navigates_to?}`. 설계할 때만 쓴다 (STU-13 요소 목록, LLM 계획) |

#### WindowSpec (데스크톱 창 조건)

| 필드 | 뜻 |
| --- | --- |
| `title` | 창 제목 **정규식** (부분 일치). 예: `^ERP Client` |
| `class_name` | 창 클래스 이름 (정확히). 예: `XLMAIN` |
| `process` | 실행 파일 이름 (대소문자 무시). 예: `erp.exe` |

- **하나 이상** 있어야 한다. 주어진 것을 **모두** 만족하는 최상위 창이 이 화면이다.
- 맞는 창이 여럿이면 Worker는 고르지 않는다 (C10 `window_ambiguous`) — 엉뚱한 창에 입력하지 않게.

검사:

- `elements`·`catalog`의 키는 모두 `locators`에 있어야 한다. 사다리 없는 정보는 거부한다.
- `platform`이 `desktop`이면 `window`가 있어야 하고(조건 하나 이상), 로케이터는 데스크톱 전략(C8)이어야 한다. `title`은 정규식으로 읽혀야 한다.
- `depends_on`에 자기 자신이 있으면 거부한다.
- `actions`는 C10 동작 목록 안에서만 쓴다.

### registry_register

입력: `{page: PageRegistration}`.

규칙:

- **기존 것을 지우지 않는다.** 같은 요소에 새 로케이터를 더하고, 이미 있는 로케이터(`locator_key`가 같음)는 그대로 둔다.
- 보낸 `status`는 무시하고 새 로케이터는 **`unverified`** 로 넣는다. 사람이 화면에서 검증을 통과시켰어도 그건 "그 순간 그 화면"에서만 참이다. `active` 승격은 실행 통계로만 한다 (C8).
- **실제로 바뀐 것이 있을 때만**(`created`가 비어 있지 않을 때) 화면의 `revision`을 1 올린다. 같은 것을 다시 올려도 Worker 계획 캐시가 버려지지 않는다.
- `name`·`url_pattern`·`app`·`window`는 **보낸 것만 바꾼다** (안 보내면 그대로). `app`·`window`가 바뀌면 `revision`도 올린다 — 캐시된 계획이 옛 창 조건을 쥐고 있지 않게.

출력 (RegistrationResult):

| 필드 | 뜻 |
| --- | --- |
| `page_id` | |
| `revision` | 새 판 번호 |
| `created` | `[{semantic_key, locator_key}]` 새로 생긴 것 |
| `kept` | `[{semantic_key, locator_key}]` 이미 있던 것 |
| `created_page` | bool. 새 화면이었나 |
| `unchanged` | bool. `created`가 비고 `kept`만 있으면 true, "이미 등록된 것과 같다"는 뜻 (BUI-06 결과 문구) |

### registry_delete

입력: `{page_id, semantic_key?, force: false}`. `semantic_key`가 없으면 화면 전체를 지운다.

- **잘못 만든 것을 없애는 길이다.** 화면 개편용이 아니다. 개편은 재등록(사다리를 더함)과 `deprecated` 판정으로 한다. 지우면 그 화면의 통계·승격·치유 이력이 사라진다.
- **배포된 Bot이 쓰는지는 UI 자동화 앱이 모른다** (Center가 안다). 그래서 유틸리티는 지우기 전에 Center 리소스 목록(C7 `ContributedResource.used_by`)을 읽어 「이 화면을 쓰는 Bot <N>개 — 지우면 그 Bot의 UI 태스크가 실패합니다」를 보이고 확인을 받는다. 실행 중에 지워져도 보고는 걸리지 않는다 (C8 재전송 규칙).
- 다른 화면의 요소가 이것을 가리키면(`navigates_to`, `depends_on`), `force=false`일 때 409 `has_links`와 함께 끊길 경로 목록을 돌려준다. 사람이 두 번째로 확인하면(U9) `force=true`로 다시 보낸다.

출력 (DeletionResult): `{page_id, semantic_key?, elements, locators, broken_links: [{page_id, semantic_key, kind}], revision}`. 되돌릴 수 없는 일이라 숫자로 남긴다.

### registry_list_pages / registry_get_page

| 작업 | 입력 | 출력 |
| --- | --- | --- |
| `registry_list_pages` | `{platform?, query?}` | `[{page_id, name, platform, element_count, revision, updated_at}]` |
| `registry_get_page` | `{page_id}` | PageRegistration (모든 로케이터와 각 `status`·통계 `{success, fail, last_success_at}`) + `revision` |

### 공개 카탈로그 `GET /v1/catalog` (C13 §5 공통 형식)

```json
{
  "schema": 1,
  "revision": 482,
  "items": [{
    "type": "ui_page", "id": "erp.order.form", "name": "ERP 주문 입력",
    "summary": "요소 12개 · 사용 중 9 · 검증 전 2", "updated_at": "2026-10-01T10:40:00+09:00",
    "data": {
      "platform": "web", "revision": 12,
      "elements": [
        {"semantic_key": "customer.name", "name": "고객명", "kind": "control", "actions": ["fill", "read"], "depends_on": []},
        {"semantic_key": "submit", "name": "저장", "kind": "control", "actions": ["click"], "depends_on": ["customer.name"], "navigates_to": "erp.order.done"}
      ],
      "locator_summary": {"active": 9, "unverified": 2, "deprecated": 1}
    }
  }]
}
```

- **서버망 안에서만 연다.** 역방향 프록시에서 `/v1/catalog`의 바깥 노출을 막는다 (C13 §5).
- 최상위 `revision`은 어느 화면이든 바뀌면 오른다. Center는 이 값이 같으면 다시 읽지 않는다.
- 들어가는 것: 요소 이름·종류·동작·관계·로케이터 상태 개수.
- 들어가지 않는 것: 셀렉터, `description` 원문(치유 프롬프트용), 통계 세부.

## 관리 콘솔이 읽는 길 (UIA-01~03)

관리 콘솔의 **앱 고유 화면**(C13 `console.pages`, [ADR-0042](../decisions/0042-extension-contributed-panels.md))이 읽는 경로다. 코드 위치는 `extensions/ui_automation/…/service/console.py`이고 모델은 `…/contracts/console.py`다.

| 경로 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /admin/v1/overview` | **관리자 토큰** | UIA-01 개요 — 셀렉터 셈·모델·세션 셈·배포 전 확인 |
| `GET /admin/v1/pages` | 같음 | UIA-02 화면 고르기 목록. **셀렉터는 없다** (`registry_list_pages`와 같은 칸) |
| `GET /admin/v1/pages/{page_id}` | 같음 | UIA-02 화면 하나 — 로케이터·성적·요소·전략별 합·경고. **셀렉터가 나간다.** 없으면 404 `not_found` |
| `GET /admin/v1/path?start=&goal=` | 같음 | UIA-02 「화면 간 경로 탐색」. 둘 중 하나가 비면 422 `input_invalid` |
| `GET /admin/v1/sessions?limit=` | 같음 | UIA-03 — 이력·요약·폴백 깊이 분포. `limit` 기본 100·최대 1000 |

- **관문은 C11 관리 API와 같다** (`service_kit.admin_guard`) — 관리자 토큰이 없으면 503 `admin_disabled`, 없는 토큰은 401, 틀린 토큰은 403이다. **업무 키로는 못 부른다** (`registry_write` 키여도 403).
- 왜 관리자 토큰인가: **콘솔은 서비스 앱 키를 갖지 않는다** ([ADR-0013](../decisions/0013-api-keys.md)). 셀렉터를 보는 작업(`registry_get_page`)은 `registry_write` 키의 일이고, 콘솔이 그 키를 들고 있으면 「키를 발급하는 화면이 키를 쓰는」 꼴이 된다. 관리자 토큰은 키를 발급하는 토큰이라 이미 더 강하다.
- **읽기만 한다.** 등록·삭제는 §전송의 작업(`/v1/ops/registry_*`)이고 Bot UI 유틸리티(BUI-06)의 일이다.
- **대체된 것(`deprecated`)도 준다** — 무엇이 밀려났는지 보는 화면이다 (UIA-02).
- **「치유가 더했다」는 표시는 레지스트리에 없다** — 보고가 적어 둔 것(`healed[].locator`·`supersedes`)에서 모은다. 그래서 화면의 「자가 치유」 열과 「대체 관계」는 **세션 기록이 있어야** 보인다.
- 「화면 간 경로 탐색」은 **최단 하나**를 앱이 **너비 우선**으로 찾는다 ([ADR-0040](../decisions/0040-registry-storage-sqlite.md)) — 길이 없으면 빈 목록이고 **지어내지 않는다**.
- 성공률은 **센 적이 없으면 `null`**이다 — 0%와 다르다 (아직 안 돌았다는 뜻).
- 모델은 JSON Schema로 내보낸다 (`…/ui_automation/schemas/c9-console-overview.json`, `uv run python scripts/gen_schemas.py`) — 콘솔 타입이 거기서 생성된다. **확장이 소유한 계약이라 확장 폴더에 둔다** (계약 README 원칙 1).

### UI 세션 기록

`report`(C8)가 도착하면 **한 줄 남긴다** — UIA-01 「최근 UI 세션」과 UIA-03이 읽는다.

- **보고가 도착한 것만** 안다. C8 보고는 세션이 **끝날 때** 오므로 **「진행 중」은 없다** — 도는 세션은 현장의 BUI-09가 보여 준다. 없는 수를 0으로 보이면 「아무것도 안 돈다」로 읽히므로 칸 자체를 두지 않는다.
- **시험 보고(`origin: test`)는 따로 센다** — 승격 통계와 같은 규칙이다 (C8).
- 같은 `business_key`가 다시 오면 **나중 것이 이긴다** (재시도는 `attempt`가 달라 다른 키다).
- **업무 값은 없다** — C8 보고 자체가 읽은 값·입력한 글자를 담지 않는다 (원칙 6).
- **최근 5000줄까지** 들고 오래된 것부터 버린다. 모니터링 자료라 영원히 쌓을 이유가 없다.
- **봉투가 말해 주는 것도 함께 적는다** — `caller.type`(요청 쪽)·`mode`(수행 모드)·`caller.bpm_process_id`(Bot)·`caller.host`(Bot UI). C8 보고에는 없고 C11 호출(`OpRequest`)에는 있다. UIA-03 표의 그 네 열이 여기서 온다.
- 「폴백 깊이 분포」는 `attempts`를 요소별로 세어 만든다 — `0`이 **1순위 로케이터로 바로 성공**한 것이고, **끝까지 실패한 요소는 깊이가 아니다** (전환·실패로 센다).

### 배포 전 확인 (UIA-01)

**이 앱이 자기 힘으로 볼 수 있는 것만** 본다: 모델 연결, 등록 담당자 키(`registry_write` 권한이 살아 있는 키), 등록된 화면. 등급은 `ok`·`warn`이고 **막지 않는다** — 무엇이 안 되는지 알려 주는 줄이다.

허용 주소·인증 설정은 **외부 확장 어댑터의 개념**(C13 §4)이고 C11을 따르는 이 앱에는 없다.

## 예시 (등록)

```json
{
  "schema": 1, "mode": "deterministic",
  "run_id": "reg_7f3a9c21", "node_id": "registry", "node_instance": 1, "attempt": 1, "call_seq": 1,
  "caller": {"type": "bot_ui", "host": "bui_a81c22d0"},
  "input": {"page": {
    "page_id": "erp.order.form", "name": "ERP 주문 입력", "url_pattern": "https://erp.example/order/*",
    "locators": {"customer.name": [
      {"type": "role", "value": "textbox", "name": "고객명"},
      {"type": "css", "value": "#custName"}]},
    "elements": {"customer.name": {"description": "주문 고객 이름 입력칸", "role": "textbox", "kind": "control"}},
    "catalog": {"customer.name": {"actions": ["fill", "read"], "concepts": ["고객"]}}
  }}
}
```

데스크톱 화면:

```json
{
  "schema": 1, "mode": "deterministic",
  "run_id": "reg_0b9d4e17", "node_id": "registry", "node_instance": 1, "attempt": 1, "call_seq": 1,
  "caller": {"type": "bot_ui", "host": "bui_a81c22d0"},
  "input": {"page": {
    "page_id": "erp.desktop.po_entry", "platform": "desktop", "name": "ERP 발주 입력",
    "app": "ERP Client", "window": {"title": "^ERP Client", "process": "erp.exe"},
    "locators": {"po.item": [
      {"type": "automation_id", "value": "txtItem", "platform": "desktop"},
      {"type": "control_name", "value": "품목", "control_type": "Edit", "platform": "desktop"}]},
    "elements": {"po.item": {"description": "발주 품목 코드", "role": "textbox", "kind": "control"}}
  }}
}
```

- 셀렉터 등록은 실행이 아니므로, C11 멱등 키를 만들기 위해 `run_id`에 **동작마다 새로 만든** `reg_<hex8>`를 넣는다.

## 오류

| 상태 코드 | `code` | 언제 | 할 일 (BUI-06) |
| --- | --- | --- | --- |
| 403 | `scope_missing` | `registry_write` 없는 키 (코드는 작업의 `required_scopes`를 뼈대가 걸어 낸다, C11 §오류) | 「등록 권한이 있는 키가 아닙니다 — 설정 → UI 셀렉터 등록」 |
| 404 | `page_not_found` | | 「새 화면 — 등록하면 만들어집니다」 |
| 409 | `has_links` (`detail.broken_links`) | 다른 화면이 가리키는 것 삭제 | 두 번째 확인 창 → `force=true` |
| 422 | `invalid_page` (`detail` 규칙별) | 이름 규칙, 사다리 없는 요소, 자기 의존, 데스크톱인데 창 조건 없음·웹 전략 | 칸마다 표시 |
| 503 | `registry_unavailable` | 저장소가 내려감 (무엇이 저장소인지는 응답에 드러내지 않는다) | 「서버에 닿지 못해 등록을 큐에 쌓았습니다」(BUI-06, 4xx는 큐에 쌓지 않음) |

## 호환 규칙

- 모르는 필드는 보관하고 무시한다. `kind`·`actions`·`status`는 열린 문자열이다.
- **저장소가 무엇인지는 응답에 드러내지 않는다** (프로토타입의 `backend`·`path` 필드는 없앴다). 지금 구현은 SQLite 한 파일이다 (`service/store.py`) — 그것은 계약이 정할 일이 아니다.

저장소는 **SQLite 한 파일이고 그래프 저장소를 두지 않는다** ([ADR-0040](../decisions/0040-registry-storage-sqlite.md)).
폴백도 없다. 「화면 간 경로 탐색」(UIA-02)은 요소의 `navigates_to`를 간선으로 앱 코드가 너비 우선으로
찾는다 — 질의 언어가 필요하지 않다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-09 | 1 | 「관리 콘솔이 읽는 길」에 UIA-02·03의 경로 넷(`pages`·`pages/{id}`·`path`·`sessions`)을 더했다. 세션 기록이 **봉투의 `caller`·`mode`도** 적는다 (UIA-03 표의 네 열). 치유 표시·대체 관계는 보고에서 모은다 | 0042 |
| 2026-10-09 | 1 | 「관리 콘솔이 읽는 길」을 적었다 — `GET /admin/v1/overview`(UIA-01), UI 세션 기록(보고가 도착한 것만·시험은 따로·5000줄), 「배포 전 확인」. 관문은 C11 관리 API와 같은 관리자 토큰이다 | 0042 |
| 2026-10-01 | 1 | 초안. 프로토타입 화면 등록을 C11 작업으로 옮겼다. 그 과정에서 바뀐 것: `registry_write` 권한, 셀렉터 없는 공개 카탈로그, `revision`, 삭제 때 끊길 경로를 확인하는 단계 | 0010, 0012, 0013 |
| 2026-10-01 | 1 | 검토 반영: 레지스트리는 확장의 Bot UI 유틸리티가 직접 부름(Worker 경유 아님), 동작마다 새 `reg_` id, 바뀔 때만 `revision` 증가, 삭제 전 Center `used_by` 확인, 카탈로그를 C13 공통 형식으로·서버망 한정 | 0018 |
| 2026-10-05 | 1 | 데스크톱 화면: `app`(앱 이름)·`window`(창 조건 `title`·`class_name`·`process`), 데스크톱이면 `window` 필수. 등록은 보낸 칸만 바꾸고 `app`·`window`가 바뀌면 `revision`을 올린다. 더하기만이라 schema는 그대로 1 | 0033 |

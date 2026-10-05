# C13. 확장 정의 (extension.json)

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영). 모델·검사 규칙 **구현됨** |
| schema | 2 (1은 `local_runtimes.command`를 쓰던 것 — 아래 변경 이력) |
| 보내는 쪽 → 받는 쪽 | 확장 작성자 → Studio·Bot UI·실행기·서버 실행기(확장 호스트), Center(리소스 목록·검사), 관리 콘솔 |
| 코드 위치 | `chaeksas.contracts.extension`, 인터페이스 `packages/extension_api/`, 호스트 `chaeksas.core.extensions` |
| 관련 ADR | [0018](../decisions/0018-extensions.md), [0010](../decisions/0010-service-apps.md), [0013](../decisions/0013-api-keys.md) |
| 관련 화면 | BUI-01·03·11, STU-03·14·15, CON-07 |

## 목적

확장 하나가 무엇을 더하는지 선언한다. 플랫폼은 이 파일만 보고 기여를 끼워 넣는다. 특정 확장 이름을 플랫폼 코드에 쓰지 않는다.

## 전송

### 내장·사내 확장

- 확장 패키지 안에 `extension.json`을 둔다. 확장 호스트가 엔트리 포인트 `chaeksas.extensions`로 찾는다.
  - **파이썬 패키지 안**이다 (`extensions/<id>/src/chaeksas/ext/<id>/extension.json`). 호스트가 `importlib.resources`로 읽으므로, 패키지 밖에 두면 설치 파일로 묶은 뒤 사라진다 ([ADR-0024](../decisions/0024-desktop-packaging-extensions.md)).
- 정의는 설치 파일에 들어 있으므로 서명된 설치 파일이 곧 신뢰의 근거다.
- 실행하는 쪽(Bot UI, 서버 실행기)은 설치된 확장의 `{id, version, definition_hash}`를 Center에 보고한다 (C4·C12 `extensions`).
- 서버 부분이 있으면 그 서비스 앱의 `/manifest`가 `extension: {id, version, definition_hash}`를 싣는다 (C11).

### 외부 확장

외부 확장은 정의 파일만 있다. **Admin 서명 없이는 쓰이지 않는다.**

정의가 서비스 앱 키를 어느 주소로 보낼지 정하기 때문에, 배포와 같은 관문(C2)을 둔다. 관리자 토큰만 새어도 Bot의 키·업무 값이 다른 주소로 새는 일을 막기 위해서다.

1. 운영자가 정의 파일을 Admin에게 넘긴다.
2. Admin이 `chk-admin sign-extension <정의 파일>`로 C2 `extension` claim(`{id, version, definition_hash}`)에 서명한다.
3. 정의와 봉투를 함께 Center에 올린다.

| 경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /api/v1/resources/extensions` `{definition, envelope}` | 관리자 토큰 + **C2 `extension` 봉투** | 외부 확장 등록 |
| `GET /api/v1/resources?type=extension` | 읽기·관리자 토큰, Studio·Bot UI·서버 실행기 키 (C5 권한표) | 목록 |
| `GET /api/v1/resources/extensions/{id}` | 같음 | 하나 (외부면 정의와 봉투 포함) |
| `DELETE /api/v1/resources/extensions/{id}` | 관리자 토큰 + C2 `extension_revoke` 봉투 | 해제. 쓰는 Bot이 있으면 409 `in_use` |

- **실행하는 쪽은 받은 외부 정의의 봉투를 다시 검증한다** (C2 V1~V3, `definition_hash` 일치). 검증되지 않은 정의는 쓰지 않는다.
- 같은 `id`·`version`·같은 내용이면 200, 같은 `id`·`version`인데 내용이 다르면 409 `version_conflict`. 내용을 바꾸려면 버전을 올린다.
- **이름 공간은 하나다.** 확장 `id`는 서비스 앱 `app_id`와 같은 공간을 쓴다. 이미 있는 확장·서비스 앱과 `id`가 같으면 409 `id_conflict`.
- BPM 프로세스 매니페스트(C1)의 `requires.extensions[]`는 외부 확장이면 `definition_hash`까지 고정한다. 정의가 바뀌면 Bot을 다시 승인·배포해야 한다.
- 크기 한도: 256 KB.

`definition_hash` = `sha256:<hex>` of `canonical_json(정의)` (C2 규칙).

## 모델

### ExtensionManifest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 2 |
| `id` | str | ✓ | `^[a-z][a-z0-9-]{1,49}$`. 서버 부분이 있으면 그 `app_id`와 같다 (예: `ui-automation`) |
| `version` | str | ✓ | SemVer |
| `name` | str | ✓ | 화면 표시 이름 |
| `description` | str | | 화면 표시 설명 |
| `publisher` | str | ✓ | 화면 표시 제공자 |
| `tier` | `builtin` \| `internal` \| `external` | ✓ | 등급 (ADR-0018 §3) |
| `api` | str | 내장·사내 ✓ | 필요한 `extension_api` 버전 범위 (예: `>=1,<2`) |
| `service` | Service | | 서버 부분 (아래) |
| `contributes` | Contributes | ✓ | 기여 (아래) |
| `requires_keys` | KeyNeed[] | | 이 확장이 쓰는 서비스 앱 키 |
| `docs_url`, `console_url` | str | | `http(s)://`만 (콘솔이 링크로 보이므로) |

### Service

| 필드 | 뜻 |
| --- | --- |
| `protocol` | `chk-c11`(C11을 따르는 서비스 앱) 또는 `http-adapter`(외부 앱, §4) |
| `base_url` | 기본 주소. **주소의 출처는 하나다:** Center 리소스 등록(C7)의 `base_url`이 있으면 그것을, 없으면 이 값을 쓴다. 클라이언트 설정에 따로 두지 않는다 |
| `adapter` | `protocol=http-adapter`일 때만 (§4) |

### Contributes

| 키 | 모양 | 누가 쓰나 | 외부 확장 |
| --- | --- | --- | --- |
| `task_types` | `[{id, label, icon, bpmn: "serviceTask", editor, executor, run_locations}]` | Studio 팔레트·속성 패널, 실행기 | 불가 (서비스 앱 태스크로 씀) |
| `studio.editors` | `[{task_type, entry}]` | Studio | 불가 (자동 폼) |
| `studio.resource_views` | `[{id, label, resource_type, creates_task_type?}]` | STU-03 | 가능 (선언) |
| `bot_ui.utilities` | `[{id, label, menu: "tools", entry, needs_runtime?}]` | Bot UI 「도구」 메뉴·탭 | 불가 |
| `bot_ui.local_runtimes` | `[{id, label, entry, port_setting, default_port, health, token_dir, start}]` | Bot UI (BUI-09·11) | 불가 |
| `agent_environments` | `[{domain, entry}]` | 엔진 — `domain: web`·`desktop` AI 태스크의 눈과 손 ([ADR-0037](../decisions/0037-desktop-ai-task-environment.md)) | 불가 |
| `configuration` | `[{key, label, scope, schema, secret}]` | 설정 화면 칸 (BUI-03 「확장별 설정」, STU-10, 서버 실행기 설정) | 불가 |
| `preflight` | `[{id, entry}]` | Studio·Bot UI·서버 실행기 사전 점검 | 불가 |
| `console.pages` | `[{id, label, module}]` | 서비스 앱 관리 콘솔 | 불가 (자기 콘솔 링크만) |
| `resources` | `[{type, label, catalog_url}]` | Center 리소스 목록 (C7) | 가능 |

필드 설명:

- `run_locations`: 이 태스크 종류를 쓸 수 있는 실행 위치. `ui_task`는 `["pc"]`다.
- `agent_environments[].entry`: `extension_api.AgentEnvironment`. 엔진이 AI 태스크마다 `open(ctx)`로 **세션 하나**를 열어 그 도구(`AgentTool` — 이름·설명·인자 스키마·부를 함수)를 허용 목록에 더해 쓰고, 끝나면 `close()`한다. 한 `domain`은 한 확장만 기여한다 (둘이면 검사 오류 E8).
- `start`: `on_demand` 또는 `always`.
- `bot_ui.local_runtimes[].entry`: 런타임을 **실행하는 코드**를 가리킨다 (`entry` 형식은 위와 같고, 그 확장 패키지 안만 가리킬 수 있다). **명령줄을 확장이 적지 않는다** — Bot UI가 만든다 ([ADR-0024](../decisions/0024-desktop-packaging-extensions.md)).
  - Bot UI는 **자기 실행 파일을 자식으로 다시 띄운다**: `<Bot UI 실행 파일> --local-runtime <확장 id>:<런타임 id> --port <p> --token-dir <폴더>`. 개발 환경(소스 실행)에서는 같은 인자로 `python -m chaeksas.bot_ui`다.
  - 자식은 그 확장의 `entry`를 풀어 부르고, 그때부터 화면 없는 서버로 돈다 (Worker는 C10).
  - 왜 명령이 아니라 진입점인가: 설치 파일로 묶은 앱 안에는 콘솔 스크립트(`chk-worker`)가 없다 (PyInstaller는 실행 파일 하나를 만든다). 같은 실행 파일로 띄우면 DPI 선언([ADR-0021](../decisions/0021-worker-dpi-capture.md))·서명·파이썬 런타임을 그대로 함께 쓴다.
  - 작업 관리자에서는 Bot UI와 같은 이름으로 보인다. 구별은 명령줄(`--local-runtime …`)로 한다.
- `bot_ui.utilities[].needs_runtime`: 그 유틸리티를 열기 전에 호스트가 띄워야 할 **로컬 런타임의 id**. 띄우지 못하면 유틸리티를 열지 않고 왜 못 열었는지 말한다 (「없는데 된 척」하지 않는다).
- **호스트가 채우는 예약 설정 키** — 띄운 로컬 런타임이 어디 있는지는 **확장이 설정으로 받는다** (`ctx.setting(…)`). 확장이 포트를 다시 계산하거나 토큰 파일 자리를 추측하지 않게 한다.

  | 키 | 값 |
  | --- | --- |
  | `runtime.<런타임 id>.port` | 호스트가 정한 포트 (int) |
  | `runtime.<런타임 id>.token_dir` | 토큰 파일 폴더 (str). 정의에 `token_dir: true`일 때만 |
  | `runtime.<런타임 id>.state` | `off` · `running` · `restarting` · `stopped` (C4 `WorkerState.state`와 같은 낱말) |
  | `storage.dir` | 이 확장이 **자기 파일을 둘 폴더** (호스트가 만들어 준다). 밀린 등록 큐처럼 확장이 혼자 들고 있어야 하는 것을 여기 둔다. **비밀은 두지 않는다** (OS 비밀 저장소로 간다) |
  | `service.base_url` | 이 확장의 **서버 부분 주소**. **출처는 하나다** — Center 리소스 등록(C7)에 있으면 그것을, 없으면 정의의 `service.base_url`을 쓴다. 확장이 설정 칸으로 따로 받지 않는다 |

  로컬 런타임 자식에게는 같은 주소를 환경변수 **`CHK_RUNTIME__SERVICE_URL`**로 물려준다 (이름은 플랫폼이 정한다 — 호스트가 확장 이름을 모르고 넣을 수 있어야 한다). **비밀은 물려주지 않는다** — 키는 부르는 쪽이 세션마다 준다 (C10 `service_key`, ADR-0013).

  `runtime.`·`service.`·`storage.`로 시작하는 키는 **호스트가 소유한다** — 확장이 `configuration`에 같은 이름을 선언하면 거부한다 (E7).
- `configuration`의 `scope`: `bot_ui`, `studio`, `server_runner` 중 하나.
- `configuration`의 `schema`: JSON Schema. 확장이 설정 칸을 이것으로 선언한다.
- **`secret: true`인 칸은 OS 비밀 저장소에 둔다** (ADR-0013). 설정 파일·로그에는 남기지 않는다. 키(`requires_keys` `utility`)도 이 칸으로 받는다.
- `editor`: 두 가지 중 하나다.
  - `{"kind": "builtin", "entry": "…"}`: 확장이 준 편집기.
  - `{"kind": "schema"}`: 입력 JSON Schema로 만든 자동 폼 (STU-14 방식).
- `executor`: `{"entry": "…"}`. `extension_api.TaskExecutor`를 구현한다.
- **`entry` 형식: `"<모듈>:<이름>"`.** 모듈은 확장 이름 공간(`chaeksas.ext`) 밑에서 찾는다 — `ui_automation.client:UiTaskExecutor`는 `chaeksas.ext.ui_automation.client.UiTaskExecutor`다 ([ADR-0019](../decisions/0019-package-names.md)). 가리키는 것은 **인자 없이 만들 수 있는 클래스**(또는 이미 만들어진 객체)이고, 확장 호스트가 만들어 `extension_api`의 모양인지 확인한 뒤 켠다.
  - 확장 호스트는 **그 확장의 패키지 안**만 허용한다. 정의가 다른 모듈(`os:getcwd` 같은 것)을 가리켜 import시킬 수 없다.
- `resources[].catalog_url`: 상대 경로(서버 부분 기준) 또는 `allowed_hosts` 안의 주소. 응답은 §5 공통 카탈로그 형식이다.

### KeyNeed

| 필드 | 뜻 |
| --- | --- |
| `purpose` | 키를 어디에 쓰나. 두 가지 중 하나다 (아래) |
| `extra_scopes` | 그 키에 필요한 추가 권한 (C11 키 레코드와 같은 이름, 예: `registry_write`) |
| `config_key` | `utility`일 때 그 키를 받는 `configuration` 칸 |

`purpose` 값:

- `run`: BPM 프로세스가 작업을 부를 때. BPM 프로세스의 키 참조로 지정한다.
- `utility`: Bot UI 유틸리티가 쓸 때. `configuration`의 `secret` 칸으로 받는다.

## 4. HTTP 어댑터 (`protocol: "http-adapter"`, 외부 확장)

### 4-1. 필드

| 필드 | 뜻 |
| --- | --- |
| `allowed_hosts` | 부를 수 있는 호스트 목록 (정확한 이름, 와일드카드 없음). `base_url`·Center의 `base_url`·`catalog_url`·`health`의 호스트가 모두 이 안에 있어야 한다 |
| `allow_private_network` | 기본 false. 사설망·루프백·링크 로컬 주소를 부르려면 true여야 하고, 이것도 서명 대상이다 |
| `auth` | `{type: "bearer" \| "header", name?}`. 값은 BPM 프로세스 키 참조로 푼 키. **쿼리 문자열 인증은 없다** (주소·로그에 키가 남는다). 템플릿에서는 키를 쓸 수 없다 |
| `limits` | `{timeout_s: 60, max_response_kb: 1024}` |
| `health` | 선택. `{path, expect_status: 200}`. 없으면 Center는 상태를 「확인 전」으로 둔다 |
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

- PC: 확인(`confirmation`)으로 넘긴다.
- 서버: 실행 실패 또는 오류 경계 이벤트로 보낸다.

### 4-2. 템플릿 규칙 (주입 막기)

| 위치 | 쓸 수 있는 것 | 처리 |
| --- | --- | --- |
| `path` | 고정 문자열 + `{{input.<필드>}}` | 반드시 `/`로 시작. 값은 **경로 조각 하나로 퍼센트 인코딩**한다 (`/`, `..`, `@`, `?`, `#`도 인코딩) |
| `query` | `{이름: 템플릿}` | 값마다 인코딩 |
| `headers` | 고정 이름 → 템플릿 | 값에 CR·LF·제어 문자가 있으면 거부. `Authorization`·`Host`·`Cookie`는 템플릿으로 못 쓴다 |
| `body` | JSON 템플릿 | 값은 JSON 값으로 넣는다 (문자열 이어 붙이기 없음) |

- 쓸 수 있는 변수: `{{input.<필드>}}`, `{{run_id}}`, `{{node_id}}`, `{{idempotency_key}}`(C11 멱등 키 문자열). 그 밖의 변수·식은 정의 검사에서 거부한다.
- 출력 경로와 `error_when`의 `path`는 **제한된 JSONPath**만 쓴다: `$`, `.이름`, `[숫자]`. 필터·식·와일드카드는 쓸 수 없다.

### 4-3. 호출 규칙 (해석기 `core.http_adapter`)

1. 주소를 만든다: 리소스 등록의 `base_url`(없으면 정의의 `base_url`) + `path`.
2. **https만 쓴다.** `allow_private_network: true`이고 호스트가 사설 주소인 경우만 http를 허용한다.
3. 호스트가 `allowed_hosts`에 있는지 본다.
4. **DNS를 한 번 풀고 그 IP로 접속한다** (DNS 재바인딩 방지). `allow_private_network=false`면 루프백(127.0.0.0/8, ::1), 사설(10/8, 172.16/12, 192.168/16, fc00::/7), 링크 로컬(169.254/16, fe80::/10)을 거부한다. 이 규칙은 같은 PC의 Worker(127.0.0.1:8899)도 막는다.
5. **리다이렉트를 따라가지 않는다.** 3xx는 오류(`redirect_not_allowed`)로 처리한다.
6. 응답은 **읽는 동안** `max_response_kb`를 넘으면 끊는다.
7. 결과를 C3 `service_call`로 남긴다 (`app_id` = 확장 `id`). 요청·응답 본문은 남기지 않는다.

## 5. 공통 카탈로그 형식 (`resources[].catalog_url`)

확장이 Center 리소스 목록에 올리는 자원은 모두 이 형식으로 준다. 플랫폼(C7)은 이 형식만 안다.

```json
{
  "schema": 1,
  "revision": 482,
  "items": [{"type": "ui_page", "id": "erp.order.form", "name": "ERP 주문 입력",
             "summary": "요소 12개 · 사용 중 9", "updated_at": "…", "data": {"…": "확장 고유 내용"}}]
}
```

- `data`의 모양은 확장이 정한다. 예를 들어 UI 자동화 확장은 C9 카탈로그 항목을 쓴다. Center는 `data`를 해석하지 않고 그대로 Studio에 넘긴다.
- **비밀·셀렉터·업무 값을 넣지 않는다.** 카탈로그는 서버망 안에서만 연다 (역방향 프록시에서 바깥 노출을 막는다).

## 예시

### 내장 확장 (요약)

```json
{
  "schema": 2, "id": "ui-automation", "version": "0.4.0", "name": "UI 자동화", "publisher": "Chaeksas",
  "tier": "builtin", "api": ">=1,<2",
  "service": {"protocol": "chk-c11", "base_url": "http://svc-uia:8000"},
  "requires_keys": [
    {"purpose": "run", "extra_scopes": []},
    {"purpose": "utility", "extra_scopes": ["registry_write"], "config_key": "registrar_key"}],
  "contributes": {
    "task_types": [{"id": "ui_task", "label": "UI 태스크", "icon": "mouse-pointer-click", "bpmn": "serviceTask",
                    "editor": {"kind": "builtin", "entry": "ui_automation.client:UiTaskEditor"},
                    "executor": {"entry": "ui_automation.client:UiTaskExecutor"}, "run_locations": ["pc"]}],
    "studio.resource_views": [{"id": "ui-pages", "label": "UI 화면", "resource_type": "ui_page", "creates_task_type": "ui_task"}],
    "bot_ui.utilities": [{"id": "selector-registration", "label": "UI 셀렉터 등록", "menu": "tools",
                          "entry": "ui_automation.client:SelectorRegistration", "needs_runtime": "worker"}],
    "bot_ui.local_runtimes": [{"id": "worker", "label": "Worker 프로세스", "entry": "ui_automation.worker:serve",
                               "port_setting": "CHK_WORKER__LOCAL_API__PORT", "default_port": 8899,
                               "health": "/v1/health", "token_dir": true, "start": "on_demand"}],
    "configuration": [{"key": "registrar_key", "label": "등록 담당자 키", "scope": "bot_ui",
                       "schema": {"type": "string"}, "secret": true}],
    "preflight": [{"id": "pages-registered", "entry": "ui_automation.client:PagesRegisteredCheck"}],
    "console.pages": [{"id": "overview", "label": "개요", "module": "ui-automation/overview"}],
    "resources": [{"type": "ui_page", "label": "UI 화면", "catalog_url": "/v1/catalog"}]
  }
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
| E3 | `http-adapter`: `allowed_hosts`·https·템플릿 변수·경로 시작 `/`·제한 JSONPath·금지 헤더 규칙(§4) | 422 `adapter_invalid` (`detail`에 칸별 사유) |
| E4 | `task_types[].id`는 확장 사이에 겹치지 않는다 | 409 `task_type_conflict` |
| E5 | 확장 호스트는 `api` 범위가 맞지 않는 확장을 켜지 않는다 (목록에 「호환 안 됨」) | — |
| E6 | 외부 정의의 봉투(C2 `extension`)가 검증되고 `definition_hash`가 맞는다 | 400 `bad_envelope` / `hash_mismatch` |
| E7 | `configuration[].key`가 `runtime.`·`service.`·`storage.`로 시작하지 않는다 (호스트가 쓰는 이름이다) | 422 `reserved_config_key` |
| E8 | `agent_environments[].domain`은 확장 사이에 겹치지 않는다 (한 domain의 눈과 손은 하나) | 409 `environment_conflict` |

Studio 「확장」(STU-15)의 「정의 파일 열기...」는 E1·E3을 로컬에서 먼저 돌려 보여 준다.

## 호환 규칙

- 모르는 `contributes` 키는 무시한다. 새 기여 지점은 `extension_api` 버전을 올려 추가한다.
- `tier`·`protocol` 값은 열린 문자열이지만, 확장 호스트는 아는 값만 켠다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-05 | 2 | `agent_environments`(AI 태스크의 `web`·`desktop` 환경)를 더했다. 모르는 열쇠는 무시하므로 기존 호스트는 영향이 없다 | 0037 |
| 2026-10-01 | 1 | 초안 | 0018 |
| 2026-10-01 | 1 | 검토 반영 (아래) | — |
| 2026-10-02 | 1 | 구현하며 명시한 것: `entry` 형식과 그 확장 패키지 안으로 제한, 예시의 편집기·유틸리티 entry를 `client`로 (ADR-0018 §6 폴더 구성) | 0018 |
| 2026-10-02 | 1 | 설치 파일로 묶어 보고 명시한 것: `extension.json`은 파이썬 패키지 안 | 0024 |
| 2026-10-05 | 2 | 예약 설정 키에 `storage.dir`을 더했다 — 확장이 자기 파일을 둘 폴더 (밀린 등록 큐 등) | 0018 |
| 2026-10-05 | 2 | 예약 설정 키에 `service.base_url`을 더했다 — 서버 주소의 출처를 하나로 (Center 리소스 등록 > 정의) | 0013, 0018 |
| 2026-10-05 | 2 | 호스트가 채우는 **예약 설정 키**(`runtime.<id>.port`·`token_dir`·`state`)를 적었다 — 유틸리티가 띄워진 런타임을 설정으로 받는다. 같은 이름을 확장이 선언하면 거부한다 (E7). 새 칸이 아니라 호스트가 주는 값이라 schema는 그대로 | 0018, 0024 |
| 2026-10-03 | **2** | `bot_ui.local_runtimes`의 `command`(명령 배열)를 **`entry`**(진입점 문자열)로 **바꿨다.** 명령줄은 Bot UI가 만들고, 자기 실행 파일을 자식으로 다시 띄운다. 필드의 뜻이 바뀌었으므로 schema를 올린다 | 0024 |

검토 반영 내용:

- 외부 정의는 Admin 서명(C2 `extension`)을 받아야 쓰이고, C1에 `definition_hash`로 고정한다.
- 어댑터 안전 규칙을 더했다: https만, 리다이렉트 금지, 사설망 차단, DNS 고정, 위치별 인코딩, 쿼리 인증 제거, 제한 JSONPath, 읽는 동안 크기 상한.
- `configuration` 기여 지점(비밀 칸은 OS 비밀 저장소)을 더했다.
- 주소 출처를 하나로 했다.
- 이름 공간을 하나로 했다.
- 외부 작업의 기본 모드를 자율 수행으로 했다.
- 공통 카탈로그 형식을 정했다.

# C11. 서비스 앱 공통

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-09, [09-gaps](../09-gaps.md) §1 대조) — 2026-10-29부터 **일꾼**이다 ([ADR-0102](../decisions/0102-calling-outside-is-pull.md)): 앱은 C15로 Center에서 일감을 가져가고 HTTP로 업무 호출을 받지 않는다 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 서비스 앱(일꾼) → Center (C15 가져가기·끝내기). 업무 호출의 모양은 부르는 쪽이 C15로 Center에 올린 것이다 |
| 코드 위치 | 모델 `packages/contracts/src/chaeksas/contracts/service_app.py`, 받는 쪽 뼈대 `packages/service_kit/` (`service_kit.consumer` — 가져가기 루프·들이기), **부르는 쪽 `chaeksas.core.services`** (`CenterServiceCaller` — 멱등 칸·재시도·C3 `service_call` 기록). 보기: 업무 예제가 부르는 **모의 앱 열셋**은 [`samples/`](../../samples/README.md) |
| JSON Schema | [`c11-service-app-manifest.json`](../../packages/contracts/schemas/c11-service-app-manifest.json) · [`c11-op-request.json`](../../packages/contracts/schemas/c11-op-request.json) · [`c11-op-response.json`](../../packages/contracts/schemas/c11-op-response.json) · [`c11-health-response.json`](../../packages/contracts/schemas/c11-health-response.json) |
| 관련 ADR | [0010](../decisions/0010-service-apps.md), [0015](../decisions/0015-run-location.md), [0102](../decisions/0102-calling-outside-is-pull.md) |
| 관련 화면 | STU-14, SVC-00·01·03, CON-07 |

## 목적

**서비스 앱은 확장의 서버 부분이다** ([ADR-0018](../decisions/0018-extensions.md)). 내장·사내 확장의 서비스 앱은 이 계약을 따르고, 이 계약을 따르지 않는 외부 앱은 확장 정의의 HTTP 어댑터(C13 §4)를 **어댑터 일꾼**이 돌려 붙인다. 서비스 앱이 늘어나도 부르는 쪽은 **한 가지 방식**(C15 외부 작업)으로 부르고, Studio는 manifest로 서비스 앱 태스크 편집기(STU-14)를 만들며, 관리 콘솔은 `service_kit`이 같은 모양으로 제공한다.

## 전송

| 길 | 인증 | 뜻 |
| --- | --- | --- |
| C15 `POST /api/v1/consumers/enroll`·`fetch`·`…/complete·fail·extend` | 일꾼 토큰 | 들이기, 일감 가져가기·끝내기 |
| C15 `PUT /api/v1/consumers/self/manifest`·`…/catalogs/{type}` | 일꾼 토큰 | manifest(작업 목록)·기여 자원 카탈로그 올리기 |
| `GET /healthz` | 없음 | 살아 있는지 (운영자·컨테이너 점검용 — **Center는 읽지 않는다**) |
| 관리 콘솔 (웹) | 관리자 토큰 | SVC-00·01·03 (+ 앱 고유 화면). 기본 포트 = API 포트 + 1 |

- **앱은 업무 호출을 HTTP로 받지 않는다.** `POST /v1/ops`·`/manifest`·앱 안의 API 키(`/v1/keys/self`·`/center/v1/keys`·`/center/v1/trust`)는 없다. 「누가 불러도 되나」는 Center가 배포로 가린다 (C15 §올리기).
- 멱등: **멱등 칸 = `(operation, run_id, node_id, node_instance, attempt, call_seq)`** (C15 `idempotency` + `operation`). 같은 칸으로 다시 오면(`delivery` ≥ 2 — 잠금이 지나 다시 나갔다) 수행하지 않고 저장된 결과를 그대로 끝낸다 (`replayed: true`). 같은 칸인데 본문(`input`·`mode`) 해시가 다르면 실패 `idempotency_conflict`. 보관 기간 기본 7일 (`CHK_SVC_<APP>__IDEMPOTENCY_DAYS`).
  - **부르는 쪽은 재시작 뒤에도 `node_instance`·`attempt`·`call_seq`를 같은 값으로 다시 만들어야 한다** (contracts README 원칙 9) — 그래야 Center가 같은 일감을 돌려준다.
- 시간 제한: 작업마다 manifest의 `timeout_s` (기본 60). C15 일감의 기한이 된다.
- 크기 한도: 입력·출력 각 1 MB (C15).

## 모델

### `GET /healthz` 응답

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `status` | `ok` \| `degraded` | `degraded`면 `reasons`에 이유 (예: `llm_unreachable`) |
| `version` | str | |
| `reasons` | str[] | |

### ServiceAppManifest (일꾼이 Center에 올린다)

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `app_id` | str | ✓ | 예: `tax-invoice` |
| `name` | str | ✓ | 표시 이름 |
| `version` | str | ✓ | SemVer |
| `category` | `business` \| `system` | ✓ | 업무용 / 시스템용 |
| `console_url` | str | ✓ | 관리 콘솔 주소 (CON-07 링크) |
| `extension` | object | | `{id, version}`. 이 서비스 앱이 어느 확장의 서버 부분인가 (C13). 내장·사내 확장이면 넣는다 |
| `operations` | Operation[] | ✓ | 작업 목록 |
| `resources` | ResourceCatalog[] | | 이 앱이 주는 **기여 자원 카탈로그** (C7). 아래 |

| ResourceCatalog 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `type` | str | 자원 종류 (예: `seal_specimen`). 확장이 정한다 |
| `catalog_url` | str | **쓰지 않는다** (읽고 무시한다 — 카탈로그는 일꾼이 Center에 올린다, C15 §카탈로그). 옛 앱이 적어 보내도 거부하지 않는다 |
| `label` | str | 화면에 보일 이름 (CON-07 탭 제목). 없으면 `type`을 쓴다 |

**왜 manifest가 이것을 알리나.** 확장 정의(C13 `contributes.resources`)에도 같은 것이 있지만 **내장·사내 확장의 정의는 Center에 없다** — 설치 파일에 들어 있고 Center는 실행하는 쪽의 보고로 `{id, version}`만 안다 (C7 §리소스 모으는 방식). 서버 쪽 자원을 가장 잘 아는 것은 서버 부분이라 **일꾼이 manifest와 함께 알리고 항목은 카탈로그로 올린다** (C15). 외부 확장은 정의가 Center에 있으니 거기서 읽는다 — 두 출처가 같은 모양이다.

| Operation 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `name` | str | `^[a-z][a-z0-9_]{0,63}$` |
| `description` | str | STU-14에 보이는 설명 |
| `modes` | (`autonomous` \| `deterministic`)[] | 지원하는 수행 모드 |
| `fallback` | `none` \| `autonomous` | 결정 수행이 실패했을 때. **기본 `none`** (운영에서 LLM이 몰래 개입하지 않게). `autonomous`여도 **시험 일감(`origin: test` — Studio 시험 실행)일 때만** 넘어간다. 현장 일감이면 폴백하지 않고 실패한다 |
| `input_schema` / `output_schema` | JSON Schema | STU-14 입력·출력 표의 원본 |
| `timeout_s` | int | 기본 60 |
| `server_ok` | bool | 서버 실행기에서 불러도 되는가 (기본 true. 현장 PC에서만 의미 있는 작업은 false) |
| `required_scopes` | str[] | 이 작업을 부르려면 부르는 쪽에 켜져 있어야 하는 **추가 권한**. 비어 있으면 「불러도 되나」(C15)를 지난 누구나. **지금 Center에는 추가 권한을 켜 줄 길이 없다** — 적은 작업은 아무도 올리지 못하고 C15 올리기가 403 `scope_missing`이다 ([ADR-0114](../decisions/0114-remove-ui-automation.md)) |

**추가 권한은 작업이 선언하고 Center가 건다** (C15 §올리기) — 일꾼·작업 함수는 부른 쪽을 들여다보지 않는다. 없으면 403 `scope_missing`.

### OpRequest (가져간 일감 → 작업 함수)

일꾼 뼈대가 C15 `LockedTask`를 이 모양으로 바꿔 작업 함수에 준다 — 작업 함수는 Center를 모른다.

| 필드 | 뜻 | `LockedTask`의 |
| --- | --- | --- |
| `schema` | 1 | |
| `mode` | 수행 모드. **받는 쪽은 바꾸지 않는다** (원칙 7 — 폴백은 위 `fallback`뿐) | `mode` |
| `run_id`·`node_id`·`node_instance`·`attempt`·`call_seq` | 멱등 칸 | `idempotency` |
| `caller` | `{type, host, bpm_process_id, version}`. `bpm_process_id`는 **패키지 id**다 (C3, [ADR-0086](../decisions/0086-run-identity-is-the-package-id.md)). `type`은 열린 문자열 — `bot_ui` `server_runner` `studio` | `caller` |
| `business_key` | 여러 호출을 한 업무로 잇는 키 (선택, 부르는 쪽이 정한다) | `business_key` |
| `input` | `input_schema`를 따름 | `input` |
| `origin` | `run` \| `test` — 시험 일감이면 앱이 시험 쪽으로 보낼지 정한다 (ADR-0102 §6) | `origin` |

### OpResponse (작업 함수 → 끝내기)

| 필드 | 뜻 | C15 끝내기의 |
| --- | --- | --- |
| `output` | `output_schema`를 따름 | `complete.output` |
| `mode_used` | 실제로 쓴 모드. 폴백이 일어났을 때만 `mode`와 다르다 | `complete.mode_used` |
| `replayed` | 저장된 결과를 돌려준 것인가 (멱등) | `complete.replayed` |
| `usage` | `{model, input_tokens, output_tokens}` — C3 `llm_usage`와 같은 이름 | `complete.usage` |

작업 함수가 실패를 올리면(`OpError(status, code, message)`) 뼈대가 C15 `fail`로 옮긴다 — `retryable`은 아래 표의 「다시 해 볼 만함」이다.

### 사용 기록 (앱 안, SVC-03)

시각 / 부른 쪽(`caller.type`·`host`) / 작업 / 수행 모드 / 결과(`ok` 또는 실패 코드) / 소요 / `run_id` / 몇 번째로 나갔나(`delivery`) / LLM 사용량. **입력·출력 값은 기록하지 않는다.**

## 관리 API (`/admin/v1/*`, SVC-00·01·03)

관리 콘솔이 쓰는 API. 앱 설정의 **관리자 토큰**으로만 부른다 (`Authorization: Bearer <관리자 토큰>`). 화면은 `web/apps/svc-console` 한 벌이 그린다 (ADR-0017).

| 메서드·경로 | 뜻 | 화면 |
| --- | --- | --- |
| `GET /admin/v1/status` | 앱 요약·작업별 최근 통계·의존 상태·Center 연결 | SVC-01 |
| `GET /admin/v1/usage?limit=` | 사용 기록 (최근 것부터). **입력·출력 값은 없다** | SVC-03 |

AdminStatus:

| 필드 | 뜻 |
| --- | --- |
| `app_id`, `name`, `version`, `category`, `console_url` | manifest와 같은 값 |
| `extension` | `{id, version}` — 이 앱이 **어느 확장의 서버 부분인가**. 관리 콘솔이 이것으로 그 확장의 고유 화면(C13 `console.pages`)을 고른다 ([ADR-0042](../decisions/0042-extension-contributed-panels.md)) |
| `started_at`, `uptime_s` | 가동 시간 |
| `operations` | 작업마다 `{name, description, modes, fallback, server_ok, calls_24h, errors_24h, error_rate}` — 수는 **앱 안의 사용 기록**에서 센다 |
| `dependencies` | 바깥 의존마다 `{name, status, detail?}`. `status`는 `ok`·`degraded`·`unreachable`·`unknown`. 일꾼이면 `center` 줄이 붙는다(마지막으로 가져간 때·들인 상태) |
| `center` | `{registered, base_url?, last_reported_at?}` — `registered`는 **일꾼으로 들었나**, `last_reported_at`은 마지막으로 가져간 때 |

- 관리자 토큰이 설정되지 않았으면 관리 API 전체가 503 `admin_disabled`다. **빈 토큰으로 열리지 않는다.**

## 모델 연결

모델(LLM)이 필요한 작업이 있는 앱은 `service_kit`이 주는 모델 연결을 쓴다 ([ADR-0034](../decisions/0034-service-app-model-connection.md)). 클라이언트는 `chaeksas.llm`(OpenAI 호환 `/v1/chat/completions`) 하나다.

| 환경변수 | 뜻 |
| --- | --- |
| `CHK_SVC_<APP>__LLM__BASE_URL` | 모델 주소 (`/v1/chat/completions` 앞까지) |
| `CHK_SVC_<APP>__LLM__MODEL` | 모델 이름 |
| `CHK_SVC_<APP>__LLM__API_KEY` | 키 (선택 — 키가 필요 없는 로컬 모델이면 비운다). **비밀이라 환경변수로만** 준다 |
| `CHK_SVC_<APP>__LLM__TIMEOUT_S` | 한 번 물을 때 기다리는 시간 (기본 120) |

- 주소와 모델 이름이 **둘 다** 있어야 연결된 것이다. 하나만 있으면 설정이 덜 된 것이고 연결되지 않은 것으로 본다 (관리 상태에 그렇게 보인다).
- 연결되지 않았는데 모델이 필요한 작업이 불리면 **503 `llm_unavailable`** 이다. 모델 없이 지어낸 답을 돌려주지 않는다.
- 모델을 부르다 실패하면, 잠깐 막힌 것(닿지 못함·408·429·5xx)은 503 `dependency_down`(다시 시도할 만함)이다. 그 밖(키·모델 이름이 틀림 등)은 503 `llm_unavailable`(설정 문제)이다.
- 관리 상태(`/admin/v1/status`)의 `dependencies`에 `name: "llm"` 한 줄이 생긴다.
  - 설정 없음·덜 됨: `unknown`
  - 설정됨, 아직 부른 적 없음: `unknown` (`detail`에 모델 이름)
  - 마지막 호출 성공: `ok`
  - 마지막 호출이 닿지 못함: `unreachable`
  - 마지막 호출이 그 밖의 오류: `degraded`

  **키 값·주소는 보이지 않는다.**
- 쓴 양은 작업 응답의 `usage`(`model`·`input_tokens`·`output_tokens`)로 돌려준다. 한 작업에서 여러 번 물었으면 더한다. **금액은 넣지 않는다.**
- 모델에 보내는 화면 정보는 부르는 쪽이 **가린 것**만이다 (원칙 6). 앱은 받은 입력을 저장하지 않는다.

## 오류 (실패 코드)

작업 함수·뼈대가 C15 `fail`의 `code`로 올린다. 부르는 쪽은 그대로 받는다 (C15 §결과).

| `code` | 언제 | 다시 해 볼 만함 |
| --- | --- | --- |
| `operation_not_found` | 없는 작업 (manifest가 바뀌었다) | 아니다 |
| `idempotency_conflict` | 같은 멱등 칸인데 본문이 다름 | 아니다 (버그 — `node_instance`·`attempt` 관리 확인) |
| `input_invalid` / `mode_unsupported` / `schema_unsupported` | 입력이 스키마와 다름, 작업이 그 모드를 지원 안 함 | 아니다 (업무 실패 — 오류 경계) |
| `rate_limited` | 앱의 의존이 너무 많다고 함 | **그렇다** (C14 `retry.on` 429) |
| `dependency_down` | 앱의 의존(LLM·DB)이 죽음 | **그렇다** (C14 `retry.on` 503) |
| `llm_unavailable` | 모델이 필요한 작업인데 앱에 모델이 설정되지 않음 | 아니다 — 앱 운영자가 `CHK_SVC_<APP>__LLM__*`를 고친다 |
| `internal` | 작업 함수가 예상하지 못한 예외 | 아니다 |

## 호환 규칙

- 일꾼은 모르는 일감 칸을 무시한다. 부르는 쪽은 모르는 결과 칸을 무시한다.
- 작업의 `input_schema`에 **필수 필드를 추가**하는 것은 깨는 변경이다 → 새 작업 이름(`issue_v2`)으로 낸다. 선택 필드 추가는 괜찮다.

## `service_kit`이 제공하는 것

새 서비스 앱은 작업 함수만 쓴다. 나머지는 `service_kit`이 이 계약대로 제공한다: 가져가기 루프(`Consumer` — 들이기·토큰 보관·manifest와 카탈로그 올리기·끝내기 — 잠금은 늘리지 않고 작업 `timeout_s`만큼 잡는다, C15), 멱등 저장소, 오류 형식, 사용 기록, `/healthz`, 관리 콘솔 공통 화면(SVC-00·01·03), 모델 연결(`CHK_SVC_<APP>__LLM__*`), 설정(`CHK_SVC_<APP>__CENTER__URL`·`…__CENTER__TOKEN`·`…__DATA_DIR`), 포트(관리 API 8000·8010…, 콘솔 +1).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-31 | 1 | 칸은 그대로다. `caller.type`의 아는 값에서 `worker`·`tool_ui`를 뺐고, `required_scopes`를 켜 줄 길(PC의 「셀렉터 등록」)이 없어졌다고 적었다 | [0114](../decisions/0114-remove-ui-automation.md) |
| 2026-10-29 | 1 | **앱이 일꾼이 된다** — `POST /v1/ops`·`/manifest`·앱 안의 키(`/v1/keys/self`·`/center/v1/keys`·`/center/v1/trust`)·관리 API의 키 발급을 걷고 C15 가져가기로 같은 작업을 수행한다. 폴백은 시험 일감일 때만, 추가 권한은 Center가 건다, 카탈로그는 일꾼이 올린다 | [0102](../decisions/0102-calling-outside-is-pull.md) |
| 2026-10-25 | 1 | §Center가 발급하는 키 — `CENTER__URL`, `GET /center/v1/trust`, `POST /center/v1/keys`(C2 봉투 `service_key`, 해시만), 키 레코드 `issued_by`·`center_key_id`·`issued_for`. 새 경로·선택 칸이라 옛 부르는 쪽은 그대로다 | [0094](../decisions/0094-service-app-keys-ride-the-deployment.md) |
| 2026-10-03 | 1 | 관리 API(`/admin/v1/status`·`keys`·`usage`)의 경로·모델·권한을 적었다 — ADR-0017이 경로만 말하고 모양이 없어서 콘솔이 타입을 손으로 쓸 수밖에 없었다 | 0017 |
| 2026-10-05 | 1 | 모델 연결(`CHK_SVC_<APP>__LLM__*`)과 503 `llm_unavailable`, 관리 상태의 `llm` 의존 줄을 적었다 — 서비스 앱은 `core`를 쓸 수 없어 모델 클라이언트를 `chaeksas.llm`으로 내렸다. 모델 칸은 새로 생긴 것이라 기존 앱은 영향이 없다 | 0034 |
| 2026-10-05 | 1 | `Operation.required_scopes`를 더했다 — 추가 권한을 **작업이 선언하고 뼈대가 건다** (C9의 `registry_write`를 앱마다 손으로 거는 것을 막는다). 없던 칸이라 기존 앱은 영향이 없다 | 0013 |
| 2026-10-01 | 1 | 초안 (키는 앱 관리 콘솔 발급·자체 검증, 멱등 키, `server_ok`) | 0010, 0013, 0015 |
| 2026-10-01 | 1 | 검토 반영: 멱등 키에 `operation`·`node_instance` 추가와 본문 충돌 409, 폴백은 키가 자율 수행을 허용할 때만, 키 앞자리 규칙, usage 이름 통일, 보관 7일 | — |
| 2026-10-01 | 1 | 확장 반영: manifest `extension` 선택 필드 | 0018 |
| 2026-10-08 | 1 | manifest에 `resources`(기여 자원 카탈로그)를 더했다 — **내장 확장의 정의가 Center에 없어** `catalog_url`을 찾을 길이 없었다 (C7 「UI 화면」 탭에 데이터가 닿지 못했다). 선택 칸이라 기존 앱은 영향이 없다 | 0018 |
| 2026-10-01 | 1 | 확장 검토 반영: 멱등 키에 `call_seq` | 0018 |

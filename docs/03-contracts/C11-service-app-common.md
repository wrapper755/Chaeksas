# C11. 서비스 앱 공통

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Bot UI(실행 중 Bot)·서버 실행기·Studio·Worker 프로세스 → 모든 서비스 앱 |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/service_app.py` (import `chaeksas.contracts.service_app`), 구현 뼈대 `packages/service_kit/` (import `chaeksas.service_kit`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c11-service-app-manifest.json`](../../packages/contracts/schemas/c11-service-app-manifest.json) · [`c11-op-request.json`](../../packages/contracts/schemas/c11-op-request.json) · [`c11-op-response.json`](../../packages/contracts/schemas/c11-op-response.json) · [`c11-health-response.json`](../../packages/contracts/schemas/c11-health-response.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0010](../decisions/0010-service-apps.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md) |
| 관련 화면 | STU-14, BUI-10, SVC-00~03, CON-07 |

## 목적

**서비스 앱은 확장의 서버 부분이다** ([ADR-0018](../decisions/0018-extensions.md)). 내장·사내 확장의 서비스 앱은 이 계약을 따르고, 이 계약을 따르지 않는 외부 앱은 확장 정의의 HTTP 어댑터(C13 §4)로 붙인다. BPM 프로세스가 부르는 서비스 앱(대부분 LLM 앱)이 늘어나도, 부르는 쪽은 **한 가지 방식**으로 부르고 관리하게 한다. 이 계약을 지키면 Studio가 manifest를 읽어 서비스 앱 태스크 편집기(STU-14)를 자동으로 만들고, 서비스 앱 관리 콘솔은 `service_kit`이 같은 모양으로 제공한다.

## 전송

| 엔드포인트 | 인증 | 뜻 |
| --- | --- | --- |
| `GET /healthz` | 없음 | 살아 있는지 |
| `GET /manifest` | 없음 (비밀 없음) | 앱 정보와 작업 목록 |
| `POST /v1/ops/{operation}` | **서비스 앱 API 키** | 작업 호출 |
| `GET /v1/keys/self` | 서비스 앱 API 키 | 이 키의 이름·허용 작업·허용 모드·만료 (Studio·Bot UI 「연결 테스트」용, 키 원문은 돌려주지 않음) |
| 관리 콘솔 (웹) | 관리자 토큰 | SVC-00~03 (+ 앱 고유 화면). 기본 포트 = API 포트 + 1 |

- 인증: `Authorization: Bearer <서비스 앱 API 키>`. 키는 **그 서비스 앱의 관리 콘솔(SVC-02)에서 발급**하고, 앱이 **스스로 검증**한다 (해시 저장). Center는 키를 모른다.
- 키 형식: `chk_svc_<무작위 40자>`. **앞자리 = 앞 16자**(`chk_svc_` + 무작위 8자)만 화면·기록에 남긴다. 앱 id는 키에 넣지 않는다 (앞자리가 키마다 달라야 구별된다). Center API 키도 같은 규칙으로 `chk_ctr_…` (C4).
- 멱등성: **멱등 키 = `(operation, run_id, node_id, node_instance, attempt, call_seq)`.** 같은 키로 다시 오면 수행하지 않고 저장된 결과를 그대로 돌려준다 (`replayed: true`). 같은 키인데 본문(`input`·`mode`)의 해시가 다르면 409 `idempotency_conflict`. 보관 기간 기본 7일 (`CHK_SVC_<APP>__IDEMPOTENCY_DAYS`).
  - `node_instance`: 같은 노드가 한 실행 안에서 몇 번째로 실행되는가 (BPMN 반복·다중 인스턴스). 1부터.
  - `attempt`: 같은 노드 인스턴스의 재시도 번호. 1부터.
  - `call_seq`: 한 노드 인스턴스·시도 안에서 같은 작업을 여러 번 부를 때의 일련번호 (기본 1). 예: UI 세션 안의 치유 호출들 (C8).
  - **부르는 쪽은 `node_instance`·`attempt`·`call_seq`를 호출 전에 저장한다.** 그래야 서버 실행기가 재시작 후 같은 키로 다시 불러 한 번만 수행된다 (contracts README 원칙 9).
- 시간 제한: 작업마다 manifest의 `timeout_s` (기본 60). schema 1은 동기 호출만. 더 긴 작업은 나중에 비동기 방식을 추가한다.
- 크기 한도: 요청·응답 각 1 MB (서비스 앱 설정 `CHK_SVC_<APP>__MAX_BODY_MB`).

## 모델

### `GET /healthz` 응답

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `status` | `ok` \| `degraded` | `degraded`면 `reasons`에 이유 (예: `neo4j_unreachable`) |
| `version` | str | |
| `reasons` | str[] | |

### `GET /manifest` 응답 (ServiceAppManifest)

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `app_id` | str | ✓ | 예: `ui-automation`, `tax-invoice` |
| `name` | str | ✓ | 표시 이름 |
| `version` | str | ✓ | SemVer |
| `category` | `business` \| `system` | ✓ | 업무용 / 시스템용 |
| `console_url` | str | ✓ | 관리 콘솔 주소 (CON-07 링크) |
| `extension` | object | | `{id, version}`. 이 서비스 앱이 어느 확장의 서버 부분인가 (C13). 내장·사내 확장이면 넣는다 |
| `operations` | Operation[] | ✓ | 작업 목록 |

| Operation 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `name` | str | `^[a-z][a-z0-9_]{0,63}$` |
| `description` | str | STU-14에 보이는 설명 |
| `modes` | (`autonomous` \| `deterministic`)[] | 지원하는 수행 모드 |
| `fallback` | `none` \| `autonomous` | 결정 수행이 실패했을 때. **기본 `none`** (운영에서 LLM이 몰래 개입하지 않게). `autonomous`여도 **호출한 키가 자율 수행을 허용할 때만** 넘어간다. 운영 키(결정 수행만)면 폴백하지 않고 실패한다 |
| `input_schema` / `output_schema` | JSON Schema | STU-14 입력·출력 표의 원본 |
| `timeout_s` | int | 기본 60 |
| `server_ok` | bool | 서버 실행기에서 불러도 되는가 (기본 true. 현장 PC에서만 의미 있는 작업은 false) |

### `POST /v1/ops/{operation}` 요청 (OpRequest)

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `mode` | `autonomous` \| `deterministic` | ✓ | 수행 모드. **받는 쪽은 바꾸지 않는다** (원칙 7) |
| `run_id` | str | ✓ | 실행 id (C3). Studio 단독 시험이면 `test_<hex>` |
| `node_id` | str | ✓ | BPMN 노드 id |
| `node_instance` | int | ✓ | 이 실행에서 이 노드의 몇 번째 실행인가. 1부터 |
| `attempt` | int | ✓ | 1부터. 재시도마다 +1 |
| `call_seq` | int | | 1부터 (기본 1). 같은 노드 인스턴스·시도 안에서 같은 작업을 여러 번 부를 때 +1 |
| `caller` | object | ✓ | `{type, host, bpm_process_id, version}`. `type`은 열린 문자열, 알려진 값 `bot_ui` `server_runner` `studio` `worker` |
| `business_key` | str | | UI 자동화처럼 세션을 잇는 키 (`<run_id>:<node_id>:<node_instance>:<attempt>`, C10) |
| `input` | object | ✓ | `input_schema`를 따름 |

### 응답 (OpResponse, 200)

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `status` | `ok` | |
| `output` | object | `output_schema`를 따름 |
| `mode_used` | `autonomous` \| `deterministic` | 실제로 쓴 모드. 폴백이 일어났을 때만 `mode`와 다르다 → 부르는 쪽이 C3 `service_call.mode_used`에 남김 |
| `replayed` | bool | 이전 호출 결과를 돌려준 것인가 (멱등) |
| `usage` | object | `{model, input_tokens, output_tokens}` — C3 `llm_usage`와 같은 이름 (LLM을 안 썼으면 생략) |

### 서비스 앱 API 키 (앱 안의 레코드)

| 필드 | 뜻 |
| --- | --- |
| `name` | 사람이 알아볼 이름. BPM 프로세스의 키 참조 이름과 맞추기를 권장 |
| `hash` | 키 원문의 해시 (원문은 저장하지 않음) |
| `prefix` | 앞자리 16자 (`chk_svc_` + 무작위 8자) |
| `allowed_operations` | `*` 또는 작업 이름 목록 |
| `allowed_modes` | `deterministic`(운영: Bot UI·서버 실행기용) / `autonomous`+`deterministic`(개발: Studio용) |
| `extra_scopes` | 앱별 추가 권한 (예: UI 자동화 앱 `registry_write` — UI 셀렉터 등록 담당자용) |
| `expires_at`, `created_at`, `last_used_at`, `revoked_at` | |

### 사용 기록 (앱 안, SVC-03)

시각 / 키 이름 / 작업 / 수행 모드 / 결과(HTTP 코드) / 소요 / `run_id` / `caller.type` / LLM 사용량. **입력·출력 값은 기록하지 않는다.**

## 예시

```http
POST /v1/ops/issue HTTP/1.1
Authorization: Bearer chk_svc_tax-invo_…
Content-Type: application/json

{
  "schema": 1,
  "mode": "deterministic",
  "run_id": "run_20261001_103000_d4e5f6",
  "node_id": "Task_issue",
  "node_instance": 1,
  "attempt": 1,
  "caller": {"type": "server_runner", "host": "srv_01", "bpm_process_id": "finance.invoice-issue", "version": "1.0.0"},
  "input": {"buyer_biz_no": "123-45-67890", "amount": 1100000}
}
```

응답:

```json
{"status": "ok", "output": {"invoice_no": "2026100100001"}, "mode_used": "deterministic", "replayed": false,
 "usage": {"model": "local-7b", "input_tokens": 0, "output_tokens": 0}}
```

## 오류

모든 오류 본문: `{"code": "<기계용 코드>", "message": "<사람용 한 줄>", "detail": {…}}`

| 상태 코드 | `code` | 언제 | 부르는 쪽이 할 일 |
| --- | --- | --- | --- |
| 401 | `key_missing` / `key_invalid` | 키 없음·모름 | 재시도하지 않음. 「키 참조 <이름>의 값이 틀렸습니다」 (BUI-05, STU-08) |
| 403 | `key_revoked` / `key_expired` | 폐기·만료 | 재시도하지 않음. 키 교체 안내 |
| 403 | `operation_not_allowed` / `mode_not_allowed` | 키 권한 밖 (예: 운영 키로 자율 수행) | 재시도하지 않음 |
| 404 | `operation_not_found` | 없는 작업 | 재시도하지 않음. 「작업 정의가 바뀌었습니다」 (STU-14) |
| 409 | `in_progress` | 같은 멱등 키가 아직 수행 중 | `Retry-After` 뒤 같은 요청을 다시 |
| 409 | `idempotency_conflict` | 같은 멱등 키인데 본문이 다름 | 버그. 재시도하지 않음 (`node_instance`·`attempt` 관리 확인) |
| 422 | `input_invalid` / `mode_unsupported` / `schema_unsupported` | 입력이 스키마와 다름, 작업이 그 모드를 지원 안 함 | 재시도하지 않음. 실행 실패 (또는 오류 경계 이벤트) |
| 429 | `rate_limited` | 너무 많음 | `Retry-After` 뒤 같은 요청 |
| 503 | `dependency_down` | 앱의 의존(LLM·DB)이 죽음 | 태스크 재시도 정책대로 `attempt`를 올려 다시 |
| 504 | `timeout` | `timeout_s` 초과 | 같은 `attempt`로 한 번 다시 (멱등이라 안전), 그 뒤 실패 |

## 호환 규칙

- 서비스 앱은 모르는 요청 필드를 무시한다. 부르는 쪽은 모르는 응답 필드를 무시한다.
- 작업의 `input_schema`에 **필수 필드를 추가**하는 것은 깨는 변경이다 → 새 작업 이름(`issue_v2`)으로 낸다. 선택 필드 추가는 괜찮다.
- `schema`가 더 높은 요청은 422 `schema_unsupported`.

## `service_kit`이 제공하는 것

새 서비스 앱은 작업 함수만 쓴다. 나머지는 `service_kit`이 이 계약대로 제공한다: `/healthz`, `/manifest`(작업 함수의 타입에서 생성), 키 검증·권한·멱등 저장소, 오류 형식, 사용 기록, 관리 콘솔 공통 화면(SVC-00~03), 설정(`CHK_SVC_<APP>__…`), 포트(API 8000·8010…, 콘솔 +1).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (키는 앱 관리 콘솔 발급·자체 검증, 멱등 키, `server_ok`) | 0010, 0013, 0015 |
| 2026-10-01 | 1 | 검토 반영: 멱등 키에 `operation`·`node_instance` 추가와 본문 충돌 409, 폴백은 키가 자율 수행을 허용할 때만, 키 앞자리 규칙, usage 이름 통일, 보관 7일 | — |
| 2026-10-01 | 1 | 확장 반영: manifest `extension` 선택 필드 | 0018 |
| 2026-10-01 | 1 | 확장 검토 반영: 멱등 키에 `call_seq` | 0018 |

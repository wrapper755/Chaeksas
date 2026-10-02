# C8. UI 자동화 앱: 계획·치유·보고

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Worker 프로세스 → UI 자동화 앱 (실행 중 Bot·Studio를 대신해서) |
| 코드 위치 | `extensions/ui_automation/contracts/` (plan.py, healing.py, report.py) — UI 자동화 확장이 소유 ([ADR-0018](../decisions/0018-extensions.md)) |
| 관련 ADR | [0008](../decisions/0008-map-driver-hands-boundary.md), [0010](../decisions/0010-service-apps.md) §5, [0013](../decisions/0013-api-keys.md) |
| 관련 화면 | STU-13, BUI-07·08, UIA-02·03, CON-01 「UI 태스크」 |

## 목적

UI 태스크 한 번(UI 세션)은 UI 자동화 앱과 세 번 오간다.

1. **계획:** 시맨틱 키 스텝과, 그 요소들의 로케이터 사다리 **전부**를 한 번에 받는다.
2. **치유:** 사다리가 모두 실패했을 때만 대체 로케이터 제안을 받는다.
3. **보고:** 끝나면 한 번에 묶어서 결과를 보낸다.

로케이터 사다리는 Worker가 계획을 들고 **로컬에서** 돈다. 폴백 도중에는 네트워크를 타지 않는다. 정책(시간 제한·치유 한도)은 계획에 실려 내려오므로, Worker를 다시 배포하지 않고도 서버가 동작을 바꿀 수 있다.

## 전송

- **C11 서비스 앱 공통 규칙을 그대로 따른다.** 세 동작은 UI 자동화 앱의 작업(operation)이다.
  - `POST /v1/ops/plan`
  - `POST /v1/ops/heal`
  - `POST /v1/ops/report`
- 인증: 세션 요청에 실려 온 **UI 자동화 앱 API 키**(C10 `service_key`). BPM 프로세스의 키 참조를 Bot 쪽에서 푼 값이다.
- OpRequest 공통 필드(`mode`, `run_id`, `node_id`, `node_instance`, `attempt`)는 C10 세션 요청의 값을 그대로 쓴다. `caller.type`은 `worker`이고 `business_key`는 C10의 4단 형식이다.
- **`call_seq`(C11):** 한 UI 세션 안에서 같은 작업을 여러 번 부르므로, Worker가 세션마다 작업별 일련번호를 매긴다. 그래야 C11 멱등 키가 겹치지 않는다.
  - `plan`: 1, 다시 계획하면 2, 3…
  - `heal`: 세션 안 치유 호출마다 1, 2, 3… (`heal_attempt`와는 따로 센다)
  - `report`: 1
  - Worker는 `call_seq`를 호출 전에 세션 기록에 저장한다.
- 멱등성:
  - `plan`·`heal`: 같은 멱등 키로 다시 보내면 같은 결과를 돌려준다.
  - `report`: 한 번만 반영된다.
- **보고 재전송 규칙:** Worker는 보고를 디스크 큐에 둔다.
  - 5xx·연결 실패면 같은 요청을 다시 보낸다 (30초부터 최대 10분 간격).
  - **4xx면 다시 보내지 않고** 「보내지 못한 보고」로 옮긴다 (BUI-09 「밀린 보고」에 보임).
  - 서버는 모르는 화면·요소·로케이터가 섞인 보고도 **거부하지 않는다.** 아는 부분만 반영하고 응답 `ignored`에 개수를 알린다. 실행 중 화면이 삭제돼도 보고가 영원히 걸리지 않게 하기 위해서다.
- 수행 모드:

  | 작업 | 자율 수행 | 결정 수행 |
  | --- | --- | --- |
  | `plan` | `steps` 또는 `goal` (LLM이 계획) | **`steps`만.** `goal`을 보내면 422 `mode_unsupported` |
  | `heal` | 가능 | 가능. 치유는 폴백이 아니라 **UI 자동화 확장의 정해진 기능**이다. UI 태스크마다 켜고 끈다 (STU-13 「자가 치유 사용」, 기본 켬, C10 `heal`). 결정 수행 Bot이 치유(LLM)를 쓸 수 있으면 사전 점검이 「이 Bot은 UI 태스크에서 자가 치유(LLM)를 쓸 수 있습니다」를 알린다. 운영에서 막으려면 운영 키의 허용 작업에서 `heal`을 빼면 된다 (403 → 전환). manifest에 두 모드를 모두 선언한다. 제안은 반드시 Worker가 로컬에서 검증한 뒤에만 쓴다 |
  | `report` | 가능 | 가능 |

## 모델

### LocatorSpec (로케이터 하나)

| 필드 | 타입 | 뜻 |
| --- | --- | --- |
| `type` | `role` \| `test_id` \| `css` \| `xpath` (웹), `automation_id` \| `class_name` \| `control_name` (데스크톱) | 전략 |
| `value` | str | `role`이면 ARIA role, 그 밖은 셀렉터 문자열 |
| `name` | str? | `role`일 때만, 필수. 접근성 이름 |
| `priority` | int? | 없으면 기본값: role 1, test_id 2, css 3, xpath 4 / automation_id 1, class_name 2, control_name 3 |
| `status` | `active` \| `unverified` \| `deprecated` | `deprecated`는 시도하지 않는다 |
| `exact` | bool | 이름 정확히 일치 |
| `control_type` | str? | 데스크톱만. 그 전략으로 찾은 것을 **컨트롤 종류로 좁힌다** (예: `Edit`, `Button`, `DataItem`). 값은 UIA ControlType 이름이고, Linux 백엔드는 AT-SPI 역할로 옮긴다 |
| `timeout_ms` | int? | |
| `platform` | `web` \| `desktop` | 전략과 맞아야 한다 |

- `locator_key` = `<type>|<value>|<name 또는 빈 문자열>`. 통계·승격·보고에서 로케이터를 가리킬 때 쓴다. **`control_type`은 열쇠에 넣지 않는다** — 같은 요소를 좁히는 조건일 뿐이라, 넣으면 같은 로케이터의 통계가 갈린다.
- **데스크톱 전략은 안정한 순서대로 쓴다** ([ADR-0020](../decisions/0020-windows-desktop-backend.md)).
  - `automation_id`(UIA `AutomationId`)가 가장 안정하다. 그러나 메모장 편집기처럼 **`AutomationId`가 없는 컨트롤이 흔하다.**
  - `class_name`(UIA `ClassName`)은 언어를 따라 바뀌지 않아 `control_name`보다 먼저 시도한다. 대신 창 안에서 여러 개가 같은 값을 가질 수 있어 `control_type`으로 좁히는 것을 권한다.
  - `control_name`(UIA `Name`)은 **화면 언어에 따라 달라진다** (같은 메모장 편집기가 한국어에서 「텍스트 편집기」다). 이것만으로 잡은 로케이터는 다른 언어 PC에서 깨진다 — 등록할 때 `class_name`을 함께 남긴다.

### plan

입력:

| 필드 | 필수 | 뜻 |
| --- | --- | --- |
| `page_id` | ✓ | |
| `platform` | | 기본 `web` |
| `start_url` | | |
| `steps` | 결정 수행 ✓ | `[{semantic_key, action, value?, expect_navigation}]`. 동작과 값 규칙은 C10과 같다 |
| `goal`, `values` | 자율 수행만 | 목표 한 줄과 쓸 값 (STU-13 「목표로 계획」) |

출력 (ExecutionPlan):

| 필드 | 뜻 |
| --- | --- |
| `plan_id` | |
| `page_id`, `platform`, `start_url` | |
| `revision` | 레지스트리 판 번호 (C9). Worker 캐시 키에 쓴다 |
| `steps` | 확정된 스텝 (자율 수행이면 LLM이 만든 스텝) |
| `locators` | `{semantic_key: LocatorSpec[]}`. **스텝에 나오는 모든 요소의 사다리 전부** |
| `elements` | `{semantic_key: {description, role}}`. 치유 프롬프트용 시맨틱 정보 (셀렉터 아님) |
| `policy` | `{locator_timeout_ms: 2000, action_timeout_ms: 10000, navigation_timeout_ms: 30000, require_unique_match: true, max_healing_attempts: 3}` |

- 모든 스텝의 `semantic_key`에 사다리가 있어야 한다. 없으면 422 `unknown_semantic_key` (C10 같은 코드).
- **오프라인 캐시:** Worker는 `(page_id, platform, steps 해시, revision)`으로 계획을 캐시한다. 서버에 닿지 못하면 캐시를 쓴다 (C10 `plan_source: "cache"`). 자율 수행(`goal`)은 캐시하지 않는다.

### heal

입력:

| 필드 | 뜻 |
| --- | --- |
| `page_id`, `semantic_key`, `description`, `role` | |
| `heal_attempt` | 이 요소에 대한 치유 시도 번호. 1부터, 상한은 `policy.max_healing_attempts` |
| `failure` | `{tried: [locator_key...], reasons: [...], url}` |
| `aria_snapshot` | 접근성 스냅샷. 최대 32 KB |
| `sub_dom` | 실패 지점 주변 HTML. 최대 16 KB |

- **업무 값 가리기:** Worker는 보내기 전에 입력칸의 `value` 속성과 입력 글자, 비밀번호 칸, 표 셀 글자를 `•••`로 바꾼다. 구조와 라벨만 남긴다 (원칙 6).

출력:

| 필드 | 뜻 |
| --- | --- |
| `locator` | 제안된 로케이터. 없으면 `null` (정상적인 분기다. 횟수 관리는 Worker가 한다) |
| `reasoning` | 한두 문장 |

- Worker는 제안된 로케이터가 **지금 화면에서 정확히 1개**에 맞는지 확인한 뒤에만 쓴다. 맞지 않으면 다음 시도로 넘어간다. 한도를 넘으면 **전환**(escalation)이다.

### report (UI 세션 하나의 최종 보고)

| 필드 | 뜻 |
| --- | --- |
| `business_key`, `page_id`, `plan_id`, `revision` | |
| `origin` | `run`(Bot·Studio 실행) \| `test`(셀렉터 등록의 「셀렉터 시험」 BUI-08). **`test` 보고는 승격 통계에 넣지 않는다.** UIA-03에서 따로 보인다 |
| `status` | `succeeded` / `escalated` / `failed` (열린 문자열) |
| `steps_completed`, `steps_total` | |
| `attempts[]` | `{semantic_key, locator_key, succeeded, elapsed_ms, matched_count?, failure_reason?}`. 서버가 로케이터 통계를 갱신한다 |
| `healed[]` | `{semantic_key, locator: LocatorSpec, heal_attempt, supersedes: [locator_key], reasoning}`. **로컬 검증을 통과한 것만** |
| `escalation`? | `{semantic_key, reason, attempts, url}` |
| `error`? | `{code, message}` |
| `duration_ms` | |

- **업무 값은 보내지 않는다.** 읽기 결과(`text`·`data`)는 보고에 넣지 않는다. 프로토타입의 `outputs`(읽은 값)는 없앴다. UIA-03 모니터링은 진행·폴백·치유만 보면 된다.
- 셀렉터 등록의 「셀렉터 시험」(BUI-08)도 같은 보고를 보낸다. 이때 `origin: test`이고, `run_id`에는 등록 세션의 `business_key`(`reg_<hex8>`)를 넣는다.

### 서버가 보고로 하는 일 (승격 규칙)

| 규칙 | 내용 |
| --- | --- |
| 통계 | `origin: run` 보고의 `attempts`마다 로케이터의 성공·실패 수를 갱신한다 |
| 치유 등록 | `healed`의 로케이터는 `unverified`로 사다리에 더한다. 조회는 `unverified`도 쓰므로 바로 실행된다 |
| 승격 | `unverified` 로케이터가 실행에서 **3회 연속 성공**하면 `active`로 올리고, 그 항목의 `supersedes`를 `deprecated`로 내린다 (`CHK_SVC_UI_AUTOMATION__PROMOTE_AFTER`) |
| 강등 | `active` 로케이터가 최근 N회(기본 10) 실패율 50%를 넘으면 경고만 한다 (UIA-02 띠). 자동 강등은 하지 않는다 |
| 전환 | `escalation`은 UIA-03 「전환」으로 보인다. 사람 확인은 PC Bot이 현장에서 처리하므로(CMN-01) 서버는 기록만 한다 |

## 오류

C11 오류 형식을 따른다. 이 계약에서 더하는 코드는 다음과 같다.

| 상태 코드 | `code` | 언제 | Worker가 할 일 |
| --- | --- | --- | --- |
| 404 | `page_not_found` | 등록되지 않은 화면 | 세션 열기 실패 → C10 422 `unknown_semantic_key`와 같은 처리 (재시도하지 않음) |
| 422 | `unknown_semantic_key` | 스텝 요소에 사다리가 없음 | 같음 |
| 422 | `mode_unsupported` | 결정 수행에서 `goal` | 버그 (Studio가 막아야 함) |
| 413 | `snapshot_too_large` | `aria_snapshot`·`sub_dom` 상한 초과 | 잘라서 다시 보낸다 |

보고(`report`)는 모르는 화면·요소에도 200 + `{accepted, ignored}`를 돌려준다 (위 재전송 규칙).

## 호환 규칙

- C11과 같다. 로케이터 `type`·`status`에 모르는 값이 오면 Worker는 그 로케이터를 건너뛴다 (사다리 전체를 버리지 않는다).
- `policy`의 모르는 필드는 무시한다.

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안. 프로토타입의 계획·치유·보고를 C11 작업으로 옮겼다. 그 과정에서 바뀐 것: 작업 임차 없앰, `business_key`·수행 모드 필수, 보고에서 읽은 값 제거, 스냅샷의 업무 값 가리기, `revision`으로 캐시 | 0008, 0010, 0013 |
| 2026-10-01 | 1 | 검토 반영: 세션 안 작업별 `call_seq`, 보고 재전송은 5xx만·4xx는 보내지 못한 보고로, 모르는 화면 보고도 받음, `origin: test`는 승격에서 제외, 치유 기본값·운영에서 막는 법 명시 | 0018 |
| 2026-10-03 | 1 | 데스크톱 로케이터에 `class_name` 전략과 `control_type` 조건을 더했다. 기본 우선순위도 바뀐다 — `control_name`이 2에서 **3**으로 내려간다 (화면 언어에 따라 달라지므로). 구현이 아직 없어 schema는 그대로 1 | 0020 |

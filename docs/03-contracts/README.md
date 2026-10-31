# 03. 계약

구성요소 사이에 오가는 모든 데이터·API의 명세. **코드보다 먼저 여기를 고친다.**
코드의 단일 원본은 `packages/contracts/`이고, 이 문서는 그 모델의 뜻·규칙·예시를 설명한다.

## 원칙

1. **원본은 하나.** 플랫폼 계약 모델은 `packages/contracts/`에, 확장 하나가 소유하는 계약은 그 확장의 `extensions/<id>/contracts/`에 둔다(지금은 없다 — [ADR-0114](../decisions/0114-remove-ui-automation.md)). 다른 앱은 import한다. 복사본·드리프트 테스트를 두지 않는다 (프로토타입 UI 자동화 서버 ↔ Worker의 교훈).
2. **스키마 버전을 명시한다.** 계약마다 `schema` 정수를 가진다. 필드 **추가**는 같은 번호에서, 필드 **변경·삭제**는 번호를 올린다.
3. **받는 쪽은 관대하게.** 모르는 이벤트 종류·선택 필드는 거부하지 않고 저장·무시한다. 필수 필드 누락만 거부한다.
4. **보내는 쪽은 엄격하게.** 보낼 때는 모델로 만들고 검증한다.
5. **JSON Schema를 내보낸다.** 모델에서 `packages/contracts/schemas/*.json`을 생성해 문서에 링크한다 — `uv run python scripts/gen_schemas.py` (`--check`는 생성물이 모델과 다르면 1로 끝난다). 다른 언어 도구도 같은 명세를 쓸 수 있다. 스키마는 **생성물이니 직접 고치지 않는다.**
6. **값은 기록하지 않는다.** 실행 기록·보고에 업무 값, 결재 답, 비밀, 스크린샷을 넣지 않는다 (기본값). 필요하면 명시적 옵션으로.
7. **수행 모드를 싣는다.** 서비스 앱에 가는 요청은 `mode`(autonomous / deterministic)를 가진다. 받는 쪽은 모드를 바꾸지 않는다. 유일한 예외는 C11의 폴백이며, 호출한 키가 자율 수행을 허용할 때만 일어나고 응답 `mode_used`로 드러난다.
8. **식별자로 서로를 잇는다.** 실행(`run_id`) ↔ 결재·확인(`request_id`) ↔ 서비스 앱 호출(`run_id`, `node_id`) 연결은 계약 필드로 한다.
9. **서비스 앱 작업은 다시 불러도 안전해야 한다.** 서버 실행기가 재시작 후 같은 멱등 키(`operation`, `run_id`, `node_id`, `node_instance`, `attempt`, `call_seq`)로 다시 부를 수 있고, 서비스 앱은 한 번만 수행한다 (C11).
10. **상태·종류·사유 값은 열린 문자열이다.** 받는 쪽은 모르는 값도 저장·표시하고, 그 값 하나 때문에 요청 전체를 거부하지 않는다. 알려진 값 목록은 문서에 둔다.

## 상태

「상태」 칸은 **그 계약이 코드와 얼마나 맞물렸나**다. 뜻이 적혀 있지 않아 올릴 때마다 사람이
다시 물었으므로, 셋을 여기 정한다.

| 상태 | 뜻 | 올리는 조건 |
| --- | --- | --- |
| **초안** | 글이 먼저 있다 (코드보다 먼저 고치는 자리다) | — |
| **합의** | 모양이 정해졌고 **모델·검사가 코드로 있다**. 쓰는 쪽이 아직 다 붙지 않았다 | `packages/contracts/`(또는 그 확장의 `contracts/`)에 모델과 검사 규칙이 있다 |
| **구현됨** | **양쪽이 코드로 쓰고 시험이 지킨다** — 보내는 쪽과 받는 쪽이 다 있다 | 위 + 오가는 양쪽에 부르는 코드가 있고, 그것을 보는 시험이 있다 |

**「상태」는 각 계약 문서의 머리말이 원본이다** (원칙 1). 아래 표는 그것을 모아 보여 주는
것이라 **어긋나면 시험이 깨진다** (`tests/test_contracts.py`) — 실제로 여섯 줄이 낡아 있었다.

## 목록

| # | 계약 | 누가 → 누구 | 상태 | 프로토타입 참고 ([대응표](../reference/README.md)) |
| --- | --- | --- | --- | --- |
| [C1](C1-package-manifest.md) | 패키지 매니페스트 (실행 위치 `run_location` 기본 `server`, 부르는 서비스 앱(= C15 토픽), 키 값 없음) | Studio → Center → PC 실행기·서버 실행기 | **구현됨** | Studio·BPM 프로세스 `packages/protocol/…/manifest.py` |
| [C2](C2-signing-envelope.md) | 해시·서명 봉투 | Center(관리자 계정의 승인·배포) → PC 실행기·서버 실행기 | **구현됨** | Studio·BPM 프로세스 `packages/protocol/…/hashing.py`, `signing.py` |
| [C3](C3-run-events.md) | 실행 이벤트 (실행 위치 포함) | PC 실행기(실행 중 BPM 프로세스)·서버 실행기 → Center | **구현됨** | Studio·BPM 프로세스 `packages/protocol/…/events.py` |
| [C4](C4-bot-ui-center.md) | Center API: PC 실행기 (Center API 키 인증·등록·하트비트 — 실행 중 BPM 프로세스 1건과 대기열 보고) | PC 실행기 ↔ Center | **구현됨** | Center `api/bots.py`, `schemas/api.py` |
| [C5](C5-packages-deployments-jobs.md) | Center API: 패키지·배포·작업 (배포 대상 PC 실행기 / 서버 실행기, 서버 배포의 동시 실행 상한, 작업 상태에 「대기열」, 거절 사유 「대기열 가득」) | Studio·콘솔·PC 실행기·서버 실행기 ↔ Center | **구현됨** | Center `api/packages.py`, `deployments.py`, `jobs.py` |
| [C6](C6-approvals.md) | Center API: 결재 | PC 실행기·서버 실행기 ↔ Center ↔ 콘솔 | **구현됨** | Center `api/hitl.py` |
| [C7](C7-resources-center-keys.md) | Center API: 리소스 (확장·서비스 앱·확장 기여 자원·런타임) + Center API 키 관리 | 서비스 앱·PC 실행기·Studio ↔ Center | **구현됨** | 없음 |
| [C11](C11-service-app-common.md) | 서비스 앱 공통 (일꾼 — healthz·manifest·작업 모양·수행 모드·멱등, 관리 콘솔 최소 기능) | 모든 서비스 앱(일꾼) → Center (C15) | **구현됨** | 없음 ([ADR-0010](../decisions/0010-service-apps.md), [ADR-0013](../decisions/0013-api-keys.md)) |
| [C12](C12-server-runner-center.md) | Center API: 서버 실행기 (Center API 키 인증·등록·하트비트, 실행 중·기다리는 실행·대기열 보고, 일시 중지, 메시지, PC 위임 요청·결과) | 서버 실행기 ↔ Center | **구현됨** (M7) | 없음 ([ADR-0015](../decisions/0015-run-location.md)) |
| [C13](C13-extension-manifest.md) | 확장 정의 (`extension.json`: 등급, 서버 부분, 기여 지점, 외부 앱 HTTP 어댑터) | 확장 → Studio·PC 실행기·실행기·서버 실행기·Center | **구현됨** | 없음 ([ADR-0018](../decisions/0018-extensions.md)) |
| [C14](C14-bpmn-extensions.md) | BPMN 확장 속성 (`chk:*` — 태스크 종류별 속성, 반복·파일 출력·이벤트 규칙, 시험 케이스 형식·비교 규칙, 실행 전 검사 B1~B16) | Studio → 패키지 → 실행기·서버 실행기, Center 업로드 검사 | **구현됨** | Studio `agentworks:*` 확장 속성 ([업무 예제](../08-business-examples/README.md)가 이 형식으로 쓰였다) |
| [C15](C15-external-tasks.md) | Center API: 외부 작업 (올리기·기다리기·가져가기(롱폴링)·끝내기, 일꾼 들이기 — 바깥 기능을 부르는 길이 모두 Pull, [ADR-0102](../decisions/0102-calling-outside-is-pull.md)) | 서버 실행기·실행 프로세스·Studio → Center ← 일꾼 | **구현됨** | 없음 |

새 계약 문서는 [template.md](template.md)를 복사해 `C<번호>-<이름>.md`로 만든다.

**M6의 셋째 기준은 이 표에서 `M6 범위의` 계약이 모두 「구현됨」이 되는 것이다** ([05-roadmap](../05-roadmap.md) M6). **C12는 M7이다** — 서버 실행기가 M7의 일이라 그 계약도 거기서 구현된다. 기준을 글자대로 「모두」로 읽으면 M6가 M7 없이는 닫히지 않는다. C12는 M7 첫 조각에서 **합의**가 되었고, 둘째~다섯째 조각에서 등록·하트비트·배포 설치·작업 실행·저장·재개·결재·**메시지**가 양쪽에서 돌아 **「구현됨」이 되었다**. **C15(외부 작업)는 그 뒤에 더한 것이고 「구현됨」이다** — Center·부르는 쪽·일꾼이 다 붙었다 (ADR-0102 조각 2~4). 긴 작업(조각 6)도 들어갔다 — 서버 실행기가 기다림으로 넘긴다 (ADR-0103). 지금 계약은 **열둘**(C1~C7·C11~C15)이고 모두 「구현됨」이다. C8·C9·C10은 UI 자동화 확장과 함께 걷었다 ([ADR-0114](../decisions/0114-remove-ui-automation.md)).
무엇이 남았는지는 [09-gaps](../09-gaps.md) §1에 계약마다 적혀 있다 — 상태를 올릴 때 그쪽도 함께 지운다.

### 코드로 있는 것

확장이 소유한 계약은 모듈이 그 확장의 `contracts/`에 있게 된다 (원칙 1) — 지금은 없다.

| 계약 | 모듈 | 검사 함수 | 문서 예시 시험 |
| --- | --- | --- | --- |
| C1 | `chaeksas.contracts.manifest` | `validate()` — R1·R2·R3·R6·R7 (R5는 Studio, R8은 Center 배포 때) | `tests/test_contract_examples.py` |
| C2 | `chaeksas.contracts.hashing` | `canonical_json()`, `content_hash_dir()`·`content_hash_zip()` | 같음 |
| C2 | `chaeksas.contracts.signing` | `sign()`, `verify()`(V1~V4), `verify_time()`(V5), `verify_target()`(V6), `verify_package()`(V7), `verify_admin_key_addition()`(V8) | 같음 |
| C3 | `chaeksas.contracts.events` | `missing_data_keys()` — 줄 단위 거부용 | 같음 |
| C4 | `chaeksas.contracts.bot_ui` | (모델 검증만) | 같음 |
| C5 | `chaeksas.contracts.center_api` | `validate_deployment()` — **Center `POST /deployments`가 이것을 부른다** (ADR-0047), 상태는 `deployment_refusal()`이 고른다. `validate_job_create()`, `cancel_outcome()` | (문서에 JSON 예시 없음) |
| C6 | `chaeksas.contracts.approvals` | `validate_answer()` — Center와 실행하는 쪽이 **같이 쓴다**. `validate_create()`, `request_id_for()`, `apply_defaults()` | `tests/test_contract_examples.py` |
| C7 | `chaeksas.contracts.resources` | `missing()` — C1 `requires` ↔ 리소스 목록 대조. `blocking_at_deploy()`가 배포를 막을 것만 고른다 | (문서에 JSON 예시 없음) |
| C7 | `chaeksas.contracts.center_keys` | `key_state()`, `expires_soon()`, `prefix_of()`, `validate_create()` | 같음 |
| C11 | `chaeksas.contracts.service_app` | `resolve_mode()`(폴백 규칙), `idempotency_key()` | (문서 예시는 HTTP라 모델 시험은 `tests/test_service_kit.py`) |
| C12 | `chaeksas.contracts.server_runner` | `validate_heartbeat()`(자리 셈·`waiting[]` 짝 칸 — 보내는 쪽과 받는 쪽이 **같이 쓴다**), `free_slots()`·`pick_jobs()`(작업 나누기), `restorable()`(되살리기 판정, ADR-0054), `message_matches()`·`pick_message_target()`(받는 곳 고르기 — **엔진의 규칙 그대로**이고 `tests/test_core_events.py`가 둘을 대조한다) | `tests/test_contracts_server_runner.py`·`tests/test_contract_examples.py` |
| C12 | **`chaeksas.core.run_snapshot`** | 기다리는 실행을 담고 되살린다 (ADR-0054 §1~§2) — `Run`의 칸을 **셋으로 가르고**(담는다/다시 꽂는다/버린다) `audit_fields()`가 **칸이 늘면 묻는다** | `tests/test_core_run_snapshot.py` |
| C12 | **`chaeksas.center.api.server_runner`** + **`chaeksas.server_runner`** | 받는 쪽(등록·하트비트·운영 API 셋·작업 나누기·**메시지** `api.messages`)과 보내는 쪽(`agent.tick()` — 배포 설치·준비 상태·작업 실행·저장·재개·결재·**메시지**까지. 실행 하나는 `worker.Worker` 스레드 하나이고, 기다리는 실행은 `store.Store`(SQLite)에 담긴다). 키 묶기는 C4와 **한 코드**(`center.host_keys`), `machine_id`·설치·배포 적용·`RunEnv` 짓기·**담고 되살리기**도 하나(`core.machine`·`core.packages`·`core.deploy`·`core.run_env`·`core.run_snapshot`). 현황 목록은 **콘솔 토큰만**(`auth.require_console` — CON-03도 같이 좁혔다) | `tests/test_center_server_runner.py`·`tests/test_server_runner_agent.py`·`tests/test_server_runner_deploy.py`·`tests/test_center_messages.py`·`tests/test_server_runner_messages.py` |
| C11 | **`chaeksas.service_kit`** | 계약을 지키는 일꾼 — 작업 함수를 받아 `create_app`(`/healthz`·관리 API)과 `service_kit.consumer`(`Consumer` 가져가기 루프·`Enrollment` 들이기·`TokenFile`)를 준다. 멱등, 수행 모드·폴백, 오류 형식, 사용 기록 | `tests/test_service_kit.py`·`tests/test_service_kit_consumer.py` |
| C13 | `chaeksas.contracts.extension` | `validate()` — E1·E2·E3 + 모양. `task_type_conflicts()`(E4), `check_api()`(E5), `verify_external()`(E6), `check_size()`, `definition_hash()` | `tests/test_contract_examples.py` |
| C13 | **`chaeksas.core.extensions`** | 확장 호스트 — 엔트리 포인트로 찾기, 검사 규칙 적용, 기여 지점별 목록, `entry` 해석(그 확장 패키지 안으로 제한). 인터페이스는 `chaeksas.extension_api` | `tests/test_extension_host.py` |
| C14 | `chaeksas.contracts.bpmn_ext` | `read_process()`(BPMN 읽기, 표준 라이브러리만), `validate()` — B1~B16(오류·경고), `matches()` — 기대 결과 비교, `available_vars()` — 변수 흐름 | `tests/test_contracts_bpmn_ext.py` (업무 예제 48개를 읽고 검사한다) |
| C15 | `chaeksas.contracts.external_task` + Center `api/external_tasks.py` | `task_id_for()`(멱등 칸 → 같은 일감 id), `body_hash()`(같은 칸·다른 본문 → 409), `missing_outputs()`(출력 검사). 부르는 쪽 `core.services.CenterServiceCaller`, 일꾼 `service_kit.consumer`·`apps/adapter_consumer` | `tests/test_center_external_tasks.py`·`tests/test_c15_round_trip.py`·`tests/test_adapter_consumer.py` |

V5~V8은 **역할에 따라 누가 검사하는지가 다르므로** 함수를 나눠 뒀다. Center는 `verify_time(..., check_not_before=False)`로 예약 배포를 받아 두고, 실행하는 쪽만 `not_before`를 본다.

검사 함수 이름이 계약마다 겹칠 수 있다 (`validate_create`가 C6·C7 둘에 있다). 모듈 안의 이름은 계약 문서 그대로 두고, `chaeksas.contracts`에서 다시 내보낼 때만 계약을 붙인다 (`validate_approval_create`·`validate_center_key_create`).

검사 함수는 **저장소를 보지 않는다.** 상태가 필요한 검사(대상이 존재하는지, 같은 봉투가 이미 있는지, 활성 배포가 몇 개인지)는 Center가 자기 저장소에서 읽어 인자로 넘긴다 — 없으면 그 검사를 건너뛰고, 무엇을 건너뛰는지 docstring에 적혀 있다.

문서의 JSON 예시는 **테스트가 문서에서 뽑아** 모델로 검증한다. 예시를 고치면 테스트가 깨지므로 문서와 코드가 어긋날 수 없다 (프로토타입에서 `X-Bot-Id` 헤더·`{"events": […]}` 본문이 코드와 달랐던 일).

## 프로토타입에서 이미 알려진 결함 (새 계약에서 막을 것)

- Center는 BPM 프로세스별 인증이 없어 공용 토큰으로 아무 `bot_id`나 쓸 수 있었다 → C4에서 PC 실행기별 Center API 키.
- 문서(`X-Bot-Id` 헤더, `{"events": [...]}` 본문)와 코드(`?bot_id=`, 배열 본문)가 달랐다 → 명세에서 예시 요청을 테스트로 돌린다.
- 계약 패키지 버전(1.2.0)과 사용 태그(v1.3/v1.4)가 어긋났다 → 버전은 `schema` 정수와 패키지 버전 두 가지만, 태그 없이 워크스페이스 의존.
- BPM 프로세스 상태 값이 닫힌 목록이라, 모르는 상태 하나로 하트비트 전체가 422 거부되었다 → C4의 상태 필드는 열린 문자열 + 알려진 값 목록.

# C10. Worker 로컬 API

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-05) — 셀렉터 등록용 엔드포인트(§5)의 요청·응답까지 확정 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | 실행 중 Bot(Bot UI의 실행기)·Studio·Bot UI(셀렉터 등록, Worker 관리) → Worker 프로세스 |
| 코드 위치 | `extensions/ui_automation/contracts/` (worker_local.py) — UI 자동화 확장이 소유 ([ADR-0018](../decisions/0018-extensions.md)) |
| 관련 ADR | [0008](../decisions/0008-map-driver-hands-boundary.md), [0012](../decisions/0012-bot-ui.md), [0013](../decisions/0013-api-keys.md), [0014](../decisions/0014-one-bot-per-pc.md), [0033](../decisions/0033-desktop-app-and-window.md)(데스크톱 창) |
| 관련 화면 | STU-08·13, BUI-06~09 |

## 목적

같은 PC의 Worker 프로세스에 UI 자동화를 맡기는 경계다. **부르는 쪽은 시맨틱 키로만 말한다.** 셀렉터(물리 로케이터)는 이 경계를 넘지 않는다. 로케이터 사다리와 치유는 Worker와 UI 자동화 앱 사이(C8)의 일이다. 예외는 셀렉터 등록용 엔드포인트(§5)뿐이다.

## 전송

- **방식:** HTTP, `127.0.0.1` 고정. 기본 포트는 8899이고 `CHK_WORKER__LOCAL_API__PORT`로 바꾼다. 주소는 바꿀 수 없다.
- **토큰은 두 가지이고, 둘 다 파일로만 넘긴다.** 명령줄 인자로 넘기면 프로세스 목록에서 보이기 때문이다. 두 파일 모두 사용자 데이터 폴더에 현재 사용자만 읽을 수 있게 둔다. Worker를 다시 띄우면 둘 다 바뀐다.

  | 토큰 | 파일 | 누가 읽나 | 쓰는 곳 |
  | --- | --- | --- | --- |
  | 사용 토큰 | `worker.token` | 실행기, Studio, Bot UI | 헤더 `X-CHK-Local-Token`. 세션·상태 API |
  | 관리 토큰 | `worker.admin.token` | **Bot UI만** (Studio·실행기는 읽지 않는다) | 헤더 `X-CHK-Local-Admin`. `/v1/admin/*` |

- **세션 비밀:** 세션을 열면 응답에 `session_secret`이 온다. 그 세션의 스텝·이동·닫기 요청은 헤더 `X-CHK-Session`에 이 값을 실어야 한다. 다른 호출자가 남의 세션을 조작하거나 닫지 못하게 하려는 것이다.
- **기동:**
  1. Bot UI가 두 토큰 파일을 쓴다.
  2. Worker를 띄운다. **Bot UI가 자기 실행 파일을 자식으로 다시 띄우고**(`--local-runtime ui-automation:worker --port <p> --token-dir <폴더>`), 그 자식이 확장의 진입점을 부른다 (C13 `bot_ui.local_runtimes[].entry`, [ADR-0024](../decisions/0024-desktop-packaging-extensions.md)). 개발 환경에서는 같은 인자로 `python -m chaeksas.bot_ui`다 — 설치 파일로 묶은 앱 안에는 `chk-worker` 같은 콘솔 스크립트가 없다.
  3. `GET /v1/health`가 200이 될 때까지 기다린다 (최대 30초).
  4. Worker가 죽으면 다시 띄운다 (최대 3회 연속, BUI-09).
- **UI 세션은 한 번에 하나다** (ADR-0014 §4). 열려 있는 세션이 있으면, 다른 쪽이 세션을 열 때 409 `worker_busy`를 받는다.
- **실행 예약:** Bot UI는 Bot 실행을 시작할 때 Worker를 그 실행에 예약하고(§4), 실행이 끝나면 푼다. 예약된 동안에는 그 `run_id`의 세션만 열 수 있다. 그래서 한 Bot의 UI 태스크 사이 빈틈에 Studio나 셀렉터 등록이 Worker를 가져가지 못한다.
- **유휴 시간 제한:** 세션에 10분 동안 요청이 없으면 Worker가 닫는다 (`CHK_WORKER__SESSION_IDLE_S`). 부르는 쪽이 죽어서 세션이 계속 남는 것을 막는다.
- **멱등성:**
  - 세션 열기는 같은 `business_key`로 다시 오면 열려 있는 그 세션을 돌려준다 (200, `session_secret`도 같다).
  - 스텝은 멱등이 아니다 (화면 조작이다). 스텝 응답을 못 받았으면 재시도하지 말고 `GET /v1/sessions/{id}`로 상태를 읽어 판단한다.
- **시간 제한:** 스텝 하나에 기본 60초. `timeout_s`로 바꾼다.

## 모델

### 1. 상태

`GET /v1/health` (토큰 없이도 됨) → `{status: "ok", version, session: "idle" | "bot" | "studio" | "selector_registration"}`

`GET /v1/status` (사용 토큰) → 위 내용에 다음을 더한다. BUI-09가 읽는다.

| 필드 | 뜻 |
| --- | --- |
| `pid`, `uptime_s` | |
| `reserved_for`? | 예약된 `run_id` |
| `holder`? | 지금 세션을 쥔 쪽: `{type, run_id?, bpm_process_id?}` |
| `recent_sessions[]` | 최근 20개 요약 |
| `unsent_reports` | UI 자동화 앱에 아직 못 보낸 보고 수 |

### 2. UI 세션 (Bot·Studio)

**`POST /v1/sessions` — 세션 열기**

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `caller` | object | ✓ | `{type, run_id, node_id, node_instance, attempt, bpm_process_id, version}`. `type`은 열린 문자열이고 알려진 값은 `bot`, `studio`, `selector_registration`. `selector_registration`이면 `run_id` 등 실행 필드는 비운다 (§5) |
| `mode` | `autonomous` \| `deterministic` | ✓ | 수행 모드. Worker는 바꾸지 않고 UI 자동화 앱에 그대로 전달한다 |
| `business_key` | str | ✓ | `<run_id>:<node_id>:<node_instance>:<attempt>`. 셀렉터 등록이면 `reg_<hex8>`. 계획·보고·실행 기록을 잇는 키다 (C3 `ui_session`, C8, C11 멱등 키와 같은 구성) |
| `page_id` | str | Bot·Studio만 ✓ | 시작 화면 |
| `start_url` | str | | 비우면 화면의 기본 주소, 또는 이미 열린 화면에서 이어서 |
| `browser_profile` | str | | |
| `app` | str | | 데스크톱 앱 이름 (UI 태스크의 `desktop.app`, C14). 비우면 계획에 실린 화면의 `app`을 쓴다 (C8·C9) |
| `goal` | str | | 자율 수행에서만: 스텝 대신 목표 한 줄. Worker가 계획을 받을 때 싣는다 (C8 「목표로 계획」, **캐시하지 않는다**). 세운 스텝은 `planned_steps`로 돌려준다 ([ADR-0035](../decisions/0035-ui-goal-planning.md)). 결정 수행 세션이면 422 `instruction_not_allowed` |
| `values`, `results` | str[] | | `goal`과 함께: 쓸 값의 **이름**·결과 변수 이름 (C8). 값은 싣지 않는다 |
| `headed` | bool | | 기본 false. Studio 시험은 true 권장 |
| `heal` | bool | | 자가 치유 사용. 기본 true |
| `report` | bool | | 닫을 때 UI 자동화 앱에 보고할까 (C8). 기본 true. **셀렉터 시험(BUI-08)에서 끈다** — 통계에 넣지 않을 뿐 아니라 아예 보내지 않는다 |
| `service_key` | str | Bot·Studio만 ✓ | **UI 자동화 앱 API 키 값.** 부르는 쪽이 BPM 프로세스의 키 참조를 풀어 넣는다 (ADR-0013). Worker는 이 값을 세션 동안 메모리에만 두고, 디스크·로그에 남기지 않는다 |

→ 201 SessionInfo `{session_id, session_secret, page_id, current_url, plan_source: "server" | "cache", steps_run: 0, mutating_steps_ok: 0, planned_steps}`

- `planned_steps`: `goal`로 열었을 때만 — 모델이 세우고 앱이 거른 스텝 `[{semantic_key, action, value?, result?}]`. 값은 `{이름}` 템플릿일 수 있고 **부르는 쪽이 채워** 스텝을 하나씩 보낸다 (손으로 적은 스텝과 같은 길). 계획이 거르기에 걸리면 세션을 열지 않고 422 `goal_plan_invalid`(C8)를 그대로 돌려준다.

**여는 순서** ([ADR-0033](../decisions/0033-desktop-app-and-window.md)): `page_id`가 있고 계획을 받을 수 있으면 **계획을 먼저** 받고, 계획의 `platform`으로 브라우저·데스크톱을 고른 뒤 연다. 계획이 없으면(셀렉터 등록 등) 브라우저다.

**데스크톱 세션:**

- 계획의 `window`(C9 창 조건)에 맞는 최상위 창이 **하나** 있으면 그 창에 붙는다. 여럿이면 `window_ambiguous`다 — 고르지 않는다.
- 없으면 앱 이름(`app`, 없으면 계획의 `app`)으로 **그 PC의 실행 명령**을 찾아 띄우고 창이 생길 때까지 기다린다 (기본 30초). 실행 명령은 Worker 데이터 폴더(`--token-dir`)의 `desktop-apps.json`이다: `{"ERP Client": {"command": ["C:\\ERP\\erp.exe"], "start_timeout_s": 30}}`. 경로는 PC마다 다르므로 BPM 프로세스·레지스트리에 두지 않는다.
- 그래도 창이 없으면 `app_not_running`이다.
- 찾기·조작은 그 창 **안에서만** 한다. `current_url`은 `desktop:<앱 이름>`이다 — 창 제목에는 문서 이름 같은 업무 값이 들어 있을 수 있어 싣지 않는다.
- 데스크톱 화면의 분석·직접 고르기·표시(§5)는 아직 없다 (503).

**`POST /v1/sessions/{id}/steps` — 스텝 하나** (헤더 `X-CHK-Session`)

| 필드 | 뜻 |
| --- | --- |
| `semantic_key` | 결정 수행: 등록된 요소의 시맨틱 키 |
| `instruction` | 자율 수행에서만: 자연어 지시. UI 자동화 앱이 시맨틱 키로 풀어 준다. 결정 수행 세션에서 보내면 422 `instruction_not_allowed` |
| `action` | 조작: `fill`, `click`, `press`, `select`. 읽기: `read`, `read_table`, `read_options`, `read_selection` |
| `value` | 조작에 필요한 값. 읽기 동작에 주면 422 |
| `timeout_s` | 선택 |

`semantic_key`와 `instruction`은 둘 중 하나만 준다.

→ 200 StepResult

| 필드 | 뜻 |
| --- | --- |
| `ok` | 성공 여부 |
| `semantic_key`, `action` | 실제로 수행한 것 |
| `text` | 읽기 결과 (사람이 읽는 형태, 표는 TSV) |
| `data` | 읽기 결과 구조 (`headers`, `rows`, `options`, `selected`). **UI 자동화 앱으로 보내지 않는다** |
| `fallback_depth` | 몇 번째 로케이터로 성공했나. 0이 건강한 상태 |
| `healed` | 치유로 성공했나 |
| `escalated` | **전환.** 자가 치유 한도를 넘어 사람 확인이 필요하다. 오류와 구분한다. PC Bot은 확인(CMN-01)으로 넘긴다 |
| `error_code`, `error` | 실패 시 (예: `element_not_found`, `page_mismatch`, `timeout`) |
| `current_url`, `duration_ms` | |

**그 밖의 세션 엔드포인트:**

- `GET /v1/sessions/{id}` (사용 토큰 + `X-CHK-Session`) → SessionInfo. 여기에 `last_step`과 `mutating_steps_ok`(성공한 조작 스텝 수)가 들어간다.
- `POST /v1/sessions/{id}/goto` `{url}` → SessionInfo
- `DELETE /v1/sessions/{id}` → CloseResult `{steps_run, summary: {result: "success" | "escalated" | "failed", steps, fallback_depth_max, healed, escalated}, report: "sent" | "queued"}`

부르는 쪽은 `summary`로 C3 `ui_session` 이벤트를 만든다.

### 3. Worker가 다시 떴을 때 UI 태스크를 어떻게 하나

세션이 사라지면(404 `session_not_found`) 부르는 쪽은 마지막으로 받은 응답 기준으로 판단한다.

| 상황 | 처리 |
| --- | --- |
| **성공한 조작 스텝이 하나도 없었다** (읽기만 했거나 처음이었다) | `attempt`를 +1 하고 새 세션으로 그 UI 태스크를 처음부터 한 번 다시 한다 |
| 조작 스텝이 하나라도 성공했다 | 다시 하면 같은 입력이 두 번 들어갈 수 있다. **자동으로 다시 하지 않고 확인(`confirmation`)으로 넘긴다**: 「화면 조작 도중 Worker가 다시 시작되었습니다. 화면 상태를 확인한 뒤 계속/중단을 고르세요」 |

### 4. Worker 관리 (Bot UI만, 관리 토큰)

| 경로 | 뜻 |
| --- | --- |
| `POST /v1/admin/reserve` `{run_id}` | 실행 예약. 이미 다른 세션이 열려 있으면 409 `worker_busy`. 이때 Bot UI는 그 세션을 강제로 닫을지 정한다 (셀렉터 등록 중이면 Bot이 기다린다, ADR-0014 §4) |
| `DELETE /v1/admin/reserve` | 예약 풀기 (실행이 끝났을 때. 열린 세션도 닫는다) |
| `DELETE /v1/admin/sessions/{id}` | 세션 강제 닫기 (실행기가 죽었을 때 정리) |
| `POST /v1/admin/shutdown` | 열린 세션을 닫고 보고를 저장한 뒤 종료 (Bot UI 종료 순서, BUI-01) |

### 5. 셀렉터 등록 (Bot UI의 유틸리티)

`caller.type = "selector_registration"`으로 연 세션에서만 쓸 수 있다 — 아니면 403 `session_locked`. **레지스트리 등록·삭제는 Worker가 하지 않는다.** UI 자동화 확장의 Bot UI 유틸리티가 UI 자동화 앱을 직접 부른다 (C9). 등록 화면에 필요하므로 **CSS 후보 같은 물리 정보가 응답에 포함된다** (예외).

| 경로 | 뜻 (BUI-06) |
| --- | --- |
| `POST /v1/registration/browser` | 브라우저 열기 `{start_url, headed}` → `SessionInfo` (§2와 같은 모양) |
| `POST /v1/registration/{session_id}/analyze` | 화면 분석 `{scope_css?, max, include_read}` → 요소 후보 목록 |
| `POST /v1/registration/{session_id}/pick` / `DELETE …/pick` | 직접 고르기 시작·끝. 고른 요소는 `GET …/pick/events`로 받는다 |
| `GET /v1/registration/{session_id}/pick/events` | **고른 것을 비워 가져온다** (한 번 준 것은 다시 주지 않는다) |
| `POST /v1/registration/{session_id}/highlight` | `{locators: [로케이터…]}` → 그 요소를 화면에 표시 (BUI-06 5번) |
| `POST /v1/registration/{session_id}/verify` | `{ladders: {시맨틱 키: [로케이터…]}}` → 칸별 통과·실패 |

**`business_key`는 Worker가 짓는다** (`reg_<hex8>`) — 등록 화면이 실행 키를 흉내 낼 일이 없다. 등록 세션은 `page_id`가 없어 계획(C8)을 받아 오지 않는다.

`analyze` 응답:

| 칸 | 타입 | 뜻 |
| --- | --- | --- |
| `candidates` | array | 후보 하나마다 `{tag, role, name, element_id, field_name, test_id, css[], kind, actions[], suggested_key}`. `name`은 접근성 이름, `field_name`은 HTML `name` 속성 |
| `total` | int | 범위 안에서 찾은 전체 수 (자르기 전) |
| `truncated` | bool | `max`에 걸려 잘렸다. **잘렸으면 잘렸다고 말한다** — 조용히 자르면 없는 것을 없다고 단정한다 |
| `scope_empty` | bool | `scope_css`가 아무것도 못 찾았다. **전체로 몰래 넓히지 않는다** — 범위를 잘못 적은 것을 알아야 한다 |

`suggested_key`는 `test_id` → `id` → `name` → **영문** 접근성 이름 → 역할 순으로 짓는다. **한글 이름은 음역하지 않는다** — `고객명`을 `gogaegmyeong`으로 바꾸면 사람도 기계도 못 읽는다. 어차피 사람이 고치는 자리다 (BUI-06 4번).

`pick/events` 응답: `{candidates: [Candidate…], picking: bool}`. `picking`이 `false`면 사람이 화면에서 끝낸 것이다(Esc) — 화면도 토글을 내린다. **고르는 동안 링크 이동과 폼 제출은 막는다** (누르면 다른 화면으로 가 버린다).

`highlight` 응답: `{found: int}`. **하나가 아니면 그렇게 말한다** — 0이면 「찾지 못했습니다」, 여럿이면 「N개가 잡힙니다 — 모호해서 실패합니다」.

`verify` 응답은 사다리 한 칸에 한 줄(`{semantic_key, rank, strategy, selector, passed, matched, reason}`)이다. **하나에 맞아야 통과**다 — 여럿이 잡히면 실행에서 엉뚱한 것을 누른다. 검증 결과는 **등록을 막지 않는다**: 사람이 보고 정한다.

> 상태: `analyze`·`pick`·`highlight`는 **브라우저 백엔드에서만** 된다 — 데스크톱(UIA) 세션이면 503 `browser_unavailable`이다 (데스크톱 화면 등록은 사다리를 적어 넣는다, ADR-0033).

## 오류

공통 본문: `{code, message, detail}`.

| 상태 코드 | `code` | 언제 | 부르는 쪽이 할 일 |
| --- | --- | --- | --- |
| 401 | `token_invalid` / `session_secret_invalid` | Worker가 다시 떠서 토큰이 바뀜, 남의 세션 | 토큰 파일을 다시 읽고 한 번 재시도. 세션 비밀이 틀렸으면 버그 |
| 403 | `admin_only` | 사용 토큰으로 `/v1/admin/*` 호출 | 버그 |
| 404 | `session_not_found` | 세션이 닫힘 (유휴 시간 초과, Worker 재시작) | §3 |
| 409 | `worker_busy` (`detail.holder`) / `reserved` (`detail.run_id`) | 다른 쪽이 세션을 쥐었거나 Worker가 다른 실행에 예약됨 | Studio: STU-08 「Worker 사용 중」. 셀렉터 등록: BUI-06 「Bot 실행 중」 |
| 422 | `instruction_not_allowed` / `value_required` / `value_not_allowed` / `unknown_semantic_key` | 요청 모양이 틀림 | 재시도하지 않음 |
| 502 | `ui_automation_unreachable` | UI 자동화 앱에 닿지 못하고 캐시도 없음 | 태스크 재시도 정책을 따른다 |
| 409 | `app_not_running` (`detail.app`) | 데스크톱 화면의 창이 없고 띄우는 방법도 설정돼 있지 않음 (`desktop-apps.json`에 그 이름이 없거나 띄워도 창이 안 생김) | 재시도하지 않는다. 확인(CMN-01) — 「<앱>을 띄운 뒤 계속」 |
| 409 | `window_ambiguous` (`detail.count`) | 창 조건에 맞는 창이 여럿 | 재시도하지 않는다. 창 조건(C9 `window`)을 좁힌다 |
| 503 | `browser_unavailable` | 브라우저를 띄우지 못함 (데스크톱이면 UIA를 쓸 수 없는 PC) | Bot UI에 알리고 확인으로 넘긴다 |
| 503 | `session_locked` | **화면이 잠겨 있다.** 잠긴 동안 Worker는 화면 조작·캡처를 하지 않는다 | **재시도 가능.** 풀리거나 스텝 시간 제한에 닿을 때까지 기다린다 (아래) |

### `session_locked` (잠금 화면)

Worker는 WTS 세션 알림으로 잠금을 안다 ([ADR-0023](../decisions/0023-bot-ui-process-supervision.md)). **UIA 결과로는 알 수 없다** — 잠긴 동안에도 UIA는 요소와 위치를 정상으로 돌려주므로, 그대로 두면 보이지 않는 화면에 입력하고 빈 화면을 캡처한다.

- 잠긴 동안 들어온 **조작·캡처 스텝**은 수행하지 않고 이 오류로 돌려준다. 읽기만 하는 요청(`/v1/health`, 세션 상태)은 그대로 답한다.
- 부르는 쪽(실행기·Studio)은 **그 스텝의 시간 제한 안에서 기다렸다 다시 부른다.** 시간 제한에 닿으면 UI 태스크를 확인(CMN-01)으로 넘긴다 — 사람이 PC 앞에 없다는 뜻이기 때문이다.
- `detail.locked_since`(Timestamp)를 실으면 부르는 쪽이 얼마나 잠겨 있었는지 사람에게 보일 수 있다.
- 실행 기록에는 **잠김으로 기다린 사실만** 남긴다 (C3). 화면 내용은 남기지 않는다.

## 호환 규칙

- 모르는 요청 필드는 무시한다. 상태·코드 값은 열린 문자열이다.
- Worker와 부르는 쪽은 같은 PC에 같은 버전으로 설치하는 것이 원칙이다. 그래도 `schema`가 다르면 Worker가 422 `schema_unsupported`를 돌려준다 (Studio만 따로 업데이트한 경우).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-05 | 1 | 세션 열기에 `goal`·`values`·`results`, 세션 정보에 `planned_steps` — 목표로 계획([C8](C8-ui-automation-plan-heal-report.md))의 스텝을 부르는 쪽이 채워 보낸다. 더하기만이라 schema는 그대로 1 | 0035 |
| 2026-10-01 | 1 | 초안 | 0012, 0013, 0014 |
| 2026-10-01 | 1 | 검토 반영: 토큰은 파일로만 넘기고 사용·관리 토큰으로 나눔, `session_secret`, 실행 예약과 유휴 시간 제한·강제 닫기, `caller.attempt`와 4단 `business_key`, 셀렉터 등록 caller, 재시작 시 조작 스텝이 있었으면 자동으로 다시 하지 않음 | — |
| 2026-10-01 | 1 | 확장 검토 반영: `registration/submit` 없앰 (레지스트리는 확장 유틸리티가 직접), 등록 세션은 `service_key` 불필요 | 0018 |
| 2026-10-03 | 1 | 잠금 화면 오류 `session_locked`(503, 재시도 가능) 추가. 잠긴 동안 조작·캡처를 하지 않고, 부르는 쪽은 스텝 시간 제한 안에서 기다린다 | 0023 |
| 2026-10-05 | 1 | `SessionRequest.report`를 더했다 — 셀렉터 시험이 보고를 끌 수 있게 (BUI-08 「결과를 서버에 보고」) | — |
| 2026-10-05 | 1 | §5에 `pick/events`(비워 가져오기·`picking`)와 `highlight`를 적었다 | — |
| 2026-10-05 | 1 | §5 셀렉터 등록의 요청·응답을 확정했다 — `analyze`·`verify`는 세션 경로 아래(`/v1/registration/{session_id}/…`)로 두어 나머지 세션 경로와 모양을 맞췄고, `business_key`는 Worker가 짓는다. 등록 세션이 아니면 403 | 0018 |
| 2026-10-03 | 1 | 기동 절차의 2단계를 고쳤다 — `chk-worker` 명령이 아니라 Bot UI가 자기 실행 파일을 `--local-runtime`으로 다시 띄운다 (묶인 앱에는 콘솔 스크립트가 없다). 주고받는 API는 그대로라 schema는 1 | 0024 |
| 2026-10-05 | 1 | 데스크톱 세션: `SessionRequest.app`, 계획을 먼저 받아 백엔드를 고르는 여는 순서, 창에 붙거나 `desktop-apps.json`으로 띄우기, 오류 `app_not_running`·`window_ambiguous`(409), `current_url = desktop:<앱>` | 0033 |

# 09. 공백 목록 (M6 셋째 기준)

M6의 셋째 완료 기준 — 「모든 계약 문서 상태가 「구현됨」, 모든 화면이 `06-screens`와 일치」
([05-roadmap](05-roadmap.md) M6) — 을 닫으려면 **무엇이 남았는가**를 적은 목록이다.

**이 문서는 만들 것을 고르는 근거다. 순서를 정하지 않는다** — 어느 것을 만들지는 사람이 고른다.
항목이 닫히면 그 줄을 지운다.

## 어떻게 찾았나

`docs/03-contracts/`·`docs/06-screens/`를 코드와 대조했다. 가장 많이 걸린 것은
**「규약·모델·칸은 있는데 부르는 쪽이 `tests/`뿐이거나 없는」** 꼴이다 — M5 끝 무렵 이 꼴을
네 번(사전 점검 러너, C4 `readiness`, BUI-10, BUI-04 「출처」) 우연히 만났고, 그래서 이번에는
`git grep`으로 호출자를 세어 전부 찾았다.

**「문서에 돈다고 적혀 있다」와 「부르는 쪽이 있다」는 다르다.**

## 1. 계약 문서 상태

| 계약 | 문서 머리말 | 코드 | 「구현됨」까지 남은 것 |
| --- | --- | --- | --- |
| C1 | 합의 | `contracts.manifest` R1~R8 (R8은 Center 배포가 짓는다) | `Provides`를 **아무도 채우지 않는다** (§3-1) |
| C2 | 합의 | `contracts.hashing`·`signing` V1~V8 | 없다 — 상태만 올리면 된다 |
| C3 | 합의 | `contracts.events`·`core.run_log` | `ui_session`을 **아무도 내보내지 않는다** (§3-2). `case_id`·`queued_s`도 (§3-3) |
| C4 | 합의 | `contracts.bot_ui`, Center·Bot UI 양쪽 | `WorkerState.reserved_for`를 **아무도 채우지 않는다** (§3-4) |
| C5 | 합의 | `contracts.center_api`, Center 전부 | `deprecated`로 **만들 길이 없다** (§3-5). `dependents`·`DELETE /packages` 없음 (§3-6). 오류 코드 이름·상태 코드가 코드와 다르다 (§2-1) |
| C6 | 구현됨 | `contracts.approvals`, Center·현장 | 없다 |
| C7 | 구현됨 | `contracts.resources`·`center_keys` | 외부 확장 앱의 `health`를 **보지 않는다** (§3-7) |
| C8 | 합의 | **`ext.ui_automation.contracts.plan`** | 없다 — 상태만 올리면 된다 (§2-2) |
| C9 | 구현됨 | **`ext.ui_automation.contracts.registry`** | 문서가 저장소를 **Neo4j**라고 한다, 코드는 SQLite (§2-3). 오류 코드 이름 하나 (§2-1) |
| C10 | 합의 | **`ext.ui_automation.contracts.worker_local`** | `POST /v1/admin/shutdown` 없음 (§3-8) |
| C11 | 합의 | `contracts.service_app`·`service_kit` | 없다 — 상태만 올리면 된다 |
| C12 | 초안 (M7) | **없다** (`apps/server_runner`는 docstring뿐) | M7 전부. **M6 기준의 「모든 계약」에서 빼야 하는가는 사람이 정한다** (§2-4) |
| C13 | 합의 (모델·검사 구현됨) | `contracts.extension`·`core.extensions` | `console.pages`를 **아무도 그리지 않는다** (§4-7). `studio.resource_views`도 (§4-4) |
| C14 | 초안 (B1~**B14** 구현됨) | `contracts.bpmn_ext` B1~**B15** | **머리말이 낡았다** — B15도 돈다 (§2-5) |

굵게 적은 셋(C8·C9·C10)은 **확장이 소유한 계약**이라 `extensions/ui_automation/…/contracts/`에
있다 (계약 README 원칙 1). CLAUDE.md §7이 「계약 코드 C8~C10·C12가 없다」고 적어 두었는데
**C8~C10은 있다** — 없는 것은 C12 하나다. (이 줄은 이 작업에서 고쳤다.)

## 2. 문서가 코드와 어긋난 자리 (코드를 고치는 일이 아니다)

### 2-1. 오류 코드 이름이 코드와 다르다

| 문서 | 문서가 적은 것 | 코드가 쓰는 것 |
| --- | --- | --- |
| C5 §오류 400 | `bad_zip` / `no_manifest` | `not_a_zip` / `manifest_missing` |
| C5 §오류 409 | `version_exists` | `version_conflict` |
| C9 §오류 403 | `scope_required` | `scope_missing` (C11 §오류와도 어긋난다) |

C5의 zip 형식 오류는 코드가 **422**로 돌려준다 (문서는 400이라고 적었다) — 본문은 읽혔고 내용이
계약과 맞지 않는 쪽이라 422가 맞다. 400으로 남는 것은 `bad_envelope` 하나다.

> **f-문자열로 만드는 코드는 `grep`에 안 걸린다.** C1 R8의 `operation_not_server_ok`·
> `operation_not_deterministic`은 **문서가 맞다** — `deployments.py:137`이 `f"{type}_{reason}"`으로
> 짓는다. `auth.py:80`의 `f"key_{state}"`도 같은 꼴이다. 호출자를 셀 때 이 둘을 기억할 것.

- **크기:** 아주 작다 (문서 네 줄).
- **막는 것:** 없다.
- 선례가 있다 — C4 변경 이력 2026-10-08이 같은 일을 했다 (`key_bound_elsewhere` → `machine_mismatch`,
  「409 코드 이름도 코드에 맞췄다」). 오류 코드는 **받는 쪽이 글자로 보는 값**이라 코드가 원본에
  가깝고, 문서를 맞추는 쪽이 맞다.

### 2-2. C8에는 `> 상태:` 줄이 없다

사다리·치유·보고·목표로 계획이 모두 도는데(ADR-0035) 문서는 「합의」에서 멈춰 있다.
**크기:** 아주 작다. **막는 것:** 없다.

### 2-3. C9·01-architecture가 저장소를 Neo4j라고 한다

코드는 **SQLite 한 파일**이다 (`service/store.py` — 「표준 라이브러리 `sqlite3`만」).
C9의 `> 상태:` 줄은 이미 SQLite라고 적는데, 같은 문서 §오류(`registry_unavailable` 「그래프
저장소(Neo4j)가 내려감」)와 §호환 규칙(「그래프 저장소(Neo4j)와 YAML 폴백」)은 그대로다.
`01-architecture.md` 11줄(구성도)·119줄(저장소 표)과 `06-screens/service-app-console.md`
33·72·85줄(UIA-01 「저장소 표시」, UIA-02 「통계 열은 그래프 저장소에서만」)도 그대로다.

- **크기:** 문서는 작다. **ADR은 따로다.**
- **ADR 거리다.** 「지식 그래프 → SQLite」는 **결정을 뒤집은 것**인데 ADR이 없다 (CLAUDE.md §3).
  통계·승격·화면 간 경로 탐색을 그래프 없이 어떻게 할 것인지가 ADR이 답할 거리다 — UIA-01·02가
  그래프를 전제로 쓰여 있다(§4-7). **문서만 고치고 ADR을 미루면 UIA 화면을 만들 때 또 막힌다.**

### 2-4. C12는 M7이다 — M6 기준에서 뺄 것인가

C12만 코드가 전혀 없고(`apps/server_runner`는 docstring뿐), 문서도 「초안 (M7에서 구현)」이라고
스스로 적는다. M6 기준의 「모든 계약 문서 상태가 「구현됨」」을 글자대로 읽으면 C12 때문에 M6가
닫히지 않는다. **사람이 정할 거리다** — 기준 문구를 「M6 범위의 계약」으로 좁히는 쪽이 자연스럽다.

### 2-5. C14 머리말이 B14에서 멈춰 있다

B15(도우미 호출 인자 모양)가 `core.expr.check_calls`로 돌고 Studio 실행 전 검사가 보인다.
문서 §검사 규칙 표에는 B15가 있는데 **머리말만 낡았다.** (이 작업에서 고쳤다.)

### 2-6. 코드 주석·화면 글의 낡은 마일스톤 표시

지나간 마일스톤을 「앞으로」라고 가리키는 자리가 **열다섯 군데** 있다. 공백은 진짜인데
**이름이 틀렸다** — 「M3에서 채웁니다」라고 적힌 것이 M5가 끝난 지금도 비어 있다.

| 자리 | 적힌 것 |
| --- | --- |
| `bot_ui/main_window.py:172,184` | 「실행 기록은 BPMN 엔진이 도는 M3에서 채워집니다」 (§4-1) |
| `bot_ui/main_window.py:286` | 「예약·최근 UI 세션·밀린 보고는 M5입니다」 (§4-2) |
| `bot_ui/main_window.py:100,131` | 「런타임 칸이 여럿 — M5」, 「메인 창 탭으로 붙이는 선택은 M5다」 |
| `bot_ui/tray.py:162,167` | 「확장이 더한 유틸리티가 없습니다 (M4)」, 「확장 목록(BUI-11)은 M4에서」 (§4-3·4-8) |
| `bot_ui/agent.py:9` | 「실제로 Bot을 실행하는 일(BPMN 엔진)은 M3이다」 |
| `bot_ui/settings_dialog.py:7` | 「확장 호스트가 설정 칸을 기여하는 것은 M4다」 (지금 돈다) |
| `center/__init__.py:11` | 「아직 없는 것: 배포·작업·결재·실행 이력·리소스 목록 (M5)」 (전부 돈다) |
| `center/api/bot_ui.py:172`, `api/packages.py:24` | 「서명·배포는 M5다」, 「승인은 Admin 서명으로, M5」 (돈다) |
| `studio/main_window.py:70,127,143` | 「Center 올리기는 M5입니다」, 「리소스 탐색기는 M4입니다」, 「「화면」 탭은 M4에서」 |
| `studio/extensions.py:150` | 「Center 리소스 목록(C7)의 주소는 M5다」 (돈다) |
| `studio/run_dialog.py:9,39` | 「감시 모드는 배포·작업(M5)과 함께다」 |
| `studio/settings_dialog.py:65` | 「툴팩이 쓰는 비밀은 툴팩과 함께 옵니다 (M5)」 |
| `web/…/center-console/components/Shell.tsx:26,30` | 「Bot 현황」·「공통 패키지」에 `later: "M5"` (§4-9·4-10) |
| `web/…/runs/[runId]/page.tsx:17` | 「UI 태스크는 M4」 (§4-11) |
| `web/…/runs/page.tsx:14` | 「실행 위치·Bot UI로 좁히는 것은 M5(배포)와 함께」 (§4-11) |

- **크기:** 작다 — 사실인 것은 지우고, 아직 아닌 것은 **마일스톤 이름을 떼고** 공백 번호를 가리킨다.
- **막는 것:** 없다. 다만 **고치지 않으면 다음 사람이 또 「이건 M5 몫이구나」로 읽고 넘어간다.**

## 3. 계약 쪽 기능 공백

### 3-1. C1 `Provides`를 채우는 쪽이 없다

- **문서:** C1 112줄 — `provides.processes[]{process_id, file, name, description, reads[], writes[], run_location, ai_tasks, human}`, `provides.tools[]`. CON-06 「제공 정의」·「제공 도구」가 읽는다.
- **코드:** `contracts.manifest`에 모델이 있다 (`provides: Provides | None = None`, 선택 칸).
- **없는 것:** Studio 패키지 내보내기(`apps/studio/packaging.py`)가 `provides`를 **아예 만들지 않는다.** 읽는 쪽(CON-06)도 없다.
- **크기:** 중간 — `reads`/`writes`는 `available_vars()`가 이미 아는 것이라 그림에서 모을 수 있다.
- **막는 것:** 쓸 자리가 **CON-06뿐이다**(§4-10). CON-06 없이 채우면 아무도 안 본다 — **묶어서 할 일이다.**

### 3-2. C3 `ui_session`을 내보내는 쪽이 없다

- **문서:** C3 48줄 — UI 태스크 한 번이 끝나면 `business_key`·`page_id`·`result`·`steps`·`fallback_depth_max`·`healed`를 남긴다. CON-01 「UI 태스크」 섹션과 UIA-03이 읽는다. `run_log.summarize()`가 이미 센다.
- **코드:** `REQUIRED_DATA_KEYS["ui_session"]`, `run_log.py:152`의 요약 집계, C3 문서 예시까지 다 있다.
- **없는 것:** **내보내는 쪽.** UI 태스크 수행기(`ext.ui_automation.client.task`)는 UI 자동화 앱에 C8 보고를 보내지만 C3 이벤트를 쓰지 않는다. 그리고 **쓸 길이 없다** — `TaskOutcome`에는 `usage`(→ `llm_usage`)만 있고 확장이 실행 기록에 한 줄 남길 칸이 없다.
- **크기:** 중간. `extension_api`에 칸을 더해야 한다.
- **막는 것:** 자기가 막는 쪽이다 — **ADR 거리다.** 확장이 C3에 이벤트를 남기는 길을 여는 것은 경계 변경이다(C3 + C13 + `extension_api` API 버전). 「`TaskOutcome.events[]`를 더할까, 수행기에 `RunLog`를 넘길까」가 ADR이 답할 거리다. 원칙 6(값을 기록하지 않는다)을 어기지 않게 **모양을 계약이 정해야** 한다.

### 3-3. C3 `run_started`의 선택 칸 `case_id`·`queued_s`

- **문서:** C3 43줄 — `case_id`(Studio 시험 실행이 어느 케이스였나), `queued_s`(PC 대기열에서 기다린 초).
- **코드:** 선택 칸이라 모델에 따로 없고(`data`에 들어간다) 아무도 넣지 않는다.
- **없는 것:** Studio 러너가 `case_id`를, Bot UI가 `queued_s`를 싣는 일. 둘 다 그 자리에서 안다.
- **크기:** 아주 작다 (각각 한 줄).
- **막는 것:** 없다. 쓰는 화면은 CON-01 목록·상세다.

> `run_waiting`·`run_resumed`도 내보내는 쪽이 없지만 **공백이 아니다** — C3 60줄이 「서버만 쓴다」고
> 적어 두었다 (PC Bot은 실행 자리를 쥐고 있으므로 `node_state: waiting`만 남긴다). M7 몫이다.

### 3-4. C4 `WorkerState.reserved_for`를 채우는 쪽이 없다

- **문서:** C4 97줄 — 하트비트의 `worker.reserved_for`는 C10 예약 `run_id`다. BUI-09 「예약」과 CON-03이 보인다.
- **코드:** 계약 모델·JSON Schema·TypeScript 타입이 다 있고, **Worker 쪽 `POST /v1/admin/reserve`와 `GET /v1/status`의 `reserved_for`도 돈다.** Bot UI도 Bot을 띄우기 전에 **실제로 예약한다** (`agent.py:809`, 그 자리에서 `run_id`를 안다).
- **없는 것:** `Agent.worker_state()`가 `reserved_for`를 넣지 않는다 (`health`만 읽고, `health`에는 그 칸이 없다). CON-03 상세도 보이지 않는다.
- **크기:** 작다 — 예약한 `run_id`를 쥐고 있으니 한 줄이다. 콘솔 한 줄 더.
- **막는 것:** 없다. **C4 `readiness`가 비어 있던 것과 똑같은 꼴이다.**

### 3-5. C5 `deprecated`로 만들 길이 없다

- **문서:** C5 75줄 `PUT /packages/{id}/{version}/status {status:"deprecated"}`(「서명이 필요 없다 — 막는 쪽이라서」), `06-screens/admin.md`의 `chk-admin deprecate <id> <버전>`. STU-11·CON-02가 「지원 종료」로 보인다.
- **코드:** `KNOWN_PACKAGE_STATUSES`에 `deprecated`가 있고, **배포 검사가 그것을 막는다** (`center_api.py:205`).
- **없는 것:** Center에 그 엔드포인트가 없고 `chk-admin deprecate`도 없다. **상태는 닿을 수 없는 값이다.**
- **크기:** 작다 (엔드포인트 하나 + CLI 한 줄).
- **막는 것:** 없다.

### 3-6. C5 `GET …/dependents`와 `DELETE /packages/{id}/{version}`

- **문서:** C5 76·77줄. CON-06 「이 패키지를 쓰는 패키지」와 CON-02·CON-06 관리자 「삭제...」(참조되면 409 `in_use`)가 쓴다.
- **코드:** 없다. `in_use` 코드도 문서에만 있다.
- **크기:** 중간 — 참조 그래프를 패키지 표에서 세어야 한다.
- **막는 것:** 쓸 자리가 CON-02·CON-06이다(§4-9·4-10). **묶어서 할 일이다.**

### 3-7. C7이 외부 확장 앱의 `health`를 보지 않는다

- **문서:** C13 165줄 — 외부 확장은 `adapter.health {path, expect_status}`를 선언할 수 있고 「없으면 Center는 상태를 「확인 전」으로 둔다」. 있으면 보라는 뜻이다.
- **코드:** Center는 **C11 `/healthz` 고정 경로만** 두드린다 (`api/resources.py:91`). `expect_status`를 읽는 코드가 없다.
- **없는 것:** 외부 확장 주소를 선언된 경로·기대 코드로 두드리는 일. 그래서 CON-07의 외부 확장 상태는 늘 「확인 전」이다.
- **크기:** 작다.
- **막는 것:** 없다. 다만 **외부 앱에 Center가 나가는 일이라** 허용 호스트·사설망 규칙을 어댑터와 같게 지켜야 한다 (C13 §4).

### 3-8. C10 `POST /v1/admin/shutdown`이 없다

- **문서:** C10 155줄 — 「열린 세션을 닫고 보고를 저장한 뒤 종료 (Bot UI 종료 순서, BUI-01)」. BUI-01 메뉴 10번의 종료 순서에 「Worker 프로세스 종료」가 있다.
- **코드:** Worker에 `/admin/reserve`(POST·DELETE)·`/admin/sessions/{id}`(DELETE)는 있는데 `/admin/shutdown`이 없다. Bot UI는 `core.processes`로 **프로세스를 끈다** — 보고를 저장할 틈 없이 죽는다.
- **없는 것:** 엔드포인트와, Bot UI 종료 순서가 그것을 먼저 부르는 일.
- **크기:** 작다.
- **막는 것:** 없다. 「밀린 보고」(§4-2)와 같은 자리를 본다 — **묶으면 싸다.**

## 4. 화면 쪽 기능 공백

### 4-1. BUI-02 「실행 기록」 탭이 비어 있다

- **문서:** `bot-ui.md` 72줄 — 최대 5000줄, 「<시각> [<Bot>] <노드> <내용>」, 실패는 한 줄 요약 먼저(U13), 문맥 메뉴(복사·화면 지우기). BUI-02 [S] 상태 줄의 「밀린 기록 N건」도 같은 자리를 본다.
- **코드:** 자리표시 탭 하나 (`_later_tab("…M3에서 채워집니다")`). 원본인 `runs/<run_id>.jsonl`과 `run_log.RunLog.read()`·`unsent_count()`는 **다 있다.**
- **없는 것:** 그 파일을 읽어 줄로 그리는 것.
- **크기:** 중간 (읽기·꼬리 자르기·문맥 메뉴).
- **막는 것:** 없다. **Bot UI에서 「방금 실행이 왜 실패했나」를 볼 수 있는 자리가 지금 하나도 없다** — 이 목록에서 현장 영향이 가장 큰 항목이다.

### 4-2. BUI-09 「예약」·「최근 UI 세션」·「밀린 보고」

- **문서:** `bot-ui.md` 264~267줄. `> 상태:` 줄이 「C10 `/v1/status`를 봐야 해서 **M5**」라고 적는다 — **M5는 끝났다.**
- **코드:** **Worker 쪽은 다 있다** — `GET /v1/status`가 `pid`·`uptime_s`·`reserved_for`·`holder`·`recent_sessions[]`·`unsent_reports`를 준다. Bot UI는 `health`만 읽는다.
- **없는 것:** Bot UI가 `/v1/status`를 부르고 세 칸을 그리는 일. **부르는 쪽이 없는 전형**이다 (`unsent_reports`·`recent_sessions`는 호출자가 Worker 자신뿐).
- **크기:** 작다~중간. 사용 토큰으로 부르면 되고(C10) 토큰은 Bot UI가 이미 쥔다.
- **막는 것:** 없다. §3-4(C4 `reserved_for`)와 **같은 값을 본다 — 묶으면 싸다.**

### 4-3. BUI-01 트레이가 도구 유틸리티를 열지 못한다

- **문서:** `bot-ui.md` 41줄 — 트레이 「도구」 ▸ 확장이 기여한 유틸리티 목록(확장 이름순) · 구분선 · 「확장...」.
- **코드:** 메뉴 항목은 만들지만 **전부 `setEnabled(False)`**이고, 하나도 없으면 「…없습니다 (M4)」를 보인다. **메인 창의 같은 메뉴는 돈다** (`main_window.py:195`) — 트레이만 끊겼다.
- **없는 것:** 트레이 항목이 `MainWindow.open_utility`를 부르게 잇는 일. 이름도 `found.id`(id 그대로)이고 문서는 유틸리티 **이름**을 쓰라고 한다.
- **크기:** 작다.
- **막는 것:** 없다. **트레이가 Bot UI의 주 진입점이다** (창을 닫아도 트레이에 남는다) — 현장에서는 이것만 보인다.

### 4-4. STU-03 리소스 탐색기 (C13 `studio.resource_views`)

- **문서:** `studio.md` 110~121줄 — 고정 뿌리 셋(「공유 BPM 프로세스」·「서비스 앱」·「툴팩」) + **확장이 기여하는 뿌리**(「UI 화면」). 끌어다 놓으면 Call Activity·UI 태스크·서비스 앱 태스크가 생긴다. STU-01 「보기 → 리소스」(Ctrl+Shift+E).
- **코드:** `ExtensionHost.resource_views()`가 있고 `ui-automation`이 「UI 화면」을 **선언한다** — 호출자가 `tests/`뿐이다. Studio에는 「리소스 탐색기는 M4입니다」 라벨 하나.
- **없는 것:** 화면 전부. 재료는 있다 — 서비스 앱 작업은 `service_catalog.from_center()`가 이미 가져오고(STU-14가 쓴다), UI 화면은 C9 공개 카탈로그에 있다.
- **크기:** 큼 (나무·끌어다 놓기·문맥 메뉴·오프라인 표시).
- **막는 것:** 「공유 BPM 프로세스」 뿌리는 §4-5(STU-11·12)가 없으면 늘 비어 있다. **뿌리별로 쪼갤 수 있다** — 「서비스 앱」·「UI 화면」만 먼저 하면 재료가 다 있다.

### 4-5. STU-06·STU-11·STU-12·STU-15가 없다

- **문서:** `studio.md` 186(STU-06 BPM 프로세스 정보)·269(STU-11 Center 공유 자원)·283(STU-12 공유 BPM 프로세스 내보내기·올리기)·349(STU-15 확장). STU-01 메뉴 표가 넷 다 가리킨다.
- **코드:** **없다.** 메뉴 항목도 없다 (「Center로 올리기」만 `LATER` 말풍선).
- **없는 것:** 네 창과, STU-01 메뉴에서 빠진 항목들 — 「BPM 프로세스 정보...」·「정의 추가...」·「이 정의를 진입으로 지정」·「다른 이름으로 저장...」·「Center 공유 자원...」·「공유 BPM 프로세스로 내보내기/올리기」·「결정 수행 (재생)...」(Ctrl+F5)·「감시 모드 시작」·「리소스」(Ctrl+Shift+E)·「확장...」·「속성 패널 접기」·「레이아웃 초기화」.
- **크기:** STU-15는 작다 (`ExtensionHost.states()`가 이미 목록을 준다). STU-06도 작다. STU-11·12는 중간 — **Center에 공유 패키지 길이 필요하다** (§3-6, CON-06).
- **막는 것:** STU-11·12는 **공유 BPM 프로세스 패키지 쪽(C5·CON-06)에 걸린다.** STU-06·STU-15는 막는 것이 없다.

### 4-6. Studio 「화면」 탭 (STU-01 아래 탭)

- **문서:** `studio.md` STU-01 배치 — 아래 탭에 「로그」·「검사」·「화면」·「변수」.
- **코드:** 「「화면」 탭은 UI 태스크가 생기는 M4에서 채웁니다」 라벨 하나. M4는 끝났다.
- **없는 것:** 무엇을 보일지가 **문서에도 없다** (배치도에 이름만 있다).
- **크기:** 모른다. **먼저 `06-screens/studio.md`에 무엇을 보일지 적어야 한다** (CLAUDE.md §3-4: 화면이 바뀌면 문서를 먼저).

### 4-7. UIA-01·02·03 — 확장이 기여하는 콘솔 화면 (C13 `console.pages`)

- **문서:** `service-app-console.md` 63~101줄. UI 자동화 앱 콘솔의 개요·셀렉터·모니터링.
- **코드:** `ExtensionHost.console_pages()`가 있고 `ui-automation/extension.json`이 **선언한다** — **호출자가 `tests/`뿐이다.** 콘솔(`svc-console/components/Shell.tsx`)에는 세 줄이 **손으로 베껴** 꺼진 채 들어 있다(`APP_PAGES`) — 기여에서 읽은 것이 아니라서 **확장을 더해도 줄이 생기지 않는다.** `href` 타입도 `"/status" | "/keys" | "/usage"` 고정 셋이다.
- **없는 것:** 콘솔이 `console_pages()` 기여를 읽는 길(+`href` 타입 풀기) + 화면 셋.
- **크기:** 큼. 데이터는 레지스트리에 있다 (`service/registry.py`가 `active`·`unverified`·실패율까지 센다).
- **막는 것:** **§2-3(Neo4j → SQLite ADR)이 막는다.** UIA-01은 「저장소 표시」로 「지식 그래프 (Neo4j)」/「YAML 레지스트리」를 보이고, UIA-02는 「그래프가 없으면 통계 열을 빼고…」라고 적는다 — 지금 저장소에 그 구분이 없다. **ADR 없이 만들면 화면이 거짓말을 한다.**

### 4-8. BUI-11 확장 · BUI-05 알림

- **문서:** `bot-ui.md` 300~318(BUI-11: 목록·등급·기여·상태·쓰는 Bot, 상세, 끄기/켜기/새로 고침)·128~142(BUI-05: 알림 13줄 표).
- **코드:** BUI-11은 메뉴 항목이 **`setEnabled(False)`**이다 (트레이·메인 창 둘 다). 재료는 있다 — `ExtensionHost.states()`·`all()`·`failures()`가 등급·버전·상태·기여를 준다. BUI-05는 `showMessage` **한 자리**뿐이다 (`app.py:85`의 경고 하나).
- **없는 것:** BUI-11 창. BUI-05는 13줄 중 1줄 남짓.
- **크기:** BUI-11 중간(「끄기/켜기」를 어디에 저장할지가 새 거리다 — 설정 파일). BUI-05 중간(알릴 거리마다 부르는 자리가 흩어져 있다).
- **막는 것:** BUI-11의 「새로 고침(Center에서 외부 확장 정의 다시 받기)」은 `core.app_directory`가 이미 한다. 나머지는 없다.

### 4-9. CON-02 Bot 현황

- **문서:** `center-console.md` 53~62줄. Bot·버전별 준비도(최근 20회), 경고 띠(사전 점검 실행 불가·리소스 누락), 관리자 「삭제...」.
- **코드:** 탐색에 `later: "M5"`로 박혀 있다 — **M5는 끝났다.** 재료는 상당히 있다 — 실행 기록(C3)·`readiness`(C4)·`missing_resources`(C5)가 Center에 다 있다.
- **없는 것:** 화면과, 집계(성공률·재생률·확인률·표본 수)와 `DELETE /packages`(§3-6).
- **크기:** 중간~큼.
- **막는 것:** 「삭제...」는 §3-6에 걸린다. 나머지는 없다.

### 4-10. CON-06 공통 패키지

- **문서:** `center-console.md` 116~127줄. 공유 BPM 프로세스·툴팩 목록과 상세(「제공 도구」·「제공 정의」·「이 패키지를 쓰는 패키지」), 관리자 「삭제...」.
- **코드:** 탐색에 `later: "M5"`. 패키지 표는 Bot이 아닌 종류도 담는다 (`kind=toolpack`이 C7 툴팩 리소스의 출처다).
- **없는 것:** 화면 + §3-1(`Provides`) + §3-6(`dependents`·`DELETE`).
- **크기:** 중간.
- **막는 것:** **셋이 서로를 막는다** (§3-1·§3-6·여기). 하나만 해도 쓸 데가 없다 — **한 덩이로 보는 쪽이 맞다.** STU-11·12(§4-5)도 이 덩이에 붙는다.

### 4-11. CON-01 「UI 태스크」 섹션과 목록 좁히기

- **문서:** `center-console.md` 32~51줄. 목록 열에 「UI 태스크」, 필터에 「실행 위치」·「Bot UI」·「최근 n건」. 상세에 「UI 태스크」 섹션(노드/화면/스텝 수/폴백 깊이/치유/전환 → UIA-03 링크).
- **코드:** 요약·노드 타임라인·AI 태스크 단계·사람 개입·로그·원본 이벤트는 **돈다.** 「UI 태스크」는 주석에 「M4」, 필터는 「M5(배포)와 함께」 — **둘 다 지났다.**
- **없는 것:** 필터 셋(값은 이제 쌓인다). 「UI 태스크」 섹션은 **§3-2가 막는다** — 읽을 이벤트가 없다. UIA-03 링크는 §4-7이 막는다.
- **크기:** 필터는 작다. 「UI 태스크」 섹션은 §3-2 뒤에 작다.
- **막는 것:** 필터는 없다. 섹션은 **§3-2 → §4-7 순서다.**

### 4-12. CON-00 탐색에 「서버 실행」(M7)이 없다

문서는 탐색에 「서버 실행」(M7)을 둔다. 코드에는 항목 자체가 없다. **M7 몫이라 공백으로 세지 않는다** — 다만 CON-02·CON-06처럼 **꺼진 항목으로 두는 쪽이 문서와 맞다** (U3: 없는 것은 끄고 이유를 적는다).

## 5. 공백은 아니지만 적어 둘 것

- **쓰지 않는 편의 접근자 셋** — `ExtensionHost.studio_editors()`(호출자 **아예 없음**, Studio는 단수 `editor(task_type)`를 쓴다), `adapter_operations()`(`AdapterCaller`가 `definitions`를 직접 본다), `secret_config_keys()`(`credentials.py`가 `configuration()`을 제 손으로 거른다). 기능 공백이 아니다 — **지울지 쓸지만 정하면 된다.**
- `extension_api`의 `HOST_SERVER_RUNNER`·`RUN_LOCATION_SERVER`는 M7이 쓸 상수다 (지금 호출자 없음, 정상).
- `SEVERITY_INFO`는 아무도 쓰지 않는다 (`SEVERITY_BLOCK`·`SEVERITY_WARN`만 쓴다).
- C13 `docs_url`·`owners`, C11 `Operation.json_schema`는 콘솔이 보이지 않는 선택 칸이다. 작고 급하지 않다.
- `apps/center/src/chaeksas/center/__init__.py`의 모듈 표가 M2에서 멈춰 있다 (§2-6).

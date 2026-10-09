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
| C2 | **구현됨** | `contracts.hashing`·`signing` V1~V8 | — (닫았다) |
| C3 | 합의 | `contracts.events`·`core.run_log` | `ui_session`을 **아무도 내보내지 않는다** (§3-2). `case_id`·`queued_s`도 (§3-3) |
| C4 | **구현됨** | `contracts.bot_ui`, Center·Bot UI 양쪽 | — (`reserved_for`를 채웠다) |
| C5 | 합의 | `contracts.center_api`, Center 전부 | `deprecated`로 **만들 길이 없다** (§3-5). `dependents`·`DELETE /packages` 없음 (§3-6) |
| C6 | **구현됨** | `contracts.approvals`, Center·현장 | — (닫았다) |
| C7 | 구현됨 | `contracts.resources`·`center_keys` | 외부 확장 앱의 `health`를 **보지 않는다** (§3-7) |
| C8 | **구현됨** | **`ext.ui_automation.contracts.plan`** | — (닫았다) |
| C9 | **구현됨** | **`ext.ui_automation.contracts.registry`** | — ([ADR-0040](decisions/0040-registry-storage-sqlite.md)이 저장소를 적었다) |
| C10 | **구현됨** | **`ext.ui_automation.contracts.worker_local`** | — (`shutdown`을 더했다) |
| C11 | **구현됨** | `contracts.service_app`·`service_kit` | — (닫았다) |
| C12 | 초안 (M7) | **없다** (`apps/server_runner`는 docstring뿐) | M7 전부. **M6 기준의 「모든 계약」에서 빼야 하는가는 사람이 정한다** (§2-4) |
| C13 | 합의 (모델·검사 구현됨) | `contracts.extension`·`core.extensions` | `console.pages`를 **아무도 그리지 않는다** (§4-7). `studio.resource_views`도 (§4-4) |
| C14 | 초안 (B1~**B15** 구현됨) | `contracts.bpmn_ext` B1~B15 | 「합의」로 올릴지는 M3 엔진·Studio와 함께 정한다 (문서가 그렇게 적는다) |

굵게 적은 셋(C8·C9·C10)은 **확장이 소유한 계약**이라 `extensions/ui_automation/…/contracts/`에
있다 (계약 README 원칙 1). CLAUDE.md §7이 「계약 코드 C8~C10·C12가 없다」고 적어 두었는데
**C8~C10은 있다** — 없는 것은 C12 하나다. (이 줄은 이 작업에서 고쳤다.)

## 2. 문서가 코드와 어긋난 자리 (코드를 고치는 일이 아니다)

### 2-4. C12는 M7이다 — M6 기준에서 뺄 것인가

C12만 코드가 전혀 없고(`apps/server_runner`는 docstring뿐), 문서도 「초안 (M7에서 구현)」이라고
스스로 적는다. M6 기준의 「모든 계약 문서 상태가 「구현됨」」을 글자대로 읽으면 C12 때문에 M6가
닫히지 않는다. **사람이 정할 거리다** — 기준 문구를 「M6 범위의 계약」으로 좁히는 쪽이 자연스럽다.

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
- **막는 것:** 없다 — [ADR-0041](decisions/0041-extension-run-events.md)이 모양을 정했다. **`TaskOutcome.events[]`**(`{kind, data}`)를 더하고 **줄을 쓰는 것은 엔진**이다(`run_id`·`seq`·`ts`를 붙이고 `sanitize()`로 거른다, 원칙 6). 어긋난 줄은 **그 줄만 버린다**. 남은 일: C3·C13 문서 → `extension_api` 1.2 → 엔진 → UI 태스크 수행기.

### 3-3. C3 `run_started`의 선택 칸 `case_id`·`queued_s`

- **문서:** C3 43줄 — `case_id`(Studio 시험 실행이 어느 케이스였나), `queued_s`(PC 대기열에서 기다린 초).
- **코드:** 선택 칸이라 모델에 따로 없고(`data`에 들어간다) 아무도 넣지 않는다.
- **없는 것:** Studio 러너가 `case_id`를, Bot UI가 `queued_s`를 싣는 일. 둘 다 그 자리에서 안다.
- **크기:** 아주 작다 (각각 한 줄).
- **막는 것:** 없다. 쓰는 화면은 CON-01 목록·상세다.

> `run_waiting`·`run_resumed`도 내보내는 쪽이 없지만 **공백이 아니다** — C3 60줄이 「서버만 쓴다」고
> 적어 두었다 (PC Bot은 실행 자리를 쥐고 있으므로 `node_state: waiting`만 남긴다). M7 몫이다.

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

## 4. 화면 쪽 기능 공백

### 4-2. BUI-09 「최근 UI 세션」

「예약」·「밀린 보고」는 **닫았다** — Bot UI가 C13 `status` 선언대로 런타임의 상태를 묻는다.
남은 것은 **「최근 UI 세션」 표 하나**다.

- **문서:** `bot-ui.md` 264~267줄 — 시각 / 요청한 쪽 / **화면** / 결과 / **폴백 깊이** / **치유**.
- **코드:** Worker의 `GET /v1/status`가 `recent_sessions[]`로 준다. Bot UI는 **읽지 않는다.**
- **없는 것:** 그 표를 그리는 쪽.
- **막는 것:** 없다 — [ADR-0042](decisions/0042-extension-contributed-panels.md)가 정했다.
  굵게 적은 열은 **UI 자동화의 말**이라 플랫폼이 그릴 수 없다 (ADR-0018) — 그래서 `status`의
  **뜻을 아는 칸만**(`reserved_for`·`unsent_reports`) 읽게 두었다. **확장이 위젯을 기여한다**:
  C13에 `bot_ui.panels`(`{id, label, surface, runtime?, entry}`)를 더하고, `surface`는 플랫폼이
  미리 정한 자리 이름(`bot_ui.runtimes`)이며 **모르는 `surface`는 조용히 무시한다**. 규약은
  STU-13·14 편집기와 같고 `refresh()`만 더 받는다. 남은 일: C13 문서 → 모델·검사 → Bot UI가
  칸을 끼우는 길 → 확장의 패널. §4-7과 **같은 결정**을 쓴다.

### 4-4. STU-03 리소스 탐색기 (C13 `studio.resource_views`)

- **문서:** `studio.md` 110~121줄 — 고정 뿌리 셋(「공유 BPM 프로세스」·「서비스 앱」·「툴팩」) + **확장이 기여하는 뿌리**(「UI 화면」). 끌어다 놓으면 Call Activity·UI 태스크·서비스 앱 태스크가 생긴다. STU-01 「보기 → 리소스」(Ctrl+Shift+E).
- **코드:** `ExtensionHost.resource_views()`가 있고 `ui-automation`이 「UI 화면」을 **선언한다** — 호출자가 `tests/`뿐이다. Studio에는 「리소스 탐색기는 M4입니다」 라벨 하나.
- **없는 것:** 화면 전부. 재료는 있다 — 서비스 앱 작업은 `service_catalog.from_center()`가 이미 가져오고(STU-14가 쓴다), UI 화면은 C9 공개 카탈로그에 있다.
- **크기:** 큼 (나무·끌어다 놓기·문맥 메뉴·오프라인 표시).
- **막는 것:** 「공유 BPM 프로세스」 뿌리는 §4-5(STU-11·12)가 없으면 늘 비어 있다. **뿌리별로 쪼갤 수 있다** — 「서비스 앱」·「UI 화면」만 먼저 하면 재료가 다 있다. 여기는 **코드 기여가 필요 없다** — 기여가 선언(`{id, label, resource_type, creates_task_type}`)이고 목록은 C7에서 와서 모양이 하나다 ([ADR-0042](decisions/0042-extension-contributed-panels.md) §3).

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
- **막는 것:** 없다 — ADR 둘이 풀었다. [ADR-0040](decisions/0040-registry-storage-sqlite.md)이 저장소를 적어 「저장소 표시」를 없애고 통계 열을 **늘 있는 것**으로 만들었고(경로 탐색은 앱이 너비 우선으로 찾는다), [ADR-0042](decisions/0042-extension-contributed-panels.md)가 **콘솔이 `console.pages` 기여를 읽는 길**을 정했다(모노레포 안 내장·사내 확장만, 빌드 시점 레지스트리). 손으로 베낀 `APP_PAGES`를 버리고 `href` 타입을 푼다.

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

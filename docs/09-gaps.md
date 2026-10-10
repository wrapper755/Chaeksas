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
| C1 | **구현됨** | `contracts.manifest` R1~R8 (R8은 Center 배포가 짓는다) | — (닫았다 — Studio가 `Provides`를 짓고 CON-06이 읽는다) |
| C2 | **구현됨** | `contracts.hashing`·`signing` V1~V8 | — (닫았다) |
| C3 | **구현됨** | `contracts.events`·`core.run_log` | — (닫았다: `ui_session`은 [ADR-0041](decisions/0041-extension-run-events.md), `case_id`·`queued_s`는 아는 쪽이 넣는다) |
| C4 | **구현됨** | `contracts.bot_ui`, Center·Bot UI 양쪽 | — (`reserved_for`를 채웠다) |
| C5 | **구현됨** | `contracts.center_api`, Center 전부 | — (닫았다 — 지원 종료·참조·삭제까지) |
| C6 | **구현됨** | `contracts.approvals`, Center·현장 | — (닫았다) |
| C7 | **구현됨** | `contracts.resources`·`center_keys` | — (닫았다 — 외부 확장은 어댑터 `health`로 본다) |
| C8 | **구현됨** | **`ext.ui_automation.contracts.plan`** | — (닫았다) |
| C9 | **구현됨** | **`ext.ui_automation.contracts.registry`·`console`** | — (관리 콘솔이 읽는 길도 돈다) |
| C10 | **구현됨** | **`ext.ui_automation.contracts.worker_local`** | — (`recent_sessions[]`를 BUI-09가 그린다) |
| C11 | **구현됨** | `contracts.service_app`·`service_kit` | — (닫았다) |
| C12 | 초안 (M7) | **없다** (`apps/server_runner`는 docstring뿐) | M7 전부. **M6 기준의 「모든 계약」에서 빼야 하는가는 사람이 정한다** (§2-4) |
| C13 | 합의 (모델·검사 구현됨) | `contracts.extension`·`core.extensions` | — (닫았다 — 기여 지점마다 읽는 쪽이 있다. `studio.resource_views`는 STU-03이, `console.pages`는 콘솔이 읽는다). 「구현됨」으로 올릴지는 사람이 정한다 |
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

**닫았다 — 남은 것이 없다.** 계약 열넷의 상태는 §1 표에 있다.

## 4. 화면 쪽 기능 공백

### 4-4. STU-03 리소스 탐색기 — 끌어다 놓기만 남았다

**뿌리 넷·둘째 단계·문맥 메뉴·「캔버스에 추가」는 닫았다** (`apps/studio/resources.py` + 캔버스 명령 `createTask`). C13 `studio.resource_views`를 읽는 쪽이 생겼다.

- **없는 것:** Qt → QtWebEngine **드래그**. 지금은 문맥 메뉴 「캔버스에 추가」·더블클릭이고 화면 문서가 그렇게 적는다.
- **없는 것 둘:** 기여 뿌리의 **둘째 단계**(「UI 화면 → 요소」)와 「요소 보기」·「요소를 끌어다 스텝 추가」. 항목의 `data`를 플랫폼이 해석하지 않기 때문이다 (C13 §5) — 하려면 C13에 **자식 선언**(`children_key`·`child_label_key` 같은 것)을 더해 「선언대로 걷게」 해야 한다. 요소를 고르는 일은 STU-13이 이미 한다.
- **크기:** 드래그는 중간, 자식 선언은 계약·생성물이 붙는다.
- **막는 것:** 「공유 BPM 프로세스」 뿌리와 툴팩 「설치...」·「제거...」는 §4-5(STU-11·12 「올리기」)가 없어 **꺼진 줄 + 까닭**이다.

### 4-5. STU-06·STU-11이 없다 (STU-12는 「내보내기」만 있다)

- **문서:** `studio.md` 186(STU-06 BPM 프로세스 정보)·269(STU-11 Center 공유 자원)·283(STU-12 공유 BPM 프로세스 내보내기·올리기). STU-01 메뉴 표가 셋 다 가리킨다.
- **코드:** STU-06·STU-11은 **없다.** STU-12는 **「공유 BPM 프로세스로 내보내기...」가 돈다** (`ShareDefinitionsDialog`) — 「올리기」 둘은 `LATER` 말풍선이다. **STU-15는 닫았다** (`extension_dialog.py` — 끄고 켜기까지, [ADR-0043](decisions/0043-turned-off-extensions.md)).
- **없는 것:** 두 창과, STU-01 메뉴에서 빠진 항목들 — 「BPM 프로세스 정보...」·「정의 추가...」·「이 정의를 진입으로 지정」·「다른 이름으로 저장...」·「Center 공유 자원...」·「결정 수행 (재생)...」(Ctrl+F5)·「감시 모드 시작」·「속성 패널 접기」·「레이아웃 초기화」.
- **크기:** STU-06은 작다. STU-11은 중간. **STU-12의 「내보내기」는 생겼다** (`ShareDefinitionsDialog` + `packaging.export_lib`) — 남은 것은 「올리기」이고 그것은 「Center로 올리기」와 **같은 거리**다 (Studio에 패키지 올리는 길이 없다).
- **막는 것:** 없다. STU-11은 Center 리소스 목록(C7)을, STU-12 「올리기」는 Studio의 패키지 업로드를 먼저 붙이면 된다.

### 4-6. Studio 「화면」 탭 (STU-01 아래 탭)

- **문서:** `studio.md` STU-01 배치 — 아래 탭에 「로그」·「검사」·「화면」·「변수」.
- **코드:** 「「화면」 탭은 UI 태스크가 생기는 M4에서 채웁니다」 라벨 하나. M4는 끝났다.
- **없는 것:** 무엇을 보일지가 **문서에도 없다** (배치도에 이름만 있다).
- **크기:** 모른다. **먼저 `06-screens/studio.md`에 무엇을 보일지 적어야 한다** (CLAUDE.md §3-4: 화면이 바뀌면 문서를 먼저).

### 4-8. BUI-05 알림 두 줄 — **이 PC가 그 값을 모른다**

**열한 줄은 닫았다** (`bot_ui/notices.py` + `agent.py`). 남은 둘은 코드를 더 쓰는 문제가 아니라 **값이 없는** 문제다 — 다른 쪽을 먼저 정해야 한다.

- **문서:** `bot-ui.md` BUI-05 표의 「Center API 키 만료 임박」·「서비스 앱 키 만료 임박·거부」.
- **없는 것과 왜:**
  - **Center API 키 만료 임박**(14일 전부터 하루 한 번): 만료일은 **Center만 안다**. C4 등록·하트비트 응답에 그 칸이 없어 Bot UI는 「거부됨」만 알 수 있다(403). **C4에 선택 칸(예: `key_expires_at`)을 더하면** 나머지는 하루 한 번 재는 것뿐이다.
  - **서비스 앱 키 만료 임박·거부**: 만료일은 그 앱의 C11 `GET /v1/keys/self`가 말해 주지만 **사전 점검은 서버를 부르지 않는다**(ADR-0013) — 하트비트마다 물을 수 없다. 「언제 물을 것인가」(하루 한 번? BUI-10을 열 때만?)를 정해야 한다. 거부는 실행 기록의 `service_call`에 남아 있지만, **Bot UI가 기록을 읽어 해석하는 자리가 없다**(기록은 그려 보일 뿐이다 — BUI-02).
- **크기:** 둘 다 작다 (각 한 줄 + 재는 주기). **먼저 정할 것이 계약·주기**다.
- **막는 것:** 앞은 C4 칸, 뒤는 「서버를 언제 부르나」 결정.

### 4-9. CON-02가 못 세는 것 둘

**화면은 닫았다** (`app/bots` — 목록·경고 띠 둘·관리자 「삭제...」). 남은 둘은 **값이 없거나 시험 판이 없는** 것이다.

- **「확인률」을 가를 수 없다:** C3 `RunInfo.human_requests`가 **결재와 확인을 한 칸에 합쳐** 센다. 화면은 「사람 개입(실행당)」으로 보이고 그렇게 말한다. 가르려면 **C3 `run_finished`에 셈 칸을 더해야** 한다(보내는 쪽이 세는 값이라 Center가 뒤에서 만들 수 없다) — 선택 칸이니 옛 Bot UI가 보낸 기록은 그대로 합으로 남는다. **크기:** 작다 (엔진 한 줄 + 계약 한 칸 + 화면 한 열).
- **「배포된 Bot UI」의 PC 수를 셀 수 없다:** 그룹·전체(`*`) 배포의 대상을 Center가 풀어 주지 않는다. 지금은 **배포 건수**와, 그 판을 실행 불가로 **보고한 PC 수**를 보인다. PC 수를 세려면 Center가 대상을 푸는 길(C5에 `targets[]` 같은 것)을 먼저 정해야 한다.
- **콘솔 집계 함수에 단위 시험이 없다:** 성공률·재생률·표본을 세는 것은 TypeScript(`summarize`)이고 **`web`에 시험 판이 없다** — 지금은 `pnpm typecheck`·`pnpm build`와, 재료가 오는지 보는 파이썬 시험(`tests/test_console_bot_status.py`)까지다. 셈이 틀려도 잡히지 않는다. **먼저 정할 것:** 웹에 시험 판(예: vitest)을 들일지 — 들이면 CI에 한 걸음이 늘고, 들이지 않으면 콘솔의 계산은 계속 눈으로 본다.

### 4-11. CON-01 「Bot UI」 필터와 UIA-03 링크

**필터 넷·목록 열·「UI 태스크」 섹션은 닫았다.** 남은 둘은 **다른 것을 먼저 정해야** 하는 자리다.

- **「Bot UI」 필터·열:** C3 `RunInfo`에 **어느 Bot UI였나가 없다**. Center는 `run_id`를 보낸 **키**에 묶어 두고(C3 소유) C4 키 묶기로 그 키가 어느 Bot UI인지도 알지만, 실행 요약에 적지 않는다. 적으려면 C3에 칸을 더할지(선택 칸 `bot_ui_id`), 요약을 만들 때 키→Bot UI를 풀어 넣을지 정해야 한다. **크기:** 작다 (요약 한 칸 + 필터 한 줄). 화면은 지금 **그 이유를 적어 둔다** (U3).
- **UIA-03 링크:** 상세의 「UI 태스크」 줄에서 그 앱의 관리 콘솔로 가는 링크. Center 콘솔은 **그 주소를 모른다** — C7 서비스 앱 리소스의 `console_url`을 BFF가 읽어 와야 한다. **크기:** 작다. **막는 것:** 어느 앱의 콘솔인지 고르는 길(실행 기록에는 `page_id`만 있고 어느 UI 자동화 앱인지는 없다)을 정해야 한다.

## 5. 공백은 아니지만 적어 둘 것

- **C3 `run_waiting`·`run_resumed`는 내보내는 쪽이 없다** — 공백이 아니다. C3가 「서버만 쓴다」고 적어 두었다 (PC Bot은 실행 자리를 쥐고 있어 `node_state: waiting`만 남긴다). M7 몫이다. (§3-3이 닫히면서 이 줄이 여기로 왔다.)
- **쓰지 않는 편의 접근자 셋** — `ExtensionHost.studio_editors()`(호출자 **아예 없음**, Studio는 단수 `editor(task_type)`를 쓴다), `adapter_operations()`(`AdapterCaller`가 `definitions`를 직접 본다), `secret_config_keys()`(`credentials.py`가 `configuration()`을 제 손으로 거른다). 기능 공백이 아니다 — **지울지 쓸지만 정하면 된다.**
- `extension_api`의 `HOST_SERVER_RUNNER`·`RUN_LOCATION_SERVER`는 M7이 쓸 상수다 (지금 호출자 없음, 정상).
- `SEVERITY_INFO`는 아무도 쓰지 않는다 (`SEVERITY_BLOCK`·`SEVERITY_WARN`만 쓴다).
- C13 `docs_url`·`owners`, C11 `Operation.json_schema`는 콘솔이 보이지 않는 선택 칸이다. 작고 급하지 않다.

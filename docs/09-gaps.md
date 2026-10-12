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
| C3 | **구현됨** | `contracts.events`·`core.run_log` | — (닫았다: `ui_session`은 [ADR-0041](decisions/0041-extension-run-events.md), `case_id`·`queued_s`는 아는 쪽이 넣는다, `confirmations`는 **세는 쪽**이 가르고 `bot_ui_id`는 **Center가 읽을 때** 채운다) |
| C4 | **구현됨** | `contracts.bot_ui`, Center·Bot UI 양쪽 | — (`reserved_for`를 채웠고 `key_expires_at`으로 BUI-05 키 만료를 닫았다) |
| C5 | **구현됨** | `contracts.center_api`, Center 전부 | — (닫았다 — 지원 종료·참조·삭제, 그리고 **권한표**까지. 패키지 쪽은 키 종류를 보는 관문이 따로 있다: `auth.require_upload`·`require_package_read`·`api.package_access.guard_download`) |
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

계약 열넷의 상태는 §1 표에 있다. 남은 것은 아래 하나다.

### 3-9. 배포의 「대상이 존재한다」 — **막을 것인지 먼저 정한다**

C5 §배포가 Center의 검사로 「대상이 존재한다」를 적어 두었는데 **어느 쪽도 보지 않는다** —
계약 `validate_deployment()`도(저장소를 보지 않으니 당연하다), Center `create()`도 `bot_uis`
표를 찾지 않는다. 작업 지시(`POST /jobs`)는 본다 (`not_found`, 404).

[ADR-0047](decisions/0047-one-deployment-gate.md)에서 관문을 하나로 모으며 드러났고, **그
ADR의 범위가 아니다**(관문을 모으는 일과 규칙을 더하는 일은 다르다).

**먼저 정할 것:** 등록되지 않은 PC에 미리 배포해 두는 것이 뜻 있는 일인가. 뜻이 있다면
(새 PC를 준비해 두고 등록하면 첫 하트비트에 받아 가는 길) 검사를 더하지 않고 **C5에서 그
줄을 걷는다**. 뜻이 없다면 Center `create()`가 404로 막고 ADR-0046의 결(「받아는 줬다가 가장
나쁜 답이다」)을 따른다. **고르기 전에 코드를 더하지 않는다** — 막는 쪽으로 가면 되돌릴 때
이미 배포해 둔 것이 없어진다.

## 4. 화면 쪽 기능 공백

### 4-5. 「설치」 (올리기·STU-11·STU-06·STU-03과 **공유 BPM 프로세스 설치**는 닫았다)

**올리기 둘과 STU-11 읽기는 닫았다** (`apps/studio/upload.py` + `center_resources.py`, Center 쪽 권한 관문은 `center/auth.py`·`api/package_access.py`). Studio 키로 올리고, 올라온 공유 BPM 프로세스·툴팩을 STU-11과 STU-03이 **같은 출처**(C5 패키지 표)에서 본다. **STU-06도 닫았다** (`process_dialog.py` — 그림 쪽은 캔버스를 거친다. 확장 태스크의 실행 위치는 확장 호스트의 표로 센다 — F6·매니페스트가 같은 표를 쓴다). **STU-15도 닫았다** ([ADR-0043](decisions/0043-turned-off-extensions.md)). **STU-03도 닫았다** (`resources.py` — 뿌리 넷·둘째 단계·문맥 메뉴·「캔버스에 추가」·끌어다 놓기. 드래그는 [ADR-0044](decisions/0044-canvas-drag-and-drop.md), 기여 뿌리의 둘째 단계를 **두지 않기로** 한 것은 [ADR-0045](decisions/0045-contributed-resource-children.md)다).

**공유 BPM 프로세스 「설치」는 닫았다** ([ADR-0048](decisions/0048-installing-shared-packages.md) — `apps/studio/install.py` + `workspace.py`·`packaging.py`·STU-11). 받은 것이 그 BPM 프로세스 작업 폴더의 `libs/`로 가고, **호출이 거기서 찾는다**(실행기가 이미 읽는 자리라 내보내기·실행기는 바뀌지 않았다) — 그래서 설치 뒤에는 시험 실행도 **C14 B14도** 그 호출을 받아들이고, 내보낼 때 `requires.libs`에 **판이 붙는다**(C1 `<id>@<version>` — 전에는 id만 적혀 R3·CON-06의 참조 셈이 어긋났다). **결정표(DMN)도 함께 온다** — 정의가 쓰는 `.dmn`을 같이 풀고 **Studio와 실행기가 둘 다** `libs/*.dmn`을 읽어, lib 안의 규칙 태스크가 **진짜로 돈다**(엔진으로 본다. 결정표를 지우면 멈추는 것도 함께).

- **남은 것 하나 — STU-03의 편의 셋:** 「캔버스에 추가」(Call Activity)·「열기 (읽기 전용)」·「내 BPM 프로세스로 복사」. **막는 것:** 그 뿌리의 줄은 **Center 목록**이라 「이 PC(이 BPM 프로세스)에 그 판이 있나」를 줄마다 알지 못한다 — 설치 여부를 뿌리에 섞어 그릴지(그러면 뿌리가 Center 목록이 아니게 된다), STU-11에만 두고 STU-03은 보기 전용으로 둘지 **고르면 된다**. 지금은 속성 패널에서 `calledElement`를 적어 부른다. **크기:** 작다.
- **남은 것 둘 — 툴팩 「설치」:** 자리가 아니라 **도구를 싣는 길이 아무 데도 없다** — `toolpack`을 아는 곳은 Center의 목록·참조 계산과 Studio의 **표시**뿐이고, 도구는 `core.tools`의 내장 넷뿐이다 (Bot UI 실행기에도 싣는 길이 없다). **먼저 정할 것:** 「받은 코드를 돌려도 되나」 — 관문(승인된 것만?)·싣는 길(「툴팩은 확장이 아닌가?」)·파일 권한(ADR-0032의 경계를 어떻게 물려주나). **ADR 하나가 먼저다** (ADR-0048 §왜 툴팩을 가르나).
- **남은 것 셋 — STU-01 메뉴에서 빠진 항목들:** 「정의 추가...」·「이 정의를 진입으로 지정」·「다른 이름으로 저장...」·「결정 수행 (재생)...」(Ctrl+F5)·「감시 모드 시작」·「속성 패널 접기」·「레이아웃 초기화」.
  **크기:** 작다.

### 4-6. Studio 「화면」 탭 (STU-01 아래 탭)

- **문서:** `studio.md` STU-01 배치 — 아래 탭에 「로그」·「검사」·「화면」·「변수」.
- **코드:** 「「화면」 탭은 UI 태스크가 생기는 M4에서 채웁니다」 라벨 하나. M4는 끝났다.
- **없는 것:** 무엇을 보일지가 **문서에도 없다** (배치도에 이름만 있다).
- **크기:** 모른다. **먼저 `06-screens/studio.md`에 무엇을 보일지 적어야 한다** (CLAUDE.md §3-4: 화면이 바뀌면 문서를 먼저).

### 4-8. BUI-05 「서비스 앱 키 만료 임박·거부」 — **언제 물을 것인가를 먼저 정한다**

**열두 줄은 닫았다** (`bot_ui/notices.py` + `agent.py`). 「Center API 키 만료 임박」은 C4에 `key_expires_at`을 더해 닫았다 — 만료일은 Center만 알아 응답에 싣고, 14일 전부터 하루 한 번 알린다.

- **문서:** `bot-ui.md` BUI-05 표의 「서비스 앱 키 만료 임박·거부」.
- **없는 것과 왜:** 만료일은 그 앱의 C11 `GET /v1/keys/self`가 말해 주지만 **사전 점검은 서버를 부르지 않는다**(ADR-0013) — 하트비트마다 물을 수 없다. 거부는 실행 기록의 `service_call`에 남아 있지만, **Bot UI가 기록을 읽어 해석하는 자리가 없다**(기록은 그려 보일 뿐이다 — BUI-02).
- **먼저 정할 것:** **「언제 물을 것인가」.** 셋을 놓고 골랐다가 미뤘다 — ① 하루 한 번 `agent`의 주기 자리에서 각 앱의 `/v1/keys/self`를 묻는다(점검 규칙은 지키지만 Bot UI에 새 네트워크 동작이 생긴다), ② BUI-10을 열 때만 묻는다(알림으로는 못 띄운다 — BUI-05의 그 줄은 안 닫힌다), ③ 하지 않는다. **ADR-0013의 결을 건드리므로 ADR이 먼저다.**
- **크기:** 알림 자체는 작다 (한 줄 + 재는 주기). 「거부」는 기록을 읽는 자리를 새로 만드는 일이라 그보다 크다.

### 4-9. CON-02 — 콘솔 집계 시험

**화면·「확인률」·「배포된 Bot UI」를 닫았다** (`app/bots`). 확인률은 C3 `run_finished`에 선택 칸 `confirmations`를 더해 잰다 — 가르는 것은 **세는 쪽의 일**이고(Center는 줄을 다시 읽어 세지 않는다) 보내지 않은 옛 기록은 **분모에서 빠진다**.

**「배포된 Bot UI」도 닫았다** ([ADR-0046](decisions/0046-no-wildcard-pc-deployment.md)). 여기 적혀 있던 「먼저 정할 것」(**C5가 대상을 푸는 길**)은 **없었다** — 「그룹 배포」는 계약에도 코드에도 아예 없고, 전체(`*`) 배포는 **PC 쪽에 없다**(C2는 `"*"`를 서버 배포에만 주고 `DeploymentTarget.matches`·V6도 그렇다). 그래서 PC 배포는 전부 `bot_ui_id` 하나를 가리키고 「배포된 Bot UI」는 **`target.id`를 겹치지 않게 센 수**다. 재료는 CON-02가 이미 받아 둔 둘(C5 배포 목록·Bot UI 목록)로 끝났고 **계약이 늘지 않았다**. 함께 고친 것 둘: Center 네 자리가 대상 종류를 가리지 않고 `"*"`를 풀던 것(이제 한 함수가 짓고 `POST /deployments`는 409 `wrong_target`), 그리고 `summarize`가 **제가 세지 않은 칸**(`blocked`·`deployments`)을 0으로 들고 돌아와 실제 값을 덮던 것(끝난 실행이 있는 판은 「실행 불가」가 늘 0이었다).

- **콘솔 집계 함수에 단위 시험이 없다:** 성공률·재생률·확인률·표본을 세는 것은 TypeScript(`summarize`)이고 **`web`에 시험 판이 없다** — 지금은 `pnpm typecheck`·`pnpm build`와, 재료가 오는지 보는 파이썬 시험(`tests/test_console_bot_status.py`)까지다. 셈이 틀려도 잡히지 않는다. **덮어쓰기 흠을 겪은 뒤로** 그 묶음이 **글로도** 본다(열 이름, `RunFields`가 있는가, `Omit<BotRow`로 돌려주지 않는가, `*`를 푸는 코드가 없는가) — 셈을 재지는 못하고 **같은 흠이 다시 들어오는 것만** 막는다. **먼저 정할 것:** 웹에 시험 판(예: vitest)을 들일지 — 들이면 CI에 한 걸음이 늘고, 들이지 않으면 콘솔의 계산은 계속 눈으로 본다. **2026-10-11에 「들이지 않는다」로 한 번 정했다** (사람이 고른 것이고, 뒤집을 수 있다).

## 5. 공백은 아니지만 적어 둘 것

- **C3 `run_waiting`·`run_resumed`는 내보내는 쪽이 없다** — 공백이 아니다. C3가 「서버만 쓴다」고 적어 두었다 (PC Bot은 실행 자리를 쥐고 있어 `node_state: waiting`만 남긴다). M7 몫이다. (§3-3이 닫히면서 이 줄이 여기로 왔다.)
- **쓰지 않는 편의 접근자 셋** — `ExtensionHost.studio_editors()`(호출자 **아예 없음**, Studio는 단수 `editor(task_type)`를 쓴다), `adapter_operations()`(`AdapterCaller`가 `definitions`를 직접 본다), `secret_config_keys()`(`credentials.py`가 `configuration()`을 제 손으로 거른다). 기능 공백이 아니다 — **지울지 쓸지만 정하면 된다.**
- `extension_api`의 `HOST_SERVER_RUNNER`·`RUN_LOCATION_SERVER`는 M7이 쓸 상수다 (지금 호출자 없음, 정상).
- `SEVERITY_INFO`는 아무도 쓰지 않는다 (`SEVERITY_BLOCK`·`SEVERITY_WARN`만 쓴다).
- C13 `docs_url`·`owners`, C11 `Operation.json_schema`는 콘솔이 보이지 않는 선택 칸이다. 작고 급하지 않다.

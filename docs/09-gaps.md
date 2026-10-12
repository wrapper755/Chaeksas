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

계약 열넷의 상태는 §1 표에 있다. **남은 것이 없다** (3-9를 [ADR-0049](decisions/0049-deployment-target-must-exist.md)로 닫았다 — 배포 대상은 등록된 PC여야 하고, 등록 전에는 봉투에 적을 `bot_ui_id`가 없어 「미리 배포해 두기」는 길이 아니었다).

## 4. 화면 쪽 기능 공백

### 4-5. 「설치」 (올리기·STU-11·STU-06·STU-03과 **공유 BPM 프로세스 설치·부르기·보기·복사**는 닫았다)

**올리기 둘과 STU-11 읽기는 닫았다** (`apps/studio/upload.py` + `center_resources.py`, Center 쪽 권한 관문은 `center/auth.py`·`api/package_access.py`). Studio 키로 올리고, 올라온 공유 BPM 프로세스·툴팩을 STU-11과 STU-03이 **같은 출처**(C5 패키지 표)에서 본다. **STU-06도 닫았다** (`process_dialog.py` — 그림 쪽은 캔버스를 거친다. 확장 태스크의 실행 위치는 확장 호스트의 표로 센다 — F6·매니페스트가 같은 표를 쓴다). **STU-15도 닫았다** ([ADR-0043](decisions/0043-turned-off-extensions.md)). **STU-03도 닫았다** (`resources.py` — 뿌리 넷·둘째 단계·문맥 메뉴·「캔버스에 추가」·끌어다 놓기. 드래그는 [ADR-0044](decisions/0044-canvas-drag-and-drop.md), 기여 뿌리의 둘째 단계를 **두지 않기로** 한 것은 [ADR-0045](decisions/0045-contributed-resource-children.md)다).

**공유 BPM 프로세스 「설치」는 닫았다** ([ADR-0048](decisions/0048-installing-shared-packages.md) — `apps/studio/install.py` + `workspace.py`·`packaging.py`·STU-11). 받은 것이 그 BPM 프로세스 작업 폴더의 `libs/`로 가고, **호출이 거기서 찾는다**(실행기가 이미 읽는 자리라 내보내기·실행기는 바뀌지 않았다) — 그래서 설치 뒤에는 시험 실행도 **C14 B14도** 그 호출을 받아들이고, 내보낼 때 `requires.libs`에 **판이 붙는다**(C1 `<id>@<version>` — 전에는 id만 적혀 R3·CON-06의 참조 셈이 어긋났다). **결정표(DMN)도 함께 온다** — 정의가 쓰는 `.dmn`을 같이 풀고 **Studio와 실행기가 둘 다** `libs/*.dmn`을 읽어, lib 안의 규칙 태스크가 **진짜로 돈다**(엔진으로 본다. 결정표를 지우면 멈추는 것도 함께).

**STU-03의 편의 셋도 닫았다** ([ADR-0051](decisions/0051-shared-process-conveniences.md) — `resources.py`·`install.py`·`center_actions.py`·`viewer.py`). 적혀 있던 「먼저 정할 것」(**줄마다 설치 여부를 알지 못한다**)은 **틀렸다** — 재료(`BpmProcess.libs`)가 다 있었고 **STU-11이 바로 그 C5 목록에 설치 여부를 덧붙여** 그리고 있었다. 그래서 적어 둔 두 선택지가 **셋째를 빠뜨렸다**: 멤버십은 Center 목록 그대로 두고 **설치 여부만 줄에 덧붙인다**(줄이 늘거나 줄지 않는다). 설치 여부를 읽는 함수는 **STU-11과 하나**(`install.installed_of`)이고, 셋은 **설치된 판의 정의에서만** 켜진다(아니면 끄고 까닭을 적어 STU-11로 보낸다 — 설치되지 않은 호출은 B14가 막는다). 「열기 (읽기 전용)」은 **bpmn-js 뷰어 한 벌을 더 실어**(+190 KB) 지킨다 — 팔레트만 가린 편집기를 「읽기 전용」이라 부르지 않는다. 「복사」는 `process/`로 가 그때부터 **내 것이 이기고** `requires.libs`에서 저절로 빠진다.

- **남은 것 하나 — 툴팩 「설치」:** 자리가 아니라 **도구를 싣는 길이 아무 데도 없다** — `toolpack`을 아는 곳은 Center의 목록·참조 계산과 Studio의 **표시**뿐이고, 도구는 `core.tools`의 내장 넷뿐이다 (Bot UI 실행기에도 싣는 길이 없다). **먼저 정할 것:** 「받은 코드를 돌려도 되나」 — 관문(승인된 것만?)·싣는 길(「툴팩은 확장이 아닌가?」)·파일 권한(ADR-0032의 경계를 어떻게 물려주나). **ADR 하나가 먼저다** (ADR-0048 §왜 툴팩을 가르나).
- **남은 것 둘 — STU-01 메뉴:** 파일 메뉴 셋(「정의 추가...」·「이 정의를 진입으로 지정」·「다른 이름으로 저장...」)과 「결정 수행 (재생)...」(Ctrl+F5)은 **닫았다** (`file_actions.py`·`workspace.py`·`run_dialog.py`의 `prefer`). 「다른 이름으로 저장」의 단위는 **BPM 프로세스 한 벌**이다 — 정의 하나만 복사하면 그림 안의 process id가 겹쳐 호출이 모호해지고, 고치려면 XML을 파이썬이 만져야 한다 ([ADR-0022](decisions/0022-studio-canvas.md)가 막는다). 남은 것은 셋이다.
  - **「감시 모드 시작」 (Shift+F5):** 트리거를 기다려 되풀이하는 일이 **아무 데도 없다** (STU-08의 라디오도 끈 채다). Studio가 타이머·메시지를 기다리는 자리를 새로 만드는 일이라 **먼저 정할 것**은 「시험 실행이 기다려도 되는가」다(지금 시험 실행은 한 번 돌고 끝난다). **크기:** 중간 — ADR 하나가 먼저다.
  - **「속성 패널 접기」(Ctrl+Shift+P)·「레이아웃 초기화」:** 화면은 「크기·위치를 기억한다」고 적어 두었는데 **`QSettings`가 아예 없다** — 기억하는 쪽을 먼저 만들어야 「초기화」가 뜻을 가진다. **크기:** 작다 (독·분할 상태를 저장·복원하는 한 자리).


### 4-9. CON-02 — 콘솔 집계 시험

**화면·「확인률」·「배포된 Bot UI」를 닫았다** (`app/bots`). 확인률은 C3 `run_finished`에 선택 칸 `confirmations`를 더해 잰다 — 가르는 것은 **세는 쪽의 일**이고(Center는 줄을 다시 읽어 세지 않는다) 보내지 않은 옛 기록은 **분모에서 빠진다**.

**「배포된 Bot UI」도 닫았다** ([ADR-0046](decisions/0046-no-wildcard-pc-deployment.md)). 여기 적혀 있던 「먼저 정할 것」(**C5가 대상을 푸는 길**)은 **없었다** — 「그룹 배포」는 계약에도 코드에도 아예 없고, 전체(`*`) 배포는 **PC 쪽에 없다**(C2는 `"*"`를 서버 배포에만 주고 `DeploymentTarget.matches`·V6도 그렇다). 그래서 PC 배포는 전부 `bot_ui_id` 하나를 가리키고 「배포된 Bot UI」는 **`target.id`를 겹치지 않게 센 수**다. 재료는 CON-02가 이미 받아 둔 둘(C5 배포 목록·Bot UI 목록)로 끝났고 **계약이 늘지 않았다**. 함께 고친 것 둘: Center 네 자리가 대상 종류를 가리지 않고 `"*"`를 풀던 것(이제 한 함수가 짓고 `POST /deployments`는 409 `wrong_target`), 그리고 `summarize`가 **제가 세지 않은 칸**(`blocked`·`deployments`)을 0으로 들고 돌아와 실제 값을 덮던 것(끝난 실행이 있는 판은 「실행 불가」가 늘 0이었다).

- **콘솔 집계 함수에 단위 시험이 없다:** 성공률·재생률·확인률·표본을 세는 것은 TypeScript(`summarize`)이고 **`web`에 시험 판이 없다** — 지금은 `pnpm typecheck`·`pnpm build`와, 재료가 오는지 보는 파이썬 시험(`tests/test_console_bot_status.py`)까지다. 셈이 틀려도 잡히지 않는다. **덮어쓰기 흠을 겪은 뒤로** 그 묶음이 **글로도** 본다(열 이름, `RunFields`가 있는가, `Omit<BotRow`로 돌려주지 않는가, `*`를 푸는 코드가 없는가) — 셈을 재지는 못하고 **같은 흠이 다시 들어오는 것만** 막는다. **먼저 정할 것:** 웹에 시험 판(예: vitest)을 들일지 — 들이면 CI에 한 걸음이 늘고, 들이지 않으면 콘솔의 계산은 계속 눈으로 본다. **2026-10-11에 「들이지 않는다」로 한 번 정했다** (사람이 고른 것이고, 뒤집을 수 있다).

## 5. 공백은 아니지만 적어 둘 것

- **C3 `run_waiting`·`run_resumed`는 내보내는 쪽이 없다** — 공백이 아니다. C3가 「서버만 쓴다」고 적어 두었다 (PC Bot은 실행 자리를 쥐고 있어 `node_state: waiting`만 남긴다). M7 몫이다. (§3-3이 닫히면서 이 줄이 여기로 왔다.)
- **쓰지 않는 편의 접근자 셋** — `ExtensionHost.studio_editors()`(호출자 **아예 없음**, Studio는 단수 `editor(task_type)`를 쓴다), `adapter_operations()`(`AdapterCaller`가 `definitions`를 직접 본다), `secret_config_keys()`(`credentials.py`가 `configuration()`을 제 손으로 거른다). 기능 공백이 아니다 — **지울지 쓸지만 정하면 된다.**
- `extension_api`의 `HOST_SERVER_RUNNER`·`RUN_LOCATION_SERVER`는 M7이 쓸 상수다 (지금 호출자 없음, 정상).
- `SEVERITY_INFO`는 아무도 쓰지 않는다 (`SEVERITY_BLOCK`·`SEVERITY_WARN`만 쓴다).
- **C1의 「아는 값」 중 둘은 아직 호출자가 없다** — `KNOWN_SETTINGS`·`KNOWN_BUILT_BY`. `KNOWN_TRIGGER_KINDS`는 **쓰는 쪽을 만들었고**(R9, 2026-10-12 — 아무도 검사하지 않는 동안 Studio가 `schedule`·`manual`을 올려 **올라간 모든 패키지의 `triggers`가 계약에 없는 값을 담고 있었다**), `KNOWN_DOMAINS`는 C14 **B8**이 그림에서 쓴다. 남은 둘을 같이 묶지 않은 까닭은 **막는 것이 틀려서**다 — `built.by`는 우리가 모르는 빌더가 적을 수 있어 **열린 문자열이 맞다**(막으면 남의 도구로 만든 올바른 패키지를 거부한다), `settings`는 아직 읽는 쪽이 없다.
- **도메인 목록의 정의는 `manifest.py` 하나다** — `KNOWN_DOMAINS`·`PC_ONLY_DOMAINS`를 `bpmn_ext`(C14 B8·B6)와 `core`(사전 점검·AI 태스크)가 import해 쓴다. 자리가 C1 쪽인 것은 층 때문이다 (`bpmn_ext`가 `manifest`를 import하므로 거꾸로는 순환이다). **두 벌로 되돌리지 않는다** — 값이 같고 거르는 자리만 다른 목록이 둘이면 조용히 갈라진다(`triggers[].kind`가 그랬다). `tests/test_contracts_bpmn_ext.py`가 **같은 객체인지**(`is`) 본다.
- C13 `docs_url`·`owners`, C11 `Operation.json_schema`는 콘솔이 보이지 않는 선택 칸이다. 작고 급하지 않다.

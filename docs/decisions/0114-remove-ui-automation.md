# ADR-0114. UI 자동화 확장과 그것만 쓰던 플랫폼 장치를 걷는다 — 나중에 다시 정리해 들인다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-31 |
| 관련 | 계약 C1·C3·C4·C5·C7·C11·C13·C14·C15 (C8·C9·C10은 지웠다), [ADR-0018](0018-extensions.md), [ADR-0024](0024-desktop-packaging-extensions.md), [ADR-0042](0042-extension-contributed-panels.md), [ADR-0062](0062-pc-delegation.md), [ADR-0064](0064-extension-tasks-on-the-server.md), [ADR-0077](0077-tool-ui.md), [ADR-0102](0102-calling-outside-is-pull.md) |

## 배경

유일한 내장 확장 「UI 자동화」(Worker·서비스 앱·클라이언트·C8~C10)는 플랫폼에 기여 지점과 장치를 여럿 붙여 두었다 —
PC 실행기의 로컬 런타임 감독·실행 예약, Tool UI, `bot_ui.panels`, `agent_environments`(웹·데스크톱 AI 태스크), Center의
셀렉터 등록 스위치, C3 `ui_session`. 바깥 시연 앱(NowView)과의 연동을 새로 시험하려고 로컬 Center를 비우는 중에 compose가
띄운 UI 자동화 앱이 일꾼 승인을 청했고, 사용자는 **이 확장을 통째로 걷고 나중에 다시 정리해 들이기로** 했다. 반쯤 남기면
쓰이지 않는 장치가 계약·화면·시험에 남아 「있는데 안 돈다」가 된다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 확장 폴더만 지운다 | 손이 적다 | Tool UI·로컬 런타임·셀렉터 등록·`ui_session`이 **그리는 것 없이** 남는다. 계약이 「구현됨」인데 쓰는 쪽이 없다 |
| B. **확장과 그것만 쓰던 장치를 함께 걷는다** — 다른 쓰는 곳이 있는 일반 장치(확장 호스트·`chk:task`·`TaskOutcome.events`·호출 토큰·`console.pages`·`storage.dir`)는 남긴다 | 계약·화면·코드가 같은 것을 말한다. 다시 들일 때 **필요한 것만** 골라 정리할 수 있다 | 손이 많다. 「확장 구조가 실제로 돈다」를 보이던 유일한 확장이 사라진다 |
| C. 확장을 꺼 둔 채로 둔다 | 되살리기 쉽다 | 끄는 자리(BUI-11·STU-15)가 사람의 것이라 배포 묶음에는 그대로 들어간다. compose의 앱도 남는다 |

## 결정

**B다.** 걷은 것과 그 자리는 이렇다.

1. **확장 자체** — `extensions/ui_automation/` 전부, 엔트리 포인트, 워크스페이스 멤버(`extensions/*`는 멤버 목록에서
   뺐다 — 확장을 들일 때 다시 더한다), 계약 C8·C9·C10, 서비스 앱 콘솔의 UIA-01~03, compose의 `svc-uia`·`svc-console`
   (`svc-console`이 가리킬 다른 앱이 없다), `Dockerfile.svc-uia`.
2. **그것만 쓰던 플랫폼 장치**
   - `apps/tool_ui` 전체(TOL-01~05)와 `--tool-ui` 깃발·설치 파일의 Tool UI 바로가기.
   - PC 실행기의 로컬 런타임 감독·실행 예약(`runtimes.py`·`tool_launch.py`), BUI-03 「로컬 런타임」 탭, BUI-09, 「도구」의
     바로가기, BUI-05의 런타임 알림, `--local-runtime`·`--start-runtimes`. 호출 토큰을 비밀 저장소에 두던 것(Tool UI 몫)도
     걷었다 — 메모리에만 든다.
   - C4 하트비트 `worker`·`versions.worker`·상태 `selector_registration`, C5 `BotUiInfo.worker`·`selector_registration`과
     CON-03의 그 칸, `PUT /bot-uis/{id}/utility`, C15의 `reg_` 등록 세션. 저장소 열은 `migrations.py` **18판**이
     지운다(`storage.SCHEMA`는 얼어 있다). C11 `required_scopes`를 적은 작업은 **줄 길이 없어** 아무도 올리지 못한다.
   - C3 `ui_session`과 `run_finished.ui_tasks`, CON-01·STU-09의 「UI 태스크」, `status_map`의 「Worker 프로세스」·「UI 세션」.
   - C13 기여 지점 `tool_ui.tools`·`bot_ui.panels`·`bot_ui.local_runtimes`·`agent_environments`, E8, 예약 키 `runtime.<id>.*`,
     `scope: tool_ui`, `requires_keys[].purpose: utility`. 정의에 적혀 있으면 호스트가 **경고 한 줄**을 남기고 읽지 않는다
     (모르는 열쇠라고 조용히 사라지지 않게, `LEGACY_CONTRIBUTION_KEYS`). E7은 `runtime.` 머리를 계속 막는다.
   - `extension_api` **2.0.0** — `ToolUiTool`·`BotUiUtility`·`BotUiPanel`·`LocalRuntimeEntry`·`AgentEnvironment`·
     `AgentSession`·`AgentTool`·`HOST_TOOL_UI`를 지웠다(이름을 지우면 주 번호다).
3. **`web`·`desktop` AI 태스크는 낱말로 남고 돌지 않는다** — C14·C1의 domain 값은 그대로다(다시 들일 때 그림을 고치지
   않게). 엔진은 그 태스크를 만나면 **그림·설치 오류**(`node_kind_unsupported`)로 멈추고, 사전 점검이 **시작 전에**
   `missing_agent_environment`로 막는다(이제 확장을 묻지 않는다 — 줄 확장이 없다). Studio 편집기는 고를 수는 있지만
   「이 판에서 돌릴 수 없다」고 말한다.
4. **업무 예제 7개를 지웠다** — BX-04·BX-14·BX-17·BX-36·FX-05·FX-15·FX-16 (UI 태스크·웹/데스크톱 AI 태스크). BX-16의 PC
   위임 대상은 BX-17 대신 **FX-19**(수동 확인 PC)이고 FX-19가 `확인됨`을 `outputs`로 선언한다 — 위임의 모양(맡기기·결과
   받기·오류 경계)은 그대로 예제가 밟는다. M4 인수 묶음은 비어 생성기에서 뺐다.
5. **「확장이 빠지면 빌드 실패」 시험은 걷는다** — 묶을 확장이 없다. `--selftest`는 `--want`가 없으면 **확장 0개를 정상**으로
   보고(읽지 못한 정의·켜지지 않은 확장은 여전히 실패), 빌드 워크플로는 `--want`를 넘기지 않는다. 확장 호스트의 규칙은
   시험용 가짜 확장(`tests/fake_extension.py`)으로 본다 — 설치 파일에는 들어가지 않는다.

## 결과

- 쉬워지는 것: 로컬 Center·현장 PC가 쓰지 않는 앱·창·포트를 띄우지 않는다. 계약 열둘이 쓰는 쪽과 함께 맞는다.
- 어려워지거나 포기하는 것: 화면 조작 자동화가 **없다**. PC BPM 프로세스로 할 수 있는 것은 현장 확인·파일·서비스 앱
  호출이다. 엔트리 포인트·PyInstaller 훅·`--selftest`가 **진짜 확장으로** 도는지는 확장을 다시 들일 때까지 아무도 보지
  않는다. 걷은 장치의 결정(아래 대체된 ADR)은 본문이 그대로 남아 다시 들일 때 출발점이 된다.
- 다시 볼 조건: UI 자동화(또는 다른 내장 확장)를 다시 들일 때 — 그때 기여 지점·장치를 **필요한 것만** 새 ADR로 정하고,
  `extensions/*` 멤버·`--want`·빌드 검사 시험을 함께 되살린다.
- 대체한 것: [ADR-0020](0020-windows-desktop-backend.md)·[0021](0021-worker-dpi-capture.md)·[0033](0033-desktop-app-and-window.md)·
  [0035](0035-ui-goal-planning.md)·[0036](0036-screen-read-values.md)·[0037](0037-desktop-ai-task-environment.md)·
  [0040](0040-registry-storage-sqlite.md)·[0072](0072-desktop-pick-without-hooks.md)·[0074](0074-ui-task-editor-runs-on-the-worker.md)·
  [0077](0077-tool-ui.md) 전부, 그리고 [0012](0012-bot-ui.md)·[0014](0014-one-bot-per-pc.md)·[0018](0018-extensions.md)·
  [0023](0023-bot-ui-process-supervision.md)·[0024](0024-desktop-packaging-extensions.md)·[0042](0042-extension-contributed-panels.md)·
  [0064](0064-extension-tasks-on-the-server.md)·[0112](0112-escalation-review-from-extensions.md)의 해당 부분.

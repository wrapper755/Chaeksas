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

**2026-10-31에 한 번 더 대조했다** (main `dacdc3b`) — §3과 로드맵의 코드 항목이 다 비었는데, 지난번 §3-20(타이머 시작을 깨우는 자리)이 목록에 없다가 코드를 대조하다 나왔기 때문이다. 계약 열다섯은 칸·상태값·트리거마다 **쓰는 쪽과 읽는 쪽**을 `git grep`으로 세었고(`tests/`와 계약 모듈은 뺐다), 화면 문서는 라벨 글을 코드에서 찾았고, 업무 예제는 55개의 `bpm:*`를 모두 읽어 쓰인 키를 셌다. 새로 찾은 것은 §3-21~27·§8·§9이고, 대조하다 찾은 **낡은 줄은 그 자리에서 고쳤다**(§2).

## 1. 계약 문서 상태

| 계약 | 문서 머리말 | 코드 | 「구현됨」까지 남은 것 |
| --- | --- | --- | --- |
| C1 | **구현됨** | `contracts.manifest` R1~R8 (R8은 Center 배포가 짓는다) | — (닫았다 — Studio가 `Provides`를 짓고 CON-06이 읽는다). — (닫았다). `definition_hash`는 **STU-15에서 사람이 고정한다**([ADR-0060](decisions/0060-pinning-external-definitions.md) — 고정하지 않으면 경고만 한다), `requires.settings`는 Studio가 그림에서 채운다 (`bpm:email` → `smtp`, [ADR-0059](decisions/0059-sending-mail-and-webhooks.md)) |
| C2 | **구현됨** | `contracts.hashing`·`signing` V1~V8 | — (닫았다) |
| C3 | **구현됨** | `contracts.events`·`core.run_log` | — (닫았다: 확장이 남기는 줄은 [ADR-0041](decisions/0041-extension-run-events.md), `case_id`·`queued_s`는 아는 쪽이 넣는다, `confirmations`는 **세는 쪽**이 가르고 `bot_ui_id`는 **Center가 읽을 때** 채운다) |
| C4 | **구현됨** | `contracts.bot_ui`, Center·PC 실행기 양쪽 | — (`key_expires_at`으로 BUI-05 Center API 키 만료를 닫았다). `runtimes.browsers`·`desktop_backend`는 채우는 쪽이 없다 — §3-28 |
| C5 | **구현됨** | `contracts.center_api`, Center 전부 | — (닫았다 — 지원 종료·참조·삭제, 그리고 **권한표**까지. 패키지 쪽은 키 종류를 보는 관문이 따로 있다: `auth.require_upload`·`require_package_read`·`api.package_access.guard_download`) |
| C6 | **구현됨** | `contracts.approvals`, Center·현장 | — (닫았다) |
| C7 | **구현됨** | `contracts.resources`·`center_keys` | — (닫았다 — 상태는 토픽에서 온다, C15). `requires.resources`를 짓는 쪽이 없어 `used_by`가 빈다 — §3-24 |
| C11 | **구현됨** | `contracts.service_app`·`service_kit`(`service_kit.consumer` — 일꾼) | — (닫았다) |
| C12 | **구현됨** (M7) | `contracts.server_runner`·`core.run_snapshot` + **양쪽** — 등록·하트비트·운영 API·배포 설치·작업 실행·저장·재개·결재·**메시지**가 돈다 | — (닫았다). 「기한은 간다」는 [ADR-0061](decisions/0061-waking-runs-whose-timer-is-due.md)이 코드로도 사실로 만들었다 (주기만큼 늦을 수 있다고 C12에 적었다). **PC 위임도 본문이 되어 양쪽이 돈다** ([ADR-0062](decisions/0062-pc-delegation.md) — §3-13). 담고 되살리는 모양은 [ADR-0054](decisions/0054-server-run-state-and-concurrency.md)가 정했고, **재시작을 건너 메시지가 두 번 들어가던 자리**는 [ADR-0058](decisions/0058-absorbed-messages-travel-with-the-snapshot.md)이 닫았다 (ADR-0056이 「재 보지 않았다」고 적어 둔 것 — 재 보니 정말 두 번이었다) |
| C13 | **구현됨** | `contracts.extension`·`core.extensions` | — (닫았다 — 기여 지점마다 읽는 쪽이 있다: 호스트·Studio·PC 실행기·콘솔·Center) |
| C14 | **구현됨** | `contracts.bpmn_ext` B1~B16 + `contracts.dmn` | — (닫았다 — 엔진이 수행하고 Studio가 편집·검사하고 예제 48개가 이 형식이다. schema 1에서 **쓰지 않기로 적은 것**은 범위 결정이다) |
| C15 | **구현됨** | `contracts.external_task`, Center `api/external_tasks.py` (15판) + **양쪽** — 부르는 쪽 `core.services.CenterServiceCaller`, 일꾼 `service_kit.consumer`·`apps/adapter_consumer` | — (조각 2~4가 닫았고 긴 작업은 [ADR-0103](decisions/0103-long-external-tasks.md)이 닫았다, §3-17) |

**열둘이 모두 「구현됨」이다** (C12가 M7 다섯째 조각에서, C15가 ADR-0102 조각 4에서 올라왔다). C8·C9·C10은 UI 자동화 확장과 함께 지웠다 ([ADR-0114](decisions/0114-remove-ui-automation.md) — §3-28). 상태 셋의 뜻은 [03-contracts/README](03-contracts/README.md) §상태에 적었다 — 적혀 있지 않아 올릴 때마다 사람이 다시 물었다.

## 2. 문서가 코드와 어긋난 자리 (코드를 고치는 일이 아니다)

**2026-10-31 대조에서 찾은 것은 그 자리에서 고쳤다** — ADR-0090 뒤에 남은 「Admin」 글(C1 패키지 구성·C4 `admin_keys`·C12 §설치·BUI-11·계약 README의 C2·C5 줄), 계약 README의 C12 「(제안)」·C14 「B1~B14」, C5 `server_runner_not_available`의 「M7까지」, C14 `DELEGATION_FAILED`의 「(예약)」, ADR-0102 뒤에 남은 것(C7 머리말의 어댑터 `health`·`ToolpackResource`·내지 않는 오류 코드 넷, C13 상태 줄·`allowed_hosts`의 「Center의 `base_url`」·`health` 칸), C15·C11의 「`service_kit`이 잠금을 늘린다」(늘리지 않는다), CON-04 상태 줄의 「현장에서 올라오는 결재가 없다」, UIA·Worker 화면 문서의 코드 경로, 화면 README의 WRK 대응, STU-04 스크립트의 「Python」, STU-05의 「서버 실행은 M7부터」, 업무 예제 README의 「실행 — 아직 없음」과 닫힌 공백 넷. **코드가 문서와 다르고 문서가 맞는 것**은 고치지 않고 §3·§8에 적었다(§3-22가 그 꼴이었다 — 닫았다).

그 전의 마지막 하나(§2-5 — C3 `run_started.bpm_process_id`가 패키지 id인가 그림의 process id인가)는 패키지 id로 정해 엔진·계약을 맞췄다 ([ADR-0086](decisions/0086-run-identity-is-the-package-id.md)).

## 3. 계약 쪽 기능 공백

계약 열둘의 상태는 §1 표에 있다. PC 위임을 닫았고(§3-13) 그 거리가 드러낸 「도는 서버 실행을 멈출 길이 없다」도 [ADR-0063](decisions/0063-stopping-a-running-server-run.md)으로, 「서버 실행기가 확장 태스크를 꽂지 않는다」(§3-14)도 [ADR-0064](decisions/0064-extension-tasks-on-the-server.md)로 닫았다. 일괄 기동이 드러낸 「서버의 병렬 반복」(§3-15)도 [ADR-0087](decisions/0087-parallel-loop-on-the-server.md)로 닫았다. 바깥 요청(NowView R4)이 드러낸 「외부 확장 주소의 입구」(§3-16)도 [ADR-0097](decisions/0097-external-extension-address-from-center.md)로 닫았다. C15(외부 작업, §3-17)도 조각 1~6과 옛 키 칸 걷기로 닫았다. AI 태스크의 거짓 칸을 정리하다(ADR-0105) 드러난 「PC 전환 → 사람 확인」(§3-18)도 [ADR-0106](decisions/0106-pc-escalation-asks-a-person.md)으로 닫았다. 그 길을 닫다 드러난 「어댑터의 결과 모름」(§3-19)도 [ADR-0107](decisions/0107-outcome-unknown-asks-a-person.md)로 닫았다. 다음 거리를 코드와 대조하다 드러난 「타이머 시작을 깨우는 자리」(§3-20)도 [ADR-0110](decisions/0110-center-keeps-the-schedule.md)으로 닫았다. 그 뒤 2026-10-31 대조가 **새로 일곱**(§3-21~27)을 찾았다 — 넷(§3-21~24)은 업무에 닿고, §3-25는 엔진의 흠, §3-26·27은 작은 칸과 「미정」 모음이다. 그중 배포의 끝 둘(§3-22·23)은 [ADR-0113](decisions/0113-field-follows-withdrawn-deployments.md)으로 닫았다. UI 자동화 확장을 걷으며(ADR-0114) 다시 들일 때 정할 것을 §3-28에 모았다.

### 3-29. 조직·업무 자리 — Center·Studio·승인 화면은 돈다, 조직 화면이 아직

[ADR-0125](decisions/0125-organization-and-work-placement.md)·[ADR-0127](decisions/0127-studio-picks-the-work-place.md), 계약 [C16](03-contracts/C16-organization.md) 「합의」. 도는 것: 조직 API, 장비의 회사(등록 승인), 올릴 때 업무 자리 검사(매니페스트 `place`), PC 배포의 회사 관문, 작업의 주인·`owner_stopped`·서버 작업의 `place`, 회사 관리자 거르기, STU-12b 자리 고르기, 콘솔 승인 창·등록 승인·계정의 회사. 가상 직원은 없앴다. **남은 것**: ① 조직 화면 CON-13(나무 + 상세 — 화면 문서에 있다, 지금은 API로 만든다) ② CON-01의 회사·부서·직원 열 ③ PC 작업에 `place` 나르기(> 미정 — C4 실행기 파일) ④ 연동용·대리 답용 키의 회사(> 미정) ⑤ 직원 사이의 업무 요청 ADR(ADR-0125 §8 — 조직이 선 뒤).

### 3-21. PC BPM 프로세스로 메시지를 넣는 길이 없다

**무엇이 없나.** C12 「C4와 다른 점」 표는 PC 쪽 메시지를 「PC 실행기 메시지 수신(8790)」으로 적었고, C14 §이벤트도 「PC는 PC 실행기 메시지 수신」이라고 적었으며, ADR-0014 §1도 메시지 수신을 PC 실행기 대기열의 출처로 든다. 그런데 **받는 쪽이 아무 데도 없다.** 그래서 실행 위치가 `pc`인 그림의 받기 태스크·메시지 중간 받기·경계는 영원히 기다리고(타이머 경계가 없으면), 메시지 시작 트리거는 울리지 않는다. 그림 검사도 이것을 말하지 않는다 — B6은 반대쪽(서버에서 못 하는 것)만 본다.

**근거.**
- Center `api/messages.py`는 **서버 실행기만** 고른다 — 기다리는 실행은 `server_runners` 행에서 찾고(:145), 메시지 시작은 `target: {"type": "server_runner"}`로 작업을 만든다(:220). C4 하트비트 응답에는 `messages[]`가 없다.
- PC 실행기에는 설정 칸만 있다 — `bot_ui/settings.py:23` `DEFAULT_WEBHOOK_PORT = 8790`·`webhook_port`를 읽는 곳이 없고, BUI-03 「나중에」 탭이 「메시지 수신 포트 — … M5」를 꺼 둔 채 보인다(`settings_dialog.py:502-512`).
- `contracts.bpmn_ext.server_blockers`(:1304)는 서버의 막힘만 센다. PC에서 메시지를 받는 그림을 막는 검사는 없다.
- 업무 예제 중 메시지를 받는 16개는 **모두** `run_location: server`라 예제가 이 길을 밟지 않는다.

**먼저 정할 것.** 「PC도 Center를 거쳐 받는다」(C12 §메시지와 같은 길 — C4 하트비트 응답에 `messages[]`·ack, PC 실행기 → 제어 파일 → 실행 프로세스. 8790과 「나중에」 탭은 걷는다)인가, 「PC 그림은 메시지를 받지 않는다」(B 검사로 막고 C12·C14·ADR-0014의 줄을 걷는다)인가. ADR-0102(바깥에서 들어오는 길은 Center)와 ADR-0007(밀지 않는다)은 첫째 쪽을 가리킨다.

### 3-22. 지원 종료가 돌던 배포를 멈춘다 — 닫았다

**닫았다** ([ADR-0113](decisions/0113-field-follows-withdrawn-deployments.md) §8). Center가 활성 배포를 고르는 자리(하트비트 봉투·작업의 판·PC 위임·일정·메시지 시작·내려받기)가 모두 `approved`만 받아 「지원 종료...」가 돌던 판을 세웠다. 조건을 `deployments.live_sql` 하나로 모았고(철회되지 않음 + 패키지가 `approved`·`deprecated`, 상태 묶음은 `signing.LIVE_STATUSES`) 새 배포·승인 관문만 `approved` 하나다. 시험: `test_m5_deploy.py`의 `test_a_deprecated_package_keeps_running_where_it_is_deployed`·`test_a_deprecated_package_stays_on_in_the_field`, `test_center_timers.py`의 `test_a_deprecated_package_keeps_its_schedule`.

### 3-23. 승인·배포가 철회돼도 현장이 그 BPM 프로세스를 끄지 않는다 — 닫았다

**닫았다** ([ADR-0113](decisions/0113-field-follows-withdrawn-deployments.md)). 현장은 **Center가 답한** 하트비트의 `deployments`로 설치를 맞춘다(`Deployer.reconcile` — 닿지 못한 주기에는 바꾸지 않는다, 빈 목록도 목록이다). 「Center 배포」 설치마다 지금 덮는 봉투(V1~V6)를 폴더의 `DEPLOYMENT` 표식에 적고, 없으면 `withdrawn_at`을 적는다 — 버린 서명 키(V2)도 같은 길이다. 사전 점검 `deployment_withdrawn`·`deployment_expired`(기한은 표식으로 현장 시각에, 캐시하지 않는다)가 대기열·BUI-04 「지금 실행...」(넣을 때 거절)·`readiness`·서버 작업(`not_ready`)을 함께 막는다. BUI-04 「준비」에 「배포 철회」·「배포 만료」, BUI-05에 「배포가 철회되어 실행할 수 없습니다」(한 번). 파일은 지우지 않고 도는·기다리는 실행은 건드리지 않는다(세우는 것은 작업 취소 — ADR-0063). 「수동 설치」·「알 수 없음」 출처는 다루지 않는다.

### 3-24. `requires.resources`를 짓는 쪽이 없다

**무엇이 없나.** C1 `requires.resources`(BPM 프로세스가 쓰는 확장 기여 자원)를 **세 곳이 읽는데 쓰는 곳이 없다.** 그래서 C7 기여 자원의 `used_by`가 늘 비고(CON-07 「쓰는 BPM 프로세스」 열), C7 누락 검사의 `resource/not_found`가 울리지 않는다.

**근거.** 읽는 쪽 — Center `api/packages.py:207`(`missing`)·`api/deployments.py:277`(`blocking_at_deploy`)·`api/resources.py`(`used_by`). 쓰는 쪽 — Studio `packaging.py:160-169`의 `Requires(...)`에 `resources`가 없고, `ResourceRef`를 만드는 코드가 계약 패키지 밖에 없다.

**먼저 정할 것.** 그림의 어디서 자원 id를 모으나. 후보는 확장이 선언한 칸(`creates_task_field` — STU-03 「캔버스에 추가」가 자원 id를 넣는 자리, ADR-0045)이다. 그 칸을 읽으면 플랫폼이 확장의 `data`를 해석하지 않고도(C13 §5) 모을 수 있다.

### 3-25. 종료(terminate) 끝 이벤트를 엔진이 일반 끝으로 돈다

**무엇이 없나.** BX-11(`bx11_bid_collection.bpmn:173`)이 `terminateEventDefinition`을 쓰고 커버리지 표가 「끝 — 종료(terminate) | BX-11」로 센다. 그런데 엔진의 `handle_end`(`core/nodes.py:108-118`)는 그 토큰만 지운다 — **다른 가지의 토큰이 살아 있으면 실행이 끝나지 않는다.** `packages/core`·`packages/contracts`에 `terminat`가 없고(OS 프로세스 끄기뿐) C14 §이벤트에도 이 요소가 없다. 「모르는 노드는 실패」 규칙도 못 잡는다(요소가 `endEvent`라서다). 시험이 없다.

**먼저 정할 것.** 엔진이 짓나(남은 토큰·기다림을 걷고 `success`로 끝낸다 — 경계·위임·외부 작업을 걷는 길은 취소가 이미 갖고 있다), 아니면 C14 schema 1에서 쓰지 않기로 하고 B 검사로 막나. BX-11은 그림에 가지가 하나라 지금도 결과가 같다.

### 3-26. 싣기만 하고 아무도 읽지 않는 칸 · 읽는데 아무도 싣지 않는 칸

하나하나는 작고 업무를 막지 않는다. 다만 §3-20이 바로 이 꼴이었다 — 「칸이 있다」가 「돈다」로 읽힌다. 고르는 사람이 「짓는다 / 걷는다 / 둔다(까닭을 적는다)」를 칸마다 정한다.

| 칸 | 쓰는 쪽 | 읽는 쪽 | 비고 |
| --- | --- | --- | --- |
| C1 `triggers[kind=signal]`·`[kind=conditional]` | Studio `packaging.py:258-260` | 없음 | 신호는 「한 실행 안의 가지 사이에서만」(C14)이라 시작을 울릴 수 없고, 조건 시작은 schema 1에서 쓰지 않는다(C14). Studio 이벤트 편집기는 신호 시작에 경고하지만(`event_editor.py` `SIGNAL_START`) **그림 검사(B)는 둘 다 말하지 않는다** |
| C1 `requires.core`·`runtimes`·`os` | 없음 | CON-06 표시뿐(`packages/[packageId]/[version]/page.tsx:33-42`) | C1은 「설치 전 사전 점검에 쓴다」고 적었지만 `core/preflight.py`는 `settings`·`domains`만 본다 |
| C1 `preflight.json`·C5 `PackageInfo.preflight` | 없음 — Studio zip은 `process`·`memory`·`libs`만(`packaging.py:42`), Center도 채우지 않는다 | 없음 | 걷거나 짓는다 |
| C3 `source: message`·`watch` | 없음 — 메시지 시작 작업도 `job_source()`가 `job`으로 적는다(`contracts/center_api.py:114-125`, `requested_by`가 부른 쪽 이름이다) | PC 실행기 표기(`main_window.py:131-132`) | 메시지로 시작한 실행을 CON-01이 가를 수 없다. `watch`는 감시 모드가 아무 데도 없다(§8 BUI-01) |
| C3 `llm_usage` | 엔진(`core/agent.py`·`nodes.py`) | 없음 | ADR-0027은 「Center가 가격표로 계산」이라 적었다. Center·콘솔에 읽는 곳이 없다. C3 `service_call`·`mode_used`도 CON-01이 그리지 않는다(`runs/[runId]/page.tsx:167-171`) |
| C3 `kind: data`(`data.vars`, 켠 경우에만) | 없음, 켜는 설정도 없다 | 없음 | |
| C3 `run_started.queued_s` | PC 실행기·서버 실행기 | Center·콘솔에 없음 | 표시만의 칸 — CON-01이 보이지 않는다 |
| C4 `runtimes.browsers`·`desktop_backend` | 없음 | Center C7 `RuntimeResource`(`api/resources.py` `runtimes()`), CON-03 「런타임」 열(`bot-uis/page.tsx`) | 읽는데 싣지 않는다 — 실을 쪽(UI 자동화)을 걷었다. §3-28 |
| C11 사용 기록 `delivery` (SVC-03 열), C15 `LockedTask.delivery` | Center | 없음 — `UsageRecord`(`contracts/service_app.py:151-163`)에 칸이 없다 | C11 문서가 그 열을 약속한다 |
| C12 하트비트 `restored[]` | 서버 실행기 첫 하트비트(`agent.py:337`) | 없음 — Center가 `state_json`에 담고(`api/server_runner.py:210`) 다음 하트비트가 덮는다 | CON-12가 「재시작 때 되살린 실행」을 보일 재료다 |
| C12 `status: draining`·`error` | 없음 — `running`·`paused`만(`agent.py:1138`, `STATUS_ERROR`는 정의뿐) | 콘솔 표기(`lib/summary.ts:173`) | SIGTERM에도 `draining`을 보내지 않는다 |
| C13 `adapter.health` | 확장 정의 | 없음 (ADR-0102로 Center가 두드리지 않는다. Center 저장소에 `extension_health` 표의 `CREATE`가 1판 기준선에 남았다 — `storage.py:218`, 16판이 지운다) | 문서는 고쳤다(C13 §4-1) |
| C15 `POST …/consumers/tasks/{id}/extend` | — | 부르는 일꾼 없음 | 문서는 고쳤다(C15·C11 — `service_kit`은 늘리지 않는다) |
| `contracts.bpmn_ext.ERROR_CODES` | — | 없음 — Studio는 제 목록(`event_editor.py:55`)을 쓴다 | 계약 쪽 목록은 결재 코드 둘이 빠진 채 낡았다. 두 벌을 하나로 |

### 3-27. 「미정」으로 적혀 있는데 이 목록에 없던 것

- **PC 작업에 작업의 주인이 가지 않는다** — C14 §입력의 값 출처, C4 `JobDispatch.place`(C16). PC 실행기는 그 칸을 읽지 않아, PC BPM 프로세스가 `company.*`·`department.*`·`staff.*` 출처 입력을 필수로 선언하면 시작하지 못한다. 먼저 정할 것: C4 실행기 파일에 싣는 길 하나다(Center가 `place`를 붙이는 조각 2 뒤의 일).
- **CON-07 「할 일」을 확장 정의에서 짓기** — `06-screens/center-console.md` CON-07 「> 미정」: Center가 내장·사내 확장의 정의를 갖지 않는다. 먼저 정할 것: C13 정의를 Center로 올리나.

### 3-28. UI 자동화 확장을 다시 들인다

**무엇이 없나.** 화면 조작이 없다 — UI 자동화 확장(서비스 앱·Worker 프로세스·UI 태스크·셀렉터 등록)과 그것만 쓰던
장치(Tool UI, PC 실행기의 로컬 런타임 감독·예약, C8~C10, C3 `ui_session`, 기여 지점 `tool_ui.tools`·`bot_ui.panels`·
`bot_ui.local_runtimes`·`agent_environments`)를 걷었다 ([ADR-0114](decisions/0114-remove-ui-automation.md)). 다시 들인다.
그때까지 `web`·`desktop` AI 태스크는 낱말로만 남아(C14·C1 domain) 사전 점검이 `missing_agent_environment`로 시작 전에
막고, 시나리오 3(M6 첫째)은 멈춰 있다.

**쓰는 쪽 없이 남은 칸.** 걷지 않고 둔 것이다 — 다시 들일 때 쓸지 걷을지 정한다.
- C4 `runtimes.browsers`·`desktop_backend` — 싣는 쪽이 없다. Center는 C7 `RuntimeResource`로 읽고 CON-03 「런타임」 열이 그리므로 늘 빈다(§3-26).
- C7 런타임 자원(`type: runtime`) — 위 칸에서 짓는 것이라 함께 빈다.

**먼저 정할 것.** 기여 지점·장치 중 **무엇을 다시 들이나** — 로컬 런타임(띄우기·예약)·도구 창·패널·AI 환경을 하나씩 새
ADR로 고른다. 그때 `extensions/*` 워크스페이스 멤버·`--selftest --want`·「확장이 빠지면 빌드 실패」 시험을 함께 되살린다
(ADR-0114 「다시 볼 조건」).

### 3-20. 타이머 시작을 깨우는 자리 — **닫았다**

[ADR-0110](decisions/0110-center-keeps-the-schedule.md). 시작 타이머는 C1 `triggers[]`에 실리기만 하고 **그 일정으로 BPM 프로세스를
시작하는 쪽이 아무 데도 없었다**(C14는 「서버 실행기·PC 실행기의 일정이 읽는다」고 적었는데 둘 다 그 코드가 없었다) — 타이머로
시작하는 업무 예제 열(BX-01·02·04·05·07·08·14·16·23·35)이 현장에서 작업 지시 없이는 돌지 않았다. 09-gaps에는 §3이 아니라
§4-5의 「감시 모드」와 7-11에 지나가는 말로만 있었다. **Center가 쥔다** — 하트비트를 받을 때 분마다 한 번 배포된 매니페스트의
타이머를 쓸어 `POST /jobs`와 같은 함수로 작업을 만든다(`center/api/timers.py`, 저장소 17판 `timer_fires`·`timer_sweeps`).
놓친 차례는 가장 최근 한 번, 배포 전 차례는 없다, `expires_at`은 다음 차례, 차례는 기본 키로 먼저 잡고 멱등 키도 일정·차례로
짓는다. 식은 `contracts.schedule` 하나이고 **C1 R13**이 올릴 때, Studio 이벤트 편집기가 고칠 때 같은 함수로 본다. 일정이 만든
작업은 `requested_by` `timer:<식>`이고 PC 실행기·서버 실행기가 실행 기록의 `source`를 **`schedule`**로 적는다(`job_source`).
BX-23이 작업 지시 없이 서버 실행기에서 끝까지 도는 것을 `tests/test_m7_server_rerun.py`가 본다. 콘솔은 CON-02 「일정」(C5 `GET /schedules` — 다음 차례·마지막
차례·놓친 차례·만들지 못한 코드)이 보이고, 같은 묶음에서 CON-01 「외부 작업」(C15 `GET /external-tasks?run_id=` — 일감이
기다리는지·일꾼이 쥐었는지·다시 나갔는지)도 더했다. 남겨 둔 것: BPM 프로세스마다 다른 시간대(ADR-0110 「다시 볼 조건」).

### 3-19. 어댑터의 결과 모름 → PC는 확인 — **닫았다**

[ADR-0107](decisions/0107-outcome-unknown-asks-a-person.md). C15 `fail`·결과 `error`에 **`outcome_unknown`** 칸 하나를
더했다(`retryable`과 함께 참일 수 없다 — Center가 지운다). 어댑터 해석기(`core.http_adapter`)가 `idempotent: false` 작업에서
요청을 **보낸 뒤** 답을 못 받았을 때(읽기 시간 초과·끊김)만 싣고 — 연결 단계 실패(`ConnectError`·`ConnectTimeout`)는
요청이 나가지 않아 모름이 아니다 — 어댑터 일꾼이 `service_kit.Outcome`으로 나르며 `CenterServiceCaller`가
`ServiceCallError.outcome_unknown`으로 옮긴다. 엔진의 `bpm:serviceCall`은 재시도를 다 쓴 마지막 실패가 모름이고 **PC
실행**이면 ADR-0106과 같은 현장 확인으로 멈춘다(`Pending.retry_attempt`·`retry_call_seq`) — 「계속」은 `attempt`를 올려
**같은 `call_seq`로 다시 부르고**(새 일감, 출력이 채워진다), 「중단」은 서버와 같은 `TASK_FAILED`다. `TASK_FAILED`를 이름으로
받는 경계가 있으면 묻지 않고, 서버는 그대로 오류 경계다(BX-32가 그 모양이다). 남겨 둔 것: 잠금이 지나 만료된 일감
(`expired`·`timeout`)도 결과를 모르는 경우지만 Center는 작업이 멱등인지 몰라 표시하지 않는다. 지금 C11 서비스 앱은 그 칸을
싣지 않는데 공백이 아니다 — 바깥 시스템에 쓰는 앱이 없다(LLM 호출은 다시 해도 된다). 그런 앱이 생기면 그 앱이
`Outcome.outcome_unknown`을 싣는다.

### 3-18. PC에서 전환을 사람 확인으로 넘기는 길 — **닫았다**

[ADR-0106](decisions/0106-pc-escalation-asks-a-person.md). 확장의 `escalate: confirmation`과 AI 태스크의 확인 트리거가 **PC 실행이면** 그 자리에서 현장 확인 하나로 멈춘다(`core.nodes`의
`asks_a_person`·`escalate_to_person` — `manualTask`와 같은 요청이라 PC 실행기·실행 프로세스·CMN-01은 그대로다). 「계속」은
**다시 하지 않고 결과 없이** 넘어가고(`Engine._escalation_answered`), 「중단」은 `ESCALATED` 업무 실패다. 그림이
`ESCALATED`를 이름으로 받는 경계를 달았으면 확인을 띄우지 않고, 서버는 늘 오류 경계다. Studio 시험 실행은 케이스
`approvals`가 그 태스크 노드 id로 답하고 **적지 않으면 「중단」**이다. 확장이 확인 창에 보일 자료도
[ADR-0112](decisions/0112-escalation-review-from-extensions.md)로 왔다 — 확장이 `TaskFailed(review=…)`로 넘기고 엔진이
확인 요청의 C6 `review`로 옮긴다(실행 기록에는 없다). 표는 C6 표 값 `{headers, rows}`다. C13 §4-1의 어댑터
쪽은 §3-19가 닫았다. 남겨 둔 것: Center 콘솔(CON-04)은 표 값을 아직 표로 그리지 않는다 — 그 모양을 싣는 확인은 Center로
올라가지 않는다.

### 3-17. 바깥 기능을 부르는 길 (Pull) — **닫았다**

[ADR-0102](decisions/0102-calling-outside-is-pull.md)가 「네트워크를 건너는 바깥 호출은 모두 Pull」로 정했고 [C15](03-contracts/C15-external-tasks.md)는 **구현됨**이다.
부르는 쪽 셋(서버 실행기·실행 프로세스·Studio — `core.services.CenterServiceCaller`)과 일꾼(`service_kit.consumer` — 서비스 앱·모의 앱 열셋, 어댑터 일꾼 `bpm-adapter-consumer`)이 붙었고,
옛 길(C11 `POST /v1/ops`·`/manifest`·앱 안의 키, HTTP 어댑터 직접 호출, 서비스 앱 키 배달 ADR-0094, Center의 외부 앱
키·주소 덮어쓰기 ADR-0097)은 걷었다. 남았던 둘도 닫았다:

- ~~긴 작업~~ (조각 6) — **닫았다** ([ADR-0103](decisions/0103-long-external-tasks.md)): 서버 실행기는 한 번 기다려
  (`PARK_AFTER_S`, 기본 20초) 끝나지 않은 일감을 다섯째 기다림 `external_task`로 넘기고 자리를 놓는다. 결과는
  하트비트 주기마다 C15로 묻고, 걷히면 거두고, 받아 간 값을 잃으면 같은 칸으로 다시 올린다.
- ~~C14의 옛 칸~~ — **걷었다**: C14 `bpm:serviceCall.key_ref`·`bpm:process.service_keys`와 C1
  `requires.service_apps[].key_ref`·`task_key_refs`·R4가 모델·빌드·검사에서 없어졌다. 예제 생성기(`exdsl.py`)가
  더 적지 않아 업무 예제에 없고, 옛 그림·패키지는 모르는 칸으로 읽어(원칙 3) **B7이 경고 한 줄**로
  말한다(`old_key_field`). 선택 칸을 걷은 것이라 판은 올리지 않았다(C4의 키 칸과 같은 결).
  남겨 둔 것은 **옛 받는 쪽을 위한 칸**뿐이다 — C3 `service_call.key_ref`(늘 빈 글), C4
  `Readiness.missing_key_refs`(늘 빈다), `extension_api.PreflightTarget.key_refs`(늘 빈다).

### 3-13. PC 위임 — **닫았다**

[ADR-0062](decisions/0062-pc-delegation.md)가 정했고(선택지 셋을 두고 골랐다) **계약 다섯·엔진·
꽂는 쪽 둘·현장에서 값이 올라오는 길이 모두 돈다**. 그래서 ADR 끝의 **「증명할 다섯」이 다 찼다**:
서버 실행이 위임으로 멈추면 **자리를 놓고**, 재시작을 건너 **작업이 하나**이며(작업 id가 스냅샷과
함께 간다), **선언한 `outputs`가 값으로 돌아와** `bpm:call.output`이 적은 변수에 담기고, 실패·거절은
**오류 경계가 받고**, Studio 시험 실행은 **케이스가 적어 둔 결과로** 끝까지 간다. 지키는 시험은 셋이다
— `tests/test_core_events.py`(엔진)·`test_studio_runner.py`(케이스 포트)·`test_server_runner_delegation.py`
(실행기·Center, 마지막 하나는 **PC를 진짜 자식 프로세스로 돌려** 현장이 만든 값이 서버 변수에
담기는 것까지 본다). **업무 예제에도 들어왔다** — BX-16이 쓰던 사내 확장 우회(`center-jobs`)를
걷어내고 `bpm:call.delegate`로 다시 썼다(2026-10-16). 그 예제가 제품 흠 하나를 드러냈다:
`import_example`이 **위임 대상까지 작업 폴더로 끌어와** 매니페스트가 그 BPM 프로세스의 요구사항을 제
것처럼 모았다(BX-16이 맡기는 PC BPM 프로세스의 태스크 종류를 요구해 서버 BPM 프로세스가 `not_ready`가 됐다).

**B14의 `delegated_outputs`도 왔다** — Studio가 Center에서 BPM 프로세스 패키지 목록(C5)을 받아 매니페스트의
`outputs`를 모아 실행 전 검사에 넘긴다(`service_catalog.declared_outputs` → `preflight.inspect`).
그래서 「그 BPM 프로세스가 돌려주지 않는 값을 받는다」를 **그림에서** 안다 — 실행할 때 알면 늦다.
**판이 여럿이면 합친다**(막는 검사라 좁게 잡으면 멀쩡한 그림을 거부한다 — 그림이 판을 적지 않으면
「배포된 판」이라는 뜻이고 어느 판이 배포될지 Studio는 모른다), **매니페스트가 없는 줄은 건너뛰고**,
**못 받으면 그 대조만 건너뛴다**(빈 사전을 그대로 넘기면 「아무것도 선언하지 않았다」가 되어
멀쩡한 위임이 모두 막힌다 — Center에 닿지 못한 날 Studio가 멈춘다).

**값이 Center를 지나가는 것**이 이 거리의 값이다 (C6 `review`·`answer`에 이어 둘째 예외다) —
그래서 올리는 것은 **선언한 `outputs`만**이고, **ack와 함께 지우며**, 화면에 보이지 않는다.

**ADR이 적어 둔 둘도 왔고, 그중 하나를 켜 주는 길까지 생겼다**:

- **서버 실행이 취소되면 그 위임 작업도 거둔다** (ADR-0062 §5) — 거두는 길은 실행기 키로
  들어오는 `POST …/server-runner/delegations/{job_id}/cancel`이고 **Center 안에서** 작업 취소
  함수를 부른다(위임 요청과 같은 결 — 권한표를 넓히면 실행기 키로 남의 작업까지 취소할 수
  있게 된다). 거둘 것은 **기다림이 걷히기 전에** 읽고(`Engine.cancel`이 비운다) 닿지 못하면
  들고 있다 다시 건다. **그 가지를 켜 주는 길도 생겼다** —
  [ADR-0063](decisions/0063-stopping-a-running-server-run.md)이 C5 취소 표에서 **서버 대상
  `accepted`**를 202로 열었다 (PC는 그대로 거절이다).
- **못 받은 값은 작업 멱등 기간(7일)에 지운다** (ADR-0062 §4) — `delegations.purge_values`가
  하트비트에서 돈다 (C6 결재의 `purge_values`와 같은 자리·같은 결). **값만** 지우고
  누가·언제·성패는 남으며, `acked`는 **그대로 0이다**(받지 못한 것을 받았다고 적지 않는다).

**함께 고친 흠 둘** (이 조각을 돌려 보며 드러났다):
- **취소된 서버 실행이 `failed`로 올라가고 있었다** — 엔진은 성공만 `DONE`으로 앉히고
  **취소도 `FAILED`**인데(`_finish`) 일꾼의 스냅샷이 상태로 갈랐다. 그래서 작업 ack가
  `cancelled`를 잃고(C4) 같은 실행의 기록(`cancelled`)과 어긋났다. 끝난 방식은 **기록에서
  읽는다**(파일이 원본이다 — C3).
- **기다리는 실행은 취소를 부탁할 상대가 없었다** — 스레드를 놓았으므로 깃발만 세워 두면
  영원히 기다리고 작업도 `accepted`로 남는다. 도는 스레드가 없을 때는 **부르는 쪽이 그 자리에서**
  닫는다 (답·메시지를 넣는 것과 같은 자리다, ADR-0054 §5).

### 3-14. 서버 실행기의 확장 태스크 — **닫았다**

[ADR-0064](decisions/0064-extension-tasks-on-the-server.md)가 정했다: **실행기는 확장을 꽂고
로컬 런타임은 띄우지 않는다.** 적어 두었던 「먼저 정할 것」(런타임을 누가 띄우나)의 답은
**선택지 ②**였고, 그것을 고른 까닭은 하나로 모인다 — **예약(`reserve`)이 배타 잠금**이라
(ADR-0014 §4, 「PC에 하나」) **동시 실행이 기본인 서버**(C12)와 맞지 않는다. 묶는 길도 다르다:
런타임은 데스크톱 설치 파일에 들어가고(ADR-0024) 서버는 화면 없는 컨테이너다.

**계약은 늘지 않았다** — `run_locations`에 `server`를 적는 것이 이미 「런타임도 화면도 필요
없다」는 약속이라, 새 칸(`needs_runtime`)을 더하지 않았다. 더하면 **띄울 것을 고르는 길이 둘**이
된다(PC 실행기는 확장 단위로 띄운다) — 값이 같고 거르는 자리만 다른 목록은 조용히 갈라진다.

**함께 드러난 것 하나** — Center의 C7 확장 자원이 `bot_uis`만 읽고 있었다. 계약은 처음부터
「C4·**C12** 보고」라고 적어 두었는데(C7 `installed_on`) 코드가 덜 됐고, 실행기도 등록에
`extensions=[]`를 싣고 있었다. 그래서 **서버에만 깔린 확장은 Center가 모르고**, 그것을 요구하는
멀쩡한 서버 BPM 프로세스의 **배포가 「확장 누락」으로 막혔다**. 양쪽을 고쳤다.

남은 두 가지는 **공백이 아니라 선언의 일**이다: 서버에서 돌 태스크 종류를 가진 확장이 아직
하나도 없고(지금은 깔린 내장 확장이 없다 — ADR-0114), 그 길이 정말 열렸는지는
가짜 확장으로 끝까지 돌려 본다 (`tests/test_server_runner_extension_run.py`).

**닫은 것들** — §3-12(타이머로 깨우는 자리)는 [ADR-0061](decisions/0061-waking-runs-whose-timer-is-due.md)로 닫았다(하트비트가 쓸어서 깨우고 자리가 있을 때만 — 기한은 「그 시각 이후」다). 3-10(정의 고정)은 [ADR-0060](decisions/0060-pinning-external-definitions.md)으로 닫았고(그림에 고정하고 막지 않고 경고한다 — 재료가 이미 깔려 있어 계약이 늘지 않았다), 3-11(`requires.settings`)은 [ADR-0059](decisions/0059-sending-mail-and-webhooks.md)가 닫았다. 3-9는 [ADR-0049](decisions/0049-deployment-target-must-exist.md)로 닫았다 — 배포 대상은 등록된 PC여야 하고, 등록 전에는 봉투에 적을 `bot_ui_id`가 없어 「미리 배포해 두기」는 길이 아니었다.

### 3-15. 서버의 병렬 반복 — **닫았다**

[ADR-0087](decisions/0087-parallel-loop-on-the-server.md)이 정했다. 적어 둔 「먼저 정할 것」 셋의 답이다.

① **함께 기다리는 모양은 차례마다 토큰 하나**다 — 반복 노드를 처음 밟은 토큰이 주인으로 멈추고
차례 토큰이 같은 노드를 한 번씩 밟는다. 「기다림은 토큰 하나에 하나」가 그대로라 답·위임 결과·
경계·스냅샷이 지금 길을 탄다(`Run`에 칸이 늘지 않고 `LoopState`에 `offset`·`host`가 붙었다).
② **결과는 주인이 건수만큼 미리 잡은 자리**에 차례마다 넣는다 — 끝난 순서와 상관없이 입력 순서다.
③ **한 건 실패는 나머지를 거둔다** — BPMN의 다중 인스턴스 오류 뜻 그대로이고, 맡긴 작업은 위임
포트에 더한 `withdraw`로 거둔다(서버 실행기는 실행 취소와 **같은 줄**에 넣어 하트비트 뒤에 건다).
반복 노드의 오류 경계가 **한 번** 받는다. 그 길을 지으며 **위임 호출의 중단 경계(업무 기한)가
울려도 그 작업을 거두지 않던 것**도 함께 닫았다.

함께 도는 것은 **실행 위치가 `server`인 그림**뿐이고(PC는 차례로), 「함께」는 **기다림이 겹친다**는
뜻이다 — 엔진에 스레드가 없어 서비스 앱 호출 같은 동기 태스크는 겹치지 않는다. FX-24가 병렬로
그려져 세 건을 한 번에 맡긴다(M7 `test_cancelling_the_batch_cancels_the_child_that_has_not_run`이
「한 건도 시작되지 않았는데 셋이 다 맡겨졌다」를 본다).


### 3-16. 외부 확장의 주소를 Center가 덮어쓰는 입구 — **닫았다**

> [ADR-0102](decisions/0102-calling-outside-is-pull.md)로 대체됐다 — 외부 앱의 주소·키는 이제 어댑터 일꾼의 설정에만 있고 Center는 덮어쓰지 않는다. 아래는 그때 닫은 기록이다.

C13은 「Center 리소스 등록의 `base_url`이 이긴다」고 적었는데 읽는 쪽만 돌고 Center에 외부 확장의 주소를 넣는
길이 없었다(서비스 앱 등록은 C11 `/manifest`를 읽어야 행을 만든다 — 바깥 요청 NowView R4가 드러냈다).
[ADR-0097](decisions/0097-external-extension-address-from-center.md)이 C7 §외부 확장 주소로 닫았다 — 관리자가
CON-07 상세 「서버 주소」에서 넣고 **정의의 허용 호스트 안에서만** 받으며, 같은 명부로 내려가 어댑터가 쓴다.

## 4. 화면 쪽 기능 공백

### 4-5. 「설치」 (올리기·STU-11·STU-06·STU-03과 **공유 BPM 프로세스 설치·부르기·보기·복사**는 닫았다)

**올리기 둘과 STU-11 읽기는 닫았다** (`apps/studio/upload.py` + `center_resources.py`, Center 쪽 권한 관문은 `center/auth.py`·`api/package_access.py`). Studio 키로 올리고, 올라온 공유 BPM 프로세스·툴팩을 STU-11과 STU-03이 **같은 출처**(C5 패키지 표)에서 본다. **STU-06도 닫았다** (`process_dialog.py` — 그림 쪽은 캔버스를 거친다. 확장 태스크의 실행 위치는 확장 호스트의 표로 센다 — F6·매니페스트가 같은 표를 쓴다). **STU-15도 닫았다** ([ADR-0043](decisions/0043-turned-off-extensions.md)). **STU-03도 닫았다** (`resources.py` — 뿌리 넷·둘째 단계·문맥 메뉴·「캔버스에 추가」·끌어다 놓기. 드래그는 [ADR-0044](decisions/0044-canvas-drag-and-drop.md), 기여 뿌리의 둘째 단계를 **두지 않기로** 한 것은 [ADR-0045](decisions/0045-contributed-resource-children.md)다).

**공유 BPM 프로세스 「설치」는 닫았다** ([ADR-0048](decisions/0048-installing-shared-packages.md) — `apps/studio/install.py` + `workspace.py`·`packaging.py`·STU-11). 받은 것이 그 BPM 프로세스 작업 폴더의 `libs/`로 가고, **호출이 거기서 찾는다**(실행기가 이미 읽는 자리라 내보내기·실행기는 바뀌지 않았다) — 그래서 설치 뒤에는 시험 실행도 **C14 B14도** 그 호출을 받아들이고, 내보낼 때 `requires.libs`에 **판이 붙는다**(C1 `<id>@<version>` — 전에는 id만 적혀 R3·CON-06의 참조 셈이 어긋났다). **결정표(DMN)도 함께 온다** — 정의가 쓰는 `.dmn`을 같이 풀고 **Studio와 실행기가 둘 다** `libs/*.dmn`을 읽어, lib 안의 규칙 태스크가 **진짜로 돈다**(엔진으로 본다. 결정표를 지우면 멈추는 것도 함께).

**STU-03의 편의 셋도 닫았다** ([ADR-0051](decisions/0051-shared-process-conveniences.md) — `resources.py`·`install.py`·`center_actions.py`·`viewer.py`). 적혀 있던 「먼저 정할 것」(**줄마다 설치 여부를 알지 못한다**)은 **틀렸다** — 재료(`BpmProcess.libs`)가 다 있었고 **STU-11이 바로 그 C5 목록에 설치 여부를 덧붙여** 그리고 있었다. 그래서 적어 둔 두 선택지가 **셋째를 빠뜨렸다**: 멤버십은 Center 목록 그대로 두고 **설치 여부만 줄에 덧붙인다**(줄이 늘거나 줄지 않는다). 설치 여부를 읽는 함수는 **STU-11과 하나**(`install.installed_of`)이고, 셋은 **설치된 판의 정의에서만** 켜진다(아니면 끄고 까닭을 적어 STU-11로 보낸다 — 설치되지 않은 호출은 B14가 막는다). 「열기 (읽기 전용)」은 **bpmn-js 뷰어 한 벌을 더 실어**(+190 KB) 지킨다 — 팔레트만 가린 편집기를 「읽기 전용」이라 부르지 않는다. 「복사」는 `process/`로 가 그때부터 **내 것이 이기고** `requires.libs`에서 저절로 빠진다.

**툴팩 「설치」는 만들지 않기로 닫았다** ([ADR-0050](decisions/0050-no-toolpack-kind.md)) — 「받은 코드를 돌려도 되나」를 정하려고 셋(관문·싣는 길·파일 권한)을 적어 뒀는데, **셋째의 답이 첫째와 둘째를 지웠다**: 툴팩은 처음부터 코드가 아니었고(용어집) 선언을 담을 자리도 계약에 없어 **지금의 툴팩 패키지는 「이름표만 든 zip」**이었다. 그래서 설치할 것이 없다 — 도구는 확장이 기여하고, 코드 있는 도구는 설치 파일로만 온다.

- **STU-01 메뉴도 닫았다:** 파일 메뉴 셋(「정의 추가...」·「이 정의를 진입으로 지정」·「다른 이름으로 저장...」)과 「결정 수행 (재생)...」(Ctrl+F5)은 **닫았다** (`file_actions.py`·`workspace.py`·`run_dialog.py`의 `prefer`). 「다른 이름으로 저장」의 단위는 **BPM 프로세스 한 벌**이다 — 정의 하나만 복사하면 그림 안의 process id가 겹쳐 호출이 모호해지고, 고치려면 XML을 파이썬이 만져야 한다 ([ADR-0022](decisions/0022-studio-canvas.md)가 막는다). **남은 것이 없다** — 레이아웃 기억·초기화·「속성 패널 접기」는 `layout.py`로 닫았고(담는 자리는 설정과 따로인 `layout.json`이다), 「감시 모드 시작」은 **두지 않기로** 닫았다.
  - **「감시 모드 시작」은 두지 않기로 닫았다** ([ADR-0053](decisions/0053-no-watch-mode-in-studio.md)) — 「먼저 정할 것」이 「시험 실행이 기다려도 되는가」였는데 질문이 그보다 **앞에** 있었다: **일정(cron)을 읽는 자리가 그때 어디에도 없었다**(지금은 Center가 쥔다 — §3-20, [ADR-0110](decisions/0110-center-keeps-the-schedule.md)). 개발 도구가 먼저 가지면 「Studio에서는 도는데 현장에서 안 된다」의 새 원천이 된다. 트리거가 깨우는 그림은 **시험 케이스의 `messages`**로 보고, 시험 실행은 **판정이 있는 한 번**으로 남는다.


### 4-9. CON-02 — 콘솔 집계 시험

**화면·「확인률」·「배포된 PC 실행기」를 닫았다** (`app/bots`). 확인률은 C3 `run_finished`에 선택 칸 `confirmations`를 더해 잰다 — 가르는 것은 **세는 쪽의 일**이고(Center는 줄을 다시 읽어 세지 않는다) 보내지 않은 옛 기록은 **분모에서 빠진다**.

**「배포된 PC 실행기」도 닫았다** ([ADR-0046](decisions/0046-no-wildcard-pc-deployment.md)). 여기 적혀 있던 「먼저 정할 것」(**C5가 대상을 푸는 길**)은 **없었다** — 「그룹 배포」는 계약에도 코드에도 아예 없고, 전체(`*`) 배포는 **PC 쪽에 없다**(C2는 `"*"`를 서버 배포에만 주고 `DeploymentTarget.matches`·V6도 그렇다). 그래서 PC 배포는 전부 `bot_ui_id` 하나를 가리키고 「배포된 PC 실행기」는 **`target.id`를 겹치지 않게 센 수**다. 재료는 CON-02가 이미 받아 둔 둘(C5 배포 목록·PC 실행기 목록)로 끝났고 **계약이 늘지 않았다**. 함께 고친 것 둘: Center 네 자리가 대상 종류를 가리지 않고 `"*"`를 풀던 것(이제 한 함수가 짓고 `POST /deployments`는 409 `wrong_target`), 그리고 `summarize`가 **제가 세지 않은 칸**(`blocked`·`deployments`)을 0으로 들고 돌아와 실제 값을 덮던 것(끝난 실행이 있는 판은 「실행 불가」가 늘 0이었다).

- **콘솔 집계 함수의 셈을 vitest가 잰다** (`web`에서 `pnpm test`, CI 웹 잡에 한 걸음). **2026-10-11에 「시험 판을 들이지 않는다」로 정했던 것을 2026-10-13에 뒤집었다** — 들이지 않는 쪽의 값은 「CI가 짧다」였고, 치른 값은 **덮어쓰기 흠**(끝난 실행이 있는 판의 「실행 불가」·「배포된 PC 실행기」가 늘 0이던 것)이었다. 글로 막는 것은 같은 흠의 재발까지이고 **셈이 틀리는 것은 못 막는다**. 들이면서 한 일 둘: 세는 코드를 **화면을 모르는 모듈**로 갈랐고(`lib/summary.ts` — 페이지는 `server-only`를 끌고 와 단위 시험에서 부를 수 없다), 브라우저·React를 **띄우지 않게** 했다(jsdom·플러그인이 없어 CI에 느는 것은 몇 초다). 재는 것은 성공률·재생률·**확인률의 분모**·최근 20회 끊기·최근 성공 시각·`RunFields`가 남의 칸을 들고 오지 않는가·PC 수 세기·키 참조 모으기다.

## 5. 공백은 아니지만 적어 둘 것

- **편의 접근자 둘을 지웠다** (2026-10-16) — `ExtensionHost.adapter_operations()`(창·어댑터는 정의의 `m.adapter.operations`를 직접 읽는다)와 `secret_config_keys()`(`credentials.py`가 `configuration()`에 `.secret`을 걸어 본다). **쓰는 길이 둘이면 한쪽만 고친다.** 함께 적어 둔 `studio_editors()`는 **쓰인다** — `editor(task_type)`가 그것을 부른다(단수 메서드 뒤에 있어 「호출자 없음」으로 잘못 적혀 있었다). 시험은 **제품이 쓰는 길**로 고쳐 같은 것을 본다.
- **C1의 「아는 값」 둘을 정했다** (2026-10-16) — `KNOWN_SETTINGS`는 **쓰는 쪽을 만들었다**(R11: `requires.settings`가 아는 값인가 — R9와 같은 까닭이고, 지금 Studio가 넣는 것은 `smtp` 하나뿐이라 올라간 패키지는 다 지난다). `KNOWN_BUILT_BY`는 **검사하지 않는 쪽으로 정했다** — 남의 도구로 만든 올바른 패키지를 거부하게 되므로 열린 문자열이 맞다. 그 까닭을 **상수 옆에 적어** 두어 다음 사람이 「검사가 없다」고 또 적지 않게 했다.
- **`extension_api`에 우리 호출자가 없는 상수들은 정상이다** (`SEVERITY_INFO`) — 그 패키지는 **확장 저자에게 주는 API**(C13)다. 우리 코드가 다 쓰는지로 셈하지 않는다. (`HOST_SERVER_RUNNER`·`RUN_LOCATION_SERVER`는 2026-10-16에 쓰는 쪽이 생겼다 — [ADR-0064](decisions/0064-extension-tasks-on-the-server.md). 그때 그 둘을 대조하다 §3-14를 찾았다.)
- **도메인 목록의 정의는 `manifest.py` 하나다** — `KNOWN_DOMAINS`·`PC_ONLY_DOMAINS`를 `bpmn_ext`(C14 B8·B6)와 `core`(사전 점검·AI 태스크)가 import해 쓴다. 자리가 C1 쪽인 것은 층 때문이다 (`bpmn_ext`가 `manifest`를 import하므로 거꾸로는 순환이다). **두 벌로 되돌리지 않는다** — 값이 같고 거르는 자리만 다른 목록이 둘이면 조용히 갈라진다(`triggers[].kind`가 그랬다). `tests/test_contracts_bpmn_ext.py`가 **같은 객체인지**(`is`) 본다.
- **「C13 `docs_url`·`owners`, C11 `Operation.json_schema`를 콘솔이 보이지 않는다」는 닫았다** (2026-10-18) — 대조해 보니 **셋 중 둘은 계약에 없는 칸**이었다(C13에 `owners`가 없고, C11 작업의 스키마는 `input_schema`·`output_schema`이며 STU-14·STU-03 툴팁이 그것으로 칸을 그린다). 남은 `docs_url`은 STU-15·BUI-11 상세 맨 위에 「설명 문서」로 보인다. **없는 칸을 공백으로 적어 두면** 다음 사람이 그 칸을 만들러 간다.

## 6. M6 첫째 — 현장 시나리오 3: 멈춤

시나리오 3(웹에서 읽어 데스크톱 앱에 입력)은 화면 조작이 있어야 돌고, 그것을 하던 UI 자동화 확장을 걷었다 — 예제(BX-04)도 함께 없다. **§3-28로 다시 들인 뒤에** 이 기준을 다시 연다. 서버 BPM 프로세스인 시나리오 1·2·4는 M7 인수 시험이 덮는다 ([ADR-0055](decisions/0055-m6-field-scenario-is-scenario-3.md)).

## 7. 화면 문서에 「아직」으로 적힌 자리 (M6 셋째 기준)

§1~§4는 계약·화면을 **코드의 호출자**로 대조했다. 이번에는 거꾸로 **화면 문서의 「상태」 줄이 「아직」이라고 적은 것**을 모았다(2026-10-18) — 화면이 문서와 **맞기는 하지만**(문서가 「아직」이라고 정직하게 적었다) 기준의 뜻은 「문서가 약속한 화면이 돈다」라서 여기 둔다. 먼저 정할 것이 없던 하나(BUI-04 「최근 실행」 — BUI-02가 읽는 기록 파일에서 그 BPM 프로세스의 마지막 실행을 고른다)는 **닫았다**. 7-4(STU-06 「나누기」)도 **닫았다** — 노드 하나를 새 PC BPM 프로세스로 옮기고 그 자리를 위임 호출로 바꾼다([ADR-0071](decisions/0071-splitting-a-task-into-a-pc-bot.md)). 7-5(STU-10 나머지 분류)도 **닫았다** — 칸마다 읽는 곳을 대조해 테마·확장별 설정은 켜고, 읽는 곳이 없는 메일·비밀·공급자·temperature·화면 인식 모델·캔버스 팔레트는 화면 문서에서 걷었다([ADR-0073](decisions/0073-studio-settings-only-what-is-used.md)). 7-7(서비스 앱 콘솔 → CON-01)도 **닫았다** — Center 콘솔 주소는 서비스 앱 콘솔의 설정 하나로 받고 C11은 그대로다([ADR-0075](decisions/0075-service-console-links-to-center-console.md)). 7-8(ADM 창)은 닫았다 — 지금은 Admin 창도 CLI도 없고 관리자가 Center 콘솔에 계정으로 들어와 Center가 대신 서명한다([ADR-0090](decisions/0090-center-admin-accounts.md)). UI 자동화 쪽 자리(7-2·7-3·7-6·7-10)는 그 확장과 함께 걷었다 ([ADR-0114](decisions/0114-remove-ui-automation.md)).

| 자리 | 화면 | 남은 것 | 먼저 정할 것 |
| --- | --- | --- | --- |
| 7-11 | STU-04 「요소별 편집기」의 나머지 | 폼이 있는 것은 **AI 태스크**(`ai_task_editor.py`)·**결재·확인**(`approval_editor.py`)·**보내기**(`send_editor.py` — 메일·웹훅)·**BPM 프로세스 호출**(`call_editor.py` — PC 위임 포함)·**반복**(`loop_editor.py` — 다른 편집기 탭 옆에 하나 더)·**게이트웨이**(`gateway_editor.py` — 기본 흐름)·**이벤트·받기 태스크**(`event_editor.py` — 타이머·메시지·신호·오류·경계의 중단, `bpm:receive`)·**데이터 객체**(`data_output_editor.py` — `bpm:dataOutput`)·**BPM 프로세스(정의) 자체**(`defaults_editor.py` — `bpm:defaults`, 빈 상태의 「BPM 프로세스 기본값」 단추로 들어간다. `bpm:process`는 「변수」 탭·STU-06·STU-15가 고치므로 다시 만들지 않았다)·**규칙 태스크**(`rule_editor.py` — `bpm:rule`의 결정·입력·출력 짝. 결정표 격자는 따로 뜨는 창 STU-04a `decision_dialog.py`이고 창의 「저장」이 `.dmn`을 바로 쓴다, [ADR-0109](decisions/0109-studio-writes-decision-tables.md))·서비스 앱 태스크(STU-14)·순서 흐름의 조건식·스크립트 태스크다 — 화면 문서의 표는 그 폼들을 약속하는데 상태 줄이 없어 「돈다」로 읽혔다(2026-10-23, 결재 폼이 「이름·설명」만 보여 드러났다). **AI 태스크 폼의 「재생 명세」 한 줄·「명세 잊기」**(속성 패널이 열린 정의의 process id로 `memory/specs.json`을 읽는다 — `replay_specs.py`, 잊기는 「적용」을 기다리지 않고 시험 실행 중에는 꺼진다)와 **목표 미리보기**(엔진과 같은 `goal_names`로 모델에게 가는 이름)까지 와서 **화면 문서가 약속한 폼은 다 돈다**. 「재생 검증 결과」는 명세에 그런 칸이 없어 문서에서 뺐다. 남은 것은 웹 환경 칸뿐이고 웹 환경을 주는 확장이 생길 때의 일이다 | 없다 — 요소마다 C14 모델이 칸을 정해 두었다. 보내기·AI 태스크는 화면 문서가 C14에 없거나 **엔진이 읽지 않는** 칸(웹훅 헤더·메일 HTML 여부, AI의 시작 주소·로그인·창 제목·「복합」 환경·환경별 도구 검증)을 약속하고 있어 **계약에 있고 엔진이 읽는 칸만으로** 문서를 다시 썼다. `bpm:aiTask`의 `forbidden_actions`·`confirm_triggers`·`limits.timeout_s`는 **엔진이 읽고 폼에도 있다** ([ADR-0105](decisions/0105-ai-task-limits-and-instructions.md)). C14에 있는데 쓰이지 않는 것은 `web`(웹 환경을 주는 확장이 없다)뿐이다 — 정의 폼도 그것과 「창 숨김」(계약에 없다)을 두지 않고, 그림에 있는 `web`은 남기고 말한다. 이벤트도 같은 원칙으로 다시 썼다 — 「수신 주소」·조건 이벤트의 식·확인 주기·「다음 실행 미리보기」(주기)는 두지 않았고, 시작 타이머의 주기는 **매니페스트(C1 `triggers`)에 실리고 배포되면 Center가 그 일정으로 깨운다**고 폼이 말한다(§3-20 — 주기는 Center와 같은 `contracts.schedule`로 본다) |

## 8. 화면 문서가 약속했는데 코드에 없는 것 (2026-10-31 대조)

§7은 화면 문서가 스스로 「아직」이라 적은 것이었다. 이번에는 **상태 줄이 「돈다」인데** 표의 단추·칸·문구가 코드에 없는 것을 모았다. 화면 문서의 라벨 글을 코드에서 찾고 손으로 읽어 맞췄다. 정직한 「아직」인데 여기 없던 것(STU-05 「실행 위치」, STU-07 `delegations` 칸, BUI-11 「필요한 키」·주소 줄, CON-07 「PC N대에서 시작되지 않음」)도 함께 둔다.

| 자리 | 화면 | 약속한 것 | 코드 근거 | 먼저 정할 것 |
| --- | --- | --- | --- | --- |
| 8-1 | CON-05 「새 작업」 | 서버 BPM 프로세스면 PC 고르기 대신 「서버 실행기에서 실행 — 동시 실행 상한 <n>」 | **닫았다** — 서버에 배포된 BPM 프로세스면 PC 칸 대신 그 글이 보이고(<n>은 배포의 `max_concurrency`, 없으면 「기본」) `target: {type: "server_runner", id: "*"}`로 만든다. 판단은 `lib/jobs.ts`(`runsOnServer`·`serverVersions`·`serverLimit`, vitest `jobs.test.ts`) | — |
| 8-2 | CON-05 「중지」 | 도는 서버 실행(`accepted`)의 「중지」·확인 문구 「도는 실행을 멈춥니다…」·「중지 요청함」, PC면 끄고 까닭 | **닫았다** — 단추는 `lib/jobs.ts`의 `cancelControl()` 하나가 정한다(취소·중지·끈 단추, vitest). 「중지...」는 확인 창(기본 「취소」)을 거쳐 같은 `DELETE /jobs/{id}`를 부르고, 상태 옆 글이 「중지 요청함 — 다음 하트비트에 반영」이다. PC면 끈 단추에 까닭(목록은 툴팁, 상세는 한 줄) | — |
| 8-3 | CON-01 목록 「시작 방식」 | 작업·감시·수동·일정·메시지 | **닫았다** — 표기는 `lib/labels.ts`의 `sourceLabel()` 하나(C3 `KNOWN_SOURCES` 일곱, 모르는 값은 그대로, vitest `labels.test.ts`)이고 CON-01 목록과 CON-03 상세 대기열 「출처」가 같이 쓴다 | — |
| 8-4 | CON-01 상세 | 노드 타임라인의 가로 막대·이어 돌기 점선, 요약의 「재생」·「LLM 단계」 | **닫았다** — 막대는 노드마다 한 줄(색 = 「실행·노드」 상태 색, 줄 앞에 노드 id·상태 글), 기다린 구간은 그 줄에 점선 테두리로 겹치고 표는 아래 그대로다. 자리 셈은 `lib/timeline.ts`(`timeline`·`bars` — 도는 실행의 끝은 「지금」, vitest `timeline.test.ts`). 요약에 「재생」(`RunInfo.replayed_tasks`, 도는 중 「—」)과 「LLM 단계」(`llmSteps` — `agent`의 `plan`·`extract`와 재생이 아닌 `finish`)를 더했다. 「사람 개입」의 「폼 키」는 화면 문서에서 걷고(C3에 칸이 없다) 「무엇」·「종류」를 글로 옮긴다 | — |
| 8-5 | CON-00 위 막대 | 「새로 고침」 | **닫았다** — 아이디·역할 옆, 「로그아웃」 앞에 `components/Refresh.tsx`(`router.refresh()` — 다시 읽는 것은 서버 쪽이라 브라우저에 토큰이 오지 않는다) | — |
| 8-6 | CON-11 | 키 목록 필터 「종류」·「상태」 | **닫았다** — GET 폼과 「좁히기」(JS 없음), 두 표에 함께 걸린다. 주소의 값은 `lib/center-keys.ts`의 `keyFilter()`가 아는 것만 남겨 Center `?type=&state=`로 넘긴다(vitest). 좁혀 빈 표는 「조건에 맞는 키가 없습니다.」 | — |
| 8-7 | CON-03 목록 | 오프라인 줄의 실행·대기열 칸에 「마지막 보고 <시각> 기준」 | **닫았다** — 두 칸 아래 작은 글로 붙는다(`lib/labels.ts`의 `lastReportNote()`, vitest — 온라인·보고 없음이면 붙이지 않는다). 「런타임」 열은 §3-28(C4 `runtimes.browsers`)이라 그대로 빈다 | — |
| 8-8 | CON-07 | 기여 자원 줄의 상세(「이 자원을 쓰는 BPM 프로세스」), 「할 일」 → CON-03 **그 PC들만** | `app/resources/page.tsx:334-372` `Contributed`는 평평한 표, `lib/features.ts:131-133`은 필터 없는 `/bot-uis`. 「쓰는 BPM 프로세스」는 §3-24 때문에 늘 빈다 | §3-24가 먼저다 |
| 8-9 | CON-02 | (흠) 사람에게 마크다운 별표가 보인다 | **닫았다** — 별표를 걷어 「셈은 끝난 실행만 셉니다」 | — |
| 8-12 | STU-02 | 줄 종류별 문맥 메뉴(「정의 삭제...」·「BPM 프로세스 삭제...」·「다른 그룹으로 이동...」·「새 그룹...」·「그룹 삭제」·「새로 고침」), 끌어 옮기기, 삭제 확인 | `explorer.py:146`이 `CustomContextMenu`를 켜지만 `customContextMenuRequested`를 잇는 곳이 없다(유일한 연결은 `resources.py:639` — STU-03). `workspace.py`에 정의·BPM 프로세스·그룹을 지우거나 옮기는 함수가 없다 | 지우기의 범위(케이스·학습 자료)와 「다른 정의가 부르면 거부」를 B14와 같은 함수로 볼지 |
| 8-13 | STU-02 「학습·검증」 | 「AI 태스크 N개 · 학습 a/N · 재생 검증 v/N · 케이스 통과 p/S」 | `explorer.py:39-47`이 「AI 태스크 N개 · 정의 N개」 — docstring이 「아직 비어 있다」고 적었는데 화면 문서에는 상태 줄이 없다 | 「재생 검증」은 명세에 칸이 없어 7-11에서 이미 걷었다 — 같이 걷을지 |
| 8-14 | STU-04 스크립트 | 「상세 편집」 창·문법 검사·Ctrl+Enter | `properties.py:266-267`의 글상자뿐 (「Python」이라던 낡은 글은 고쳤다) | 문법 검사는 `core.expr`가 있다 |
| 8-15 | STU-05 | 「실행 위치」 라디오 | `dialogs.py`에 칸이 없다 — 화면 문서가 「아직」이라 적었다(그림 칸이라 캔버스를 거쳐야 한다, ADR-0022) | 만든 직후 캔버스에 넘기는 길 |
| 8-16 | STU-07 | PC 위임 결과(`delegations`)를 칸으로 | 화면 문서가 「아직」이라 적었다 — 지금은 파일에 적은 것을 남기기만 한다 | 없다 |
| 8-17 | STU-08 | 「서비스 앱」 줄 | `run_dialog.py`가 「서비스 앱 줄은 그 쪽이 생기면 채운다」 — 서비스 앱은 생겼다 | C15로 무엇을 보일지(일꾼이 붙었나 — C7 토픽 상태) |
| 8-18 | STU-09 | 상태 막대 「실행 중: <노드 이름>」·「완료: <도달한 종료> · 변수 N개 · …」, 사전 점검을 로그에 `[정상]`·`[경고]`… | `run_actions.py:126`은 케이스 이름, `:148`은 마지막 결과 글. 사전 점검은 「검사」 탭으로 간다(`main_window.show_preflight`) — **로그 문구는 문서가 고칠 쪽**이다 | 로그 문구를 문서에서 걷는다 |
| 8-19 | BUI-01 트레이 | 2-2 「오늘 실행 N (완료 x, 실패 y)」, 5 「보내지 못한 기록 N건」, 2-1 「등록을 마치면 실행됩니다」, 경과 시간·「연결 끊김 (마지막 <시각>)」 | `tray.py:121-177` — 없다. `core/run_shipping.py:131`이 BUI-05용 재료를 이미 준다 | 없다 |
| 8-20 | BUI-04 | 「맨 앞으로」·「제거...」·「새로 고침」, 「지금 실행...」의 입력 창·「맨 앞에 넣기」·「대기열에 넣었습니다 (N번째)」 | `main_window.py:247-290`의 단추는 결재 창·중지·취소·지금 실행·파일 설치뿐이고 `run_selected`(:597-608)는 입력 없이 넣는다. `agent.enqueue_manual(front=…)`(:1234)은 이미 있다. 설치 제거 함수가 없다 | 입력 창은 CON-05와 같은 규칙(매니페스트 `inputs`)으로 |
| 8-21 | BUI-01·04 「감시」 | 「감시 시작」↔「감시 중지」, 상태 「감시 중」, 대기열 출처 「감시 트리거」 (`bot-ui.md:13`·`42`·`124`·`127`) | PC 실행기에 감시가 없다 — 남은 것은 표기 하나(`main_window.py:132`) | **걷는 쪽으로 보인다** — 일정은 Center가 쥐고(ADR-0110), 폴더 감시인 조건 시작은 schema 1에서 쓰지 않는다(C14). 걷으면 C3·C4 `source: watch`도 함께(§3-26) |
| 8-22 | BUI-03 「나중에」 | 「메시지 수신 포트」·「툴팩 비밀」을 끈 채 보인다 | `settings_dialog.py:502-512` — 툴팩은 [ADR-0050](decisions/0050-no-toolpack-kind.md)으로 없어졌고(Studio는 ADR-0073으로 걷었다) 메시지 수신은 §3-21에 달렸다 | §3-21 |
| 8-23 | BUI-11 | 「필요한 키」·서버 부분 「주소」 줄 | 화면 문서가 「아직 보인다」고 적었다(`bot-ui.md:215`, 코드 `extension_dialog.py:103`·`:290`·`:326`). 같은 문서 `:213`(「주소는 보이지 않는다」)과 `:228`(「상세의 서버 부분은 주소만 말한다」)이 서로 다르다 | ADR-0102 뒤라 걷는 쪽 — 문서 둘을 한 가지로 |
| 8-26 | CMN-01 확인 | 한 줄 「응답 입력」, 「직접 처리했음」, 시간 초과 기록 「결재 요청이 시간 초과로 취소되었습니다.」 | `packages/qt/…/approval.py:205-209`는 「계속」·「중단」 둘뿐 | 「직접 처리했음」이 엔진에서 무엇인가(「계속」과 다른가) — ADR-0106은 둘만 정했다 |

## 9. 업무 예제가 밟지 않는 기능 (2026-10-31 대조)

예제 55개의 `bpm:*` JSON을 모두 읽어 쓰인 키를 세고 이벤트·게이트웨이 요소를 찾았다. 커버리지 표(`_source/build.py:279-388`)는 **노드 종류 + 칸 하나**로 행을 짓고 런타임 응답은 보지 못하므로, 아래는 표에 행이 없거나 행이 있어도 0인 것이다. **케이스 형식이 서비스 응답을 지어낼 수 없다** — 케이스 키는 `inputs`·`expected`·`approvals`·`manual`·`messages`·`delegations`뿐이라 「서비스가 실패·보류·결과 모름」을 예제가 시험하지 못하고 설명 글로만 적는다(BX-32의 「실패·결과 모름을 오류 경계로」가 그렇다 — 케이스는 정상 길 하나다). 아래 기능은 대부분 **단위·통합 시험은 있다** — 빠진 것은 「예제가 오라클」인 자리다.

| 기능 | 예제 | 코드 | 시험 |
| --- | --- | --- | --- |
| 종료(terminate) 끝 | BX-11이 쓰지만 엔진이 짓지 않는다 | §3-25 | 없음 |
| `ESCALATED` 오류 경계·PC 전환 확인 (ADR-0106·0112) | 0 — 경계 코드는 `TASK_FAILED`·`SEND_FAILED`·`DELEGATION_FAILED`뿐 | `core/nodes.py:470-543`, `engine.py:1068-1107` | `test_core_extension_tasks.py`·`test_core_ai_task.py` |
| 서비스 호출 결과 모름 (ADR-0107) | 0 (BX-32는 경계만) | `nodes.py:939-945` | `test_core_service_outcome_unknown.py` |
| 긴 외부 작업 `WAIT_EXTERNAL_TASK` (ADR-0103) | 0 | `run_state.py:86`, `nodes.py:904-911` | `test_core_service_task.py`·`test_m7_server_rerun.py` |
| 결재 `expires`·`APPROVAL_EXPIRED`/`WITHDRAWN` 경계 | 0 | `bpmn_ext.py:262`, `engine.py:1251` | `test_approval_channel.py` |
| 결재 `location: follow`(기본값) | 0 — 23개 모두 `center`·`field`를 적었다 | `bpmn_ext.py:261` | `test_approval_channel.py` |
| `answered_by_as`·`answered_via_as` (ADR-0096) | 0 | `bpmn_ext.py:264-269` | `test_core_engine.py` |
| 입력 출처 `company.*`·`department.*`·`staff.*` (ADR-0125) | 1 (`staff.name`만 — FX-25) | `bpmn_ext.py` `INPUT_SOURCE_TYPES` | `test_core_engine.py` |
| 웹훅 본문 `all`·`template:` | 0 — 6개 모두 `fields:[…]` | `bpmn_ext.py:296` | `test_core_senders.py` |
| 메시지 중간 받기 | 0 — 중간 받기는 타이머·신호뿐 | `nodes.py:1088` | |
| 타이머 `timeDate`·ISO 반복 `R[n]/…` 시작 | 0 — 시작 12개 모두 5필드 cron | `engine.py:855-872`, `contracts/schedule.py` | `test_center_timers.py`·`test_core_events.py` |
| 태스크 단위 AI 덮어쓰기(`aiTask.forbidden_actions`·`confirm_triggers`·`web`·`desktop`) | 0 — `bpm:defaults`만 쓴다 | `nodes.py:723-735` | `test_core_ai_task.py` |
| 작은 칸 — `email.cc`·`serviceCall.timeout_s`·`call.delegate.version`·`.bot_ui`·`fileList.limit`·`web.session` | 0 | `bpmn_ext.py:154`·`249`·`284`·`318-320`·`364` | 일부 |
| AI 태스크 `web` | 0 (표가 이미 「없음」) | 웹 환경을 주는 확장이 없다 | |

**표의 주석 하나가 낡았다** — `build.py:375`가 「**없음**인 요소는 C14 schema 1에서 쓰지 않거나(조건 시작)」라고 적지만 표에 조건 시작 행이 없다(생성기 글이라 다음 생성기 조각에서 고친다).

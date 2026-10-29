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
| C1 | **구현됨** | `contracts.manifest` R1~R8 (R8은 Center 배포가 짓는다) | — (닫았다 — Studio가 `Provides`를 짓고 CON-06이 읽는다). — (닫았다). `definition_hash`는 **STU-15에서 사람이 고정한다**([ADR-0060](decisions/0060-pinning-external-definitions.md) — 고정하지 않으면 경고만 한다), `requires.settings`는 Studio가 그림에서 채운다 (`chk:email` → `smtp`, [ADR-0059](decisions/0059-sending-mail-and-webhooks.md)) |
| C2 | **구현됨** | `contracts.hashing`·`signing` V1~V8 | — (닫았다) |
| C3 | **구현됨** | `contracts.events`·`core.run_log` | — (닫았다: `ui_session`은 [ADR-0041](decisions/0041-extension-run-events.md), `case_id`·`queued_s`는 아는 쪽이 넣는다, `confirmations`는 **세는 쪽**이 가르고 `bot_ui_id`는 **Center가 읽을 때** 채운다) |
| C4 | **구현됨** | `contracts.bot_ui`, Center·Bot UI 양쪽 | — (`reserved_for`를 채웠고 `key_expires_at`으로 BUI-05 Center API 키 만료를 닫았다) |
| C5 | **구현됨** | `contracts.center_api`, Center 전부 | — (닫았다 — 지원 종료·참조·삭제, 그리고 **권한표**까지. 패키지 쪽은 키 종류를 보는 관문이 따로 있다: `auth.require_upload`·`require_package_read`·`api.package_access.guard_download`) |
| C6 | **구현됨** | `contracts.approvals`, Center·현장 | — (닫았다) |
| C7 | **구현됨** | `contracts.resources`·`center_keys` | — (닫았다 — 외부 확장은 어댑터 `health`로 본다) |
| C8 | **구현됨** | **`ext.ui_automation.contracts.plan`** | — (닫았다) |
| C9 | **구현됨** | **`ext.ui_automation.contracts.registry`·`console`** | — (관리 콘솔이 읽는 길도 돈다) |
| C10 | **구현됨** | **`ext.ui_automation.contracts.worker_local`** | — (`recent_sessions[]`를 BUI-09가 그린다) |
| C11 | **구현됨** | `contracts.service_app`·`service_kit`(`service_kit.consumer` — 일꾼) | — (닫았다) |
| C12 | **구현됨** (M7) | `contracts.server_runner`·`core.run_snapshot` + **양쪽** — 등록·하트비트·운영 API·배포 설치·작업 실행·저장·재개·결재·**메시지**가 돈다 | — (닫았다). 「기한은 간다」는 [ADR-0061](decisions/0061-waking-runs-whose-timer-is-due.md)이 코드로도 사실로 만들었다 (주기만큼 늦을 수 있다고 C12에 적었다). **PC 위임도 본문이 되어 양쪽이 돈다** ([ADR-0062](decisions/0062-pc-delegation.md) — §3-13). 담고 되살리는 모양은 [ADR-0054](decisions/0054-server-run-state-and-concurrency.md)가 정했고, **재시작을 건너 메시지가 두 번 들어가던 자리**는 [ADR-0058](decisions/0058-absorbed-messages-travel-with-the-snapshot.md)이 닫았다 (ADR-0056이 「재 보지 않았다」고 적어 둔 것 — 재 보니 정말 두 번이었다) |
| C13 | **구현됨** | `contracts.extension`·`core.extensions` | — (닫았다 — 기여 지점마다 읽는 쪽이 있다: 호스트·Studio·Bot UI·콘솔·Center) |
| C14 | **구현됨** | `contracts.bpmn_ext` B1~B16 + `contracts.dmn` | — (닫았다 — 엔진이 수행하고 Studio가 편집·검사하고 예제 50개가 이 형식이다. schema 1에서 **쓰지 않기로 적은 것**은 범위 결정이다) |
| C15 | **구현됨** | `contracts.external_task`, Center `api/external_tasks.py` (15판) + **양쪽** — 부르는 쪽 `core.services.CenterServiceCaller`·UI 자동화 `CenterOps`, 일꾼 `service_kit.consumer`·`apps/adapter_consumer` | — (조각 2~4가 닫았다). 남은 것은 긴 작업이다 (§3-17) |

**열다섯이 모두 「구현됨」이다** (C12가 M7 다섯째 조각에서, C15가 ADR-0102 조각 4에서 올라왔다). 상태 셋의 뜻은 [03-contracts/README](03-contracts/README.md) §상태에 적었다 — 적혀 있지 않아 올릴 때마다 사람이 다시 물었다.

굵게 적은 셋(C8·C9·C10)은 **확장이 소유한 계약**이라 `extensions/ui_automation/…/contracts/`에
있다 (계약 README 원칙 1). CLAUDE.md §7이 「계약 코드 C8~C10·C12가 없다」고 적어 두었는데
**C8~C10은 있다** — C12도 모델·검사와 양쪽이 다 생겼다.

## 2. 문서가 코드와 어긋난 자리 (코드를 고치는 일이 아니다)

**없다.** 마지막 하나(§2-5 — C3 `run_started.bpm_process_id`가 패키지 id인가 그림의 process id인가)는 패키지 id로 정해 엔진·계약을 맞췄다 ([ADR-0086](decisions/0086-run-identity-is-the-package-id.md)).

## 3. 계약 쪽 기능 공백

계약 열다섯의 상태는 §1 표에 있다. PC 위임을 닫았고(§3-13) 그 거리가 드러낸 「도는 서버 실행을 멈출 길이 없다」도 [ADR-0063](decisions/0063-stopping-a-running-server-run.md)으로, 「서버 실행기가 확장 태스크를 꽂지 않는다」(§3-14)도 [ADR-0064](decisions/0064-extension-tasks-on-the-server.md)로 닫았다. 일괄 기동이 드러낸 「서버의 병렬 반복」(§3-15)도 [ADR-0087](decisions/0087-parallel-loop-on-the-server.md)로 닫았다. 바깥 요청(NowView R4)이 드러낸 「외부 확장 주소의 입구」(§3-16)도 [ADR-0097](decisions/0097-external-extension-address-from-center.md)로 닫았다. C15(외부 작업, §3-17)도 조각 1~6과 옛 키 칸 걷기로 닫았다. **남은 것은 §3-18 하나다** — AI 태스크의 거짓 칸을 정리하다(ADR-0105) 드러난 「PC 전환 → 사람 확인」이다.

### 3-18. PC에서 전환을 사람 확인으로 넘기는 길 — **남았다**

C10(`escalated` — 「PC Bot은 확인(CMN-01)으로 넘긴다」)과 C13 §4(「PC는 확인, 서버는 오류 경계」)는 결과를 모르는
실패·전환을 PC에서 **사람 확인**으로 넘긴다고 적었지만, 엔진에 그 길이 없다 — 확장의 `escalate: confirmation`은
PC·서버 모두 **오류 경계 `ESCALATED`**로 간다([ADR-0105](decisions/0105-ai-task-limits-and-instructions.md)가 코드를
`ESCALATED`로 맞췄다 — 전에는 확장의 코드 `ui_escalated`로 올라가 그 경계도 받지 못했다). AI 태스크의 확인 트리거도
같은 길이다. 지금은 그림이 경계를 달아 확인 태스크로 보내면 된다. **먼저 정할 것**: 태스크 안에서 확인으로 멈췄다
「계속」이면 그 태스크를 다시 하는가·건너뛰는가(UI 태스크는 조작한 뒤라 다시 하면 두 번 들어간다).

### 3-17. 바깥 기능을 부르는 길 (Pull) — **닫았다**

[ADR-0102](decisions/0102-calling-outside-is-pull.md)가 「네트워크를 건너는 바깥 호출은 모두 Pull」로 정했고 [C15](03-contracts/C15-external-tasks.md)는 **구현됨**이다.
부르는 쪽 다섯(서버 실행기·실행기 자식·Studio는 `core.services.CenterServiceCaller`, Worker·Tool UI는 UI 자동화의
`CenterOps`)과 일꾼(`service_kit.consumer` — 서비스 앱·모의 앱 열셋, 어댑터 일꾼 `chk-adapter-consumer`)이 붙었고,
옛 길(C11 `POST /v1/ops`·`/manifest`·앱 안의 키, HTTP 어댑터 직접 호출, 서비스 앱 키 배달 ADR-0094, Center의 외부 앱
키·주소 덮어쓰기 ADR-0097)은 걷었다. 남았던 둘도 닫았다:

- ~~긴 작업~~ (조각 6) — **닫았다** ([ADR-0103](decisions/0103-long-external-tasks.md)): 서버 실행기는 한 번 기다려
  (`PARK_AFTER_S`, 기본 20초) 끝나지 않은 일감을 다섯째 기다림 `external_task`로 넘기고 자리를 놓는다. 결과는
  하트비트 주기마다 C15로 묻고, 걷히면 거두고, 받아 간 값을 잃으면 같은 칸으로 다시 올린다.
- ~~C14의 옛 칸~~ — **걷었다**: C14 `chk:serviceCall.key_ref`·`chk:process.service_keys`와 C1
  `requires.service_apps[].key_ref`·`task_key_refs`·R4가 모델·빌드·검사에서 없어졌다. 예제 생성기(`exdsl.py`)가
  더 적지 않아 업무 예제 55개에 없고, 옛 그림·패키지는 모르는 칸으로 읽어(원칙 3) **B7이 경고 한 줄**로
  말한다(`old_key_field`). 선택 칸을 걷은 것이라 판은 올리지 않았다(C4의 키 칸과 같은 결).
  남겨 둔 것은 **옛 받는 쪽을 위한 칸**뿐이다 — C3 `service_call.key_ref`(늘 빈 글), C4
  `Readiness.missing_key_refs`(늘 빈다), `extension_api.PreflightTarget.key_refs`(늘 빈다).

### 3-13. PC 위임 — **닫았다**

[ADR-0062](decisions/0062-pc-delegation.md)가 정했고(선택지 셋을 두고 골랐다) **계약 다섯·엔진·
꽂는 쪽 둘·현장에서 값이 올라오는 길이 모두 돈다**. 그래서 ADR 끝의 **「증명할 다섯」이 다 찼다**:
서버 실행이 위임으로 멈추면 **자리를 놓고**, 재시작을 건너 **작업이 하나**이며(작업 id가 스냅샷과
함께 간다), **선언한 `outputs`가 값으로 돌아와** `chk:call.output`이 적은 변수에 담기고, 실패·거절은
**오류 경계가 받고**, Studio 시험 실행은 **케이스가 적어 둔 결과로** 끝까지 간다. 지키는 시험은 셋이다
— `tests/test_core_events.py`(엔진)·`test_studio_runner.py`(케이스 포트)·`test_server_runner_delegation.py`
(실행기·Center, 마지막 하나는 **PC를 진짜 자식 프로세스로 돌려** 현장이 만든 값이 서버 변수에
담기는 것까지 본다). **업무 예제에도 들어왔다** — BX-16이 쓰던 사내 확장 우회(`center-jobs`)를
걷어내고 `chk:call.delegate`로 다시 썼다(2026-10-16). 그 예제가 제품 흠 하나를 드러냈다:
`import_example`이 **위임 대상까지 작업 폴더로 끌어와** 매니페스트가 그 Bot의 요구사항을 제
것처럼 모았다(BX-16이 BX-17의 `ui_task`를 요구해 서버 Bot이 `not_ready`가 됐다).

**B14의 `delegated_outputs`도 왔다** — Studio가 Center에서 Bot 패키지 목록(C5)을 받아 매니페스트의
`outputs`를 모아 실행 전 검사에 넘긴다(`service_catalog.declared_outputs` → `preflight.inspect`).
그래서 「그 Bot이 돌려주지 않는 값을 받는다」를 **그림에서** 안다 — 실행할 때 알면 늦다.
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
된다(Bot UI는 확장 단위로 띄운다) — 값이 같고 거르는 자리만 다른 목록은 조용히 갈라진다.

**함께 드러난 것 하나** — Center의 C7 확장 자원이 `bot_uis`만 읽고 있었다. 계약은 처음부터
「C4·**C12** 보고」라고 적어 두었는데(C7 `installed_on`) 코드가 덜 됐고, 실행기도 등록에
`extensions=[]`를 싣고 있었다. 그래서 **서버에만 깔린 확장은 Center가 모르고**, 그것을 요구하는
멀쩡한 서버 Bot의 **배포가 「확장 누락」으로 막혔다**. 양쪽을 고쳤다.

남은 두 가지는 **공백이 아니라 선언의 일**이다: 서버에서 돌 태스크 종류를 가진 확장이 아직
하나도 없고(내장은 `ui-automation` 하나, `ui_task`는 PC 전용이다), 그 길이 정말 열렸는지는
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
  - **「감시 모드 시작」은 두지 않기로 닫았다** ([ADR-0053](decisions/0053-no-watch-mode-in-studio.md)) — 「먼저 정할 것」이 「시험 실행이 기다려도 되는가」였는데 질문이 그보다 **앞에** 있었다: **일정(cron)을 읽는 자리가 아직 어디에도 없다**(C14는 현장이 읽는다고 적어 두었고 Bot UI·서버 실행기에 그 코드가 없다). 개발 도구가 먼저 가지면 「Studio에서는 도는데 현장에서 안 된다」의 새 원천이 된다. 트리거가 깨우는 그림은 **시험 케이스의 `messages`**로 보고, 시험 실행은 **판정이 있는 한 번**으로 남는다.


### 4-9. CON-02 — 콘솔 집계 시험

**화면·「확인률」·「배포된 Bot UI」를 닫았다** (`app/bots`). 확인률은 C3 `run_finished`에 선택 칸 `confirmations`를 더해 잰다 — 가르는 것은 **세는 쪽의 일**이고(Center는 줄을 다시 읽어 세지 않는다) 보내지 않은 옛 기록은 **분모에서 빠진다**.

**「배포된 Bot UI」도 닫았다** ([ADR-0046](decisions/0046-no-wildcard-pc-deployment.md)). 여기 적혀 있던 「먼저 정할 것」(**C5가 대상을 푸는 길**)은 **없었다** — 「그룹 배포」는 계약에도 코드에도 아예 없고, 전체(`*`) 배포는 **PC 쪽에 없다**(C2는 `"*"`를 서버 배포에만 주고 `DeploymentTarget.matches`·V6도 그렇다). 그래서 PC 배포는 전부 `bot_ui_id` 하나를 가리키고 「배포된 Bot UI」는 **`target.id`를 겹치지 않게 센 수**다. 재료는 CON-02가 이미 받아 둔 둘(C5 배포 목록·Bot UI 목록)로 끝났고 **계약이 늘지 않았다**. 함께 고친 것 둘: Center 네 자리가 대상 종류를 가리지 않고 `"*"`를 풀던 것(이제 한 함수가 짓고 `POST /deployments`는 409 `wrong_target`), 그리고 `summarize`가 **제가 세지 않은 칸**(`blocked`·`deployments`)을 0으로 들고 돌아와 실제 값을 덮던 것(끝난 실행이 있는 판은 「실행 불가」가 늘 0이었다).

- **콘솔 집계 함수의 셈을 vitest가 잰다** (`web`에서 `pnpm test`, CI 웹 잡에 한 걸음). **2026-10-11에 「시험 판을 들이지 않는다」로 정했던 것을 2026-10-13에 뒤집었다** — 들이지 않는 쪽의 값은 「CI가 짧다」였고, 치른 값은 **덮어쓰기 흠**(끝난 실행이 있는 판의 「실행 불가」·「배포된 Bot UI」가 늘 0이던 것)이었다. 글로 막는 것은 같은 흠의 재발까지이고 **셈이 틀리는 것은 못 막는다**. 들이면서 한 일 둘: 세는 코드를 **화면을 모르는 모듈**로 갈랐고(`lib/summary.ts` — 페이지는 `server-only`를 끌고 와 단위 시험에서 부를 수 없다), 브라우저·React를 **띄우지 않게** 했다(jsdom·플러그인이 없어 CI에 느는 것은 몇 초다). 재는 것은 성공률·재생률·**확인률의 분모**·최근 20회 끊기·최근 성공 시각·`RunFields`가 남의 칸을 들고 오지 않는가·PC 수 세기·키 참조 모으기다.

## 5. 공백은 아니지만 적어 둘 것

- **편의 접근자 둘을 지웠다** (2026-10-16) — `ExtensionHost.adapter_operations()`(창·어댑터는 정의의 `m.adapter.operations`를 직접 읽는다)와 `secret_config_keys()`(`credentials.py`가 `configuration()`에 `.secret`을 걸어 본다). **쓰는 길이 둘이면 한쪽만 고친다.** 함께 적어 둔 `studio_editors()`는 **쓰인다** — `editor(task_type)`가 그것을 부른다(단수 메서드 뒤에 있어 「호출자 없음」으로 잘못 적혀 있었다). 시험은 **제품이 쓰는 길**로 고쳐 같은 것을 본다.
- **C1의 「아는 값」 둘을 정했다** (2026-10-16) — `KNOWN_SETTINGS`는 **쓰는 쪽을 만들었다**(R11: `requires.settings`가 아는 값인가 — R9와 같은 까닭이고, 지금 Studio가 넣는 것은 `smtp` 하나뿐이라 올라간 패키지는 다 지난다). `KNOWN_BUILT_BY`는 **검사하지 않는 쪽으로 정했다** — 남의 도구로 만든 올바른 패키지를 거부하게 되므로 열린 문자열이 맞다. 그 까닭을 **상수 옆에 적어** 두어 다음 사람이 「검사가 없다」고 또 적지 않게 했다.
- **`extension_api`에 우리 호출자가 없는 상수들은 정상이다** (`SEVERITY_INFO`) — 그 패키지는 **확장 저자에게 주는 API**(C13)다. 우리 코드가 다 쓰는지로 셈하지 않는다. (`HOST_SERVER_RUNNER`·`RUN_LOCATION_SERVER`는 2026-10-16에 쓰는 쪽이 생겼다 — [ADR-0064](decisions/0064-extension-tasks-on-the-server.md). 그때 그 둘을 대조하다 §3-14를 찾았다.)
- **도메인 목록의 정의는 `manifest.py` 하나다** — `KNOWN_DOMAINS`·`PC_ONLY_DOMAINS`를 `bpmn_ext`(C14 B8·B6)와 `core`(사전 점검·AI 태스크)가 import해 쓴다. 자리가 C1 쪽인 것은 층 때문이다 (`bpmn_ext`가 `manifest`를 import하므로 거꾸로는 순환이다). **두 벌로 되돌리지 않는다** — 값이 같고 거르는 자리만 다른 목록이 둘이면 조용히 갈라진다(`triggers[].kind`가 그랬다). `tests/test_contracts_bpmn_ext.py`가 **같은 객체인지**(`is`) 본다.
- **「C13 `docs_url`·`owners`, C11 `Operation.json_schema`를 콘솔이 보이지 않는다」는 닫았다** (2026-10-18) — 대조해 보니 **셋 중 둘은 계약에 없는 칸**이었다(C13에 `owners`가 없고, C11 작업의 스키마는 `input_schema`·`output_schema`이며 STU-14·STU-03 툴팁이 그것으로 칸을 그린다). 남은 `docs_url`은 STU-15·BUI-11 상세 맨 위에 「설명 문서」로 보인다. **없는 칸을 공백으로 적어 두면** 다음 사람이 그 칸을 만들러 간다.

## 6. M6 첫째 — 현장 시나리오 3: 돌았다, 사람이 한 번 더 (CI가 못 보는 자리)

M6의 첫째 기준(「**시나리오 3**(BX-04)이 Windows 현장 PC에서 Center 배포를 거쳐 통과」)을 **2026-10-17에 Windows 11 PC(일반 사용자, 한글 사용자 이름)에서 돌렸다** — Studio 올리기 → Admin 승인·배포 서명 → Bot UI 설치·「준비됨」 → Center 작업 지시 → 포털 표 읽기(Chromium) → 회계 프로그램 4줄 입력(UIA) → 합계 검산 → 메일 (`success`, 약 50초). 서버 Bot인 시나리오 1·2·4는 M7 인수 시험으로 넘겼다 ([ADR-0055](decisions/0055-m6-field-scenario-is-scenario-3.md)). 그 PC에서 막힌 것 중 **제품의 흠은 고쳤고**(Worker 화면 스레드·예제 폴더·설정 저장 뒤 사전 점검·SMTP 주소 검사), 환경 쪽은 `04-setup` §7에 적었다. **사람이 할 길이 없어 Claude가 대신한 자리 하나**(§6-1)도 닫았으므로, 남은 것은 **사람이 그 길로 한 번 더 돌리는 것**뿐이다 — 그때 이 기준을 체크한다. (첫 실행 전 앱 주소 명부는 Bot UI가 하트비트 뒤에 받아 두게 해 닫았고(C13 「전송」), 이름 없는 표의 「역할 + 이름」 칸은 이름을 브라우저 규칙대로 짓게 해 닫았다.)

### 6-1. BUI-06이 데스크톱 화면을 담지 못했다 — 닫았다

리허설 때는 셀렉터 등록 창이 웹만 지어, 회계 프로그램 화면(`accounting.taxbook.sheet`)을 **M4 인수 시험과 같은 정의로 C9에 직접 올렸다**. 이제 BUI-06의 「방식 › 데스크톱 창」이 창 고르기 → 창에 붙기 → UIA 분석 → 검증 → 등록(`platform: desktop` + 창 조건)을 한다 (C10 §5 `GET /registration/windows`·`POST /registration/desktop`). 붙기만 하고 **창을 띄우거나 닫지 않는다**. 사다리는 C8 데스크톱 순서이고 **창 안에서 겹치는 값은 넣지 않는다** — 진짜 창을 훑어 보니 Qt 라벨 셋이 AutomationId를, 표와 그 안쪽 틀이 또 하나를 나눠 쓰고 있었다. 데스크톱의 「직접 고르기」·「표시」는 아직이다(꺼 두고 툴팁으로 말한다) — 「분석」으로 담을 수 있어 막는 것이 아니다. 시험은 `tests/test_ui_registration_desktop.py`(진짜 창은 진짜 HTTP로, Windows만).

## 7. 화면 문서에 「아직」으로 적힌 자리 (M6 셋째 기준)

§1~§4는 계약·화면을 **코드의 호출자**로 대조했다. 이번에는 거꾸로 **화면 문서의 「상태」 줄이 「아직」이라고 적은 것**을 모았다(2026-10-18) — 화면이 문서와 **맞기는 하지만**(문서가 「아직」이라고 정직하게 적었다) 기준의 뜻은 「문서가 약속한 화면이 돈다」라서 여기 둔다. 대조하다 **낡은 「아직」 셋**(C10 §2의 데스크톱 분석, STU-01 [C]·STU-14의 끌어다 놓기)은 그 자리에서 고쳤다. 먼저 정할 것이 없던 하나(BUI-04 「최근 실행」 — BUI-02가 읽는 기록 파일에서 그 Bot의 마지막 실행을 고른다)는 **닫았다**. 7-3(BUI-06 데스크톱 「직접 고르기」·「표시」)도 **닫았다** — 전역 훅 없이 커서·Ctrl을 읽고 테두리는 Bot UI가 띄운다(스파이크 s11, [ADR-0072](decisions/0072-desktop-pick-without-hooks.md)). 7-2(BUI-08이 등록 탭의 화면을 이어 쓰기·BUI-06 「시험...」)도 **닫았다** — 등록 세션에 계획을 싣는 길(C10 `…/plan`)을 더했다. 7-4(STU-06 「나누기」)도 **닫았다** — 노드 하나를 새 PC Bot으로 옮기고 그 자리를 위임 호출로 바꾼다([ADR-0071](decisions/0071-splitting-a-task-into-a-pc-bot.md)). 7-5(STU-10 나머지 분류)도 **닫았다** — 칸마다 읽는 곳을 대조해 테마·확장별 설정은 켜고, 읽는 곳이 없는 메일·비밀·공급자·temperature·화면 인식 모델·캔버스 팔레트는 화면 문서에서 걷었다([ADR-0073](decisions/0073-studio-settings-only-what-is-used.md)). 7-6(STU-13 「이 스텝까지 시험」·계획 굳히기)도 **닫았다** — Studio 시험 실행이 이미 Worker에 직접 붙으므로 Bot UI로 넘기지 않고 편집기에 같은 문맥(Worker 자리·개발용 키·`service.key_ref`)을 주었다([ADR-0074](decisions/0074-ui-task-editor-runs-on-the-worker.md)). 7-7(서비스 앱 콘솔 → CON-01)도 **닫았다** — Center 콘솔 주소는 서비스 앱 콘솔의 설정 하나로 받고 C11은 그대로다([ADR-0075](decisions/0075-service-console-links-to-center-console.md)). 7-8(ADM 창)은 **짓지 않기로** 닫았다 — 서명은 CLI 하나에 남는다([ADR-0076](decisions/0076-no-admin-window-yet.md)). 대조하다 **CLI에 서버 배포 서명이 없던 것**(`deploy --server`)을 찾아 함께 메웠다. 7-10(셀렉터 등록을 Bot UI 밖으로)도 **닫았다** — 확장의 도구는 Tool UI가 띄우고 Worker는 Bot UI 것을 빌린다(`apps/tool_ui`, 기여 지점 `tool_ui.tools`, [ADR-0077](decisions/0077-tool-ui.md)).

| 자리 | 화면 | 남은 것 | 먼저 정할 것 |
| --- | --- | --- | --- |
| 7-11 | STU-04 「요소별 편집기」의 나머지 | 폼이 있는 것은 **AI 태스크**(`ai_task_editor.py`)·**결재·확인**(`approval_editor.py`)·**보내기**(`send_editor.py` — 메일·웹훅)·**BPM 프로세스 호출**(`call_editor.py` — PC 위임 포함)·서비스 앱 태스크(STU-14)·확장 태스크(STU-13)·순서 흐름의 조건식·스크립트 태스크뿐이다. **게이트웨이·이벤트·규칙(DMN 격자)·받기·데이터 객체·반복(`chk:loop`)·BPM 프로세스(정의) 자체**는 「JSON」 탭으로만 고친다 — 화면 문서의 표는 그 폼들을 약속하는데 상태 줄이 없어 「돈다」로 읽혔다(2026-10-23, 결재 폼이 「이름·설명」만 보여 드러났다). AI 태스크 폼에 아직 없는 것: 「재생 명세」 상태·「명세 잊기」(속성 패널이 패키지의 `memory/specs.json`을 모른다), 목표 미리보기 | 없다 — 요소마다 C14 모델이 칸을 정해 두었다. 보내기·AI 태스크는 화면 문서가 C14에 없거나 **엔진이 읽지 않는** 칸(웹훅 헤더·메일 HTML 여부, AI의 시작 주소·로그인·창 제목·「복합」 환경·환경별 도구 검증)을 약속하고 있어 **계약에 있고 엔진이 읽는 칸만으로** 문서를 다시 썼다. `chk:aiTask`의 `forbidden_actions`·`confirm_triggers`·`limits.timeout_s`는 **엔진이 읽고 폼에도 있다** ([ADR-0105](decisions/0105-ai-task-limits-and-instructions.md)). C14에 있는데 쓰이지 않는 것은 `web`(웹 환경을 주는 확장이 없다)뿐이다 |

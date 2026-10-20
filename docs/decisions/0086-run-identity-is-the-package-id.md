# ADR-0086. 실행이 말하는 `bpm_process_id`는 **패키지 id**이고, 실행하는 쪽이 엔진에 넘긴다

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-20 |
| 관련 | [C3](../03-contracts/C3-run-events.md) `run_started`, [C6](../03-contracts/C6-approvals.md), [C11](../03-contracts/C11-service-app-common.md) `caller`, [C1](../03-contracts/C1-package-manifest.md) `id`·`process_id`, [ADR-0085](0085-virtual-worker-resource.md), 09-gaps §2-5 |

## 배경

엔진(`Engine.start`)은 C3 `run_started.bpm_process_id`에 **그림의 process id**(`Proc_…`)를 적었다. 결재 요청(C6, `core.requests`)과 서비스 앱 호출 봉투(C11 `caller.bpm_process_id`)도 같았다. 그런데 C3 예시는 `erp.order-entry`(패키지 id)이고, 작업·배포(C4·C5·C2)·C12 `running[]`·위임(C14 `chk:call.delegate`)은 모두 **패키지 id**로 말한다. 그래서 실행 기록을 Bot으로 묶는 자리가 어긋났다 — CON-01 「Bot」 거르기는 패키지 id를 넣으면 아무것도 안 잡히고, 가상 직원은 패키지 id와 매니페스트의 `process_id`를 **함께** 봐야 일괄을 잡았고(ADR-0085), BUI-04 「최근 실행」은 Bot(패키지 id)마다 찾는데 기록에는 그림 id가 있어 **늘 비어 있었다**.

엔진은 자기가 도는 패키지를 모른다 — Studio 시험 실행은 패키지 없이 작업 폴더에서 돈다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| **A. 패키지 id. 실행하는 쪽이 `Engine.start(bpm_process_id=…)`로 넘긴다** — `version`이 이미 그렇게 온다 | 계약 열넷이 한 이름으로 말한다. 거르는 쪽(CON-01·가상 직원·BUI-04)이 짝 맞추기를 하지 않는다 | 실행하는 쪽 셋이 한 칸씩 더 넘긴다. 이미 올라간 옛 기록은 그림 id로 남는다 |
| B. 계약을 그림 id로 고친다 | 엔진이 바뀌지 않는다 | C3만 다른 이름을 쓴다 — 작업·배포·결재·C12와 잇는 모든 자리가 매니페스트를 읽어 짝을 지어야 한다. 한 패키지의 그림 id는 바뀔 수 있고(정의를 갈아 끼우면) 패키지 id는 Bot의 신원이다(C1) |

## 결정

**실행이 바깥에 말하는 `bpm_process_id`는 패키지 id다.** 엔진은 `Engine.start(..., bpm_process_id=…)`로 받아 `Run.bpm_process_id`에 담고, `run_started`·C6 결재 요청·C11 `caller`가 그것을 쓴다.

- **주는 쪽은 셋이다** — Bot UI 실행기(설치된 패키지의 매니페스트 `id`), 서버 실행기(`bot.id`), Studio 시험 실행(작업 폴더 기록의 `id` — 내보낼 때 매니페스트 `id`가 되는 값이다).
- **주지 않으면 그림 id다** — 패키지 없이 엔진을 부르는 시험·도구가 깨지지 않게. 제품의 실행하는 쪽은 늘 준다.
- **호출(`callActivity`)의 안쪽 실행은 바깥의 것을 물려받는다** — `run_id`가 같은 한 실행이라 C6·C11이 안쪽 그림 id를 말하면 안 된다.
- **스냅샷과 함께 간다** (`core.run_snapshot` STORED) — 되살린 서버 실행이 결재를 올릴 때도 같은 이름이다. 칸이 없는 옛 스냅샷은 그림 id로 읽는다.
- **그림 id를 쓰는 자리는 남는다** — 재생 명세의 열쇠(`memory/specs.json`, `spec_key`)는 **패키지 안의 정의**를 가리키므로 그림 id 그대로다. 스냅샷의 「그림이 맞나」 대조도 그렇다.
- **짝 맞추기를 걷는다** — 가상 직원의 「접수 Bot의 실행」은 실행 기록의 `bpm_process_id`가 **그 패키지 id인 것**뿐이다(매니페스트 `process_id`를 함께 보지 않는다).

## 결과

- 쉬워지는 것: 실행 기록을 Bot으로 거르는 자리가 모두 같은 글자를 비교한다(CON-01 「Bot」·`?virtual_worker=`·BUI-04 「최근 실행」·UIA-03 「Bot」).
- 포기하는 것: 이 결정 전에 Center에 올라간 실행 기록은 그림 id로 남고 고쳐 쓰지 않는다(아직 운영 데이터가 없다). 그 기록은 Bot으로 거르면 잡히지 않는다.
- 다시 볼 조건: 한 패키지가 진입 정의를 여럿 갖게 되어(지금은 C1 `process_id` 하나) 「어느 정의로 돌았나」를 실행 기록에서 알아야 하면 — 그때는 이름을 바꾸지 말고 C3에 칸을 더한다.

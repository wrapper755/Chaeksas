# ADR-0112. 전환할 때 확장이 사람에게 보일 검토 자료를 넘긴다 — `TaskFailed(review=…)`와 C6 표 값

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-30 |
| 관련 | 계약 C6(`review`), C10(`StepResult`), C13 §4(`executor`), C3(`human_requested`), [ADR-0018](0018-extensions.md), [ADR-0041](0041-extension-run-events.md), [ADR-0042](0042-extension-contributed-panels.md), [ADR-0078](0078-field-approval-shows-what-to-judge.md), [ADR-0106](0106-pc-escalation-asks-a-person.md), 09-gaps §3-18 |

## 배경

[ADR-0106](0106-pc-escalation-asks-a-person.md)이 PC의 전환(UI 태스크 `ui_escalated`·`worker_restarted`)을 현장 확인
CMN-01로 넘겼지만 창의 [R] 「검토 자료」는 비어 있었다. 화면 문서는 「시도한 로케이터와 실패 사유 표」를 약속했는데
확장의 `TaskFailed`에 그것을 실을 자리가 없었다. 엔진의 확인 요청(`Pending.review`)은 이미 있고, 그 본문은
`.field-requests.jsonl`(ADR-0078)을 거쳐 PC 실행기가 CMN-01에 그대로 건넨다 — 비어 있는 것은 **확장 → 엔진** 한 칸과
그 재료(Worker가 사다리에서 무엇을 해 봤나)다.

지켜야 할 것이 셋이다.

- **플랫폼은 확장이 무엇인지 모른다** (ADR-0018·0042) — 엔진·CMN-01에 「로케이터」라는 말이 들어가면 안 된다.
- **셀렉터는 C10 경계를 넘지 않는다** (C10 머리말 — 예외는 셀렉터 등록 §5뿐이다). 그래서 표에 로케이터 **값**을 실을 수
  없다. Playwright·UIA의 예외 글에도 셀렉터가 들어 있어 실패 사유를 글 그대로 옮길 수도 없다.
- **원칙 6** — 실행 기록에는 남지 않아야 한다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. `TaskFailed(review=…)` — C6 `review`와 같은 모양(이름 → 값). 값 하나로 **일반 표**(`{headers, rows}`)를 C6에 정의하고 CMN-01이 표로 그린다. Worker는 C10 `StepResult.attempts`로 **종류와 결과 코드만** 준다 | 플랫폼은 「이름 → 값」과 「표」만 안다. 확장마다 제 것을 실을 수 있다. 셀렉터가 경계를 넘지 않는다 | C6 값에 표 모양 하나가 생긴다(Center 콘솔은 아직 표로 그리지 않는다) |
| B. `TaskFailed(tried_locators=[…])` | 뜻이 바로 보인다 | 플랫폼 API에 UI 자동화 말이 들어간다. 다른 확장은 쓸 수 없다 |
| C. 확장이 CMN-01에 위젯을 기여(ADR-0042 위젯 기여) | 확장이 마음대로 그린다 | 실행 프로세스(자식)와 결재 창(PC 실행기)이 다른 프로세스라 위젯을 건넬 길이 없다. Studio·PC 실행기 둘에 코드 기여가 생긴다 |
| D. 로케이터 값까지 실어 보인다 | 사람이 셀렉터를 본다 | C10 경계를 깬다. 현장 사람은 셀렉터를 고칠 수 없고 고칠 사람(등록 담당자)은 UIA-03에서 본다 |

## 결정

**A.** 확장이 전환할 때 사람에게 보일 검토 자료를 `TaskFailed(review=…)`로 넘기고 엔진이 그것을 확인 요청의 C6
`review`로 옮긴다. 표는 C6의 일반 표 값이다.

1. **`extension_api` 1.5** — `TaskFailed`에 선택 칸 `review: Mapping[str, Any]`(C6 `review`와 같은 모양 — 이름 → 값)와
   도우미 `review_table(headers, rows)`를 더한다. 칸을 더한 것이라 부 번호다(`api: ">=1,<2"`인 확장이 그대로 돈다).
   **`escalate`가 없으면 쓰지 않는다** — 확인이 없으면 보일 사람도 없다.
2. **표 값은 C6이 정한다** (`contracts.approvals.review_table`·`as_table`): `{"headers": [글], "rows": [[값]]}` — 열쇠가
   정확히 그 둘이고 줄마다 칸 수가 머리줄과 같을 때만 표다. 아니면 지금처럼 「열쇠: 값」 줄이다(뜻을 어림하지 않는다).
   CMN-01은 표를 읽기 전용 표로 그린다. 확인은 Center로 올라가지 않으므로(C6) 콘솔 결재 화면은 이 모양을 아직 따로
   그리지 않는다 — 업무 결재의 `review`가 이 모양이면 콘솔은 지금 규칙대로 보인다.
3. **엔진은 옮기기만 한다** — `escalate_to_person(…, review=…)`이 `Pending.review`에 담는다. 그 뒤 길은 업무 결재와
   같다: 실행 프로세스가 `.field-requests.jsonl`에 C6 본문으로 쓰고 PC 실행기가 CMN-01에 건네며 **끝나면 지운다**.
   C3 `human_requested`에는 `review`가 없으므로 **실행 기록에는 남지 않는다**. 엔진은 값을 다시 거르지 않는다 — `review`는
   원칙 6의 예외 자리이고, 무엇을 보일지는 그것을 아는 확장이 정한다.
4. **오류 경계로 갈 때는 버린다** — 서버 실행(늘 오류 경계)·`ESCALATED`를 이름으로 받는 경계가 있을 때는 확인이 없으므로
   `review`는 어디에도 가지 않는다. 서버에서 사람에게 묻는 길이 생기면(ADR-0106 「다시 볼 조건」) 같은 칸이 Center
   결재함으로 간다.
5. **UI 자동화가 싣는 것** — Worker는 C10 `StepResult`에 선택 칸 `attempts[]`(`{source: ladder | heal, type, result,
   count?}`)를 싣는다. **로케이터 값·예외 글은 싣지 않는다**(C10 경계). `result`는 `not_found`·`ambiguous`·`error`·
   `heal_unmatched` 넷이다. 수행기는 전환하면 `review`를 짓는다:
   - `ui_escalated` → `{"요소": <시맨틱 키>, "시도한 로케이터": 표(순서·출처·종류·결과)}`. 치유를 부르지 못했으면 그 줄도
     표에 넣는다(「치유 — 닿지 못함」).
   - `worker_restarted` → `{"끝낸 스텝": 표(순서·요소·동작)}` — 무엇까지 했는지 보여야 「계속」·「중단」을 고른다.
     입력한 **값**은 넣지 않는다(동작 이름뿐이다).

## 결과

- 쉬워지는 것: CMN-01 [R]이 「무엇을 해 봤고 왜 막혔나」를 보인다. 다른 확장도 같은 칸으로 제 검토 자료를 싣는다.
  플랫폼 코드에는 「로케이터」가 없다.
- 포기하는 것: 표에는 로케이터 **값**이 없다 — 종류(`role`·`css`…)와 결과뿐이다. 셀렉터를 보고 고치는 것은 등록 담당자가
  UIA-03(C8 보고의 `tried`)에서 한다.
- 다시 볼 조건: 업무 결재가 표 값을 쓰기 시작하면 Center 콘솔(CON-04)도 같은 표로 그린다. 서버 확인이 생기면 4를 다시 본다.

# C6. Center API: 결재

| 항목 | 값 |
| --- | --- |
| 상태 | **구현됨** (2026-10-09, [09-gaps](../09-gaps.md) §1 대조) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Bot UI(실행 중 Bot)·서버 실행기 → Center ↔ Center 콘솔(결재함) |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/approvals.py` (import `chaeksas.contracts.approvals`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c6-approval-create-request.json`](../../packages/contracts/schemas/c6-approval-create-request.json) · [`c6-approval-info.json`](../../packages/contracts/schemas/c6-approval-info.json) · [`c6-answer-request.json`](../../packages/contracts/schemas/c6-answer-request.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md), [0017](../decisions/0017-web-nextjs-design-system.md), [0080](../decisions/0080-approval-assignees.md)·[0081](../decisions/0081-answering-on-behalf.md) |
| 관련 화면 | CON-04 결재함, CMN-01, BUI-05, STU-04(결재 위치) |

## 목적

BPM 프로세스의 결재(UserTask)를 Center 결재함으로 올린다. 결재자가 콘솔에서 답하면, 실행하는 쪽이 그 답을 받아 실행을 이어 간다.

> 상태: **Center 쪽·결재함(CON-04)·현장 연결이 돈다** ([ADR-0038](../decisions/0038-approval-request-channel.md)).
> - 엔진이 `where`를 고른다 (`location` + 실행하는 쪽의 기본값 — Bot UI는 BUI-03 「원격 결재」).
> - `center`면 실행기가 요청 파일(`runs/<run_id>.requests.jsonl`)에 이 계약의 `ApprovalCreateRequest`를 그대로 쓰고, Bot UI가 하트비트 뒤에 올린다.
> - 현장(`field`) 결재·확인도 같은 본문을 `runs/<run_id>.field-requests.jsonl`에 쓴다 ([ADR-0078](../decisions/0078-field-approval-shows-what-to-judge.md)) — **올리지 않고** CMN-01이 제목·설명·검토 자료를 읽는다. 끝나면 지운다.
> - 답·회수·만료는 하트비트(`approvals[]`)로 내려와 제어 파일을 거쳐 실행기에 간다. 받아 간 것은 `approval_acks`로 알린다 — 지금 기다리지 않는 결재의 답은 `accepted: false`(`not_waiting`)다.
> - 회수·만료는 실행하는 쪽에 **답 없이 끝남**(`TaskFailed` `APPROVAL_WITHDRAWN`·`APPROVAL_EXPIRED`)으로 간다. 오류 경계가 있으면 그리로, 없으면 실행이 실패로 끝난다.
> - 현장에서 먼저 답하면 Bot UI가 `DELETE …?reason=answered_in_field`로 거둔다.
>
> 상태: **결재 담당자·대리 답도 돈다** ([ADR-0080](../decisions/0080-approval-assignees.md)·[ADR-0081](../decisions/0081-answering-on-behalf.md)) — 엔진이 그림의 담당자를 풀어 싣고(서버 스냅샷에도 간다), Center가 `?assignee=`로 거르고 대리 답용 키를 담당자와 대조하며, `answered_via`가 하트비트를 거쳐 C3 `human_answered`까지 간다. CON-04에 「담당」 칸·거르기가 있다.
> - **결재 읽기는 콘솔 토큰과 대리 답용 키뿐이다** — 권한표 그대로다. 실행하는 쪽 키로는 읽지 못한다(검토 자료가 업무 값이다. 답은 하트비트로 받는다).

- **Center로 올라가는 것은 결재(`approval`)뿐이다.** 확인(실행 중 막힘, `confirmation`)은 화면 앞 사람만 답할 수 있으므로 올리지 않는다 (용어집 §3). 서버 Bot에는 확인이 없다 (C1 R2).
- PC Bot은 답이 올 때까지 실행 자리를 쥐고 기다린다 (ADR-0014 §5). 서버 Bot은 상태를 저장하고 기다린다 (ADR-0015).

## 전송

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /api/v1/approvals` | Bot UI·서버 실행기 키 | 결재 요청 올리기 |
| `DELETE /api/v1/approvals/{request_id}` | 올린 쪽 키 (`reason: "answered_in_field"` 또는 `"run_ended"`) / 관리자 토큰 (`reason: "admin_withdraw"`) | 회수 |
| `GET /api/v1/approvals?state=&bpm_process_id=&host=&assignee=` | 읽기·관리자 토큰 / 대리 답용 키 (**담당인 것만**) | 결재함 목록 |
| `GET /api/v1/approvals/{request_id}` | 읽기·관리자 토큰 / 대리 답용 키 (**담당인 것만**, 아니면 404) | 하나 |
| `POST /api/v1/approvals/{request_id}/answer` | 관리자 토큰 (콘솔 BFF, `X-CHK-Actor`) / 대리 답용 키 (`X-CHK-On-Behalf-Of`, **담당자일 때만**) | 답하기 |

**답 전달:**

- PC: C4 하트비트 응답 `approvals[]`로 내려가고, Bot UI가 `approval_acks[]`로 받았다고 알린다.
- 서버: C12 (M7).
- **ack가 올 때까지 매번 다시 내려간다** (`delivered = 0`이면 다시 싣는다). 그래서 실행하는 쪽은 **지금 넣을 수 없는 답을 ack하지 않고 그냥 둔다** — 서버 실행기에서는 **빈자리가 없을 때**가 그렇다(기다리던 실행이 이어 가면 자리를 다시 쥐므로 상한을 넘기면 하트비트가 스스로 막힌다, C12). **거절로 적지 않는다**: `accepted: false`는 결재를 `open`으로 되돌리며 **답을 지우므로**(아래) 사람이 답한 결재가 버려진다. ack하지 않으면 다음 주기에 그대로 다시 온다.

**식별자·멱등성·소유:**

- `request_id`는 실행하는 쪽이 `apr_<run_id>_<node_id>_<node_instance>` 형식으로 만든다.
- 같은 키가 같은 `request_id`와 같은 본문을 다시 올리면 200 (기존 그대로).
- 다른 키가 올리거나 본문이 다르면 409 `idempotency_conflict`.
- 결재 요청은 올린 키에 묶이고, 답은 그 키에게만 전달된다. Center는 `run_id`도 C3 소유와 대조한다. 다른 키가 만든 실행이면 403 `run_owner_mismatch`.
- 답은 한 번만 받는다. 두 번째 답은 409 `already_answered`.

**행위자:** `answered_by`는 본문에서 받지 않는다. 콘솔 BFF가 로그인 세션의 이름을 `X-CHK-Actor` 헤더로 보낸다. OIDC 전에는 콘솔이 「답하는 사람 (자칭)」 입력값을 세션 이름으로 쓰고, 화면에 「자칭」으로 표시한다. **대리 답이면 `answered_by`는 그 사람, `answered_via`는 키 이름**이다 (아래). 콘솔로 답하면 `answered_via`는 없다.

**결재 담당자** ([ADR-0080](../decisions/0080-approval-assignees.md)):

- `assignees[]`는 실행하는 쪽이 그림(C14 `chk:approval.assignees`)에서 풀어 싣는다. 본문의 일부라 멱등 대조에 들어간다.
- `?assignee=<이름>`은 그 이름이 `assignees`에 있는 결재만 준다. 이름은 앞뒤 공백을 걷고 NFC로 맞춘 뒤 **글자 그대로** 비교한다 (`contracts.approvals.normalize_assignees`).
- **관리자 토큰은 담당자로 막지 않는다** — 콘솔의 이름은 자칭이라 막아도 증명이 아니다. 콘솔은 보이고 거르기만 한다.
- 담당자 이름은 업무 값이 아니라 30일 삭제 대상이 아니다 (`answered_by`와 같다).

**대리 답** ([ADR-0081](../decisions/0081-answering-on-behalf.md)) — 대리 답용 키(C7 `type: relay`)로 부른다.

- 사람 이름을 **`X-CHK-On-Behalf-Of`**에 싣는다. 값은 `X-CHK-Actor`와 같이 UTF-8을 퍼센트 인코딩하고, Center는 디코딩해 같은 정규화를 거친다. 없으면 400 `on_behalf_required`, 비었거나 200자를 넘거나 예약 앞머리(`server_bot:` 등)로 시작하면 422 `on_behalf_invalid`.
- 목록·하나는 **그 이름이 `assignees`에 있는 결재만** 준다. `?assignee=`는 그 이름으로 고정되고, 다른 이름이면 403 `not_assignee`. 담당이 아닌 결재 하나는 **404**다 (있다는 것조차 알리지 않는다).
- 답은 그 이름이 `assignees`에 있을 때만 받는다. 아니면 403 `not_assignee`. **담당자가 없는 결재는 대리 답을 받지 않는다** (콘솔에서만).
- 나머지 규칙(폼 검증·`already_answered`·`not_open`)은 콘솔 답과 같다 — 어느 쪽으로 답해도 결재는 한 번만 닫힌다.
- Center는 그 이름이 참인지 증명하지 못한다. 사람 확인은 키를 쥔 쪽의 책임이고, Center는 담당자 목록과 대조하는 것까지 한다.

## 모델

### ApprovalCreateRequest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `schema` | int | ✓ | 1 |
| `request_id` | str | ✓ | 위 형식 |
| `layer` | str | ✓ | `approval`만 받는다. 그 밖이면 422 `confirmation_not_allowed` (열린 문자열이지만 Center는 이 값만 받는다) |
| `run_id`, `node_id`, `node_instance` | str, str, int | ✓ | C3과 같은 값 |
| `bpm_process_id`, `version` | str | ✓ | |
| `title`, `description` | str | | 폼 제목·설명. 없으면 「결재 요청」 |
| `form` | Form | | 답의 모양. 없으면 「승인 / 반려」 두 단추 |
| `review` | object | | **검토 자료.** 폼의 「표시 변수」만 담는다 (이름 → 값) |
| `assignees` | str[] | | **결재 담당자** — 이름 목록 (정규화 뒤, 겹침 없음). 비면 담당자 없음 (ADR-0080) |
| `expires_at` | str | | 시간 제한. 지나면 `expired` |

**`review`는 원칙 6의 예외다.** 결재자가 판단하려면 업무 값이 필요하기 때문이다. 콘솔에서는 접어서 보인다 (U10). `review`와 `answer`의 **값**은 결재가 끝난 뒤 30일이 지나면 지운다 (`CHK_CENTER__APPROVAL__VALUE_DAYS`). 누가·언제·결과(승인/반려/값 있음)는 남는다.

Form: `fields: [{key, label, type: "bool" | "number" | "text" | "choice", choices?, required, default?}]`. STU-04 결재 「출력」 표와 같은 모양이다.

### ApprovalInfo (콘솔이 읽는 것)

위 필드에 다음을 더한다.

| 필드 | 뜻 |
| --- | --- |
| `host` | `{type: bot_ui \| server_runner, id, name}` |
| `state` | 아래 상태 표 |
| `answer`?, `answered_by`?, `answered_at`? | |
| `answered_via`? | 대리 답이면 **그 키의 이름**. 콘솔 답이면 없다 (ADR-0081) |
| `review_digest`? | **검토 자료의 지문** — `sha256:` + 정규화한 `review`의 SHA-256 (아래 「내용 고정」). Center가 받을 때 계산하고 **값을 지운 뒤에도 남긴다** ([ADR-0083](../decisions/0083-review-digest.md)) |
| `requested_by`? | 그 실행을 시작한 **작업**의 `requested_by` (C5). Center가 읽을 때 붙이고 저장하지 않는다. 작업 없이 시작한 실행이면 없다 (ADR-0080) |
| `withdraw_reason`? | |
| `created_at` | |
| `delivered` | 실행하는 쪽이 답을 받아 갔는지 |
| `delivery_accepted`?, `delivery_reason`? | |

### 상태 (열린 문자열)

| state | CON-04 표기 | 뜻 |
| --- | --- | --- |
| `open` | 대기 | 답을 기다림 |
| `answered` | 답함 | |
| `expired` | 시간 초과 | |
| `withdrawn` | 회수됨 | `withdraw_reason`: `answered_in_field`(현장에서 먼저 답함), `run_ended`(실행이 끝남·취소됨), `admin_withdraw`(관리자 회수), `host_lost`(Bot UI 기록 유실) |
| `rejected_by_host` | Bot 거절 | 실행하는 쪽이 답을 받아들이지 못함 (`delivery_reason`) |

**상태 전이 규칙:**

- `rejected_by_host`는 **곧바로 `open`으로 돌아간다.** 거절 사유는 콘솔에 남겨, 결재자가 고쳐서 다시 답한다. 실행하는 쪽은 계속 기다린다.
- **자동 회수:** Center는 다음 경우 그 실행의 `open` 결재를 `withdrawn`으로 바꾼다.
  - C3 `run_finished`를 받았을 때 (`run_ended`)
  - 작업이 `bot_ui_lost`가 되었을 때 (`host_lost`)

  이렇게 해서 답할 수는 있지만 전달될 곳이 없는 결재가 결재함에 남지 않게 한다.
- **관리자 회수(`admin_withdraw`)의 효과:** 실행하는 쪽은 이 결재를 "답 없이 끝남"으로 받는다. 그 노드에 오류 경계 이벤트가 있으면 그쪽으로 가고, 없으면 실행이 실패로 끝난다 (CON-04 「그 실행은 실패로 끝납니다」). 현장에서 먼저 답해서 회수된 경우는 실행에 영향이 없다.

### AnswerRequest

| 필드 | 타입 | 필수 | 뜻 |
| --- | --- | --- | --- |
| `answer` | object | ✓ | 폼이 있으면 `{key: value}`. 없으면 `{"decision": "approve" \| "reject", "comment"?}` |
| `if_review_digest` | str | | 답하는 쪽이 **본** 결재의 `review_digest`. 지금 것과 다르면 409 `review_changed` ([ADR-0083](../decisions/0083-review-digest.md)) |

- **내용 고정** ([ADR-0083](../decisions/0083-review-digest.md)) — `review_digest`는 `contracts.approvals.review_digest`가 짓는다: `json.dumps(review, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`를 UTF-8로 SHA-256, 16진 소문자, 앞에 `sha256:`. `review`가 비어도 있다. 연동하는 쪽은 **Center가 준 값을 그대로** 되돌려 보낸다(제 손으로 다시 계산하지 않는다 — 수의 표기가 갈라질 수 있다). 이 칸이 생기기 전의 결재는 남은 `review`로 읽을 때 계산하고, 값도 지워졌으면 없다 — 그때 `if_review_digest`를 실으면 `review_changed`다.
- **Center가 폼으로 답을 검증한다** (필수·타입·선택지, `contracts.approvals.validate_answer`). 틀리면 422로 콘솔에 바로 보인다. 실행하는 쪽도 같은 함수로 한 번 더 검증한다.
- **검증 전에 빈 칸을 기본값으로 채운다** (`contracts.approvals.apply_defaults`) — 콘솔 폼이 안 보낸 칸이 「필수인데 비었다」가 되지 않게.
- **폼의 칸은 모두 변수가 된다** (`contracts.approvals.answer_variables`) — 실행하는 쪽이 답을 변수로 옮길 때 기본값으로, 그것도 없으면 **`None`**으로 채운다. 결재 창(CMN-01)이 빈 칸에 보내는 것과 같은 값이다.
  - 빼 두면 BPM 프로세스가 그 칸의 이름을 쓸 수 없고(웹훅 `fields:[…]`·스크립트), 더 나쁘게는 **이름이 식 도우미로 떨어진다** — `기간`·`합계`처럼 겹치는 이름이면 변수가 아니라 **함수**가 잡혀 나간다. 식 쪽에서도 막는다 (호출형 도우미는 이름만으로 잡히지 않는다, [ADR-0025](../decisions/0025-expression-language.md)).
  - **지나지 않은 결재의 칸은 채우지 않는다.** 그 칸은 애초에 없었으므로 그것을 가리키는 식은 그대로 실패해야 한다.

## 예시

```json
{
  "schema": 1,
  "request_id": "apr_run_20261001_103000_d4e5f6_Task_approve_1",
  "layer": "approval",
  "run_id": "run_20261001_103000_d4e5f6",
  "node_id": "Task_approve",
  "node_instance": 1,
  "bpm_process_id": "finance.invoice-issue",
  "version": "1.0.0",
  "title": "세금계산서 발행 승인",
  "form": {"fields": [
    {"key": "approved", "label": "승인", "type": "bool", "required": true},
    {"key": "memo", "label": "메모", "type": "text", "required": false}]},
  "review": {"거래처": "주식회사 예시", "금액": 1100000},
  "assignees": ["김재무"],
  "expires_at": "2026-10-02T18:00:00+09:00"
}
```

## 오류

| 상태 코드 | `code` | 언제 | 할 일 |
| --- | --- | --- | --- |
| 400 | `on_behalf_required` | 대리 답용 키인데 `X-CHK-On-Behalf-Of`가 없음 | 연동하는 쪽 버그 |
| 403 | `not_owner` / `run_owner_mismatch` | 다른 키가 만든 결재·실행 | 버그 |
| 403 | `not_assignee` | 대리 답의 그 사람이 담당자가 아님 (담당자 없는 결재 포함), 또는 `?assignee=`가 그 사람과 다름 | 연동하는 쪽: 답하지 못한다고 사람에게 알린다 |
| 404 | `not_found` | | |
| 409 | `already_answered` / `not_open` | 이미 답함, 회수·만료됨 | 콘솔: 목록을 새로 고친다 |
| 409 | `review_changed` | `if_review_digest`가 지금 결재의 지문과 다르다 | 연동하는 쪽: 결재를 다시 읽어 사람에게 다시 보인다 |
| 409 | `idempotency_conflict` | 같은 `request_id`에 다른 키·본문 | 버그 |
| 422 | `answer_invalid` (`detail.fields`) | 폼과 맞지 않는 답 | 콘솔: 칸마다 오류를 표시한다 |
| 422 | `confirmation_not_allowed` | `layer`가 `approval`이 아님 | 버그 |
| 422 | `on_behalf_invalid` | `X-CHK-On-Behalf-Of`가 비었거나 200자를 넘거나 예약 앞머리로 시작함 | 연동하는 쪽 버그 |

## 호환 규칙

- 상태 값은 열린 문자열이다. 모르는 필드는 무시한다.
- `review`의 값 타입은 자유다 (문자열·숫자·목록). 콘솔은 문자열은 글자로, 목록은 글머리표로 보인다 (CMN-01과 같은 규칙).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-20 | 1 | **내용 고정** — `ApprovalInfo.review_digest`(값을 지워도 남는다), `AnswerRequest.if_review_digest?`, 409 `review_changed`. 선택 칸이라 schema는 그대로다 | [0083](../decisions/0083-review-digest.md) |
| 2026-10-20 | 1 | **결재 담당자·대리 답이 돈다** (형식은 그대로다). 그러면서 결재 읽기가 **권한표를 따라갔다** — 코드가 「키면 무엇이든」(`require_read`)이라 Bot UI·서버 실행기 키도 남의 검토 자료를 읽을 수 있었다. 이제 콘솔 토큰과 대리 답용 키(담당인 것만)뿐이다 | [0080](../decisions/0080-approval-assignees.md), [0081](../decisions/0081-answering-on-behalf.md) |
| 2026-10-20 | 1 | **결재 담당자·대리 답** — `assignees[]`·`?assignee=`, 대리 답용 키와 `X-CHK-On-Behalf-Of`(담당자일 때만), `answered_via`·`requested_by`, 오류 `on_behalf_required`·`not_assignee`·`on_behalf_invalid`. 모두 선택 칸이라 schema는 그대로다 | [0080](../decisions/0080-approval-assignees.md), [0081](../decisions/0081-answering-on-behalf.md) |
| 2026-10-20 | 1 | 현장 결재도 이 본문을 현장 요청 파일에 쓴다 (형식은 그대로다, 올리지 않는다) — CMN-01이 검토 자료를 보인다 | 0078 |
| 2026-10-15 | 1 | **「넣을 수 없는 답은 ack하지 않고 둔다」**를 적었다 (형식은 그대로다) — `delivered = 0`이면 다시 내려가므로 그것이 멀쩡한 길이고, **거절로 적으면 결재가 `open`으로 되돌아가며 답이 지워져** 사람이 다시 답해야 한다. 서버 실행기에서 그런 자리는 **빈자리가 없을 때**다 (C12 — 이어 가면 자리를 다시 쥔다) | — |
| 2026-10-07 | 1 | 현장 연결 — 요청 파일로 올리고 하트비트로 내려받는다. 회수·만료는 실행하는 쪽에 `APPROVAL_WITHDRAWN`·`APPROVAL_EXPIRED`로 간다 | 0038 |
| 2026-10-01 | 1 | 초안 (확인은 올리지 않음, Center가 답 검증, `review` 보관 기한, 서버 실행기도 올림) | 0014, 0015 |
| 2026-10-01 | 1 | 검토 반영: `layer` 필드, `run_id` 소유·멱등 충돌, `rejected_by_host` → `open` 복귀, 자동 회수(`run_ended`·`host_lost`), 관리자 회수의 효과, 행위자는 `X-CHK-Actor`, `answer` 값도 30일 뒤 삭제 | 0017 |

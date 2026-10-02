# C6. Center API: 결재

| 항목 | 값 |
| --- | --- |
| 상태 | **합의** (2026-10-01, 독립 검토 반영) |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Bot UI(실행 중 Bot)·서버 실행기 → Center ↔ Center 콘솔(결재함) |
| 코드 위치 | `packages/contracts/src/chaeksas/contracts/approvals.py` (import `chaeksas.contracts.approvals`, [ADR-0019](../decisions/0019-package-names.md)) |
| JSON Schema | [`c6-approval-create-request.json`](../../packages/contracts/schemas/c6-approval-create-request.json) · [`c6-approval-info.json`](../../packages/contracts/schemas/c6-approval-info.json) · [`c6-answer-request.json`](../../packages/contracts/schemas/c6-answer-request.json) — `uv run python scripts/gen_schemas.py`로 모델에서 생성 |
| 관련 ADR | [0007](../decisions/0007-client-initiated-communication.md), [0014](../decisions/0014-one-bot-per-pc.md), [0015](../decisions/0015-run-location.md), [0017](../decisions/0017-web-nextjs-design-system.md) |
| 관련 화면 | CON-04 결재함, CMN-01, BUI-05, STU-04(결재 위치) |

## 목적

BPM 프로세스의 결재(UserTask)를 Center 결재함으로 올린다. 결재자가 콘솔에서 답하면, 실행하는 쪽이 그 답을 받아 실행을 이어 간다.

- **Center로 올라가는 것은 결재(`approval`)뿐이다.** 확인(실행 중 막힘, `confirmation`)은 화면 앞 사람만 답할 수 있으므로 올리지 않는다 (용어집 §3). 서버 Bot에는 확인이 없다 (C1 R2).
- PC Bot은 답이 올 때까지 실행 자리를 쥐고 기다린다 (ADR-0014 §5). 서버 Bot은 상태를 저장하고 기다린다 (ADR-0015).

## 전송

| 메서드·경로 | 인증 | 뜻 |
| --- | --- | --- |
| `POST /api/v1/approvals` | Bot UI·서버 실행기 키 | 결재 요청 올리기 |
| `DELETE /api/v1/approvals/{request_id}` | 올린 쪽 키 (`reason: "answered_in_field"` 또는 `"run_ended"`) / 관리자 토큰 (`reason: "admin_withdraw"`) | 회수 |
| `GET /api/v1/approvals?state=&bpm_process_id=&host=` | 읽기·관리자 토큰 | 결재함 목록 |
| `GET /api/v1/approvals/{request_id}` | 읽기·관리자 토큰 | 하나 |
| `POST /api/v1/approvals/{request_id}/answer` | 관리자 토큰 (콘솔 BFF, `X-CHK-Actor`) | 답하기 |

**답 전달:**

- PC: C4 하트비트 응답 `approvals[]`로 내려가고, Bot UI가 `approval_acks[]`로 받았다고 알린다.
- 서버: C12 (M7).

**식별자·멱등성·소유:**

- `request_id`는 실행하는 쪽이 `apr_<run_id>_<node_id>_<node_instance>` 형식으로 만든다.
- 같은 키가 같은 `request_id`와 같은 본문을 다시 올리면 200 (기존 그대로).
- 다른 키가 올리거나 본문이 다르면 409 `idempotency_conflict`.
- 결재 요청은 올린 키에 묶이고, 답은 그 키에게만 전달된다. Center는 `run_id`도 C3 소유와 대조한다. 다른 키가 만든 실행이면 403 `run_owner_mismatch`.
- 답은 한 번만 받는다. 두 번째 답은 409 `already_answered`.

**행위자:** `answered_by`는 본문에서 받지 않는다. 콘솔 BFF가 로그인 세션의 이름을 `X-CHK-Actor` 헤더로 보낸다. OIDC 전에는 콘솔이 「답하는 사람 (자칭)」 입력값을 세션 이름으로 쓰고, 화면에 「자칭」으로 표시한다.

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

- **Center가 폼으로 답을 검증한다** (필수·타입·선택지, `contracts.approvals.validate_answer`). 틀리면 422로 콘솔에 바로 보인다. 실행하는 쪽도 같은 함수로 한 번 더 검증한다.

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
  "expires_at": "2026-10-02T18:00:00+09:00"
}
```

## 오류

| 상태 코드 | `code` | 언제 | 할 일 |
| --- | --- | --- | --- |
| 403 | `not_owner` / `run_owner_mismatch` | 다른 키가 만든 결재·실행 | 버그 |
| 404 | `not_found` | | |
| 409 | `already_answered` / `not_open` | 이미 답함, 회수·만료됨 | 콘솔: 목록을 새로 고친다 |
| 409 | `idempotency_conflict` | 같은 `request_id`에 다른 키·본문 | 버그 |
| 422 | `answer_invalid` (`detail.fields`) | 폼과 맞지 않는 답 | 콘솔: 칸마다 오류를 표시한다 |
| 422 | `confirmation_not_allowed` | `layer`가 `approval`이 아님 | 버그 |

## 호환 규칙

- 상태 값은 열린 문자열이다. 모르는 필드는 무시한다.
- `review`의 값 타입은 자유다 (문자열·숫자·목록). 콘솔은 문자열은 글자로, 목록은 글머리표로 보인다 (CMN-01과 같은 규칙).

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (확인은 올리지 않음, Center가 답 검증, `review` 보관 기한, 서버 실행기도 올림) | 0014, 0015 |
| 2026-10-01 | 1 | 검토 반영: `layer` 필드, `run_id` 소유·멱등 충돌, `rejected_by_host` → `open` 복귀, 자동 회수(`run_ended`·`host_lost`), 관리자 회수의 효과, 행위자는 `X-CHK-Actor`, `answer` 값도 30일 뒤 삭제 | 0017 |

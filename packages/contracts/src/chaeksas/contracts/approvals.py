"""C6. Center API: 결재.

단일 원본: `docs/03-contracts/C6-approvals.md`.

**Center로 올라가는 것은 결재(`approval`)뿐이다.** 확인(`confirmation`)은 화면 앞 사람만 답할 수
있으므로 올리지 않는다. PC Bot은 답이 올 때까지 실행 자리를 쥐고 기다리고(ADR-0014),
서버 Bot은 상태를 저장하고 기다린다(ADR-0015).

답이 내려가는 길은 C4 하트비트 응답 `approvals[]`(PC)과 C12(서버, M7)다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, model_validator

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp, Violation

#: 폼이 없을 때 콘솔이 보이는 기본값 (저장되는 값이 아니다).
DEFAULT_TITLE = "결재 요청"

#: `review`·`answer`의 **값**은 결재가 끝난 뒤 이만큼 지나면 지운다
#: (`CHK_CENTER__APPROVAL__VALUE_DAYS`). 누가·언제·결과는 남는다.
VALUE_RETENTION_DAYS = 30

#: 폼이 없을 때의 답 모양.
KNOWN_DECISIONS = frozenset({"approve", "reject"})

#: 폼 칸의 종류.
KNOWN_FIELD_TYPES = frozenset({"bool", "number", "text", "choice"})

# 열린 문자열의 알려진 값 (README 원칙 10).
KNOWN_STATES = frozenset({"open", "answered", "expired", "withdrawn", "rejected_by_host"})
KNOWN_WITHDRAW_REASONS = frozenset({"answered_in_field", "run_ended", "admin_withdraw", "host_lost"})
KNOWN_HOST_TYPES = frozenset({"bot_ui", "server_runner"})

#: 실행 쪽 사건 → 자동 회수 사유. 답할 수는 있지만 전달될 곳이 없는 결재를 결재함에 남기지 않는다.
AUTO_WITHDRAW_REASONS = {
    "run_finished": "run_ended",  # C3 run_finished를 받았을 때
    "bot_ui_lost": "host_lost",  # 작업이 bot_ui_lost가 되었을 때 (C4 맞추기 규칙)
}


def request_id_for(run_id: str, node_id: str, node_instance: int) -> str:
    """`apr_<run_id>_<node_id>_<node_instance>` — 실행하는 쪽이 만든다."""
    return f"apr_{run_id}_{node_id}_{node_instance}"


class FormField(ContractModel):
    """결재 폼의 칸 하나. STU-04 결재 「출력」 표와 같은 모양이다."""

    key: str
    label: str
    type: str  # KNOWN_FIELD_TYPES
    required: bool = False
    choices: list[Any] | None = None
    default: Any = None


class Form(ContractModel):
    """답의 모양. 없으면 「승인 / 반려」 두 단추다."""

    fields: list[FormField] = Field(default_factory=list)

    def field(self, key: str) -> FormField | None:
        return next((f for f in self.fields if f.key == key), None)


class ApprovalHost(ContractModel):
    """이 결재를 올린 쪽."""

    type: str  # KNOWN_HOST_TYPES
    id: str
    name: str | None = None


class ApprovalCreateRequest(SchemaVersioned):
    """`POST /api/v1/approvals` — 실행하는 쪽이 결재를 올린다.

    `request_id`는 `run_id`·`node_id`·`node_instance`와 **맞아야 한다**. 어긋나면 답이 엉뚱한
    노드로 돌아갈 수 있으므로 모델이 막는다.
    """

    request_id: str
    layer: str  # Center는 "approval"만 받는다 (`validate_create`가 검사)
    run_id: str
    node_id: str
    node_instance: int = Field(ge=1)
    bpm_process_id: str
    version: str
    title: str | None = None
    description: str | None = None
    form: Form | None = None
    # `review`는 README 원칙 6의 예외다 — 결재자가 판단하려면 업무 값이 필요하다.
    # 폼의 「표시 변수」만 담고, 값은 끝난 뒤 VALUE_RETENTION_DAYS가 지나면 지운다.
    review: dict[str, Any] = Field(default_factory=dict)
    expires_at: Timestamp | None = None

    @model_validator(mode="after")
    def _request_id_matches_node(self) -> ApprovalCreateRequest:
        expected = request_id_for(self.run_id, self.node_id, self.node_instance)
        if self.request_id != expected:
            raise ValueError(f"request_id가 노드와 맞지 않는다 (기대 {expected}, 받은 값 {self.request_id})")
        return self


class ApprovalInfo(ApprovalCreateRequest):
    """`GET /api/v1/approvals` — 콘솔(CON-04 결재함)이 읽는 모양."""

    host: ApprovalHost
    state: str  # 열린 문자열 (KNOWN_STATES)
    created_at: Timestamp
    answer: dict[str, Any] | None = None
    answered_by: str | None = None
    answered_at: Timestamp | None = None
    withdraw_reason: str | None = None  # KNOWN_WITHDRAW_REASONS
    delivered: bool = False
    delivery_accepted: bool | None = None
    delivery_reason: str | None = None


class AnswerRequest(ContractModel):
    """`POST /api/v1/approvals/{request_id}/answer`.

    `answered_by`는 **본문에서 받지 않는다.** 콘솔 BFF가 `X-CHK-Actor` 헤더로 보낸다.
    """

    answer: dict[str, Any]


def validate_create(req: ApprovalCreateRequest) -> list[Violation]:
    """올라온 결재 요청 중 Center가 거부할 것.

    확인(`confirmation`)은 Center로 올리지 않는다 — 화면 앞 사람만 답할 수 있다.
    """
    if req.layer != "approval":
        return [
            Violation(
                rule="C6",
                code="confirmation_not_allowed",
                message=f"Center는 layer=approval만 받는다 (받은 값 {req.layer})",
            )
        ]
    return []


def _type_ok(field: FormField, value: Any) -> bool:
    if field.type == "bool":
        return isinstance(value, bool)
    if field.type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if field.type == "text":
        return isinstance(value, str)
    if field.type == "choice":
        return value in (field.choices or [])
    return True  # 모르는 칸 종류는 검사하지 않는다 (열린 문자열)


def validate_answer(form: Form | None, answer: Mapping[str, Any]) -> list[Violation]:
    """답이 폼과 맞는지. **Center와 실행하는 쪽이 같은 함수를 쓴다** (C6 「답하기」).

    칸마다 위반 하나를 돌려주므로, 422 응답의 `detail.fields`는
    `[v.items[0] for v in violations]`로 만들면 된다 (콘솔이 칸마다 오류를 표시한다).

    모르는 키는 거부하지 않는다 (README 원칙 3).
    """
    out: list[Violation] = []

    if form is None or not form.fields:
        # 폼이 없으면 「승인 / 반려」.
        decision = answer.get("decision")
        if decision is None:
            out.append(_field_violation("decision", "답이 없다 (approve 또는 reject)"))
        elif decision not in KNOWN_DECISIONS:
            out.append(_field_violation("decision", f"approve 또는 reject여야 한다 (받은 값 {decision!r})"))
        comment = answer.get("comment")
        if comment is not None and not isinstance(comment, str):
            out.append(_field_violation("comment", "메모는 글자여야 한다"))
        return out

    for field in form.fields:
        if field.key not in answer:
            if field.required:
                out.append(_field_violation(field.key, f"「{field.label}」은 필수다"))
            continue
        value = answer[field.key]
        if value is None:
            if field.required:
                out.append(_field_violation(field.key, f"「{field.label}」이 비어 있다"))
            continue
        if not _type_ok(field, value):
            expected = f"{field.type} 중 {field.choices}" if field.type == "choice" else field.type
            out.append(_field_violation(field.key, f"「{field.label}」은 {expected}여야 한다 (받은 값 {value!r})"))
    return out


def _field_violation(key: str, message: str) -> Violation:
    return Violation(rule="C6", code="answer_invalid", message=message, items=[key])


def answer_variables(form: Form | None, answer: Mapping[str, Any]) -> dict[str, Any]:
    """답 → **실행하는 쪽의 변수** (C6). `apply_defaults` + 남은 칸은 `None`이다.

    `apply_defaults`와 나누어 둔 것은 하는 일이 다르기 때문이다 — 저쪽은 **검증 전에** 빈 칸을
    기본값으로 채우는 것이고, 이쪽은 **답을 변수로 옮기는** 것이다.

    폼의 칸은 **모두 변수가 된다.** 답하지 않은 선택 칸을 빼면 BPM 프로세스가 그 이름을 쓸 수
    없고(BX-10의 웹훅이 `의견`을 보낸다), 더 나쁘게는 **이름이 식 도우미로 떨어진다** — `기간`·
    `합계`처럼 겹치는 이름이면 변수가 아니라 함수가 잡힌다.

    빈 칸은 `None`이다 — 결재 창(CMN-01)이 보내는 것과 같은 값이다. **그 폼의 칸만** 채운다:
    지나지 않은 결재의 칸은 애초에 없으므로 그것을 가리키는 식은 그대로 실패해야 한다.
    """
    filled = apply_defaults(form, answer)
    if form is not None:
        for field in form.fields:
            filled.setdefault(field.key, None)
    return filled


def apply_defaults(form: Form | None, answer: Mapping[str, Any]) -> dict[str, Any]:
    """답하지 않은 칸을 폼의 `default`로 채운다 (검증 전에 쓴다)."""
    if form is None:
        return dict(answer)
    filled = dict(answer)
    for field in form.fields:
        if field.key not in filled and field.default is not None:
            filled[field.key] = field.default
    return filled

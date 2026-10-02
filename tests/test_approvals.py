"""C6 결재 — 요청 모양과 폼으로 답 검증.

`validate_answer`는 **Center와 실행하는 쪽이 같이 쓴다.** 양쪽이 다르게 판단하면 결재자는
답했는데 실행이 거절하는 일이 생기므로, 이 함수의 경계를 테스트로 못 박는다.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from chaeksas.contracts import (
    ApprovalCreateRequest,
    ApprovalInfo,
    Form,
    FormField,
    apply_defaults,
    request_id_for,
    validate_answer,
    validate_approval_create,
)
from chaeksas.contracts.approvals import AUTO_WITHDRAW_REASONS, VALUE_RETENTION_DAYS

RUN = "run_20261001_103000_d4e5f6"
NOW = "2026-10-01T10:30:00+09:00"


def request(**over: Any) -> ApprovalCreateRequest:
    base: dict[str, Any] = {
        "schema": 1,
        "request_id": request_id_for(RUN, "Task_approve", 1),
        "layer": "approval",
        "run_id": RUN,
        "node_id": "Task_approve",
        "node_instance": 1,
        "bpm_process_id": "finance.invoice-issue",
        "version": "1.0.0",
    }
    return ApprovalCreateRequest.model_validate(base | over)


def form(*fields: dict[str, Any]) -> Form:
    return Form(fields=[FormField.model_validate(f) for f in fields])


# ─────────────── 요청 ───────────────


def test_request_id_format() -> None:
    assert request_id_for(RUN, "Task_approve", 1) == f"apr_{RUN}_Task_approve_1"


def test_request_id_must_match_the_node() -> None:
    """어긋나면 답이 엉뚱한 노드로 돌아갈 수 있다."""
    with pytest.raises(ValidationError, match="노드와 맞지 않는다"):
        request(request_id=f"apr_{RUN}_Task_other_1")
    with pytest.raises(ValidationError, match="노드와 맞지 않는다"):
        request(node_instance=2)  # id는 _1인데 instance가 2


def test_node_instance_starts_at_one() -> None:
    with pytest.raises(ValidationError):
        request(request_id=f"apr_{RUN}_Task_approve_0", node_instance=0)


def test_confirmation_is_not_accepted_by_center() -> None:
    """확인은 화면 앞 사람만 답할 수 있어 Center로 올리지 않는다."""
    assert validate_approval_create(request()) == []
    v = validate_approval_create(request(layer="confirmation"))
    assert [x.code for x in v] == ["confirmation_not_allowed"]


def test_review_is_kept_as_is() -> None:
    """`review`는 원칙 6의 예외 — 결재자가 판단하려면 업무 값이 필요하다."""
    req = request(review={"거래처": "주식회사 예시", "금액": 1100000, "항목": ["A", "B"]})
    assert req.review["금액"] == 1100000
    assert req.review["항목"] == ["A", "B"]
    assert VALUE_RETENTION_DAYS == 30  # 값은 30일 뒤 지운다 (누가·언제·결과는 남는다)


def test_approval_info_adds_center_side_fields() -> None:
    info = ApprovalInfo.model_validate(
        request().to_json_dict()
        | {"host": {"type": "bot_ui", "id": "bui_a81c22d0", "name": "현장PC-1"},
           "state": "open", "created_at": NOW}
    )
    assert info.host.name == "현장PC-1"
    assert info.delivered is False
    assert info.answer is None


def test_unknown_state_is_accepted() -> None:
    info = ApprovalInfo.model_validate(
        request().to_json_dict() | {"host": {"type": "bot_ui", "id": "b"}, "state": "뭔가_새로운",
                                    "created_at": NOW}
    )
    assert info.state == "뭔가_새로운"


def test_auto_withdraw_reasons() -> None:
    """답할 수는 있지만 전달될 곳이 없는 결재를 결재함에 남기지 않는다."""
    assert AUTO_WITHDRAW_REASONS["run_finished"] == "run_ended"
    assert AUTO_WITHDRAW_REASONS["bot_ui_lost"] == "host_lost"


# ─────────────── 폼이 없을 때: 승인 / 반려 ───────────────


def test_decision_answer_without_a_form() -> None:
    assert validate_answer(None, {"decision": "approve"}) == []
    assert validate_answer(None, {"decision": "reject", "comment": "금액 확인 필요"}) == []


def test_decision_is_required() -> None:
    v = validate_answer(None, {})
    assert [x.code for x in v] == ["answer_invalid"]
    assert v[0].items == ["decision"]


def test_decision_must_be_approve_or_reject() -> None:
    v = validate_answer(None, {"decision": "maybe"})
    assert v[0].items == ["decision"]
    v = validate_answer(None, {"decision": True})
    assert v[0].items == ["decision"]


def test_comment_must_be_text() -> None:
    v = validate_answer(None, {"decision": "approve", "comment": 123})
    assert v[0].items == ["comment"]


def test_empty_form_behaves_like_no_form() -> None:
    assert [x.items[0] for x in validate_answer(Form(), {})] == ["decision"]


# ─────────────── 폼이 있을 때 ───────────────


def test_form_answer_passes() -> None:
    f = form(
        {"key": "approved", "label": "승인", "type": "bool", "required": True},
        {"key": "memo", "label": "메모", "type": "text", "required": False},
    )
    assert validate_answer(f, {"approved": True, "memo": "확인"}) == []
    assert validate_answer(f, {"approved": False}) == []  # 선택 칸은 없어도 된다


def test_required_field_missing_is_reported_per_field() -> None:
    f = form(
        {"key": "approved", "label": "승인", "type": "bool", "required": True},
        {"key": "amount", "label": "금액", "type": "number", "required": True},
    )
    v = validate_answer(f, {})
    assert [x.items[0] for x in v] == ["approved", "amount"]  # 콘솔이 칸마다 표시한다
    assert all(x.code == "answer_invalid" for x in v)


def test_required_field_explicit_null_is_reported() -> None:
    f = form({"key": "approved", "label": "승인", "type": "bool", "required": True})
    assert [x.items[0] for x in validate_answer(f, {"approved": None})] == ["approved"]


def test_bool_and_number_are_not_interchangeable() -> None:
    """`True`가 1로 통하면 「승인 여부」에 숫자가 들어간다."""
    f = form({"key": "approved", "label": "승인", "type": "bool", "required": True})
    assert [x.items[0] for x in validate_answer(f, {"approved": 1})] == ["approved"]
    assert [x.items[0] for x in validate_answer(f, {"approved": "true"})] == ["approved"]

    f = form({"key": "amount", "label": "금액", "type": "number", "required": True})
    assert [x.items[0] for x in validate_answer(f, {"amount": True})] == ["amount"]
    assert validate_answer(f, {"amount": 1100000}) == []
    assert validate_answer(f, {"amount": 10.5}) == []  # 서명 대상이 아니라 실수도 된다


def test_text_must_be_a_string() -> None:
    f = form({"key": "memo", "label": "메모", "type": "text", "required": True})
    assert [x.items[0] for x in validate_answer(f, {"memo": 123})] == ["memo"]


def test_choice_must_be_one_of_the_choices() -> None:
    f = form({"key": "등급", "label": "등급", "type": "choice", "choices": ["A", "B"], "required": True})
    assert validate_answer(f, {"등급": "A"}) == []
    v = validate_answer(f, {"등급": "C"})
    assert v[0].items == ["등급"]
    assert "['A', 'B']" in v[0].message  # 고를 수 있는 값을 알려 준다


def test_choice_without_choices_rejects_everything() -> None:
    f = form({"key": "x", "label": "x", "type": "choice", "required": True})
    assert [v.items[0] for v in validate_answer(f, {"x": "아무거나"})] == ["x"]


def test_unknown_field_type_is_not_checked() -> None:
    """칸 종류도 열린 문자열 — 모르는 종류는 통과시킨다 (받는 쪽은 관대하게)."""
    f = form({"key": "sig", "label": "서명", "type": "signature", "required": True})
    assert validate_answer(f, {"sig": {"png": "..."}}) == []


def test_unknown_answer_keys_are_ignored() -> None:
    f = form({"key": "approved", "label": "승인", "type": "bool", "required": True})
    assert validate_answer(f, {"approved": True, "콘솔이_더_보낸_값": 1}) == []


# ─────────────── 기본값 ───────────────


def test_apply_defaults_fills_unanswered_fields() -> None:
    f = form(
        {"key": "approved", "label": "승인", "type": "bool", "required": True, "default": True},
        {"key": "memo", "label": "메모", "type": "text", "required": False},
    )
    filled = apply_defaults(f, {})
    assert filled == {"approved": True}
    assert validate_answer(f, filled) == []


def test_apply_defaults_does_not_overwrite_the_answer() -> None:
    f = form({"key": "approved", "label": "승인", "type": "bool", "required": True, "default": True})
    assert apply_defaults(f, {"approved": False}) == {"approved": False}


def test_apply_defaults_without_a_form_is_a_copy() -> None:
    answer = {"decision": "approve"}
    assert apply_defaults(None, answer) == answer
    assert apply_defaults(None, answer) is not answer

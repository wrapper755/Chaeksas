"""CMN-01 결재 / 확인 창 (`packages/qt`) — **Studio와 PC 실행기가 같은 창을 쓴다**.

거듭 보는 것 넷.

1. **폼이 없으면 「승인 / 반려」**다 (C6 — 답은 `decision` 하나).
2. 「보내기」는 **엔진과 같은 `validate_answer`**로 본다 — 틀리면 **창이 닫히지 않는다**.
3. **거절은 답이다** (`decision: reject`) — 빈 답이 아니다. 빈 답을 보내면 실행이 다시 묻는다.
4. 검토 자료에 **JSON 따옴표가 그대로 보이지 않는다** (사람이 읽는 자리다).
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.approvals import Form, FormField, as_table, review_table  # noqa: E402
from chaeksas.qt.approval import (  # noqa: E402
    APPROVE,
    CONFIRMATION,
    REJECT,
    ApprovalDialog,
    as_text,
    review_tables,
    review_text,
)


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def form() -> Form:
    return Form(
        fields=[
            FormField(key="승인", label="승인합니까?", type="bool", required=True),
            FormField(key="금액", label="조정 금액", type="number"),
            FormField(key="사유", label="사유", type="text", required=True),
            FormField(key="등급", label="등급", type="choice", choices=["A", "B"], default="B"),
        ]
    )


# ─────────────────────────── 검토 자료 ───────────────────────────


def test_review_values_are_read_as_people_read_them() -> None:
    assert as_text("한 줄") == "한 줄"
    assert as_text(True) == "예"
    assert as_text(1250000) == "1,250,000"
    assert as_text(["가", "나"]) == "- 가\n- 나"
    assert as_text({"공급사": "한빛상사"}) == "공급사: 한빛상사"


def test_review_text_has_no_json_quotes() -> None:
    found = review_text({"보류": [{"사유": "미입고"}], "합계": 1000})
    assert '"' not in found and "\\n" not in found


# ─────────────────────────── 폼 없는 결재 (C6) ───────────────────────────


def test_without_a_form_the_answer_is_a_decision(app: Any) -> None:
    dialog = ApprovalDialog(None, title="용지 확인")
    assert not dialog.has_fields
    assert dialog.collect() == {"decision": APPROVE}

    dialog.send()
    assert dialog.answer == {"decision": APPROVE}


def test_a_memo_rides_along_when_there_is_no_form(app: Any) -> None:
    dialog = ApprovalDialog(None)
    dialog.comment.setText("용지를 넣었습니다")
    dialog.send()
    assert dialog.answer == {"decision": APPROVE, "comment": "용지를 넣었습니다"}


def test_refusing_is_an_answer_not_silence(app: Any) -> None:
    """빈 답을 보내면 실행이 **다시 묻는다** — 거절은 `decision`으로 말한다."""
    dialog = ApprovalDialog(None)
    dialog.refuse()
    assert dialog.answer == {"decision": REJECT}


# ─────────────────────────── 폼이 있는 결재 ───────────────────────────


def test_each_field_type_gets_its_own_widget(app: Any) -> None:
    from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit  # noqa: PLC0415

    dialog = ApprovalDialog(None, form=form())
    kinds = {key: type(widget) for key, widget in dialog._widgets.items()}  # noqa: SLF001
    assert kinds == {"승인": QCheckBox, "금액": QDoubleSpinBox, "사유": QLineEdit, "등급": QComboBox}
    등급 = dialog._widgets["등급"]  # noqa: SLF001
    assert isinstance(등급, QComboBox) and 등급.currentText() == "B", "기본값이 들어가야 한다"


def test_a_missing_required_field_keeps_the_window_open(app: Any) -> None:
    """**엔진과 같은 검증기**로 본다 — 돌려 보고야 아는 일을 없앤다."""
    dialog = ApprovalDialog(None, form=form())
    dialog.send()

    assert dialog.answer == {}, "틀린 답을 내보내지 않는다"
    assert "사유" in dialog.note.text()
    assert dialog.result() != int(ApprovalDialog.DialogCode.Accepted)


def test_a_good_answer_goes_out_with_its_types(app: Any) -> None:
    from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QLineEdit

    dialog = ApprovalDialog(None, form=form())
    fields = dialog._widgets  # noqa: SLF001
    assert isinstance(fields["승인"], QCheckBox)
    assert isinstance(fields["금액"], QDoubleSpinBox)
    assert isinstance(fields["사유"], QLineEdit)
    fields["승인"].setChecked(True)
    fields["금액"].setValue(1200.0)
    fields["사유"].setText("고객 요청")
    dialog.send()

    assert dialog.answer == {"승인": True, "금액": 1200, "사유": "고객 요청", "등급": "B"}
    assert isinstance(dialog.answer["금액"], int), "정수로 떨어지면 정수로 보낸다"


# ─────────────────────────── 확인 (실행 중 막힘) ───────────────────────────


def test_a_confirmation_says_continue_or_stop(app: Any) -> None:
    """확인은 업무 승인이 아니다 (CMN-01 오른쪽 칸)."""
    dialog = ApprovalDialog(None, title="로그인 확인", layer=CONFIRMATION)
    assert dialog.is_confirmation
    assert dialog.ok.text() == "계속" and dialog.no.text() == "중단"


# ─────────────────────── 표 값 (C6, ADR-0112) ───────────────────────


def test_only_the_exact_shape_is_a_table() -> None:
    """**뜻을 어림하지 않는다** — 열쇠가 정확히 `headers`·`rows`이고 칸 수가 맞을 때만 표다."""
    assert as_table(review_table(["a", "b"], [[1, 2]])) == (["a", "b"], [[1, 2]])
    assert as_table({"headers": ["a"], "rows": [[1, 2]]}) is None, "칸 수가 다르다"
    assert as_table({"headers": ["a"], "rows": [[1]], "note": "x"}) is None, "열쇠가 더 있다"
    assert as_table({"headers": "a", "rows": []}) is None
    assert as_table([["a"], [1]]) is None
    with pytest.raises(ValueError, match="칸이"):
        review_table(["a", "b"], [[1]])


def test_a_table_value_is_drawn_as_a_table_and_the_rest_as_text(app: Any) -> None:
    """CMN-01 [R] — 표는 표로, 나머지는 지금처럼 글로 (ADR-0112)."""
    review = {"요소": "주문.저장", "시도한 로케이터": review_table(["순서", "결과"], [[1, "찾지 못함"], [2, True]])}
    assert review_tables(review) == [("시도한 로케이터", ["순서", "결과"], [[1, "찾지 못함"], [2, True]])]
    assert review_text(review) == "[요소]\n주문.저장", "표는 글 상자에 들어가지 않는다"

    dialog = ApprovalDialog(None, title="실행 확인 요청 — 주문 저장", review=review, layer=CONFIRMATION)
    (table,) = dialog.review_tables
    assert (table.rowCount(), table.columnCount()) == (2, 2)
    cell = table.item(1, 1)
    assert cell is not None and cell.text() == "예", "칸도 따옴표 없이 읽는 말로"
    assert table.editTriggers() == table.EditTrigger.NoEditTriggers, "읽기 전용"


def test_a_review_without_tables_draws_no_table(app: Any) -> None:
    dialog = ApprovalDialog(None, review={"합계": 1000})
    assert dialog.review_tables == []

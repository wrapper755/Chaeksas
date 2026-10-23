"""STU-04 결재·확인 편집기 (`studio/approval_editor.py`) — 화면 없이.

보는 것은 셋이다: 그림에 적힌 것이 **다 보이는가**(폼 칸 전부·위치·담당자·기한), 고친 것이
**C14 모델로 그대로 읽히는가**, 엔진이 거부할 것을 **「적용」 전에 막는가**.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QComboBox  # noqa: E402

from chaeksas.contracts.bpmn_ext import Approval  # noqa: E402
from chaeksas.studio.approval_editor import (  # noqa: E402
    COL_DEFAULT,
    COL_KEY,
    COL_REQUIRED,
    COL_TYPE,
    SERVER_NO_FIELD,
    VISIBLE_ROWS,
    ApprovalEditor,
)

#: 사용자가 「다 안 보인다」고 한 그 결재(sc01 Approve_DQ)와 같은 모양.
BODY: dict[str, Any] = {
    "title": "고객계획 원천 확인",
    "description": "고객·모델·공장·대상 월을 확인한다.",
    "show": ["원천ID", "검증통과", "검증오류수"],
    "fields": [
        {"key": "확인결과", "label": "확인 결과", "type": "choice", "required": True,
         "choices": ["확인완료", "보완요청"]},
        {"key": "확인의견", "label": "확인 의견", "type": "text"},
        {"key": "보완일수", "label": "보완 일수", "type": "number", "default": 3},
        {"key": "긴급", "label": "긴급", "type": "bool", "default": False},
    ],
    "location": "center",
    "assignees": ["김영업", "이현업"],
    "expires": "P3D",
}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(body: dict[str, Any] | None = None, **kwargs: Any) -> ApprovalEditor:
    made = ApprovalEditor(**kwargs)
    made.load(BODY if body is None else body)
    return made


def test_everything_in_the_drawing_is_shown() -> None:
    made = loaded()
    assert made.title_box.text() == "고객계획 원천 확인"
    assert made.show_box.toPlainText().splitlines() == ["원천ID", "검증통과", "검증오류수"]
    assert made.fields.rowCount() == 4, "폼 칸이 전부 보인다"
    kinds = [made.fields.cellWidget(r, COL_TYPE) for r in range(4)]
    assert [k.currentText() for k in kinds if isinstance(k, QComboBox)] == ["choice", "text", "number", "bool"]
    required = made.fields.item(0, COL_REQUIRED)
    assert required is not None and required.checkState() == Qt.CheckState.Checked
    assert made.location() == "center"
    assert made.assignee_box.text() == "김영업, 이현업"
    assert made.expires_box.text() == "P3D"


def test_an_untouched_dump_reads_back_the_same_approval() -> None:
    made = loaded()
    assert made.problems() == ([], [])
    assert Approval.model_validate(made.dump()) == Approval.model_validate(BODY)


def test_unknown_keys_survive() -> None:
    """편집기가 다루지 않는 칸은 그대로 남긴다."""
    made = loaded({**BODY, "future_field": {"x": 1}})
    assert made.dump()["future_field"] == {"x": 1}


def test_a_row_can_be_added_and_typed() -> None:
    made = loaded()
    made._add_row({})  # noqa: SLF001 — 「줄 더하기」와 같은 길
    row = made.fields.rowCount() - 1
    made.fields.item(row, COL_KEY).setText("승인금액")  # type: ignore[union-attr]
    kind = made.fields.cellWidget(row, COL_TYPE)
    assert isinstance(kind, QComboBox)
    kind.setCurrentText("number")
    made.fields.item(row, COL_DEFAULT).setText("1500")  # type: ignore[union-attr]
    found = Approval.model_validate(made.dump()).fields[-1]
    assert (found.key, found.type, found.default) == ("승인금액", "number", 1500)


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda e: e.title_box.setText(""), "제목"),
        (lambda e: e.fields.item(1, COL_KEY).setText("확인결과"), "겹칩니다"),
        (lambda e: e.fields.item(2, COL_DEFAULT).setText("사흘"), "수가 아닙니다"),
        (lambda e: e.fields.item(3, COL_DEFAULT).setText("아마"), "true / false"),
        (lambda e: e.fields.item(0, COL_DEFAULT).setText("모름"), "선택지에 없습니다"),
    ],
)
def test_what_the_engine_would_refuse_blocks_apply(change: Any, said: str) -> None:
    made = loaded()
    change(made)
    errors, _ = made.problems()
    assert errors and said in errors[0], errors


def test_a_choice_without_choices_is_refused() -> None:
    body = {"title": "t", "fields": [{"key": "a", "label": "a", "type": "choice"}]}
    errors, _ = loaded(body).problems()
    assert errors and "선택지" in errors[0]


def test_field_approval_is_off_on_the_server() -> None:
    """B6과 같은 판정 — 서버에서는 현장 결재를 쓸 수 없다."""
    made = loaded(run_location="server")
    assert not made.location_picks["field"].isEnabled()
    assert made.location_note.text() == SERVER_NO_FIELD

    # 그림에 이미 적혀 있으면 **지우지 않고** 막는다 (조용히 바꾸지 않는다).
    stuck = loaded({**BODY, "location": "field"}, run_location="server")
    assert stuck.location() == "field"
    errors, _ = stuck.problems()
    assert SERVER_NO_FIELD in errors


def test_assignees_can_be_a_variable() -> None:
    made = loaded({**BODY, "assignees": "검토자"})
    assert made.assignee_mode.currentData() == "variable"
    assert made.dump()["assignees"] == "검토자"


def test_empty_optional_fields_leave_the_drawing() -> None:
    made = loaded({"title": "확인"})
    body = made.dump()
    assert body == {"title": "확인"}, "빈 칸을 그림에 남기지 않는다"


def test_the_fields_table_shows_three_rows_from_the_start() -> None:
    made = ApprovalEditor()
    row = made.fields.verticalHeader().defaultSectionSize()
    assert made.fields.minimumHeight() >= row * VISIBLE_ROWS


def test_the_properties_panel_attaches_it_and_applies_the_whole_body() -> None:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({
        "id": "Approve_DQ", "type": "UserTask", "name": "원천 확인",
        "chk": {"approval": json.dumps(BODY, ensure_ascii=False)},
    })
    assert panel.tabs.tabText(1) == "결재"
    editor: Any = panel._editor  # noqa: SLF001
    editor.title_box.setText("원천 확인 (수정)")
    changes, problem = panel.patch()
    assert problem is None
    applied = json.loads(changes["chk"]["approval"])
    assert applied["title"] == "원천 확인 (수정)" and len(applied["fields"]) == 4


def test_a_manual_task_gets_the_confirmation_tab() -> None:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({"id": "M", "type": "ManualTask", "name": "현장 확인", "chk": {}})
    assert panel.tabs.tabText(1) == "확인"
    changes, problem = panel.patch()
    assert changes == {} and problem is None, "손대지 않으면 아무것도 보내지 않는다"

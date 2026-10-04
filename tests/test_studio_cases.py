"""Studio 시험 케이스 편집기 (M3 조각 3e-4) — STU-07.

거듭 보는 것 넷.

1. **JSON 글상자를 쓰지 않는다** — 값은 타입을 골라 넣고, 그것이 케이스 JSON으로 돌아간다.
   읽기와 쓰기가 맞물려야(왕복) 한 번 저장할 때마다 값이 바뀌지 않는다.
2. **저장 전에 검증한다** — 결재 답은 **엔진과 같은 `validate_answer`**로 본다. 돌려 보고야
   아는 일을 없앤다 (FX-19에서 실제로 겪었다).
3. **저장해도 창이 닫히지 않는다** (STU-07).
4. 케이스 파일은 **정의 옆**에 있다 (`cases/<정의>.cases.json`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QComboBox  # noqa: E402

from chaeksas.contracts.bpmn_ext import Case, CaseMessage  # noqa: E402
from chaeksas.studio.case_dialog import CaseDialog  # noqa: E402
from chaeksas.studio.cases import (  # noqa: E402
    approvals_of,
    check_cases,
    declared_inputs,
    messages_of,
    pack_expected,
    pack_value,
    read,
    unpack_expected,
    unpack_value,
    write,
)
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

EXPENSE = "bx03_expense_approval"  # 결재가 있다 (폼 있음)
MANUAL = "fx19_manual_task_pc"  # 폼 없는 확인 — 답은 `decision` 하나 (C6)
RECONCILIATION = "bx01_invoice_reconciliation"


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def imported(tmp_path: Path, example: str) -> tuple[BpmProcess, Definition]:
    made = Workspace(tmp_path / "작업").ensure().import_example(EXAMPLES, example)
    found = made.entry_definition
    assert found is not None
    return made, found


# ─────────────────────────── 값 왕복 ───────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "글자",
        12,
        3.5,
        True,
        False,
        {"$now_plus": "PT30M"},
        {"$test_receiver": "reply"},
        {"쪽": [1, 2]},
    ],
)
def test_a_value_survives_the_table(value: Any) -> None:
    """표로 갔다 돌아와도 같은 값 — 저장할 때마다 값이 바뀌면 안 된다."""
    kind, text = unpack_value(value)
    assert pack_value(kind, text) == value


@pytest.mark.parametrize(
    "value",
    ["*", "맞음", 100, {"$gte": 90}, {"$contains": "세금"}, {"$lt": 3}],
)
def test_an_expected_value_survives_the_table(value: Any) -> None:
    comparison, kind, text = unpack_expected(value)
    assert pack_expected(comparison, kind, text) == value


def test_a_broken_json_cell_stays_as_text() -> None:
    """괄호 하나로 저장이 막히지 않는다 (STU-07이 JSON 상자를 버린 이유)."""
    assert pack_value("json", "{이건 JSON이 아니다") == "{이건 JSON이 아니다"


# ─────────────────────────── 그림에서 읽는 것 ───────────────────────────


def test_the_approval_nodes_come_from_the_drawing(tmp_path: Path) -> None:
    _, definition = imported(tmp_path, EXPENSE)
    forms = approvals_of(definition)
    assert forms, "결재가 있는 예제인데 폼을 못 찾았다"


def test_the_message_names_come_from_the_drawing(tmp_path: Path) -> None:
    _, definition = imported(tmp_path, EXPENSE)
    assert messages_of(definition) == sorted(messages_of(definition))


def _sample(field: Any) -> Any:
    """그 칸 타입에 맞는 값 하나 (폼 검증이 통과해야 하는 쪽을 만들 때)."""
    if field.choices:
        return field.choices[0]
    return {"bool": True, "number": 1, "date": "2026-10-05", "money": 1000}.get(field.type, "값")


# ─────────────────────────── 저장 전 검증 ───────────────────────────


def test_a_formless_approval_needs_a_decision(tmp_path: Path) -> None:
    """FX-19가 실제로 걸린 자리 — 폼이 없으면 답은 `decision`이다 (C6)."""
    _, definition = imported(tmp_path, MANUAL)
    node_id = next(iter(approvals_of(definition)))
    problems = check_cases([Case(name="빈 답", approvals={node_id: {}})], definition)
    assert problems and "decision" in problems[0]


def test_a_good_answer_passes(tmp_path: Path) -> None:
    _, definition = imported(tmp_path, EXPENSE)
    forms = approvals_of(definition)
    node_id, form = next(iter(forms.items()))
    answer: dict[str, Any] = {"decision": "approve"}
    for field in form.fields:
        answer[field.key] = _sample(field)
    assert check_cases([Case(name="좋은 답", approvals={node_id: answer})], definition) == []


def test_a_manual_case_is_not_checked_against_the_form(tmp_path: Path) -> None:
    """사람이 직접 답하는 케이스는 자동 응답을 쓰지 않는다."""
    _, definition = imported(tmp_path, MANUAL)
    node_id = next(iter(approvals_of(definition)))
    assert check_cases([Case(name="손으로", approvals={node_id: {}}, manual=True)], definition) == []


def test_an_unknown_approval_node_is_caught(tmp_path: Path) -> None:
    _, definition = imported(tmp_path, EXPENSE)
    problems = check_cases([Case(name="없는 노드", approvals={"없는것": {"decision": "approve"}})], definition)
    assert problems and "결재 노드가 없습니다" in problems[0]


def test_a_message_with_no_receiver_is_caught(tmp_path: Path) -> None:
    _, definition = imported(tmp_path, EXPENSE)
    if not messages_of(definition):
        pytest.skip("이 예제에는 메시지가 없다")
    case = Case(name="엉뚱한 메시지", messages=[CaseMessage(name="없는메시지")])
    assert any("받는 곳이 없는 메시지" in p for p in check_cases([case], definition))


def test_duplicate_names_are_caught(tmp_path: Path) -> None:
    _, definition = imported(tmp_path, RECONCILIATION)
    problems = check_cases([Case(name="같은이름"), Case(name="같은이름")], definition)
    assert problems and "겹칩니다" in problems[0]


# ─────────────────────────── 파일 ───────────────────────────


def test_cases_live_next_to_the_definition(tmp_path: Path) -> None:
    made, definition = imported(tmp_path, RECONCILIATION)
    edited = read(made, definition)
    edited.cases = [Case(name="첫 케이스", inputs={"금액": 100})]
    written = write(edited, process_id=definition.process.id if definition.process else "")

    assert written == made.folder / "cases" / f"{definition.path.stem}.cases.json"
    body = json.loads(written.read_text(encoding="utf-8"))
    assert body["schema"] == 1 and body["cases"][0]["name"] == "첫 케이스"
    assert read(made, definition).cases[0].inputs == {"금액": 100}


def test_a_broken_case_file_does_not_break_the_editor(tmp_path: Path) -> None:
    """고칠 수 있어야 한다 — 열리지도 않으면 고칠 길이 없다."""
    made, definition = imported(tmp_path, RECONCILIATION)
    path = made.case_file(definition)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{망가진", encoding="utf-8")
    assert read(made, definition).cases == []


# ─────────────────────────── 창 ───────────────────────────


def test_the_dialog_round_trips_a_case(app: Any, tmp_path: Path) -> None:
    """목록에서 고르고 → 화면에 보이고 → 저장하면 그대로 파일에 간다."""
    made, definition = imported(tmp_path, RECONCILIATION)
    edited = read(made, definition)
    edited.cases = [Case(name="원본", inputs={"마감": {"$now_plus": "PT1H"}}, expected={"결과": {"$gte": 90}})]
    write(edited)

    dialog = CaseDialog(None, made, definition)
    assert dialog.list.count() == 1
    assert dialog.name_box.text() == "원본"
    assert dialog.save() is True

    again = read(made, definition).cases[0]
    assert again.inputs == {"마감": {"$now_plus": "PT1H"}}
    assert again.expected == {"결과": {"$gte": 90}}


def test_saving_a_bad_answer_does_not_write(app: Any, tmp_path: Path) -> None:
    """저장을 막고 **창은 열어 둔다** (STU-07) — 고칠 수 있게."""
    made, definition = imported(tmp_path, EXPENSE)
    node_id = next(iter(approvals_of(definition)))
    edited = read(made, definition)
    edited.cases = [Case(name="나쁜 답", approvals={node_id: {}})]
    write(edited)

    dialog = CaseDialog(None, made, definition)
    assert dialog.save() is False
    assert dialog.note.text()
    assert dialog.isVisible() is False  # 아직 띄우지 않았다 — 닫히지도 않았다


def test_adding_a_case_keeps_the_one_being_edited(app: Any, tmp_path: Path) -> None:
    made, definition = imported(tmp_path, RECONCILIATION)
    dialog = CaseDialog(None, made, definition)
    dialog._add()
    dialog.name_box.setText("둘째")
    dialog._add()
    # 「추가」는 지금 고치던 것을 먼저 거둬 간다 — 적던 이름이 날아가지 않는다.
    assert [c.name for c in dialog.edited.cases][-2] == "둘째"


def test_a_row_can_be_added_and_dropped(app: Any, tmp_path: Path) -> None:
    """표에 줄을 더할 길이 없으면 편집기가 아니다 (STU-07 「추가」·「선택 줄 삭제」)."""
    made, definition = imported(tmp_path, RECONCILIATION)
    dialog = CaseDialog(None, made, definition)
    dialog._add()

    before = dialog.inputs.rowCount()
    dialog.input_block.add_row()
    assert dialog.inputs.rowCount() == before + 1

    dialog.inputs.setCurrentCell(before, 0)
    dialog.input_block.drop_row()
    assert dialog.inputs.rowCount() == before


def test_the_declared_inputs_are_offered(app: Any, tmp_path: Path) -> None:
    """`chk:process.inputs`가 이름 콤보에 미리 나온다 — 오타로 안 맞는 일을 줄인다."""
    made, definition = imported(tmp_path, RECONCILIATION)
    if not declared_inputs(definition):
        pytest.skip("이 예제는 입력을 적지 않았다")
    dialog = CaseDialog(None, made, definition)
    dialog._add()
    dialog.input_block.add_row()
    box = dialog.inputs.cellWidget(dialog.inputs.rowCount() - 1, 0)
    assert isinstance(box, QComboBox)
    assert [box.itemText(i) for i in range(box.count())] == declared_inputs(definition)


def test_an_unanswered_approval_stays_unanswered(app: Any, tmp_path: Path) -> None:
    """답을 비운 결재는 **기다린다**는 뜻이다 (기한 초과 시험) — 거둬 갈 때 지우지 않는다."""
    made, definition = imported(tmp_path, EXPENSE)
    node_id = next(iter(approvals_of(definition)))
    edited = read(made, definition)
    edited.cases = [Case(name="기다리는 결재", approvals={node_id: {}}, manual=True)]
    write(edited)

    dialog = CaseDialog(None, made, definition)
    dialog._gather()
    assert dialog.edited.cases[0].approvals == {node_id: {}}


def test_closing_with_changes_asks_first(app: Any, tmp_path: Path, monkeypatch: Any) -> None:
    """U11 — 묻지 않고 버리지 않는다."""
    from PySide6.QtWidgets import QMessageBox

    made, definition = imported(tmp_path, RECONCILIATION)
    dialog = CaseDialog(None, made, definition)
    dialog._add()
    assert dialog.unsaved() is True

    asked: list[str] = []

    def answer(*args: Any, **kwargs: Any) -> Any:
        asked.append("물었다")
        return QMessageBox.StandardButton.Cancel

    closed: list[str] = []
    dialog.rejected.connect(lambda: closed.append("닫혔다"))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer))
    dialog.reject()

    assert asked, "저장 안 한 변경이 있는데 묻지 않았다"
    assert not closed, "「취소」를 골랐는데 닫혔다"


def test_closing_without_changes_does_not_ask(app: Any, tmp_path: Path) -> None:
    made, definition = imported(tmp_path, RECONCILIATION)
    assert CaseDialog(None, made, definition).unsaved() is False

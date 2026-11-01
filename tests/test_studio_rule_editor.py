"""STU-04 규칙 편집기·STU-04a 결정표 창 (`rule_editor.py`·`decision_dialog.py`, ADR-0109) — 화면 없이.

보는 것: 그림의 `bpm:rule`이 **다 보이고 손대지 않으면 같은 것**이 나가는가(업무 예제 전부), B14가 거부할 것을
「적용」 전에 막는가, 창의 「저장」이 `.dmn`을 쓰고 탭이 **다시 읽는가**, 받은 결정표는 읽기 전용인가.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.contracts.dmn import read_decisions  # noqa: E402
from chaeksas.studio.dmn_table import Decisions, decisions_of, read_tables  # noqa: E402
from chaeksas.studio.rule_editor import NO_OUTPUT, NOT_IN_PACKAGE, NOT_IN_TABLE, RuleEditor  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

RULE: dict[str, Any] = {
    "decision": "card_policy",
    "input": {"요일": "건.요일", "시": "건.시", "업종": "건.업종", "금액": "건.금액"},
    "output": {"사유": "violation"},
}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def process(tmp_path: Path) -> Any:
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    return Workspace(tmp_path / "작업").ensure().import_example(EXAMPLES, "bx07_corporate_card_review")


def editor(process: Any, body: dict[str, Any] | None) -> Any:
    made = RuleEditor(decisions=lambda: decisions_of(process))
    made.load(body)
    return made


def _rules_in_examples() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        drawn = read_process(path.read_text(encoding="utf-8"))
        for node in drawn.all_nodes():
            rule = node.prop("rule")
            if rule is not None:
                out.append((f"{path.stem}:{node.id}", rule.model_dump(mode="json")))
    return out


RULES = _rules_in_examples()


def test_examples_have_rule_tasks() -> None:
    assert len(RULES) >= 8


def _examples_decisions() -> Decisions:
    from chaeksas.studio.dmn_table import catalog  # noqa: PLC0415

    found, broken = catalog([(p, False) for p in sorted(EXAMPLES.glob("*.dmn"))])
    assert not broken
    return Decisions(found=found, broken=broken, process_dir=EXAMPLES)


@pytest.mark.parametrize(("where", "body"), RULES, ids=[w for w, _ in RULES])
def test_every_example_rule_reads_back_the_same(where: str, body: dict[str, Any]) -> None:
    known = _examples_decisions()
    made = RuleEditor(decisions=lambda: known)
    made.load(body)
    assert made.decision() == body["decision"]
    assert made.dump() == body, where
    assert made.problems()[0] == [], where


def test_everything_is_shown(process: Any) -> None:
    made = editor(process, RULE)
    assert made.decision() == "card_policy"
    assert made.decision_box.currentText().startswith("card_policy — ")
    assert made.inputs.rowCount() == 4
    assert made.input_map() == RULE["input"]
    assert made.output_map() == RULE["output"]
    assert "COLLECT · 입력 4 · 출력 1 · 규칙 4" in made.summary_label.text()
    assert not made.collect_note.isHidden()
    assert made.edit_button.isEnabled() and made.edit_button.text() == "결정표 편집..."
    assert made.problems() == ([], [])


def test_nothing_drawn_dumps_nothing(process: Any) -> None:
    made = editor(process, None)
    assert made.dump() is None
    assert made.problems() == ([], [])


def test_a_missing_decision_blocks(process: Any) -> None:
    made = editor(process, {**RULE, "decision": "없는_것"})
    assert NOT_IN_PACKAGE in made.decision_box.currentText()
    assert any("패키지에 없습니다 (B14)" in e for e in made.problems()[0])
    assert made.dump()["decision"] == "없는_것", "적어 둔 것을 조용히 바꾸지 않는다"


def test_an_unknown_workspace_checks_nothing_against_tables() -> None:
    made = RuleEditor()
    made.load({**RULE, "decision": "어디에도_없다"})
    assert made.problems()[0] == []
    assert made.dump() == {**RULE, "decision": "어디에도_없다"}
    assert not made.edit_button.isEnabled() and not made.new_button.isEnabled()


def test_empty_input_expression_blocks(process: Any) -> None:
    made = editor(process, {**RULE, "input": {k: v for k, v in RULE["input"].items() if k != "금액"}})
    assert made.inputs.rowCount() == 4, "줄은 결정표가 정한다"
    assert any("금액의 식이 비었습니다" in e for e in made.problems()[0])
    made.inputs.item(3, 1).setText("건.금액")
    assert made.problems()[0] == []
    assert made.dump() == RULE


def test_an_unreadable_expression_blocks(process: Any) -> None:
    made = editor(process, RULE)
    made.inputs.item(0, 1).setText("건.요일 +")
    assert any("식을 읽을 수 없습니다" in e for e in made.problems()[0])


def test_an_input_the_table_lacks_is_dropped_by_clearing(process: Any) -> None:
    made = editor(process, {**RULE, "input": {**RULE["input"], "부서": "건.부서"}})
    assert made.inputs.rowCount() == 5
    assert NOT_IN_TABLE in made.inputs.item(4, 0).text()
    assert any("결정표에 없는 입력" in e for e in made.problems()[0])
    made.inputs.item(4, 1).setText("")
    assert made.problems()[0] == []
    assert made.dump() == RULE


def test_output_problems(process: Any) -> None:
    made = editor(process, {**RULE, "output": {"사유": "없는출력"}})
    assert any("DMN 출력에 없는 것" in e for e in made.problems()[0])
    made = editor(process, {**RULE, "output": {"1번": "violation"}})
    assert any("변수 이름 규칙" in e for e in made.problems()[0])
    made = editor(process, {**RULE, "output": {}})
    assert made.problems() == ([], [NO_OUTPUT])
    made.fill_outputs()
    assert made.output_map() == {"violation": "violation"}
    made.fill_outputs()
    assert made.outputs.rowCount() == 1, "있는 줄은 덮지 않는다"


def test_changing_the_decision_keeps_same_named_expressions(process: Any) -> None:
    other = (EXAMPLES / "credit_grade.dmn").read_text(encoding="utf-8")
    (process.folder / "process" / "credit_grade.dmn").write_text(other, encoding="utf-8")
    made = editor(process, RULE)
    made.reload()
    made.decision_box.setCurrentIndex(made.decision_box.findData("credit_grade"))
    names = [made.inputs.item(r, 0).data(256) for r in range(made.inputs.rowCount())]
    expected = [c.expression for c in read_tables(other)["credit_grade"].inputs]
    assert names[: len(expected)] == expected


# ── STU-04a 창 ──


def test_saving_in_the_dialog_writes_the_file_and_the_tab_rereads(process: Any) -> None:
    made = editor(process, RULE)
    dialog: Any = made.table_dialog()
    assert dialog is not None and not dialog.read_only
    assert dialog.id_box.isReadOnly(), "있는 결정의 ID는 바꾸지 않는다"
    assert not dialog.save_button.isEnabled(), "고친 것이 없으면 저장할 것이 없다"
    hour = [c.expression for c in dialog.table.inputs].index("시")
    rule = next(r for r, row in enumerate(dialog.table.rules) if row.cells[hour] == ">= 23")
    dialog.set_cell(rule, hour, ">= 22")
    assert dialog.unsaved() and dialog.save_button.isEnabled()
    dialog.add_output()
    dialog.edit_column("output", 1, {"name": "등급", "type": "string"})
    assert dialog.save()
    path = process.folder / "process" / "card_policy.dmn"
    decision = read_decisions(path.read_text(encoding="utf-8"))["card_policy"]
    assert decision.decide({"요일": "월", "시": 22, "업종": "식당", "금액": 1})["violation"] == ["심야 사용"]
    assert [o.name for o in decision.outputs] == ["violation", "등급"]
    assert not dialog.unsaved()
    assert "출력 2" in made.summary_label.text(), "탭이 다시 읽었다"
    assert made.outputs.cellWidget(0, 1).count() == 2


def test_a_bad_cell_is_marked_and_blocks_saving(process: Any) -> None:
    made = editor(process, RULE)
    dialog: Any = made.table_dialog()
    dialog.set_cell(0, 0, "토요일")
    assert "큰따옴표" in dialog.grid.item(0, 0).toolTip()
    assert not dialog.save_button.isEnabled()
    assert not dialog.problem_label.isHidden()
    assert not dialog.save()
    dialog.set_cell(0, 0, '"토"')
    assert dialog.save_button.isEnabled()


def test_rows_move_and_drop(process: Any) -> None:
    dialog: Any = editor(process, RULE).table_dialog()
    first = dialog.table.rules[0].id
    dialog.grid.setCurrentCell(0, 0)
    dialog.move_rule(1)
    assert dialog.table.rules[1].id == first
    dialog.grid.setCurrentCell(1, 0)
    dialog.drop_rule()
    assert first not in [r.id for r in dialog.table.rules]
    dialog.grid.setCurrentCell(0, 0)
    dialog.add_rule()
    assert dialog.table.rules[1].cells == ["-"] * 4


def test_the_last_output_column_cannot_go(process: Any) -> None:
    dialog: Any = editor(process, RULE).table_dialog()
    dialog.grid.setCurrentCell(0, 4)
    assert not dialog.drop_column_button.isEnabled()
    dialog.grid.setCurrentCell(0, 0)
    assert dialog.drop_column_button.isEnabled()


def test_a_new_table_is_saved_and_picked(process: Any) -> None:
    made = editor(process, None)
    dialog: Any = made.table_dialog(new=True)
    assert not dialog.id_box.isReadOnly()
    dialog.id_box.setText("card_policy")
    assert any("이미 있는" in e for e in dialog.problems()[0])
    dialog.id_box.setText("my_rule")
    dialog.edit_column("input", 0, {"label": "금액", "name": "금액", "type": "number"})
    dialog.edit_column("output", 0, {"name": "결과", "type": "string"})
    dialog.set_cell(0, 0, ">= 100")
    dialog.set_cell(0, 1, '"크다"')
    assert dialog.save()
    path = process.folder / "process" / "my_rule.dmn"
    assert read_decisions(path.read_text(encoding="utf-8"))["my_rule"].decide({"금액": 200}) == {"결과": "크다"}
    assert made.decision() == "my_rule", "저장하면 그 결정을 고른다"
    assert made.input_map() == {"금액": ""}
    assert any("금액의 식이 비었습니다" in e for e in made.problems()[0])


def test_a_received_table_opens_read_only(process: Any) -> None:
    libs = process.folder / "libs"
    libs.mkdir(exist_ok=True)
    source = (EXAMPLES / "credit_grade.dmn").read_text(encoding="utf-8")
    (libs / "credit_grade.dmn").write_text(source, encoding="utf-8")
    made = editor(process, {"decision": "credit_grade", "input": {}, "output": {}})
    assert "(공유)" in made.decision_box.currentText()
    assert made.edit_button.text() == "결정표 보기..."
    dialog: Any = made.table_dialog()
    assert dialog.read_only and dialog.save_button.isHidden()
    assert not dialog.read_only_note.isHidden()
    assert not dialog.save()


# ── 속성 패널 ──


def test_the_panel_sends_the_whole_rule(process: Any) -> None:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.decision_tables = lambda: decisions_of(process)
    panel.show_element({
        "id": "Task_Policy", "type": "BusinessRuleTask", "name": "정책 점검",
        "chk": {"rule": json.dumps(RULE, ensure_ascii=False)},
    })
    texts = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert texts[1] == "규칙" and "반복" in texts
    assert panel.patch() == ({}, None), "손대지 않으면 보내지 않는다"
    found: Any = panel._editor
    found.inputs.item(0, 1).setText("건.요일2")
    changes, problem = panel.patch()
    assert problem is None
    assert json.loads(changes["chk"]["rule"])["input"]["요일"] == "건.요일2"
    found.inputs.item(0, 1).setText("")
    assert "식이 비었습니다" in (panel.patch()[1] or "")

"""STU-01 아래 탭 「변수」 — 입력·출력 **정의**를 고치고, 시험 실행 중에는 **지금 값**을 보인다.

거듭 보는 것.

1. **쓰기는 캔버스를 거친다** (ADR-0022) — 「적용」은 `chk:process`를 통째로 되돌려 쓰고(모르는
   칸이 남는다) 실행 취소가 한 걸음이다.
2. **값 출처가 가상 직원이면 타입을 맞추고 잠근다** (ADR-0099, B8과 같은 표).
3. **적용 안 한 편집을 덮지 않는다** — 그림이 바뀌어 다시 읽어도 입력·출력 줄은 그대로다.
4. 여기 적은 이름이 **다른 화면의 고를 거리**가 된다 — 케이스(STU-07)·속성 패널(STU-04).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QStringListModel  # noqa: E402
from PySide6.QtWidgets import QComboBox, QLineEdit, QStyleOptionViewItem  # noqa: E402

from chaeksas.contracts.bpmn_ext import Case, InputDecl, ProcessInfo, read_process  # noqa: E402
from chaeksas.studio.case_dialog import CaseDialog  # noqa: E402
from chaeksas.studio.cases import declared_inputs, read, result_names, write  # noqa: E402
from chaeksas.studio.variables import (  # noqa: E402
    MAX_VALUE,
    InputRow,
    build_inputs,
    changed,
    known_names,
    made_by,
    parse_default,
    problem,
    process_patch,
    value_text,
)
from chaeksas.studio.variables_tab import (  # noqa: E402
    DEFAULT,
    INPUTS,
    MADE,
    NAME,
    NOW,
    OTHER,
    OUTPUTS,
    REQUIRED,
    RUNNING,
    SOURCE,
    TYPE,
    VariablesTab,
)
from chaeksas.studio.workspace import Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
RECONCILIATION = "bx01_invoice_reconciliation"  # 입력 셋이 정의돼 있다
EXPENSE = "bx03_expense_approval"  # 결재 폼 칸이 변수를 만든다


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def info_of(**fields: Any) -> ProcessInfo:
    return ProcessInfo.model_validate(fields)


# ─────────────────────────── 값 다루기 (Qt 없음) ───────────────────────────


@pytest.mark.parametrize(
    ("kind", "text", "value", "bad"),
    [
        ("string", " 그대로 ", "그대로", False),
        ("int", "3", 3, False),
        ("int", "3.5", None, True),
        ("number", "3.5", 3.5, False),
        ("bool", "true", True, False),
        ("bool", "1", None, True),
        ("list", '["가"]', ["가"], False),
        ("dict", "[1]", None, True),
        ("list", "[망가짐", None, True),
        ("number", "", None, False),
    ],
)
def test_a_default_is_read_by_its_type(kind: str, text: str, value: Any, bad: bool) -> None:
    found, why = parse_default(kind, text)
    assert found == value
    assert bool(why) is bad


def test_the_first_problem_is_said() -> None:
    """「적용」을 막는 흠 — 첫 하나만 (C14 B2·B8과 같은 규칙)."""
    assert problem([InputRow(name="")], []) == "입력의 이름을 적으세요."
    assert "쓸 수 없습니다" in problem([InputRow(name="1번")], [])
    assert "둘입니다" in problem([InputRow(name="가"), InputRow(name="가")], [])
    assert "list여야" in problem([InputRow(name="감독자", source="virtual_worker.supervisors")], [])
    assert "int가 아닙니다" not in problem([InputRow(name="수", type="int", default="3")], [])
    assert "기본값" in problem([InputRow(name="수", type="int", default="셋")], [])
    assert "출력의 이름" in problem([], [""])
    assert "같은 이름의 출력" in problem([], ["결과", "결과"])
    # 입력과 출력에 같은 이름은 된다 — 받은 값을 고쳐 내놓는 BPM 프로세스가 있다.
    assert problem([InputRow(name="건")], ["건"]) == ""


def test_building_keeps_the_fields_the_table_does_not_know() -> None:
    """읽어 온 줄은 **모르는 칸을 남긴 채** 고친다 — 부르는 쪽 출처는 적지 않는다."""
    decl = InputDecl.model_validate({"name": "건", "type": "string", "x-memo": "남는다"})
    row = InputRow.of(decl)
    made = build_inputs([InputRow(**{**row.__dict__, "required": True})])
    dumped = made[0].to_json_dict()
    assert dumped["required"] is True
    assert dumped.get("x-memo") == "남는다"
    assert "source" not in dumped, "부르는 쪽은 비운다 — 옛 그림과 같은 모양"


def test_the_patch_writes_the_whole_process_back() -> None:
    """**통째로 되돌려 쓴다** — 실행 위치·확장처럼 이 탭이 모르는 칸이 사라지지 않는다."""
    info = info_of(run_location="server", extensions=[{"id": "ui-automation", "version": ">=1"}], outputs=["옛것"])
    body = json.loads(
        process_patch(info, [InputRow(name="감독자", type="list", source="virtual_worker.supervisors")], ["결과"])
    )
    assert body["run_location"] == "server"
    assert body["extensions"][0]["id"] == "ui-automation"
    wanted = {"name": "감독자", "type": "list", "required": False, "source": "virtual_worker.supervisors"}
    assert body["inputs"] == [wanted]
    assert body["outputs"] == ["결과"]
    ProcessInfo.model_validate(body)  # C14 모델로 다시 읽힌다


def test_changed_compares_what_the_screen_shows() -> None:
    info = info_of(inputs=[{"name": "건", "type": "string"}], outputs=["결과"])
    rows = [InputRow.of(d) for d in info.inputs]
    assert not changed(info, rows, ["결과"])
    assert changed(info, rows, ["결과", "더"])
    assert changed(info, [InputRow(**{**rows[0].__dict__, "default": "기본"})], ["결과"])


def test_made_by_is_the_contract_function_and_names_the_node() -> None:
    """그림이 만드는 변수는 **계약의 `produced_vars`** 그대로다 — 검사와 다른 말을 하지 않는다."""
    drawn = read_process((EXAMPLES / f"{EXPENSE}.bpmn").read_text(encoding="utf-8"))
    made = made_by(drawn)
    assert made, "결재 폼 칸이 변수를 만든다"
    names = {n.name or n.id for n in drawn.all_nodes()}
    assert all(set(nodes) <= names for nodes in made.values())


def test_known_names_put_outputs_first_and_do_not_repeat() -> None:
    info = info_of(inputs=[{"name": "건", "type": "string"}, {"name": "결과", "type": "string"}], outputs=["결과"])
    assert known_names(info, {"판정": ["노드"], "건": ["노드"]}) == ["결과", "건", "판정"]
    assert known_names(None, {"판정": ["노드"]}) == ["판정"]


def test_a_long_value_is_cut_and_a_string_keeps_its_quotes() -> None:
    assert value_text("값") == '"값"', "글자는 따옴표째 — 1과 \"1\"을 가른다"
    assert value_text([1, 2]) == "[1, 2]"
    assert len(value_text("가" * 500)) == MAX_VALUE + 1


# ─────────────────────────── 탭 ───────────────────────────


def shown(app: Any, info: ProcessInfo, made: dict[str, list[str]] | None = None, **kwargs: Any) -> VariablesTab:
    tab = VariablesTab()
    tab.show_definition(info, made or {}, key="정의.bpmn", **kwargs)
    return tab


def test_the_tab_shows_inputs_outputs_and_what_the_drawing_makes(app: Any) -> None:
    info = info_of(
        inputs=[{"name": "건", "type": "int", "required": True, "default": 3}],
        outputs=["결과"],
    )
    tab = shown(app, info, {"판정": ["신용 판정"], "결과": ["끝"]})
    assert tab.sections.tabText(INPUTS) == "입력 (1)"
    assert tab.sections.tabText(OUTPUTS) == "출력 (1)"
    # 출력에 이미 있는 이름(「결과」)은 「그림이 만드는 변수」에 다시 적지 않는다.
    assert tab.sections.tabText(MADE) == "그림이 만드는 변수 (1)"
    made = tab.made_group.child(0)
    assert made is not None and (made.text(NAME), made.text(SOURCE)) == ("판정", "신용 판정")
    row = tab.inputs_group.child(0)
    assert row is not None and row.text(DEFAULT) == "3"
    assert row.checkState(REQUIRED).name == "Checked"
    assert tab.inputs_tree.isColumnHidden(NOW), "값이 오기 전에는 「지금 값」 열이 없다"
    assert not tab.sections.isTabVisible(OTHER)
    assert not tab.unapplied and not tab.apply_button.isEnabled()


def test_a_virtual_worker_source_pins_and_locks_the_type(app: Any) -> None:
    """ADR-0099 — 출처가 가상 직원이면 그 출처의 타입으로 맞추고 잠근다 (B8과 같은 표)."""
    tab = shown(app, info_of())
    tab._new_input()  # noqa: SLF001 — 「입력 더하기」
    item = tab.inputs_group.child(0)
    assert item is not None
    item.setText(NAME, "감독자")
    tab.set_source(item, "virtual_worker.supervisors")
    assert item.text(TYPE) == "list" and tab.type_pinned(item)
    assert item.text(SOURCE) != "virtual_worker.supervisors", "칸에는 사람이 읽는 이름이 보인다"
    assert tab.input_rows()[0].source == "virtual_worker.supervisors"
    tab.set_source(item, "caller")
    assert not tab.type_pinned(item)


def test_applying_emits_the_whole_process_and_a_problem_blocks_it(app: Any) -> None:
    info = info_of(run_location="pc", inputs=[{"name": "건", "type": "string"}])
    tab = shown(app, info)
    got: list[str] = []
    tab.applying.connect(got.append)

    item = tab.inputs_group.child(0)
    assert item is not None
    item.setText(DEFAULT, "기본")
    assert tab.unapplied and tab.apply_button.isEnabled()
    assert tab.apply() is True
    body = json.loads(got[-1])
    assert body["run_location"] == "pc"
    assert body["inputs"][0]["default"] == "기본"

    item.setText(NAME, "1번")
    assert tab.error.text() and not tab.apply_button.isEnabled()
    assert tab.apply() is False and len(got) == 1


def test_outputs_can_be_added_and_dropped(app: Any) -> None:
    tab = shown(app, info_of())
    tab._new_output()  # noqa: SLF001
    item = tab.outputs_group.child(0)
    assert item is not None
    item.setText(NAME, "결과")
    assert tab.output_names() == ["결과"] and tab.unapplied
    tab.outputs_tree.setCurrentItem(item)
    tab._drop()  # noqa: SLF001 — 「줄 삭제」
    assert tab.output_names() == [] and not tab.unapplied


def test_a_reason_locks_editing_but_keeps_the_table(app: Any) -> None:
    """U3 — 표는 보이고 고치기만 잠근다. 까닭을 안내 줄이 말한다."""
    tab = shown(app, info_of(inputs=[{"name": "건", "type": "string"}]), reason=RUNNING)
    assert tab.locked and tab.note.text() == RUNNING
    assert not tab.add_input.isEnabled() and not tab.apply_button.isEnabled()
    item = tab.inputs_group.child(0)
    assert item is not None
    assert tab.inputs_tree.itemDelegate().createEditor(  # 잠겨 있으면 칸을 열지 않는다
        tab.inputs_tree.viewport(), QStyleOptionViewItem(), tab.inputs_tree.indexFromItem(item, TYPE)
    ) is None
    tab._new_input()  # noqa: SLF001
    assert tab.inputs_group.childCount() == 1, "잠겨 있으면 줄을 더하지 않는다"


def test_values_fill_the_now_column_and_the_rest_goes_to_other(app: Any) -> None:
    tab = shown(app, info_of(inputs=[{"name": "건", "type": "string"}], outputs=["결과"]))
    tab.show_values({"건": "가", "오늘": "2026-10-26"})
    assert not tab.inputs_tree.isColumnHidden(NOW)
    first = tab.inputs_group.child(0)
    output = tab.outputs_group.child(0)
    other = tab.other_group.child(0)
    assert first is not None and first.text(NOW) == '"가"'
    assert output is not None and output.text(NOW) == "—", "아직 없는 이름"
    assert other is not None and other.text(NAME) == "오늘" and tab.sections.isTabVisible(OTHER)
    tab.clear_values()
    assert tab.inputs_tree.isColumnHidden(NOW) and not tab.sections.isTabVisible(OTHER)


def test_values_stay_until_another_definition_is_shown(app: Any) -> None:
    info = info_of(outputs=["결과"])
    tab = shown(app, info)
    tab.show_values({"결과": 1})
    tab.show_definition(info, {}, key="정의.bpmn")
    assert tab.values == {"결과": 1}, "같은 정의를 다시 읽어도 값은 남는다"
    tab.show_definition(info, {}, key="다른.bpmn")
    assert tab.values is None


def test_rereading_the_drawing_does_not_overwrite_unapplied_edits(app: Any) -> None:
    """그림이 바뀌어 다시 읽어도 **사람이 고치던 것을 덮지 않는다** — 그림이 만드는 변수만 바뀐다."""
    info = info_of(inputs=[{"name": "건", "type": "string"}])
    tab = shown(app, info)
    item = tab.inputs_group.child(0)
    assert item is not None
    item.setText(NAME, "고친건")
    tab.show_definition(info, {"새것": ["노드"]}, key="정의.bpmn")
    again = tab.inputs_group.child(0)
    assert again is not None and again.text(NAME) == "고친건"
    assert tab.made_group.child(0) is not None
    tab.discard()
    back = tab.inputs_group.child(0)
    assert back is not None and back.text(NAME) == "건" and not tab.unapplied


def test_without_a_process_nothing_is_editable(app: Any) -> None:
    tab = VariablesTab()
    tab.show_definition(None, {}, key="")
    assert tab.locked and not tab.add_input.isEnabled()
    assert tab.patch() == (None, "열린 BPM 프로세스가 없습니다.")


def test_one_section_at_a_time_with_buttons_that_fit_it(app: Any) -> None:
    """STU-01 「변수」 탭 [S]·[B] — 무리 하나만 보이고 단추는 그 무리에 맞는 것만, 강조색은 「적용」 하나."""
    tab = shown(app, info_of(inputs=[{"name": "건", "type": "string"}]), {"판정": ["신용 판정"]})
    assert tab.sections.currentIndex() == INPUTS and tab.stack.currentIndex() == INPUTS
    assert not tab.add_input.isHidden() and tab.add_output.isHidden() and not tab.drop_row.isHidden()
    tab.sections.setCurrentIndex(OUTPUTS)
    assert tab.add_input.isHidden() and not tab.add_output.isHidden()
    tab.sections.setCurrentIndex(MADE)
    assert tab.stack.currentIndex() == MADE
    assert tab.add_input.isHidden() and tab.add_output.isHidden() and tab.drop_row.isHidden()
    assert {b.objectName() for b in (tab.add_input, tab.add_output, tab.drop_row)} == {"Secondary"}
    assert tab.apply_button.objectName() != "Secondary"


def test_finding_filters_what_the_drawing_makes(app: Any) -> None:
    tab = shown(app, info_of(), {"판정": ["신용 판정"], "금액": ["계산"], "결재의견": ["팀장 승인"]})
    tab.find_box.setText("승인")
    shown_names = [one.text(NAME) for one in (tab.made_group.child(i) for i in range(3)) if one and not one.isHidden()]
    assert shown_names == ["결재의견"], "만드는 곳으로도 찾는다"
    tab.find_box.clear()
    assert all(not tab.made_group.child(i).isHidden() for i in range(3))  # type: ignore[union-attr]


def test_cells_read_as_text_and_open_an_editor_when_pressed(app: Any) -> None:
    """STU-01 「변수」 탭 [T] — 평소에는 글자, 누르면 그 자리의 편집기 (타입·값 출처는 콤보)."""
    tab = shown(app, info_of(inputs=[{"name": "건", "type": "string"}]))
    item = tab.inputs_group.child(0)
    assert item is not None and item.text(TYPE) == "string" and item.text(SOURCE) == "부르는 쪽"
    assert tab.inputs_tree.itemWidget(item, TYPE) is None, "콤보를 늘 그려 두지 않는다"
    delegate, viewport = tab.inputs_tree.itemDelegate(), tab.inputs_tree.viewport()
    kind = delegate.createEditor(viewport, QStyleOptionViewItem(), tab.inputs_tree.indexFromItem(item, TYPE))
    assert isinstance(kind, QComboBox)
    kind.setCurrentText("int")
    delegate.setModelData(kind, tab.inputs_tree.model(), tab.inputs_tree.indexFromItem(item, TYPE))
    assert item.text(TYPE) == "int" and tab.unapplied
    name = delegate.createEditor(viewport, QStyleOptionViewItem(), tab.inputs_tree.indexFromItem(item, NAME))
    assert isinstance(name, QLineEdit)


# ─────────────────────────── 케이스 (STU-07) ───────────────────────────


def imported(tmp_path: Path, example: str) -> Any:
    made = Workspace(tmp_path / "작업").ensure().import_example(EXAMPLES, example)
    assert made.entry_definition is not None
    return made, made.entry_definition


def test_declared_inputs_are_laid_out_and_empty_ones_are_not_saved(app: Any, tmp_path: Path) -> None:
    """정의된 입력은 케이스에 없어도 줄로 깔린다 — **비운 채 둔 줄은 담지 않는다** (기본값이 쓰인다)."""
    made, definition = imported(tmp_path, RECONCILIATION)
    names = declared_inputs(definition)
    assert len(names) >= 2
    edited = read(made, definition)
    edited.cases = [Case(name="하나", inputs={names[0]: "적은 값"})]
    write(edited)

    dialog = CaseDialog(None, made, definition)
    laid = [dialog.inputs.cellWidget(row, 0) for row in range(dialog.inputs.rowCount())]
    assert [box.currentText() for box in laid if isinstance(box, QComboBox)] == names
    second = laid[1]
    assert isinstance(second, QComboBox) and second.toolTip(), "필수·설명을 툴팁이 말한다"

    assert dialog.save() is True
    assert read(made, definition).cases[0].inputs == {names[0]: "적은 값"}

    value = dialog.inputs.item(1, 2)
    assert value is not None
    value.setText("둘째 값")
    assert dialog.save() is True
    assert read(made, definition).cases[0].inputs[names[1]] is not None


def test_the_expected_name_is_picked_from_the_list(app: Any, tmp_path: Path) -> None:
    made, definition = imported(tmp_path, EXPENSE)
    dialog = CaseDialog(None, made, definition)
    dialog._add()  # noqa: SLF001
    dialog.expected_block.add_row()
    box = dialog.expected.cellWidget(0, 0)
    assert isinstance(box, QComboBox) and box.isEditable()
    assert [box.itemText(i) for i in range(box.count())] == result_names(definition)
    assert result_names(definition), "결재 폼 칸이 고를 거리가 된다"


# ─────────────────────────── 변수 이름 칸 (STU-04) ───────────────────────────


def completions(line: QLineEdit) -> list[str]:
    found = line.completer()
    assert found is not None, "고를 거리가 달려 있지 않다"
    model = found.model()
    return [model.index(i, 0).data() for i in range(model.rowCount())]


def test_the_approval_editor_offers_the_known_names(app: Any) -> None:
    from chaeksas.studio.approval_editor import ApprovalEditor  # noqa: PLC0415

    names = QStringListModel(["결과", "감독자"])
    editor = ApprovalEditor(names=names)
    for line in (editor.show_input, editor.expires_box, editor.answered_by_box, editor.answered_via_box):
        assert completions(line) == ["결과", "감독자"]
    # 담당자는 「변수 이름 하나」일 때만 — 이름 목록에 변수 이름을 권하지 않는다.
    assert completions(editor.assignee_box) == []
    editor.assignee_mode.setCurrentIndex(editor.assignee_mode.findData("variable"))
    assert completions(editor.assignee_box) == ["결과", "감독자"]
    names.setStringList(["새것"])
    assert completions(editor.show_input) == ["새것"], "같은 모델을 본다 — 그림이 바뀌면 따라 바뀐다"


def test_the_service_editor_name_cells_offer_the_known_names(app: Any) -> None:
    from chaeksas.studio.name_pick import NameDelegate  # noqa: PLC0415
    from chaeksas.studio.service_catalog import Catalog  # noqa: PLC0415
    from chaeksas.studio.service_editor import ServiceTaskEditor  # noqa: PLC0415

    names = QStringListModel(["결과"])
    editor = ServiceTaskEditor(Catalog(), names=names)
    for table, column in ((editor.inputs, 3), (editor.outputs, 1)):
        delegate = table.itemDelegateForColumn(column)
        assert isinstance(delegate, NameDelegate) and delegate.names is names


# ─────────────────────────── 메인 창과 캔버스 ───────────────────────────


_PROBE: list[Any] = []


def wait_for(condition: Callable[[], bool], ms: int = 30_000) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if condition() else None)
    poll.start(50)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    poll.stop()
    return condition()


@pytest.fixture
def window(app: Any, tmp_path: Path) -> Any:
    """뜬 캔버스를 쥔 메인 창 — WebEngine이 못 뜨면 건너뛴다 (`test_studio_canvas`와 같은 태도)."""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: PLC0415

        if not _PROBE:
            _PROBE.append(QWebEngineView())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    from chaeksas.studio.main_window import MainWindow  # noqa: PLC0415
    from chaeksas.studio.settings import Settings  # noqa: PLC0415

    found = MainWindow(Settings(data_dir=tmp_path))
    if not wait_for(lambda: found.canvas.live):
        pytest.skip("캔버스가 30초 안에 뜨지 않았다 (WebEngine이 이 환경에서 막혀 있다)")
    return found


def test_applying_goes_through_the_canvas_and_undoes_in_one_step(window: Any) -> None:
    """ADR-0022 — 「적용」은 캔버스로 가고 **실행 취소 한 걸음**에 되돌아간다. 파일은 그대로다."""
    from chaeksas.studio import file_actions  # noqa: PLC0415

    made = window.workspace.import_example(EXAMPLES, RECONCILIATION)
    path = made.entry_definition.path
    before = path.read_text(encoding="utf-8")
    file_actions.open_definition(window, path.as_posix())
    tab = window.variables
    assert wait_for(lambda: tab.inputs_group.childCount() == len(declared_inputs(made.entry_definition)))
    assert not tab.locked
    assert window.properties.known_names.stringList(), "속성 패널의 고를 거리도 채운다"

    tab._new_output()  # noqa: SLF001
    item = tab.outputs_group.child(tab.outputs_group.childCount() - 1)
    item.setText(NAME, "새출력")
    assert tab.apply() is True
    assert wait_for(lambda: "새출력" in read_process(window.canvas.save_xml()).info.outputs)
    drawn = read_process(window.canvas.save_xml()).info
    assert drawn.run_location == read_process(before).info.run_location, "모르는 칸은 남는다"
    assert path.read_text(encoding="utf-8") == before, "파일로 가는 것은 「저장」이다"
    assert wait_for(lambda: not tab.unapplied)

    window.canvas.call_sync("undo")
    assert "새출력" not in read_process(window.canvas.save_xml()).info.outputs


def test_a_test_run_locks_the_tab_and_shows_values(window: Any) -> None:
    window.variables_running(True)
    assert window.variables.locked and window.variables.values is None
    window.show_variables({"건": 1})
    assert window.variables.values == {"건": 1}
    window.variables_running(False)
    assert window.variables.values == {"건": 1}, "끝나도 값은 남는다"

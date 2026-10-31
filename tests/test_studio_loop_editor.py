"""STU-04 반복 편집기 (`studio/loop_editor.py`) — 화면 없이.

보는 것은 넷이다: 그림에 적힌 것이 **다 보이는가**, 손대지 않으면 **C14 모델로 같은 뜻인가**(업무 예제
전부), 엔진·검사가 거부할 것을 **「적용」 전에 막는가**, 그리고 **다른 편집기 옆에 붙어 서로의 칸을
지우지 않는가**(속성 패널이 둘의 고친 것을 합친다).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Loop  # noqa: E402
from chaeksas.studio.loop_editor import (  # noqa: E402
    MODE_NONE,
    MODE_PARALLEL,
    MODE_SEQUENTIAL,
    NO_RESULT,
    LoopEditor,
)

LOOP: dict[str, Any] = {
    "collection": "거래처목록",
    "item": "거래처",
    "result": "신용",
    "collect_into": "신용목록",
}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(mode: str, loop: dict[str, Any] | None, *, run_location: str | None = None) -> LoopEditor:
    made = LoopEditor(run_location=run_location)
    made.load({"multiInstance": mode, "loop": loop})
    return made


def test_everything_in_a_loop_is_shown() -> None:
    made = loaded(MODE_PARALLEL, LOOP)
    assert made.mode() == MODE_PARALLEL
    assert made.collection_box.text() == "거래처목록"
    assert made.item_box.text() == "거래처"
    assert made.result_box.text() == "신용"
    assert made.collect_box.text() == "신용목록"
    assert made.problems() == ([], [])


def test_an_untouched_dump_reads_back_the_same() -> None:
    made = loaded(MODE_SEQUENTIAL, LOOP)
    assert made.dump() == {"multiInstance": MODE_SEQUENTIAL, "loop": LOOP}


def test_unknown_keys_survive() -> None:
    made = loaded(MODE_SEQUENTIAL, {**LOOP, "future": 1})
    assert made.dump()["loop"]["future"] == 1


def test_a_loop_without_the_marker_shows_as_in_turn() -> None:
    """표시 없이 `bpm:loop`만 있으면 엔진은 차례로 돈다 — 그렇게 보인다."""
    assert loaded(MODE_NONE, LOOP).mode() == MODE_SEQUENTIAL


def test_a_plain_task_opens_without_a_loop() -> None:
    made = loaded(MODE_NONE, None)
    assert made.mode() == MODE_NONE
    assert made.fields.isHidden()
    assert made.dump() == {"multiInstance": MODE_NONE, "loop": None}
    assert made.problems() == ([], [])


def test_every_example_loop_round_trips() -> None:
    """업무 예제의 반복이 **손대지 않으면 같은 뜻으로** 돌아온다 — 표시(차례로·함께)까지."""
    from chaeksas.contracts.bpmn_ext import read_process  # noqa: PLC0415

    seen = set()
    for path in sorted(Path("docs/08-business-examples/bpmn").glob("*.bpmn")):
        for node in read_process(path.read_text(encoding="utf-8")).all_nodes():
            spec = node.prop("loop")
            if spec is None:
                continue
            assert node.is_sequential is not None, f"{path.name}:{node.id} — 예제는 표시를 단다"
            mode = MODE_SEQUENTIAL if node.is_sequential else MODE_PARALLEL
            made = loaded(mode, spec.model_dump(exclude_unset=True))
            assert made.problems()[0] == [], f"{path.name}:{node.id}"
            out = made.dump()
            assert out["multiInstance"] == mode
            assert Loop.model_validate(out["loop"]) == spec, f"{path.name}:{node.id}"
            seen.add(mode)
    assert seen == {MODE_SEQUENTIAL, MODE_PARALLEL}, "예제에 둘 다 있다"


@pytest.mark.parametrize(
    ("box", "value", "said"),
    [
        ("collection_box", "", "반복할 목록을 적으세요."),
        ("collection_box", "목록[", "목록 식을 읽을 수 없습니다"),
        ("item_box", "", "「한 건 이름」을 적으세요."),
        ("collect_box", "", "「모은 목록」을 적으세요 — 없으면 반복이 멈춥니다 (B4)."),
        ("item_box", "1번", "「한 건 이름」에 변수 이름으로 쓸 수 없는 것이 있습니다: 1번"),
        ("result_box", "a-b", "「한 건의 결과」에 변수 이름으로 쓸 수 없는 것이 있습니다: a-b"),
    ],
)
def test_what_would_fail_blocks_apply(box: str, value: str, said: str) -> None:
    made = loaded(MODE_SEQUENTIAL, LOOP)
    getattr(made, box).setText(value)
    errors, _ = made.problems()
    assert errors and errors[0].startswith(said)


def test_an_expression_is_a_fine_collection() -> None:
    made = loaded(MODE_SEQUENTIAL, LOOP)
    made.collection_box.setText("거래처목록 + 추가목록")
    assert made.problems()[0] == []


def test_no_result_and_same_names_are_warnings() -> None:
    made = loaded(MODE_SEQUENTIAL, LOOP)
    made.result_box.setText("")
    errors, warnings = made.problems()
    assert errors == [] and warnings == [NO_RESULT]
    assert "result" not in made.dump()["loop"], "빈 칸은 적지 않는다"

    made.result_box.setText("거래처")
    errors, warnings = made.problems()
    assert errors == [] and any("거래처" in one for one in warnings)


def test_the_collection_may_be_the_collected_list() -> None:
    """원본을 결과로 바꿔 쓰는 꼴은 말하지 않는다."""
    made = loaded(MODE_SEQUENTIAL, {**LOOP, "collect_into": "거래처목록"})
    assert made.problems() == ([], [])


def test_parallel_on_a_pc_says_it_runs_in_turn() -> None:
    pc = loaded(MODE_PARALLEL, LOOP, run_location="pc")
    assert not pc.pc_note.isHidden()
    server = loaded(MODE_PARALLEL, LOOP, run_location="server")
    assert server.pc_note.isHidden()
    pc.mode_picks[MODE_SEQUENTIAL].setChecked(True)
    assert pc.pc_note.isHidden()


def test_turning_it_off_drops_the_body_and_ignores_the_fields() -> None:
    made = loaded(MODE_SEQUENTIAL, LOOP)
    made.item_box.setText("")
    made.mode_picks[MODE_NONE].setChecked(True)
    assert made.dump() == {"multiInstance": MODE_NONE, "loop": None}
    assert made.problems() == ([], []), "끈 반복의 빈 칸으로 막지 않는다"


# ── 속성 패널 ──


def panel_with(bpmn_type: str, chk: dict[str, Any], mode: str = "", *, run_location: str | None = None) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.run_location = run_location
    panel.show_element({
        "id": "Task_1", "type": bpmn_type, "name": "신용 조회",
        "multiInstance": mode,
        "chk": {name: json.dumps(body, ensure_ascii=False) for name, body in chk.items()},
    })
    return panel


def tab_texts(panel: Any) -> list[str]:
    return [panel.tabs.tabText(i) for i in range(panel.tabs.count())]


AI = {"goal": "신용을 본다", "domain": "llm", "results": {"신용": "string"}}


@pytest.mark.parametrize("bpmn_type", ["ServiceTask", "BusinessRuleTask", "CallActivity"])
def test_the_loop_tab_sits_beside_the_others(bpmn_type: str) -> None:
    panel = panel_with(bpmn_type, {"loop": LOOP}, MODE_SEQUENTIAL)
    texts = tab_texts(panel)
    assert "반복" in texts and texts[-1] == "JSON"
    assert panel.tabs.currentIndex() != texts.index("반복"), "반복 탭을 고르지는 않는다"
    assert panel.patch() == ({}, None), "손대지 않으면 보내지 않는다"


@pytest.mark.parametrize("bpmn_type", ["UserTask", "SendTask", "ScriptTask", "ExclusiveGateway", "SequenceFlow"])
def test_no_loop_tab_where_loops_do_not_go(bpmn_type: str) -> None:
    assert "반복" not in tab_texts(panel_with(bpmn_type, {}))


def test_an_ai_task_and_its_loop_both_have_tabs() -> None:
    panel = panel_with("ServiceTask", {"aiTask": AI, "loop": LOOP}, MODE_PARALLEL)
    assert tab_texts(panel) == ["폼", "AI 태스크", "반복", "JSON"]
    assert panel.tabs.currentIndex() == 1


def test_changing_only_the_loop_leaves_the_ai_task_alone() -> None:
    panel = panel_with("ServiceTask", {"aiTask": AI, "loop": LOOP}, MODE_SEQUENTIAL)
    panel._loop_editor.result_box.setText("등급")  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert list(changes) == ["chk"] and list(changes["chk"]) == ["loop"]
    assert json.loads(changes["chk"]["loop"])["result"] == "등급"


def test_changing_both_sends_both() -> None:
    panel = panel_with("ServiceTask", {"aiTask": AI, "loop": LOOP}, MODE_SEQUENTIAL)
    panel._editor.goal_box.setPlainText("다른 목표")  # noqa: SLF001
    panel._loop_editor.mode_picks[MODE_PARALLEL].setChecked(True)  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert changes["multiInstance"] == MODE_PARALLEL
    assert set(changes["chk"]) == {"aiTask"}, "본문이 그대로면 bpm:loop는 보내지 않는다"
    assert json.loads(changes["chk"]["aiTask"])["goal"] == "다른 목표"


def test_a_call_keeps_its_called_element_beside_the_loop() -> None:
    panel = panel_with("CallActivity", {"call": {"output": {"신용": "신용"}}, "loop": LOOP}, MODE_SEQUENTIAL)
    panel._loop_editor.collect_box.setText("모은신용")  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert "calledElement" not in changes and set(changes["chk"]) == {"loop"}


def test_a_new_loop_adds_the_marker_and_the_body() -> None:
    panel = panel_with("ServiceTask", {"aiTask": AI})
    editor: Any = panel._loop_editor  # noqa: SLF001
    editor.mode_picks[MODE_SEQUENTIAL].setChecked(True)
    changes, problem = panel.patch()
    assert changes == {} and problem == "반복할 목록을 적으세요."
    for box, value in (("collection_box", "거래처목록"), ("item_box", "거래처"), ("collect_box", "신용목록")):
        getattr(editor, box).setText(value)
    changes, problem = panel.patch()
    assert problem is None
    assert changes["multiInstance"] == MODE_SEQUENTIAL
    wanted = {"collection": "거래처목록", "item": "거래처", "collect_into": "신용목록"}
    assert json.loads(changes["chk"]["loop"]) == wanted


def test_turning_a_loop_off_removes_both() -> None:
    panel = panel_with("BusinessRuleTask", {"loop": LOOP}, MODE_PARALLEL)
    panel._loop_editor.mode_picks[MODE_NONE].setChecked(True)  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert changes == {"multiInstance": MODE_NONE, "chk": {"loop": None}}


def test_a_blocking_loop_problem_blocks_the_panel() -> None:
    panel = panel_with("ServiceTask", {"loop": LOOP}, MODE_SEQUENTIAL)
    panel._loop_editor.collect_box.setText("")  # noqa: SLF001
    changes, problem = panel.patch()
    assert changes == {} and problem is not None and "B4" in problem
    assert not panel.apply_button.isEnabled()


def test_the_panel_passes_the_run_location() -> None:
    panel = panel_with("ServiceTask", {"loop": LOOP}, MODE_PARALLEL, run_location="pc")
    assert not panel._loop_editor.pc_note.isHidden()  # noqa: SLF001

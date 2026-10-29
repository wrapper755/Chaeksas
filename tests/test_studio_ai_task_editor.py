"""STU-04 AI 태스크 편집기 (`studio/ai_task_editor.py`) — 화면 없이.

보는 것은 넷이다: 그림에 적힌 것이 **다 보이는가**, 손대지 않으면 **같은 본문으로** 돌아오는가
(업무 예제의 AI 태스크 전부 — 편집기가 다루지 않는 칸까지), 엔진·검사가 거부할 것을 **「적용」 전에
막는가**, 속성 패널이 **`chk:aiTask` 통째로** 캔버스에 넘기는가.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import AiTask, read_process  # noqa: E402
from chaeksas.studio.ai_task_editor import (  # noqa: E402
    GOAL_OUTLINE,
    SERVER_NO_SCREEN,
    AiTaskEditor,
    builtin_tool_descriptions,
)

BODY: dict[str, Any] = {
    "goal": "## 할 일\n`청구서`에서 금액을 읽는다.",
    "domain": "doc",
    "tools": ["pdf_text_tool", "image_ocr_tool"],
    "params": {"통화": "KRW", "허용오차": 0.5, "필드": ["금액", "날짜"], "규칙": {"반올림": True}},
    "results": {"금액": "number", "날짜": "date", "비고": "string"},
    "replay": "full",
    "limits": {"timeout_s": 20, "max_steps": 6},
    "forbidden_actions": ["삭제"],
    "confirm_triggers": ["100만원 이상"],
}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(body: dict[str, Any], *, run_location: str | None = None) -> AiTaskEditor:
    made = AiTaskEditor(run_location=run_location)
    made.load(body)
    return made


def cell(table: Any, row: int, column: int) -> Any:
    found = table.item(row, column)
    assert found is not None
    return found


def _param_cells(made: AiTaskEditor) -> list[tuple[str, str, str]]:
    out = []
    for row in range(made.params.rowCount()):
        combo: Any = made.params.cellWidget(row, 1)
        out.append((cell(made.params, row, 0).text(), combo.currentText(), cell(made.params, row, 2).text()))
    return out


def test_everything_in_an_ai_task_is_shown() -> None:
    made = loaded(BODY)
    assert made.goal_box.toPlainText() == BODY["goal"]
    assert made.domain() == "doc"
    assert made.tools() == ["pdf_text_tool", "image_ocr_tool"]
    assert "image_ocr_tool" in made.tool_checks, "내장이 아닌 도구도 지우지 않고 보인다"
    assert _param_cells(made) == [
        ("통화", "string", "KRW"),
        ("허용오차", "number", "0.5"),
        ("필드", "list", '["금액", "날짜"]'),
        ("규칙", "dict", '{"반올림": true}'),
    ]
    assert made.replay() == "full"
    assert made.max_steps_box.value() == 6


def test_the_builtin_tools_are_offered_with_the_descriptions_the_model_sees() -> None:
    made = loaded({"goal": "g", "domain": "llm"})
    builtin = builtin_tool_descriptions()
    assert set(builtin) >= {"http_request_tool", "pdf_text_tool", "excel_parser_tool", "csv_parser_tool"}
    for name, text in builtin.items():
        assert made.tool_checks[name].toolTip() == text


def test_an_untouched_dump_reads_back_the_same() -> None:
    made = loaded(BODY)
    errors, warnings = made.problems()
    assert errors == []
    assert any("image_ocr_tool" in w for w in warnings)
    assert made.dump() == BODY


def test_every_example_ai_task_round_trips() -> None:
    """업무 예제의 AI 태스크가 **손대지 않으면 같은 본문으로** 돌아온다 — 편집기가 조용히 바꾸지 않는다."""
    seen = 0
    for path in sorted(Path("docs/08-business-examples/bpmn").glob("*.bpmn")):
        for node in read_process(path.read_text(encoding="utf-8")).all_nodes():
            model = node.prop("aiTask")
            if model is None:
                continue
            seen += 1
            body = json.loads(model.model_dump_json(exclude_unset=True))
            made = loaded(body)
            assert made.problems()[0] == [], f"{path.name}:{node.id}"
            assert made.dump() == body, f"{path.name}:{node.id}"
            assert AiTask.model_validate(made.dump()) == model
    assert seen > 30, "예제의 AI 태스크를 찾았다"


def test_editing_a_param_value_writes_it_with_its_type() -> None:
    made = loaded(BODY)
    cell(made.params, 1, 2).setText("2")
    assert made.dump()["params"]["허용오차"] == 2
    combo: Any = made.params.cellWidget(0, 1)
    cell(made.params, 0, 2).setText("[1, 2]")
    combo.setCurrentText("list")
    assert made.dump()["params"]["통화"] == [1, 2]


def test_a_new_tool_and_a_new_result_are_written() -> None:
    made = loaded({"goal": "g", "domain": "llm", "results": {"답": "string"}})
    made.tool_checks["http_request_tool"].setChecked(True)
    made.tool_input.setText("my_tool")
    made.add_tool_name()
    made.add_result.click()
    cell(made.results, 1, 0).setText("점수")
    combo: Any = made.results.cellWidget(1, 1)
    combo.setCurrentText("int")
    out = made.dump()
    assert out["tools"] == ["http_request_tool", "my_tool"]
    assert out["results"] == {"답": "string", "점수": "int"}


def test_defaults_are_not_written() -> None:
    made = loaded({"goal": "g", "domain": "llm"})
    made.goal_box.setPlainText("바뀐 목표")
    assert made.dump() == {"goal": "바뀐 목표", "domain": "llm"}


def test_limits_are_written_field_by_field() -> None:
    made = loaded(BODY)
    assert (made.max_steps_box.value(), made.timeout_box.value()) == (6, 20)
    made.max_steps_box.setValue(0)
    assert made.dump()["limits"] == {"timeout_s": 20}
    made.timeout_box.setValue(0)
    assert "limits" not in made.dump()
    made = loaded({"goal": "g", "domain": "llm"})
    made.timeout_box.setValue(90)
    assert made.dump()["limits"] == {"timeout_s": 90}


def test_instructions_are_one_per_line() -> None:
    """지시문은 **줄마다 하나**이고 빈 줄은 버린다 — 엔진이 읽는다 (ADR-0105)."""
    made = loaded(BODY)
    assert made.forbidden_box.toPlainText() == "삭제"
    assert made.confirm_box.toPlainText() == "100만원 이상"
    made.forbidden_box.setPlainText("삭제\n\n  메일을 보내지 않는다  ")
    made.confirm_box.setPlainText("")
    out = made.dump()
    assert out["forbidden_actions"] == ["삭제", "메일을 보내지 않는다"]
    # 비우면 BPM 프로세스 기본값을 따른다 — 그림에 칸이 있었으면 빈 목록으로 남는다(뜻이 같다).
    assert out["confirm_triggers"] == []
    made = loaded({"goal": "g", "domain": "llm"})
    made.confirm_box.setPlainText("\n")
    assert "confirm_triggers" not in made.dump()


def test_an_empty_instruction_list_that_was_written_stays() -> None:
    body = {"goal": "g", "domain": "llm", "forbidden_actions": []}
    assert loaded(body).dump() == body


def test_the_form_says_forbidden_actions_do_not_block() -> None:
    """금지 행동은 **모델에게 주는 말일 뿐**이다 — 화면이 「막아 준다」고 읽히면 안 된다."""
    from PySide6.QtWidgets import QLabel

    from chaeksas.studio.ai_task_editor import CONFIRM_NOTE, FORBIDDEN_NOTE

    texts = [one.text() for one in loaded(BODY).findChildren(QLabel)]
    assert FORBIDDEN_NOTE in texts and "막지는 않습니다" in FORBIDDEN_NOTE
    assert CONFIRM_NOTE in texts and "ESCALATED" in CONFIRM_NOTE


def test_the_outline_goes_only_into_an_empty_goal() -> None:
    made = loaded({"goal": "", "domain": "llm"})
    assert made.outline_button.isEnabled()
    made.insert_outline()
    assert made.goal_box.toPlainText() == GOAL_OUTLINE
    assert not made.outline_button.isEnabled()
    made.insert_outline()
    assert made.goal_box.toPlainText() == GOAL_OUTLINE


def test_desktop_shows_the_app_and_writes_it() -> None:
    made = loaded({"goal": "g", "domain": "llm"})
    assert made.app_box.isHidden()
    made.domain_picks["desktop"].setChecked(True)
    assert not made.app_box.isHidden()
    assert any("띄울 앱" in w for w in made.problems()[1])
    made.app_box.setText("legacy-erp")
    assert made.dump()["desktop"] == {"app": "legacy-erp"}
    assert made.problems() == ([], [])


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda m: m.results.item(0, 0).setText(""), "결과 필드 이름을 적으세요."),
        (lambda m: m.results.item(0, 0).setText("날짜"), "결과 필드 이름이 겹칩니다: 날짜"),
        (lambda m: m.results.item(0, 0).setText("1등"), "결과 필드 이름은 변수 이름이어야 합니다: 1등"),
        (lambda m: m.params.item(0, 0).setText(""), "업무 파라미터 이름을 적으세요."),
        (lambda m: m.params.item(1, 0).setText("통화"), "업무 파라미터 이름이 겹칩니다: 통화"),
        (lambda m: m.params.item(1, 2).setText("많이"), "업무 파라미터 허용오차: 수가 아닙니다: 많이"),
        (lambda m: m.params.item(2, 2).setText("{}"), "업무 파라미터 필드: list가 아닙니다: {}"),
        (lambda m: m.params.item(0, 2).setText(""), "업무 파라미터 통화: 값을 적으세요."),
        (
            lambda m: [c.setChecked(False) for c in m.tool_checks.values()],
            "도구가 없는 AI 태스크에는 재생 「전부」(full)를 쓸 수 없습니다 (B12).",
        ),
    ],
)
def test_what_the_engine_or_checks_refuse_blocks_apply(change: Any, said: str) -> None:
    made = loaded(BODY)
    change(made)
    errors, _ = made.problems()
    assert errors and errors[0] == said
    assert made.warning.text() == said


def test_a_code_like_int_result_is_a_warning() -> None:
    made = loaded({"goal": "g", "domain": "llm", "results": {"발주번호": "int"}})
    errors, warnings = made.problems()
    assert errors == []
    assert any("발주번호" in w and "B8" in w for w in warnings)


def test_an_unknown_domain_is_kept_but_blocks_a_change() -> None:
    made = loaded({"goal": "g", "domain": "fax"})
    assert made.domain() == ""
    assert made.dump()["domain"] == "fax"
    assert "fax" in made.problems()[0][0]


def test_on_the_server_web_and_desktop_are_off() -> None:
    made = loaded({"goal": "g", "domain": "llm"}, run_location="server")
    assert not made.domain_picks["web"].isEnabled()
    assert not made.domain_picks["desktop"].isEnabled()
    assert SERVER_NO_SCREEN in made.domain_note.text()
    # 이미 골라 둔 것은 지우지 않는다 — 막고 까닭을 말한다 (B6).
    made = loaded({"goal": "g", "domain": "desktop", "desktop": {"app": "x"}}, run_location="server")
    assert made.domain_picks["desktop"].isEnabled()
    assert made.problems()[0] == [SERVER_NO_SCREEN]


# ── 속성 패널 ──


def panel_with(body: dict[str, Any], *, run_location: str | None = None) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.run_location = run_location
    panel.show_element({
        "id": "Task_Ai", "type": "ServiceTask", "name": "읽기",
        "chk": {"aiTask": json.dumps(body, ensure_ascii=False)},
    })
    return panel


def test_the_properties_panel_attaches_it_and_applies_the_whole_body() -> None:
    panel = panel_with(BODY)
    assert panel.tabs.tabText(1) == "AI 태스크"
    editor: Any = panel._editor  # noqa: SLF001
    editor.goal_box.setPlainText("바뀐 목표")
    changes, problem = panel.patch()
    assert problem is None
    assert list(changes["chk"]) == ["aiTask"]
    assert json.loads(changes["chk"]["aiTask"]) == {**BODY, "goal": "바뀐 목표"}


def test_an_untouched_ai_task_sends_nothing() -> None:
    panel = panel_with(BODY)
    assert panel.patch() == ({}, None)


def test_a_blocking_problem_blocks_the_panel() -> None:
    panel = panel_with(BODY)
    editor: Any = panel._editor  # noqa: SLF001
    editor.results.item(0, 0).setText("")
    changes, problem = panel.patch()
    assert changes == {} and problem == "결과 필드 이름을 적으세요."


def test_the_panel_passes_the_run_location() -> None:
    panel = panel_with({"goal": "g", "domain": "llm"}, run_location="server")
    editor: Any = panel._editor  # noqa: SLF001
    assert not editor.domain_picks["web"].isEnabled()

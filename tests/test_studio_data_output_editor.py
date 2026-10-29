"""STU-04 파일 출력 편집기 (`studio/data_output_editor.py`) — 화면 없이, 끝에 캔버스 왕복.

보는 것은 넷이다: 그림에 적힌 것이 **다 보이는가**, 손대지 않으면 **C14 모델로 같은 뜻인가**(업무 예제
전부), 엔진·검사(B5·B12)가 거부할 것을 **「적용」 전에 막는가**, 그리고 속성 패널이 `chk:dataOutput`을
**통째로 쓰고 끄면 지우는가**.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import FILE_FORMATS, DataOutput, read_process  # noqa: E402
from chaeksas.studio.data_output_editor import (  # noqa: E402
    BOTH_WRITTEN,
    CONTENT_TEMPLATE,
    CONTENT_VARIABLES,
    FORMATS,
    SHEET_UNUSED,
    DataOutputEditor,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
MD: dict[str, Any] = {"path": "결과/{대상월}.md", "format": "md", "template": "# {대상월}\n", "store_as": "결과파일"}
XLSX: dict[str, Any] = {"path": "장부.xlsx", "format": "xlsx", "variables": ["거래목록"], "sheet": "거래",
                        "store_as": "장부파일"}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(body: dict[str, Any] | None) -> DataOutputEditor:
    made = DataOutputEditor()
    made.load(body)
    return made


def test_the_formats_are_the_contract_s() -> None:
    assert {value for value, _ in FORMATS} == FILE_FORMATS


def test_everything_in_a_template_output_is_shown() -> None:
    made = loaded(MD)
    assert made.on_box.isChecked()
    assert made.path_box.text() == "결과/{대상월}.md" and made.fmt() == "md"
    assert made.content() == CONTENT_TEMPLATE and made.template_box.toPlainText() == "# {대상월}\n"
    assert made.store_box.text() == "결과파일"
    assert made.sheet_box.isHidden(), "시트는 엑셀에서만"
    assert made.problems() == ([], [])
    assert made.dump() == MD


def test_a_spreadsheet_shows_its_sheet_and_variables() -> None:
    made = loaded(XLSX)
    assert made.content() == CONTENT_VARIABLES and made.variables_box.text() == "거래목록"
    assert not made.sheet_box.isHidden() and made.sheet_box.text() == "거래"
    assert not made.content_picks[CONTENT_TEMPLATE].isEnabled(), "엑셀에는 템플릿이 없다"
    assert made.dump() == XLSX


def test_every_example_output_round_trips() -> None:
    """업무 예제의 파일 출력이 **손대지 않으면 같은 뜻으로** 돌아온다 — 형식 다섯 모두."""
    seen = set()
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        for node in read_process(path.read_text(encoding="utf-8")).all_nodes():
            spec = node.prop("dataOutput")
            if spec is None:
                continue
            made = loaded(spec.model_dump(exclude_unset=True))
            assert made.problems()[0] == [], f"{path.name}:{node.id}"
            assert DataOutput.model_validate(made.dump()) == spec, f"{path.name}:{node.id}"
            seen.add(spec.format)
    assert seen == FILE_FORMATS, "예제에 형식 다섯이 다 있다"


def test_unknown_keys_survive() -> None:
    out = loaded({**MD, "future": 1}).dump()
    assert out is not None and out["future"] == 1


def test_a_plain_data_object_opens_off_and_stays_off() -> None:
    made = loaded(None)
    assert not made.on_box.isChecked() and made.file_group.isHidden()
    assert made.dump() is None and made.problems() == ([], [])


def test_turning_it_on_asks_for_the_required_fields() -> None:
    made = loaded(None)
    made.on_box.setChecked(True)
    errors, _ = made.problems()
    assert errors[0] == "파일 경로를 적으세요."
    assert any("B5" in one and "경로 저장" in one for one in errors)
    assert any("템플릿이 비어 있습니다" in one for one in errors)


def test_choosing_one_content_drops_the_other() -> None:
    """엔진은 템플릿이 있으면 그것만 쓴다 — 둘이 다 적힌 그림은 말하고, 고른 쪽만 남긴다."""
    made = loaded({**MD, "variables": ["대상월"]})
    assert made.content() == CONTENT_TEMPLATE
    assert made.problems() == ([], [BOTH_WRITTEN])
    out = made.dump()
    assert out is not None and "variables" not in out
    made.content_picks[CONTENT_VARIABLES].setChecked(True)
    out = made.dump()
    assert out is not None and out["variables"] == ["대상월"] and "template" not in out


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({**MD, "store_as": None}, "B5"),
        ({**MD, "store_as": "1번"}, "「경로 저장」에 변수 이름으로 쓸 수 없는 것이 있습니다: 1번"),
        ({**MD, "path": ""}, "파일 경로를 적으세요."),
        ({**MD, "format": "pdf"}, "파일 형식을 모릅니다: pdf"),
        ({**MD, "format": "json", "append": True}, "json은 이어 쓸 수 없습니다"),
        ({**XLSX, "variables": ["a-b"]}, "변수 이름으로 쓸 수 없는 것이 있습니다: a-b"),
        ({"path": "a.csv", "format": "csv", "variables": ["가", "나"], "store_as": "f"}, "CSV에는 변수 하나만"),
        ({"path": "a.xlsx", "format": "xlsx", "template": "{가}", "store_as": "f"}, "엑셀에는 템플릿을 쓸 수 없습니다"),
    ],
)
def test_what_would_fail_blocks_apply(body: dict[str, Any], said: str) -> None:
    errors, _ = loaded({k: v for k, v in body.items() if v is not None}).problems()
    assert errors and said in errors[0], errors


def test_an_unknown_format_is_shown_not_dropped() -> None:
    made = loaded({**MD, "format": "pdf"})
    assert made.fmt() == "pdf"
    out = made.dump()
    assert out is not None and out["format"] == "pdf"


def test_a_sheet_with_many_variables_is_a_warning() -> None:
    made = loaded({**XLSX, "variables": ["가", "나"]})
    assert made.problems() == ([], [SHEET_UNUSED])


def test_append_is_written_only_when_on_or_already_there() -> None:
    made = loaded(MD)
    out = made.dump()
    assert out is not None and "append" not in out
    made.append_box.setChecked(True)
    out = made.dump()
    assert out is not None and out["append"] is True
    out = loaded({**MD, "append": False}).dump()
    assert out is not None and out["append"] is False


# ── 속성 패널 ──


def panel_with(chk: dict[str, Any]) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({
        "id": "Data_1", "type": "DataObjectReference", "name": "대사 결과",
        "chk": {name: json.dumps(body, ensure_ascii=False) for name, body in chk.items()},
    })
    return panel


def test_a_data_object_gets_the_tab_and_sends_nothing_untouched() -> None:
    panel = panel_with({"dataOutput": MD})
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ["폼", "파일 출력", "JSON"]
    assert panel.patch() == ({}, None)
    assert panel_with({}).patch() == ({}, None), "평범한 데이터 객체도 그대로"


def test_an_edit_writes_the_whole_body() -> None:
    panel = panel_with({"dataOutput": MD})
    panel._editor.path_box.setText("결과/다른.md")  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert json.loads(changes["chk"]["dataOutput"]) == {**MD, "path": "결과/다른.md"}


def test_turning_it_off_removes_the_element() -> None:
    panel = panel_with({"dataOutput": MD})
    panel._editor.on_box.setChecked(False)  # noqa: SLF001
    assert panel.patch() == ({"chk": {"dataOutput": None}}, None)


def test_a_blocking_problem_blocks_the_panel() -> None:
    panel = panel_with({"dataOutput": MD})
    panel._editor.store_box.setText("")  # noqa: SLF001
    changes, problem = panel.patch()
    assert changes == {} and problem is not None and "B5" in problem
    assert not panel.apply_button.isEnabled()


"""STU-04 게이트웨이 편집기 (`studio/gateway_editor.py`) — 화면 없이.

보는 것은 셋이다: 흐름이 **다 보이고** 기본 흐름이 골라져 있는가(업무 예제 전부 — 손대지 않으면 그대로),
**조건식이 있는 흐름은 기본이 될 수 없는가**, 그리고 속성 패널이 **표준 `default` 하나만** 보내는가
(조건식은 그 흐름의 「폼」 탭에서 고친다).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.studio.gateway_editor import (  # noqa: E402
    ALWAYS,
    HAS_CONDITION,
    PARALLEL_NOTE,
    GatewayEditor,
)

EXAMPLES = Path("docs/08-business-examples/bpmn")


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def flows(*specs: tuple[str, str]) -> list[dict[str, str]]:
    """`(id, 조건)` → 캔버스 `gateway.outgoing`의 줄."""
    return [{"id": id_, "name": f"{id_} 이름", "to": f"{id_} 대상", "condition": cond} for id_, cond in specs]


SPLIT = {
    "default": "F_else",
    "incoming": [{"id": "F_in", "from": "검토"}],
    "outgoing": flows(("F_big", "금액 > 100"), ("F_else", "")),
}


def loaded(found: dict[str, Any], kind: str = "ExclusiveGateway") -> GatewayEditor:
    made = GatewayEditor(kind=kind)
    made.load(found)
    return made


def test_the_flows_and_the_default_are_shown() -> None:
    made = loaded(SPLIT)
    assert made.incoming_label.text() == "1개 — 검토"
    assert made.table.rowCount() == 2
    cells = [[made.table.item(row, col) for col in (1, 2, 3)] for row in range(2)]
    texts = [[cell.text() if cell is not None else None for cell in row] for row in cells]
    assert texts == [["F_big 이름", "F_big 대상", "금액 > 100"], ["F_else 이름", "F_else 대상", ALWAYS]]
    assert made.chosen() == "F_else"
    assert made.dump() == {"default": "F_else"}
    assert made.problems() == ([], [])


def test_a_join_says_so() -> None:
    made = loaded({"incoming": [{"id": "a", "from": "A"}, {"id": "b", "from": "B"}], "outgoing": flows(("F", ""))})
    assert made.incoming_label.text() == "2개 — A, B (합류)"


def test_a_flow_with_a_condition_cannot_be_picked() -> None:
    made = loaded(SPLIT)
    pick = made._picks["F_big"]  # noqa: SLF001
    assert not pick.isEnabled() and pick.toolTip() == HAS_CONDITION
    assert made._picks["F_else"].isEnabled()  # noqa: SLF001


def test_a_default_with_a_condition_in_the_diagram_blocks_apply() -> None:
    made = loaded({**SPLIT, "default": "F_big"})
    errors, _ = made.problems()
    assert errors and "F_big 이름" in errors[0]


def test_choosing_none_leaves_a_bare_flow_and_b3_warns() -> None:
    made = loaded(SPLIT)
    made.none_pick.setChecked(True)
    assert made.dump() == {"default": ""}
    errors, warnings = made.problems()
    assert errors == [] and warnings and "F_else 이름" in warnings[0] and "B3" in warnings[0]


def test_a_single_outgoing_flow_needs_no_default() -> None:
    made = loaded({"outgoing": flows(("F", ""))})
    assert made.problems() == ([], [])


def test_a_parallel_gateway_has_no_default_and_ignores_conditions() -> None:
    made = loaded({"outgoing": flows(("A", ""), ("B", "x > 1"))}, kind="ParallelGateway")
    assert made.table.isColumnHidden(0) and made.none_pick.isHidden()
    assert not made.parallel_note.isHidden() and made.parallel_note.text() == PARALLEL_NOTE
    errors, warnings = made.problems()
    assert errors == [] and warnings and "B 이름" in warnings[0]
    assert made.dump() == {"default": ""}


def test_every_example_gateway_opens_without_problems() -> None:
    """예제 그림은 B3를 지나간다 — 손대지 않으면 막을 것도 경고할 것도 없고 기본 흐름이 그대로다."""
    from chaeksas.contracts.bpmn_ext import read_process  # noqa: PLC0415

    seen = 0
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        for scope_name, nodes, scope_flows in process.scopes():
            del scope_name
            for node in nodes:
                if not node.kind.endswith("Gateway"):
                    continue
                outgoing = process.outgoing(node.id, scope_flows)
                found = {
                    "default": next((f.id for f in outgoing if f.is_default), ""),
                    "incoming": [{"id": f.id, "from": f.source} for f in process.incoming(node.id, scope_flows)],
                    "outgoing": [
                        {"id": f.id, "name": "", "to": f.target, "condition": f.condition or ""} for f in outgoing
                    ],
                }
                kind = node.kind[0].upper() + node.kind[1:]
                made = loaded(found, kind=kind)
                assert made.problems() == ([], []), f"{path.name}:{node.id}"
                assert made.dump() == {"default": found["default"]}, f"{path.name}:{node.id}"
                seen += 1
    assert seen > 10


# ── 속성 패널 ──


def panel_with(bpmn_type: str, found: dict[str, Any]) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({"id": "Gw_1", "type": bpmn_type, "name": "금액?", "gateway": found, "chk": {}})
    return panel


@pytest.mark.parametrize("bpmn_type", ["ExclusiveGateway", "InclusiveGateway", "ParallelGateway"])
def test_gateways_get_the_tab_and_send_nothing_untouched(bpmn_type: str) -> None:
    panel = panel_with(bpmn_type, SPLIT)
    assert [panel.tabs.tabText(i) for i in range(panel.tabs.count())] == ["폼", "게이트웨이", "JSON"]
    assert panel.patch() == ({}, None)


def test_picking_another_default_sends_only_default() -> None:
    panel = panel_with("ExclusiveGateway", SPLIT)
    panel._editor.none_pick.setChecked(True)  # noqa: SLF001
    assert panel.patch() == ({"default": ""}, None)
    panel._editor._picks["F_else"].setChecked(True)  # noqa: SLF001
    assert panel.patch() == ({}, None)


def test_a_name_change_and_a_default_go_together() -> None:
    panel = panel_with("InclusiveGateway", {**SPLIT, "default": ""})
    panel.name_box.setText("금액 판단")
    panel._editor._picks["F_else"].setChecked(True)  # noqa: SLF001
    assert panel.patch() == ({"name": "금액 판단", "default": "F_else"}, None)

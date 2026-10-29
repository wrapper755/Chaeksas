"""STU-04 이벤트 편집기 (`studio/event_editor.py`) — 화면 없이.

보는 것은 넷이다: 그림에 적힌 것이 **다 보이는가**(업무 예제의 이벤트 전부 — 손대지 않으면 고칠 것이
없다), **엔진이 읽는 자리에만** 칸이 있는가, 엔진이 거부할 것을 **「적용」 전에 막는가**, 그리고 속성 패널이
**바뀐 칸만** 캔버스로 보내는가.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Receive  # noqa: E402
from chaeksas.studio.event_editor import (  # noqa: E402
    CATCH_UNDEFINED,
    CONDITIONAL,
    ERROR_CODES,
    MILESTONE,
    NOT_READ,
    PLAIN_START,
    SIGNAL_START,
    START_TIMER_NOTE,
    EventEditor,
)

EXAMPLES = Path("docs/08-business-examples/bpmn")


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def event(definition: str = "", **fields: Any) -> dict[str, Any]:
    """캔버스 `properties()`의 `event`와 같은 모양."""
    out: dict[str, Any] = {
        "definition": definition,
        "attachedTo": "",
        "cancelActivity": True,
        "timer": None,
        "message": "",
        "signal": "",
        "error": "",
    }
    out.update(fields)
    return out


def loaded(bpmn_type: str, found: dict[str, Any], receive: dict[str, Any] | None = None) -> EventEditor:
    made = EventEditor()
    made.load({"type": bpmn_type, "event": found, "receive": receive})
    return made


# ── 업무 예제 ──


def canvas_event(process: Any, node: Any) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """계약이 읽은 노드 → 캔버스가 줄 `event` (같은 것을 다른 눈으로 본다)."""
    bpmn_type = node.kind[0].upper() + node.kind[1:]
    definition = ""
    if node.event_definitions:
        definition = node.event_definitions[0][: -len("EventDefinition")]
        definition = definition[0].upper() + definition[1:]
    if bpmn_type == "ReceiveTask":
        definition = "Message"
    error = next((code for code, id_ in process.errors.items() if id_ == node.error_ref), "")
    found = event(
        definition,
        attachedTo=node.attached_to or "",
        cancelActivity=node.cancel_activity,
        timer={"kind": node.timer.kind, "value": node.timer.value} if node.timer else None,
        message=process.message_name(node.message_ref) or "",
        signal=process.signal_name(node.signal_ref) or "",
        error=error,
    )
    receive = node.prop("receive")
    return bpmn_type, found, receive.model_dump(exclude_unset=True) if receive is not None else None


def example_events() -> list[tuple[str, Any, Any]]:
    from chaeksas.contracts.bpmn_ext import read_process  # noqa: PLC0415

    out = []
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        for node in process.all_nodes():
            if node.kind.endswith("Event") or node.kind == "receiveTask":
                out.append((f"{path.name}:{node.id}", process, node))
    return out


def test_every_example_event_opens_without_problems_and_dumps_what_it_read() -> None:
    """예제 그림의 이벤트는 엔진이 도는 것이다 — 손대지 않았는데 「적용」을 막으면 편집기가 틀렸다."""
    sections: set[str] = set()
    for where, process, node in example_events():
        bpmn_type, found, receive = canvas_event(process, node)
        made = loaded(bpmn_type, found, receive)
        errors, _ = made.problems()
        assert errors == [], where
        out = made.dump()
        for key, value in out["event"].items():
            assert value == found[key], f"{where}: {key}"
        # 같은 **뜻**이면 된다 — 빈 `payload: []`는 적지 않은 것과 같다 (C14 모델로 본다).
        assert Receive.model_validate(out["receive"] or {}) == Receive.model_validate(receive or {}), where
        sections.add(made.section())
    assert {"Timer", "Message", "Signal", "Error"} <= sections, "예제에 넷이 다 있다"


# ── 타이머 ──


def test_a_boundary_timer_shows_its_duration_and_what_it_means() -> None:
    made = loaded("BoundaryEvent", event("Timer", attachedTo="결재", timer={"kind": "timeDuration", "value": "PT30M"}))
    assert made.section() == "Timer" and not made.timer_group.isHidden()
    assert made.timer_box.text() == "PT30M"
    assert made.timer_preview.text() == "30분 뒤"
    assert "붙은 노드: 결재" in made.what.text()
    assert made.problems() == ([], [])


@pytest.mark.parametrize(
    ("value", "said"),
    [("P3D", "3일 뒤"), ("PT2H", "2시간 뒤"), ("마감기한", "실행 때 변수 「마감기한」의 값")],
)
def test_the_preview_says_when(value: str, said: str) -> None:
    made = loaded("IntermediateCatchEvent", event("Timer", timer={"kind": "timeDuration", "value": value}))
    assert made.timer_preview.text().startswith(said)


@pytest.mark.parametrize(
    ("bpmn_type", "value", "said"),
    [
        ("BoundaryEvent", "", "타이머 값을 적으세요."),
        ("BoundaryEvent", "30분", "기한은 ISO 기간"),
        ("BoundaryEvent", "2026-11-01T09:00", "기한은 ISO 기간"),
        ("StartEvent", "매일 9시", "주기는 5필드 cron"),
    ],
)
def test_what_the_engine_cannot_read_blocks_apply(bpmn_type: str, value: str, said: str) -> None:
    kind = "timeCycle" if bpmn_type == "StartEvent" else "timeDuration"
    before = "PT1H" if kind == "timeDuration" else "0 9 * * *"
    made = loaded(bpmn_type, event("Timer", timer={"kind": kind, "value": before}))
    made.timer_box.setText(value)
    errors, _ = made.problems()
    assert errors and errors[0].startswith(said)


@pytest.mark.parametrize("value", ["0 9 * * 1-5", "R/2026-11-01T09:00:00/P1D", "R5/PT1H"])
def test_a_start_timer_takes_a_cycle_and_says_nobody_wakes_it_yet(value: str) -> None:
    made = loaded("StartEvent", event("Timer", timer={"kind": "timeCycle", "value": "0 9 * * *"}))
    made.timer_box.setText(value)
    assert made.problems() == ([], [])
    assert made.timer_preview.text() == START_TIMER_NOTE
    assert made.dump()["event"]["timer"] == {"kind": "timeCycle", "value": value}


def test_a_timer_kind_that_does_not_fit_the_place_is_kept_until_the_value_changes() -> None:
    """적어 둔 것을 조용히 바꾸지 않는다 — 경고하고, 값을 고치면 그 자리의 종류로 쓴다."""
    made = loaded("BoundaryEvent", event("Timer", timer={"kind": "timeDate", "value": "2026-11-01T09:00"}))
    errors, warnings = made.problems()
    assert errors == [] and any("timeDate" in one and "timeDuration" in one for one in warnings)
    assert made.dump()["event"]["timer"] == {"kind": "timeDate", "value": "2026-11-01T09:00"}
    made.timer_box.setText("P1D")
    assert made.dump()["event"]["timer"] == {"kind": "timeDuration", "value": "P1D"}


def test_a_new_timer_without_a_body_gets_the_kind_of_its_place() -> None:
    made = loaded("IntermediateCatchEvent", event("Timer"))
    made.timer_box.setText("PT10M")
    assert made.dump()["event"]["timer"] == {"kind": "timeDuration", "value": "PT10M"}


# ── 메시지·받기 ──


def test_a_message_catch_shows_its_name_and_receive_body() -> None:
    receive = {"correlation": "월", "payload": ["금액", "건수"]}
    made = loaded("IntermediateCatchEvent", event("Message", message="결산 완료"), receive)
    assert made.message_box.text() == "결산 완료"
    assert made.correlation_box.text() == "월" and made.payload_box.text() == "금액, 건수"
    assert not made.correlation_box.isHidden()
    assert made.problems() == ([], [])


def test_a_message_start_has_no_receive_fields() -> None:
    """메시지 시작은 작업이 된다 — `chk:receive`를 읽지 않으므로 칸이 없다."""
    made = loaded("StartEvent", event("Message", message="경비 요청"))
    assert made.correlation_box.isHidden() and made.payload_box.isHidden()
    assert made.dump() == {"event": {"message": "경비 요청"}, "receive": None}


def test_a_receive_task_is_the_message_section() -> None:
    made = loaded("ReceiveTask", event("Message", message="입금"), {"correlation": "주문번호"})
    assert made.section() == "Message" and not made.correlation_box.isHidden()
    made.payload_box.setText("금액")
    assert made.dump()["receive"] == {"correlation": "주문번호", "payload": ["금액"]}


def test_emptying_the_receive_fields_drops_the_body_but_keeps_unknown_keys() -> None:
    made = loaded("BoundaryEvent", event("Message", message="취소"), {"correlation": "주문번호"})
    made.correlation_box.setText("")
    assert made.dump()["receive"] is None
    made = loaded("BoundaryEvent", event("Message", message="취소"), {"correlation": "주문번호", "future": 1})
    made.correlation_box.setText("")
    assert made.dump()["receive"] == {"future": 1}


@pytest.mark.parametrize(
    ("box", "value", "said"),
    [
        ("message_box", "", "메시지 이름을 적으세요"),
        ("correlation_box", "주문-번호", "「상관 변수」는 변수 이름이어야 합니다"),
        ("payload_box", "금액, 1건", "「받을 값」에 변수 이름으로 쓸 수 없는 것이 있습니다: 1건"),
    ],
)
def test_message_problems_block_apply(box: str, value: str, said: str) -> None:
    made = loaded("IntermediateCatchEvent", event("Message", message="결산 완료"))
    getattr(made, box).setText(value)
    errors, _ = made.problems()
    assert errors and errors[0].startswith(said)


# ── 신호·오류·경계 ──


def test_a_signal_needs_a_name_and_a_signal_start_is_warned() -> None:
    made = loaded("IntermediateThrowEvent", event("Signal", signal="검토 끝"))
    assert made.problems() == ([], [])
    made.signal_box.setText("")
    assert made.problems()[0] == ["신호 이름을 적으세요."]
    assert loaded("StartEvent", event("Signal", signal="x")).problems()[1] == [SIGNAL_START]


def test_an_error_boundary_offers_the_standard_codes_and_blank_catches_all() -> None:
    made = loaded("BoundaryEvent", event("Error", attachedTo="신용 조회", error="TASK_FAILED"))
    offered = [made.error_box.itemText(i) for i in range(made.error_box.count())]
    assert offered == ["", *ERROR_CODES]
    assert made.interrupt_box.isHidden(), "오류 경계는 늘 중단이다"
    made.error_box.setCurrentText("")
    assert made.dump()["event"] == {"error": ""}
    assert made.problems() == ([], [])
    made.error_box.setCurrentText("MY_CODE")
    errors, warnings = made.problems()
    assert errors == [] and warnings and "MY_CODE" in warnings[0]


@pytest.mark.parametrize("definition", ["Timer", "Message", "Signal"])
def test_a_boundary_can_be_non_interrupting(definition: str) -> None:
    fields: dict[str, dict[str, Any]] = {
        "Timer": {"timer": {"kind": "timeDuration", "value": "P1D"}},
        "Message": {"message": "m"},
        "Signal": {"signal": "s"},
    }
    made = loaded("BoundaryEvent", event(definition, **fields[definition]))
    assert not made.interrupt_box.isHidden() and made.interrupt_box.isChecked()
    made.interrupt_box.setChecked(False)
    assert made.dump()["event"]["cancelActivity"] is False


# ── 칸이 없는 것 ──


@pytest.mark.parametrize(
    ("bpmn_type", "definition", "said"),
    [
        ("StartEvent", "", PLAIN_START),
        ("IntermediateThrowEvent", "", MILESTONE),
        ("IntermediateCatchEvent", "", CATCH_UNDEFINED),
        ("StartEvent", "Conditional", CONDITIONAL),
        ("EndEvent", "Error", NOT_READ),
        ("EndEvent", "Terminate", NOT_READ),
        ("EndEvent", "Message", NOT_READ),
        ("IntermediateThrowEvent", "Message", NOT_READ),
        ("StartEvent", "Error", NOT_READ),
    ],
)
def test_what_the_engine_does_not_read_has_no_fields(bpmn_type: str, definition: str, said: str) -> None:
    made = loaded(bpmn_type, event(definition))
    assert made.section() == ""
    assert made.what_note.text() == said
    for group in (made.timer_group, made.message_group, made.signal_group, made.error_group):
        assert group.isHidden()
    assert made.dump()["event"] == {}
    assert made.problems() == ([], [])


def test_a_plain_end_says_nothing() -> None:
    made = loaded("EndEvent", event(""))
    assert made.what_note.isHidden() and made.dump() == {"event": {}, "receive": None}


# ── 속성 패널 ──


def panel_with(bpmn_type: str, found: dict[str, Any], chk: dict[str, Any] | None = None) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({
        "id": "Event_1", "type": bpmn_type, "name": "기한",
        "event": found,
        "chk": {name: json.dumps(body, ensure_ascii=False) for name, body in (chk or {}).items()},
    })
    return panel


def tab_texts(panel: Any) -> list[str]:
    return [panel.tabs.tabText(i) for i in range(panel.tabs.count())]


@pytest.mark.parametrize(
    ("bpmn_type", "tab"),
    [
        ("StartEvent", "이벤트"),
        ("IntermediateCatchEvent", "이벤트"),
        ("IntermediateThrowEvent", "이벤트"),
        ("BoundaryEvent", "이벤트"),
        ("EndEvent", "이벤트"),
        ("ReceiveTask", "받기"),
    ],
)
def test_events_and_receive_tasks_get_the_tab(bpmn_type: str, tab: str) -> None:
    panel = panel_with(bpmn_type, event("Message", message="m"))
    assert tab_texts(panel) == ["폼", tab, "JSON"]
    assert panel.patch() == ({}, None), "손대지 않으면 보내지 않는다"


def test_only_changed_fields_go_to_the_canvas() -> None:
    panel = panel_with("BoundaryEvent", event("Timer", timer={"kind": "timeDuration", "value": "P1D"}))
    editor: Any = panel._editor  # noqa: SLF001
    editor.interrupt_box.setChecked(False)
    assert panel.patch() == ({"event": {"cancelActivity": False}}, None)
    editor.timer_box.setText("P2D")
    changes, problem = panel.patch()
    assert problem is None
    assert changes == {"event": {"cancelActivity": False, "timer": {"kind": "timeDuration", "value": "P2D"}}}


def test_a_receive_body_goes_as_chk_receive() -> None:
    panel = panel_with("ReceiveTask", event("Message", message="입금"))
    panel._editor.correlation_box.setText("주문번호")  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert set(changes) == {"chk"} and json.loads(changes["chk"]["receive"]) == {"correlation": "주문번호"}


def test_emptying_a_receive_body_removes_it() -> None:
    panel = panel_with("BoundaryEvent", event("Message", message="취소"), {"receive": {"correlation": "주문번호"}})
    panel._editor.correlation_box.setText("")  # noqa: SLF001
    assert panel.patch() == ({"chk": {"receive": None}}, None)


def test_a_blocking_event_problem_blocks_the_panel() -> None:
    panel = panel_with("IntermediateCatchEvent", event("Signal", signal="검토 끝"))
    panel._editor.signal_box.setText("")  # noqa: SLF001
    changes, problem = panel.patch()
    assert changes == {} and problem == "신호 이름을 적으세요."
    assert not panel.apply_button.isEnabled()

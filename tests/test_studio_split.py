"""STU-06a 「PC BPM 프로세스로 나누기」 (ADR-0071, `studio/split_actions.py`).

두 갈래다.

- **규칙** — 무엇을 옮기고 무엇을 적나. Qt 없이 돈다.
- **한 바퀴** — 진짜 캔버스(bpmn-js)로 나눈다. 창은 가짜고 캔버스만 진짜다. WebEngine이 못 뜨면
  건너뛴다 (`test_studio_canvas.py`와 같은 태도).

거듭 보는 것 넷.

1. **PC 쪽을 다 지은 뒤 서버 쪽을 바꾼다** — 서버 쪽은 캔버스에만 적용된다(디스크는 그대로).
2. **이름을 지어내지 않는다** — 미리 채우는 것은 세는 이름뿐이고 짝은 같은 이름이다.
3. **옮긴 노드의 확장 것만** 키 참조·고정을 가져간다.
4. 나눈 서버 그림은 **B6을 지나고**, 위임 호출은 PC BPM 프로세스가 선언한 출력과 맞는다 (B14).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from chaeksas.contracts.bpmn_ext import read_process, validate  # noqa: E402
from chaeksas.studio import split_actions  # noqa: E402
from chaeksas.studio.split_actions import Plan  # noqa: E402
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace  # noqa: E402

LOCATIONS = {"ui_task": ["pc"]}

SERVER = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpm="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="Proc_order" name="발주">
    <bpmn:extensionElements><bpm:process>{"run_location": "server",
      "service_keys": {"ui-automation": "erp-ui", "mail-app": "mail-key"},
      "extensions": [{"id": "ui-automation", "version": "&gt;=1"}, {"id": "other", "version": "1"}]}</bpm:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:scriptTask id="Task_Prepare" name="준비" scriptFormat="bpm-expr">
      <bpmn:script>확정 = [1, 2]</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:serviceTask id="Task_Erp" name="ERP 입력">
      <bpmn:extensionElements>
        <bpm:task type="ui_task" extension="ui-automation">{"page_id": "erp.po"}</bpm:task>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:userTask id="Task_Check" name="현장 확인">
      <bpmn:extensionElements><bpm:approval>{"title": "확인",
        "fields": [{"key": "승인", "label": "승인", "type": "bool"}],
        "location": "field"}</bpm:approval></bpmn:extensionElements>
    </bpmn:userTask>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Task_Prepare"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Prepare" targetRef="Task_Erp"/>
    <bpmn:sequenceFlow id="f3" sourceRef="Task_Erp" targetRef="Task_Check"/>
    <bpmn:sequenceFlow id="f4" sourceRef="Task_Check" targetRef="End_1"/>
  </bpmn:process>
</bpmn:definitions>
"""


def server() -> Any:
    return read_process(SERVER)


# ─────────────────────────── 규칙 ───────────────────────────


def test_blockers_are_what_b6_counts() -> None:
    found = split_actions.blockers(server(), LOCATIONS)
    assert [one.node_id for one in found] == ["Task_Erp", "Task_Check"]
    assert found[0].label.startswith("ERP 입력 (Task_Erp) — ")
    assert [one.node_id for one in split_actions.blockers(server())] == ["Task_Check"], (
        "실행 위치를 모르는 확장 태스크는 세지 않는다 — 검사와 같다"
    )


def test_only_counted_names_are_suggested() -> None:
    reads, made, known = split_actions.suggested(server(), "Task_Check")
    assert (reads, made, known) == ([], ["승인"], True)
    reads, made, known = split_actions.suggested(server(), "Task_Erp")
    assert known is False, "확장 태스크는 다 알지 못한다고 말한다"
    assert "*" not in reads + made


def test_a_plan_with_a_taken_id_or_clashing_names_is_refused() -> None:
    plan = Plan(node_id="Task_Erp", pc_id="order-pc", pc_name="발주 PC", inputs=[("a", "string"), ("a", "int")])
    assert any("겹칩니다" in one for one in split_actions.problems(plan, taken=lambda _: False))
    assert any("같은 id" in one for one in split_actions.problems(plan, taken=lambda _: True))
    bad = Plan(node_id="x", pc_id="Order PC", pc_name="", outputs=[""])
    found = split_actions.problems(bad, taken=lambda _: False)
    assert any("id는" in one for one in found) and any("빈" in one for one in found)


def test_the_call_pairs_names_with_themselves() -> None:
    plan = Plan(node_id="Task_Erp", pc_id="order-pc", pc_name="", inputs=[("발주", "list")], outputs=["번호"])
    body = json.loads(split_actions.call_body(plan))
    assert body == {"delegate": {"bpm_process_id": "order-pc"}, "input": {"발주": "발주"}, "output": {"번호": "번호"}}


def test_the_pc_bot_takes_only_the_moved_extensions_pin_and_no_keys() -> None:
    plan = Plan(node_id="Task_Erp", pc_id="order-pc", pc_name="", inputs=[("발주", "list")], outputs=["번호"])
    info = server().info
    body = json.loads(split_actions.pc_process(plan, info, "ui-automation"))
    assert body["run_location"] == "pc"
    assert "service_keys" not in body, "옛 키 참조는 옮기지 않는다 (ADR-0102)"
    assert [one["id"] for one in body["extensions"]] == ["ui-automation"]
    assert body["inputs"] == [{"name": "발주", "type": "list", "required": True}]
    assert body["outputs"] == ["번호"]
    plain = json.loads(split_actions.pc_process(plan, info, None))
    assert "service_keys" not in plain and "extensions" not in plain


# ─────────────────────────── 한 바퀴 (진짜 캔버스) ───────────────────────────


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    try:
        found = QApplication.instance() or QApplication([])
        from PySide6.QtWebEngineWidgets import QWebEngineView

        QWebEngineView()
    except Exception as e:  # noqa: BLE001 — 환경 문제면 건너뛴다
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    return found


@pytest.fixture
def canvas(app: Any) -> Any:
    from PySide6.QtCore import QEventLoop, QTimer

    from chaeksas.studio.canvas import Canvas

    found = Canvas()
    loop = QEventLoop()
    found.opened.connect(loop.quit)
    QTimer.singleShot(30_000, loop.quit)
    found.boot()
    loop.exec()
    if not found.live:
        pytest.skip("캔버스가 30초 안에 뜨지 않았다")
    return found


@dataclass
class Explorer:
    refreshed: list[str] = field(default_factory=list)

    added: list[str] = field(default_factory=list)

    def refresh(self, *, opened: str = "", adding: Any = ()) -> None:
        self.refreshed.append(opened)
        self.added.extend(adding)


@dataclass
class Window:
    """`split()`이 쓰는 **작은 길**만 가진 창 — 캔버스만 진짜다."""

    workspace: Workspace
    canvas: Any
    process: BpmProcess | None = None
    definition: Path | None = None
    dirty: bool = False
    explorer: Explorer = field(default_factory=Explorer)
    said: list[str] = field(default_factory=list)

    def say(self, message: str) -> None:
        self.said.append(message)

    def retitle(self) -> None:
        pass

    def saved_to_disk(self) -> bool:
        return True

    def opened_definition(self) -> Definition | None:
        assert self.process is not None
        return next(d for d in self.process.definitions if d.path == self.definition)


def drawn(canvas: Any) -> str:
    """`SERVER`와 같은 그림을 **캔버스로** 짓는다 — 현장 파일은 늘 그림 정보(DI)를 갖는다."""
    source = server()
    canvas.create_empty("Proc_order", "발주")
    canvas.append_chain(
        [
            {"bpmn": "bpmn:ScriptTask", "name": "준비", "chk": {},
             "attrs": {"scriptFormat": "bpm-expr", "script": "확정 = [1, 2]"}},
            {"bpmn": "bpmn:ServiceTask", "name": "ERP 입력",
             "chk": {"task": json.dumps({"type": "ui_task", "extension": "ui-automation",
                                         "data": {"page_id": "erp.po"}}, ensure_ascii=False)}},
            {"bpmn": "bpmn:UserTask", "name": "현장 확인",
             "chk": {"approval": source.node("Task_Check").prop("approval").model_dump_json(exclude_none=True)}},
            {"bpmn": "bpmn:EndEvent", "name": "끝"},
        ]
    )
    info = source.info.model_dump_json(exclude_none=True)
    canvas.call_sync("setProperties", "Proc_order", {"chk": {"process": info}})
    return str(canvas.save_xml())


def opened(tmp_path: Path, canvas: Any) -> Window:
    xml = drawn(canvas)
    workspace = Workspace(tmp_path / "작업").ensure()
    made = workspace.create("order", name="발주")
    path = workspace.save_definition(made, made.entry, xml)
    again = workspace.find("order")
    assert again is not None
    return Window(workspace=workspace, canvas=canvas, process=again, definition=path)


def node_named(process: Any, name: str) -> str:
    return str(next(n.id for n in process.all_nodes() if n.name == name))


def test_splitting_builds_the_pc_bot_then_delegates_in_place(tmp_path: Path, canvas: Any) -> None:
    window = opened(tmp_path, canvas)
    assert window.definition is not None
    disk = window.definition.read_text(encoding="utf-8")
    drawn_server = read_process(disk)
    erp, prepare, check = (node_named(drawn_server, n) for n in ("ERP 입력", "준비", "현장 확인"))
    plan = Plan(node_id=erp, pc_id="order-pc", pc_name="발주 PC", inputs=[("확정", "list")], outputs=["번호"])
    assert split_actions.split(window, plan) is True  # type: ignore[arg-type]
    assert window.explorer.added == ["order-pc"]  # STU-02 — 만든 PC BPM 프로세스도 목록에 올린다

    # PC 쪽 — 새 작업 폴더, 시작 → 옮긴 노드(본문 그대로) → 끝.
    pc = window.workspace.find("order-pc")
    assert pc is not None and pc.group == window.process.group  # type: ignore[union-attr]
    entry = pc.entry_definition
    assert entry is not None and entry.process is not None
    built = entry.process
    assert built.id == "Proc_order_pc"
    assert built.info.run_location == "pc" and built.info.outputs == ["번호"]
    assert "service_keys" not in (built.info.model_extra or {}), "옛 키 참조는 옮기지 않는다"
    moved = next(n for n in built.all_nodes() if n.kind == "serviceTask")
    task = moved.prop("task")
    assert task.type == "ui_task" and task.extension == "ui-automation" and task.data == {"page_id": "erp.po"}
    assert len(built.flows) == 2

    # 서버 쪽 — **캔버스에만** 바뀌었다 (디스크는 「저장」 전 그대로).
    assert window.dirty is True
    assert window.definition.read_text(encoding="utf-8") == disk
    after = read_process(canvas.save_xml())
    call = next(n for n in after.all_nodes() if n.kind == "callActivity")
    assert call.called_element == "Proc_order_pc"
    assert call.prop("call").delegate.bpm_process_id == "order-pc"
    assert sorted((f.source, f.target) for f in after.flows if call.id in (f.source, f.target)) == sorted(
        [(prepare, call.id), (call.id, check)]
    ), "흐름이 그대로다"
    assert "DELEGATION_FAILED" in window.said[-1], "경계·케이스는 지어 넣지 않고 말한다"

    found = validate(after, task_type_locations=LOCATIONS, delegated_outputs={"order-pc": ["번호"]})
    errors = [v for v in found if v.severity == "error"]
    blocked = [item for v in errors if v.rule == "B6" for item in v.items]
    assert not any(item.startswith(f"{erp}:") for item in blocked), "옮긴 노드는 더 B6에 걸리지 않는다"
    assert any("현장 결재" in item for item in blocked), "옮기지 않은 것은 그대로 걸린다 — 하나씩 나눈다"
    assert not [v for v in errors if v.rule == "B14"], "위임 출력이 PC BPM 프로세스가 선언한 것과 맞는다"


def test_a_taken_id_changes_nothing(tmp_path: Path, canvas: Any) -> None:
    window = opened(tmp_path, canvas)
    window.workspace.create("order-pc")
    before = read_process(canvas.save_xml())
    plan = Plan(node_id=node_named(before, "ERP 입력"), pc_id="order-pc", pc_name="")
    assert split_actions.split(window, plan) is False  # type: ignore[arg-type]
    assert "만들지 못했습니다" in window.said[-1]
    after = read_process(canvas.save_xml())
    assert sorted(n.id for n in after.all_nodes()) == sorted(n.id for n in before.all_nodes())


# ─────────────────────────── 창 (STU-06a) ───────────────────────────


def test_the_window_fills_counted_names_and_keeps_open_on_a_problem(app: Any) -> None:
    from chaeksas.studio.split_dialog import SplitDialog  # noqa: PLC0415

    process = server()
    window = SplitDialog(
        process,
        split_actions.blockers(process, LOCATIONS),
        server_id="order",
        server_name="발주",
        taken=lambda one: one == "order-pc",
    )
    assert window.id_box.text() == "order-pc" and window.name_box.text() == "발주 PC"
    assert window.hint.text() == split_actions.UNKNOWN_HINT, "확장 태스크는 다 알지 못한다고 말한다"
    window.accept()
    assert window.plan is None and "같은 id" in window.error.text(), "검사에 걸리면 창을 닫지 않는다"

    window.node_box.setCurrentIndex(1)  # 현장 확인 — 만드는 것을 플랫폼이 센다
    assert window.hint.text() == ""
    assert window.current().outputs == ["승인"]
    window.id_box.setText("order-check")
    window.accept()
    assert window.plan is not None and window.plan.node_id == "Task_Check"

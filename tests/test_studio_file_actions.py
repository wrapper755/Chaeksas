"""STU-01 파일 메뉴의 작은 동작들 — 화면 없이 도는 것만 (`studio/file_actions.py`).

창을 받아 쓰는 글루라, 여기서는 **창 대신 가짜 하나**를 넘긴다 (Qt도 캔버스도 띄우지 않는다).
그래서 보는 것은 **창이 옮기는 상태**다 — 기록이 바뀌었나, 탐색기를 다시 그렸나, 무엇을 말했나.
파일에 무엇이 쓰이는지는 `test_studio_workspace.py`가 본다 (규칙은 작업 폴더가 안다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QInputDialog, QMessageBox

from chaeksas.studio import file_actions
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace, read_record

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="{process_id}" name="{process_id}">
    <bpmn:extensionElements><chk:process>{{}}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


@dataclass
class FakeExplorer:
    refreshed: list[str] = field(default_factory=list)

    def refresh(self, *, opened: str = "") -> None:
        self.refreshed.append(opened)


@dataclass
class FakeWindow:
    """창이 공개하는 **작은 길**만 가진 가짜 (`main_window.py` 머리말)."""

    workspace: Workspace
    process: BpmProcess | None = None
    definition: Path | None = None
    explorer: FakeExplorer = field(default_factory=FakeExplorer)
    said: list[str] = field(default_factory=list)
    retitled: int = 0

    def say(self, message: str) -> None:
        self.said.append(message)

    def retitle(self) -> None:
        self.retitled += 1

    def opened_definition(self) -> Definition | None:
        if self.process is None or self.definition is None:
            return None
        return next((d for d in self.process.definitions if d.path == self.definition), None)


def opened(tmp_path: Path, *names: str, entry: str | None = None) -> FakeWindow:
    """정의 몇 개를 가진 BPM 프로세스를 만들고 **첫 정의를 연 창**을 돌려준다.

    `entry`를 주지 않으면 첫 정의가 진입이다. `""`는 **기록이 비어 있는** 쪽이다.
    """
    workspace = Workspace(tmp_path / "작업").ensure()
    made = workspace.create("a.b", name="한글 이름", entry=names[0] if entry is None else entry)
    for name in names:
        workspace.save_definition(made, name, MINIMAL.format(process_id=f"Proc_{Path(name).stem}"))
    again = workspace.find("a.b")
    assert again is not None
    return FakeWindow(workspace=workspace, process=again, definition=again.definitions[0].path)


def test_making_the_open_definition_the_entry_writes_the_record(tmp_path: Path) -> None:
    """「이 정의를 진입으로 지정」 — 기록만 바뀌고, 제목·탐색기가 다시 그려진다."""
    window = opened(tmp_path, "main.bpmn", "sub.bpmn", entry="main.bpmn")
    assert window.process is not None
    window.definition = window.process.definitions[1].path  # sub.bpmn을 열어 둔다

    # 창 대신 가짜를 넘긴다 (아래 모두 같다).
    file_actions.make_entry(window)  # type: ignore[arg-type]

    assert read_record(window.process.folder)["entry"] == "sub.bpmn"
    assert window.process.entry == "sub.bpmn", "창이 쥔 것도 함께 바뀐다"
    assert window.retitled == 1
    assert window.explorer.refreshed[-1].endswith("sub.bpmn")
    assert window.said[-1] == "진입 정의로 지정했습니다: sub.bpmn"


def test_making_the_entry_the_entry_again_changes_nothing(tmp_path: Path) -> None:
    """이미 진입이면 **할 일이 없다** — 기록을 다시 쓰지도, 제목을 다시 그리지도 않는다."""
    window = opened(tmp_path, "main.bpmn", "sub.bpmn", entry="main.bpmn")
    file_actions.make_entry(window)  # type: ignore[arg-type]
    assert window.said == ["이미 진입 정의입니다: main.bpmn"]
    assert window.retitled == 0


def test_the_first_definition_counts_as_the_entry_even_with_an_empty_record(tmp_path: Path) -> None:
    """기록이 비면 **첫 정의가 진입이다** (`entry_definition`) — 그 정의에는 할 일이 없다."""
    window = opened(tmp_path, "main.bpmn", "sub.bpmn", entry="")
    assert window.process is not None and window.process.entry == ""
    file_actions.make_entry(window)  # type: ignore[arg-type]
    assert window.said == ["이미 진입 정의입니다: main.bpmn"]

    # 둘째 정의는 진입이 아니라 지정할 수 있다 — 그때 기록에 **적힌다**.
    window.definition = window.process.definitions[1].path
    file_actions.make_entry(window)  # type: ignore[arg-type]
    assert read_record(window.process.folder)["entry"] == "sub.bpmn"


def test_nothing_open_says_so_instead_of_failing(tmp_path: Path) -> None:
    window = opened(tmp_path, "main.bpmn")
    window.process, window.definition = None, None
    file_actions.make_entry(window)  # type: ignore[arg-type]
    file_actions.add_definition(window)  # type: ignore[arg-type]
    file_actions.save_process_as(window)  # type: ignore[arg-type]
    assert window.said == [
        file_actions.NO_DEFINITION,
        file_actions.NO_PROCESS,
        file_actions.NO_PROCESS,
    ]


def test_the_name_rule_refuses_before_anything_is_written(tmp_path: Path, monkeypatch: Any) -> None:
    """「정의 추가...」는 이름을 먼저 본다 — **경로를 적으면 아무것도 만들지 않는다**."""
    window = opened(tmp_path, "main.bpmn")
    assert window.process is not None
    warned: list[str] = []
    monkeypatch.setattr(file_actions, "may_discard", lambda _window: True)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("../밖", True)))
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda _p, _t, text, *a, **k: warned.append(text))
    )

    file_actions.add_definition(window)  # type: ignore[arg-type]

    assert warned and "쓸 수 없다" in warned[0]
    assert [d.path.name for d in window.process.definitions] == ["main.bpmn"]
    assert not list((window.process.folder.parent).glob("**/밖*"))

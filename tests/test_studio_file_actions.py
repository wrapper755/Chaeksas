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
from chaeksas.studio.dialogs import NewProcessDialog
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
class FakeCanvas:
    """`load_xml`은 받은 답을 **그 자리에서** 돌려준다 (캔버스가 무엇을 했는지는 시험이 정한다)."""

    answer: dict[str, Any] = field(default_factory=lambda: {"ok": True, "warnings": []})
    cleared: int = 0

    def load_xml(self, _xml: str, *, then: Any = None) -> None:
        if then is not None:
            then(self.answer)

    def clear(self) -> None:
        self.cleared += 1


@dataclass
class FakeProperties:
    service_keys: dict[str, str] = field(default_factory=dict)
    run_location: str | None = None
    emptied: int = 0

    def show_nothing(self) -> None:
        self.emptied += 1


@dataclass
class FakeTable:
    rows: int = 3

    def setRowCount(self, rows: int) -> None:  # noqa: N802 — Qt 이름 그대로
        self.rows = rows


@dataclass
class FakeSettings:
    last_opened: str = ""
    saved: int = 0

    def save(self) -> None:
        self.saved += 1


@dataclass
class FakeWindow:
    """창이 공개하는 **작은 길**만 가진 가짜 (`main_window.py` 머리말)."""

    workspace: Workspace
    process: BpmProcess | None = None
    definition: Path | None = None
    explorer: FakeExplorer = field(default_factory=FakeExplorer)
    said: list[str] = field(default_factory=list)
    retitled: int = 0
    dirty: bool = False
    running: object | None = None
    canvas: FakeCanvas = field(default_factory=FakeCanvas)
    properties: FakeProperties = field(default_factory=FakeProperties)
    preflight: FakeTable = field(default_factory=FakeTable)
    settings: FakeSettings = field(default_factory=FakeSettings)

    def refresh_catalog(self) -> None:
        pass

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


# ─────────────────────────── 닫기 · 파일에서 가져오기 · 자동 배치 ───────────────────────────


def test_closing_empties_the_window_and_forgets_the_last_opened(tmp_path: Path) -> None:
    """「BPM 프로세스 닫기」 — **다음에 띄울 때도 열지 않는다**."""
    window = opened(tmp_path, "main.bpmn")
    window.settings.last_opened = str(window.definition)
    file_actions.close_process(window)  # type: ignore[arg-type]
    assert (window.process, window.definition, window.dirty) == (None, None, False)
    assert window.canvas.cleared == 1 and window.properties.emptied == 1
    assert window.preflight.rows == 0 and window.retitled == 1
    assert (window.settings.last_opened, window.settings.saved) == ("", 1)
    assert window.said[-1] == "닫았습니다: 한글 이름"


def test_closing_during_a_test_run_is_refused(tmp_path: Path) -> None:
    window = opened(tmp_path, "main.bpmn")
    window.running = object()
    file_actions.close_process(window)  # type: ignore[arg-type]
    assert window.process is not None and window.canvas.cleared == 0
    assert window.said == [file_actions.CLOSE_WHILE_RUNNING]


def test_closing_with_nothing_open_says_so(tmp_path: Path) -> None:
    window = opened(tmp_path, "main.bpmn")
    window.process, window.definition = None, None
    file_actions.close_process(window)  # type: ignore[arg-type]
    assert window.said == [file_actions.NO_PROCESS] and window.canvas.cleared == 0


def test_closing_keeps_unsaved_edits_when_asked_to_cancel(tmp_path: Path, monkeypatch: Any) -> None:
    window = opened(tmp_path, "main.bpmn")
    window.dirty = True
    monkeypatch.setattr(file_actions, "may_discard", lambda _window: False)
    file_actions.close_process(window)  # type: ignore[arg-type]
    assert window.process is not None and window.canvas.cleared == 0


def test_a_laid_out_definition_opens_as_unsaved(tmp_path: Path) -> None:
    """캔버스가 배치했으면(ADR-0088) 디스크와 다르다 — 「저장 안 한 변경」이고 그렇게 말한다."""
    window = opened(tmp_path, "main.bpmn")
    window.canvas.answer = {"ok": True, "warnings": [], "laid_out": True}
    assert window.definition is not None
    file_actions.open_definition(window, window.definition.as_posix())  # type: ignore[arg-type]
    assert window.dirty is True
    assert window.said[-1] == file_actions.LAID_OUT


def test_a_definition_with_di_opens_as_saved(tmp_path: Path) -> None:
    window = opened(tmp_path, "main.bpmn")
    assert window.definition is not None
    file_actions.open_definition(window, window.definition.as_posix())  # type: ignore[arg-type]
    assert window.dirty is False and file_actions.LAID_OUT not in window.said


def test_importing_a_file_makes_a_process_and_opens_it(tmp_path: Path, monkeypatch: Any) -> None:
    """「파일에서 BPM 프로세스 가져오기...」 — 파일 → STU-05 → 연다."""
    window = opened(tmp_path, "main.bpmn")
    source = tmp_path / "바깥.bpmn"
    source.write_text(MINIMAL.format(process_id="Proc_out"), encoding="utf-8")
    seen: dict[str, Any] = {}

    def ask(_parent: Any, workspace: Workspace, **kwargs: Any) -> BpmProcess:
        seen.update(kwargs)
        return workspace.create("c.d", first=kwargs["imported"])

    monkeypatch.setattr(file_actions, "pick_bpmn_file", lambda _window: source)
    monkeypatch.setattr(NewProcessDialog, "ask", staticmethod(ask))
    opened_paths: list[str] = []
    monkeypatch.setattr(file_actions, "open_definition", lambda _w, path: opened_paths.append(path))

    file_actions.import_file(window)  # type: ignore[arg-type]

    assert seen == {"imported": source}
    assert opened_paths and opened_paths[0].endswith("c.d/process/바깥.bpmn")
    assert window.said[-1] == "가져왔습니다: Proc_out — 바깥.bpmn"


def test_importing_stops_when_no_file_is_picked(tmp_path: Path, monkeypatch: Any) -> None:
    window = opened(tmp_path, "main.bpmn")
    monkeypatch.setattr(file_actions, "pick_bpmn_file", lambda _window: None)
    file_actions.import_file(window)  # type: ignore[arg-type]
    assert window.said == [] and window.workspace.find("c.d") is None

"""STU-05 새 BPM 프로세스의 「첫 정의」·설명·담당자 (`studio/dialogs.py`·`workspace.create`).

**파일에 무엇이 쓰이는지는 작업 폴더가 정한다** — 그래서 규칙은 `Workspace.create(first=…)`로
보고, 창은 **고른 것을 그쪽으로 옮기는가**만 본다 (Qt는 offscreen, 대화상자를 띄우지 않는다).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from chaeksas.studio.dialogs import NewProcessDialog  # noqa: E402
from chaeksas.studio.workspace import Workspace, WorkspaceError, read_record  # noqa: E402

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="Proc_청구" name="청구서 대사">
    <bpmn:extensionElements><chk:process>{}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


@pytest.fixture
def space(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "작업").ensure()


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    found = tmp_path / "바깥" / "청구.bpmn"
    found.parent.mkdir()
    found.write_text(MINIMAL, encoding="utf-8")
    return found


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# ─────────────────────────── 작업 폴더 (Qt 없음) ───────────────────────────


def test_a_file_becomes_the_entry_definition_unchanged(space: Workspace, outside: Path) -> None:
    made = space.create("finance.claims", first=outside)
    entry = made.entry_definition
    assert entry is not None and entry.path.name == "청구.bpmn"
    assert entry.path.read_text(encoding="utf-8") == MINIMAL  # 그림은 손대지 않는다 (ADR-0022)
    assert read_record(made.folder)["entry"] == "청구.bpmn"
    assert outside.read_text(encoding="utf-8") == MINIMAL  # 원본은 읽기만 한다


def test_an_empty_name_takes_the_drawing_name(space: Workspace, outside: Path) -> None:
    assert space.create("finance.claims", first=outside).display == "청구서 대사"
    assert space.create("finance.claims2", name="내 이름", first=outside).display == "내 이름"


def test_an_unreadable_file_leaves_nothing_behind(space: Workspace, tmp_path: Path) -> None:
    """폴더를 먼저 만들고 실패하면 반쯤 만든 BPM 프로세스가 탐색기에 남는다."""
    broken = tmp_path / "깨짐.bpmn"
    broken.write_text("<not-bpmn/>", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="BPMN으로 읽지 못했다"):
        space.create("finance.claims", first=broken)
    assert space.find("finance.claims") is None
    assert not any(space.root.rglob("finance.claims"))


@pytest.mark.parametrize("name", ["청구.xml", "없는.bpmn"])
def test_only_an_existing_bpmn_file_is_taken(space: Workspace, tmp_path: Path, name: str) -> None:
    with pytest.raises(WorkspaceError):
        space.create("finance.claims", first=tmp_path / name)
    assert space.find("finance.claims") is None


def test_description_and_owner_go_to_the_record(space: Workspace) -> None:
    made = space.create("finance.claims", description="월말 대사", owner="재무팀")
    record = read_record(made.folder)
    assert (record["description"], record["owner"]) == ("월말 대사", "재무팀")


# ─────────────────────────── 창 ───────────────────────────


def fill(dialog: NewProcessDialog, process_id: str = "finance.claims") -> None:
    dialog.id_box.setText(process_id)
    dialog.name_box.setText("")


def test_blank_is_the_default_and_makes_no_definition(space: Workspace) -> None:
    dialog = NewProcessDialog(None, space)
    fill(dialog)
    dialog.description_box.setPlainText("  월말 대사  ")
    dialog.owner_box.setText("재무팀")
    dialog.accept()
    assert dialog.made is not None
    assert dialog.made.definitions == []  # 빈 정의는 캔버스가 저장할 때 생긴다
    assert read_record(dialog.made.folder)["description"] == "월말 대사"


def test_the_new_dialog_offers_no_file_import(space: Workspace) -> None:
    """파일에서 가져오기는 **따로 메뉴다** — 이 창의 「첫 정의」는 둘뿐이다."""
    dialog = NewProcessDialog(None, space)
    assert [b.text() for b in dialog.picks.buttons()][0] == "빈 정의로 시작"
    assert len(dialog.picks.buttons()) == 2


def test_importing_shows_the_file_and_fills_from_the_drawing(space: Workspace, outside: Path) -> None:
    dialog = NewProcessDialog(None, space, imported=outside)
    assert dialog.windowTitle() == "파일에서 BPM 프로세스 가져오기"
    assert not hasattr(dialog, "picks"), "「첫 정의」 대신 「가져올 파일」이다"
    assert dialog.name_box.text() == "청구서 대사"
    assert dialog.id_box.text() == "", "그림 id `Proc_청구`는 C1 규칙에 맞지 않아 채우지 않는다"
    dialog.id_box.setText("finance.claims")
    dialog.accept()
    assert dialog.made is not None and dialog.made.entry == "청구.bpmn"


def test_a_drawing_id_that_fits_c1_is_offered(space: Workspace, tmp_path: Path) -> None:
    found = tmp_path / "sc01.bpmn"
    found.write_text(MINIMAL.replace('id="Proc_청구"', 'id="nowview.sc01"'), encoding="utf-8")
    assert NewProcessDialog(None, space, imported=found).id_box.text() == "nowview.sc01"
    space.create("nowview.sc01")
    assert NewProcessDialog(None, space, imported=found).id_box.text() == "", "이미 있으면 비운다"


def test_an_unreadable_import_keeps_the_dialog_open(
    space: Workspace, tmp_path: Path, monkeypatch: Any
) -> None:
    broken = tmp_path / "깨짐.bpmn"
    broken.write_text("<not-bpmn/>", encoding="utf-8")
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda _p, _t, text: warned.append(text)))
    dialog = NewProcessDialog(None, space, imported=broken)
    fill(dialog)
    dialog.accept()
    assert dialog.made is None and warned and "BPMN으로 읽지 못했다" in warned[0]
    assert space.find("finance.claims") is None


def test_copying_the_open_definition_is_off_without_one(space: Workspace, outside: Path) -> None:
    assert not NewProcessDialog(None, space).opened_pick.isEnabled()
    dialog = NewProcessDialog(None, space, opened=outside)
    assert dialog.opened_pick.isEnabled() and "청구.bpmn" in dialog.opened_pick.text()
    fill(dialog)
    dialog.opened_pick.setChecked(True)
    dialog.accept()
    assert dialog.made is not None and dialog.made.entry == "청구.bpmn"


def test_save_as_has_no_first_definition(space: Workspace, outside: Path) -> None:
    """「다른 이름으로 저장」은 한 벌을 통째로 옮긴다 — 「첫 정의」를 고를 거리가 없다."""
    source = space.create("finance.claims", first=outside)
    dialog = NewProcessDialog(None, space, source=source)
    assert not hasattr(dialog, "picks")
    fill(dialog, "finance.claims-copy")
    dialog.accept()
    assert dialog.made is not None and dialog.made.entry == "청구.bpmn"

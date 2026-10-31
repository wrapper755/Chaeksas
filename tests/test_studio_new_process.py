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
                  xmlns:bpm="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="Proc_청구" name="청구서 대사">
    <bpmn:extensionElements><bpm:process>{}</bpm:process></bpmn:extensionElements>
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
    """파일에서 가져오기는 **따로 메뉴다** — 이 창의 「첫 정의」는 빈 정의·열린 정의·예제 셋이다."""
    dialog = NewProcessDialog(None, space)
    texts = [b.text() for b in dialog.picks.buttons()]
    assert texts[0] == "빈 정의로 시작" and len(texts) == 3
    assert not any("파일" in t for t in texts)


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
    assert NewProcessDialog(None, space, imported=found).id_box.text() == "nowview.sc01", (
        "이미 있어도 채운다 — 「기존 것을 바꾸기」의 입구다"
    )


def _answer_replace(monkeypatch: Any, choice: str) -> list[str]:
    """「기존 것을 바꾸기」 확인 창에 `choice` 단추로 답한다. 본 글을 돌려준다."""
    seen: list[str] = []

    def exec_(box: QMessageBox) -> int:
        seen.append(f"{box.text()}\n{box.informativeText()}")
        assert box.defaultButton().text() == "취소", "덮어쓰기는 되돌릴 수 없다 — 기본은 취소"
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(
        QMessageBox, "clickedButton", lambda box: next(b for b in box.buttons() if b.text() == choice)
    )
    return seen


def test_importing_an_existing_id_replaces_only_the_entry(
    space: Workspace, tmp_path: Path, monkeypatch: Any
) -> None:
    old = space.create("nowview.sc01", name="SC01", version="0.3.0", first=_drawing(tmp_path, "옛"))
    cases = old.folder / "cases" / "sc01.cases.json"
    cases.write_text("{}", encoding="utf-8")
    newer = _drawing(tmp_path / "new", "새")
    seen = _answer_replace(monkeypatch, "기존 것을 바꾸기")
    dialog = NewProcessDialog(None, space, imported=newer)
    dialog.name_box.setText("창에 적은 이름")
    dialog.accept()
    assert seen and "nowview.sc01" in seen[0] and "sc01.bpmn" in seen[0]
    assert dialog.replaced and dialog.made is not None
    assert (old.folder / "process" / "sc01.bpmn").read_text(encoding="utf-8") == newer.read_text(
        encoding="utf-8"
    )
    again = space.find("nowview.sc01")
    assert again is not None and (again.name, again.version) == ("SC01", "0.3.0"), "기록은 그대로"
    assert cases.read_text(encoding="utf-8") == "{}", "시험 케이스는 그대로"


def test_cancelling_the_replace_changes_nothing(
    space: Workspace, tmp_path: Path, monkeypatch: Any
) -> None:
    old = space.create("nowview.sc01", first=_drawing(tmp_path, "옛"))
    before = (old.folder / "process" / "sc01.bpmn").read_text(encoding="utf-8")
    _answer_replace(monkeypatch, "취소")
    dialog = NewProcessDialog(None, space, imported=_drawing(tmp_path / "new", "새"))
    dialog.accept()
    assert dialog.made is None and not dialog.replaced
    assert (old.folder / "process" / "sc01.bpmn").read_text(encoding="utf-8") == before


def _drawing(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    found = folder / "sc01.bpmn"
    found.write_text(
        MINIMAL.replace('id="Proc_청구"', 'id="nowview.sc01"').replace("청구서 대사", name),
        encoding="utf-8",
    )
    return found


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


# ─────────────────────────── 「예제에서 가져오기」 ───────────────────────────

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


def test_the_id_rule_is_a_tooltip_not_a_line() -> None:
    from PySide6.QtWidgets import QLabel  # noqa: PLC0415

    from chaeksas.studio.dialogs import HINT  # noqa: PLC0415

    dialog = NewProcessDialog(None, Workspace(Path("unused")), examples=EXAMPLES)
    assert dialog.id_box.toolTip() == HINT
    assert all(label.text() != HINT for label in dialog.findChildren(QLabel)), "창 아래 줄은 없다"


def test_an_example_is_the_third_first_definition(space: Workspace) -> None:
    dialog = NewProcessDialog(None, space, examples=EXAMPLES)
    assert not dialog.example_list.isEnabled(), "고르기 전에는 목록이 꺼져 있다"
    dialog.example_list.setCurrentIndex(dialog.example_list.findData("fx02_business_rule"))
    dialog.example_pick.setChecked(True)
    assert dialog.example_list.isEnabled()
    assert dialog.id_box.text() == "fx02-business-rule" and dialog.name_box.text()
    dialog.version_box.setText("0.2.0")
    dialog.owner_box.setText("김설계")
    dialog.accept()
    made = dialog.made
    assert made is not None and made.id == "fx02-business-rule" and made.version == "0.2.0"
    assert made.owner == "김설계"
    assert made.entry_definition is not None and made.entry_definition.path.is_file()
    assert list(made.folder.glob("process/*.dmn")), "쓰는 DMN도 함께 온다"


def test_picking_another_example_keeps_what_the_person_typed(space: Workspace) -> None:
    dialog = NewProcessDialog(None, space, examples=EXAMPLES)
    dialog.example_pick.setChecked(True)
    dialog.id_box.setText("my.own")
    first_name = dialog.name_box.text()
    dialog.example_list.setCurrentIndex((dialog.example_list.currentIndex() + 1) % dialog.example_list.count())
    assert dialog.id_box.text() == "my.own", "고쳐 적은 칸은 덮지 않는다"
    assert dialog.name_box.text() != first_name, "채워 둔 칸은 새 예제를 따른다"


def test_no_examples_turns_the_line_off(space: Workspace, tmp_path: Path) -> None:
    from chaeksas.studio.dialogs import NO_EXAMPLES  # noqa: PLC0415

    dialog = NewProcessDialog(None, space, examples=tmp_path / "없음")
    assert not dialog.example_pick.isEnabled() and NO_EXAMPLES in dialog.example_pick.text()
    assert dialog.blank_pick.isChecked()

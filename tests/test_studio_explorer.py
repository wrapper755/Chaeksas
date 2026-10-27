"""STU-02 탐색기 — 목록은 **연 BPM 프로세스**다 (`studio/explorer.py`).

열면 올라가고 닫으면 빠진다. 작업 폴더의 파일은 그대로다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from chaeksas.studio.explorer import Explorer
from chaeksas.studio.settings import Settings
from chaeksas.studio.workspace import Workspace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs">
  <bpmn:process id="{process_id}"><bpmn:startEvent id="Start_1"/></bpmn:process>
</bpmn:definitions>
"""


@pytest.fixture(scope="module")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def workspace(tmp_path: Path) -> Workspace:
    found = Workspace(tmp_path / "작업").ensure()
    found.create_group("영업")
    for process_id, name, group in (("one", "하나", "기본"), ("two", "둘", "영업")):
        made = found.create(process_id, name=name, group=group)
        found.save_definition(made, "main.bpmn", MINIMAL.format(process_id=f"Proc_{process_id}"))
    return found


def shown(explorer: Explorer) -> list[str]:
    """그려진 줄 — 그룹과 BPM 프로세스 (정의 줄은 뺀다)."""
    model = explorer.model()
    found: list[str] = []
    for row in range(model.rowCount()):
        group = model.index(row, 0)
        found.append(str(model.data(group)))
        found.extend(str(model.data(model.index(i, 0, group))) for i in range(model.rowCount(group)))
    return found


def test_the_list_starts_empty_and_keeps_the_default_group(app: Any, tmp_path: Path) -> None:
    explorer = Explorer(workspace(tmp_path))
    assert explorer.listed == [] and shown(explorer) == ["기본"]


def test_opening_lists_the_process_and_closing_takes_it_off(app: Any, tmp_path: Path) -> None:
    space = workspace(tmp_path)
    explorer = Explorer(space)
    two = space.find("two")
    assert two is not None and two.entry_definition is not None
    explorer.refresh(opened=two.entry_definition.path.as_posix())
    assert explorer.listed == ["two"] and shown(explorer) == ["기본", "영업", "둘"]
    explorer.refresh(adding=("one",))
    assert explorer.listed == ["two", "one"] and shown(explorer) == ["기본", "하나", "영업", "둘"]
    explorer.unlist("two")
    assert explorer.listed == ["one"] and shown(explorer) == ["기본", "하나"]
    assert space.find("two") is not None  # 파일은 그대로다


def test_the_list_drops_what_left_the_work_folder(app: Any, tmp_path: Path) -> None:
    explorer = Explorer(workspace(tmp_path), listed=["one", "gone", "one"])
    assert explorer.listed == ["one"] and shown(explorer) == ["기본", "하나"]


def test_the_list_survives_a_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, open_processes=("two", "one"))
    settings.save()
    assert Settings.load(settings.path).open_processes == ("two", "one")

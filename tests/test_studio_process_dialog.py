"""STU-06 BPM 프로세스 정보 (M6 조각 22).

보는 것:

1. **고치는 것이 두 곳에 산다** — 기록(`process.json`)은 창이 쓰고, 그림(`chk:process`)은
   **캔버스가** 쓴다. 진입 정의가 열려 있지 않으면 그 두 칸은 끄고 까닭을 적는다 (U3).
2. **읽은 것을 통째로 되돌려 쓴다** — `extensions`·`inputs`·`outputs`를 빼면 그 선언이 사라진다.
3. **「서버로 바꾸면 무엇이 걸리나」는 검사와 같은 함수로 센다** (`contracts.server_blockers`) —
   어긋나면 「검사는 통과했는데 창이 막는다」가 된다. **저장은 막지 않는다.**
4. **「서비스 앱 키」 섹션은 없다** (ADR-0094) — 키는 Center가 내려 주고, 그림에 적힌 참조는
   **그대로** 간다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import fake_extension
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import read_process, server_blockers  # noqa: E402
from chaeksas.contracts.bpmn_ext import validate as validate_bpmn  # noqa: E402
from chaeksas.studio import process_dialog as module  # noqa: E402
from chaeksas.studio.packaging import build_manifest  # noqa: E402
from chaeksas.studio.process_dialog import (  # noqa: E402
    ProcessInfoDialog,
    check,
    learning,
    server_warning,
)
from chaeksas.studio.workspace import BpmProcess, Workspace, read_record  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

#: 서비스 앱을 키 참조로 부르는 예제 (`ext-credit` / `finance-credit`).
CREDIT = "bx06_bulk_credit_check"
#: **현장 확인**이 있어 서버에서 돌 수 없는 예제 — 플랫폼이 혼자 아는 것들이다.
PC_EXAMPLE = "fx19_manual_task_pc"
#: **확장 태스크**가 있는 그림 (시험용 확장, `tests/fake_extension.py`). 실행 위치는 플랫폼이
#: 모르고 **확장 정의만** 안다 (C13·ADR-0018) — 부르는 쪽이 넘긴 표로 센다.
EXTENSION_EXAMPLE = fake_extension.DRAWING
#: 그 표 (`ExtensionHost.task_type_locations()`가 주는 모양). 이 태스크는 PC에서만 돈다.
UI_TASK_ON_PC = {"fake_task": ["pc"]}


@pytest.fixture
def space(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "작업").ensure()


def imported(space: Workspace, example: str = CREDIT) -> BpmProcess:
    if example == EXTENSION_EXAMPLE:
        return space.import_example(fake_extension.drawing(space.root.parent / "src"), example)
    return space.import_example(EXAMPLES, example)


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# ─────────────────────────── 담는 것 (Qt 없음) ───────────────────────────


def test_learning_says_nothing_when_there_is_no_memory(space: Workspace) -> None:
    """**빈 상자를 말없이 두지 않는다** — 없으면 어떻게 생기는지 말한다 (ADR-0028)."""
    assert learning(imported(space)) == module.NO_MEMORY


def test_the_server_warning_counts_and_stays_quiet_when_clean() -> None:
    assert server_warning([]) == ""
    found = server_warning(["Task_a: 현장 결재", "Task_b: AI 태스크 domain=web"])
    assert "2개" in found and "실행 전 검사" in found


def test_the_window_and_the_check_count_the_same_things(space: Workspace) -> None:
    """**검사와 같은 함수**다 (`server_blockers`) — 어긋나면 한쪽이 거짓말을 한다."""
    process = imported(space, PC_EXAMPLE)
    entry = process.entry_definition
    assert entry is not None and entry.process is not None
    blockers = server_blockers(entry.process)
    assert blockers, "현장 확인이 있는 예제라 서버에서 걸린다"

    # B6은 `run_location`이 server일 때만 말한다 — 같은 목록을 쓴다.
    xml = entry.path.read_text(encoding="utf-8")
    as_server = read_process(xml.replace('"pc"', '"server"'))
    found = [v for v in validate_bpmn(as_server) if v.rule == "B6"]
    assert found and sorted(found[0].items) == sorted(blockers)


def test_the_window_counts_extension_tasks_from_the_table_it_is_given(space: Workspace) -> None:
    """확장 태스크도 센다 — **표를 받아서** (C13 `task_types[].run_locations`, ADR-0018).

    표를 주지 않으면 세지 않는다. 「모른다」와 「서버에서 안 된다」를 가르는 자리다 — 확장을
    깔지 않은(꺼 둔) PC에서 올바른 그림을 막으면 안 된다.
    """
    process = imported(space, EXTENSION_EXAMPLE)
    assert dialog(space, process).blockers() == [], "표가 없으면 확장 태스크를 모른다"

    found = dialog(space, process, task_type_locations=UI_TASK_ON_PC).blockers()
    assert found, "확장 태스크가 있는데 세지 못했다"
    assert all("fake_task" in one for one in found)

    allowed = dialog(space, process, task_type_locations={"fake_task": ["pc", "server"]}).blockers()
    assert allowed == [], "확장이 server를 선언했으면 걸리지 않는다"


def test_the_window_and_b6_use_the_same_table_for_extension_tasks(space: Workspace) -> None:
    """**셋이 같은 표를 쓴다** — 창·F6·매니페스트. 어긋나면 한쪽이 거짓말을 한다."""
    process = imported(space, EXTENSION_EXAMPLE)
    entry = process.entry_definition
    assert entry is not None and entry.process is not None
    blockers = dialog(space, process, task_type_locations=UI_TASK_ON_PC).blockers()

    xml = entry.path.read_text(encoding="utf-8")
    as_server = read_process(xml.replace('"run_location": "pc"', '"run_location": "server"'))
    found = [
        v
        for v in validate_bpmn(as_server, task_type_locations=UI_TASK_ON_PC)
        if v.rule == "B6"
    ]
    assert found and sorted(found[0].items) == sorted(blockers)


def test_the_check_says_the_first_problem_only() -> None:
    assert check(name="이름", version="1.0.0", taken=[]) == ""
    assert "이름을 적으세요" in check(name="  ", version="1.0.0", taken=[])
    assert "같은 이름" in check(name="겹침", version="1.0.0", taken=["겹침"])
    assert "버전은" in check(name="이름", version="1.0", taken=[])


# ─────────────────────────── 창 ───────────────────────────


def dialog(
    space: Workspace,
    process: BpmProcess,
    *,
    editable: bool = True,
    task_type_locations: dict[str, list[str]] | None = None,
) -> ProcessInfoDialog:
    return ProcessInfoDialog(
        process,
        space,
        editable=editable,
        task_type_locations=task_type_locations,
    )


def test_the_record_fields_save_to_the_workspace(space: Workspace) -> None:
    """기록은 창이 쓴다 — `process.json`은 **Studio 안에서만 쓰는 기록**이라 계약이 아니다."""
    process = imported(space)
    window = dialog(space, process)
    window.name_box.setText("대량 신용 조회")
    window.version_box.setText("2.1.0")
    window.description_box.setPlainText("월말에 거래처 신용을 모아 조회한다.")
    window.owner_box.setText("재무팀 김")
    window.tags_box.setText(" 재무 , 월말 ,, ")
    window.save()

    assert window.saved is not None
    assert window.saved.tags == ("재무", "월말"), "빈 조각은 버린다"
    found = read_record(process.folder)
    assert found["name"] == "대량 신용 조회" and found["version"] == "2.1.0"
    assert found["owner"] == "재무팀 김"
    assert found["tags"] == ["재무", "월말"]


def test_an_empty_field_is_not_written(space: Workspace) -> None:
    """**「아직 안 적었다」와 「비웠다」를 가르지 않는다** — 빈 값은 기록에 넣지 않는다."""
    window = dialog(space, imported(space))
    window.save()
    found = read_record(window.saved.folder)  # type: ignore[union-attr]
    assert "description" not in found and "owner" not in found and "tags" not in found


def test_the_description_goes_into_the_package(space: Workspace) -> None:
    """설명만 패키지로 간다 (C1 `description`) — 담당자·태그는 매니페스트에 칸이 없다."""
    process = imported(space)
    window = dialog(space, process)
    window.description_box.setPlainText("월말 신용 조회")
    window.save()
    assert window.saved is not None
    assert build_manifest(window.saved).description == "월말 신용 조회"
    # 비우면 **넣지 않는다** — 빈 글을 적으면 콘솔이 「설명이 있다」로 읽는다.
    assert build_manifest(process).description is None


def test_a_bad_value_keeps_the_window_open(space: Workspace) -> None:
    window = dialog(space, imported(space))
    window.version_box.setText("버전")
    window.save()
    assert window.saved is None
    assert window.result() != ProcessInfoDialog.DialogCode.Accepted
    assert "버전은" in window.note.text()


def test_the_graph_fields_are_off_when_the_entry_is_not_open(space: Workspace) -> None:
    """**그림은 캔버스가 쓴다** (ADR-0022) — 진입이 열려 있지 않으면 끄고 까닭을 적는다 (U3)."""
    process = imported(space)
    window = dialog(space, process, editable=False)
    assert not window.location_box.isEnabled()
    entry = process.entry_definition
    assert entry is not None
    assert entry.path.name in window.note.text()

    window.name_box.setText("이름만 바꾼다")
    window.save()
    assert window.saved is not None, "기록은 그래도 저장된다"
    assert window.process_patch is None, "그림은 건드리지 않는다"


def test_saving_builds_one_patch_that_keeps_what_the_window_does_not_know(space: Workspace) -> None:
    """**읽은 것을 통째로 되돌려 쓴다** — 창이 모르는 칸(`inputs`)이 사라지면 안 된다."""
    process = imported(space)
    window = dialog(space, process)
    assert window.info.inputs, "예제가 입력을 선언한다 (지켜야 할 칸이다)"

    at = window.location_box.findData("pc")
    window.location_box.setCurrentIndex(at)
    window.save()

    assert window.process_patch is not None
    found = json.loads(window.process_patch)
    assert found["run_location"] == "pc"
    assert "service_keys" not in found, "키 참조는 없다 (ADR-0102) — 창이 지어 넣지 않는다"
    assert [one["name"] for one in found["inputs"]] == [one.name for one in window.info.inputs]


def test_the_server_warning_shows_only_for_server_and_does_not_block(space: Workspace) -> None:
    """저장을 막지 않는다 (STU-06) — 고칠 거리를 알려 줄 뿐이다."""
    process = imported(space, PC_EXAMPLE)
    window = dialog(space, process)
    at = window.location_box.findData("server")
    window.location_box.setCurrentIndex(at)
    # 창을 띄우지 않았으므로 `isVisible()`이 아니라 **명시적으로 숨겼나**를 본다.
    assert not window.warning.isHidden()
    assert "실행할 수 없는 태스크" in window.warning.text()
    assert not window.to_pc.isHidden()

    window.save()
    assert window.saved is not None, "경고는 저장을 막지 않는다"
    assert json.loads(window.process_patch or "{}")["run_location"] == "server"


def test_the_button_moves_the_location_back_to_pc(space: Workspace) -> None:
    window = dialog(space, imported(space, PC_EXAMPLE))
    window.location_box.setCurrentIndex(window.location_box.findData("server"))
    window.to_pc.click()
    assert window.location() == "pc"
    assert window.warning.isHidden(), "PC면 걸릴 것이 없다"
    assert window.warning.text() == ""


def test_the_split_button_stands_beside_to_pc_and_asks_first(space: Workspace, monkeypatch: Any) -> None:
    """STU-06 「이 부분을 PC BPM 프로세스로 나누기...」 (ADR-0071) — 「PC로 바꾸기」와 **같이** 보이고,
    누르면 이 창에서 고친 것이 저장되지 않는다고 **먼저 묻는다**. 그림은 메인 창이 바꾼다."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    found = dialog(space, imported(space, EXTENSION_EXAMPLE), task_type_locations=UI_TASK_ON_PC)
    found.location_box.setCurrentIndex(found.location_box.findData("server"))
    assert not found.to_split.isHidden() and not found.to_pc.isHidden()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    found._ask_split()
    assert found.split_requested is False, "「취소」면 그대로다"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Ok)
    found._ask_split()
    assert found.split_requested is True and found.saved is None, "저장하지 않고 닫힌다"

    found.location_box.setCurrentIndex(found.location_box.findData("pc"))
    assert found.to_split.isHidden(), "PC에서는 나눌 까닭이 없다"


# ─────────────────────────── 「서비스 앱 키」 섹션은 없다 (ADR-0102) ───────────────────────────


def test_there_is_no_key_table_and_a_written_reference_survives(space: Workspace) -> None:
    """키가 없다 — 표가 없고, 옛 그림에 적힌 참조는 **조용히 지우지 않는다** (모르는 칸으로 남는다, C14 B7)."""
    process = imported(space)
    entry = process.entry_definition
    assert entry is not None
    drawn = read_process(entry.path.read_text(encoding="utf-8"))
    assert drawn.info.model_extra is not None
    drawn.info.model_extra["service_keys"] = {"ext-credit": "applied-ref"}  # 옛 칸 — 모르는 칸으로 남는다
    window = ProcessInfoDialog(process, space, editable=True, drawn=drawn)
    assert not hasattr(window, "keys") and not hasattr(window, "drop_key")
    window.save()
    assert window.process_patch is not None
    assert json.loads(window.process_patch)["service_keys"] == {"ext-credit": "applied-ref"}


def test_the_button_is_apply_and_says_where_things_go(space: Workspace) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    window = dialog(space, imported(space))
    apply = window.buttons.button(QDialogButtonBox.StandardButton.Apply)
    assert apply is not None and apply.text() == "적용"
    assert window.buttons.button(QDialogButtonBox.StandardButton.Save) is None
    assert window.apply_note.text() == module.APPLY_NOTE
    closed = dialog(space, imported(space, PC_EXAMPLE), editable=False)
    assert closed.apply_note.text() == module.APPLY_NOTE_RECORD_ONLY

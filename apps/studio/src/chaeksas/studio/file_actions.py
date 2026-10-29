"""정의를 열고·닫고·저장하고·만들고·가져오는 자리 (STU-01·STU-05).

메인 창에서 떼어 낸 글루다 (`main_window.py`가 500줄 선을 넘어 가른 자리, CLAUDE.md §4).
**창의 상태를 바꾸는 쪽**이라 창을 받아 쓴다 — 열린 BPM 프로세스·정의·「저장 안 한 변경」은
창이 쥐고, 이 모듈이 그것을 옮긴다 (`run_actions`가 `window.queue`를 옮기는 것과 같은 결).

지키는 것 셋.

- **디스크가 원본이다.** 캔버스가 들고 있는 것은 편집 중인 사본이고, 저장은 그것을 작업
  폴더에 쓴다 (`workspace.save_definition` — 늘 UTF-8이다, CLAUDE.md §5).
- **저장 안 한 변경을 말없이 버리지 않는다** (U11). 전환·닫기·만들기·가져오기가 **같은
  관문**(`may_discard`)을 지난다.
- **XML을 글자로 견주지 않는다** — 「저장 안 한 변경」은 캔버스가 `dirtied`로 말해 준다
  (bpmn-js가 DI 순서·기본값을 바꾸므로, ADR-0022).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QInputDialog, QMessageBox

from chaeksas.qt.messages import ask_unsaved
from chaeksas.studio.canvas import CanvasError
from chaeksas.studio.dialogs import NewProcessDialog, pick_bpmn_file
from chaeksas.studio.workspace import (
    WorkspaceError,
    check_definition_name,
    definition_process_id,
)

if TYPE_CHECKING:  # pragma: no cover - 순환 import를 피한다 (창이 이 모듈을 부른다)
    from chaeksas.studio.main_window import MainWindow

NO_DEFINITION = "열린 정의가 없습니다."
NO_PROCESS = "열린 BPM 프로세스가 없습니다."
DISCARD_TITLE = "저장하지 않은 변경사항"
DISCARD_TEXT = "저장하지 않은 변경사항이 있습니다. 저장할까요?"
#: 그림 좌표가 없어 캔버스가 배치했을 때 (ADR-0088) — 디스크와 다르다는 것을 말한다.
LAID_OUT = "그림 좌표가 없어 자동 배치했습니다 — 저장하면 파일에 남습니다."
#: 시험 실행 중에는 닫지 않는다 — 실행이 그 그림에 노드 상태를 칠한다.
CLOSE_WHILE_RUNNING = "시험 실행 중에는 닫을 수 없습니다 — 먼저 「실행 중지」를 누르세요."


def may_discard(window: MainWindow) -> bool:
    """저장 안 한 변경이 있으면 묻는다 (STU-01 U11). 전환·닫기·만들기가 같은 관문을 쓴다."""
    if not window.dirty:
        return True
    answer = ask_unsaved(window, DISCARD_TITLE, DISCARD_TEXT)
    if answer == QMessageBox.StandardButton.Cancel:
        return False
    if answer == QMessageBox.StandardButton.Save:
        return save(window)
    return True


def open_definition(window: MainWindow, path_text: str) -> None:
    """정의 하나를 캔버스에 띄운다. **찾는 것은 작업 폴더에서** (디스크가 원본이다)."""
    if not may_discard(window):
        return
    path = Path(path_text)
    process = next(
        (
            one
            for group in window.workspace.groups()
            for one in group.processes
            if any(d.path == path for d in one.definitions)
        ),
        None,
    )
    if process is None or not path.is_file():
        window.say(f"정의를 찾지 못했습니다: {path.name}")
        return

    def done(found: dict[str, object]) -> None:
        if not found.get("ok"):
            window.say(f"열지 못했습니다: {found.get('error')}")
            return
        warnings = found.get("warnings")
        count = len(warnings) if isinstance(warnings, list) else 0
        laid_out = bool(found.get("laid_out"))
        window.process, window.definition, window.dirty = process, path, laid_out
        window.properties.show_nothing()
        window.preflight.setRowCount(0)
        window.retitle()
        window.explorer.refresh(opened=path.as_posix())
        note = f" (경고 {count}개)" if count else ""
        window.say(f"열었습니다: {process.display} / {path.name}{note}")
        if laid_out:
            window.say(LAID_OUT)
        # STU-14가 고를 거리는 **정의를 열 때** 받는다 (노드를 고를 때마다 두드리지 않게).
        window.refresh_catalog()
        entry = process.entry_definition
        window.properties.run_location = (
            entry.process.info.run_location if entry is not None and entry.process is not None else None
        )

    window.canvas.load_xml(path.read_text(encoding="utf-8"), then=done)


def save(window: MainWindow) -> bool:
    """캔버스의 것을 작업 폴더에 쓴다. 적용 안 한 편집이 있으면 먼저 묻는다 (STU-04)."""
    process, definition = window.process, window.definition
    if process is None or definition is None:
        window.say(NO_DEFINITION)
        return False
    if not window.may_drop_edits():
        return False
    try:
        xml = window.canvas.save_xml()
    except CanvasError as e:
        window.say(f"저장하지 못했습니다: {e}")
        return False
    window.workspace.save_definition(process, definition.name, xml)
    window.dirty = False
    window.retitle()
    window.say(f"저장했습니다: {definition.name}")
    return True


def new_process(window: MainWindow) -> None:
    """STU-05. 만든 뒤 빈 정의를 캔버스에 띄우고 바로 저장한다.

    「첫 정의」로 파일을 골랐으면 작업 폴더가 이미 복사해 두었으니 **그것을 연다** (빈 정의를
    짓지 않는다). 「지금 열린 정의 복사」가 디스크의 것을 옮기므로 관문(`may_discard`)이 먼저다.
    """
    if not may_discard(window):
        return
    made = NewProcessDialog.ask(window, window.workspace, opened=window.definition)
    if made is None:
        return
    entry = made.entry_definition
    if entry is not None and entry.path.is_file():
        window.explorer.refresh(opened=entry.path.as_posix())
        window.say(f"만들었습니다: {made.display} — 첫 정의 {entry.path.name}")
        open_definition(window, entry.path.as_posix())
        return
    try:
        window.canvas.create_empty(f"Proc_{made.id.replace('-', '_')}", made.display)
        xml = window.canvas.save_xml()
    except CanvasError as e:
        window.say(f"빈 정의를 만들지 못했습니다: {e}")
        return
    path = window.workspace.save_definition(made, made.entry, xml)
    window.explorer.refresh(opened=path.as_posix())
    open_definition(window, path.as_posix())


def add_definition(window: MainWindow) -> None:
    """STU-01 파일 → 「정의 추가...」 — 빈 하위 정의 하나를 만들고 **그것을 연다**.

    캔버스가 비는 일이라 전환과 **같은 관문**(`may_discard`)을 지난다. 이름 규칙은 작업 폴더가
    안다 (`check_definition_name` — 경로를 받지 않고, 대소문자만 다른 이름도 거부한다).
    """
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return
    if not may_discard(window):
        return
    raw, ok = QInputDialog.getText(window, "정의 추가", "정의 이름 (.bpmn)")
    if not ok:
        return
    try:
        file_name = check_definition_name(process, raw)
    except WorkspaceError as e:
        QMessageBox.warning(window, "정의 추가", str(e))
        return
    try:
        window.canvas.create_empty(definition_process_id(file_name), Path(file_name).stem)
        xml = window.canvas.save_xml()
    except CanvasError as e:
        window.say(f"빈 정의를 만들지 못했습니다: {e}")
        return
    path = window.workspace.save_definition(process, file_name, xml)
    window.explorer.refresh(opened=path.as_posix())
    # **디스크에서 다시 읽어 연다** — 그래야 창이 쥔 BPM 프로세스에 새 정의가 들어 있다.
    open_definition(window, path.as_posix())


def make_entry(window: MainWindow) -> None:
    """STU-01 파일 → 「이 정의를 진입으로 지정」 — **기록만** 바뀐다 (그림은 그대로다).

    진입이 무엇인지는 작업 폴더의 기록이고(계약이 아니다) 패키지의 `entry`는 내보낼 때 거기서
    온다 (C1 R1). 그림을 고치지 않으니 캔버스를 거칠 일도 없다 (ADR-0022).
    """
    process, found = window.process, window.opened_definition()
    if process is None or found is None:
        window.say(NO_DEFINITION)
        return
    entry = process.entry_definition
    if entry is not None and entry.path == found.path:
        window.say(f"이미 진입 정의입니다: {found.path.name}")
        return
    try:
        window.process = window.workspace.set_entry(process, found.path.name)
    except WorkspaceError as e:
        QMessageBox.warning(window, "진입 정의", str(e))
        return
    window.retitle()
    window.explorer.refresh(opened=found.path.as_posix())
    window.say(f"진입 정의로 지정했습니다: {found.path.name}")


def save_process_as(window: MainWindow) -> None:
    """STU-01 파일 → 「다른 이름으로 저장...」 (Ctrl+Shift+S) — BPM 프로세스 **한 벌**을 복사한다.

    **정의 하나가 아니다.** 파일 메뉴의 단위가 BPM 프로세스이고(U1 — 파일을 직접 여는 메뉴가
    없다), 정의 하나만 복사하면 그림 안의 BPMN process id가 겹쳐 `callActivity`가 어느 것을
    부를지 모호해진다 — 고치려면 XML을 파이썬이 만져야 하고 그것은 ADR-0022가 막는다.

    **옮기는 것은 디스크의 것이다** — 그래서 먼저 저장을 거친다 (`saved_to_disk`).
    """
    process = window.process
    if process is None:
        window.say(NO_PROCESS)
        return
    if not window.saved_to_disk():
        return
    made = NewProcessDialog.ask(window, window.workspace, source=process)
    if made is None:
        return
    window.explorer.refresh()
    window.say(f"복사했습니다: {made.display} (v{made.version}) — 이제 복사한 쪽을 편집합니다.")
    entry = made.entry_definition
    if entry is not None:
        open_definition(window, entry.path.as_posix())


def open_process(window: MainWindow) -> None:
    """STU-01 「BPM 프로세스 열기...」 (Ctrl+O) — `.bpmn` 하나를 고른다 (작업 폴더에서 시작).

    **이미 어느 BPM 프로세스의 정의면** 그것을 연다(탐색기 목록에 올라간다). 아니면 **가져온다**
    — STU-05로 id·이름을 받아 그 파일 **하나만** 진입 정의로 복사한다 (`Workspace.create`의
    `first` — 원본은 읽기만 한다). 그림 좌표가 없으면 **열 때** 캔버스가 배치한다 (ADR-0088).
    BPM 프로세스 없이 파일만 열지 않는다 (U1).
    """
    picked = pick_bpmn_file(window, window.workspace.root)
    if picked is None:
        return
    target = picked.resolve()
    for group in window.workspace.groups():
        for one in group.processes:
            for definition in one.definitions:
                if definition.path.resolve() == target:
                    open_definition(window, definition.path.as_posix())
                    return
    if not may_discard(window):
        return
    # 같은 id가 있으면 창이 「기존 것을 바꾸기」를 묻는다 — 상태 줄이 무엇을 했는지 가른다.
    known = {one.id for group in window.workspace.groups() for one in group.processes}
    made = NewProcessDialog.ask(window, window.workspace, imported=picked)
    if made is None:
        return
    entry = made.entry_definition
    window.explorer.refresh(opened=entry.path.as_posix() if entry is not None else "")
    if made.id in known:
        window.say(f"진입 정의를 바꿨습니다: {made.display} / {made.entry} ← {picked.name}")
    else:
        window.say(f"가져왔습니다: {made.display} — {picked.name}")
    if entry is not None:
        open_definition(window, entry.path.as_posix())


def close_process(window: MainWindow) -> None:
    """STU-01 「BPM 프로세스 닫기」 (Ctrl+W) — 캔버스를 비우고 **탐색기 목록에서 뺀다**.

    다음에 띄울 때도 열지 않는다. 파일은 지우지 않는다 — 다시 올리는 길은 `open_process`다.

    저장 안 한 변경은 같은 관문(`may_discard`)이 묻는다. 시험 실행 중이면 닫지 않는다 — 실행이
    그 그림에 노드 상태를 칠하고, 끝나면 그 BPM 프로세스의 기록을 쓴다.
    """
    if window.process is None:
        window.say(NO_PROCESS)
        return
    if window.running is not None:
        window.say(CLOSE_WHILE_RUNNING)
        return
    if not may_discard(window):
        return
    closed = window.process.display
    try:
        window.canvas.clear()
    except CanvasError as e:
        window.say(f"캔버스를 비우지 못했습니다: {e}")
        return
    closed_id = window.process.id
    window.process, window.definition, window.dirty = None, None, False
    window.properties.show_nothing()
    window.preflight.setRowCount(0)
    window.retitle()
    # STU-02 — 닫으면 목록에서도 빠진다 (작업 폴더의 파일은 그대로다).
    window.explorer.unlist(closed_id)
    remember_last_opened(window)
    window.say(f"닫았습니다: {closed}")


def remember_last_opened(window: MainWindow) -> None:
    """마지막으로 열었던 정의와 탐색기 목록을 설정에 남긴다 (다음에 그대로 뜬다). **닫았으면 비운다**."""
    opened = window.definition.as_posix() if window.definition is not None else ""
    listed = tuple(window.explorer.listed)
    if (opened, listed) != (window.settings.last_opened, window.settings.open_processes):
        window.settings = replace(window.settings, last_opened=opened, open_processes=listed)
        window.settings.save()


__all__ = [
    "CLOSE_WHILE_RUNNING",
    "DISCARD_TEXT",
    "DISCARD_TITLE",
    "LAID_OUT",
    "NO_DEFINITION",
    "NO_PROCESS",
    "add_definition",
    "close_process",
    "make_entry",
    "may_discard",
    "new_process",
    "open_definition",
    "open_process",
    "remember_last_opened",
    "save",
    "save_process_as",
]

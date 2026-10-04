"""STU-02 BPM 프로세스 탐색기 — 그룹 → BPM 프로세스 → 정의.

**파일을 직접 여는 메뉴는 없다** (STU-01 U1). BPM 프로세스는 여기서 연다.

열은 셋이다: 「BPM 프로세스 / 정의」, 「버전」, 「학습·검증」. 학습·검증 칸은 지금 AI 태스크 수만
센다 — 학습·재생 검증·케이스 통과 수는 시험 실행이 생긴 뒤에 채운다 (조각 3e-3).
"""

from __future__ import annotations

from collections.abc import Iterator

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView, QWidget

from chaeksas.studio.workspace import BpmProcess, Definition, Group, Workspace

HEADERS = ("BPM 프로세스 / 정의", "버전", "학습·검증")

#: 줄 하나가 무엇인지 (문맥 메뉴·더블클릭이 갈린다).
ROW_GROUP = "group"
ROW_PROCESS = "process"
ROW_DEFINITION = "definition"

_KIND = Qt.ItemDataRole.UserRole + 1
_PAYLOAD = Qt.ItemDataRole.UserRole + 2

EMPTY_TEXT = "BPM 프로세스가 없습니다. 파일 → 새 BPM 프로세스...로 만드세요."


def ai_task_count(definition: Definition) -> int:
    if definition.process is None:
        return 0
    return sum(1 for node in definition.process.all_nodes() if node.prop("aiTask") is not None)


def summary(process: BpmProcess) -> str:
    """BPM 프로세스 줄의 「학습·검증」 (STU-02).

    학습·재생 검증·케이스 통과는 시험 실행이 세는 것이라 아직 비어 있다 — 수를 지어내지 않는다.
    """
    total = sum(ai_task_count(d) for d in process.definitions)
    if not process.definitions:
        return "정의 없음"
    return f"AI 태스크 {total}개 · 정의 {len(process.definitions)}개"


def definition_note(process: BpmProcess, definition: Definition) -> str:
    if definition.problem:
        return f"읽지 못함: {definition.problem}"
    entry = process.entry_definition
    if entry is not None and entry.path == definition.path:
        return "진입"
    called = {
        node.called_element
        for other in process.definitions
        if other.process is not None
        for node in other.process.all_nodes()
        if node.called_element
    }
    return "진입에서 호출되지 않음" if definition.id not in called else "호출됨"


class ExplorerModel(QStandardItemModel):
    """디스크를 읽어 만든 나무. **디스크가 원본**이라 바뀌면 다시 읽는다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHorizontalHeaderLabels(list(HEADERS))

    def fill(self, groups: list[Group], *, opened: str = "") -> None:
        self.removeRows(0, self.rowCount())
        for group in groups:
            row = _row(group.name, "", "", ROW_GROUP, group.name)
            for process in group.processes:
                row[0].appendRow(_process_row(process, opened))
            self.appendRow(row)

    def rows(self) -> Iterator[QStandardItem]:
        def walk(item: QStandardItem) -> Iterator[QStandardItem]:
            yield item
            for index in range(item.rowCount()):
                yield from walk(item.child(index, 0))

        for index in range(self.rowCount()):
            yield from walk(self.item(index, 0))


def _row(text: str, version: str, note: str, kind: str, payload: object) -> list[QStandardItem]:
    first = QStandardItem(text)
    first.setData(kind, _KIND)
    first.setData(payload, _PAYLOAD)
    cells = [first, QStandardItem(version), QStandardItem(note)]
    for cell in cells:
        cell.setEditable(False)
    return cells


def _process_row(process: BpmProcess, opened: str) -> list[QStandardItem]:
    row = _row(process.display, process.version, summary(process), ROW_PROCESS, process.id)
    for definition in process.definitions:
        child = _row(
            definition.name, "", definition_note(process, definition), ROW_DEFINITION,
            definition.path.as_posix(),
        )
        if definition.path.as_posix() == opened:
            _embolden(child)
        row[0].appendRow(child)
    if any(d.path.as_posix() == opened for d in process.definitions):
        _embolden(row)
    return row


def _embolden(cells: list[QStandardItem]) -> None:
    for cell in cells:
        font = QFont(cell.font())
        font.setBold(True)
        cell.setFont(font)


class Explorer(QTreeView):
    """STU-02. 더블클릭·Enter로 연다 — BPM 프로세스 줄이면 진입 정의를."""

    #: 열 정의의 경로 (`Definition.path`).
    opening = Signal(str)

    def __init__(self, workspace: Workspace, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._model = ExplorerModel(self)
        self.setModel(self._model)
        self.setAlternatingRowColors(True)
        self.setRootIsDecorated(True)
        self.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doubleClicked.connect(lambda _: self.open_selected())
        self.refresh()

    def refresh(self, *, opened: str = "") -> None:
        self._model.fill(self.workspace.groups(), opened=opened)
        self.expandAll()
        for column in range(len(HEADERS)):
            self.resizeColumnToContents(column)

    # ── 고른 줄 ──

    def selection(self) -> tuple[str, object] | None:
        """고른 줄의 `(종류, 값)`. 고른 것이 없으면 `None`."""
        indexes = self.selectedIndexes()
        if not indexes:
            return None
        item = self._model.itemFromIndex(indexes[0].siblingAtColumn(0))
        if item is None:
            return None
        return str(item.data(_KIND)), item.data(_PAYLOAD)

    def open_selected(self) -> None:
        found = self.selection()
        if found is None:
            return
        kind, payload = found
        if kind == ROW_DEFINITION:
            self.opening.emit(str(payload))
            return
        if kind == ROW_PROCESS:
            process = self.workspace.find(str(payload))
            entry = process.entry_definition if process else None
            if entry is not None:
                self.opening.emit(entry.path.as_posix())

    def keyPressEvent(self, event: object) -> None:  # noqa: N802 — Qt 이름 그대로
        from PySide6.QtGui import QKeyEvent  # noqa: PLC0415

        if isinstance(event, QKeyEvent) and event.key() in (
            Qt.Key.Key_Return.value, Qt.Key.Key_Enter.value
        ):
            self.open_selected()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]


__all__ = [
    "EMPTY_TEXT",
    "HEADERS",
    "ROW_DEFINITION",
    "ROW_GROUP",
    "ROW_PROCESS",
    "Explorer",
    "ExplorerModel",
    "ai_task_count",
    "definition_note",
    "summary",
]

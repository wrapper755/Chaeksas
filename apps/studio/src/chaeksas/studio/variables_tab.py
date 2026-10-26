"""STU-01 아래 탭 「변수」 — 입력·출력 **정의**를 고치고, 시험 실행 중에는 **지금 값**을 보인다.

한 표(나무)에 무리가 넷이다: 「입력」·「출력」(고친다), 「그림이 만드는 변수」(읽기 전용),
「그 밖의 값」(실행 중에만). 값 다루기는 `variables.py`(Qt 없음)에 있다.

**이 탭은 그림을 만지지 않는다** — 「적용」은 `chk:process` 본문을 `applying`으로 올리고 캔버스를
쥔 메인 창이 넘긴다 (ADR-0022 — 실행 취소가 한 걸음). 그림을 읽는 것도 메인 창이다
(`show_definition`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import INPUT_SOURCE_CALLER, INPUT_SOURCE_TYPES, InputDecl, ProcessInfo
from chaeksas.qt.theme.tokens import SPACE_2
from chaeksas.studio.variables import (
    INPUT_SOURCES,
    INPUT_TYPES,
    NONE,
    InputRow,
    caption,
    changed,
    problem,
    process_patch,
    value_text,
)

COLUMNS = ("이름", "타입", "필수", "기본값", "값 출처 / 만드는 곳", "설명", "지금 값")
NAME, TYPE, REQUIRED, DEFAULT, SOURCE, DESCRIPTION, NOW = range(len(COLUMNS))

GROUP_INPUTS = "입력"
GROUP_OUTPUTS = "출력"
GROUP_MADE = "그림이 만드는 변수"
GROUP_OTHER = "그 밖의 값"

NOTE_EDITABLE = "적용하면 그림에 들어갑니다 — 「저장」(Ctrl+S)으로 파일에 씁니다."
NO_PROCESS = "열린 BPM 프로세스가 없습니다."
RUNNING = "시험 실행 중에는 고칠 수 없습니다."
SOURCE_TIP = "가상 직원 출처는 Center가 넣습니다 — 부르는 쪽(작업 지시·메시지)은 줄 수 없습니다."
MADE_TIP = "노드를 지나면 생기는 변수 — 노드 속성에서 고칩니다."

#: 입력 줄에서 글로 고치는 열 (타입·값 출처는 콤보, 필수는 체크다).
INPUT_TEXT_COLUMNS = (NAME, DEFAULT, DESCRIPTION)
#: 줄에 붙여 두는 읽어 온 그 입력 — 표가 모르는 칸을 그 줄에 남긴다.
ORIGINAL = Qt.ItemDataRole.UserRole


def _children(group: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    return [found for at in range(group.childCount()) if (found := group.child(at)) is not None]


class _Edits(QStyledItemDelegate):
    """**고칠 수 있는 칸만** 칸을 연다 — 나무는 줄 단위로만 「고칠 수 있음」을 단다."""

    def __init__(self, tab: VariablesTab) -> None:
        super().__init__(tab)
        self.tab = tab

    def createEditor(  # noqa: N802 — Qt 이름 그대로
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        if not isinstance(index, QModelIndex):
            index = index.model().index(index.row(), index.column(), index.parent())
        item = self.tab.tree.itemFromIndex(index)
        if self.tab.locked or item is None or item.parent() is None:
            return None  # type: ignore[return-value]  # 칸을 열지 않는다
        group = item.parent()
        column = index.column()
        if group is self.tab.inputs_group and column in INPUT_TEXT_COLUMNS:
            return QLineEdit(parent)
        if group is self.tab.outputs_group and column == NAME:
            return QLineEdit(parent)
        return None  # type: ignore[return-value]


class VariablesTab(QWidget):
    """「변수」 탭. 메인 창이 `show_definition`·`show_values`로 채우고 `applying`을 받는다."""

    #: 「적용」 — 캔버스에 넘길 `chk:process` 본문(JSON 글).
    applying = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info: ProcessInfo | None = None
        #: 어느 정의의 표인가 — 바뀌면 지금 값을 비운다.
        self.key = ""
        self.made: dict[str, list[str]] = {}
        self.values: dict[str, Any] | None = None
        self.locked = True
        self._reason = NO_PROCESS
        self._quiet = False

        self.add_input = QPushButton("입력 더하기", self)
        self.add_output = QPushButton("출력 더하기", self)
        self.drop_row = QPushButton("줄 삭제", self)
        self.drop_row.setObjectName("Secondary")
        self.apply_button = QPushButton("적용", self)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setItemDelegate(_Edits(self))
        self.tree.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
        )
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column, width in ((NAME, 140), (TYPE, 100), (REQUIRED, 44), (DEFAULT, 110), (SOURCE, 170)):
            self.tree.setColumnWidth(column, width)
        self.inputs_group = self._group()
        self.outputs_group = self._group()
        self.made_group = self._group()
        self.other_group = self._group()

        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        self.note.setProperty("role", "muted")
        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        self.error.setProperty("role", "error")
        self.error.hide()

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_input)
        buttons.addWidget(self.add_output)
        buttons.addWidget(self.drop_row)
        buttons.addStretch(1)
        buttons.addWidget(self.apply_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_2)
        layout.addLayout(buttons)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.note)
        layout.addWidget(self.error)

        self.add_input.clicked.connect(lambda: self._new_input())
        self.add_output.clicked.connect(lambda: self._new_output())
        self.drop_row.clicked.connect(self._drop)
        self.apply_button.clicked.connect(self.apply)
        self.tree.itemChanged.connect(lambda *_: self._changed())
        self.tree.currentItemChanged.connect(lambda *_: self._refresh_buttons())
        self._regroup()
        self._refresh_buttons()

    # ── 채우기 (메인 창이 부른다) ──

    def show_definition(
        self,
        info: ProcessInfo | None,
        made: Mapping[str, Sequence[str]],
        *,
        key: str,
        reason: str = "",
    ) -> None:
        """그림에서 읽은 것을 보인다. `reason`이 있으면 고치기를 잠근다 (표는 보인다, U3).

        **적용 안 한 편집이 있으면 입력·출력 줄은 그대로 두고** 「그림이 만드는 변수」만
        바꾼다 — 캔버스에서 노드를 고칠 때마다 사람이 고치던 것을 덮으면 안 된다.
        """
        if key != self.key:
            self.values = None
        keep = key == self.key and info is not None and self.unapplied
        self.key = key
        self.made = {name: list(nodes) for name, nodes in made.items()}
        self._reason = reason
        # 이 탭이 모르는 칸(실행 위치 …)은 **지금 그림의 것**을 들고 있어야 적용이 덮지 않는다.
        self.info = info
        self._quiet = True
        if not keep:
            self._fill_definitions(info)
        self._fill_made()
        self._fill_values()
        self._quiet = False
        self.set_locked(bool(reason) or info is None, reason or (NO_PROCESS if info is None else ""))

    def show_values(self, variables: Mapping[str, Any]) -> None:
        """시험 실행이 보낸 값 — 「지금 값」 열이 보이고 없는 이름은 「그 밖의 값」에 간다."""
        self.values = dict(variables)
        self._quiet = True
        self._fill_values()
        self._quiet = False
        self.note.setText(caption(variables))

    def clear_values(self) -> None:
        """다음 실행이 시작할 때."""
        self.values = None
        self._quiet = True
        self._fill_values()
        self._quiet = False

    def set_locked(self, locked: bool, reason: str = "") -> None:
        self.locked = locked
        self._reason = reason if locked else ""
        for item in _children(self.inputs_group):
            for column in (TYPE, SOURCE):
                widget = self.tree.itemWidget(item, column)
                if isinstance(widget, QComboBox):
                    widget.setEnabled(not locked and not (column == TYPE and self._type_pinned(item)))
            flags = item.flags()
            checkable = Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags & ~checkable if locked else flags | checkable)
        if self.values is not None and locked:
            self.note.setText(caption(self.values))
        else:
            self.note.setText(self._reason or NOTE_EDITABLE)
        self._refresh_buttons()

    # ── 읽기 ──

    def input_rows(self) -> list[InputRow]:
        out: list[InputRow] = []
        for item in _children(self.inputs_group):
            kind = self.tree.itemWidget(item, TYPE)
            source = self.tree.itemWidget(item, SOURCE)
            assert isinstance(kind, QComboBox) and isinstance(source, QComboBox)
            out.append(
                InputRow(
                    name=item.text(NAME),
                    type=kind.currentText(),
                    required=item.checkState(REQUIRED) == Qt.CheckState.Checked,
                    default=item.text(DEFAULT),
                    source=str(source.currentData()),
                    description=item.text(DESCRIPTION),
                    original=item.data(NAME, ORIGINAL),
                )
            )
        return out

    def output_names(self) -> list[str]:
        return [item.text(NAME) for item in _children(self.outputs_group)]

    @property
    def unapplied(self) -> bool:
        """적용 안 한 편집이 있나 (STU-01 「닫기·전환 보호」)."""
        if self.info is None:
            return False
        return changed(self.info, self.input_rows(), self.output_names())

    def patch(self) -> tuple[str | None, str | None]:
        """`(본문, 흠)` — 흠이 있으면 본문이 없다 (STU-04 `patch`와 같은 모양)."""
        if self.info is None:
            return None, NO_PROCESS
        rows, outputs = self.input_rows(), self.output_names()
        found = problem(rows, outputs)
        if found:
            return None, found
        return process_patch(self.info, rows, outputs), None

    def apply(self) -> bool:
        body, found = self.patch()
        if body is None:
            self._say_error(found or "")
            return False
        self.applying.emit(body)
        return True

    def discard(self) -> None:
        """「버리기」 — 그림에 있는 것으로 되돌린다."""
        self._quiet = True
        self._fill_definitions(self.info)
        self._fill_values()
        self._quiet = False
        self.set_locked(self.locked, self._reason)
        self._changed()

    # ── 짓기 ──

    def _group(self) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setFirstColumnSpanned(True)
        font = item.font(NAME)
        font.setBold(True)
        item.setFont(NAME, font)
        item.setExpanded(True)
        return item

    def _regroup(self) -> None:
        """무리 이름에 줄 수를 붙이고, 「그 밖의 값」은 값이 있을 때만 보인다.

        무리 이름을 바꾸는 것도 `itemChanged`라 **조용히** 바꾼다 — 아니면 `_changed`가 다시 부른다.
        """
        quiet, self._quiet = self._quiet, True
        try:
            self._relabel()
        finally:
            self._quiet = quiet

    def _relabel(self) -> None:
        for group, title in (
            (self.inputs_group, GROUP_INPUTS),
            (self.outputs_group, GROUP_OUTPUTS),
            (self.made_group, GROUP_MADE),
            (self.other_group, GROUP_OTHER),
        ):
            group.setText(NAME, f"{title} ({group.childCount()})")
        if self.values is None:
            self.made_group.setText(NAME, f"{self.made_group.text(NAME)} — 읽기 전용")
        self.other_group.setHidden(self.other_group.childCount() == 0)
        self.tree.setColumnHidden(NOW, self.values is None)

    def _fill_definitions(self, info: ProcessInfo | None) -> None:
        self.inputs_group.takeChildren()
        self.outputs_group.takeChildren()
        if info is not None:
            for decl in info.inputs:
                self._input_item(InputRow.of(decl), decl)
            for name in info.outputs:
                self._output_item(name)
        self._regroup()

    def _fill_made(self) -> None:
        self.made_group.takeChildren()
        declared = {decl.name for decl in self.info.inputs} | set(self.info.outputs) if self.info else set()
        for name in sorted(self.made):
            if name in declared:
                continue  # 입력·출력에 이미 있는 이름은 다시 적지 않는다
            item = QTreeWidgetItem(self.made_group)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setText(NAME, name)
            item.setText(SOURCE, ", ".join(self.made[name]))
            item.setToolTip(NAME, MADE_TIP)
        self._regroup()

    def _fill_values(self) -> None:
        self.other_group.takeChildren()
        values = self.values
        shown: set[str] = set()
        for group in (self.inputs_group, self.outputs_group, self.made_group):
            for item in _children(group):
                name = item.text(NAME)
                shown.add(name)
                item.setText(NOW, "" if values is None else value_text(values[name]) if name in values else NONE)
        for name in sorted(values or {}):
            if name in shown:
                continue
            item = QTreeWidgetItem(self.other_group)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setText(NAME, name)
            item.setText(NOW, value_text((values or {})[name]))
        self._regroup()

    def _input_item(self, row: InputRow, decl: InputDecl | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.inputs_group)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        item.setText(NAME, row.name)
        item.setData(NAME, ORIGINAL, decl)
        item.setCheckState(REQUIRED, Qt.CheckState.Checked if row.required else Qt.CheckState.Unchecked)
        item.setText(DEFAULT, row.default)
        item.setText(DESCRIPTION, row.description)

        kind = QComboBox(self.tree)
        kind.addItems(list(INPUT_TYPES))
        if row.type not in INPUT_TYPES:
            kind.addItem(row.type)  # 모르는 타입도 그대로 보인다 (B8이 말한다)
        kind.setCurrentText(row.type)
        self.tree.setItemWidget(item, TYPE, kind)

        source = QComboBox(self.tree)
        source.setToolTip(SOURCE_TIP)
        for value, label in INPUT_SOURCES:
            source.addItem(label, value)
        if source.findData(row.source) < 0:
            source.addItem(row.source, row.source)  # 모르는 출처는 글자 그대로 둔다
        source.setCurrentIndex(source.findData(row.source))
        self.tree.setItemWidget(item, SOURCE, source)
        self._match_type(source, kind)
        kind.currentIndexChanged.connect(lambda _at: self._changed())
        source.currentIndexChanged.connect(lambda _at, s=source, k=kind: self._source_changed(s, k))
        return item

    def _output_item(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.outputs_group)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        item.setText(NAME, name)
        return item

    def _new_input(self) -> None:
        if self.locked:
            return
        self._quiet = True
        item = self._input_item(InputRow(name=""))
        self._fill_values()
        self._quiet = False
        self._changed()
        self.tree.setCurrentItem(item, NAME)
        self.tree.editItem(item, NAME)

    def _new_output(self) -> None:
        if self.locked:
            return
        self._quiet = True
        item = self._output_item("")
        self._fill_values()
        self._quiet = False
        self._changed()
        self.tree.setCurrentItem(item, NAME)
        self.tree.editItem(item, NAME)

    def _drop(self) -> None:
        item = self.tree.currentItem()
        if self.locked or item is None or item.parent() not in (self.inputs_group, self.outputs_group):
            return
        group = item.parent()
        assert group is not None
        group.removeChild(item)
        self._regroup()
        self._changed()

    # ── 반응 ──

    def _type_pinned(self, item: QTreeWidgetItem) -> bool:
        source = self.tree.itemWidget(item, SOURCE)
        return isinstance(source, QComboBox) and str(source.currentData()) in INPUT_SOURCE_TYPES

    def _match_type(self, source: QComboBox, kind: QComboBox) -> None:
        """출처가 가상 직원이면 **그 출처의 타입으로 맞추고 잠근다** (B8과 같은 표)."""
        wanted = INPUT_SOURCE_TYPES.get(str(source.currentData() or INPUT_SOURCE_CALLER))
        if wanted is not None:
            kind.setCurrentText(wanted)
        kind.setEnabled(wanted is None and not self.locked)

    def _source_changed(self, source: QComboBox, kind: QComboBox) -> None:
        self._match_type(source, kind)
        self._changed()

    def _changed(self) -> None:
        if self._quiet:
            return
        self._regroup()
        found = problem(self.input_rows(), self.output_names()) if self.unapplied else ""
        self._say_error(found)
        self._refresh_buttons()

    def _say_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))

    def _refresh_buttons(self) -> None:
        editable = not self.locked and self.info is not None
        self.add_input.setEnabled(editable)
        self.add_output.setEnabled(editable)
        current = self.tree.currentItem()
        self.drop_row.setEnabled(
            editable and current is not None and current.parent() in (self.inputs_group, self.outputs_group)
        )
        self.apply_button.setEnabled(editable and self.unapplied and not self.error.text())


__all__ = [
    "COLUMNS",
    "GROUP_INPUTS",
    "GROUP_MADE",
    "GROUP_OTHER",
    "GROUP_OUTPUTS",
    "NOTE_EDITABLE",
    "NO_PROCESS",
    "RUNNING",
    "VariablesTab",
]

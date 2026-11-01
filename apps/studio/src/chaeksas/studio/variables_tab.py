"""STU-01 아래 탭 「변수」 — 입력·출력 **정의**를 고치고, 시험 실행 중에는 **지금 값**을 보인다.

무리가 넷이고 **작은 탭으로 한 번에 하나만** 보인다: 「입력」·「출력」(고친다), 「그림이 만드는
변수」(읽기 전용, 찾기 칸), 「그 밖의 값」(값이 있을 때만). 읽기 전용 목록이 고치는 줄을 밀어내지
않게 하려는 것이다. 칸은 **글자로 보이고 누르면 그 자리에서 고친다** (`_Edits`). 값 다루기는
`variables.py`(Qt 없음)에 있다.

**이 탭은 그림을 만지지 않는다** — 「적용」은 `bpm:process` 본문을 `applying`으로 올리고 캔버스를
쥔 메인 창이 넘긴다 (ADR-0022 — 실행 취소가 한 걸음). 그림을 읽는 것도 메인 창이다
(`show_definition`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import INPUT_SOURCE_CALLER, INPUT_SOURCE_TYPES, InputDecl, ProcessInfo
from chaeksas.qt.theme import icon, set_role
from chaeksas.qt.theme.tokens import SIZE_ROW_COMPACT, SPACE_1, SPACE_2
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

#: 열 자리는 모든 표가 같다 — 표마다 쓰지 않는 열을 감추고 머리글만 바꾼다.
COLUMNS = ("이름", "타입", "필수", "기본값", "값 출처", "설명", "지금 값")
NAME, TYPE, REQUIRED, DEFAULT, SOURCE, DESCRIPTION, NOW = range(len(COLUMNS))
#: 「그림이 만드는 변수」 표에서 `SOURCE` 자리의 머리글.
MADE_BY = "만드는 곳"

GROUP_INPUTS = "입력"
GROUP_OUTPUTS = "출력"
GROUP_MADE = "그림이 만드는 변수"
GROUP_OTHER = "그 밖의 값"
#: 작은 탭의 차례.
INPUTS, OUTPUTS, MADE, OTHER = range(4)

NOTE_EDITABLE = "적용하면 그림에 들어갑니다 — 「저장」(Ctrl+S)으로 파일에 씁니다."
NO_PROCESS = "열린 BPM 프로세스가 없습니다."
RUNNING = "시험 실행 중에는 고칠 수 없습니다."
SOURCE_TIP = "회사·부서·직원 출처는 Center가 업무 자리에서 넣습니다 — 부르는 쪽(작업 지시·메시지)은 줄 수 없습니다."
PINNED_TIP = "값 출처가 업무 자리이면 타입은 그 출처의 것입니다."
MADE_TIP = "노드를 지나면 생기는 변수 — 노드 속성에서 고칩니다."
FIND_HINT = "이름·만드는 곳으로 찾기"
#: 누르면 콤보가 뜨는 칸이라는 표시 (STU-01 「변수」 탭 [T]).
COMBO_MARK = "▾"

#: 입력 줄에서 글로 고치는 열 (타입·값 출처는 콤보, 필수는 체크다).
INPUT_TEXT_COLUMNS = (NAME, DEFAULT, DESCRIPTION)
#: 줄에 붙여 두는 읽어 온 그 입력 — 표가 모르는 칸을 그 줄에 남긴다.
ORIGINAL = Qt.ItemDataRole.UserRole
#: 값 출처 칸의 **값** (글자는 사람에게 보이는 이름이다).
SOURCE_VALUE = Qt.ItemDataRole.UserRole + 1


def _children(group: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    return [found for at in range(group.childCount()) if (found := group.child(at)) is not None]


def _source_label(value: str) -> str:
    return next((label for found, label in INPUT_SOURCES if found == value), value)


class _Rows(QStyledItemDelegate):
    """줄 높이는 스타일 가이드의 표 줄(`row.compact`)이다 — 글자 높이만큼 붙으면 줄이 비좁다."""

    def sizeHint(  # noqa: N802 — Qt 이름 그대로
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        found = super().sizeHint(option, index)
        return QSize(found.width(), max(found.height(), SIZE_ROW_COMPACT))


class _Edits(_Rows):
    """**고칠 수 있는 칸만** 그 자리에서 편집기를 연다 — 평소에는 글자로 그린다.

    타입·값 출처는 콤보, 이름·기본값·설명은 입력란이다. 콤보 칸에는 ▾를 그려 「눌러서 고른다」를 알린다.
    """

    def __init__(self, tab: VariablesTab) -> None:
        super().__init__(tab)
        self.tab = tab

    def _item(self, index: QModelIndex | QPersistentModelIndex) -> QTreeWidgetItem | None:
        if not isinstance(index, QModelIndex):
            index = index.model().index(index.row(), index.column(), index.parent())
        for tree in (self.tab.inputs_tree, self.tab.outputs_tree):
            if index.model() is tree.model():
                return tree.itemFromIndex(index)
        return None

    def _combo_column(self, item: QTreeWidgetItem, column: int) -> bool:
        if item.treeWidget() is not self.tab.inputs_tree or self.tab.locked:
            return False
        return column == SOURCE or (column == TYPE and not self.tab.type_pinned(item))

    def createEditor(  # noqa: N802 — Qt 이름 그대로
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        item = self._item(index)
        if self.tab.locked or item is None:
            return None  # type: ignore[return-value]  # 칸을 열지 않는다
        column = index.column()
        if item.treeWidget() is self.tab.outputs_tree:
            return QLineEdit(parent) if column == NAME else None  # type: ignore[return-value]
        if column in INPUT_TEXT_COLUMNS:
            return QLineEdit(parent)
        if not self._combo_column(item, column):
            return None  # type: ignore[return-value]
        combo = QComboBox(parent)
        if column == TYPE:
            combo.addItems(list(INPUT_TYPES))
            if item.text(TYPE) not in INPUT_TYPES:
                combo.addItem(item.text(TYPE))  # 모르는 타입도 그대로 보인다 (B8이 말한다)
        else:
            combo.setToolTip(SOURCE_TIP)
            for value, label in INPUT_SOURCES:
                combo.addItem(label, value)
            current = str(item.data(SOURCE, SOURCE_VALUE))
            if combo.findData(current) < 0:
                combo.addItem(current, current)  # 모르는 출처는 글자 그대로 둔다
        # 고르면 바로 들어간다 — 칸을 벗어나야 들어가면 「적용」이 늦게 켜진다.
        combo.activated.connect(lambda _at, c=combo: self.commitData.emit(c))
        return combo

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:  # noqa: N802
        item = self._item(index)
        if isinstance(editor, QComboBox) and item is not None:
            if index.column() == TYPE:
                editor.setCurrentText(item.text(TYPE))
            else:
                editor.setCurrentIndex(editor.findData(str(item.data(SOURCE, SOURCE_VALUE))))
            editor.showPopup()
            return
        super().setEditorData(editor, index)

    def setModelData(  # noqa: N802 — Qt 이름 그대로
        self,
        editor: QWidget,
        model: QAbstractItemModel,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        item = self._item(index)
        if isinstance(editor, QComboBox) and item is not None:
            if index.column() == TYPE:
                item.setText(TYPE, editor.currentText())
            else:
                self.tab.set_source(item, str(editor.currentData()))
            return
        super().setModelData(editor, model, index)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        item = self._item(index)
        if item is None or not self._combo_column(item, index.column()):
            return
        painter.save()
        painter.setPen(option.palette.color(QPalette.ColorRole.PlaceholderText))
        rect = option.rect.adjusted(0, 0, -SPACE_2, 0)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), COMBO_MARK)
        painter.restore()


class VariablesTab(QWidget):
    """「변수」 탭. 메인 창이 `show_definition`·`show_values`로 채우고 `applying`을 받는다."""

    #: 「적용」 — 캔버스에 넘길 `bpm:process` 본문(JSON 글).
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

        self.sections = QTabBar(self)
        self.sections.setDrawBase(False)
        self.sections.setExpanding(False)
        self.sections.setUsesScrollButtons(False)  # 넷이 늘 다 보인다 — 화살표로 숨기지 않는다
        for title in (GROUP_INPUTS, GROUP_OUTPUTS, GROUP_MADE, GROUP_OTHER):
            self.sections.addTab(title)

        self.add_input = QPushButton("입력 더하기", self)
        self.add_output = QPushButton("출력 더하기", self)
        self.drop_row = QPushButton("줄 삭제", self)
        for button in (self.add_input, self.add_output, self.drop_row):
            button.setObjectName("Secondary")  # 강조색은 「적용」 하나다
        self.apply_button = QPushButton("적용", self)

        edits = _Edits(self)
        self.inputs_tree = self._tree(
            {TYPE: COLUMNS[TYPE], REQUIRED: COLUMNS[REQUIRED], DEFAULT: COLUMNS[DEFAULT],
             SOURCE: COLUMNS[SOURCE], DESCRIPTION: COLUMNS[DESCRIPTION]},
            widths={NAME: 180, TYPE: 110, REQUIRED: 48, DEFAULT: 140, SOURCE: 170},
            stretch=DESCRIPTION,
        )
        self.outputs_tree = self._tree({}, widths={}, stretch=NAME)
        self.made_tree = self._tree({SOURCE: MADE_BY}, widths={NAME: 240}, stretch=SOURCE)
        self.other_tree = self._tree({}, widths={NAME: 240}, stretch=NOW)
        for tree in (self.inputs_tree, self.outputs_tree):
            tree.setItemDelegate(edits)
            tree.setEditTriggers(
                QAbstractItemView.EditTrigger.CurrentChanged
                | QAbstractItemView.EditTrigger.SelectedClicked
                | QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed
            )
        self.inputs_group = self.inputs_tree.invisibleRootItem()
        self.outputs_group = self.outputs_tree.invisibleRootItem()
        self.made_group = self.made_tree.invisibleRootItem()
        self.other_group = self.other_tree.invisibleRootItem()

        self.find_box = QLineEdit(self)
        self.find_box.setPlaceholderText(FIND_HINT)
        self.find_box.setClearButtonEnabled(True)
        made_page = QWidget(self)
        made_layout = QVBoxLayout(made_page)
        made_layout.setContentsMargins(0, 0, 0, 0)
        made_layout.setSpacing(SPACE_2)
        made_layout.addWidget(self.find_box)
        made_layout.addWidget(self.made_tree, 1)
        self.stack = QStackedWidget(self)
        for page in (self.inputs_tree, self.outputs_tree, made_page, self.other_tree):
            self.stack.addWidget(page)

        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")
        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        set_role(self.error, "error")
        self.error.hide()

        top = QHBoxLayout()
        top.addWidget(self.sections, 0, Qt.AlignmentFlag.AlignBottom)  # 탭이 아래 선 위에 앉는다
        top.addStretch(1)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, SPACE_1)  # 단추는 선에 닿지 않는다
        buttons.addWidget(self.add_input)
        buttons.addWidget(self.add_output)
        buttons.addWidget(self.drop_row)
        buttons.addSpacing(SPACE_2)
        buttons.addWidget(self.apply_button)
        top.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)
        layout.setSpacing(SPACE_2)
        rule = QFrame(self)
        rule.setObjectName("Rule")  # 무리 탭과 표를 가르는 선 (STU-01)
        head = QVBoxLayout()
        head.setSpacing(0)
        head.addLayout(top)
        head.addWidget(rule)
        layout.addLayout(head)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.note)
        layout.addWidget(self.error)

        self.sections.currentChanged.connect(self._section_changed)
        self.add_input.clicked.connect(lambda: self._new_input())
        self.add_output.clicked.connect(lambda: self._new_output())
        self.drop_row.clicked.connect(self._drop)
        self.apply_button.clicked.connect(self.apply)
        self.find_box.textChanged.connect(lambda _text: self._filter_made())
        for tree in (self.inputs_tree, self.outputs_tree):
            tree.itemChanged.connect(lambda *_: self._changed())
            tree.currentItemChanged.connect(lambda *_: self._refresh_buttons())
        self._paint_icons()
        self._regroup()
        self._section_changed(INPUTS)

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
            flags = item.flags()
            checkable = Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags & ~checkable if locked else flags | checkable)
        if self.values is not None and locked:
            self.note.setText(caption(self.values))
        else:
            self.note.setText(self._reason or NOTE_EDITABLE)
        self.inputs_tree.viewport().update()  # ▾는 고칠 수 있을 때만 그린다
        self._refresh_buttons()

    def set_source(self, item: QTreeWidgetItem, value: str) -> None:
        """입력 줄의 값 출처를 바꾼다. Center가 넣는 출처이면 **그 출처의 타입으로 맞춘다** (B8과 같은 표)."""
        item.setData(SOURCE, SOURCE_VALUE, value)
        item.setText(SOURCE, _source_label(value))
        item.setToolTip(SOURCE, SOURCE_TIP)
        wanted = INPUT_SOURCE_TYPES.get(value or INPUT_SOURCE_CALLER)
        if wanted is not None:
            item.setText(TYPE, wanted)
        item.setToolTip(TYPE, PINNED_TIP if wanted is not None else "")

    def type_pinned(self, item: QTreeWidgetItem) -> bool:
        return str(item.data(SOURCE, SOURCE_VALUE)) in INPUT_SOURCE_TYPES

    # ── 읽기 ──

    def input_rows(self) -> list[InputRow]:
        return [
            InputRow(
                name=item.text(NAME),
                type=item.text(TYPE),
                required=item.checkState(REQUIRED) == Qt.CheckState.Checked,
                default=item.text(DEFAULT),
                source=str(item.data(SOURCE, SOURCE_VALUE)),
                description=item.text(DESCRIPTION),
                original=item.data(NAME, ORIGINAL),
            )
            for item in _children(self.inputs_group)
        ]

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

    def _tree(self, headers: dict[int, str], *, widths: dict[int, int], stretch: int) -> QTreeWidget:
        """무리 하나의 표. `headers`에 없는 열(이름·지금 값 말고)은 감춘다."""
        tree = QTreeWidget(self)
        tree.setColumnCount(len(COLUMNS))
        labels = list(COLUMNS)
        for column, label in headers.items():
            labels[column] = label
        tree.setHeaderLabels(labels)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setItemDelegate(_Rows(tree))
        tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for column in range(len(COLUMNS)):
            tree.setColumnHidden(column, column not in (NAME, NOW, *headers))
        header = tree.header()
        header.setStretchLastSection(False)
        for column, width in widths.items():
            tree.setColumnWidth(column, width)
        tree.setColumnWidth(NOW, 240)
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
        return tree

    def _regroup(self) -> None:
        """작은 탭 이름에 줄 수를 붙이고, 「그 밖의 값」은 값이 있을 때만 보인다."""
        for at, (group, title) in enumerate(
            (
                (self.inputs_group, GROUP_INPUTS),
                (self.outputs_group, GROUP_OUTPUTS),
                (self.made_group, GROUP_MADE),
                (self.other_group, GROUP_OTHER),
            )
        ):
            self.sections.setTabText(at, f"{title} ({group.childCount()})")
        has_other = self.other_group.childCount() > 0
        self.sections.setTabVisible(OTHER, has_other)
        if not has_other and self.sections.currentIndex() == OTHER:
            self.sections.setCurrentIndex(INPUTS)
        for tree in (self.inputs_tree, self.outputs_tree, self.made_tree):
            tree.setColumnHidden(NOW, self.values is None)

    def _fill_definitions(self, info: ProcessInfo | None) -> None:
        self.inputs_tree.clear()
        self.outputs_tree.clear()
        if info is not None:
            for decl in info.inputs:
                self._input_item(InputRow.of(decl), decl)
            for name in info.outputs:
                self._output_item(name)
        self._regroup()

    def _fill_made(self) -> None:
        self.made_tree.clear()
        declared = {decl.name for decl in self.info.inputs} | set(self.info.outputs) if self.info else set()
        for name in sorted(self.made):
            if name in declared:
                continue  # 입력·출력에 이미 있는 이름은 다시 적지 않는다
            item = QTreeWidgetItem(self.made_tree)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setText(NAME, name)
            item.setText(SOURCE, ", ".join(self.made[name]))
            item.setToolTip(NAME, f"{name} — {MADE_TIP}")
            item.setToolTip(SOURCE, item.text(SOURCE))  # 잘린 칸은 툴팁이 전체를 보인다
        self._filter_made()
        self._regroup()

    def _filter_made(self) -> None:
        needle = self.find_box.text().strip().casefold()
        for item in _children(self.made_group):
            haystack = f"{item.text(NAME)} {item.text(SOURCE)}".casefold()
            item.setHidden(bool(needle) and needle not in haystack)

    def _fill_values(self) -> None:
        self.other_tree.clear()
        values = self.values
        shown: set[str] = set()
        for group in (self.inputs_group, self.outputs_group, self.made_group):
            for item in _children(group):
                name = item.text(NAME)
                shown.add(name)
                text = "" if values is None else value_text(values[name]) if name in values else NONE
                item.setText(NOW, text)
                item.setToolTip(NOW, text)
        for name in sorted(values or {}):
            if name in shown:
                continue
            item = QTreeWidgetItem(self.other_tree)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setText(NAME, name)
            item.setText(NOW, value_text((values or {})[name]))
            item.setToolTip(NOW, item.text(NOW))
        self._regroup()

    def _input_item(self, row: InputRow, decl: InputDecl | None = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.inputs_tree)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        item.setText(NAME, row.name)
        item.setData(NAME, ORIGINAL, decl)
        item.setText(TYPE, row.type)
        item.setCheckState(REQUIRED, Qt.CheckState.Checked if row.required else Qt.CheckState.Unchecked)
        item.setText(DEFAULT, row.default)
        item.setText(DESCRIPTION, row.description)
        item.setToolTip(DESCRIPTION, row.description)
        self.set_source(item, row.source)
        return item

    def _output_item(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.outputs_tree)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable)
        item.setText(NAME, name)
        return item

    def _new_input(self) -> None:
        if self.locked:
            return
        self.sections.setCurrentIndex(INPUTS)
        self._quiet = True
        item = self._input_item(InputRow(name=""))
        self._fill_values()
        self._quiet = False
        self._changed()
        self.inputs_tree.setCurrentItem(item, NAME)
        self.inputs_tree.editItem(item, NAME)

    def _new_output(self) -> None:
        if self.locked:
            return
        self.sections.setCurrentIndex(OUTPUTS)
        self._quiet = True
        item = self._output_item("")
        self._fill_values()
        self._quiet = False
        self._changed()
        self.outputs_tree.setCurrentItem(item, NAME)
        self.outputs_tree.editItem(item, NAME)

    def _drop(self) -> None:
        tree = self._editable_tree()
        item = tree.currentItem() if tree is not None else None
        if self.locked or tree is None or item is None:
            return
        tree.invisibleRootItem().removeChild(item)
        self._regroup()
        self._changed()

    # ── 반응 ──

    def _editable_tree(self) -> QTreeWidget | None:
        """지금 보이는 무리가 고치는 무리면 그 표."""
        return {INPUTS: self.inputs_tree, OUTPUTS: self.outputs_tree}.get(self.sections.currentIndex())

    def _section_changed(self, at: int) -> None:
        self.stack.setCurrentIndex(at)
        # 단추는 보이는 무리에 맞는 것만 — 읽기 전용 무리에서는 더하기·삭제가 없다.
        self.add_input.setVisible(at == INPUTS)
        self.add_output.setVisible(at == OUTPUTS)
        self.drop_row.setVisible(at in (INPUTS, OUTPUTS))
        self._refresh_buttons()

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
        tree = self._editable_tree()
        self.drop_row.setEnabled(editable and tree is not None and tree.currentItem() is not None)
        self.apply_button.setEnabled(editable and self.unapplied and not self.error.text())

    def _paint_icons(self) -> None:
        """보조 단추 아이콘을 지금 팔레트의 글자색으로 칠한다 (테마가 바뀌면 다시 — `changeEvent`)."""
        color = self.palette().color(QPalette.ColorRole.ButtonText).name()
        self.add_input.setIcon(icon("plus", color))
        self.add_output.setIcon(icon("plus", color))
        self.drop_row.setIcon(icon("trash", color))

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt 이름 그대로
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            if hasattr(self, "drop_row"):  # 짓는 도중에도 올 수 있다
                self._paint_icons()
        super().changeEvent(event)


__all__ = [
    "COLUMNS",
    "GROUP_INPUTS",
    "GROUP_MADE",
    "GROUP_OTHER",
    "GROUP_OUTPUTS",
    "INPUTS",
    "MADE",
    "NOTE_EDITABLE",
    "NO_PROCESS",
    "OTHER",
    "OUTPUTS",
    "RUNNING",
    "VariablesTab",
]

"""STU-04a 결정표 — 규칙 태스크가 쓰는 `.dmn` 결정표 하나를 격자로 고친다 (ADR-0109).

STU-04 「규칙」 탭의 「결정표 편집...」·「새 결정표...」가 연다. **「저장」이 그 자리에서 `.dmn`을 쓴다** —
캔버스의 실행 취소·「저장 안 한 변경」과 따로다(`.dmn`은 bpmn-js 캔버스에 실리지 않는다).

- 칸은 **적힌 글 그대로** 고치고, 틀린 칸은 그 자리에서 빨갛게 한다 — 검사는 `contracts.dmn`과 같은 함수다
  (`dmn_table.cell_problem`). 마지막 관문은 지어 쓴 파일을 다시 읽는가다.
- **받은 결정표**(`libs/`)는 읽기 전용이다 (ADR-0048). **있는 결정의 ID는 바꾸지 않는다** — 다른 규칙 태스크가
  id로 가리킨다.
- 쓰는 것은 그 결정표 하나다 — 같은 파일의 다른 결정·모르는 요소는 `write_table`이 남긴다.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.qt.messages import ask_unsaved
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_3
from chaeksas.studio.dmn_table import (
    CELL_HELP,
    HITS,
    TYPES,
    VALUE_HELP,
    Table,
    cell_problem,
    problems,
    write_table,
)

TITLE = "결정표"
READ_ONLY_NOTE = (
    "받아 둔 공유 BPM 프로세스의 결정표입니다 — 고치지 않습니다. 같은 id로 내 결정표를 만들면 내 것이 이깁니다."
)
ID_LOCKED = "다른 규칙 태스크가 이 ID로 결정을 가리킵니다 — ID는 「새 결정표...」에서만 적습니다."
DESCRIPTION = "설명"
FILE_EXISTS = "파일이 이미 있습니다: {name} — 다른 ID를 적으세요."


def _type_label(type_ref: str) -> str:
    return type_ref or "(없음)"


def _input_header(label: str, expression: str, type_ref: str) -> str:
    """「라벨 (식 이름) · typeRef」 — 라벨이 식 이름과 같거나 없으면 한 번."""
    shown = label or expression or "?"
    if label and expression and label != expression:
        shown += f" ({expression})"
    return f"{shown} · {_type_label(type_ref)}"


class ColumnDialog(QDialog):
    """「열 고치기...」 — 입력은 라벨·식 이름·typeRef, 출력은 이름·typeRef."""

    def __init__(self, parent: QWidget | None, *, output: bool, values: dict[str, str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("출력 열" if output else "입력 열")
        self.output = output
        self.label_box = QLineEdit(values.get("label", ""), self)
        self.label_box.setPlaceholderText("사람이 읽는 이름 (비우면 식 이름)")
        self.name_box = QLineEdit(values.get("name", ""), self)
        self.name_box.setPlaceholderText(
            "판정 결과의 이름 (필수)" if output else "규칙 태스크가 값을 넘기는 이름 (필수 — inputExpression)"
        )
        self.type_box = QComboBox(self)
        for value, text in TYPES:
            self.type_box.addItem(text, value)
        current = values.get("type", "")
        index = self.type_box.findData(current)
        if index < 0:
            # 그림에 적힌 낯선 값은 그대로 보인다 (조용히 바꾸지 않는다).
            self.type_box.addItem(current, current)
            index = self.type_box.count() - 1
        self.type_box.setCurrentIndex(index)

        form = QFormLayout()
        if not output:
            form.addRow("라벨", self.label_box)
            form.addRow("식 이름", self.name_box)
        else:
            self.label_box.hide()
            form.addRow("이름", self.name_box)
        form.addRow("typeRef", self.type_box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        return {
            "label": self.label_box.text().strip(),
            "name": self.name_box.text().strip(),
            "type": str(self.type_box.currentData() or ""),
        }


class DecisionDialog(QDialog):
    """결정표 하나. `path`가 없으면 새 결정표이고 `process/<id>.dmn`에 쓴다."""

    #: 저장했다 — 결정 id. 「규칙」 탭이 다시 읽는다.
    saved = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        table: Table,
        path: Path | None = None,
        process_dir: Path | None = None,
        read_only: bool = False,
        taken: Iterable[str] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.resize(900, 520)
        self.path = path
        self.process_dir = process_dir
        self.read_only = read_only
        self.new = path is None
        self.taken = set(taken)
        self.original_id = None if self.new else table.id
        self.table = table.copy()
        self._saved_copy = table.copy()
        self._quiet = False

        self.read_only_note = QLabel(READ_ONLY_NOTE, self)
        self.read_only_note.setWordWrap(True)
        set_role(self.read_only_note, "muted")
        self.read_only_note.setVisible(read_only)

        self.id_box = QLineEdit(self.table.id, self)
        self.id_box.setPlaceholderText("결정 ID (필수)")
        if not self.new:
            self.id_box.setReadOnly(True)
            self.id_box.setToolTip(ID_LOCKED)
        self.name_box = QLineEdit(self.table.name, self)
        self.name_box.setPlaceholderText("이름")
        self.hit_box = QComboBox(self)
        for value, meaning in HITS:
            self.hit_box.addItem(value, value)
            self.hit_box.setItemData(self.hit_box.count() - 1, meaning, Qt.ItemDataRole.ToolTipRole)
        if self.hit_box.findData(self.table.hit) < 0:
            self.hit_box.addItem(self.table.hit, self.table.hit)  # C14 밖 — 보이고 「저장」을 막는다
        self.hit_box.setCurrentIndex(self.hit_box.findData(self.table.hit))

        head = QHBoxLayout()
        head.addWidget(QLabel("ID", self))
        head.addWidget(self.id_box, 1)
        head.addWidget(QLabel("이름", self))
        head.addWidget(self.name_box, 2)
        head.addWidget(QLabel("적중 정책", self))
        head.addWidget(self.hit_box)

        self.grid = QTableWidget(self)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.add_input_button = QPushButton("입력 열 더하기", self)
        self.add_output_button = QPushButton("출력 열 더하기", self)
        self.edit_column_button = QPushButton("열 고치기...", self)
        self.drop_column_button = QPushButton("열 삭제", self)
        self.add_rule_button = QPushButton("규칙 더하기", self)
        self.drop_rule_button = QPushButton("규칙 삭제", self)
        self.up_button = QPushButton("위로", self)
        self.down_button = QPushButton("아래로", self)
        for one in (
            self.add_input_button,
            self.add_output_button,
            self.edit_column_button,
            self.drop_column_button,
            self.add_rule_button,
            self.drop_rule_button,
            self.up_button,
            self.down_button,
        ):
            one.setObjectName("Secondary")
        tools = QHBoxLayout()
        for one in (self.add_input_button, self.add_output_button, self.edit_column_button, self.drop_column_button):
            tools.addWidget(one)
        tools.addStretch(1)
        for one in (self.add_rule_button, self.drop_rule_button, self.up_button, self.down_button):
            tools.addWidget(one)

        self.problem_label = QLabel("", self)
        self.problem_label.setWordWrap(True)
        set_role(self.problem_label, "error")
        self.warning_label = QLabel("", self)
        self.warning_label.setWordWrap(True)
        set_role(self.warning_label, "muted")

        self.save_button = QPushButton("저장", self)
        self.close_button = QPushButton("닫기", self)
        self.close_button.setObjectName("Secondary")
        self.save_button.setVisible(not read_only)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.save_button)
        bottom.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(self.read_only_note)
        layout.addLayout(head)
        layout.addWidget(self.grid, 1)
        layout.addLayout(tools)
        layout.addWidget(self.problem_label)
        layout.addWidget(self.warning_label)
        layout.addLayout(bottom)

        self.id_box.textChanged.connect(self._head_changed)
        self.name_box.textChanged.connect(self._head_changed)
        self.hit_box.currentIndexChanged.connect(self._head_changed)
        self.grid.itemChanged.connect(self._cell_changed)
        self.grid.currentCellChanged.connect(lambda *_: self._refresh_buttons())
        self.add_input_button.clicked.connect(self.add_input)
        self.add_output_button.clicked.connect(self.add_output)
        self.edit_column_button.clicked.connect(self._ask_column)
        self.drop_column_button.clicked.connect(self.drop_column)
        self.add_rule_button.clicked.connect(self.add_rule)
        self.drop_rule_button.clicked.connect(self.drop_rule)
        self.up_button.clicked.connect(lambda: self.move_rule(-1))
        self.down_button.clicked.connect(lambda: self.move_rule(1))
        self.save_button.clicked.connect(self.save)
        self.close_button.clicked.connect(self.reject)

        if read_only:
            for box in (self.name_box, self.id_box):
                box.setReadOnly(True)
            self.hit_box.setEnabled(False)
            self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rebuild()

    # ── 격자 ──

    def _columns(self) -> int:
        return len(self.table.inputs) + len(self.table.outputs) + 1

    def _rebuild(self) -> None:
        self._quiet = True
        try:
            table = self.table
            self.grid.clear()
            self.grid.setColumnCount(self._columns())
            self.grid.setRowCount(len(table.rules))
            headers = [_input_header(c.label, c.expression, c.type) for c in table.inputs]
            headers += [f"→ {o.name or '?'} · {_type_label(o.type)}" for o in table.outputs]
            headers.append(DESCRIPTION)
            self.grid.setHorizontalHeaderLabels(headers)
            width = len(table.inputs)
            for r, row in enumerate(table.rules):
                for c, text in enumerate(row.cells):
                    self.grid.setItem(r, c, QTableWidgetItem(text))
                for c, text in enumerate(row.values):
                    self.grid.setItem(r, width + c, QTableWidgetItem(text))
                self.grid.setItem(r, self._columns() - 1, QTableWidgetItem(row.description))
            for r in range(len(table.rules)):
                for c in range(self._columns() - 1):
                    self._mark(r, c)
        finally:
            self._quiet = False
        self._refresh()

    def _mark(self, row: int, column: int) -> None:
        """틀린 칸은 빨갛게 — 색은 팔레트의 오류색이다 (STU-14와 같은 방식, 값을 적지 않는다)."""
        item = self.grid.item(row, column)
        if item is None:
            return
        output = column >= len(self.table.inputs)
        found = cell_problem(item.text(), output=output)
        if found:
            item.setForeground(self.grid.palette().brush(QPalette.ColorRole.BrightText))
            item.setToolTip(found)
        else:
            item.setForeground(self.grid.palette().brush(QPalette.ColorRole.Text))
            item.setToolTip(VALUE_HELP if output else CELL_HELP)

    def _cell_changed(self, item: QTableWidgetItem) -> None:
        if self._quiet:
            return
        r, c = item.row(), item.column()
        row = self.table.rules[r]
        width = len(self.table.inputs)
        if c < width:
            row.cells[c] = item.text()
        elif c < width + len(self.table.outputs):
            row.values[c - width] = item.text()
        else:
            row.description = item.text()
        if c < self._columns() - 1:
            self._quiet = True
            try:
                self._mark(r, c)
            finally:
                self._quiet = False
        self._refresh()

    def _head_changed(self, *_: Any) -> None:
        if self.new:
            self.table.id = self.id_box.text().strip()
        self.table.name = self.name_box.text().strip()
        self.table.hit = str(self.hit_box.currentData() or "")
        self._refresh()

    def set_cell(self, row: int, column: int, text: str) -> None:
        """칸 하나에 적는다 (사람이 적는 것과 같은 길 — 시험이 쓴다)."""
        item = self.grid.item(row, column)
        assert item is not None
        item.setText(text)

    # ── 열·줄 ──

    def _column_at(self) -> tuple[str, int] | None:
        """고른 칸의 열 — `("input" | "output", 열 번호)`. 설명 열이나 아무 데도 아니면 `None`."""
        column = self.grid.currentColumn()
        width = len(self.table.inputs)
        if column < 0:
            return None
        if column < width:
            return "input", column
        if column < width + len(self.table.outputs):
            return "output", column - width
        return None

    def add_input(self) -> None:
        self.table.add_input()
        self._rebuild()
        self.grid.setCurrentCell(0 if self.table.rules else -1, len(self.table.inputs) - 1)

    def add_output(self) -> None:
        self.table.add_output()
        self._rebuild()
        self.grid.setCurrentCell(0 if self.table.rules else -1, len(self.table.inputs) + len(self.table.outputs) - 1)

    def drop_column(self) -> None:
        found = self._column_at()
        if found is None:
            return
        kind, index = found
        if kind == "input":
            self.table.remove_input(index)
        elif len(self.table.outputs) > 1:
            self.table.remove_output(index)
        self._rebuild()

    def edit_column(self, kind: str, index: int, values: dict[str, str]) -> None:
        """열 하나를 고친다 — 「열 고치기...」 창이 돌려준 값으로 (시험이 바로 부른다)."""
        if kind == "input":
            column = self.table.inputs[index]
            column.label = values.get("label", column.label)
            column.expression = values.get("name", column.expression)
            column.type = values.get("type", column.type)
        else:
            out = self.table.outputs[index]
            out.name = values.get("name", out.name)
            out.type = values.get("type", out.type)
        self._rebuild()

    def _ask_column(self) -> None:
        found = self._column_at()
        if found is None:
            return
        kind, index = found
        if kind == "input":
            column = self.table.inputs[index]
            values = {"label": column.label, "name": column.expression, "type": column.type}
        else:
            out = self.table.outputs[index]
            values = {"name": out.name, "type": out.type}
        asked = ColumnDialog(self, output=kind == "output", values=values)
        if asked.exec() == QDialog.DialogCode.Accepted:
            self.edit_column(kind, index, asked.values())

    def add_rule(self) -> None:
        current = self.grid.currentRow()
        at = current + 1 if current >= 0 else len(self.table.rules)
        self.table.add_rule(at)
        self._rebuild()
        self.grid.setCurrentCell(at, 0)

    def drop_rule(self) -> None:
        current = self.grid.currentRow()
        if 0 <= current < len(self.table.rules):
            del self.table.rules[current]
            self._rebuild()

    def move_rule(self, step: int) -> None:
        current = self.grid.currentRow()
        target = current + step
        if not (0 <= current < len(self.table.rules)) or not (0 <= target < len(self.table.rules)):
            return
        rules = self.table.rules
        rules[current], rules[target] = rules[target], rules[current]
        column = self.grid.currentColumn()
        self._rebuild()
        self.grid.setCurrentCell(target, max(column, 0))

    # ── 상태 ──

    def problems(self) -> tuple[list[str], list[str]]:
        errors, warnings = problems(self.table, taken=self.taken if self.new else ())
        if self.new and not errors and self.process_dir is not None:
            if (self.process_dir / f"{self.table.id}.dmn").exists():
                errors.append(FILE_EXISTS.format(name=f"{self.table.id}.dmn"))
        return errors, warnings

    def unsaved(self) -> bool:
        return not self.read_only and self.table != self._saved_copy

    def _refresh(self) -> None:
        errors, warnings = self.problems()
        self.problem_label.setText("\n".join(errors[:5]) + (" …" if len(errors) > 5 else ""))
        self.problem_label.setVisible(bool(errors))
        self.warning_label.setText("\n".join(warnings[:5]) + (" …" if len(warnings) > 5 else ""))
        self.warning_label.setVisible(bool(warnings))
        self.save_button.setEnabled(not self.read_only and not errors and (self.new or self.unsaved()))
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        editable = not self.read_only
        found = self._column_at()
        has_row = 0 <= self.grid.currentRow() < len(self.table.rules)
        self.add_input_button.setEnabled(editable)
        self.add_output_button.setEnabled(editable)
        self.add_rule_button.setEnabled(editable)
        self.edit_column_button.setEnabled(editable and found is not None)
        self.drop_column_button.setEnabled(
            editable and found is not None and (found[0] == "input" or len(self.table.outputs) > 1)
        )
        self.drop_rule_button.setEnabled(editable and has_row)
        self.up_button.setEnabled(editable and has_row and self.grid.currentRow() > 0)
        self.down_button.setEnabled(editable and has_row and self.grid.currentRow() < len(self.table.rules) - 1)

    # ── 저장·닫기 ──

    def target(self) -> Path | None:
        if self.path is not None:
            return self.path
        if self.process_dir is None or not self.table.id:
            return None
        return self.process_dir / f"{self.table.id}.dmn"

    def save(self) -> bool:
        """`.dmn`을 그 자리에서 쓴다. 창을 닫지 않는다."""
        if self.read_only:
            return False
        errors, _ = self.problems()
        path = self.target()
        if errors or path is None:
            self._refresh()
            return False
        # 쓰기 직전에 다시 읽는다 — 그 사이 같은 파일의 다른 결정이 바뀌었어도 남는다.
        source = path.read_text(encoding="utf-8") if path.exists() else None
        made = write_table(source, self.table, original_id=self.original_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(made, encoding="utf-8")
        self.path = path
        self.new = False
        self.original_id = self.table.id
        self.id_box.setReadOnly(True)
        self.id_box.setToolTip(ID_LOCKED)
        self._saved_copy = self.table.copy()
        self._refresh()
        self.saved.emit(self.table.id)
        return True

    def reject(self) -> None:
        """「닫기」 — 저장하지 않은 편집이 있으면 묻는다 (STU-07과 같은 물음)."""
        if self.unsaved():
            answer = ask_unsaved(self, "저장하지 않은 변경사항", "결정표에 저장하지 않은 변경이 있습니다.")
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self.save():
                return
        super().reject()


__all__ = ["DESCRIPTION", "FILE_EXISTS", "ID_LOCKED", "READ_ONLY_NOTE", "TITLE", "ColumnDialog", "DecisionDialog"]

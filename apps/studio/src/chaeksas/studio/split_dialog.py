"""STU-06a 「PC BPM 프로세스로 나누기」 창 (ADR-0071).

**고르고 확인만 한다** — 그림을 바꾸는 일은 `split_actions.split()`이 캔버스로 한다. 창은 옮길 노드·
새 PC Bot의 id·이름과 입력·출력 이름을 받아 `Plan` 하나를 돌려준다.

미리 채우는 것은 **플랫폼이 세는 이름뿐**이다 (`split_actions.suggested`). 확장·AI 태스크는 다 알지
못하므로 그렇게 말하고 사람이 적게 둔다 — 이름을 지어내지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import VALUE_TYPES, BpmnProcess
from chaeksas.studio.split_actions import (
    DEFAULT_TYPE,
    UNKNOWN_HINT,
    Blocker,
    Plan,
    default_pc_id,
    problems,
    suggested,
)

#: 타입 콤보의 순서 — 흔한 것부터 (C14 값 타입).
TYPE_ORDER = ("string", "number", "int", "bool", "date", "list", "dict")


class SplitDialog(QDialog):
    """STU-06a. `plan`은 「나누기」를 누르고 검사를 지났을 때만 채워진다."""

    def __init__(
        self,
        process: BpmnProcess,
        blockers: list[Blocker],
        *,
        server_id: str,
        server_name: str,
        taken: Callable[[str], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("PC BPM 프로세스로 나누기")
        self.setMinimumWidth(640)
        self._process = process
        self._taken = taken
        self.plan: Plan | None = None

        self.node_box = QComboBox(self)
        for one in blockers:
            self.node_box.addItem(one.label, one.node_id)
        self.node_box.currentIndexChanged.connect(self._fill)
        self.id_box = QLineEdit(default_pc_id(server_id), self)
        self.name_box = QLineEdit(f"{server_name} PC", self)

        self.inputs = self._table(("쓸 것", "이름", "타입"))
        self.outputs = self._table(("쓸 것", "이름"))
        add_input = QPushButton("입력 추가", self)
        add_input.clicked.connect(lambda: self._add_input("", DEFAULT_TYPE))
        add_output = QPushButton("출력 추가", self)
        add_output.clicked.connect(lambda: self._add_output(""))

        self.hint = QLabel("", self)
        self.hint.setWordWrap(True)
        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        self.error.setObjectName("splitError")

        form = QFormLayout()
        form.addRow("옮길 노드", self.node_box)
        form.addRow("새 PC Bot id", self.id_box)
        form.addRow("이름", self.name_box)

        buttons = QDialogButtonBox(self)
        self.split_button = buttons.addButton("나누기", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("입력 — PC Bot이 받는 값 (위임 호출이 같은 이름으로 넘긴다)", self))
        layout.addWidget(self.inputs)
        layout.addLayout(_right(add_input))
        layout.addWidget(QLabel("출력 — PC Bot이 돌려주는 값 (같은 이름의 변수로 돌아온다)", self))
        layout.addWidget(self.outputs)
        layout.addLayout(_right(add_output))
        layout.addWidget(self.hint)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self._fill()

    # ── 만들기 ──

    def _table(self, columns: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(columns), self)
        table.setHorizontalHeaderLabels(list(columns))
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _check(self) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(Qt.CheckState.Checked)
        return item

    def _add_input(self, name: str, kind: str) -> None:
        row = self.inputs.rowCount()
        self.inputs.insertRow(row)
        self.inputs.setItem(row, 0, self._check())
        self.inputs.setItem(row, 1, QTableWidgetItem(name))
        box = QComboBox(self.inputs)
        for one in TYPE_ORDER:
            if one in VALUE_TYPES:
                box.addItem(one)
        box.setCurrentText(kind)
        self.inputs.setCellWidget(row, 2, box)

    def _add_output(self, name: str) -> None:
        row = self.outputs.rowCount()
        self.outputs.insertRow(row)
        self.outputs.setItem(row, 0, self._check())
        self.outputs.setItem(row, 1, QTableWidgetItem(name))

    def _fill(self) -> None:
        """고른 노드가 바뀌면 **세는 이름만** 다시 채운다."""
        self.inputs.setRowCount(0)
        self.outputs.setRowCount(0)
        node_id = str(self.node_box.currentData() or "")
        reads, made, known = suggested(self._process, node_id)
        for name in reads:
            self._add_input(name, DEFAULT_TYPE)
        for name in made:
            self._add_output(name)
        self.hint.setText("" if known else UNKNOWN_HINT)
        self.split_button.setEnabled(bool(node_id))

    # ── 읽기 ──

    def current(self) -> Plan:
        inputs: list[tuple[str, str]] = []
        for row in range(self.inputs.rowCount()):
            used, name = self.inputs.item(row, 0), self.inputs.item(row, 1)
            box = self.inputs.cellWidget(row, 2)
            if used is None or used.checkState() != Qt.CheckState.Checked:
                continue
            kind = box.currentText() if isinstance(box, QComboBox) else DEFAULT_TYPE
            inputs.append(((name.text() if name else "").strip(), kind))
        outputs: list[str] = []
        for row in range(self.outputs.rowCount()):
            used, name = self.outputs.item(row, 0), self.outputs.item(row, 1)
            if used is not None and used.checkState() == Qt.CheckState.Checked:
                outputs.append((name.text() if name else "").strip())
        return Plan(
            node_id=str(self.node_box.currentData() or ""),
            pc_id=self.id_box.text().strip(),
            pc_name=self.name_box.text().strip() or self.id_box.text().strip(),
            inputs=inputs,
            outputs=outputs,
        )

    def accept(self) -> None:
        """검사에 걸리면 **창을 닫지 않는다** (STU-06·STU-10과 같은 결)."""
        found = self.current()
        wrong = problems(found, taken=self._taken)
        if wrong:
            self.error.setText(" · ".join(wrong))
            return
        self.plan = found
        super().accept()


def _right(button: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(button)
    return row


__all__ = ["TYPE_ORDER", "SplitDialog"]

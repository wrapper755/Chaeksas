"""STU-04 규칙 편집기 — 규칙 태스크의 `chk:rule` (C14 §규칙 태스크와 DMN, ADR-0109).

속성 패널이 규칙 태스크(`businessRuleTask`)를 만나면 탭으로 끼운다. **규약은 결재·STU-14와 같다**
(`load`/`dump`/`problems`/`changed`). 고치는 것은 `chk:rule` **통째로**이고 `dump()`는 본문 또는 `None`(없음)이다.

- **결정표 자체는 여기서 고치지 않는다** — 「결정표 편집...」이 STU-04a 창(`decision_dialog.py`)을 열고 그 창의
  「저장」이 `.dmn`을 바로 쓴다. 저장하면 이 탭이 결정표를 **다시 읽는다**(입력 줄·출력 고를 거리가 따라 바뀐다).
- 입력 줄은 **결정표가 정한다**(B14 — 엔진은 모든 입력을 받아야 판정한다). 그림에 있는데 결정표에 없는 입력은
  「(결정표에 없음)」으로 보이고 **식을 비우면 지운다**.
- 결정표를 모르면(열린 작업 폴더가 없다) 대조만 건너뛴다 — 모르는 것으로 막지 않는다.
- **적어 둔 것을 조용히 바꾸지 않는다.**
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import is_var_name
from chaeksas.core.expr import ExprError, parse
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.dmn_table import DecisionFile, Decisions, blank, io_names, summary
from chaeksas.studio.name_pick import NameDelegate

#: 탭 이름.
TAB_LABEL = "규칙"

NOT_IN_PACKAGE = "(패키지에 없음)"
NOT_IN_TABLE = "(결정표에 없음)"
RECEIVED = "공유"
COLLECT_NOTE = "적중 정책이 COLLECT라 출력이 목록입니다 (맞는 줄이 없으면 빈 목록)."
NO_OUTPUT = "받는 출력이 없습니다 — 판정 결과가 어디에도 남지 않습니다."
UNKNOWN_TABLES = "열린 BPM 프로세스가 없어 결정표를 모릅니다 — 결정표와 맞춰 보지 않습니다."

VISIBLE_ROWS = 3


class RuleEditor(QWidget):
    """규칙 태스크 하나."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        decisions: Callable[[], Decisions | None] = lambda: None,
        names: QStringListModel | None = None,
    ) -> None:
        super().__init__(parent)
        self.decisions_of = decisions
        self.decisions: Decisions | None = decisions()
        self._loaded: dict[str, Any] = {}
        self._had = False
        self._quiet = False

        self.decision_box = QComboBox(self)
        self.new_button = QPushButton("새 결정표...", self)
        self.new_button.setObjectName("Secondary")
        self.summary_label = QLabel("", self)
        self.summary_label.setWordWrap(True)
        set_role(self.summary_label, "muted")
        self.edit_button = QPushButton("결정표 편집...", self)
        self.edit_button.setObjectName("Secondary")
        self.collect_note = QLabel(COLLECT_NOTE, self)
        self.collect_note.setWordWrap(True)
        set_role(self.collect_note, "muted")

        self.inputs = QTableWidget(0, 2, self)
        self.inputs.setHorizontalHeaderLabels(["DMN 입력", "식"])
        self.inputs.verticalHeader().setVisible(False)
        self.inputs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        _show_rows(self.inputs, VISIBLE_ROWS)

        self.outputs = QTableWidget(0, 2, self)
        self.outputs.setHorizontalHeaderLabels(["변수", "DMN 출력"])
        self.outputs.verticalHeader().setVisible(False)
        self.outputs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.outputs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.outputs.setItemDelegateForColumn(0, NameDelegate(names, self.outputs))
        _show_rows(self.outputs, VISIBLE_ROWS)
        self.add_output_button = QPushButton("줄 더하기", self)
        self.drop_output_button = QPushButton("줄 삭제", self)
        self.drop_output_button.setObjectName("Secondary")
        self.fill_button = QPushButton("출력 채우기", self)
        self.fill_button.setObjectName("Secondary")
        self.fill_button.setToolTip("받지 않은 출력마다 같은 이름의 변수 줄을 더합니다 — 있는 줄은 덮지 않습니다.")

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        decision_group = QGroupBox("결정", self)
        decision_layout = QVBoxLayout(decision_group)
        _tight(decision_layout)
        row = QHBoxLayout()
        row.addWidget(self.decision_box, 1)
        row.addWidget(self.new_button)
        decision_layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.summary_label, 1)
        row.addWidget(self.edit_button)
        decision_layout.addLayout(row)

        input_group = QGroupBox("입력", self)
        input_layout = QVBoxLayout(input_group)
        _tight(input_layout)
        input_layout.addWidget(self.inputs)

        output_group = QGroupBox("출력", self)
        output_layout = QVBoxLayout(output_group)
        _tight(output_layout)
        output_layout.addWidget(self.collect_note)
        output_layout.addWidget(self.outputs)
        row = QHBoxLayout()
        row.addWidget(self.add_output_button)
        row.addWidget(self.drop_output_button)
        row.addWidget(self.fill_button)
        row.addStretch(1)
        output_layout.addLayout(row)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(decision_group)
        layout.addWidget(input_group)
        layout.addWidget(output_group)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

        self.decision_box.currentIndexChanged.connect(self._decision_changed)
        self.inputs.itemChanged.connect(self._touched)
        self.outputs.itemChanged.connect(self._touched)
        self.add_output_button.clicked.connect(lambda: self._add_output("", ""))
        self.drop_output_button.clicked.connect(self._drop_output)
        self.fill_button.clicked.connect(self.fill_outputs)
        self.edit_button.clicked.connect(self.open_table)
        self.new_button.clicked.connect(self.new_table)
        self._fill_decisions("")

    # ── 규약 ──

    def load(self, found: Mapping[str, Any] | None) -> None:
        """`chk:rule` 본문(없으면 `None`)을 그린다."""
        self._had = found is not None
        self._loaded = dict(found or {})
        self._quiet = True
        try:
            self._fill_decisions(str(self._loaded.get("decision") or ""))
            given = self._loaded.get("input")
            self._fill_inputs(dict(given) if isinstance(given, Mapping) else {})
            self.outputs.setRowCount(0)
            taken = self._loaded.get("output")
            for variable, output in (dict(taken) if isinstance(taken, Mapping) else {}).items():
                self._add_output(str(variable), str(output))
        finally:
            self._quiet = False
        self._refresh()

    def dump(self) -> dict[str, Any] | None:
        """`chk:rule` 본문. 그림에 없었고 아무것도 적지 않았으면 `None`."""
        decision = self.decision()
        inputs = self.input_map()
        outputs = self.output_map()
        if not self._had and not decision and not inputs and not outputs:
            return None
        return {**self._loaded, "decision": decision, "input": inputs, "output": outputs}

    def problems(self) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        if self.dump() is None:
            return errors, warnings
        decision = self.decision()
        found = self._file()
        if not decision:
            errors.append("부를 결정을 고르세요 (엔진 rule_missing).")
        elif self.decisions is not None and found is None:
            errors.append(f"DMN 결정 {decision}이 패키지에 없습니다 (B14).")
        table_inputs, table_outputs = io_names(found.table) if found is not None else (None, None)
        for name, expression in self._input_rows():
            known = table_inputs is None or name in table_inputs
            if not known and expression:
                errors.append(f"결정표에 없는 입력입니다: {name} — 식을 비우면 지웁니다 (B14).")
                continue
            if not expression:
                if known:
                    errors.append(f"입력 {name}의 식이 비었습니다 — 판정에는 모든 입력이 필요합니다 (B14).")
                continue
            try:
                parse(expression)
            except ExprError as e:
                errors.append(f"입력 {name}의 식을 읽을 수 없습니다: {e}")
        seen: set[str] = set()
        for variable, output in self._output_rows():
            if not variable:
                errors.append("출력 표에 빈 변수 이름이 있습니다.")
            elif not is_var_name(variable):
                errors.append(f"변수 이름 규칙에 맞지 않습니다: {variable}")
            elif variable in seen:
                errors.append(f"변수 이름이 겹칩니다: {variable}")
            seen.add(variable)
            if not output:
                errors.append(f"변수 {variable or '?'}가 받을 DMN 출력을 고르세요.")
            elif table_outputs is not None and output not in table_outputs:
                errors.append(f"DMN 출력에 없는 것을 받습니다: {output} (B14).")
        if not self._output_rows() and decision:
            warnings.append(NO_OUTPUT)
        return errors, warnings

    # ── 읽기 ──

    def decision(self) -> str:
        return str(self.decision_box.currentData() or "")

    def _file(self) -> DecisionFile | None:
        if self.decisions is None:
            return None
        return self.decisions.found.get(self.decision())

    def _input_rows(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for row in range(self.inputs.rowCount()):
            name = self.inputs.item(row, 0)
            expression = self.inputs.item(row, 1)
            out.append(
                (
                    str(name.data(Qt.ItemDataRole.UserRole) or "") if name else "",
                    expression.text().strip() if expression else "",
                )
            )
        return out

    def input_map(self) -> dict[str, str]:
        """`{DMN 입력 이름: 식}` — 결정표에 없는 줄은 식을 비우면 빠진다."""
        return {name: expression for name, expression in self._input_rows() if expression or self._in_table(name)}

    def _in_table(self, name: str) -> bool:
        found = self._file()
        return found is not None and name in io_names(found.table)[0]

    def _output_rows(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for row in range(self.outputs.rowCount()):
            variable = self.outputs.item(row, 0)
            box = self.outputs.cellWidget(row, 1)
            output = box.currentText().strip() if isinstance(box, QComboBox) else ""
            out.append((variable.text().strip() if variable else "", output))
        return out

    def output_map(self) -> dict[str, str]:
        return dict(self._output_rows())

    # ── 그리기 ──

    def _fill_decisions(self, wanted: str) -> None:
        self._quiet, quiet = True, self._quiet
        try:
            self.decision_box.clear()
            self.decision_box.addItem("(고르세요)", "")
            found = self.decisions.found if self.decisions is not None else {}
            for decision_id in sorted(found):
                where = found[decision_id]
                name = where.table.name
                text = f"{decision_id} — {name}" if name and name != decision_id else decision_id
                if where.received:
                    text += f"  ({RECEIVED})"
                self.decision_box.addItem(text, decision_id)
            if wanted and self.decision_box.findData(wanted) < 0:
                shown = f"{wanted}  {NOT_IN_PACKAGE}" if self.decisions is not None else wanted
                self.decision_box.addItem(shown, wanted)
            self.decision_box.setCurrentIndex(max(self.decision_box.findData(wanted), 0))
        finally:
            self._quiet = quiet

    def _fill_inputs(self, given: Mapping[str, str]) -> None:
        """결정표의 입력 줄 + 그림에만 있는 입력 줄. 같은 이름의 식은 남는다."""
        self._quiet, quiet = True, self._quiet
        try:
            found = self._file()
            self.inputs.setRowCount(0)
            names: list[tuple[str, str]] = []
            if found is not None:
                for column in found.table.inputs:
                    if column.expression:
                        names.append((column.expression, column.label))
            in_table = {n for n, _ in names}
            for name in given:
                if name not in in_table:
                    names.append((name, ""))
            for name, label in names:
                row = self.inputs.rowCount()
                self.inputs.insertRow(row)
                shown = name if found is None or name in in_table else f"{name}  {NOT_IN_TABLE}"
                head = QTableWidgetItem(shown)
                head.setData(Qt.ItemDataRole.UserRole, name)
                head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if label and label != name:
                    head.setToolTip(f"라벨: {label}")
                self.inputs.setItem(row, 0, head)
                self.inputs.setItem(row, 1, QTableWidgetItem(str(given.get(name, ""))))
        finally:
            self._quiet = quiet

    def _output_choices(self) -> list[str]:
        found = self._file()
        return io_names(found.table)[1] if found is not None else []

    def _add_output(self, variable: str, output: str) -> None:
        row = self.outputs.rowCount()
        self.outputs.insertRow(row)
        self.outputs.setItem(row, 0, QTableWidgetItem(variable))
        box = QComboBox(self.outputs)
        box.setEditable(self._file() is None)  # 결정표를 모르면 적는다
        box.addItems(self._output_choices())
        if output and box.findText(output) < 0:
            box.addItem(output)
        box.setCurrentIndex(box.findText(output) if output else (0 if box.count() else -1))
        box.currentTextChanged.connect(self._touched)
        self.outputs.setCellWidget(row, 1, box)
        self._touched()

    def _drop_output(self) -> None:
        row = self.outputs.currentRow()
        if row >= 0:
            self.outputs.removeRow(row)
            self._touched()

    def fill_outputs(self) -> None:
        """받지 않은 출력마다 같은 이름의 변수 줄 — 있는 줄은 덮지 않는다."""
        taken = {output for _, output in self._output_rows()}
        variables = {variable for variable, _ in self._output_rows()}
        for output in self._output_choices():
            if output not in taken and output not in variables:
                self._add_output(output, output)

    def _rebuild_outputs(self) -> None:
        rows = self._output_rows()
        self._quiet, quiet = True, self._quiet
        try:
            self.outputs.setRowCount(0)
            for variable, output in rows:
                self._add_output(variable, output)
        finally:
            self._quiet = quiet

    def _decision_changed(self, *_: Any) -> None:
        if self._quiet:
            return
        self._fill_inputs({n: e for n, e in self._input_rows() if e})
        self._rebuild_outputs()
        self._touched()

    def _touched(self, *_: Any) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        found = self._file()
        if self.decisions is None:
            self.summary_label.setText(UNKNOWN_TABLES)
        elif found is not None:
            self.summary_label.setText(summary(found.table) + f" · {found.path.name}")
        elif self.decision():
            self.summary_label.setText(f"패키지의 결정표에 {self.decision()}이 없습니다.")
        else:
            broken = "; ".join(f"{p.name}: {why}" for p, why in (self.decisions.broken.items()))
            self.summary_label.setText(f"읽지 못한 결정표 — {broken}" if broken else "")
        self.edit_button.setEnabled(found is not None)
        self.edit_button.setText("결정표 보기..." if found is not None and found.received else "결정표 편집...")
        self.new_button.setEnabled(self.decisions is not None)
        self.collect_note.setVisible(found is not None and found.table.hit == "COLLECT")
        self.fill_button.setEnabled(bool(self._output_choices()))
        errors, warnings = self.problems()
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))

    # ── 결정표 창 (STU-04a) ──

    def table_dialog(self, *, new: bool = False) -> QDialog | None:
        """STU-04a 창을 짓는다 (띄우지 않는다 — `open_table`·`new_table`이 띄운다, 시험은 이것을 쓴다)."""
        from chaeksas.studio.decision_dialog import DecisionDialog  # noqa: PLC0415

        if self.decisions is None:
            return None
        if new:
            made = DecisionDialog(
                self,
                table=blank(),
                process_dir=self.decisions.process_dir,
                taken=set(self.decisions.found),
            )
        else:
            found = self._file()
            if found is None:
                return None
            made = DecisionDialog(self, table=found.table, path=found.path, read_only=found.received)
        made.saved.connect(self._table_saved)
        return made

    def open_table(self) -> None:
        made = self.table_dialog()
        if made is not None:
            made.exec()

    def new_table(self) -> None:
        made = self.table_dialog(new=True)
        if made is not None:
            made.exec()

    def _table_saved(self, decision_id: str) -> None:
        """창이 `.dmn`을 썼다 — 다시 읽고 그 결정을 고른다."""
        self.reload(decision_id)

    def reload(self, decision_id: str | None = None) -> None:
        keep_inputs = {n: e for n, e in self._input_rows() if e}
        self.decisions = self.decisions_of()
        self._quiet = True
        try:
            self._fill_decisions(decision_id or self.decision())
            self._fill_inputs(keep_inputs)
            self._rebuild_outputs()
        finally:
            self._quiet = False
        self._touched()


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 테마가 안쪽 패딩을 주므로 레이아웃 기본 여백까지 더하면 위가 빈다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


def _show_rows(table: QTableWidget, rows: int) -> None:
    """줄이 없어도 `rows`줄 높이를 보인다 (결재 편집기와 같은 계산)."""
    table.setMinimumHeight(
        table.horizontalHeader().sizeHint().height()
        + table.verticalHeader().defaultSectionSize() * rows
        + table.frameWidth() * 2
    )


__all__ = [
    "COLLECT_NOTE",
    "NOT_IN_PACKAGE",
    "NOT_IN_TABLE",
    "NO_OUTPUT",
    "TAB_LABEL",
    "RuleEditor",
]

"""STU-07 시험 케이스 창 — 왼쪽 목록 + 오른쪽 편집 (880×620).

**JSON 입력 상자를 쓰지 않는다** (STU-07 — 괄호 하나로 저장이 막혔다). 값은 표로 받고 타입을
골라 넣는다. 고를 것(입력 이름·결재 노드·폼 칸·메시지 이름)은 **그림에서 미리 넣어 둔다**.

「저장」은 창을 닫지 않고 모든 케이스를 검증한다. 값과 검증은 `cases.py`에 있다.

표 넷은 **탭**이고 탭 이름에 줄 수가 붙는다. 표는 줄 셋이 스크롤 없이 보이는 높이를 늘 가진다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import CASE_ANSWERER, Case, CaseMessage
from chaeksas.qt.messages import ask_unsaved
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3, SPACE_4
from chaeksas.studio.cases import (
    COMPARISONS,
    NO_APPROVALS,
    PLAIN_KINDS,
    VALUE_KINDS,
    approvals_of,
    check_cases,
    declared_input_decls,
    declared_inputs,
    input_tip,
    kind_of,
    messages_of,
    pack_expected,
    pack_value,
    read,
    result_names,
    unpack_expected,
    unpack_value,
    write,
)
from chaeksas.studio.workspace import BpmProcess, Definition

#: 스크롤 없이 보이는 줄 수 (STU-07).
VISIBLE_ROWS = 3

#: 「결재 자동 응답」 탭 아래 작은 표의 이름 (케이스 `answered_by`, ADR-0096).
ANSWERER_TITLE = f"답한 사람 (적지 않으면 「{CASE_ANSWERER}」)"


def _table(headers: Sequence[str]) -> QTableWidget:
    found = QTableWidget(0, len(headers))
    found.setHorizontalHeaderLabels(list(headers))
    rows = found.verticalHeader()
    rows.setVisible(False)
    # 줄 높이는 **콤보가 잘리지 않는** 높이 — 기본 줄 높이는 글자 한 줄이라 콤보가 눌린다.
    rows.setDefaultSectionSize(max(rows.defaultSectionSize(), QComboBox().sizeHint().height()))
    found.setMinimumHeight(
        found.horizontalHeader().sizeHint().height()
        + VISIBLE_ROWS * rows.defaultSectionSize()
        + 2 * found.frameWidth()
    )
    found.horizontalHeader().setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    found.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return found


class Block(QWidget):
    """탭 하나 — 표 + 「추가」·「선택 줄 삭제」 (STU-07 — 줄을 더할 길이 없으면 표가 소용없다).

    `title`은 탭 이름이다. 줄 수가 바뀔 때마다 `counted`를 불러 탭 이름을 다시 쓰게 한다.
    """

    def __init__(self, title: str, headers: Sequence[str], maker: Callable[[], Sequence[Any]]) -> None:
        super().__init__()
        self.title = title
        self.table = _table(headers)
        self.maker = maker
        self.counted: Callable[[], None] = lambda: None

        add = QPushButton("추가", self)
        add.clicked.connect(self.add_row)
        drop = QPushButton("선택 줄 삭제", self)
        drop.clicked.connect(self.drop_row)

        head = QHBoxLayout()
        head.addStretch(1)
        head.addWidget(add)
        head.addWidget(drop)

        layout = QVBoxLayout(self)
        # 탭 테두리와 단추·표 사이를 띄운다 (붙어 있으면 답답하다).
        layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_2)
        layout.addLayout(head)
        layout.addWidget(self.table, 1)

    def label(self) -> str:
        """탭 이름 — 「입력 변수 (2)」. 비었으면 이름만."""
        count = self.table.rowCount()
        return f"{self.title} ({count})" if count else self.title

    def add_row(self) -> None:
        # **있는 줄은 건드리지 않는다** — 표를 다시 채우면 같은 콤보를 같은 칸에 다시 넣게 되고,
        # Qt는 그 칸의 옛 위젯(=같은 콤보)을 `deleteLater`로 지운다. 다음 이벤트에 콤보가
        # 사라지고 그 칸을 만지면 프로세스가 죽는다.
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, cell in enumerate(self.maker()):
            _fill_cell(self.table, row, column, cell)
        self.table.setCurrentCell(row, 0)
        self.counted()

    def drop_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        self.counted()


class CaseDialog(QDialog):
    """STU-07. 왼쪽에서 고르고 오른쪽에서 고친다."""

    def __init__(self, parent: QWidget | None, process: BpmProcess, definition: Definition) -> None:
        super().__init__(parent)
        self.process = process
        self.definition = definition
        self.edited = read(process, definition)
        self.current = -1
        self.setWindowTitle("시험 케이스")
        self.resize(880, 620)

        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(self._pick)
        add = QPushButton("추가", self)
        add.clicked.connect(self._add)
        drop = QPushButton("삭제", self)
        drop.clicked.connect(self._drop)

        self.names = declared_inputs(definition)
        #: 정의된 입력 — 케이스에 없어도 줄로 깔린다 (STU-07). 비운 채 둔 깔린 줄은 담지 않는다.
        self.decls = declared_input_decls(definition)
        #: 지금 케이스가 **적어 둔** 입력 이름 — 깔린 줄과 가른다.
        self._given: set[str] = set()
        #: 「기대 결과」 이름의 고를 거리 (출력 → 그림이 만드는 변수 → 입력).
        self.result_names = result_names(definition)
        self.forms = approvals_of(definition)
        self.message_names = messages_of(definition)

        self.name_box = QLineEdit(self)
        self.description_box = QLineEdit(self)
        self.manual_box = QCheckBox("사람이 직접 답함 (수동 케이스)", self)

        self.input_block = Block(
            "입력 변수",
            ("이름", "타입", "값"),
            lambda: [_combo(self.names, "", editable=True), _kind_box("string"), ""],
        )
        self.expected_block = Block(
            "기대 결과",
            ("이름", "비교", "타입", "값"),
            lambda: [
                _combo(self.result_names, "", editable=True),
                _combo(list(COMPARISONS), "같음"),
                _kind_box("string"),
                "",
            ],
        )
        self.answer_block = Block(
            "결재 자동 응답",
            ("결재 노드", "칸", "값"),
            lambda: [_combo(sorted(self.forms), ""), _combo(self._keys(), "decision", editable=True), ""],
        )
        # 답한 사람 (케이스 `answered_by`, ADR-0096) — 답과 한 자리에서 보이게 같은 탭 아래에 둔다.
        self.answerer_block = Block(
            ANSWERER_TITLE,
            ("결재 노드", "이름"),
            lambda: [_combo(sorted(self.forms), ""), ""],
        )
        heading = QLabel(ANSWERER_TITLE, self.answer_block)
        set_role(heading, "muted")
        answer_layout = self.answer_block.layout()
        assert isinstance(answer_layout, QVBoxLayout)
        answer_layout.addWidget(heading)
        inner = self.answerer_block.layout()
        if inner is not None:
            inner.setContentsMargins(0, 0, 0, 0)  # 탭 안의 표라 테두리 여백을 또 두지 않는다
        answer_layout.addWidget(self.answerer_block, 1)
        self.message_block = Block(
            "보낼 메시지",
            ("몇 초 뒤", "메시지", "상관 값", "본문(JSON)"),
            lambda: ["0", _combo(self.message_names, "", editable=True), "", "{}"],
        )
        self.inputs = self.input_block.table
        self.expected = self.expected_block.table
        self.answers = self.answer_block.table
        self.answerers = self.answerer_block.table
        self.messages = self.message_block.table

        mark = " — 진입" if definition is process.entry_definition else ""
        form = QFormLayout()
        form.addRow("대상 정의", QLabel(f"{definition.path.name}{mark}", self))
        form.addRow("이름", self.name_box)
        form.addRow("설명", self.description_box)
        form.addRow("", self.manual_box)

        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "error")

        self.blocks = (self.input_block, self.expected_block, self.answer_block, self.message_block)
        self.tabs = QTabWidget(self)
        for block in self.blocks:
            self.tabs.addTab(block, block.title)
            block.counted = self._recount

        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(self.tabs, 1)

        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(drop)
        left.addLayout(buttons)

        # 왼쪽 목록·단추와 오른쪽 탭의 **아래 끝을 맞춘다** — 안내 줄은 아래 단추 줄로 뺀다.
        middle = QHBoxLayout()
        middle.setSpacing(SPACE_4)
        middle.addLayout(left, 1)
        middle.addLayout(right, 3)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close, parent=self
        )
        box.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        box.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        box.accepted.connect(self.save)
        box.button(QDialogButtonBox.StandardButton.Save).clicked.connect(self.save)
        box.rejected.connect(self.reject)

        bottom = QHBoxLayout()
        bottom.addWidget(self.note, 1)
        bottom.addWidget(box)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addLayout(middle, 1)
        layout.addLayout(bottom)

        self._refresh_list()
        if self.edited.cases:
            self.list.setCurrentRow(0)

    # ── 목록 ──

    def _refresh_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for case in self.edited.cases:
            self.list.addItem(case.name or "(이름 없음)")
        self.list.blockSignals(False)

    def _add(self) -> None:
        self._gather()
        self.edited.cases.append(Case(name=f"케이스 {len(self.edited.cases) + 1}"))
        self._refresh_list()
        self.list.setCurrentRow(len(self.edited.cases) - 1)

    def _drop(self) -> None:
        if 0 <= self.current < len(self.edited.cases):
            del self.edited.cases[self.current]
            self.current = -1
            self._refresh_list()
            self.list.setCurrentRow(min(0, len(self.edited.cases) - 1))

    def _pick(self, row: int) -> None:
        self._gather()
        self.current = row
        if not (0 <= row < len(self.edited.cases)):
            return
        self._show(self.edited.cases[row])

    # ── 보이기·모으기 ──

    def _show(self, case: Case) -> None:
        self.name_box.setText(case.name)
        self.description_box.setText(case.description or "")
        self.manual_box.setChecked(case.manual)

        self._given = set(case.inputs)
        rows: list[list[Any]] = [
            [_combo(self.names, name, editable=True), _kind_box(kind), text]
            for name, kind, text in ((n, *unpack_value(v)) for n, v in case.inputs.items())
        ]
        # 정의된 입력 중 적지 않은 것도 줄로 깐다 — 값만 적으면 된다 (「변수」 탭의 정의).
        for decl in self.decls:
            if decl.name not in self._given:
                name_box = _combo(self.names, decl.name, editable=True)
                name_box.setToolTip(input_tip(decl))
                rows.append([name_box, _kind_box(kind_of(decl)), ""])
        _fill(self.inputs, rows)

        wanted = []
        for name, value in case.expected.items():
            comparison, kind, text = unpack_expected(value)
            wanted.append(
                [
                    _combo(self.result_names, name, editable=True),
                    _combo(list(COMPARISONS), comparison),
                    _kind_box(kind),
                    text,
                ]
            )
        _fill(self.expected, wanted)

        answers = []
        for node_id, answer in case.approvals.items():
            # 답이 **비어 있는** 결재는 지우지 않는다 — 「기다린다」는 뜻이다 (기한 초과 시험).
            for key, value in (answer or {"": ""}).items():
                answers.append(
                    [
                        _combo(sorted(self.forms) or [node_id], node_id),
                        _combo(self._keys(node_id), key, editable=True),
                        _text(value),
                    ]
                )
        _fill(self.answers, answers)
        _fill(
            self.answerers,
            [[_combo(sorted(self.forms) or [node_id], node_id), name] for node_id, name in case.answered_by.items()],
        )
        self.note.setText("" if self.forms else NO_APPROVALS)

        _fill(
            self.messages,
            [
                [
                    str(m.after_s),
                    _combo(self.message_names, m.name, editable=True),
                    m.correlation or "",
                    json.dumps(m.payload, ensure_ascii=False),
                ]
                for m in case.messages
            ],
        )
        self._recount()

    def _recount(self) -> None:
        """탭 이름의 줄 수를 다시 쓴다 — 가린 탭에 무엇이 있는지 열지 않고 보이게."""
        for index, block in enumerate(self.blocks):
            self.tabs.setTabText(index, block.label())

    def _keys(self, node_id: str = "") -> list[str]:
        """그 결재 폼의 칸 이름들 (폼이 없으면 `decision`·`comment` — C6)."""
        form = self.forms.get(node_id)
        if form is None or not form.fields:
            return ["decision", "comment"]
        return [f.key for f in form.fields]

    def _gather(self) -> None:
        """화면 → 지금 고른 케이스."""
        if not (0 <= self.current < len(self.edited.cases)):
            return
        declared = {decl.name for decl in self.decls}
        inputs = {
            name: pack_value(kind, text)
            for name, kind, text in _read(self.inputs, (0, 1, 2))
            # 깔린 줄을 비운 채 두었으면 「적지 않았다」다 — 빈 글을 담지 않는다 (기본값이 쓰인다).
            if name and not (name in declared and name not in self._given and not text.strip() and kind in PLAIN_KINDS)
        }
        expected = {
            name: pack_expected(comparison, kind, text)
            for name, comparison, kind, text in _read(self.expected, (0, 1, 2, 3))
            if name
        }
        approvals: dict[str, dict[str, Any]] = {}
        for node_id, key, text in _read(self.answers, (0, 1, 2)):
            if not node_id:
                continue
            answer = approvals.setdefault(node_id, {})
            if key:
                answer[key] = _loose(text)
        # 이름이 빈 줄은 담지 않는다 — 비우면 「시험 케이스」다.
        answered_by = {node_id: name for node_id, name in _read(self.answerers, (0, 1)) if node_id and name}
        messages = []
        for after, name, correlation, payload in _read(self.messages, (0, 1, 2, 3)):
            if not name:
                continue
            try:
                body = json.loads(payload) if payload.strip() else {}
            except ValueError:
                body = {}
            messages.append(
                CaseMessage(
                    after_s=int(after) if after.strip().isdigit() else 0,
                    name=name,
                    correlation=correlation or None,
                    payload=body if isinstance(body, dict) else {},
                )
            )
        # **편집기가 다루지 않는 칸은 그대로 남긴다** (`delegations`).
        self.edited.cases[self.current] = self.edited.cases[self.current].model_copy(
            update={
                "name": self.name_box.text().strip(),
                "description": self.description_box.text().strip() or None,
                "inputs": inputs,
                "expected": expected,
                "approvals": approvals,
                "answered_by": answered_by,
                "messages": messages,
                "manual": self.manual_box.isChecked(),
            }
        )

    # ── 저장·닫기 ──

    def unsaved(self) -> bool:
        """화면이 파일과 다른가 (U11)."""
        self._gather()
        before = read(self.process, self.definition)
        return [c.to_json_dict() for c in before.cases] != [c.to_json_dict() for c in self.edited.cases]

    def reject(self) -> None:
        """「닫기」 — 저장 안 한 변경이 있으면 묻는다 (U11)."""
        if self.unsaved():
            answer = ask_unsaved(self, "저장하지 않은 변경사항", "시험 케이스에 저장하지 않은 변경이 있습니다.")
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self.save():
                return
        super().reject()

    def save(self) -> bool:
        """창을 닫지 않는다 (STU-07). 모든 케이스를 검증한 뒤에 쓴다."""
        self._gather()
        problems = check_cases(self.edited.cases, self.definition)
        if problems:
            self.note.setText(" / ".join(problems[:3]) + (" …" if len(problems) > 3 else ""))
            return False
        process_id = self.definition.process.id if self.definition.process else ""
        write(self.edited, process_id=process_id)
        self.note.setText(f"저장됨 — 케이스 {len(self.edited.cases)}개")
        self._refresh_list()
        return True


def _kind_box(kind: str) -> QComboBox:
    return _combo(list(VALUE_KINDS), kind)


def _combo(items: Sequence[str], current: str, *, editable: bool = False) -> QComboBox:
    """고를 것은 미리 넣어 두고, 거기 없는 것도 쓸 수 있게 한다 (`editable`)."""
    found = QComboBox()
    found.setEditable(editable)
    found.addItems([i for i in items if i])
    if current and current not in items:
        found.addItem(current)
    found.setCurrentText(current)
    return found


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _fill_cell(table: QTableWidget, row: int, column: int, cell: Any) -> None:
    if isinstance(cell, QComboBox):
        table.setCellWidget(row, column, cell)
    else:
        table.removeCellWidget(row, column)
        table.setItem(row, column, QTableWidgetItem(str(cell)))


def _fill(table: QTableWidget, rows: Sequence[Sequence[Any]]) -> None:
    table.clearContents()
    table.setRowCount(len(rows))
    for row, cells in enumerate(rows):
        for column, cell in enumerate(cells):
            _fill_cell(table, row, column, cell)


def _read(table: QTableWidget, columns: Sequence[int]) -> list[tuple[str, ...]]:
    out = []
    for row in range(table.rowCount()):
        cells = []
        for column in columns:
            widget = table.cellWidget(row, column)
            if isinstance(widget, QComboBox):
                cells.append(widget.currentText())
            else:
                item = table.item(row, column)
                cells.append(item.text() if item else "")
        out.append(tuple(cells))
    return out


def _loose(text: str) -> Any:
    """결재 답 한 칸 — 참거짓·수로 보이면 그렇게 읽는다 (폼 타입이 그것을 요구한다)."""
    body = text.strip()
    if body.lower() in ("true", "false"):
        return body.lower() == "true"
    try:
        return int(body)
    except ValueError:
        pass
    try:
        return float(body)
    except ValueError:
        return text


__all__ = ["Block", "CaseDialog"]

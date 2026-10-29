"""STU-04 호출 편집기 — `callActivity`의 `calledElement`와 `chk:call` (C14, ADR-0062).

속성 패널이 Call Activity를 만나면 탭으로 끼운다. **규약은 결재·STU-14와 같다**
(`load`/`dump`/`problems`/`changed`) — 다른 것은 하나다: 고치는 것이 **표준 속성 하나와 `chk:` 요소
하나**라 `dump()`가 `{"calledElement": 글, "call": 본문}`을 준다.

- 갈래가 둘이다 — **이 패키지에서 부르기**(이 패키지의 정의·`libs/`에 받아 둔 공유 정의, 엔진이
  `RunEnv.processes`로 찾는 것과 같다)와 **다른 Bot에 맡기기**(`delegate` — 실행 위치가 서버일 때만,
  B14). 갈래를 바꾸면 다른 쪽 설정은 지운다(위임이 남으면 엔진은 `calledElement`를 보지 않는다).
- **기한·「실패하면」 칸을 두지 않는다** (ADR-0062 §3) — 기한은 타이머 경계, 실패는 오류 경계다.
- 「채우기」는 **대상이 선언한 것**에서 오고 **빈 자리만** 더한다(있는 줄을 덮지 않는다).
- **적어 둔 것을 조용히 바꾸지 않는다.** 편집기가 다루지 않는 칸은 읽은 그대로 돌려준다.
- 「적용」을 막는 것은 **엔진·검사·Center가 거부할 것**뿐이다. 대상을 모르면(Center를 못 읽었다)
  대조만 건너뛴다 — 모르는 것으로 막지 않는다.
- 마지막 관문은 계약 모델(`Call`)이다 — 여기서 놓친 것도 그것이 잡는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import Call, is_var_name
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.service_catalog import CallTarget, target_of
from chaeksas.studio.workspace import BpmProcess

#: 탭 이름.
TAB_LABEL = "호출"

#: 갈래 둘.
MODE_LOCAL = "local"
MODE_DELEGATE = "delegate"

INPUT_COLUMNS = ("호출 대상 변수", "식")
OUTPUT_COLUMNS = ("내 변수", "호출 대상 변수")

#: 표가 처음부터 보이는 줄 수.
VISIBLE_ROWS = 3

HERE = "이 패키지"
NOT_IN_PACKAGE = "(패키지에 없음)"
PC_NO_DELEGATE = "PC BPM 프로세스에서는 위임할 수 없습니다 (실행 전 검사 B14)."
SERVER_BOT_NO_PC = "대상이 서버 Bot이라 PC를 고르지 않습니다 — 적으면 Center가 거절합니다 (bot_ui_for_server)."
BOUNDARY_NOTE = (
    "기한은 타이머(중단) 경계, 실패는 오류 경계로 받습니다 (위임 실패는 DELEGATION_FAILED) — 경계를 다세요."
)
UNKNOWN_TARGET = "대상을 모릅니다 — 받는 것·내놓는 것은 「채우기」 없이 적습니다."


def local_targets(process: BpmProcess | None) -> dict[str, CallTarget] | None:
    """열린 BPM 프로세스에서 부를 수 있는 정의 — **엔진·B14가 찾는 것과 같은 `processes()`**다.

    공유 정의에는 어느 판에서 왔는지 붙인다(`lib_of` — 내보내기가 판을 붙이는 것과 같은 함수).
    열린 것이 없으면 `None`(모른다)이다 — 빈 사전을 주면 모든 호출이 「패키지에 없음」이 된다.
    """
    if process is None:
        return None
    own = {d.process.id for d in process.definitions if d.process is not None}
    out: dict[str, CallTarget] = {}
    for process_id, found in sorted(process.processes().items()):
        lib = None if process_id in own else process.lib_of(process_id)
        where = HERE if lib is None else f"공유 ({lib.ref})"
        out[process_id] = target_of(found, where)
    return out


class CallEditor(QWidget):
    """Call Activity 하나. `run_location`이 `server`가 아니면 위임을 끈다 (B14 — 적지 않은 것도)."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        run_location: str | None = None,
        targets: Mapping[str, CallTarget] | None = None,
        bots: Mapping[str, CallTarget] | None = None,
    ) -> None:
        super().__init__(parent)
        self.run_location = run_location
        #: 이 패키지에서 부를 수 있는 것. `None`이면 모른다 (대조를 건너뛴다).
        self.targets = None if targets is None else dict(targets)
        #: 위임으로 부를 수 있는 Bot (Center). 비어 있으면 모른다.
        self.bots = dict(bots or {})
        self._loaded: dict[str, Any] = {}
        self._called = ""
        self._quiet = False

        self.mode_picks = {
            MODE_LOCAL: QRadioButton("이 패키지에서 부르기", self),
            MODE_DELEGATE: QRadioButton("다른 Bot에 맡기기 (위임)", self),
        }
        self.mode_group = QButtonGroup(self)
        for one in self.mode_picks.values():
            self.mode_group.addButton(one)
        self.mode_picks[MODE_LOCAL].setChecked(True)
        self.mode_note = QLabel("", self)
        self.mode_note.setWordWrap(True)
        set_role(self.mode_note, "muted")

        self.target_box = QComboBox(self)
        self.bot_box = QComboBox(self)
        self.bot_box.setEditable(True)
        line = self.bot_box.lineEdit()
        if line is not None:
            line.setPlaceholderText("Bot 패키지 id (필수)")
        for target in self.bots.values():
            self.bot_box.addItem(target.label, target.id)
        self.version_box = QLineEdit(self)
        self.version_box.setPlaceholderText("비우면 배포된 판")
        self.bot_ui_box = QLineEdit(self)
        self.bot_ui_box.setPlaceholderText("식 — 비우면 Center가 고릅니다")
        self.bot_ui_note = QLabel("", self)
        self.bot_ui_note.setWordWrap(True)
        set_role(self.bot_ui_note, "muted")

        self.target_note = QLabel("", self)
        self.target_note.setWordWrap(True)
        set_role(self.target_note, "muted")

        self.inputs = _table(self, INPUT_COLUMNS)
        self.outputs = _table(self, OUTPUT_COLUMNS)
        self.fill_inputs = QPushButton("기대 입력 채우기", self)
        self.fill_outputs = QPushButton("만드는 출력 채우기", self)
        self.add_input = QPushButton("줄 더하기", self)
        self.drop_input = QPushButton("줄 삭제", self)
        self.add_output = QPushButton("줄 더하기", self)
        self.drop_output = QPushButton("줄 삭제", self)
        # 채운 단추는 영역마다 하나 (스타일 가이드 §3 Button).
        for button in (self.add_input, self.drop_input, self.add_output, self.drop_output):
            button.setObjectName("Secondary")

        self.boundary_note = QLabel(BOUNDARY_NOTE, self)
        self.boundary_note.setWordWrap(True)
        set_role(self.boundary_note, "muted")
        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        self._build_layout()
        self._wire()
        self._refresh()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)

        box = QGroupBox("호출 대상", self)
        column = QVBoxLayout(box)
        _tight(column)
        column.addWidget(self.mode_picks[MODE_LOCAL])
        local = QFormLayout()
        local.addRow("정의", self.target_box)
        column.addLayout(local)
        column.addWidget(self.mode_picks[MODE_DELEGATE])
        column.addWidget(self.mode_note)
        layout.addWidget(box)

        self.delegate_box = QGroupBox("위임", self)
        form = QFormLayout(self.delegate_box)
        _tight(form)
        form.addRow("Bot", self.bot_box)
        form.addRow("판", self.version_box)
        form.addRow("대상 PC", self.bot_ui_box)
        form.addRow("", self.bot_ui_note)
        layout.addWidget(self.delegate_box)

        layout.addWidget(self.target_note)
        layout.addWidget(
            _section(self, "입력", self.inputs, (self.fill_inputs, self.add_input, self.drop_input))
        )
        layout.addWidget(
            _section(self, "출력", self.outputs, (self.fill_outputs, self.add_output, self.drop_output))
        )
        layout.addWidget(self.boundary_note)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

    def _wire(self) -> None:
        self.mode_group.buttonToggled.connect(self._touched)
        self.target_box.currentIndexChanged.connect(self._touched)
        self.bot_box.currentTextChanged.connect(self._touched)
        for line in (self.version_box, self.bot_ui_box):
            line.textChanged.connect(self._touched)
        for table in (self.inputs, self.outputs):
            table.itemChanged.connect(self._touched)
        self.add_input.clicked.connect(lambda: self._add_row(self.inputs))
        self.add_output.clicked.connect(lambda: self._add_row(self.outputs))
        self.drop_input.clicked.connect(lambda: self._drop_rows(self.inputs))
        self.drop_output.clicked.connect(lambda: self._drop_rows(self.outputs))
        self.fill_inputs.clicked.connect(self.fill_expected_inputs)
        self.fill_outputs.clicked.connect(self.fill_made_outputs)

    # ── 규약 ──

    def load(self, body: Mapping[str, Any]) -> None:
        """`{"calledElement": 글, "call": chk:call 본문}`을 그린다."""
        self._quiet = True
        call = body.get("call")
        self._loaded = dict(call) if isinstance(call, Mapping) else {}
        self._called = str(body.get("calledElement") or "")
        delegate = self._loaded.get("delegate")
        delegate = dict(delegate) if isinstance(delegate, Mapping) else None

        self.target_box.clear()
        self.target_box.addItem("— 고르세요 —", "")
        for target in (self.targets or {}).values():
            self.target_box.addItem(target.label, target.id)
        if delegate is None and self._called and self.target_box.findData(self._called) < 0:
            # 그림에 적힌 것을 **지우지 않고** 보인다 — 그대로면 「적용」을 막는다 (B14).
            self.target_box.addItem(f"{self._called} {NOT_IN_PACKAGE}", self._called)
        self.target_box.setCurrentIndex(max(0, self.target_box.findData(self._called if delegate is None else "")))

        bot = str((delegate or {}).get("bpm_process_id") or "")
        found = self.bot_box.findData(bot) if bot else -1
        if found >= 0:
            self.bot_box.setCurrentIndex(found)
        else:
            self.bot_box.setEditText(bot)
        self.version_box.setText(str((delegate or {}).get("version") or ""))
        self.bot_ui_box.setText(str((delegate or {}).get("bot_ui") or ""))
        self.mode_picks[MODE_DELEGATE if delegate is not None else MODE_LOCAL].setChecked(True)

        _fill(self.inputs, _pairs(self._loaded.get("input")))
        _fill(self.outputs, _pairs(self._loaded.get("output")))
        self._quiet = False
        self._refresh()

    def mode(self) -> str:
        return MODE_DELEGATE if self.mode_picks[MODE_DELEGATE].isChecked() else MODE_LOCAL

    def bot_id(self) -> str:
        """고른 Bot — 목록 줄이면 그 id, 적은 글이면 글 그대로 (Center 목록을 못 받았을 때)."""
        text = self.bot_box.currentText().strip()
        index = self.bot_box.findText(text)
        if index >= 0 and self.bot_box.itemData(index):
            return str(self.bot_box.itemData(index))
        return text

    def target(self) -> CallTarget | None:
        """지금 고른 대상 — 모르면 `None`."""
        if self.mode() == MODE_DELEGATE:
            return self.bots.get(self.bot_id())
        return (self.targets or {}).get(str(self.target_box.currentData() or ""))

    def dump(self) -> dict[str, Any]:
        """`{"calledElement", "call"}` — 본문은 **읽은 것 위에** 고친 칸만 얹는다."""
        call = dict(self._loaded)
        _put_map(call, "input", _rows(self.inputs))
        _put_map(call, "output", _rows(self.outputs))
        if self.mode() == MODE_DELEGATE:
            before = self._loaded.get("delegate")
            delegate = dict(before) if isinstance(before, Mapping) else {}
            bot = self.bot_id()
            changed = bot != str(delegate.get("bpm_process_id") or "")
            delegate["bpm_process_id"] = bot
            _put(delegate, "version", self.version_box.text().strip() or None)
            _put(delegate, "bot_ui", self.bot_ui_box.text().strip() or None)
            call["delegate"] = delegate
            found = self.bots.get(bot)
            # **읽는 사람에게 뜻이 있다** (C14) — Bot을 바꿀 때만 그 Bot의 진입 process id를 적는다.
            # 모르면 비운다(다른 것의 이름이 남으면 거짓말이 된다). 바꾸지 않았으면 적힌 그대로다.
            if changed:
                called = found.process_id if found is not None and found.process_id else ""
            else:
                called = self._called
        else:
            call.pop("delegate", None)
            called = str(self.target_box.currentData() or "")
        return {"calledElement": called, "call": call}

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        target = self.target()
        if self.mode() == MODE_DELEGATE:
            if self.run_location != "server":
                errors.append(PC_NO_DELEGATE)
            if not self.bot_id():
                errors.append("맡길 Bot을 고르세요 (bpm_process_id).")
            if target is not None and target.run_location == "server" and self.bot_ui_box.text().strip():
                errors.append(SERVER_BOT_NO_PC)
        else:
            called = str(self.target_box.currentData() or "")
            if not called:
                errors.append("부를 정의를 고르세요.")
            elif self.targets is not None and called not in self.targets:
                errors.append(
                    f"호출 대상 {called}이 이 패키지에 없습니다 (B14) — 공유 정의면 먼저 설치합니다 (STU-11)."
                )

        inputs = _raw_rows(self.inputs)
        outputs = _raw_rows(self.outputs)
        errors.extend(_table_errors(inputs, "입력", key_label="호출 대상 변수", value_label="식"))
        errors.extend(_table_errors(outputs, "출력", key_label="내 변수", value_label="호출 대상 변수"))
        errors.extend(
            f"내 변수 이름으로 쓸 수 없습니다: {key}" for key, _ in outputs if key and not is_var_name(key)
        )
        if target is not None:
            declared = {one.name: one for one in target.inputs}
            for key, _ in inputs:
                if not key:
                    continue
                one = declared.get(key)
                if one is None:
                    errors.append(f"{target.id}이 선언하지 않은 입력입니다: {key} (input_unknown)")
                elif one.from_center:
                    errors.append(f"값 출처가 따로 있어 넘길 수 없는 입력입니다: {key} (input_not_from_caller)")
            unknown = sorted({value for _, value in outputs if value and value not in target.outputs})
            if unknown:
                errors.append(f"{target.id}이 내놓지 않는 출력입니다 (B14): {', '.join(unknown)}")
            given = {key for key, _ in inputs}
            missing = [
                one.name
                for one in target.inputs
                if one.required and not one.has_default and not one.from_center and one.name not in given
            ]
            if missing:
                warnings.append(f"넘기지 않은 필수 입력: {', '.join(missing)}")
        if not errors:
            try:
                Call.model_validate(self.dump()["call"])
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                errors.append(f"호출 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    # ── 채우기 ──

    def fill_expected_inputs(self) -> None:
        """대상이 받는 입력 중 **빈 자리만** 더한다 — 식은 같은 이름. Center가 넣는 것은 뺀다."""
        target = self.target()
        if target is None:
            return
        have = {key for key, _ in _raw_rows(self.inputs)}
        self._append(
            self.inputs,
            [(one.name, one.name) for one in target.inputs if not one.from_center and one.name not in have],
        )

    def fill_made_outputs(self) -> None:
        """대상이 내놓는 것 중 **아직 받지 않는 것만** 더한다 — 내 변수도 같은 이름."""
        target = self.target()
        if target is None:
            return
        taken = {value for _, value in _raw_rows(self.outputs)}
        mine = {key for key, _ in _raw_rows(self.outputs)}
        self._append(
            self.outputs, [(name, name) for name in target.outputs if name not in taken and name not in mine]
        )

    # ── 안쪽 ──

    def _append(self, table: QTableWidget, pairs: list[tuple[str, str]]) -> None:
        if not pairs:
            return
        self._quiet = True
        for key, value in pairs:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(key))
            table.setItem(row, 1, QTableWidgetItem(value))
        self._quiet = False
        self._touched()

    def _add_row(self, table: QTableWidget) -> None:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem(""))
        table.setCurrentCell(row, 0)
        self._touched()

    def _drop_rows(self, table: QTableWidget) -> None:
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        if not rows and table.currentRow() >= 0:
            rows = [table.currentRow()]
        for row in rows:
            table.removeRow(row)
        if rows:
            self._touched()

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        delegating = self.mode() == MODE_DELEGATE
        # B14와 같은 판정 — 실행 위치를 적지 않은 그림도 위임을 쓸 수 없다.
        server = self.run_location == "server"
        # 이미 적힌 위임은 끄지 않는다 — 지우지 않고 「적용」을 막는다 (B14).
        self.mode_picks[MODE_DELEGATE].setEnabled(server or delegating)
        self.mode_note.setText("" if server else PC_NO_DELEGATE)
        self.mode_note.setVisible(not server)
        self.target_box.setEnabled(not delegating)
        self.delegate_box.setVisible(delegating)

        target = self.target()
        server_bot = delegating and target is not None and target.run_location == "server"
        self.bot_ui_box.setEnabled(not server_bot or bool(self.bot_ui_box.text().strip()))
        self.bot_ui_note.setText(SERVER_BOT_NO_PC if server_bot else "")
        self.bot_ui_note.setVisible(server_bot)

        known = target is not None
        for one in (self.fill_inputs, self.fill_outputs):
            one.setEnabled(known)
            one.setToolTip("" if known else UNKNOWN_TARGET)
        if target is None:
            self.target_note.setText(UNKNOWN_TARGET if delegating and self.bot_id() else "")
        else:
            takes = ", ".join(one.name for one in target.inputs if not one.from_center) or "없음"
            gives = ", ".join(target.outputs) or "없음"
            self.target_note.setText(f"받는 것: {takes} · 내놓는 것: {gives}")
        self.problems()


def _table(parent: QWidget, columns: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(columns), parent)
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    header = table.horizontalHeader().sizeHint().height()
    row = table.verticalHeader().defaultSectionSize()
    table.setFixedHeight(header + row * VISIBLE_ROWS + table.frameWidth() * 2)
    return table


def _section(parent: QWidget, title: str, table: QTableWidget, buttons: tuple[QPushButton, ...]) -> QGroupBox:
    box = QGroupBox(title, parent)
    column = QVBoxLayout(box)
    _tight(column)
    column.addWidget(table)
    row = QHBoxLayout()
    for one in buttons:
        row.addWidget(one)
    row.addStretch(1)
    column.addLayout(row)
    return box


def _pairs(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, Mapping):
        return []
    return [(str(key), str(item)) for key, item in value.items()]


def _fill(table: QTableWidget, pairs: list[tuple[str, str]]) -> None:
    table.setRowCount(0)
    for key, value in pairs:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(key))
        table.setItem(row, 1, QTableWidgetItem(value))


def _raw_rows(table: QTableWidget) -> list[tuple[str, str]]:
    return [(_cell(table, row, 0), _cell(table, row, 1)) for row in range(table.rowCount())]


def _cell(table: QTableWidget, row: int, column: int) -> str:
    found = table.item(row, column)
    return found.text().strip() if found is not None else ""


def _rows(table: QTableWidget) -> dict[str, str]:
    """표 → 사전. **둘 다 빈 줄은 버린다** (줄 더하기만 누른 것)."""
    return {key: value for key, value in _raw_rows(table) if key or value}


def _table_errors(rows: list[tuple[str, str]], title: str, *, key_label: str, value_label: str) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for key, value in rows:
        if not key and not value:
            continue
        if not key:
            errors.append(f"{title}: 「{key_label}」이 빈 줄이 있습니다.")
        elif key in seen:
            errors.append(f"{title}: 「{key_label}」이 겹칩니다: {key}")
        elif not value:
            errors.append(f"{title}: {key}의 「{value_label}」을 적으세요.")
        seen.add(key)
    return errors


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _put_map(out: dict[str, Any], key: str, value: dict[str, str]) -> None:
    """비면 — 읽은 그림에 그 칸이 없었으면 더하지 않는다 (적어 둔 것을 조용히 바꾸지 않는다)."""
    if value or key in out:
        out[key] = value


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "BOUNDARY_NOTE",
    "MODE_DELEGATE",
    "MODE_LOCAL",
    "PC_NO_DELEGATE",
    "SERVER_BOT_NO_PC",
    "TAB_LABEL",
    "CallEditor",
    "local_targets",
]

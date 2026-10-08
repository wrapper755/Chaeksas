"""STU-14 서비스 앱 태스크 편집기 — 앱·작업을 골라 `chk:serviceCall`을 만든다.

확장이 기여한 편집기(STU-13)와 **같은 규약**을 쓴다 (`load`/`dump`/`problems`/`changed`) —
속성 패널은 어느 쪽인지 모르고 탭으로 끼울 뿐이다. 다만 이것은 **플랫폼이 가진 편집기**다:
확장이 자기 편집기를 기여하지 않은 작업은 모두 이 편집기를 쓴다 (STU-14 머리말).

지키는 것 다섯.

- **고를 거리는 Center에서 온다** (`service_catalog`) — 주소·작업·수행 모드·입출력 스키마.
  **키 값은 모른다** (ADR-0013). 「API 키」 칸은 **참조 이름**만 받는다.
- **적어 둔 것을 조용히 바꾸지 않는다** (STU-13과 같은 규칙). 작업을 바꿔도 사람이 적어 둔
  입력·출력 값은 지우지 않고, 작업 정의에 없는 칸은 **낡았다고 말한다**.
- **필수 입력이 비면 「적용」을 막는다** (STU-14 검증) — 실행할 때 알면 늦다.
- **결정 수행을 지원하지 않는 작업은 경고한다** — Bot에서 돌지 않는다 (배포 전 검사도 잡는다).
- manifest가 입력·출력 칸을 알려 주지 않으면(스키마는 선택 칸이다) **사람이 적게 둔다** —
  없는 칸을 지어내지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.studio.service_catalog import Catalog, Operation, Usage, missing_required, stale_fields

#: 탭 이름.
TAB_LABEL = "서비스 앱"

#: 「API 키」 — 기본은 BPM 프로세스 설정을 따른다 (STU-14).
FOLLOW_TEXT = "BPM 프로세스 설정을 따름"

#: 표의 열.
INPUT_COLUMNS = ("입력 필드", "필수", "타입", "값 (변수 또는 식)")
OUTPUT_COLUMNS = ("작업 출력 필드", "저장할 변수")

#: 제한 시간을 비우면 「작업 기본값을 따름」이다 (0으로 보인다).
NO_TIMEOUT = 0


def _readonly(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


class ServiceTaskEditor(QWidget):
    """STU-14. 속성 패널이 `chk:serviceCall`을 만났을 때 탭으로 끼운다."""

    #: 무엇이든 바뀌었다 (속성 패널이 「적용」을 켠다).
    changed = Signal()

    def __init__(
        self,
        catalog: Catalog,
        parent: QWidget | None = None,
        *,
        inherited: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog = catalog
        #: BPM 프로세스가 적어 둔 키 참조 (`chk:process.service_keys`) — **이름만** 보인다.
        self.inherited = dict(inherited or {})
        self.usage = Usage()
        self._quiet = False

        self.app_box = QComboBox(self)
        self.operation_box = QComboBox(self)
        self.operation_note = QLabel("", self)
        self.operation_note.setWordWrap(True)
        self.operation_note.setProperty("role", "muted")
        self.modes_note = QLabel("", self)
        self.modes_note.setWordWrap(True)

        self.follow_key = QCheckBox(FOLLOW_TEXT, self)
        self.follow_key.setChecked(True)
        self.key_box = QLineEdit(self)
        self.key_box.setPlaceholderText("이 태스크만 다른 참조 (예외일 때만)")

        self.inputs = QTableWidget(0, len(INPUT_COLUMNS), self)
        self.inputs.setHorizontalHeaderLabels(list(INPUT_COLUMNS))
        self.outputs = QTableWidget(0, len(OUTPUT_COLUMNS), self)
        self.outputs.setHorizontalHeaderLabels(list(OUTPUT_COLUMNS))
        for table in (self.inputs, self.outputs):
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.fill_inputs = QPushButton("기대 입력 채우기", self)
        self.same_names = QPushButton("모두 같은 이름으로", self)
        self.add_input = QPushButton("줄 더하기", self)
        self.add_output = QPushButton("줄 더하기", self)

        self.timeout_box = QSpinBox(self)
        self.timeout_box.setRange(NO_TIMEOUT, 3600)
        self.timeout_box.setSpecialValueText("작업 기본값을 따름")
        self.retry_box = QSpinBox(self)
        self.retry_box.setRange(0, 10)
        self.retry_note = QLabel("", self)
        self.retry_note.setWordWrap(True)
        self.retry_note.setProperty("role", "muted")

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        self.warning.setProperty("role", "warning")

        self._build_layout()
        self._wire()
        self._load_apps()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("서비스 앱", self.app_box)
        form.addRow("작업", self.operation_box)
        form.addRow("", self.operation_note)
        form.addRow("지원 수행 모드", self.modes_note)

        keys = QHBoxLayout()
        keys.addWidget(self.follow_key)
        keys.addWidget(self.key_box, 1)
        form.addRow("API 키", _wrap(keys))

        limits = QHBoxLayout()
        limits.addWidget(QLabel("제한 시간(초)", self))
        limits.addWidget(self.timeout_box)
        limits.addWidget(QLabel("재시도 횟수", self))
        limits.addWidget(self.retry_box)
        limits.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_section("입력", [self.fill_inputs, self.add_input], self))
        layout.addWidget(self.inputs, 1)
        layout.addWidget(_section("출력", [self.same_names, self.add_output], self))
        layout.addWidget(self.outputs, 1)
        layout.addWidget(_section("실행 제한", [], self))
        layout.addLayout(limits)
        layout.addWidget(self.retry_note)
        layout.addWidget(self.warning)

    def _wire(self) -> None:
        self.app_box.currentIndexChanged.connect(self._app_picked)
        self.operation_box.currentIndexChanged.connect(self._operation_picked)
        self.follow_key.toggled.connect(self._key_toggled)
        self.key_box.textChanged.connect(self._touched)
        self.timeout_box.valueChanged.connect(self._touched)
        self.retry_box.valueChanged.connect(self._touched)
        self.inputs.itemChanged.connect(self._touched)
        self.outputs.itemChanged.connect(self._touched)
        self.fill_inputs.clicked.connect(self._fill_expected)
        self.same_names.clicked.connect(self._same_names)
        self.add_input.clicked.connect(lambda: self._add_row(self.inputs))
        self.add_output.clicked.connect(lambda: self._add_row(self.outputs))

    def _load_apps(self) -> None:
        self._quiet = True
        self.app_box.clear()
        if not self.catalog:
            # **고를 것이 없으면 그렇게 말한다** — 빈 콤보를 두지 않는다.
            self.app_box.addItem("(Center에 등록된 서비스 앱이 없습니다)", "")
            self.app_box.setEnabled(False)
        else:
            for one in self.catalog.apps:
                self.app_box.addItem(one.label, one.app_id)
        self._quiet = False

    # ── 규약 (속성 패널이 부른다) ──

    def load(self, call: Mapping[str, Any]) -> None:
        """그림에 적힌 `chk:serviceCall`을 그린다."""
        self._quiet = True
        self.usage = Usage.of(call)
        self._select(self.app_box, self.usage.app_id)
        self._load_operations()
        self._select(self.operation_box, self.usage.operation)
        self.follow_key.setChecked(not self.usage.key_ref)
        self.key_box.setText(self.usage.key_ref)
        self.key_box.setEnabled(bool(self.usage.key_ref))
        self.timeout_box.setValue(int(self.usage.timeout_s or NO_TIMEOUT))
        self.retry_box.setValue(int(self.usage.retry_max))
        self._draw_tables()
        self._quiet = False
        self._retell()

    def dump(self) -> dict[str, Any]:
        """지금 화면 → `chk:serviceCall` 본문."""
        return self._current().to_call()

    def problems(self) -> tuple[list[str], list[str]]:
        """`(막는 것, 경고)` — 막는 것이 있으면 속성 패널이 「적용」을 막는다."""
        usage = self._current()
        blocking: list[str] = []
        warnings: list[str] = []
        if not usage.app_id:
            blocking.append("서비스 앱을 고르세요.")
        if not usage.operation:
            blocking.append("작업을 고르세요.")

        operation = self._operation()
        for name in missing_required(operation, usage):
            blocking.append(f"필수 입력 「{name}」의 값이 비었습니다.")
        for variable, field_name in usage.outputs.items():
            if not variable.strip() or not field_name.strip():
                blocking.append("출력 줄에 빈 칸이 있습니다 (저장할 변수와 작업 출력 필드).")
                break

        stale_in, stale_out = stale_fields(operation, usage)
        if stale_in or stale_out:
            warnings.append(
                "작업 정의가 바뀌었습니다 — 없는 필드: " + ", ".join([*stale_in, *stale_out])
            )
        app = self.catalog.app(usage.app_id)
        if app is not None and not app.healthy:
            warnings.append(f"「{app.name}」이 지금 응답하지 않습니다 (고를 수는 있습니다).")
        if operation is not None and not operation.deterministic_ok:
            warnings.append("이 작업은 Bot(결정 수행)에서 실행할 수 없습니다.")
        if operation is not None and not operation.server_ok:
            warnings.append("이 작업은 서버 실행기에서 부를 수 없습니다 (C1 R8).")
        return blocking, warnings

    # ── 속 ──

    def _operation(self) -> Operation | None:
        app = self.catalog.app(str(self.app_box.currentData() or ""))
        if app is None:
            return None
        return app.operation(str(self.operation_box.currentData() or ""))

    def _current(self) -> Usage:
        inputs = {}
        for row in range(self.inputs.rowCount()):
            name = self._cell(self.inputs, row, 0)
            value = self._cell(self.inputs, row, 3)
            if name and value:
                inputs[name] = value
        outputs = {}
        for row in range(self.outputs.rowCount()):
            field_name = self._cell(self.outputs, row, 0)
            variable = self._cell(self.outputs, row, 1)
            if field_name or variable:
                outputs[variable] = field_name
        return Usage(
            app_id=str(self.app_box.currentData() or ""),
            operation=str(self.operation_box.currentData() or ""),
            inputs=inputs,
            outputs=outputs,
            key_ref="" if self.follow_key.isChecked() else self.key_box.text().strip(),
            timeout_s=self.timeout_box.value() or None,
            retry_max=self.retry_box.value(),
            retry_on=self._retry_on(),
        )

    def _retry_on(self) -> tuple[int, ...]:
        """다시 부를 상태 코드. 적어 둔 것이 있으면 그대로, 없으면 작업이 알려 준 것이다."""
        if self.usage.retry_on:
            return self.usage.retry_on
        operation = self._operation()
        return operation.retry_on if operation is not None else ()

    @staticmethod
    def _cell(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    @staticmethod
    def _select(box: QComboBox, value: str) -> None:
        index = box.findData(value)
        if index >= 0:
            box.setCurrentIndex(index)

    def _load_operations(self) -> None:
        app = self.catalog.app(str(self.app_box.currentData() or ""))
        self.operation_box.clear()
        if app is None:
            return
        for one in app.operations:
            self.operation_box.addItem(one.name, one.name)

    def _app_picked(self) -> None:
        if self._quiet:
            return
        self._quiet = True
        self._load_operations()
        self._quiet = False
        self._operation_picked()

    def _operation_picked(self) -> None:
        if self._quiet:
            return
        self._draw_tables()
        self._retell()
        self.changed.emit()

    def _key_toggled(self, following: bool) -> None:
        self.key_box.setEnabled(not following)
        self._touched()

    def _retell_key(self) -> None:
        """「BPM 프로세스 설정을 따름 (`<참조>`)」 — 무엇을 따르는지 보인다 (STU-14).

        적혀 있지 않으면 **그렇게 말한다** — 따를 것이 없으면 실행할 때 「키 참조가 없다」다 (B7).
        """
        app_id = str(self.app_box.currentData() or "")
        found = self.inherited.get(app_id, "")
        self.follow_key.setText(
            f"{FOLLOW_TEXT} ({found})" if found else f"{FOLLOW_TEXT} — 이 앱의 참조가 적혀 있지 않습니다"
        )

    def _touched(self) -> None:
        if self._quiet:
            return
        self._retell()
        self.changed.emit()

    def _retell(self) -> None:
        self._retell_key()
        operation = self._operation()
        self.operation_note.setText(operation.description if operation is not None else "")
        self.modes_note.setText(", ".join(operation.modes) if operation is not None else "")
        codes = self._retry_on()
        self.retry_note.setText(
            f"다시 부를 상태 코드: {', '.join(str(one) for one in codes)}" if codes else ""
        )
        _, warnings = self.problems()
        self.warning.setText(" ".join(warnings))

    # ── 표 ──

    def _draw_tables(self) -> None:
        """작업의 칸 + **사람이 적어 둔 것**을 함께 보인다 (적은 것을 지우지 않는다)."""
        quiet, self._quiet = self._quiet, True
        operation = self._operation()
        usage = self.usage

        names = [one.name for one in (operation.inputs if operation is not None else ())]
        names += [name for name in usage.inputs if name not in names]
        by_name = {one.name: one for one in (operation.inputs if operation is not None else ())}
        self.inputs.setRowCount(len(names))
        for row, name in enumerate(names):
            spec = by_name.get(name)
            self.inputs.setItem(row, 0, _readonly(name) if spec is not None else QTableWidgetItem(name))
            self.inputs.setItem(row, 1, _readonly("필수" if spec is not None and spec.required else ""))
            self.inputs.setItem(row, 2, _readonly(spec.type if spec is not None else ""))
            self.inputs.setItem(row, 3, QTableWidgetItem(usage.inputs.get(name, "")))

        stale_in, stale_out = stale_fields(operation, usage)
        for row, name in enumerate(names):
            if name in stale_in:
                _mark_stale(self.inputs, row)

        rows = [(field_name, variable) for variable, field_name in usage.outputs.items()]
        known = {one.name for one in (operation.outputs if operation is not None else ())}
        rows += [(name, "") for name in sorted(known) if name not in {one[0] for one in rows}]
        self.outputs.setRowCount(len(rows))
        for row, (field_name, variable) in enumerate(rows):
            self.outputs.setItem(row, 0, QTableWidgetItem(field_name))
            self.outputs.setItem(row, 1, QTableWidgetItem(variable))
            if field_name in stale_out:
                _mark_stale(self.outputs, row)
        self._quiet = quiet

    def _add_row(self, table: QTableWidget) -> None:
        table.setRowCount(table.rowCount() + 1)
        for column in range(table.columnCount()):
            table.setItem(table.rowCount() - 1, column, QTableWidgetItem(""))
        self._touched()

    def _fill_expected(self) -> None:
        """「기대 입력 채우기」 — 빈 값을 **같은 이름의 변수**로 채운다 (STU-14).

        이미 적어 둔 값은 건드리지 않는다.
        """
        quiet, self._quiet = self._quiet, True
        for row in range(self.inputs.rowCount()):
            name = self._cell(self.inputs, row, 0)
            if name and not self._cell(self.inputs, row, 3):
                self.inputs.setItem(row, 3, QTableWidgetItem(name))
        self._quiet = quiet
        self._touched()

    def _same_names(self) -> None:
        """「모두 같은 이름으로」 — 빈 변수 칸을 출력 필드 이름으로 채운다."""
        quiet, self._quiet = self._quiet, True
        for row in range(self.outputs.rowCount()):
            field_name = self._cell(self.outputs, row, 0)
            if field_name and not self._cell(self.outputs, row, 1):
                self.outputs.setItem(row, 1, QTableWidgetItem(field_name))
        self._quiet = quiet
        self._touched()


def _mark_stale(table: QTableWidget, row: int) -> None:
    """작업 정의에 **없는 칸**임을 그 줄에 보인다 (STU-14 — 빨갛게).

    색을 직접 적지 않는다 — 토큰에서 온 팔레트의 오류색을 쓴다 (`docs/07-style-guide.md`).
    """
    from PySide6.QtGui import QPalette  # noqa: PLC0415

    brush = table.palette().brush(QPalette.ColorRole.BrightText)
    for column in range(table.columnCount()):
        item = table.item(row, column)
        if item is not None:
            item.setForeground(brush)
            item.setToolTip("작업 정의에 없는 필드입니다")


def _wrap(layout: Any) -> QWidget:
    holder = QWidget()
    holder.setLayout(layout)
    return holder


def _section(title: str, buttons: list[QPushButton], parent: QWidget) -> QWidget:
    holder = QWidget(parent)
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    label = QLabel(f"<b>{title}</b>", holder)
    row.addWidget(label)
    row.addStretch(1)
    for one in buttons:
        one.setParent(holder)
        row.addWidget(one)
    return holder


__all__ = ["FOLLOW_TEXT", "INPUT_COLUMNS", "OUTPUT_COLUMNS", "TAB_LABEL", "ServiceTaskEditor"]

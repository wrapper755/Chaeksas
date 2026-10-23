"""STU-04 결재·확인 편집기 — `chk:approval` (C14·C6).

속성 패널이 결재(`userTask`)·확인(`manualTask`)을 만나면 탭으로 끼운다. **규약은 STU-14와
같다** (`load`/`dump`/`problems`/`changed`) — 속성 패널은 어느 편집기인지 모른다.

- **적어 둔 것을 조용히 바꾸지 않는다.** 편집기가 다루지 않는 칸은 읽은 그대로 돌려준다.
- 「표시 변수」는 **목록에 더하고 지운다** — 글상자로 두면 오타·빈 줄·겹침이 그대로 그림에 간다.
  규칙에 맞지 않거나 이미 있는 이름은 **넣지 않고** 그 자리에서 까닭을 말한다.
- 「적용」을 막는 것은 **엔진이 거부할 것**뿐이다 — 제목 없음, 키 없음·겹침, 선택지 없는
  `choice`, 타입에 맞지 않는 기본값, 서버에서의 현장 결재(B6과 같은 판정).
- 마지막 관문은 계약 모델(`Approval`)이다 — 여기서 놓친 것도 그것이 잡는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
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
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import Approval, is_var_name
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3

#: 탭 이름 — 결재와 확인은 같은 `chk:approval`이고 이름만 다르다 (C14).
TAB_APPROVAL = "결재"
TAB_CONFIRMATION = "확인"

FIELD_COLUMNS = ("키 (변수명)", "라벨", "타입", "선택지 (쉼표)", "필수", "기본값")
COL_KEY, COL_LABEL, COL_TYPE, COL_CHOICES, COL_REQUIRED, COL_DEFAULT = range(len(FIELD_COLUMNS))

#: 폼 칸 타입 (C6 `KNOWN_FIELD_TYPES`) — 보이는 순서.
FIELD_TYPES = ("text", "number", "bool", "choice")

#: `chk:approval.location` (C14 `APPROVAL_LOCATIONS`) — 보이는 글.
LOCATIONS = (
    ("follow", "Bot UI 설정을 따름"),
    ("center", "Center로 올림"),
    ("field", "현장 PC에서만"),
)
SERVER_NO_FIELD = "서버 BPM 프로세스는 현장 결재를 쓸 수 없습니다 (실행 전 검사 B6)."

#: 담당자를 적는 두 갈래 (ADR-0080 — 이름 배열이거나 변수 이름 하나).
ASSIGNEE_NAMES = "names"
ASSIGNEE_VARIABLE = "variable"

#: 폼 칸 표가 처음부터 보이는 줄 수 (STU-04).
VISIBLE_ROWS = 3

_TRUE = {"true", "예", "참", "1", "yes"}
_FALSE = {"false", "아니오", "거짓", "0", "no"}


class ApprovalEditor(QWidget):
    """결재·확인 하나. `run_location`이 `server`면 「현장 PC에서만」을 끈다."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        run_location: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.run_location = run_location
        self._loaded: dict[str, Any] = {}
        self._quiet = False

        self.title_box = QLineEdit(self)
        self.title_box.setPlaceholderText("결재 창 제목 (필수)")
        self.description_box = QPlainTextEdit(self)
        self.description_box.setPlaceholderText("결재하는 사람에게 보일 설명")
        lines = self.fontMetrics().lineSpacing()
        self.description_box.setFixedHeight(lines * 4)
        self.show_list = QListWidget(self)
        self.show_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # 테마가 줄마다 안쪽 여백을 주므로 글 높이만으로 세면 셋째 줄이 잘린다 — 넉 줄이 보이게.
        self.show_list.setFixedHeight(int(lines * 1.6) * 4 + self.show_list.frameWidth() * 2)
        self.show_input = QLineEdit(self)
        self.show_input.setPlaceholderText("변수 이름 — Enter로 추가 (목록이 비면 전부 보입니다)")
        self.add_show = QPushButton("추가", self)
        self.drop_show = QPushButton("삭제", self)
        self.drop_show.setObjectName("Secondary")
        self.show_note = QLabel("", self)
        self.show_note.setWordWrap(True)
        self.show_note.setProperty("role", "error")
        self.show_note.hide()

        self.fields = QTableWidget(0, len(FIELD_COLUMNS), self)
        self.fields.setHorizontalHeaderLabels(list(FIELD_COLUMNS))
        self.fields.verticalHeader().setVisible(False)
        self.fields.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.fields.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_REQUIRED, QHeaderView.ResizeMode.ResizeToContents)
        _show_rows(self.fields, VISIBLE_ROWS)
        self.add_field = QPushButton("줄 더하기", self)
        self.drop_field = QPushButton("줄 삭제", self)
        # 채운 단추는 영역마다 하나 (스타일 가이드 §3 Button).
        self.drop_field.setObjectName("Secondary")

        self.location_picks: dict[str, QRadioButton] = {}
        self.location_group = QButtonGroup(self)
        for value, text in LOCATIONS:
            one = QRadioButton(text, self)
            self.location_picks[value] = one
            self.location_group.addButton(one)
        self.location_picks["follow"].setChecked(True)
        self.location_note = QLabel("", self)
        self.location_note.setWordWrap(True)
        self.location_note.setProperty("role", "muted")

        self.assignee_mode = QComboBox(self)
        self.assignee_mode.addItem("이름 목록 (쉼표)", ASSIGNEE_NAMES)
        self.assignee_mode.addItem("변수 이름 하나", ASSIGNEE_VARIABLE)
        self.assignee_box = QLineEdit(self)
        self.assignee_box.setPlaceholderText("비우면 담당자를 정하지 않습니다")
        self.expires_box = QLineEdit(self)
        self.expires_box.setPlaceholderText("ISO 기간(예: P3D) 또는 변수 이름 — 비우면 기한 없음")

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        self.warning.setProperty("role", "error")

        self._build_layout()
        self._wire()
        self._refresh_location()
        self._refresh_show_buttons()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(self._content_box())
        layout.addWidget(self._fields_box(), 1)
        layout.addWidget(self._location_box())
        layout.addWidget(self._who_box())
        layout.addWidget(self.warning)

    def _content_box(self) -> QGroupBox:
        box = QGroupBox("내용", self)
        form = QFormLayout(box)
        _tight(form)
        form.addRow("제목", self.title_box)
        form.addRow("설명", self.description_box)
        form.addRow("표시 변수", self._show_area())
        return box

    def _show_area(self) -> QWidget:
        area = QWidget(self)
        column = QVBoxLayout(area)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(SPACE_2)
        row = QHBoxLayout()
        row.setSpacing(SPACE_2)
        row.addWidget(self.show_input, 1)
        row.addWidget(self.add_show)
        row.addWidget(self.drop_show)
        column.addLayout(row)
        column.addWidget(self.show_note)
        column.addWidget(self.show_list)
        return area

    def _fields_box(self) -> QGroupBox:
        box = QGroupBox("폼 칸", self)
        column = QVBoxLayout(box)
        _tight(column)
        row = QHBoxLayout()
        hint = QLabel("답한 값은 같은 이름의 변수가 됩니다. 칸이 없으면 「승인 / 반려」 두 단추입니다.", box)
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        row.addWidget(hint, 1)
        row.addWidget(self.add_field)
        row.addWidget(self.drop_field)
        column.addLayout(row)
        column.addWidget(self.fields, 1)
        return box

    def _location_box(self) -> QGroupBox:
        box = QGroupBox("결재 위치", self)
        column = QVBoxLayout(box)
        _tight(column)
        for one in self.location_picks.values():
            column.addWidget(one)
        column.addWidget(self.location_note)
        return box

    def _who_box(self) -> QGroupBox:
        box = QGroupBox("담당자·기한", self)
        form = QFormLayout(box)
        _tight(form)
        who = QHBoxLayout()
        who.setSpacing(SPACE_2)
        who.addWidget(self.assignee_mode)
        who.addWidget(self.assignee_box, 1)
        form.addRow("담당자", who)
        form.addRow("기한", self.expires_box)
        return box

    def _wire(self) -> None:
        for line in (self.title_box, self.assignee_box, self.expires_box):
            line.textChanged.connect(self._touched)
        self.description_box.textChanged.connect(self._touched)
        self.show_input.textChanged.connect(self._refresh_show_buttons)
        self.show_input.returnPressed.connect(self.add_show_name)
        self.add_show.clicked.connect(self.add_show_name)
        self.drop_show.clicked.connect(self.drop_show_names)
        self.show_list.itemSelectionChanged.connect(self._refresh_show_buttons)
        delete = QShortcut(QKeySequence.StandardKey.Delete, self.show_list)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self.drop_show_names)
        self.fields.itemChanged.connect(self._touched)
        self.location_group.buttonToggled.connect(self._touched)
        self.assignee_mode.currentIndexChanged.connect(self._touched)
        self.add_field.clicked.connect(lambda: self._add_row({}))
        self.drop_field.clicked.connect(self._drop_row)

    # ── 규약 ──

    def load(self, body: Mapping[str, Any]) -> None:
        """그림에 적힌 `chk:approval`을 그린다 (없으면 빈 것)."""
        self._quiet = True
        self._loaded = dict(body)
        self.title_box.setText(str(body.get("title") or ""))
        self.description_box.setPlainText(str(body.get("description") or ""))
        show = body.get("show")
        self.show_list.clear()
        # 그림에 있는 것은 규칙에 맞지 않아도 그대로 보인다 — 지우는 것은 사람이다 (검사가 말한다).
        self.show_list.addItems([str(v) for v in show] if isinstance(show, list) else [])
        self.show_input.clear()
        self._say_show("")
        self.fields.setRowCount(0)
        for found in body.get("fields") or []:
            if isinstance(found, Mapping):
                self._add_row(found)
        location = str(body.get("location") or "follow")
        self.location_picks.get(location, self.location_picks["follow"]).setChecked(True)
        assignees = body.get("assignees")
        if isinstance(assignees, str):
            self.assignee_mode.setCurrentIndex(self.assignee_mode.findData(ASSIGNEE_VARIABLE))
            self.assignee_box.setText(assignees)
        else:
            self.assignee_mode.setCurrentIndex(self.assignee_mode.findData(ASSIGNEE_NAMES))
            names = assignees if isinstance(assignees, list) else []
            self.assignee_box.setText(", ".join(str(n) for n in names))
        self.expires_box.setText(str(body.get("expires") or ""))
        self._quiet = False
        self._refresh_location()

    def dump(self) -> dict[str, Any]:
        """`chk:approval` 본문 — **읽은 것 위에** 고친 칸만 얹는다."""
        out = dict(self._loaded)
        out["title"] = self.title_box.text().strip()
        _put(out, "description", self.description_box.toPlainText().strip() or None)
        _put(out, "show", self.show_names() or None)
        _put(out, "fields", [one for one, _ in self._rows()] or None)
        location = self.location()
        # 기본값(`follow`)은 적지 않는다 — 읽은 그림에 있었으면 그대로 둔다.
        _put(out, "location", location if location != "follow" or "location" in self._loaded else None)
        _put(out, "assignees", self._assignees())
        _put(out, "expires", self.expires_box.text().strip() or None)
        return out

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        if not self.title_box.text().strip():
            errors.append("제목을 적으세요.")
        errors.extend(
            f"표시 변수 이름으로 쓸 수 없습니다: {name}" for name in self.show_names() if not is_var_name(name)
        )
        seen: set[str] = set()
        for one, row_errors in self._rows():
            errors.extend(row_errors)
            key = str(one.get("key") or "")
            if key and key in seen:
                errors.append(f"폼 칸 키가 겹칩니다: {key}")
            seen.add(key)
        if self.location() == "field" and self.run_location == "server":
            errors.append(SERVER_NO_FIELD)
        if self._assignees() is not None and self.assignee_mode.currentData() == ASSIGNEE_VARIABLE:
            name = self.assignee_box.text().strip()
            if not name.isidentifier():
                errors.append(f"담당자 변수 이름으로 쓸 수 없습니다: {name}")
        if not errors:
            try:
                Approval.model_validate(self.dump())
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                errors.append(f"결재 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
        self.warning.setText(errors[0] if errors else "")
        return errors, []

    def show_names(self) -> list[str]:
        """「표시 변수」 목록 — 보이는 순서 그대로."""
        return [self.show_list.item(i).text() for i in range(self.show_list.count())]

    def add_show_name(self) -> None:
        """입력 칸의 이름을 목록 끝에 더한다. **틀린 이름·겹친 이름은 넣지 않는다.**"""
        name = self.show_input.text().strip()
        if not name:
            return
        if not is_var_name(name):
            self._say_show(f"변수 이름으로 쓸 수 없습니다: {name}")
            return
        names = self.show_names()
        if name in names:
            self.show_list.setCurrentRow(names.index(name))
            self._say_show(f"이미 있습니다: {name}")
            return
        self.show_list.addItem(name)
        self.show_input.clear()
        self._say_show("")
        self._touched()

    def drop_show_names(self) -> None:
        """고른 줄을 지운다 (고른 것이 없으면 아무것도 하지 않는다)."""
        rows = sorted({self.show_list.row(one) for one in self.show_list.selectedItems()}, reverse=True)
        if not rows:
            return
        for row in rows:
            self.show_list.takeItem(row)
        self._say_show("")
        self._touched()

    def location(self) -> str:
        return next((v for v, one in self.location_picks.items() if one.isChecked()), "follow")

    # ── 안쪽 ──

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh_location()
        self.changed.emit()

    def _refresh_show_buttons(self) -> None:
        self.add_show.setEnabled(bool(self.show_input.text().strip()))
        self.drop_show.setEnabled(bool(self.show_list.selectedItems()))
        if not self.show_input.text().strip():
            self._say_show("")

    def _say_show(self, text: str) -> None:
        self.show_note.setText(text)
        self.show_note.setVisible(bool(text))

    def _refresh_location(self) -> None:
        """서버에서는 「현장 PC에서만」을 끄고 까닭을 적는다 — **이미 골라 둔 것은 지우지 않는다**."""
        on_server = self.run_location == "server"
        field = self.location_picks["field"]
        field.setEnabled(not on_server or field.isChecked())
        if on_server:
            self.location_note.setText(SERVER_NO_FIELD)
        else:
            self.location_note.setText("여기서 정한 것이 Bot UI의 「결재를 Center로 올리기」보다 우선합니다.")

    def _add_row(self, found: Mapping[str, Any]) -> None:
        quiet, self._quiet = self._quiet, True
        row = self.fields.rowCount()
        self.fields.insertRow(row)
        self.fields.setItem(row, COL_KEY, QTableWidgetItem(str(found.get("key") or "")))
        self.fields.setItem(row, COL_LABEL, QTableWidgetItem(str(found.get("label") or "")))
        kind = QComboBox(self.fields)
        for one in FIELD_TYPES:
            kind.addItem(one)
        wanted = str(found.get("type") or "text")
        if kind.findText(wanted) < 0:
            kind.addItem(wanted)  # 모르는 타입도 지우지 않는다 — 검사가 말한다
        kind.setCurrentText(wanted)
        kind.currentIndexChanged.connect(self._touched)
        self.fields.setCellWidget(row, COL_TYPE, kind)
        # 콤보가 줄보다 크면 아래 줄을 덮는다 — 줄을 콤보에 맞춘다.
        self.fields.setRowHeight(row, max(self.fields.rowHeight(row), kind.sizeHint().height()))
        choices = found.get("choices")
        shown = ", ".join(str(c) for c in choices) if isinstance(choices, list) else ""
        self.fields.setItem(row, COL_CHOICES, QTableWidgetItem(shown))
        required = QTableWidgetItem("")
        required.setFlags((required.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
        required.setCheckState(Qt.CheckState.Checked if found.get("required") else Qt.CheckState.Unchecked)
        self.fields.setItem(row, COL_REQUIRED, required)
        self.fields.setItem(row, COL_DEFAULT, QTableWidgetItem(_shown_default(found.get("default"))))
        self._quiet = quiet
        self._touched()

    def _drop_row(self) -> None:
        rows = sorted({i.row() for i in self.fields.selectedIndexes()}, reverse=True)
        if not rows and self.fields.rowCount():
            rows = [self.fields.rowCount() - 1]
        for row in rows:
            self.fields.removeRow(row)
        self._touched()

    def _cell(self, row: int, column: int) -> str:
        found = self.fields.item(row, column)
        return found.text().strip() if found is not None else ""

    def _rows(self) -> list[tuple[dict[str, Any], list[str]]]:
        """표의 줄 → `(C6 FormField 모양, 그 줄의 오류)`. **모두 빈 줄은 건너뛴다**."""
        out: list[tuple[dict[str, Any], list[str]]] = []
        for row in range(self.fields.rowCount()):
            kind_box = self.fields.cellWidget(row, COL_TYPE)
            kind = kind_box.currentText() if isinstance(kind_box, QComboBox) else "text"
            key, label = self._cell(row, COL_KEY), self._cell(row, COL_LABEL)
            choices_text, default_text = self._cell(row, COL_CHOICES), self._cell(row, COL_DEFAULT)
            checked = self.fields.item(row, COL_REQUIRED)
            required = checked is not None and checked.checkState() == Qt.CheckState.Checked
            if not (key or label or choices_text or default_text):
                continue
            errors: list[str] = []
            where = key or f"{row + 1}번째 줄"
            if not key:
                errors.append(f"폼 칸의 키(변수명)를 적으세요 ({where}).")
            one: dict[str, Any] = {"key": key, "label": label or key, "type": kind}
            if required:
                one["required"] = True
            choices: list[Any] = list(_split(choices_text))
            if kind == "number":
                parsed = [_number(c) for c in choices]
                if any(p is None for p in parsed):
                    errors.append(f"{where}: 선택지가 수가 아닙니다.")
                choices = [p for p in parsed if p is not None]
            if choices:
                one["choices"] = choices
            elif kind == "choice":
                errors.append(f"{where}: `choice`에는 선택지가 필요합니다.")
            if default_text:
                value, problem = _typed_default(kind, default_text, choices)
                if problem:
                    errors.append(f"{where}: {problem}")
                else:
                    one["default"] = value
            out.append((one, errors))
        return out

    def _assignees(self) -> list[str] | str | None:
        text = self.assignee_box.text().strip()
        if not text:
            return None
        if self.assignee_mode.currentData() == ASSIGNEE_VARIABLE:
            return text
        return _split(text)


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글·빈 목록을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，]", text) if part.strip()]


def _number(text: str) -> int | float | None:
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def _shown_default(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _typed_default(kind: str, text: str, choices: list[Any]) -> tuple[Any, str | None]:
    """기본값 글 → 그 타입의 값. 맞지 않으면 `(None, 까닭)`."""
    if kind == "number":
        found = _number(text)
        return (found, None) if found is not None else (None, f"기본값 「{text}」이 수가 아닙니다.")
    if kind == "bool":
        lowered = text.lower()
        if lowered in _TRUE:
            return True, None
        if lowered in _FALSE:
            return False, None
        return None, f"기본값 「{text}」은 true / false 중 하나여야 합니다."
    if kind == "choice" and choices and text not in [str(c) for c in choices]:
        return None, f"기본값 「{text}」이 선택지에 없습니다."
    return text, None


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 테마가 안쪽 패딩을 주므로 레이아웃 기본 여백까지 더하면 위가 빈다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


def _show_rows(table: QTableWidget, rows: int) -> None:
    """줄이 없어도 `rows`줄 높이를 보인다 (STU-14와 같은 계산)."""
    table.setMinimumHeight(
        table.horizontalHeader().sizeHint().height()
        + table.verticalHeader().defaultSectionSize() * rows
        + table.frameWidth() * 2
    )


__all__ = [
    "FIELD_COLUMNS",
    "FIELD_TYPES",
    "LOCATIONS",
    "SERVER_NO_FIELD",
    "TAB_APPROVAL",
    "TAB_CONFIRMATION",
    "VISIBLE_ROWS",
    "ApprovalEditor",
]

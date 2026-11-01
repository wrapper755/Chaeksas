"""STU-04 파일 출력 편집기 — 데이터 객체의 `bpm:dataOutput` (C14 §파일 출력, ADR-0026).

속성 패널이 데이터 객체(`DataObjectReference`)를 만나면 탭으로 끼운다. **규약은 결재·보내기·STU-14와
같다** (`load`/`dump`/`problems`/`changed`). 아직 `bpm:dataOutput`이 없는 데이터 객체에도 붙는다 —
「파일로 씁니다」를 켜고 적용하면 생기고, 끄면 지운다(`dump()`가 `None`).

- **엔진은 템플릿이 있으면 그것만 쓴다** (`core.files._render`) — 그래서 「내용」은 라디오이고 고른 쪽만
  남긴다. 둘이 다 적힌 그림은 템플릿으로 열고 경고로 말한다(적용하면 변수 칸이 빠진다).
- **적어 둔 것을 조용히 바꾸지 않는다.** 편집기가 다루지 않는 칸은 읽은 그대로 돌려준다.
- 「적용」을 막는 것은 **엔진·검사가 거부할 것**뿐이다 — 빈 경로, B5(경로 저장·내용·엑셀 템플릿·CSV
  변수 하나·이어쓰기 형식), B12(모르는 형식), 변수 이름 규칙. 마지막 관문은 계약 모델(`DataOutput`)이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QStringListModel, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import APPENDABLE_FORMATS, FILE_FORMATS, DataOutput, is_var_name
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.name_pick import attach

#: 탭 이름.
TAB_LABEL = "파일 출력"

#: 형식 — 보이는 차례와 이름 (`FILE_FORMATS`와 같은 것을 시험이 대조한다).
FORMATS = (
    ("md", "Markdown (.md)"),
    ("txt", "텍스트 (.txt)"),
    ("csv", "CSV (.csv)"),
    ("json", "JSON (.json)"),
    ("xlsx", "엑셀 (.xlsx)"),
)

#: 내용 둘.
CONTENT_VARIABLES = "variables"
CONTENT_TEMPLATE = "template"

WHEN_WRITTEN = "이어진 태스크(dataOutputAssociation)가 끝날 때 씁니다 — 그 태스크가 만든 변수도 쓸 수 있습니다."
BOTH_WRITTEN = "템플릿과 변수가 함께 적혀 있습니다 — 엔진은 템플릿만 씁니다. 적용하면 변수 칸은 빠집니다."
SHEET_UNUSED = "시트 이름은 변수가 하나일 때만 씁니다 — 여럿이면 시트마다 변수 이름입니다."


class DataOutputEditor(QWidget):
    """파일 출력 하나."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, names: QStringListModel | None = None) -> None:
        super().__init__(parent)
        self._loaded: dict[str, Any] = {}
        self._both = False
        self._quiet = False
        lines = self.fontMetrics().lineSpacing()

        self.on_box = QCheckBox("이 데이터 객체를 파일로 씁니다", self)
        self.on_box.setToolTip("끄면 bpm:dataOutput을 지웁니다 — 평범한 데이터 객체는 엔진이 건너뜁니다.")

        self.path_box = QLineEdit(self)
        self.path_box.setPlaceholderText("예: 결과/{대상월}_대사.md (필수)")
        self.path_box.setToolTip("{변수} 템플릿입니다. 상대 경로는 출력 폴더 기준입니다 (C14 §파일 경로).")
        self.format_box = QComboBox(self)
        for value, text in FORMATS:
            self.format_box.addItem(text, value)
        self.append_box = QCheckBox("이어쓰기", self)
        self.append_box.setToolTip("Markdown·텍스트·CSV만 이어 쓸 수 있습니다. CSV는 열 이름 줄을 다시 쓰지 않습니다.")
        self.sheet_box = QLineEdit(self)
        self.sheet_box.setPlaceholderText("비우면 변수 이름")

        self.content_picks = {
            CONTENT_VARIABLES: QRadioButton("변수", self),
            CONTENT_TEMPLATE: QRadioButton("템플릿", self),
        }
        self.content_group = QButtonGroup(self)
        for one in self.content_picks.values():
            self.content_group.addButton(one)
        self.content_picks[CONTENT_TEMPLATE].setChecked(True)
        self.variables_box = QLineEdit(self)
        self.variables_box.setPlaceholderText("변수 이름, 쉼표로 여럿 — 사전 목록이면 표가 됩니다")
        self.template_box = QPlainTextEdit(self)
        self.template_box.setPlaceholderText("텍스트에 {변수}를 끼웁니다 — {{·}}는 중괄호 한 개")
        self.template_box.setFixedHeight(lines * 7)

        self.store_box = QLineEdit(self)
        self.store_box.setPlaceholderText("변수 이름 (필수)")
        self.store_box.setToolTip("쓴 파일의 경로(출력 폴더 기준 상대 경로)가 들어갑니다 — 메일 첨부가 이것을 씁니다.")
        attach(self.store_box, names)

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        self.file_group = QGroupBox("파일", self)
        file_form = QFormLayout(self.file_group)
        _tight(file_form)
        file_form.addRow("파일 경로", self.path_box)
        file_form.addRow("형식", self.format_box)
        file_form.addRow("", self.append_box)
        file_form.addRow("시트", self.sheet_box)
        self._file_form = file_form

        self.content_group_box = QGroupBox("내용", self)
        content = QVBoxLayout(self.content_group_box)
        _tight(content)
        row = QHBoxLayout()
        for one in self.content_picks.values():
            row.addWidget(one)
        row.addStretch(1)
        content.addLayout(row)
        content.addWidget(self.variables_box)
        content.addWidget(self.template_box)

        self.store_group = QGroupBox("경로 저장", self)
        store = QFormLayout(self.store_group)
        _tight(store)
        store.addRow("변수", self.store_box)

        when = QLabel(WHEN_WRITTEN, self)
        when.setWordWrap(True)
        set_role(when, "muted")

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(self.on_box)
        layout.addWidget(when)
        layout.addWidget(self.file_group)
        layout.addWidget(self.content_group_box)
        layout.addWidget(self.store_group)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

        self.on_box.toggled.connect(self._touched)
        for line in (self.path_box, self.sheet_box, self.variables_box, self.store_box):
            line.textChanged.connect(self._touched)
        self.template_box.textChanged.connect(self._touched)
        self.format_box.currentIndexChanged.connect(self._touched)
        self.append_box.toggled.connect(self._touched)
        self.content_group.buttonToggled.connect(self._touched)
        self._refresh()

    # ── 규약 ──

    def load(self, body: Mapping[str, Any] | None) -> None:
        """`bpm:dataOutput` 본문(없으면 `None`)을 그린다."""
        self._quiet = True
        self._loaded = dict(body) if isinstance(body, Mapping) else {}
        self.on_box.setChecked(bool(self._loaded))
        self.path_box.setText(str(self._loaded.get("path") or ""))
        fmt = str(self._loaded.get("format") or "md")
        index = self.format_box.findData(fmt)
        if index < 0:
            # 모르는 형식도 보인다 — 지우지 않고 「적용」을 막는다 (B12).
            self.format_box.addItem(f"{fmt} (모르는 형식)", fmt)
            index = self.format_box.count() - 1
        self.format_box.setCurrentIndex(index)
        self.append_box.setChecked(self._loaded.get("append") is True)
        self.sheet_box.setText(str(self._loaded.get("sheet") or ""))
        template = self._loaded.get("template")
        variables = self._loaded.get("variables")
        self._both = bool(template) and bool(variables)
        self.template_box.setPlainText(str(template or ""))
        self.variables_box.setText(_joined(variables))
        use_template = bool(template) or (not variables and fmt != "xlsx")
        self.content_picks[CONTENT_TEMPLATE if use_template else CONTENT_VARIABLES].setChecked(True)
        self.store_box.setText(str(self._loaded.get("store_as") or ""))
        self._quiet = False
        self._refresh()

    def fmt(self) -> str:
        return str(self.format_box.currentData() or "")

    def content(self) -> str:
        return CONTENT_TEMPLATE if self.content_picks[CONTENT_TEMPLATE].isChecked() else CONTENT_VARIABLES

    def dump(self) -> dict[str, Any] | None:
        """본문 — **읽은 것 위에** 고친 칸만 얹는다. 「파일로 씁니다」를 끄면 `None`(그 요소를 지운다)."""
        if not self.on_box.isChecked():
            return None
        out = dict(self._loaded)
        out["path"] = self.path_box.text().strip()
        out["format"] = self.fmt()
        if self.content() == CONTENT_TEMPLATE:
            _put(out, "template", self.template_box.toPlainText() or None)
            out.pop("variables", None)
        else:
            _put(out, "variables", _split(self.variables_box.text()) or None)
            out.pop("template", None)
        # 기본값(`false`)은 적지 않는다 — 읽은 그림에 있었으면 그대로 둔다.
        _put(out, "append", True if self.append_box.isChecked() else (False if "append" in self._loaded else None))
        _put(out, "sheet", self.sheet_box.text().strip() or None)
        _put(out, "store_as", self.store_box.text().strip() or None)
        return out

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        body = self.dump()
        if body is not None:
            fmt = self.fmt()
            if not body["path"]:
                errors.append("파일 경로를 적으세요.")
            if fmt not in FILE_FORMATS:
                errors.append(f"파일 형식을 모릅니다: {fmt} — 하나를 고르세요 (B12).")
            store = str(body.get("store_as") or "")
            if not store:
                errors.append("「경로 저장」 변수를 적으세요 — 첨부·후속 태스크가 경로를 받는 유일한 길입니다 (B5).")
            elif not is_var_name(store):
                errors.append(f"「경로 저장」에 변수 이름으로 쓸 수 없는 것이 있습니다: {store}")
            variables = list(body.get("variables") or [])
            if self.content() == CONTENT_TEMPLATE:
                if not body.get("template"):
                    errors.append("템플릿이 비어 있습니다 — 무엇을 쓸지 적으세요 (B5).")
                if fmt == "xlsx":
                    errors.append("엑셀에는 템플릿을 쓸 수 없습니다 — 「변수」로 시트를 만듭니다 (B5).")
            else:
                if not variables:
                    errors.append("쓸 변수를 적으세요 (B5).")
                bad = [name for name in variables if not is_var_name(name)]
                if bad:
                    errors.append(f"「변수」에 변수 이름으로 쓸 수 없는 것이 있습니다: {', '.join(bad)}")
                if fmt == "csv" and len(variables) > 1:
                    errors.append("CSV에는 변수 하나만 쓸 수 있습니다 (B5).")
            if body.get("append") and fmt not in APPENDABLE_FORMATS:
                errors.append(f"{fmt}은 이어 쓸 수 없습니다 — 이어쓰기를 끄세요 (B5).")
            if self._both:
                warnings.append(BOTH_WRITTEN)
            if fmt == "xlsx" and self.sheet_box.text().strip() and len(variables) > 1:
                warnings.append(SHEET_UNUSED)
            if not errors:
                try:
                    DataOutput.model_validate(body)
                except ValidationError as e:
                    first = e.errors()[0]
                    where = ".".join(str(p) for p in first.get("loc", ()))
                    errors.append(f"파일 출력 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    # ── 안쪽 ──

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        on = self.on_box.isChecked()
        for group in (self.file_group, self.content_group_box, self.store_group):
            group.setVisible(on)
        fmt = self.fmt()
        xlsx = fmt == "xlsx"
        # 이미 켜 둔 이어쓰기는 끄지 않는다 — 막고 말한다 (적어 둔 것을 조용히 바꾸지 않는다).
        self.append_box.setEnabled(fmt in APPENDABLE_FORMATS or self.append_box.isChecked())
        self._show_row(self.sheet_box, xlsx)
        template_pick = self.content_picks[CONTENT_TEMPLATE]
        template_pick.setEnabled(not xlsx or template_pick.isChecked())
        template_pick.setToolTip("엑셀에는 템플릿을 쓸 수 없습니다." if xlsx else "")
        use_template = self.content() == CONTENT_TEMPLATE
        self.template_box.setVisible(use_template)
        self.variables_box.setVisible(not use_template)
        self.problems()

    def _show_row(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self._file_form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)


def _joined(value: Any) -> str:
    return ", ".join(str(v) for v in value) if isinstance(value, list) else ""


def _split(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,，]", text) if part.strip()]


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "BOTH_WRITTEN",
    "CONTENT_TEMPLATE",
    "CONTENT_VARIABLES",
    "FORMATS",
    "SHEET_UNUSED",
    "TAB_LABEL",
    "WHEN_WRITTEN",
    "DataOutputEditor",
]

"""CMN-01 결재 / 확인 창 — **Studio와 Bot UI가 같은 창을 쓴다** (`docs/06-screens/README.md` §5).

같은 폼(C6)을 두 곳에서 그리므로 여기 한 곳에 둔다. 다르게 그리면 개발 실행과 운영 실행에서
사람이 다른 것을 보게 된다.

- 폼 칸의 종류대로 위젯을 고른다 (참/거짓 → 체크, 숫자 → 숫자 상자, 선택지 → 콤보, 그 밖 →
  한 줄 입력). **필수는 ` *`**.
- **폼이 없으면 「승인 / 반려」**다 (C6 — 답은 `decision` 하나).
- 「보내기」는 **엔진과 같은 `validate_answer`로 본다** — 틀리면 빨간 글자를 보이고 **창을 닫지
  않는다**. 돌려 보고야 아는 일을 없앤다.
- 검토 자료는 **읽기 전용**이고 JSON 따옴표·`\\n`이 그대로 보이지 않게 푼다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.approvals import Form, FormField, validate_answer

#: 확인(`confirmation`)은 업무 결재가 아니라 **실행 중 막힘**이다 (CMN-01 오른쪽 칸).
CONFIRMATION = "confirmation"
APPROVAL = "approval"

APPROVE = "approve"
REJECT = "reject"

#: 숫자 상자의 범위 — 금액이 들어올 수 있다.
NUMBER_MIN = -1_000_000_000_000.0
NUMBER_MAX = 1_000_000_000_000.0


def as_text(value: Any) -> str:
    """검토 자료 한 값 — **JSON 따옴표가 그대로 보이지 않게** (CMN-01 [R])."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, int | float):
        return f"{value:,}"
    if isinstance(value, list):
        return "\n".join(f"- {as_text(one)}" for one in value)
    if isinstance(value, Mapping):
        return "\n".join(f"{k}: {as_text(v)}" for k, v in value.items())
    return json.dumps(value, ensure_ascii=False)


def review_text(review: Mapping[str, Any]) -> str:
    return "\n".join(f"[{name}]\n{as_text(value)}" for name, value in review.items())


class ApprovalDialog(QDialog):
    """CMN-01. **항상 위에 뜬다** — 사람이 못 보고 지나치면 실행이 멈춰 있는다."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "결재 요청",
        description: str = "",
        form: Form | None = None,
        review: Mapping[str, Any] | None = None,
        layer: str = APPROVAL,
    ) -> None:
        super().__init__(parent)
        self.form = form
        self.layer = layer
        self.answer: dict[str, Any] = {}
        self._widgets: dict[str, QWidget] = {}

        self.setWindowTitle(title or ("실행 확인 요청" if self.is_confirmation else "결재 요청"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        heading = QLabel(title or "결재 요청", self)
        heading.setWordWrap(True)
        heading.setProperty("role", "h2")
        layout.addWidget(heading)

        if description:
            said = QLabel(description, self)
            said.setWordWrap(True)
            layout.addWidget(said)

        if review:
            box = QPlainTextEdit(review_text(review), self)
            box.setReadOnly(True)
            layout.addWidget(box, 1)

        if self.has_fields:
            layout.addLayout(self._fields())

        buttons = self._buttons()
        # 폼이 없는 결재의 「메모」 한 줄 (CMN-01 — 단추 칸에 함께 둔다).
        if getattr(self, "comment", None) is not None:
            layout.addWidget(self.comment)

        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        self.note.setProperty("role", "error")
        layout.addWidget(self.note)
        layout.addWidget(buttons)

    # ── 모양 ──

    @property
    def is_confirmation(self) -> bool:
        return self.layer == CONFIRMATION

    @property
    def has_fields(self) -> bool:
        return bool(self.form and self.form.fields)

    def _fields(self) -> QFormLayout:
        made = QFormLayout()
        for field in self.form.fields if self.form else []:
            widget = self._widget(field)
            self._widgets[field.key] = widget
            made.addRow(f"{field.label}{' *' if field.required else ''}", widget)
        return made

    def _widget(self, field: FormField) -> QWidget:
        if field.type == "bool":
            found = QCheckBox(self)
            found.setChecked(bool(field.default))
            return found
        if field.type == "number":
            number = QDoubleSpinBox(self)
            number.setRange(NUMBER_MIN, NUMBER_MAX)
            number.setDecimals(2)
            if isinstance(field.default, int | float):
                number.setValue(float(field.default))
            return number
        if field.type == "choice":
            combo = QComboBox(self)
            combo.addItems([str(one) for one in (field.choices or [])])
            if field.default is not None:
                combo.setCurrentText(str(field.default))
            return combo
        line = QLineEdit(self)
        if field.default is not None:
            line.setText(str(field.default))
        return line

    def _buttons(self) -> QDialogButtonBox:
        box = QDialogButtonBox(self)
        if self.is_confirmation:
            # 확인은 「계속 / 중단」이다 (업무 승인이 아니다).
            self.ok = box.addButton("계속", QDialogButtonBox.ButtonRole.AcceptRole)
            self.no = box.addButton("중단", QDialogButtonBox.ButtonRole.RejectRole)
        elif self.has_fields:
            self.ok = box.addButton("보내기", QDialogButtonBox.ButtonRole.AcceptRole)
            self.no = box.addButton("취소", QDialogButtonBox.ButtonRole.RejectRole)
        else:
            # 폼이 없으면 **승인 / 반려**다 (C6).
            self.ok = box.addButton("승인", QDialogButtonBox.ButtonRole.AcceptRole)
            self.no = box.addButton("반려", QDialogButtonBox.ButtonRole.RejectRole)
            self.comment = QLineEdit(self)
            self.comment.setPlaceholderText("메모 (선택)")
        self.ok.clicked.connect(self.send)
        self.no.clicked.connect(self.refuse)
        return box

    # ── 답 ──

    def collect(self) -> dict[str, Any]:
        """화면 → 답 한 벌 (C6). 폼이 없으면 `decision` 하나다."""
        if not self.has_fields:
            found: dict[str, Any] = {"decision": APPROVE}
            text = getattr(self, "comment", None)
            if text is not None and text.text().strip():
                found["comment"] = text.text().strip()
            return found
        out: dict[str, Any] = {}
        for key, widget in self._widgets.items():
            if isinstance(widget, QCheckBox):
                out[key] = widget.isChecked()
            elif isinstance(widget, QDoubleSpinBox):
                value = widget.value()
                out[key] = int(value) if value.is_integer() else value
            elif isinstance(widget, QComboBox):
                out[key] = widget.currentText()
            elif isinstance(widget, QLineEdit):
                # **빈 칸은 「안 적었다」**(`None`)이지 빈 글자가 아니다 — 그래야 C6 검증이
                # 「필수인데 비어 있다」를 말한다 (빈 글자는 「적었다」로 지나간다).
                text = widget.text().strip()
                out[key] = text or None
        return out

    def send(self) -> None:
        """「보내기」 — **엔진과 같은 검증기**로 보고, 틀리면 창을 닫지 않는다 (C6)."""
        found = self.collect()
        problems = validate_answer(self.form, found)
        if problems:
            self.note.setText(" / ".join(p.message for p in problems[:3]))
            return
        self.answer = found
        self.accept()

    def refuse(self) -> None:
        """「반려」·「중단」·「취소」 — **답하지 않는 것이 아니라 거절이다** (C6)."""
        # 폼이 있어도 거절은 `decision`으로 말한다 — 빈 답을 보내면 실행이 다시 묻는다.
        self.answer = {"decision": REJECT}
        comment = getattr(self, "comment", None)
        if comment is not None and comment.text().strip():
            self.answer["comment"] = comment.text().strip()
        self.reject()

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        *,
        title: str = "결재 요청",
        description: str = "",
        form: Form | None = None,
        review: Mapping[str, Any] | None = None,
        layer: str = APPROVAL,
    ) -> dict[str, Any] | None:
        """창을 띄우고 답을 돌려준다. 창을 그냥 닫으면 `None` (= 아직 답하지 않았다)."""
        dialog = cls(
            parent, title=title, description=description, form=form, review=review, layer=layer
        )
        done = dialog.exec()
        if done == QDialog.DialogCode.Accepted:
            return dialog.answer
        return dialog.answer or None


def comment_row(dialog: ApprovalDialog) -> QLineEdit | None:
    """폼 없는 결재의 「메모」 한 줄 (있으면)."""
    return getattr(dialog, "comment", None)


__all__ = [
    "APPROVAL",
    "APPROVE",
    "CONFIRMATION",
    "REJECT",
    "ApprovalDialog",
    "as_text",
    "comment_row",
    "review_text",
]

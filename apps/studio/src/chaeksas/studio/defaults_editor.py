"""STU-04 BPM 프로세스 기본값 편집기 — `chk:defaults` (C14 §프로세스 수준, ADR-0105·ADR-0033).

속성 패널이 **정의 자체**(`Process`)를 보일 때 탭으로 끼운다 — 빈 상태의 「BPM 프로세스 기본값」 단추가
그 길이다. **규약은 결재·보내기·STU-14와 같다** (`load`/`dump`/`problems`/`changed`).

- 모든 AI 태스크의 기본값이고 **태스크에 적은 값이 이긴다** — `limits`는 칸마다, 목록 둘은 태스크에
  하나라도 적었으면 그것만 (`core.nodes.with_ai_defaults`). `desktop`은 확장 태스크에도 속성 기본값으로
  넘어간다 (`core.nodes._with_defaults`).
- **`chk:process`는 만지지 않는다** — 입력·출력은 「변수」 탭, 실행 위치는 STU-06, 정의 고정은 STU-15가
  고친다. 여기서 다시 만들면 같은 칸이 두 자리에 산다.
- **적어 둔 것을 조용히 바꾸지 않는다.** 다루지 않는 칸(`web` — 계약에 있지만 읽는 곳이 없다)은 읽은
  그대로 돌려주고 경고 한 줄로 말한다. 모든 칸을 비우면 `dump()`가 `None` — 속성 패널이 그 요소를 지운다.
- 마지막 관문은 계약 모델(`Defaults`)이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import Defaults
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.ai_task_editor import CONFIRM_NOTE, FORBIDDEN_NOTE

#: 탭 이름.
TAB_LABEL = "기본값"

ELSEWHERE = (
    "입력·출력은 아래 「변수」 탭, 실행 위치는 파일 → BPM 프로세스 정보(STU-06), "
    "외부 정의 고정은 확장 창(STU-15)에서 고칩니다."
)
TASK_WINS = (
    "모든 AI 태스크의 기본값입니다. 태스크에 적은 값이 이깁니다 — 실행 제한은 칸마다, "
    "지시문은 태스크에 한 줄이라도 적었으면 그것만."
)
INSTRUCTIONS_NOTE = "줄마다 하나. 비우면 기본값이 없습니다."
UNREAD_WEB = (
    "web(브라우저 프로필·세션)이 적혀 있습니다 — 읽는 곳이 없어 그대로 둡니다 (「JSON」 탭에서 뺄 수 있습니다)."
)


class DefaultsEditor(QWidget):
    """`chk:defaults` 하나."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loaded: dict[str, Any] = {}
        self._quiet = False
        lines = self.fontMetrics().lineSpacing()

        self.max_steps_box = QSpinBox(self)
        self.max_steps_box.setRange(0, 500)
        self.max_steps_box.setSpecialValueText("기본")
        self.max_steps_box.setToolTip("비우면 8단계(웹·데스크톱은 30단계)입니다.")
        self.timeout_box = QSpinBox(self)
        self.timeout_box.setRange(0, 86_400)
        self.timeout_box.setSpecialValueText("없음")
        self.timeout_box.setToolTip(
            "넘으면 업무 실패(TASK_FAILED)입니다 — 하던 호출은 끊지 않고 다음 일을 시작하기 전에 멈춥니다."
        )
        self.forbidden_box = QPlainTextEdit(self)
        self.forbidden_box.setPlaceholderText("예: 삭제 버튼을 누르지 않는다")
        self.forbidden_box.setFixedHeight(lines * 4)
        self.confirm_box = QPlainTextEdit(self)
        self.confirm_box.setPlaceholderText("예: 로그인 화면이 나타남")
        self.confirm_box.setFixedHeight(lines * 4)
        self.app_box = QLineEdit(self)
        self.app_box.setPlaceholderText("앱 이름 — 그 PC Worker의 desktop-apps.json에 있는 것")
        self.app_box.setToolTip("데스크톱 AI 태스크와 UI 태스크가 앱 이름을 적지 않았을 때 씁니다 (ADR-0033).")

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        limits = QGroupBox("실행 제한", self)
        limits_form = QFormLayout(limits)
        _tight(limits_form)
        limits_form.addRow("최대 단계", self.max_steps_box)
        limits_form.addRow("제한 시간(초)", self.timeout_box)

        instructions = QGroupBox("지시문", self)
        column = QVBoxLayout(instructions)
        _tight(column)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("하지 않을 것", self.forbidden_box)
        form.addRow("", _muted(FORBIDDEN_NOTE, instructions))
        form.addRow("멈추고 넘길 상황", self.confirm_box)
        form.addRow("", _muted(CONFIRM_NOTE, instructions))
        column.addLayout(form)
        column.addWidget(_muted(INSTRUCTIONS_NOTE, instructions))

        desktop = QGroupBox("데스크톱", self)
        desktop_form = QFormLayout(desktop)
        _tight(desktop_form)
        desktop_form.addRow("띄울 앱", self.app_box)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(_muted(ELSEWHERE, self))
        layout.addWidget(_muted(TASK_WINS, self))
        layout.addWidget(limits)
        layout.addWidget(instructions)
        layout.addWidget(desktop)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

        self.max_steps_box.valueChanged.connect(self._touched)
        self.timeout_box.valueChanged.connect(self._touched)
        self.forbidden_box.textChanged.connect(self._touched)
        self.confirm_box.textChanged.connect(self._touched)
        self.app_box.textChanged.connect(self._touched)
        self._refresh()

    # ── 규약 ──

    def load(self, body: Mapping[str, Any] | None) -> None:
        """`chk:defaults` 본문(없으면 `None`)을 그린다."""
        self._quiet = True
        self._loaded = dict(body) if isinstance(body, Mapping) else {}
        limits = self._loaded.get("limits")
        steps = limits.get("max_steps") if isinstance(limits, Mapping) else None
        self.max_steps_box.setValue(steps if isinstance(steps, int) and steps > 0 else 0)
        timeout = limits.get("timeout_s") if isinstance(limits, Mapping) else None
        self.timeout_box.setValue(timeout if isinstance(timeout, int) and timeout > 0 else 0)
        self.forbidden_box.setPlainText(_lines_of(self._loaded.get("forbidden_actions")))
        self.confirm_box.setPlainText(_lines_of(self._loaded.get("confirm_triggers")))
        desktop = self._loaded.get("desktop")
        self.app_box.setText(str(desktop.get("app") or "") if isinstance(desktop, Mapping) else "")
        self._quiet = False
        self._refresh()

    def dump(self) -> dict[str, Any] | None:
        """본문 — **읽은 것 위에** 고친 칸만 얹는다. 남는 칸이 없으면 `None`(그 요소를 지운다)."""
        out = dict(self._loaded)
        limits = dict(self._loaded["limits"]) if isinstance(self._loaded.get("limits"), Mapping) else {}
        _put(limits, "max_steps", self.max_steps_box.value() or None)
        _put(limits, "timeout_s", self.timeout_box.value() or None)
        _put(out, "limits", limits or None)
        for key, box in (("forbidden_actions", self.forbidden_box), ("confirm_triggers", self.confirm_box)):
            _put(out, key, _lines(box) or None)
        desktop = dict(self._loaded["desktop"]) if isinstance(self._loaded.get("desktop"), Mapping) else {}
        _put(desktop, "app", self.app_box.text().strip() or None)
        _put(out, "desktop", desktop or None)
        return out or None

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        if self._loaded.get("web") is not None:
            warnings.append(UNREAD_WEB)
        body = self.dump()
        if body is not None:
            try:
                Defaults.model_validate(body)
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                errors.append(f"기본값 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
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
        self.problems()


def _lines(box: QPlainTextEdit) -> list[str]:
    """줄마다 하나 — 빈 줄은 버린다."""
    return [line.strip() for line in box.toPlainText().splitlines() if line.strip()]


def _lines_of(value: Any) -> str:
    return "\n".join(str(one) for one in value) if isinstance(value, list) else ""


def _muted(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    set_role(label, "muted")
    return label


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글·빈 목록을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "ELSEWHERE",
    "INSTRUCTIONS_NOTE",
    "TAB_LABEL",
    "TASK_WINS",
    "UNREAD_WEB",
    "DefaultsEditor",
]

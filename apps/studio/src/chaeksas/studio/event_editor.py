"""STU-04 이벤트 편집기 — 타이머·메시지·신호·오류와 경계의 「노드 중단」 (C14 §이벤트).

속성 패널이 이벤트(시작·중간 받기·중간 던지기·경계·끝)와 받기 태스크를 만나면 탭으로 끼운다.
**규약은 결재·STU-14와 같다** (`load`/`dump`/`problems`/`changed`) — 다른 것은 둘이다.

- 고치는 것이 **표준 이벤트 정의의 칸**과 `bpm:receive`라 `dump()`가
  `{"event": {칸: 값}, "receive": 본문 | None}`을 준다. 캔버스가 `event`를 bpmn-js 명령으로 옮긴다.
- **이벤트 정의의 종류는 바꾸지 않는다** — 캔버스의 바꾸기 메뉴(렌치)가 한다. 여기서는 그 종류에서
  **엔진이 읽는 칸만** 둔다(타이머 값, 메시지·신호 이름, 오류 코드, 경계의 중단, 받기의 상관 키·받을 값).
  엔진이 읽지 않는 정의(조건·끝 이벤트의 오류·종료 …)는 칸 없이 그렇다고 말한다.

- 타이머의 종류는 **자리가 정한다** — 시작은 주기(`timeCycle`), 경계·중간은 기한(`timeDuration`)이다
  (C14). 그림이 다른 종류를 적었으면 경고하고, 값을 고치면 그 자리의 종류로 쓴다. 주기는 **Center가 일정을
  쓸 때와 같은 함수**(`contracts.schedule`, C1 R13)로 본다 — 여기서 받은 식이 올릴 때 막히지 않는다.
- 이름(메시지·신호·오류 코드)은 **같은 이름의 정의를 가리킨다** — 캔버스가 없으면 만든다. 다른 이벤트와
  함께 쓰던 정의의 이름은 바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QStringListModel, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import duration_hours, is_var_name
from chaeksas.contracts.schedule import cycle_problem
from chaeksas.core.run_state import (
    ERROR_APPROVAL_EXPIRED,
    ERROR_APPROVAL_WITHDRAWN,
    ERROR_DELEGATION_FAILED,
    ERROR_ESCALATED,
    ERROR_SEND_FAILED,
    ERROR_TASK_FAILED,
)
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.name_pick import attach

#: 탭 이름 — 이벤트와 받기 태스크.
TAB_LABEL = "이벤트"
TAB_RECEIVE = "받기"

#: 오류 경계가 고를 거리 (C14 §이벤트의 표준 코드 — 엔진이 이 코드로 실패를 올린다).
ERROR_CODES = (
    ERROR_TASK_FAILED,
    ERROR_SEND_FAILED,
    ERROR_ESCALATED,
    ERROR_APPROVAL_WITHDRAWN,
    ERROR_APPROVAL_EXPIRED,
    ERROR_DELEGATION_FAILED,
)

#: 캔버스가 주는 정의 이름(`TimerEventDefinition`에서 앞뒤를 뗀 것) → 사람의 말.
DEFINITIONS = {
    "": "정의 없음",
    "Timer": "타이머",
    "Message": "메시지",
    "Signal": "신호",
    "Error": "오류",
    "Conditional": "조건",
    "Terminate": "종료",
    "Escalation": "에스컬레이션",
    "Compensate": "보상",
    "Link": "링크",
}
#: BPMN 요소 → 자리.
POSITIONS = {
    "StartEvent": "시작",
    "IntermediateCatchEvent": "중간 받기",
    "IntermediateThrowEvent": "중간 던지기",
    "BoundaryEvent": "경계",
    "EndEvent": "끝",
    "ReceiveTask": "받기 태스크",
}

#: 정의마다 **엔진이 읽는 자리** (C14 §이벤트, `core.nodes`·`engine`). 밖은 칸이 없다.
READ_AT = {
    "Timer": frozenset({"StartEvent", "IntermediateCatchEvent", "BoundaryEvent"}),
    "Message": frozenset({"StartEvent", "IntermediateCatchEvent", "BoundaryEvent", "ReceiveTask"}),
    "Signal": frozenset({"StartEvent", "IntermediateCatchEvent", "IntermediateThrowEvent", "BoundaryEvent"}),
    "Error": frozenset({"BoundaryEvent"}),
}
#: 「노드 중단」을 고를 수 있는 경계 — 오류 경계는 늘 중단이다.
INTERRUPT_CHOICE = frozenset({"Timer", "Message", "Signal"})

CYCLE = "timeCycle"
DURATION = "timeDuration"
TIMER_KIND_LABELS = {"timeCycle": "주기", "timeDuration": "기한", "timeDate": "일시"}

NOT_READ = "엔진이 읽지 않는 이벤트 정의입니다 — 칸이 없습니다."
CONDITIONAL = "조건 이벤트는 schema 1에서 쓰지 않습니다 (C14) — 메시지나 타이머로 바꾸세요."
PLAIN_START = "작업 지시로 시작합니다."
MILESTONE = "이정표 — 지나가며 실행 기록에 남습니다. 이름이 이정표 이름입니다."
CATCH_UNDEFINED = (
    "중간 받기에 이벤트 정의가 없습니다 — 엔진이 멈춥니다 (event_undefined). 바꾸기 메뉴로 정의를 고르세요."
)
START_TIMER_NOTE = (
    "패키지의 시작 방법(C1 triggers)에 실립니다 — 배포되면 Center가 이 일정으로 작업을 만들어 깨웁니다"
    " (시간대는 Center 설정, ADR-0110)."
)
MESSAGE_NOTE = "외부 시스템은 Center 메시지 API로 이 이름을 보냅니다 (C12)."
SIGNAL_NOTE = "한 실행 안의 가지 사이에서만 오갑니다."
SIGNAL_START = "신호 시작은 schema 1 밖입니다 — 신호는 한 실행 안에서만 오가므로 이 이벤트로 시작하지 않습니다."
ERROR_NOTE = "오류 경로에는 error_code·error_message·failed_task 변수가 생깁니다."
ALL_FAILURES = "모든 업무 실패"
NOT_STANDARD = "표준 오류 코드가 아닙니다: {code} — 그 코드로 실패하는 태스크가 있어야 받습니다."
OTHER_TIMER_KIND = (
    "그림의 타이머는 {found}({kind})입니다 — 이 자리는 {wanted}({wanted_kind})를 씁니다. 값을 고치면 그렇게 씁니다."
)


class EventEditor(QWidget):
    """이벤트 하나 (또는 받기 태스크 하나)."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, names: QStringListModel | None = None) -> None:
        super().__init__(parent)
        self._quiet = False
        self.bpmn_type = ""
        self.definition = ""
        self._event: dict[str, Any] = {}
        self._receive: dict[str, Any] = {}

        self.what = QLabel("", self)
        self.what.setWordWrap(True)
        self.what_note = QLabel("", self)
        self.what_note.setWordWrap(True)
        set_role(self.what_note, "muted")

        self.timer_box = QLineEdit(self)
        attach(self.timer_box, names)
        self.timer_kind = QLabel("", self)
        self.timer_kind.setWordWrap(True)
        set_role(self.timer_kind, "muted")
        self.timer_preview = QLabel("", self)
        self.timer_preview.setWordWrap(True)
        set_role(self.timer_preview, "muted")

        self.message_box = QLineEdit(self)
        self.message_box.setPlaceholderText("메시지 이름 (필수)")
        self.correlation_box = QLineEdit(self)
        self.correlation_box.setPlaceholderText("변수 이름 — 비우면 이름만 맞으면 받습니다")
        self.correlation_box.setToolTip("그 변수의 값이 같은 메시지만 받습니다 (bpm:receive.correlation).")
        attach(self.correlation_box, names)
        self.payload_box = QLineEdit(self)
        self.payload_box.setPlaceholderText("변수 이름, 쉼표로")
        self.payload_box.setToolTip(
            "메시지 본문에서 변수가 되는 이름입니다. 적지 않은 것은 버립니다 (bpm:receive.payload)."
        )
        self.message_note = QLabel(MESSAGE_NOTE, self)
        self.message_note.setWordWrap(True)
        set_role(self.message_note, "muted")

        self.signal_box = QLineEdit(self)
        self.signal_box.setPlaceholderText("신호 이름 (필수)")
        signal_note = QLabel(SIGNAL_NOTE, self)
        signal_note.setWordWrap(True)
        set_role(signal_note, "muted")

        self.error_box = QComboBox(self)
        self.error_box.setEditable(True)
        self.error_box.addItems(["", *ERROR_CODES])
        line = self.error_box.lineEdit()
        if line is not None:
            line.setPlaceholderText(f"비우면 {ALL_FAILURES}")
        self.error_box.setToolTip("코드가 맞는 경계가 먼저 받고, 없으면 코드 없는 경계가 받습니다.")
        error_note = QLabel(ERROR_NOTE, self)
        error_note.setWordWrap(True)
        set_role(error_note, "muted")

        self.interrupt_box = QCheckBox("노드 중단", self)
        self.interrupt_box.setToolTip("끄면 노드는 그대로 돌고 경계 쪽 흐름이 하나 더 생깁니다 (cancelActivity).")

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        head = QGroupBox("이벤트 정의", self)
        head_layout = QVBoxLayout(head)
        _tight(head_layout)
        head_layout.addWidget(self.what)
        head_layout.addWidget(self.what_note)
        head_layout.addWidget(self.interrupt_box)

        self.timer_group = QGroupBox("타이머", self)
        form = QFormLayout(self.timer_group)
        _tight(form)
        form.addRow("값", self.timer_box)
        form.addRow("", self.timer_kind)
        form.addRow("", self.timer_preview)

        self.message_group = QGroupBox("메시지", self)
        form = QFormLayout(self.message_group)
        _tight(form)
        form.addRow("메시지 이름", self.message_box)
        form.addRow("", self.message_note)
        form.addRow("상관 변수", self.correlation_box)
        form.addRow("받을 값", self.payload_box)
        self._message_form = form

        self.signal_group = QGroupBox("신호", self)
        form = QFormLayout(self.signal_group)
        _tight(form)
        form.addRow("신호 이름", self.signal_box)
        form.addRow("", signal_note)

        self.error_group = QGroupBox("오류", self)
        form = QFormLayout(self.error_group)
        _tight(form)
        form.addRow("오류 코드", self.error_box)
        form.addRow("", error_note)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(head)
        for group in (self.timer_group, self.message_group, self.signal_group, self.error_group):
            layout.addWidget(group)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

        for box in (self.timer_box, self.message_box, self.correlation_box, self.payload_box, self.signal_box):
            box.textChanged.connect(self._touched)
        self.error_box.currentTextChanged.connect(self._touched)
        self.interrupt_box.toggled.connect(self._touched)
        self._refresh()

    # ── 규약 ──

    def load(self, found: Mapping[str, Any]) -> None:
        """`{"type": BPMN 요소, "event": 캔버스 `properties()`의 `event`, "receive": 본문 | None}`."""
        self._quiet = True
        self.bpmn_type = str(found.get("type") or "")
        event = found.get("event")
        self._event = dict(event) if isinstance(event, Mapping) else {}
        receive = found.get("receive")
        self._receive = dict(receive) if isinstance(receive, Mapping) else {}
        self.definition = str(self._event.get("definition") or "")

        timer = self._event.get("timer")
        self.timer_box.setText(str(timer.get("value") or "") if isinstance(timer, Mapping) else "")
        self.message_box.setText(str(self._event.get("message") or ""))
        self.signal_box.setText(str(self._event.get("signal") or ""))
        self.error_box.setCurrentText(str(self._event.get("error") or ""))
        self.interrupt_box.setChecked(self._event.get("cancelActivity") is not False)
        self.correlation_box.setText(str(self._receive.get("correlation") or ""))
        payload = self._receive.get("payload")
        self.payload_box.setText(", ".join(str(one) for one in payload) if isinstance(payload, list) else "")
        self._quiet = False
        self._refresh()

    def section(self) -> str:
        """보이는 섹션 — 엔진이 그 자리에서 읽는 정의일 때만 (`READ_AT`). 아니면 빈 글."""
        return self.definition if self.bpmn_type in READ_AT.get(self.definition, ()) else ""

    def dump(self) -> dict[str, Any]:
        """보이는 섹션의 칸만. `receive`는 **읽은 것 위에** 고친 칸만 얹고, 비면 `None`이다."""
        event: dict[str, Any] = {}
        section = self.section()
        if section == "Timer":
            event["timer"] = {"kind": self._timer_kind(), "value": self.timer_box.text().strip()}
        elif section == "Message":
            event["message"] = self.message_box.text().strip()
        elif section == "Signal":
            event["signal"] = self.signal_box.text().strip()
        elif section == "Error":
            event["error"] = self.error_box.currentText().strip()
        if self._interrupt_choice():
            event["cancelActivity"] = self.interrupt_box.isChecked()
        return {"event": event, "receive": self._receive_body()}

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        section = self.section()
        if section == "Timer":
            self._timer_problems(errors, warnings)
        elif section == "Message":
            if not self.message_box.text().strip():
                errors.append("메시지 이름을 적으세요 — 이름이 없으면 어떤 메시지도 받지 못합니다.")
            if self._receives():
                correlation = self.correlation_box.text().strip()
                if correlation and not is_var_name(correlation):
                    errors.append(f"「상관 변수」는 변수 이름이어야 합니다: {correlation}")
                bad = [name for name in self._payload() if not is_var_name(name)]
                if bad:
                    errors.append(f"「받을 값」에 변수 이름으로 쓸 수 없는 것이 있습니다: {', '.join(bad)}")
        elif section == "Signal":
            if not self.signal_box.text().strip():
                errors.append("신호 이름을 적으세요.")
            if self.bpmn_type == "StartEvent":
                warnings.append(SIGNAL_START)
        elif section == "Error":
            code = self.error_box.currentText().strip()
            if code and code not in ERROR_CODES:
                warnings.append(NOT_STANDARD.format(code=code))
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    # ── 안쪽 ──

    def _wanted_kind(self) -> str:
        """그 자리의 타이머 종류 (C14) — 시작은 주기, 경계·중간은 기한."""
        return CYCLE if self.bpmn_type == "StartEvent" else DURATION

    def _loaded_timer(self) -> tuple[str, str]:
        timer = self._event.get("timer")
        if not isinstance(timer, Mapping):
            return "", ""
        return str(timer.get("kind") or ""), str(timer.get("value") or "")

    def _timer_kind(self) -> str:
        """값을 고치지 않았으면 **적힌 종류 그대로**다 — 조용히 바꾸지 않는다."""
        kind, value = self._loaded_timer()
        if kind and self.timer_box.text().strip() == value:
            return kind
        return self._wanted_kind()

    def _timer_problems(self, errors: list[str], warnings: list[str]) -> None:
        value = self.timer_box.text().strip()
        wanted = self._wanted_kind()
        kind, _ = self._loaded_timer()
        if kind and kind != wanted:
            warnings.append(
                OTHER_TIMER_KIND.format(
                    found=TIMER_KIND_LABELS.get(kind, kind),
                    kind=kind,
                    wanted=TIMER_KIND_LABELS[wanted],
                    wanted_kind=wanted,
                )
            )
        if self._timer_kind() != wanted:
            return  # 적힌 다른 종류를 이 자리의 규칙으로 재지 않는다 (위 경고가 말한다)
        if not value:
            errors.append("타이머 값을 적으세요.")
        elif wanted == DURATION and duration_hours(value) is None and not is_var_name(value):
            errors.append(f"기한은 ISO 기간(PT30M·P3D)이나 변수 이름이어야 합니다: {value}")
        elif wanted == CYCLE and (why := cycle_problem(value)) is not None:
            errors.append(f"주기는 5필드 cron(0 9 * * 1-5)이나 ISO R/…이어야 합니다: {why}")

    def _timer_preview(self) -> str:
        value = self.timer_box.text().strip()
        if self._wanted_kind() == CYCLE:
            return START_TIMER_NOTE
        if not value or self._timer_kind() != DURATION:
            return ""
        hours = duration_hours(value)
        if hours is not None:
            return f"{_after(hours)} 뒤"
        if is_var_name(value):
            return f"실행 때 변수 「{value}」의 값 (기간이나 ISO 시각)"
        return ""

    def _receives(self) -> bool:
        """`bpm:receive`를 읽는 자리 — 메시지를 **기다리는** 것 (시작은 작업이 되므로 읽지 않는다)."""
        return self.section() == "Message" and self.bpmn_type != "StartEvent"

    def _interrupt_choice(self) -> bool:
        return self.bpmn_type == "BoundaryEvent" and self.section() in INTERRUPT_CHOICE

    def _payload(self) -> list[str]:
        return [one.strip() for one in self.payload_box.text().split(",") if one.strip()]

    def _receive_body(self) -> dict[str, Any] | None:
        if not self._receives():
            return self._receive or None
        out = dict(self._receive)
        _put(out, "correlation", self.correlation_box.text().strip() or None)
        _put(out, "payload", self._payload() or None)
        return out or None

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        section = self.section()
        position = POSITIONS.get(self.bpmn_type, self.bpmn_type)
        what = f"{DEFINITIONS.get(self.definition, self.definition)} · {position}"
        attached = str(self._event.get("attachedTo") or "")
        if attached:
            what += f" — 붙은 노드: {attached}"
        self.what.setText(what)
        self.what_note.setText(self._what_note(section))
        self.what_note.setVisible(bool(self.what_note.text()))
        self.interrupt_box.setVisible(self._interrupt_choice())
        self.timer_group.setVisible(section == "Timer")
        self.message_group.setVisible(section == "Message")
        self.signal_group.setVisible(section == "Signal")
        self.error_group.setVisible(section == "Error")
        receives = self._receives()
        for box in (self.correlation_box, self.payload_box):
            box.setVisible(receives)
            label = self._message_form.labelForField(box)
            if label is not None:
                label.setVisible(receives)
        wanted = self._wanted_kind()
        self.timer_kind.setText(
            "주기 (timeCycle) — 5필드 cron 또는 ISO R/…"
            if wanted == CYCLE
            else "기한 (timeDuration) — ISO 기간(PT30M·P3D) 또는 변수 이름"
        )
        self.timer_preview.setText(self._timer_preview())
        self.problems()

    def _what_note(self, section: str) -> str:
        if section:
            return ""
        if self.definition == "Conditional":
            return CONDITIONAL
        if self.definition:
            return NOT_READ
        if self.bpmn_type == "StartEvent":
            return PLAIN_START
        if self.bpmn_type == "IntermediateThrowEvent":
            return MILESTONE
        if self.bpmn_type == "IntermediateCatchEvent":
            return CATCH_UNDEFINED
        return ""


def _after(hours: float) -> str:
    """기간을 사람의 말로 — 분·시간·일 중 하나."""
    if hours < 1:
        return f"{round(hours * 60)}분"
    if hours < 48:
        return f"{hours:g}시간"
    return f"{hours / 24:g}일"


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
    "ALL_FAILURES",
    "CATCH_UNDEFINED",
    "CONDITIONAL",
    "ERROR_CODES",
    "MILESTONE",
    "NOT_READ",
    "NOT_STANDARD",
    "PLAIN_START",
    "SIGNAL_START",
    "START_TIMER_NOTE",
    "TAB_LABEL",
    "TAB_RECEIVE",
    "EventEditor",
]

"""STU-08 실행 대화상자 — 무엇을, 어떻게 돌릴지 고른다.

**고를 수 없는 것은 끄고 바로 아래에 이유를 보인다** (U3) — 조용히 안 되는 것보다 낫다.
지금 끄는 것은 셋이다.

실행 메뉴의 「결정 수행 (재생)...」(Ctrl+F5)은 `prefer`로 들어와 그 모드를 **미리 골라 둔다**
— 할 수 없으면 골라 두지 않는다 (끈 라디오를 고르면 어느 모드도 아니게 된다).

| 끄는 것 | 이유 |
| --- | --- |
| 결정 수행 (재생) | 학습 안 된 AI 태스크가 있다 (`memory/specs.json`에 명세가 없다) |
| 감시 모드 | 트리거를 기다려 되풀이하는 일은 아직 없다 (docs/09-gaps.md §4-5) |
| 「실행」 (케이스 없음일 때) | 기본값 없는 필수 입력이 있다 — 돌리면 엔진이 `input_required`로 거부한다 |

Worker·서비스 앱 줄은 M4·M5에 그 쪽이 생기면 채운다 — 지금 없는 것을 「정상」이라고 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import Case
from chaeksas.qt.theme import set_role
from chaeksas.studio.runner import Plan, read_cases
from chaeksas.studio.settings import Settings
from chaeksas.studio.workspace import BpmProcess, Definition

NO_CASE = "(케이스 없음)"
ALL_CASES = "(모든 케이스 차례로)"

AUTONOMOUS = "autonomous"
DETERMINISTIC = "deterministic"


@dataclass(frozen=True)
class Choice:
    """고른 것 — 메인 창이 `Plan` 목록으로 바꾼다."""

    cases: list[Case]
    mode: str


def unlearned(process: BpmProcess, definition: Definition) -> list[str]:
    """재생 명세가 없는 AI 태스크 이름들 (U3 — 「결정 수행」을 끄는 이유)."""
    if definition.process is None:
        return []
    memory = process.memory()
    return [
        node.name or node.id
        for node in definition.process.all_nodes()
        if node.prop("aiTask") is not None
        and node.prop("aiTask").replay != "none"
        and memory.find(definition.process.id, node.id) is None
    ]


def required_inputs(definition: Definition) -> list[str]:
    """케이스 없이 돌면 비는 필수 입력 — 기본값이 있는 것은 엔진이 채운다 (C14 §6)."""
    if definition.process is None:
        return []
    return [d.name for d in definition.process.info.inputs if d.required and not d.has_default]


def needs_case_text(names: list[str]) -> str:
    return (
        f"필수 입력이 있어 케이스 없이 돌 수 없습니다: {', '.join(names)} "
        "— 「파일 → 시험 케이스...」에서 값을 적은 케이스를 고르세요"
    )


def describe(case: Case | None) -> str:
    if case is None:
        return "기대 결과를 비교하지 않습니다"
    expected = f"기대 결과 {len(case.expected)}개" if case.expected else "기대 결과 없음 — 비교하지 않습니다"
    return f"입력 {len(case.inputs)}개 · {expected}"


class RunDialog(QDialog):
    """STU-08. 폭 460."""

    def __init__(
        self,
        parent: QWidget | None,
        process: BpmProcess,
        definition: Definition,
        settings: Settings,
        *,
        prefer: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.process = process
        self.definition = definition
        self.settings = settings
        self.cases = read_cases(process, definition)
        self.choice: Choice | None = None
        self.setWindowTitle("실행")
        self.setMinimumWidth(460)

        location = (definition.process.info.run_location if definition.process else None) or "pc"
        where = QLabel(
            "실행 위치: PC"
            if location == "pc"
            else "실행 위치: 서버 — 이 시험 실행은 Studio에서 돕니다",
            self,
        )

        self.case_box = QComboBox(self)
        self.case_box.addItem(NO_CASE)
        for case in self.cases:
            self.case_box.addItem(case.name)
        if len(self.cases) > 1:
            self.case_box.addItem(ALL_CASES)
        if self.cases:
            self.case_box.setCurrentIndex(1)
        self.case_note = QLabel("", self)
        self.case_note.setWordWrap(True)
        self.required = required_inputs(definition)
        self.needs_case = QLabel(needs_case_text(self.required) if self.required else "", self)
        set_role(self.needs_case, "error")
        self.needs_case.setWordWrap(True)
        self.case_box.currentIndexChanged.connect(self._retell)

        self.autonomous = QRadioButton("자율 수행 — AI가 방법을 찾고, 성공하면 학습한다", self)
        self.autonomous.setChecked(True)
        self.deterministic = QRadioButton(
            "결정 수행 (재생) — 학습된 대로 LLM 없이 수행한다. BPM 프로세스와 같은 방식", self
        )
        missing = unlearned(process, definition)
        self.deterministic.setEnabled(not missing)
        # 「결정 수행 (재생)...」(Ctrl+F5)로 들어오면 그것을 미리 골라 둔다 — **할 수 있을
        # 때만**이다. 끈 라디오를 고르면 사람이 「실행」을 눌러도 아무 모드가 아니다.
        if prefer == DETERMINISTIC and self.deterministic.isEnabled():
            self.deterministic.setChecked(True)
        reason = QLabel(
            f"학습 안 된 AI 태스크가 있습니다: {', '.join(missing)}" if missing else "", self
        )
        reason.setVisible(bool(missing))
        set_role(reason, "error")
        reason.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        self.run_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.run_button.setText("실행")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(where)
        layout.addWidget(QLabel("케이스", self))
        layout.addWidget(self.case_box)
        layout.addWidget(self.case_note)
        layout.addWidget(self.needs_case)
        layout.addWidget(QLabel("수행 모드", self))
        for radio in (self.autonomous, self.deterministic):
            layout.addWidget(radio)
        layout.addWidget(reason)
        layout.addWidget(buttons)
        self._retell()

    def _retell(self) -> None:
        self.case_note.setText(describe(self.picked_case()))
        blocked = bool(self.required) and self.case_box.currentText() == NO_CASE
        self.needs_case.setVisible(blocked)
        self.run_button.setEnabled(not blocked)

    def picked_case(self) -> Case | None:
        text = self.case_box.currentText()
        return next((c for c in self.cases if c.name == text), None)

    def picked(self) -> Choice:
        text = self.case_box.currentText()
        if text == ALL_CASES:
            cases = list(self.cases)
        else:
            one = self.picked_case()
            cases = [one] if one is not None else []
        return Choice(cases=cases, mode=DETERMINISTIC if self.deterministic.isChecked() else AUTONOMOUS)

    def accept(self) -> None:
        self.choice = self.picked()
        super().accept()

    def plans(self) -> list[Plan]:
        """고른 것 → 돌릴 계획들. 케이스를 안 골랐으면 **케이스 없이 한 번** 돈다."""
        if self.choice is None:
            return []
        cases: list[Case | None] = list(self.choice.cases) or [None]
        return [
            Plan(
                process=self.process,
                definition=self.definition,
                case=case,
                mode=self.choice.mode,
                settings=replace(self.settings),
            )
            for case in cases
        ]

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        process: BpmProcess,
        definition: Definition,
        settings: Settings,
        *,
        prefer: str | None = None,
    ) -> list[Plan]:
        dialog = cls(parent, process, definition, settings, prefer=prefer)
        return dialog.plans() if dialog.exec() == QDialog.DialogCode.Accepted else []


__all__ = [
    "ALL_CASES",
    "AUTONOMOUS",
    "DETERMINISTIC",
    "NO_CASE",
    "Choice",
    "RunDialog",
    "describe",
    "unlearned",
]

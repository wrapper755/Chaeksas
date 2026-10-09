"""STU-08 실행 대화상자 — 무엇을, 어떻게 돌릴지 고른다.

**고를 수 없는 것은 끄고 바로 아래에 이유를 보인다** (U3) — 조용히 안 되는 것보다 낫다.
지금 끄는 것은 둘이다.

| 끄는 것 | 이유 |
| --- | --- |
| 결정 수행 (재생) | 학습 안 된 AI 태스크가 있다 (`memory/specs.json`에 명세가 없다) |
| 감시 모드 | 트리거를 기다려 되풀이하는 일은 아직 없다 (docs/09-gaps.md §4-5) |

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
from chaeksas.studio.runner import Plan, read_cases
from chaeksas.studio.settings import Settings
from chaeksas.studio.workspace import BpmProcess, Definition

NO_CASE = "(케이스 없음)"
ALL_CASES = "(모든 케이스 차례로)"

AUTONOMOUS = "autonomous"
DETERMINISTIC = "deterministic"

WATCH_LATER = "감시 모드(트리거를 기다렸다 되풀이)는 아직 없습니다 (docs/09-gaps.md §4-5)."


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
        self.case_box.currentIndexChanged.connect(self._retell)

        self.autonomous = QRadioButton("자율 수행 — AI가 방법을 찾고, 성공하면 학습한다", self)
        self.autonomous.setChecked(True)
        self.deterministic = QRadioButton(
            "결정 수행 (재생) — 학습된 대로 LLM 없이 수행한다. Bot과 같은 방식", self
        )
        self.watch = QRadioButton("감시 모드 — 트리거를 기다렸다 되풀이 실행", self)
        self.watch.setEnabled(False)
        missing = unlearned(process, definition)
        self.deterministic.setEnabled(not missing)
        reason = QLabel(
            f"학습 안 된 AI 태스크가 있습니다: {', '.join(missing)}" if missing else WATCH_LATER, self
        )
        reason.setProperty("role", "error")
        reason.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("실행")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(where)
        layout.addWidget(QLabel("케이스", self))
        layout.addWidget(self.case_box)
        layout.addWidget(self.case_note)
        layout.addWidget(QLabel("수행 모드", self))
        for radio in (self.autonomous, self.deterministic, self.watch):
            layout.addWidget(radio)
        layout.addWidget(reason)
        layout.addWidget(buttons)
        self._retell()

    def _retell(self) -> None:
        self.case_note.setText(describe(self.picked_case()))

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
    ) -> list[Plan]:
        dialog = cls(parent, process, definition, settings)
        return dialog.plans() if dialog.exec() == QDialog.DialogCode.Accepted else []


__all__ = [
    "ALL_CASES",
    "AUTONOMOUS",
    "DETERMINISTIC",
    "NO_CASE",
    "WATCH_LATER",
    "Choice",
    "RunDialog",
    "describe",
    "unlearned",
]

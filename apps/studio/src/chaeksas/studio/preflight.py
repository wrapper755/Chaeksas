"""실행 전 검사 화면 — C14 B1~B14를 아래 탭에 보인다 (STU-01 「실행 전 검사」, F6).

`validate()`는 계약 쪽에 있고 여기서는 **보여 주는 일만** 한다. 오류와 경고를 **함께** 내고
(`Violation.severity`), **오류만 실행을 막는다** (`blocking()`) — 경고는 보여 주고 사람이
판단한다 (C14 §검사 규칙).

**혼자서는 할 수 없는 검사는 인자로 받는다** — DMN 결정과 호출 대상은 작업 폴더가 준다.
주지 않으면 그 부분을 건너뛰므로, Studio는 늘 준다 (그래야 B14가 돈다).
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from chaeksas.contracts import SEVERITY_ERROR, Violation
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.contracts.bpmn_ext import validate as validate_bpmn
from chaeksas.studio.workspace import BpmProcess

HEADERS = ("", "규칙", "무엇", "어디")

CLEAN = "실행 전 검사: 막는 것도 경고도 없습니다."
#: 노드 id가 메시지 어디에 적혀 있는지 — 「어디」 칸과 더블클릭(캔버스로 이동)이 쓴다.
_NODE_HINT = ("items", "message")


def inspect(process: BpmnProcess, owner: BpmProcess | None = None) -> list[Violation]:
    """B1~B14. 작업 폴더가 있으면 DMN·호출 대조까지 한다 (B14)."""
    if owner is None:
        return validate_bpmn(process)
    return validate_bpmn(
        process,
        dmn_decisions={decision_id: found.io for decision_id, found in owner.decisions().items()},
        called_processes={
            other.id: list(other.info.outputs) for other in owner.processes().values()
        },
    )


def summarize(violations: Sequence[Violation]) -> str:
    """상태 줄 한 줄. **오류만 실행을 막는다.**"""
    errors = sum(1 for v in violations if v.severity == SEVERITY_ERROR)
    warnings = len(violations) - errors
    if not violations:
        return CLEAN
    return f"실행 전 검사: 막는 것 {errors}개, 경고 {warnings}개"


def node_of(process: BpmnProcess, violation: Violation) -> str:
    """위반이 가리키는 노드 id (캔버스로 뛰어가려고). 못 찾으면 빈 글."""
    known = {n.id for n in process.all_nodes()}
    for item in violation.items:
        head = str(item).split(":")[0].strip()
        if head in known:
            return head
    for word in str(violation.message).replace(":", " ").replace(",", " ").split():
        if word.strip("`의가는이") in known:
            return word.strip("`의가는이")
        if word in known:
            return word
    return ""


class Preflight(QTableWidget):
    """아래 탭 「검사」. 줄을 더블클릭하면 캔버스가 그 노드를 고른다."""

    #: 캔버스에서 고를 노드 id.
    jumping = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(HEADERS), parent)
        self.process: BpmnProcess | None = None
        self.setHorizontalHeaderLabels(list(HEADERS))
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.doubleClicked.connect(self._jump)

    def show_result(self, process: BpmnProcess, violations: Sequence[Violation]) -> None:
        self.process = process
        self.setRowCount(len(violations))
        for row, violation in enumerate(violations):
            blocking = violation.severity == SEVERITY_ERROR
            cells = (
                "막음" if blocking else "경고",
                violation.rule,
                violation.message + (f" — {', '.join(violation.items)}" if violation.items else ""),
                node_of(process, violation),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, cells[3])
                self.setItem(row, column, item)
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def _jump(self) -> None:
        item = self.currentItem()
        node_id = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        if node_id:
            self.jumping.emit(node_id)


__all__ = ["CLEAN", "HEADERS", "Preflight", "inspect", "node_of", "summarize"]

"""실행 전 검사 화면 — 아래 탭에 보인다 (STU-01 「실행 전 검사」, F6).

출처가 **셋**이고 여기서 이어 붙인다. 검사 탭과 실행 관문이 한 모양(`Violation`)만 다루게 하려고
여기서 모으는 것이다.

| 무엇 | 어디서 | 왜 따로인가 |
| --- | --- | --- |
| C14 B1~B14 (그림) | `contracts.bpmn_ext.validate` | 형식 검사라 계약 쪽이다 |
| C14 B15 (도우미 호출 모양) | `core.expr_check` | 도우미의 인자 모양을 아는 것은 구현뿐이다 |
| **사전 점검** (이 PC에서 돌 수 있나) | `core.preflight` | 키·확장은 **그림이 아니라 이 PC**의 일이다 |

용어집이 사전 점검에 「서비스 앱 키 참조가 이 PC에 있는지」를 넣어 두었다 — 그래서 **같은 관문**에
들어간다. 「실행 전 검사」 하나만 보면 돌릴 수 있는지 알 수 있어야 한다.

`validate()`는 계약 쪽에 있고 여기서는 **보여 주는 일만** 한다. 오류와 경고를 **함께** 내고
(`Violation.severity`), **오류만 실행을 막는다** — 경고는 보여 주고 사람이 판단한다 (C14 §검사 규칙).

**혼자서는 할 수 없는 검사는 인자로 받는다** — DMN 결정과 호출 대상은 작업 폴더가 준다.
주지 않으면 그 부분을 건너뛰므로, Studio는 늘 준다 (그래야 B14가 돈다).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from chaeksas.contracts import SEVERITY_ERROR, SEVERITY_WARNING, Violation
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.contracts.bpmn_ext import validate as validate_bpmn
from chaeksas.core import preflight as platform
from chaeksas.core.expr_check import check_expressions
from chaeksas.core.extensions import ExtensionHost
from chaeksas.extension_api import SEVERITY_BLOCK, ExtensionContext
from chaeksas.studio.workspace import BpmProcess

HEADERS = ("", "규칙", "무엇", "어디")

CLEAN = "실행 전 검사: 막는 것도 경고도 없습니다."
#: 노드 id가 메시지 어디에 적혀 있는지 — 「어디」 칸과 더블클릭(캔버스로 이동)이 쓴다.
_NODE_HINT = ("items", "message")

#: 사전 점검 결과의 「규칙」 칸. B 규칙과 **한눈에 갈라** 보이게 — 그림의 흠이 아니라 이 PC의 일이다.
PREFLIGHT_RULE = "사전 점검"

#: 키가 없을 때 「어떻게 고치나」 (STU-10). 화면 이름이 들어가므로 **부르는 쪽이** 적는다.
KEY_FIX_HINT = "설정 → 「서비스 앱 키」에 넣으세요"

#: 저장하지 않은 편집이 있을 때. 사전 점검은 **저장된 파일**에서 요구 사항을 모은다.
UNSAVED = (
    "저장하지 않은 편집이 있어 사전 점검은 **저장된 내용**으로 했습니다 — "
    "방금 더한 서비스 앱·키 참조는 세지 않았습니다"
)


def inspect(process: BpmnProcess, owner: BpmProcess | None = None) -> list[Violation]:
    """B1~B15. 작업 폴더가 있으면 DMN·호출 대조까지 한다 (B14)."""
    if owner is None:
        violations = validate_bpmn(process)
    else:
        violations = validate_bpmn(
            process,
            dmn_decisions={decision_id: found.io for decision_id, found in owner.decisions().items()},
            called_processes={
                other.id: list(other.info.outputs) for other in owner.processes().values()
            },
        )
    return violations + check_expressions(process)


def readiness(
    owner: BpmProcess,
    *,
    key_value: Callable[[str], str | None],
    host: ExtensionHost | None = None,
    context: Callable[[str], ExtensionContext] | None = None,
    dirty: bool = False,
) -> list[Violation]:
    """사전 점검 — **이 PC에서 지금 돌릴 수 있나** (`core.preflight`, ADR-0013).

    Bot UI와 **같은 러너**를 쓴다 (BUI-04 「준비」가 쓰는 것) — 키 참조·확장 태스크 종류·`web`·
    `desktop` AI 환경과 확장이 기여한 점검(C13)이다. 결과를 `Violation`으로 옮겨 검사 탭이 한
    모양만 다루게 한다.

    요구 사항은 **저장된 파일**에서 모은다 (`packaging.collect_requires`가 작업 폴더를 읽는다).
    그래서 `dirty`면 그렇게 말해 준다 — 방금 더한 키 참조를 「없다」고 하거나, 방금 지운 것을
    「있다」고 하면 사람이 엉뚱한 데를 고친다.

    **그림을 읽지 못하면 조용히 통과시키지 않는다** — 점검할 수 없었다고 경고로 남긴다.
    """
    from chaeksas.studio.packaging import PackageError, build_manifest  # noqa: PLC0415 - 순환 피함

    out = []
    if dirty:
        out.append(Violation(rule=PREFLIGHT_RULE, code="unsaved", message=UNSAVED, severity=SEVERITY_WARNING))
    try:
        manifest = build_manifest(owner)
    except (PackageError, AssertionError, ValueError) as e:
        # 시작 정의가 없거나 읽히지 않는다 — B 규칙이 이미 말하고 있을 것이다. 덮어쓰지 않는다.
        out.append(
            Violation(
                rule=PREFLIGHT_RULE,
                code="manifest_unavailable",
                message=f"사전 점검을 하지 못했습니다 — 요구 사항을 모을 수 없습니다 ({e})",
                severity=SEVERITY_WARNING,
            )
        )
        return out

    found = platform.check(
        manifest, key_value=key_value, host=host, context=context, fix_hint=KEY_FIX_HINT
    )
    for finding in found.findings:
        hint = f" ({finding.fix_hint})" if finding.fix_hint else ""
        out.append(
            Violation(
                rule=PREFLIGHT_RULE,
                code=finding.id,
                message=f"{finding.message}{hint}",
                items=list(finding.items),
                severity=SEVERITY_ERROR if finding.severity == SEVERITY_BLOCK else SEVERITY_WARNING,
            )
        )
    # 돌리지 못한 점검도 보인다 — 숨기면 「점검했는데 아무 말이 없었다」가 된다 (점검은 막지 않는다).
    for why in found.skipped:
        out.append(
            Violation(
                rule=PREFLIGHT_RULE,
                code="check_skipped",
                message=f"확장의 점검 하나를 돌리지 못했습니다 — {why}",
                severity=SEVERITY_WARNING,
            )
        )
    return out


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


__all__ = [
    "CLEAN",
    "HEADERS",
    "KEY_FIX_HINT",
    "PREFLIGHT_RULE",
    "UNSAVED",
    "Preflight",
    "inspect",
    "node_of",
    "readiness",
    "summarize",
]

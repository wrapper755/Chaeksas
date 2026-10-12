"""STU-09 아래 탭 「UI 태스크」 — 그 시험 실행의 UI 세션을 한 줄씩.

재료는 **C3 `ui_session` 한 줄**이다 (ADR-0041) — UI 태스크가 끝날 때 확장이 주고 **엔진이
쓴다**. 「로그」·「변수」 탭과 같은 길로 온다 (시험 실행이 받는 C3 이벤트,
`runner.CaseRun._on_event`).

**스크린샷을 두지 않는다** (화면 문서 STU-09 「「UI 태스크」 탭」). 이 탭은 「화면」이라는 이름으로
「실행 중 스크린샷」을 보이기로 적혀 있었는데, 그림을 만드는 쪽이 아무도 없고(C10 `StepResult`에
이미지 칸이 없다 — 치유에 가는 것은 **가린 글**이다) C3가 `data`에 스크린샷을 금한다. 그림은
글처럼 가릴 수 없어서 원칙 6도 걸린다. 그래서 「화면」은 **글자 하나**(`page_id`)로 남는다.

**확장이 기여한 칸이 아니다** (ADR-0042). BUI-09 「최근 UI 세션」은 재료가 C10(확장이 소유한
계약)이라 확장이 그리지만, 여기 열은 **C3가 정한 칸**이라 플랫폼이 그려도 Studio가 UI 자동화를
알게 되지 않는다 — CON-01 상세의 「UI 태스크」가 같은 것을 같은 열로 그린다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from chaeksas.qt.theme import status_color

#: 열 — **CON-01 상세의 「UI 태스크」와 같고** 「케이스」 하나가 앞에 더 있다 (Center의 실행 하나는
#: 케이스 하나지만 Studio는 **차례로** 돌리므로, 어느 케이스의 줄인지 모르면 못 읽는다).
#: 케이스 이름은 C3 `ui_session`에 없다 — **부르는 쪽이** 준다 (`run_started`의 `case_id`와 같은 것).
COLUMNS = ("케이스", "노드", "화면", "결과", "스텝 수", "폴백 깊이 최대", "치유")
CASE, NODE, PAGE, RESULT, STEPS, DEPTH, HEALED = range(len(COLUMNS))

#: `status_map`의 묶음. **그 표에 있는 표기만 쓴다** (스타일 가이드 §2-2).
STATUS_GROUP = "UI 세션"
#: C3 `ui_session.result` → 그 표의 표기. 모르는 값은 **그대로** 보인다 (계약 원칙 10).
RESULT_LABEL = {"success": "성공", "escalated": "전환", "failed": "실패"}

#: 값이 없을 때 (U2 — id 자리를 비워 두지 않는다).
NONE = "—"

#: 빈 상태 (U12). **「진행 중」은 없다** — 줄은 세션이 끝날 때 생긴다.
EMPTY = "이 실행에는 UI 태스크가 없습니다."


@dataclass(frozen=True)
class Row:
    """표 한 줄. Qt 없이 시험한다."""

    case: str
    node_id: str
    page_id: str
    result: str
    steps: str
    fallback_depth_max: str
    healed: str

    @property
    def cells(self) -> tuple[str, ...]:
        return (
            self.case,
            self.node_id,
            self.page_id,
            self.result,
            self.steps,
            self.fallback_depth_max,
            self.healed,
        )


def _count(data: Mapping[str, Any], key: str) -> str:
    """센 값 한 칸. 모르는 모양이면 **그대로** 보인다 (고쳐 쓰지 않는다)."""
    found = data.get(key)
    if found is None:
        return NONE
    return str(found)


def row_of(event: Any, *, case: str = "") -> Row:
    """C3 `ui_session` 이벤트 하나 → 표 한 줄.

    `data`는 기록될 때 이미 걸러진 것이고(`core.run_log`의 `sanitize()`), 여기서는 **센 것과
    상태만** 글로 옮긴다 (원칙 6). 필수 키가 빠진 줄은 엔진이 이미 버렸지만, 그래도 없는 칸은
    「—」로 둔다 — 0으로 보이면 「없었다」로 읽힌다.

    `case`는 **이벤트에 없다** — 돌리는 쪽이 아는 것이라 인자로 받는다.
    """
    data: Mapping[str, Any] = event.data if isinstance(event.data, Mapping) else {}
    raw = str(data.get("result") or "")
    return Row(
        case=case or NONE,
        node_id=str(event.node_id or NONE),
        page_id=str(data.get("page_id") or NONE),
        result=RESULT_LABEL.get(raw, raw or NONE),
        steps=_count(data, "steps"),
        fallback_depth_max=_count(data, "fallback_depth_max"),
        healed=("예" if data.get("healed") else "아니오") if "healed" in data else NONE,
    )


class UiSessions(QTableWidget):
    """아래 탭 「UI 태스크」. 세션이 끝날 때마다 한 줄 쌓인다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, len(COLUMNS), parent)
        #: 지금 보이는 것이 빈 상태 한 줄뿐인가.
        self._empty = True
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(PAGE, QHeaderView.ResizeMode.Stretch)
        self.reset_rows()

    def reset_rows(self) -> None:
        """실행을 시작할 때 비운다 — 빈 상태 한 줄만 남는다 (U12)."""
        self.setRowCount(0)
        self.setColumnCount(len(COLUMNS))
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.insertRow(0)
        self.setItem(0, CASE, QTableWidgetItem(EMPTY))
        self.setSpan(0, 0, 1, len(COLUMNS))
        self._empty = True

    def add(self, row: Row) -> None:
        if self._empty:
            self.setSpan(0, 0, 1, 1)
            self.setRowCount(0)
            self._empty = False
        at = self.rowCount()
        self.insertRow(at)
        for column, text in enumerate(row.cells):
            item = QTableWidgetItem(text)
            if column == RESULT:
                # 색은 **그 표기의 것**만 (스타일 가이드 §2-2). 모르는 상태는 색이 없다.
                color = status_color(STATUS_GROUP, text, part="fg")
                if color is not None:
                    item.setForeground(QColor(color))
            self.setItem(at, column, item)
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(PAGE, QHeaderView.ResizeMode.Stretch)


__all__ = [
    "COLUMNS",
    "EMPTY",
    "NONE",
    "RESULT_LABEL",
    "STATUS_GROUP",
    "Row",
    "UiSessions",
    "row_of",
]

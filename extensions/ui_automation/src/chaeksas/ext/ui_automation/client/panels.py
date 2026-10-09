"""플랫폼 화면에 끼우는 칸 — BUI-09 「최근 UI 세션」 (`bot_ui.panels`, ADR-0042).

**이 표는 플랫폼이 그릴 수 없다.** 열(화면·폴백 깊이·치유)이 UI 자동화의 말이라, Bot UI가
그리면 Bot UI가 이 확장을 알게 된다 (ADR-0018). 그래서 Bot UI는 자리(`surface`)만 주고
**칸 안은 여기서** 그린다.

규약은 Studio 편집기(STU-13)와 같고 `refresh()`가 하나 더 있다 — **주기는 호스트가 정한다**
(패널이 타이머를 만들지 않는다). 그래서 `refresh()`는 **빨리 끝나야 한다**: 127.0.0.1의
Worker에 짧은 제한 시간으로 한 번 묻고, 못 받으면 그렇게 적는다 (화면을 붙잡지 않는다).

**업무 값은 보이지 않는다** (원칙 6) — 무엇을 입력했고 읽었는지는 C10 요약에 없다.
"""

from __future__ import annotations

import logging
from typing import Any

from chaeksas.ext.ui_automation.contracts.worker_local import (
    CALLER_BOT,
    CALLER_REGISTRATION,
    CALLER_STUDIO,
    RESULT_ESCALATED,
    RESULT_FAILED,
    RESULT_SUCCESS,
    Status,
)
from chaeksas.extension_api import ExtensionContext

log = logging.getLogger(__name__)

#: 표의 열 — BUI-09 문서 그대로다.
COLUMNS = ("시각", "요청한 쪽", "화면", "결과", "폴백 깊이", "치유")

#: 화면에서 묻는 것이라 **짧게 끊는다** — Worker가 멈추면 GUI가 그만큼 멈춘다.
STATUS_TIMEOUT_S = 1.0

#: 몇 줄까지 보일까 (C10은 최근 20개를 준다).
MAX_ROWS = 20

CALLER_LABEL = {
    CALLER_BOT: "Bot",
    CALLER_STUDIO: "Studio",
    CALLER_REGISTRATION: "셀렉터 등록",
}
RESULT_LABEL = {
    RESULT_SUCCESS: "성공",
    RESULT_ESCALATED: "사람에게 전환",
    RESULT_FAILED: "실패",
}

EMPTY = "아직 UI 세션이 없습니다."
UNREACHABLE = "Worker에 닿지 못해 최근 UI 세션을 읽지 못했습니다."


def rows_of(status: Status) -> list[tuple[str, ...]]:
    """C10 `recent_sessions[]` → 표의 줄들. **새 것이 위**다 (Worker가 그 순서로 준다)."""
    out: list[tuple[str, ...]] = []
    for one in status.recent_sessions[:MAX_ROWS]:
        at = one.at or ""
        out.append(
            (
                at[11:19] if len(at) >= 19 and at[10:11] == "T" else at or "—",
                CALLER_LABEL.get(one.caller, one.caller),
                one.page_id or "—",
                RESULT_LABEL.get(one.result, one.result),
                str(one.fallback_depth_max),
                "예" if one.healed else "아니오",
            )
        )
    return out


class RecentSessionsPanel:
    """`bot_ui.panels` — `extension_api.BotUiPanel`.

    Worker가 어디 있는지는 **호스트가 설정으로 알려 준다** (C13 예약 키 `runtime.worker.*`).
    `runtime: "worker"`라서 **Worker가 떠 있을 때만** 이 칸이 보인다 — 꺼져 있을 때 빈 표를
    보이는 것보다 칸이 없는 것이 정직하다 (ADR-0042).
    """

    def __init__(self, client: Any = None) -> None:
        self._table: Any = None
        self._note: Any = None
        #: Worker를 부르는 쪽. **호스트는 인자 없이 만든다** — 시험이 여기 끼운다.
        self._worker: Any = client

    def widget(self, ctx: ExtensionContext) -> object:
        from PySide6.QtWidgets import (  # noqa: PLC0415
            QAbstractItemView,
            QHeaderView,
            QLabel,
            QTableWidget,
            QVBoxLayout,
            QWidget,
        )

        from chaeksas.ext.ui_automation.client.registration_window import worker_client  # noqa: PLC0415

        if self._worker is None:
            self._worker = worker_client(ctx.settings)
            self._worker.timeout_s = STATUS_TIMEOUT_S

        made = QWidget()
        layout = QVBoxLayout(made)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)
        self._note = QLabel(EMPTY)
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        self.refresh()
        return made

    def refresh(self) -> None:
        """Worker에게 한 번 묻고 표를 다시 쓴다. **못 받으면 그렇게 적는다.**"""
        if self._table is None:
            return
        found = self._status()
        if found is None:
            self._fill([])
            self._say(UNREACHABLE)
            return
        rows = rows_of(found)
        self._fill(rows)
        self._say("" if rows else EMPTY)

    def _status(self) -> Status | None:
        try:
            return Status.model_validate(self._worker.call("GET", "/v1/status"))
        except Exception as e:  # noqa: BLE001 — 화면 한 칸이 Bot UI를 깨면 안 된다
            log.debug("Worker 상태를 읽지 못했다: %s", e)
            return None

    def _fill(self, rows: list[tuple[str, ...]]) -> None:
        from PySide6.QtWidgets import QTableWidgetItem  # noqa: PLC0415

        self._table.setRowCount(len(rows))
        for row, cells in enumerate(rows):
            for column, text in enumerate(cells):
                self._table.setItem(row, column, QTableWidgetItem(text))

    def _say(self, message: str) -> None:
        self._note.setText(message)
        self._note.setVisible(bool(message))


__all__ = ["COLUMNS", "EMPTY", "MAX_ROWS", "UNREACHABLE", "RecentSessionsPanel", "rows_of"]

"""BUI-01 트레이. **상태가 바뀔 때마다 메뉴를 다시 만든다** (설계서 그대로).

아이콘은 앱 아이콘 + 상태 점(색)이다. 색은 토큰에서 온다 (`chaeksas.qt.theme.status_color`) —
값을 코드에 적지 않는다 (CLAUDE.md §5).

트레이가 없는 환경이면 이 클래스를 만들지 않고 메인 창을 띄운다 (U15) — `app.py`가 고른다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from chaeksas.bot_ui.agent import (
    TRAY_DISABLED,
    TRAY_DISCONNECTED,
    TRAY_ERROR,
    TRAY_KEY_EXPIRED,
    TRAY_KEY_REVOKED,
    TRAY_UNREGISTERED,
    Agent,
)
from chaeksas.qt import theme

log = logging.getLogger(__name__)

#: 아이콘 크기와 상태 점 크기 (장치 비율은 Qt가 맞춘다).
ICON_PX = 64
DOT_PX = 26

#: 트레이 상태 글 → `status_map`의 (묶음, 표기). 색을 그 표에서만 가져온다.
STATUS_TOKENS: dict[str, tuple[str, str]] = {
    TRAY_UNREGISTERED: ("Bot UI", "등록 전"),
    TRAY_DISCONNECTED: ("Bot UI", "연결 끊김"),
    TRAY_KEY_REVOKED: ("Bot UI", "키 폐기됨"),
    TRAY_KEY_EXPIRED: ("Bot UI", "키 만료"),
    TRAY_DISABLED: ("Bot UI", "비활성"),
    TRAY_ERROR: ("Bot", "오류"),
}


def status_color(status: str, *, current_theme: str = theme.THEME_LIGHT) -> str:
    """상태 글의 점 색. 모르는 글이면 「실행 중」·「대기」로 떨어진다 (계약 원칙 10)."""
    group, label = STATUS_TOKENS.get(status, ("", ""))
    if group:
        found = theme.status_color(group, label, theme=current_theme)
        if found:
            return found
    if status.startswith("실행 중") or status.startswith("셀렉터 등록"):
        return theme.status_color("Bot", "실행 중", theme=current_theme) or "#000000"
    if status.endswith("대기") or status.startswith("대기"):
        return theme.status_color("Bot", "대기", theme=current_theme) or "#000000"
    return theme.status_color("Bot UI", "연결됨", theme=current_theme) or "#000000"


def tray_icon(status: str, *, current_theme: str = theme.THEME_LIGHT) -> QIcon:
    """앱 아이콘 자리 + 상태 점. 아이콘 파일은 아직 없어 둥근 사각형으로 그린다."""
    pixmap = QPixmap(ICON_PX, ICON_PX)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    base = theme.tokens.colors(dark=current_theme == theme.THEME_DARK)
    painter.setBrush(QColor(base["primary"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(2, 2, ICON_PX - 4, ICON_PX - 4), 12, 12)

    painter.setBrush(QColor(status_color(status, current_theme=current_theme)))
    painter.drawEllipse(QRectF(ICON_PX - DOT_PX - 2, ICON_PX - DOT_PX - 2, DOT_PX, DOT_PX))
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    """트레이 아이콘과 메뉴 (BUI-01).

    메뉴의 **비활성 줄은 정보**다 (상태·실행 중·대기열·Worker·Center). 누를 수 있는 것은
    「창 열기」·「도구」·「설정...」·「종료」뿐이다 — 나머지는 M3~M5에 붙는다.
    """

    open_window = Signal()
    open_settings = Signal()
    open_extensions = Signal()
    quit_requested = Signal()

    def __init__(self, agent: Agent, *, current_theme: str = theme.THEME_LIGHT) -> None:
        super().__init__()
        self._agent = agent
        self._theme = current_theme
        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self.refresh()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_window.emit()

    def refresh(self) -> None:
        """상태가 바뀔 때마다 (하트비트마다) 부른다."""
        status = self._agent.tray_status()
        self.setIcon(tray_icon(status, current_theme=self._theme))
        self.setToolTip(f"Chaeksas Bot UI · {status}")
        self._rebuild(status)

    def _info(self, text: str) -> None:
        action = QAction(text, self._menu)
        action.setEnabled(False)
        self._menu.addAction(action)

    def _rebuild(self, status: str) -> None:
        from chaeksas.bot_ui import machine  # noqa: PLC0415 — PC 이름만 쓴다

        self._menu.clear()
        agent = self._agent

        self._info(f"Chaeksas Bot UI · {agent.settings.name or machine.pc_name()} · {status}")

        run = agent.current_run
        if run is None:
            self._info("실행 중인 Bot 없음")
        else:
            node = f" @ {run.node_id}" if run.node_id else ""
            self._info(f"실행 중: {run.bpm_process_id} {run.version}{node}")

        waiting = agent.queue
        if waiting:
            nxt = waiting[0].bpm_process_id
            self._info(f"대기열 {len(waiting)}건 — 다음: {nxt}")

        worker = agent.settings.runtime("worker")
        state = agent.worker_state()
        if worker is not None:
            label = {
                "running": f"실행 중 (포트 {worker.port})",
                "restarting": "다시 띄우는 중",
                "stopped": "멈춤",
                "off": "꺼 둠 (필요할 때 시작)",
            }.get(state.state, state.state)
            self._info(f"Worker: {label}")

        last = agent.last_beat_at
        self._info(f"Center: 연결됨 (마지막 {last[11:19]})" if last else "Center: 연결 끊김")

        self._menu.addSeparator()
        self._menu.addAction("창 열기", self.open_window.emit)

        tools = self._menu.addMenu("도구")
        if agent.extensions:
            # 유틸리티는 확장이 기여한다 (ADR-0018). 아직 기여하는 확장이 없다.
            for found in agent.extensions:
                entry = tools.addAction(found.id)
                entry.setEnabled(False)
        else:
            empty = tools.addAction("확장이 더한 유틸리티가 없습니다 (M4)")
            empty.setEnabled(False)
        tools.addSeparator()
        extensions = tools.addAction("확장...")
        extensions.setEnabled(False)
        extensions.setToolTip("확장 목록(BUI-11)은 M4에서 만듭니다.")

        self._menu.addAction("설정...", self.open_settings.emit)
        self._menu.addSeparator()
        self._menu.addAction("종료", self.quit_requested.emit)


__all__ = ["DOT_PX", "ICON_PX", "STATUS_TOKENS", "Tray", "status_color", "tray_icon"]

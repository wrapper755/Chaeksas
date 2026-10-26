"""TOL-01 Tool UI 창 — 도구마다 탭 하나 (ADR-0077).

Tool UI는 **어느 확장인지 모른다** — `tool_ui.tools` 기여의 `label`로 메뉴를 그리고, 고르면 그
도구가 준 위젯을 탭에 붙인다.

- **런타임이 없으면 도구를 열지 않는다** — 그 자리(빈 상태 안내)에 까닭과 길을 쓴다 (U3).
- 같은 도구는 두 번 열지 않고 그 탭으로 간다. 탭을 닫으면 도구의 `closed()`를 부른다 (UI 세션을 놓는다).
- 도구를 만들다 터지면 **그 탭만** 사유를 보이고 창은 이어 그린다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.qt.theme import set_role
from chaeksas.tool_ui.host import ToolHost

log = logging.getLogger(__name__)

WINDOW_TITLE = "Chaeksas Tool UI"
WINDOW_SIZE = (1100, 760)
#: 상태 줄을 다시 재는 간격 (ms) — 런타임이 떴나 꺼졌나.
STATUS_MS = 5000

EMPTY_PICK = "「도구」 메뉴에서 열 도구를 고르세요."
NO_TOOLS = "이 PC의 확장이 더한 도구가 없습니다."
TOOL_BROKEN = "이 도구를 열지 못했습니다 —"
TOOL_NO_WIDGET = "이 도구가 화면을 주지 않았습니다."
RUNTIME_UP = "{label} 127.0.0.1:{port} · 실행 중"
RUNTIME_OFF = "{label} 꺼짐 — Bot UI 「도구」에서 열면 Bot UI가 띄웁니다"


class ToolWindow(QMainWindow):
    """도구 탭들을 쥔 창 하나. 열린 도구는 `(확장, 도구)`로 찾는다."""

    def __init__(self, tools: ToolHost, *, open_settings: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.tools = tools
        self._open_settings = open_settings
        #: 열린 탭 — `(확장, 도구)` → (위젯, 도구 객체).
        self._open: dict[tuple[str, str], tuple[QWidget, object]] = {}
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_SIZE)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)

        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        self.empty_note = QLabel()
        self.empty_note.setWordWrap(True)
        empty_layout.addWidget(self.empty_note)
        self.empty_buttons = QVBoxLayout()
        empty_layout.addLayout(self.empty_buttons)
        #: 도구를 열지 못한 까닭 (U3 — 툴팁에 숨기지 않는다).
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        set_role(self.problem, "error")
        self.problem.hide()
        empty_layout.addWidget(self.problem)
        empty_layout.addStretch(1)

        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        layout.addWidget(self.empty)
        self.setCentralWidget(holder)

        self._build_menu()
        self._fill_empty()
        self._sync()
        self.refresh_status()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_status)
        self._timer.start(STATUS_MS)

    # ── 짓기 ──

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        file_menu.addAction("설정...", self.open_settings)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("닫기", self.close)
        quit_action.setShortcut("Ctrl+Q")
        tools = self.menuBar().addMenu("도구")
        for found in self.tools.tools():
            action = tools.addAction(f"{found.value.label}...")
            action.setToolTip(f"{found.extension_id} 확장")
            action.triggered.connect(
                lambda _=False, e=found.extension_id, t=found.value.id: self.open_tool(e, t)
            )
        if not tools.actions():
            none = tools.addAction(NO_TOOLS)
            none.setEnabled(False)

    def _fill_empty(self) -> None:
        found = self.tools.tools()
        self.empty_note.setText(EMPTY_PICK if found else NO_TOOLS)
        for one in found:
            button = QPushButton(f"{one.value.label}...")
            button.clicked.connect(lambda _=False, e=one.extension_id, t=one.value.id: self.open_tool(e, t))
            self.empty_buttons.addWidget(button)

    def _sync(self) -> None:
        """탭이 없으면 빈 상태를, 있으면 탭을 보인다."""
        has_tabs = self.tabs.count() > 0
        self.tabs.setVisible(has_tabs)
        self.empty.setVisible(not has_tabs)

    def say(self, text: str) -> None:
        """도구를 열지 못한 까닭 — 빈 상태 아래, 탭이 있으면 상태 줄에."""
        self.problem.setText(text)
        self.problem.setVisible(bool(text))
        if text:
            self.statusBar().showMessage(text)

    # ── 도구 ──

    def open_tool(self, extension_id: str, tool_id: str) -> bool:
        """도구 하나를 탭으로 연다. 열었거나 이미 열려 있으면 `True`."""
        key = (extension_id, tool_id)
        opened = self._open.get(key)
        if opened is not None:
            self.tabs.setCurrentWidget(opened[0])
            return True
        found = self.tools.find(extension_id, tool_id)
        if found is None:
            self.say(f"그 도구가 없습니다 — {extension_id}:{tool_id} (확장이 꺼졌거나 깔리지 않았습니다)")
            return False
        needs = found.value.needs_runtime
        problem = self.tools.runtime_problem(needs)
        if problem:
            # **열지 않는다** — 빈 창을 띄워 놓고 「안 되네」 하게 두지 않는다.
            self.say(problem)
            return False
        self.say("")
        tool: object | None = None
        try:
            tool = self.tools.make(extension_id, tool_id)
            made = tool.widget(self.tools.context(extension_id, runtime_ids=(needs,) if needs else ()))
        except Exception as e:  # noqa: BLE001 — 도구가 깨져도 창은 산다
            log.exception("도구를 열지 못했다: %s:%s", extension_id, tool_id)
            made = QLabel(f"{TOOL_BROKEN} {e}")
            made.setWordWrap(True)
        if not isinstance(made, QWidget):
            made = QLabel(TOOL_NO_WIDGET)
        self._open[key] = (made, tool)
        self.tabs.addTab(made, found.value.label)
        self.tabs.setCurrentWidget(made)
        self._sync()
        return True

    def close_tab(self, index: int) -> None:
        """탭을 닫으면 도구가 **자리를 놓는다** (Worker의 UI 세션은 한 번에 하나다)."""
        widget = self.tabs.widget(index)
        key = next((k for k, (w, _) in self._open.items() if w is widget), None)
        if key is not None:
            _, tool = self._open.pop(key)
            _close(tool)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()
        self._sync()

    def open_keys(self) -> list[tuple[str, str]]:
        """지금 열린 도구들 (시험·로그가 본다)."""
        return list(self._open)

    def bring_forward(self) -> None:
        """두 번째 실행이 부르면 앞으로 (한 세션에 하나)."""
        self.show()
        self.raise_()
        self.activateWindow()

    # ── 상태 줄 ──

    def refresh_status(self) -> None:
        """도구가 쓰는 런타임마다 한 줄 — 떴나 꺼졌나 (TOL-01 [S])."""
        needed = sorted({c.value.needs_runtime for c in self.tools.tools() if c.value.needs_runtime})
        parts = []
        for runtime_id in needed:
            runtime = next((c.value for c in self.tools.host.local_runtimes() if c.value.id == runtime_id), None)
            if runtime is None:
                continue
            port = self.tools.runtime_port(runtime)
            up = self.tools.runtime_problem(runtime_id) is None
            parts.append((RUNTIME_UP if up else RUNTIME_OFF).format(label=runtime.label, port=port))
        if parts and not self.problem.text():
            self.statusBar().showMessage(" · ".join(parts))

    # ── 설정 ──

    def open_settings(self) -> None:
        if self._open_settings is not None:
            self._open_settings()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt 이름
        """창을 닫으면 모든 도구를 닫고 끝난다 — **트레이에 남지 않는다**."""
        for _, tool in list(self._open.values()):
            _close(tool)
        self._open.clear()
        self._timer.stop()
        event.accept()


def _close(tool: object | None) -> None:
    closing = getattr(tool, "closed", None)
    if callable(closing):
        try:
            closing()
        except Exception:  # noqa: BLE001 — 닫다 실패해도 탭은 닫힌다
            log.exception("도구를 닫다 실패했다")


__all__ = [
    "EMPTY_PICK",
    "NO_TOOLS",
    "RUNTIME_OFF",
    "RUNTIME_UP",
    "TOOL_BROKEN",
    "TOOL_NO_WIDGET",
    "WINDOW_TITLE",
    "ToolWindow",
]

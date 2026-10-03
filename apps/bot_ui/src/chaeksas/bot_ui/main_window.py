"""BUI-02 메인 창 + BUI-04의 「지금 실행·대기열」. **창을 닫아도 Bot UI는 트레이에서 돈다.**

M2에서 채우는 것은 실행 자리·대기열·로컬 런타임·상태 줄이다. 설치된 Bot 목록과 실행 기록은
배포(M5)·엔진(M3)이 생겨야 내용이 있으므로 **빈 상태로 이유를 적어 둔다** (U3).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.settings_dialog import SettingsDialog

log = logging.getLogger(__name__)

WINDOW_TITLE = "Chaeksas Bot UI"
WINDOW_SIZE = (1000, 720)

#: BUI-04 대기열 표의 열 (「입력 키」의 값은 접는다 — U10).
QUEUE_COLUMNS = ("#", "Bot", "출처", "요청 시각", "만료", "입력 키")

SOURCE_LABEL = {
    "job": "Center 작업",
    "manual": "수동",
    "watch": "감시",
    "schedule": "일정",
    "message": "메시지",
}


class MainWindow(QMainWindow):
    """메인 창. 데이터는 `Agent`에서만 읽는다 (화면은 보여 주기만)."""

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_SIZE)

        self._build_menu()
        tabs = QTabWidget()
        tabs.addTab(self._bots_tab(), "Bot")
        tabs.addTab(self._later_tab("실행 기록은 BPMN 엔진이 도는 M3에서 채워집니다."), "실행 기록")
        tabs.addTab(self._runtimes_tab(), "로컬 런타임")
        self.setCentralWidget(tabs)

        self.statusBar().showMessage(agent.status_line())
        self.refresh()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        file_menu.addAction("설정...", self.open_settings)
        later = file_menu.addAction("로그 폴더 열기")
        later.setEnabled(False)
        later.setToolTip("실행 기록이 생기는 M3에서 켭니다.")
        file_menu.addSeparator()
        quit_action = file_menu.addAction("종료", self.close)
        quit_action.setShortcut("Ctrl+Q")

        tools = self.menuBar().addMenu("도구")
        for text, why in (("서비스 앱 키...", "BUI-10 — M4"), ("확장...", "BUI-11 — M4")):
            action = tools.addAction(text)
            action.setEnabled(False)
            action.setToolTip(f"{why}에서 만듭니다.")

    # ── 탭 ──

    def _bots_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.running_label = QLabel()
        self.running_label.setWordWrap(True)
        layout.addWidget(self.running_label)

        self.queue_title = QLabel()
        layout.addWidget(self.queue_title)

        self.queue_table = QTableWidget(0, len(QUEUE_COLUMNS))
        self.queue_table.setHorizontalHeaderLabels(list(QUEUE_COLUMNS))
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.queue_table)

        self.cancel_button = QPushButton("취소...")
        self.cancel_button.clicked.connect(self.cancel_selected)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignLeft)

        installed = QLabel(
            "설치된 Bot이 없습니다. Center 배포로 받는 것은 M5, 「패키지 파일에서 설치...」는 M3입니다."
        )
        installed.setWordWrap(True)
        installed.setEnabled(False)
        layout.addWidget(installed)
        return page

    def _runtimes_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.runtime_label = QLabel()
        self.runtime_label.setWordWrap(True)
        layout.addWidget(self.runtime_label)
        note = QLabel("Worker 프로세스를 띄우는 것은 UI 자동화 확장이 붙는 M4입니다.")
        note.setEnabled(False)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _later_tab(self, why: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(why)
        label.setEnabled(False)
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    # ── 보여 주기 ──

    def refresh(self) -> None:
        """하트비트마다 부른다 (GUI 스레드에서)."""
        agent = self._agent
        run = agent.current_run
        if run is None:
            self.running_label.setText("실행 중인 Bot이 없습니다.")
        else:
            node = f" @ {run.node_id}" if run.node_id else ""
            source = SOURCE_LABEL.get(run.source, run.source)
            self.running_label.setText(f"{run.bpm_process_id} {run.version}{node} · 출처 {source}")

        items = agent.queue
        self.queue_title.setText(f"대기 {len(items)}/{agent.settings.queue_max}")
        self.queue_table.setRowCount(len(items))
        for row, item in enumerate(items):
            keys = ", ".join(sorted(agent.store.state.inputs.get(item.queue_id, {}))) or "—"
            cells = (
                str(row + 1),
                f"{item.bpm_process_id} {item.version or ''}".strip(),
                SOURCE_LABEL.get(item.source, item.source),
                item.requested_at[11:19],
                (item.expires_at or "—")[11:19] if item.expires_at else "—",
                keys,  # **값은 보이지 않는다** (U10 — 키 이름만)
            )
            for column, text in enumerate(cells):
                self.queue_table.setItem(row, column, QTableWidgetItem(text))

        self.cancel_button.setEnabled(bool(items))
        if not items:
            self.cancel_button.setToolTip("기다리는 실행이 없습니다.")

        state = agent.worker_state()
        worker = agent.settings.runtime("worker")
        port = f" (포트 {worker.port})" if worker else ""
        self.runtime_label.setText(f"Worker: {state.state}{port} · 다시 띄운 횟수 {state.restarts}")
        self.statusBar().showMessage(agent.status_line())

    # ── 동작 ──

    def open_settings(self) -> None:
        dialog = SettingsDialog(self._agent, self)
        if dialog.exec():
            self.refresh()

    def cancel_selected(self) -> None:
        """대기열 항목 취소 (BUI-04). Center 작업이면 그렇게 알린다고 먼저 말한다."""
        row = self.queue_table.currentRow()
        items = self._agent.queue
        if row < 0 or row >= len(items):
            return
        item = items[row]
        extra = "\nCenter에 「현장에서 취소함」으로 알립니다." if item.job_id else ""
        answer = QMessageBox.question(
            self,
            "대기열 항목을 취소할까요?",
            f"{item.bpm_process_id}을 대기열에서 뺍니다.{extra}",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,  # 기본은 「취소」 (U 규칙)
        )
        if answer == QMessageBox.StandardButton.Ok:
            self._agent.cancel_queued(item.queue_id)
            self.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt 이름
        """창을 닫아도 **앱은 트레이에서 계속 돈다** (BUI-02). 종료는 트레이 메뉴에서."""
        if self._agent.settings and QSystemTrayIconAvailable():
            event.ignore()
            self.hide()
            return
        event.accept()  # pragma: no cover - 트레이가 없는 환경


def QSystemTrayIconAvailable() -> bool:  # noqa: N802 — Qt 쪽 이름에 맞춘다
    from PySide6.QtWidgets import QSystemTrayIcon  # noqa: PLC0415

    return QSystemTrayIcon.isSystemTrayAvailable()


__all__ = ["QUEUE_COLUMNS", "SOURCE_LABEL", "WINDOW_SIZE", "WINDOW_TITLE", "MainWindow"]

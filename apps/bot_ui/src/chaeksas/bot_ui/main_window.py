"""BUI-02 메인 창 + BUI-04 Bot 탭. **창을 닫아도 Bot UI는 트레이에서 돈다.**

실행 자리·대기열·**설치된 Bot**·로컬 런타임·상태 줄이 있다. 결재를 기다리는 중이면 「결재 창
열기」가 CMN-01을 띄운다 (`packages/qt` — Studio와 **같은 창**이다).

**화면은 Agent에서만 읽는다.** 상태는 실행기가 쓴 기록 파일에서 오고(ADR-0031), 화면은 그것을
그릴 뿐이다 — 느린 실행기가 화면을 붙잡지 않는다.

Center 배포로 Bot을 받는 것은 M5다 — 지금은 「패키지 파일에서 설치...」로 넣는다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
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
from chaeksas.bot_ui.bots import InstalledBot, InstallError, install, installed
from chaeksas.bot_ui.runner import Running
from chaeksas.bot_ui.settings_dialog import SettingsDialog
from chaeksas.contracts.approvals import Form
from chaeksas.qt.approval import ApprovalDialog

log = logging.getLogger(__name__)

WINDOW_TITLE = "Chaeksas Bot UI"
WINDOW_SIZE = (1000, 720)

#: BUI-04 대기열 표의 열 (「입력 키」의 값은 접는다 — U10).
QUEUE_COLUMNS = ("#", "Bot", "출처", "요청 시각", "만료", "입력 키")

#: BUI-04 설치된 Bot 표의 열. 「준비」·「최근 실행」은 M5다 — 모르는 것을 적지 않는다.
BOT_COLUMNS = ("Bot", "버전", "출처", "서명", "상태")

PACKAGE_FILTER = "패키지 (*.zip)"

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

        running_buttons = QHBoxLayout()
        self.approve_button = QPushButton("결재 창 열기")
        self.approve_button.clicked.connect(self.open_approval)
        self.stop_button = QPushButton("중지...")
        self.stop_button.clicked.connect(self.stop_running)
        running_buttons.addWidget(self.approve_button)
        running_buttons.addWidget(self.stop_button)
        running_buttons.addStretch(1)
        layout.addLayout(running_buttons)

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

        self.bots_title = QLabel("설치된 Bot")
        layout.addWidget(self.bots_title)

        self.bots_table = QTableWidget(0, len(BOT_COLUMNS))
        self.bots_table.setHorizontalHeaderLabels(list(BOT_COLUMNS))
        self.bots_table.verticalHeader().setVisible(False)
        self.bots_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.bots_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.bots_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.bots_table.itemSelectionChanged.connect(self._bots_changed)
        layout.addWidget(self.bots_table)

        row = QHBoxLayout()
        self.run_button = QPushButton("지금 실행...")
        self.run_button.clicked.connect(self.run_selected)
        self.install_button = QPushButton("패키지 파일에서 설치...")
        self.install_button.clicked.connect(self.install_package)
        row.addWidget(self.run_button)
        row.addWidget(self.install_button)
        row.addStretch(1)
        layout.addLayout(row)
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

        self._refresh_bots()
        self._refresh_running_buttons()

        state = agent.worker_state()
        worker = agent.settings.runtime("worker")
        port = f" (포트 {worker.port})" if worker else ""
        self.runtime_label.setText(f"Worker: {state.state}{port} · 다시 띄운 횟수 {state.restarts}")
        self.statusBar().showMessage(agent.status_line())

    def _refresh_bots(self) -> None:
        """설치된 Bot 목록 (BUI-04 [L]). **모르는 것은 적지 않는다** — 준비·최근 실행은 M5."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        self._bots = installed(data_dir())
        running = self._agent.current_run
        self.bots_title.setText(
            f"설치된 Bot {len(self._bots)}개"
            if self._bots
            else "설치된 Bot이 없습니다. 「패키지 파일에서 설치...」로 설치하세요 (Center 배포는 M5)."
        )
        self.bots_table.setRowCount(len(self._bots))
        for row, bot in enumerate(self._bots):
            queued = [i for i, item in enumerate(self._agent.queue) if item.bpm_process_id == bot.id]
            if running is not None and running.bpm_process_id == bot.id:
                state = "실행 중"
            elif queued:
                state = f"대기열 {queued[0] + 1}번째"
            else:
                state = "대기"
            for column, text in enumerate((bot.name, bot.version, "수동 설치", bot.signature, state)):
                self.bots_table.setItem(row, column, QTableWidgetItem(text))
        self._bots_changed()

    def _bots_changed(self) -> None:
        chosen = self.selected_bot()
        self.run_button.setEnabled(chosen is not None)
        self.run_button.setToolTip("" if chosen else "실행할 Bot을 고르세요.")

    def _refresh_running_buttons(self) -> None:
        running = self._agent.runner().running
        asked = running.pendings if running is not None else []
        self.stop_button.setEnabled(running is not None)
        self.approve_button.setEnabled(bool(asked))
        self.approve_button.setToolTip("" if asked else "기다리는 결재·확인이 없습니다.")
        if asked:
            self.running_label.setText(f"{self.running_label.text()} · 결재를 기다리는 중")

    def selected_bot(self) -> InstalledBot | None:
        rows = {index.row() for index in self.bots_table.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._bots[row] if 0 <= row < len(self._bots) else None

    # ── 동작 ──

    def install_package(self) -> None:
        """BUI-04 「패키지 파일에서 설치...」. **푸는 쪽에서** 해시·경로를 본다 (C1 R6)."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        chosen, _ = QFileDialog.getOpenFileName(self, "패키지 파일에서 설치", "", PACKAGE_FILTER)
        if not chosen:
            return
        try:
            bot = install(data_dir(), Path(chosen))
        except InstallError as e:
            QMessageBox.warning(self, WINDOW_TITLE, str(e))
            return
        self.refresh()
        self.statusBar().showMessage(f"{bot.name} {bot.version}을 설치했습니다.")

    def run_selected(self) -> None:
        """BUI-04 「지금 실행...」 — 대기열에 넣는다. 자리가 비면 다음 주기에 뜬다."""
        bot = self.selected_bot()
        if bot is None:
            return
        try:
            self._agent.enqueue_manual(bot.id, version=bot.version)
        except RuntimeError as e:
            QMessageBox.warning(self, WINDOW_TITLE, str(e))
            return
        self._agent.pump()
        self.refresh()

    def stop_running(self) -> None:
        """BUI-04 「중지」 — 확인 창, 기본 「취소」 (U4)."""
        running = self._agent.runner().running
        if running is None:
            return
        answer = QMessageBox.question(
            self,
            WINDOW_TITLE,
            f"실행 중인 Bot 「{running.bot.name}」을 멈출까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._agent.runner().stop()
        self._agent.release_slot()
        self.refresh()

    def open_approval(self) -> None:
        """BUI-04 「결재 창 열기」 → CMN-01. **답은 제어 파일로** 내려간다 (ADR-0031)."""
        running = self._agent.runner().running
        if running is None or not running.pendings:
            return
        asked = running.pendings[0]
        node = running.bot.id
        form = self._form_of(running, asked.node_id)
        answer = ApprovalDialog.ask(
            self,
            title=f"{running.bot.name} — {asked.node_id}",
            description=f"{node}의 {'확인' if asked.is_confirmation else '결재'} 요청입니다.",
            form=form,
            layer=asked.layer,
        )
        if answer is None:
            return  # 창을 그냥 닫았다 — **답하지 않은 것이다** (요청은 그대로 남는다)
        running.answer(asked.request_id, answer, answered_by=self._agent.display_name())
        self.refresh()

    def _form_of(self, running: Running, node_id: str) -> Form | None:
        """그 노드의 결재 폼 (C6). 패키지의 BPMN에서 읽는다 — **화면이 지어내지 않는다**."""
        from chaeksas.contracts.bpmn_ext import read_process  # noqa: PLC0415

        bot = running.bot
        try:
            found = read_process(bot.entry_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 폼을 못 읽어도 창은 떠야 한다 (승인/반려)
            return None
        node = next((n for n in found.all_nodes() if n.id == node_id), None)
        approval = node.prop("approval") if node is not None else None
        return Form(fields=list(approval.fields)) if approval is not None else None

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

"""BUI-02 메인 창 + BUI-04 Bot 탭. **창을 닫아도 Bot UI는 트레이에서 돈다.**

실행 자리·대기열·**설치된 Bot**·로컬 런타임·상태 줄이 있다. 결재를 기다리는 중이면 「결재 창
열기」가 CMN-01을 띄운다 (`packages/qt` — Studio와 **같은 창**이다).

**화면은 Agent에서만 읽는다.** 상태는 실행기가 쓴 기록 파일에서 오고(ADR-0031), 화면은 그것을
그릴 뿐이다 — 느린 실행기가 화면을 붙잡지 않는다.

「준비」 열은 **사전 점검**(`core.preflight`)이 말하는 것이고, 표기는 `status_map`의 「Bot 준비」에
있는 것만 쓴다 (`docs/07-style-guide.md`). 키가 없으면 그 줄에서 바로 BUI-10으로 갈 수 있다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.bot_ui import run_log_view
from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.bots import (
    MANUAL,
    InstalledBot,
    InstallError,
    install,
    installed,
    write_source,
)
from chaeksas.bot_ui.keys_dialog import KeysDialog
from chaeksas.bot_ui.runner import Running
from chaeksas.bot_ui.runtimes import RuntimeUnavailable, port_for
from chaeksas.bot_ui.settings_dialog import SettingsDialog
from chaeksas.contracts.approvals import Form
from chaeksas.core.preflight import (
    EXTENSIONS_UNUSABLE,
    MISSING_ENVIRONMENT,
    TASK_TYPES_UNSUPPORTED,
    Preflight,
)
from chaeksas.core.run_log import run_dir
from chaeksas.qt import theme
from chaeksas.qt.approval import ApprovalDialog

log = logging.getLogger(__name__)

WINDOW_TITLE = "Chaeksas Bot UI"
WINDOW_SIZE = (1000, 720)

#: BUI-04 대기열 표의 열 (「입력 키」의 값은 접는다 — U10).
QUEUE_COLUMNS = ("#", "Bot", "출처", "요청 시각", "만료", "입력 키")

#: BUI-04 설치된 Bot 표의 열. 「최근 실행」은 아직 없다 — 모르는 것을 적지 않는다.
BOT_COLUMNS = ("Bot", "버전", "출처", "서명", "준비", "상태")
READY_COLUMN = BOT_COLUMNS.index("준비")

#: 「준비」의 표기 — `status_map`의 「Bot 준비」에 있는 것만 쓴다 (`docs/07-style-guide.md`).
READY = "준비됨"
NO_KEYS = "서비스 앱 키 없음"
NO_EXTENSION = "확장 없음"
PREFLIGHT_BLOCKED = "사전 점검 실행 불가"


def readiness_label(found: Preflight) -> tuple[str, str, str]:
    """사전 점검 결과 → `(status_map 표기, 줄에 보일 글, 툴팁)`.

    표기는 색을 고르는 데 쓰므로 **표에 있는 값이어야 한다**. 보일 글에는 빠진 참조 이름을 붙인다
    (BUI-04 「서비스 앱 키 없음: <참조>」) — 무엇이 빠졌는지 모르면 고칠 수 없다.
    """
    if not found.blocks:
        return READY, READY, ""
    first = next(f for f in found.findings if f.blocks)
    tip = "\n".join([first.message, *first.items, *([first.fix_hint] if first.fix_hint else [])])
    if found.missing_key_refs:
        return NO_KEYS, f"{NO_KEYS}: {', '.join(found.missing_key_refs)}", tip
    if set(found.blocked) & {TASK_TYPES_UNSUPPORTED, EXTENSIONS_UNUSABLE, MISSING_ENVIRONMENT}:
        return NO_EXTENSION, NO_EXTENSION, tip
    # 확장이 기여한 점검이 막았다 — 플랫폼은 그것이 무엇인지 모른다 (C13).
    return PREFLIGHT_BLOCKED, PREFLIGHT_BLOCKED, tip

PACKAGE_FILTER = "패키지 (*.zip)"

#: 「도구」 메뉴에 붙는 유틸리티 (C13 `bot_ui.utilities[].menu`).
UTILITY_MENU = "tools"

#: 지금 보여 주는 로컬 런타임 (BUI-09). 확장이 여럿 기여하면 칸이 여럿이 된다 — 아직 하나다.
RUNTIME_ID = "worker"

#: 유틸리티 창의 처음 크기 (BUI-06의 표 둘이 들어간다).
UTILITY_SIZE = (1100, 820)

#: BUI-09에서 아직 못 보이는 칸 (docs/09-gaps.md §4-2). 「최근 UI 세션」의 열(화면·폴백
#: 깊이·치유)은 **확장의 말**이라 플랫폼이 그리면 Bot UI가 UI 자동화를 알게 된다 (ADR-0018).
RUNTIME_STATUS_LATER = "「최근 UI 세션」은 아직 없습니다 — 확장이 그려야 하는 자리입니다 (docs/09-gaps.md §4-2)."
RUNTIME_STATE = {
    "running": "실행 중",
    "restarting": "다시 띄우는 중",
    "stopped": "멈춤",
    "off": "꺼 둠 (필요할 때 시작)",
}
#: 런타임이 `health`로 말하는 「지금 하는 일」 (C10 `session`).
SESSION_LABEL = {
    "idle": "대기",
    "bot": "Bot 요청 처리 중",
    "studio": "Studio 요청 처리 중",
    "selector_registration": "셀렉터 등록 중",
}

SOURCE_LABEL = {
    "job": "Center 작업",
    "manual": "수동",
    "watch": "감시",
    "schedule": "일정",
    "message": "메시지",
}


class UtilityWindow(QWidget):
    """확장이 기여한 유틸리티 하나의 창 (BUI-06~08은 여기 들어온다).

    **별도 창이 기본**이다 (BUI-02 [K]) — 메인 창 탭으로 붙이는 선택은 아직 없다. 닫을 때
    `closed()`를 불러 잡아 둔 자원(UI 세션 등)을 놓게 한다.
    """

    closed = Signal()

    def __init__(self, label: str, inner: QWidget, utility: object, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._utility = utility
        self.setWindowTitle(f"{label} — {WINDOW_TITLE}")
        self.resize(*UTILITY_SIZE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(inner)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt 이름
        """닫으면 유틸리티가 **자리를 놓는다** (Worker의 UI 세션은 한 번에 하나다)."""
        closing = getattr(self._utility, "closed", None)
        if callable(closing):
            try:
                closing()
            except Exception:  # noqa: BLE001 — 닫다 실패해도 창은 닫힌다
                log.exception("유틸리티를 닫다 실패했다")
        self.closed.emit()
        event.accept()


class MainWindow(QMainWindow):
    """메인 창. 데이터는 `Agent`에서만 읽는다 (화면은 보여 주기만)."""

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        #: 열려 있는 유틸리티 창 (`utility_id` → 창). 같은 것을 두 번 열지 않는다.
        self._utilities: dict[str, UtilityWindow] = {}
        #: 「실행 기록」에 마지막으로 쓴 글 — 같으면 다시 쓰지 않는다 (선택이 날아간다).
        self._run_log_text = ""
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_SIZE)

        self._build_menu()
        tabs = QTabWidget()
        tabs.addTab(self._bots_tab(), "Bot")
        tabs.addTab(self._run_log_tab(), "실행 기록")
        tabs.addTab(self._runtimes_tab(), "로컬 런타임")
        self.setCentralWidget(tabs)

        self.statusBar().showMessage(agent.status_line())
        self.refresh()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        file_menu.addAction("설정...", self.open_settings)
        file_menu.addAction("로그 폴더 열기", self.open_log_folder)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("종료", self.close)
        quit_action.setShortcut("Ctrl+Q")

        tools = self.menuBar().addMenu("도구")
        # 유틸리티는 **확장이 기여한다** (ADR-0018) — Bot UI는 어느 확장인지 모른다.
        utilities = self._agent.host.utilities() if self._agent.host is not None else []
        for found in sorted(utilities, key=lambda c: c.value.label):
            if found.value.menu != UTILITY_MENU:
                continue
            action = tools.addAction(f"{found.value.label}...")
            action.setToolTip(f"{found.extension_id} 확장")
            action.triggered.connect(
                lambda _=False, e=found.extension_id, u=found.value.id: self.open_utility(e, u)
            )
        if tools.actions():
            tools.addSeparator()
        tools.addAction("서비스 앱 키...", self.open_keys)
        later = tools.addAction("확장...")
        later.setEnabled(False)
        later.setToolTip("BUI-11에서 만듭니다.")

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
        """BUI-09. 확장이 기여한 로컬 런타임마다 한 칸 (C13) — 지금은 Worker 하나다."""
        page = QWidget()
        layout = QVBoxLayout(page)
        self.runtime_label = QLabel()
        self.runtime_label.setWordWrap(True)
        layout.addWidget(self.runtime_label)

        row = QHBoxLayout()
        self.runtime_start = QPushButton("시작")
        self.runtime_start.clicked.connect(self.start_runtime)
        self.runtime_restart = QPushButton("다시 시작...")
        self.runtime_restart.clicked.connect(self.restart_runtime)
        self.runtime_log = QPushButton("로그 보기")
        self.runtime_log.clicked.connect(self.open_runtime_log)
        row.addWidget(self.runtime_start)
        row.addWidget(self.runtime_restart)
        row.addWidget(self.runtime_log)
        row.addStretch(1)
        layout.addLayout(row)

        note = QLabel(RUNTIME_STATUS_LATER)
        note.setEnabled(False)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _run_log_tab(self) -> QWidget:
        """BUI-02 「실행 기록」. 원본은 `runs/<run_id>.jsonl`이고 화면은 **읽을 뿐이다**.

        「화면 지우기」는 **화면만** 비운다 — 파일을 지우면 Center로 보낼 기록이 사라진다 (C3).
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        self.run_log_text = QPlainTextEdit()
        self.run_log_text.setReadOnly(True)
        self.run_log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.run_log_text.setMaximumBlockCount(run_log_view.MAX_LINES)
        self.run_log_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.run_log_text.customContextMenuRequested.connect(self._run_log_menu)
        layout.addWidget(self.run_log_text)

        row = QHBoxLayout()
        refresh = QPushButton("새로 고침")
        refresh.clicked.connect(self.refresh_run_log)
        clear = QPushButton("화면 지우기")
        clear.clicked.connect(self.run_log_text.clear)
        row.addWidget(refresh)
        row.addWidget(clear)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _run_log_menu(self, where: QPoint) -> None:
        """문맥 메뉴 — 복사·화면 지우기 (BUI-02)."""
        menu = self.run_log_text.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("화면 지우기", self.run_log_text.clear)
        menu.exec(self.run_log_text.mapToGlobal(where))

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

        self._refresh_runtimes()
        self.refresh_run_log()
        self.statusBar().showMessage(agent.status_line())

    def _refresh_runtimes(self) -> None:
        """BUI-09 — 상태·PID·포트·가동 시간. **모르는 것은 적지 않는다** (답하지 않으면 그렇게 쓴다)."""
        agent = self._agent
        runtimes = agent.runtimes()
        found = runtimes.supervisors.get(RUNTIME_ID)
        try:
            _, runtime = runtimes.find(RUNTIME_ID)
        except RuntimeUnavailable:
            self.runtime_label.setText("로컬 런타임을 기여한 확장이 없습니다.")
            for button in (self.runtime_start, self.runtime_restart, self.runtime_log):
                button.setEnabled(False)
            return

        port = port_for(runtime, agent.settings)
        if found is None or found.state == "off":
            text = f"{runtime.label}: 꺼 둠 (필요할 때 시작) · 포트 {port}"
        else:
            where = f"pid {found.child.pid}" if found.child.pid else "pid 모름"
            uptime = f"{int(found.child.uptime_s)}초"
            text = (
                f"{runtime.label}: {RUNTIME_STATE.get(found.state, found.state)} · {where} · "
                f"포트 {port} · 가동 {uptime} · 다시 띄운 횟수 {found.restarts}"
            )
            health = runtimes.health_of(RUNTIME_ID)
            if health is None:
                text += " · 아직 답하지 않습니다"
            else:
                doing = SESSION_LABEL.get(str(health.get("session") or ""), "대기")
                text += f" · 버전 {health.get('version') or '모름'} · 지금 하는 일: {doing}"
                # 「예약」·「밀린 보고」는 런타임의 **상태**가 말해 준다 (C13 `status`). 본문의
                # 나머지는 확장의 말이라 읽지 않는다 (ADR-0018). **Agent가 하트비트에서 물어
                # 둔 것**을 읽는다 — 화면이 제 손으로 묻으면 GUI가 그만큼 멈춘다.
                status = agent.worker_status
                if status is None:
                    text += "\n예약·밀린 보고: 아직 묻지 않았습니다"
                elif not status:
                    text += "\n예약·밀린 보고: 상태를 받지 못했습니다"
                else:
                    held = str(status.get("reserved_for") or "")
                    text += f"\n예약: {self._reserved_label(held)}"
                    text += f" · 밀린 보고 {int(status.get('unsent_reports') or 0)}건"
            if found.last_error:
                text += f"\n{found.last_error}"
        self.runtime_label.setText(text)
        running = found is not None and found.state == "running"
        self.runtime_start.setEnabled(not running)
        self.runtime_restart.setEnabled(running)
        self.runtime_log.setEnabled(True)

    def _reserved_label(self, run_id: str) -> str:
        """BUI-09 「예약」 — 「예약됨 — <Bot> (<실행 id>)」. **Bot 이름을 모르면 적지 않는다.**"""
        if not run_id:
            return "예약 없음"
        run = self._agent.current_run
        if run is not None and run.run_id == run_id:
            return f"예약됨 — {run.bpm_process_id} ({run_id})"
        return f"예약됨 — {run_id}"

    def _refresh_bots(self) -> None:
        """설치된 Bot 목록 (BUI-04 [L]). **모르는 것은 적지 않는다** — 「최근 실행」은 아직 없다."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        self._bots = installed(data_dir())
        running = self._agent.current_run
        self.bots_title.setText(
            f"설치된 Bot {len(self._bots)}개"
            if self._bots
            else "설치된 Bot이 없습니다. Center에서 이 PC에 배포하거나 「패키지 파일에서 설치...」로 설치하세요."
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
            found = self._agent.preflight(bot)
            token, shown, tip = readiness_label(found)
            for column, text in enumerate((bot.name, bot.version, bot.source, bot.signature, shown, state)):
                item = QTableWidgetItem(text)
                if column == READY_COLUMN:
                    color = theme.status_color("Bot 준비", token, part="fg")
                    if color is not None:
                        item.setForeground(QColor(color))
                    item.setToolTip(tip)
                self.bots_table.setItem(row, column, item)
            # 키가 없으면 그 자리에서 BUI-10으로 간다 (BUI-04 — 「키 등록...」).
            self.bots_table.removeCellWidget(row, READY_COLUMN)
            if found.missing_key_refs:
                button = QPushButton(f"{shown} — 키 등록...")
                button.setToolTip(tip)
                button.clicked.connect(self.open_keys)
                self.bots_table.setCellWidget(row, READY_COLUMN, button)
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
        # **사람이 고른 파일은 이 자리가 적는다** (BUI-04 「출처」) — 적지 않으면 「알 수 없음」이다.
        write_source(bot.folder, MANUAL)
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

    def open_keys(self) -> None:
        """BUI-10. 창이 **그 자리에서** 키를 바꾸므로, 닫히면 「준비」를 다시 그린다."""
        KeysDialog(self._agent, self).exec()
        self.refresh()

    def open_log_folder(self) -> None:
        """`runs/`를 탐색기로 연다 (BUI-02 「파일」). 아직 없으면 만들어 준다 — 빈 폴더가 답이다."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        folder = run_dir(data_dir())
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def refresh_run_log(self) -> None:
        """BUI-02 「실행 기록」을 다시 읽는다. **파일이 원본이다** — 화면은 그릴 뿐이다.

        스크롤이 맨 아래가 아니면(사람이 위를 보고 있으면) **자리를 지킨다.**
        """
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        found = run_log_view.lines(data_dir())
        text = "\n".join(found) if found else run_log_view.EMPTY
        if text == self._run_log_text:
            # **바뀐 것이 없으면 손대지 않는다** — 하트비트마다 다시 쓰면 사람이 긁어 둔
            # 선택(복사하려던 것)이 사라진다.
            return
        self._run_log_text = text
        bar = self.run_log_text.verticalScrollBar()
        keep = bar.value() if bar.value() != bar.maximum() else None
        self.run_log_text.setPlainText(text)
        bar.setValue(keep if keep is not None else bar.minimum())

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

    # ── 유틸리티 (확장이 기여한다) ──

    def open_utility(self, extension_id: str, utility_id: str) -> None:
        """「도구」의 유틸리티를 연다 (C13 `bot_ui.utilities`).

        **필요한 런타임을 먼저 띄운다.** 못 띄우면 창을 열지 않고 왜 못 열었는지 말한다 —
        빈 창을 띄워 놓고 「안 되네」 하게 두지 않는다.
        """
        open_already = self._utilities.get(utility_id)
        if open_already is not None:
            open_already.show()
            open_already.raise_()
            open_already.activateWindow()
            return

        agent = self._agent
        if agent.host is None:
            return
        found = next((c for c in agent.host.utilities() if c.value.id == utility_id), None)
        if found is None:
            return
        needs = found.value.needs_runtime
        if needs:
            try:
                agent.runtimes().ensure(needs)
            except RuntimeUnavailable as e:
                QMessageBox.warning(self, found.value.label, str(e))
                self.refresh()
                return
        try:
            utility = agent.host.utility(utility_id)
            context = agent.extension_context(extension_id, runtime_ids=(needs,) if needs else ())
            widget = utility.widget(context)
        except Exception as e:  # noqa: BLE001 — 확장이 깨져도 Bot UI는 산다
            log.exception("유틸리티를 열지 못했다: %s", utility_id)
            QMessageBox.warning(self, found.value.label, f"유틸리티를 열지 못했습니다 — {e}")
            return
        if not isinstance(widget, QWidget):
            QMessageBox.warning(self, found.value.label, "유틸리티가 화면을 주지 않았습니다.")
            return

        window = UtilityWindow(found.value.label, widget, utility, self)
        window.closed.connect(lambda uid=utility_id: self._utilities.pop(uid, None))
        self._utilities[utility_id] = window
        window.show()
        self.refresh()

    # ── 로컬 런타임 (BUI-09) ──

    def start_runtime(self) -> None:
        try:
            self._agent.runtimes().ensure(RUNTIME_ID)
        except RuntimeUnavailable as e:
            QMessageBox.warning(self, WINDOW_TITLE, str(e))
        self.refresh()

    def restart_runtime(self) -> None:
        """BUI-09 「다시 시작」 — UI 세션이 열려 있으면 확인 창, 기본 「취소」 (U4)."""
        runtimes = self._agent.runtimes()
        health = runtimes.health_of(RUNTIME_ID) or {}
        busy = str(health.get("session") or "idle") != "idle"
        if busy:
            doing = SESSION_LABEL.get(str(health.get("session")), str(health.get("session")))
            answer = QMessageBox.question(
                self,
                "다시 시작할까요?",
                f"지금 {doing}입니다. 다시 시작하면 그 세션이 끊깁니다.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,  # 기본은 「취소」
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        found = runtimes.supervisors.get(RUNTIME_ID)
        if found is not None:
            found.stop()
        self.start_runtime()

    def open_runtime_log(self) -> None:
        """BUI-09 「로그 보기」 — 폴더를 연다 (파일을 우리가 그리지 않는다)."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        where = data_dir() / "logs"
        where.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(where)))

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


__all__ = [
    "QUEUE_COLUMNS",
    "RUNTIME_ID",
    "SESSION_LABEL",
    "SOURCE_LABEL",
    "UTILITY_MENU",
    "WINDOW_SIZE",
    "WINDOW_TITLE",
    "MainWindow",
    "UtilityWindow",
]

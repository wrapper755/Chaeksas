"""BUI-02 메인 창 + BUI-04 BPM 프로세스 탭. **창을 닫아도 PC 실행기는 트레이에서 돈다.**

실행 자리·대기열·**설치된 BPM 프로세스**·상태 줄이 있다. 결재를 기다리는 중이면 「결재 창
열기」가 CMN-01을 띄운다 (`packages/qt` — Studio와 **같은 창**이다).

**화면은 Agent에서만 읽는다.** 상태는 실행 프로세스가 쓴 기록 파일에서 오고(ADR-0031), 화면은 그것을
그릴 뿐이다 — 느린 실행 프로세스가 화면을 붙잡지 않는다.

「준비」 열은 **사전 점검**(`core.preflight`)이 말하는 것이고, 표기는 `status_map`의 「BPM 프로세스 준비」에
있는 것만 쓴다 (`docs/07-style-guide.md`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, QUrl
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
from chaeksas.bot_ui.extension_dialog import ExtensionsDialog
from chaeksas.bot_ui.run_log_view import LastRun, last_runs
from chaeksas.bot_ui.runner import Running
from chaeksas.bot_ui.settings_dialog import SettingsDialog
from chaeksas.contracts.approvals import Form
from chaeksas.core.deploy import DEPLOYMENT_EXPIRED, DEPLOYMENT_WITHDRAWN
from chaeksas.core.packages import (
    MANUAL,
    InstalledBot,
    InstallError,
    install,
    installed,
    write_source,
)
from chaeksas.core.preflight import (
    EXTENSION_TURNED_OFF,
    EXTENSIONS_UNUSABLE,
    MISSING_ENVIRONMENT,
    TASK_TYPES_UNSUPPORTED,
    Preflight,
)
from chaeksas.core.run_log import run_dir
from chaeksas.qt import theme
from chaeksas.qt.approval import ApprovalDialog

log = logging.getLogger(__name__)

WINDOW_TITLE = "Chaeksas PC 실행기"
WINDOW_SIZE = (1000, 720)

#: BUI-04 대기열 표의 열 (「입력 키」의 값은 접는다 — U10).
QUEUE_COLUMNS = ("#", "BPM 프로세스", "출처", "요청 시각", "만료", "입력 키")

#: BUI-04 설치된 BPM 프로세스 표의 열. 「최근 실행」은 BUI-02와 같은 기록 파일에서 읽는다.
BOT_COLUMNS = ("BPM 프로세스", "버전", "출처", "서명", "준비", "상태", "최근 실행")
READY_COLUMN = BOT_COLUMNS.index("준비")
LAST_RUN_COLUMN = BOT_COLUMNS.index("최근 실행")
#: 끝 줄이 없는 지난 실행 — 결과를 지어내지 않는다 (BUI-04).
NO_ENDING = "끝 기록이 없습니다 — 실행 프로세스가 도중에 멈췄을 수 있습니다. 「실행 기록」 탭에서 보세요."

#: 「준비」의 표기 — `status_map`의 「BPM 프로세스 준비」에 있는 것만 쓴다 (`docs/07-style-guide.md`).
READY = "준비됨"
NO_EXTENSION = "확장 없음"
#: 확장이 **깔려 있는데 사람이 껐다** (ADR-0043). 「확장 없음」과 섞지 않는다 — 고치는 길이
#: 「다시 깔기」가 아니라 **BUI-11에서 켜기**다. 색도 다르다 (neutral — 고장이 아니다).
EXTENSION_OFF = "확장 꺼짐"
PREFLIGHT_BLOCKED = "사전 점검 실행 불가"
#: 배포가 정한 「실행 불가」 (ADR-0113) — 고치는 길은 PC가 아니라 **Center에서 다시 배포**다.
DEPLOYMENT_GONE = "배포 철회"
DEPLOYMENT_OVER = "배포 만료"


def readiness_label(found: Preflight) -> tuple[str, str, str]:
    """사전 점검 결과 → `(status_map 표기, 줄에 보일 글, 툴팁)`.

    표기는 색을 고르는 데 쓰므로 **표에 있는 값이어야 한다**.
    """
    if not found.blocks:
        return READY, READY, ""
    first = next(f for f in found.findings if f.blocks)
    tip = "\n".join([first.message, *first.items, *([first.fix_hint] if first.fix_hint else [])])
    if DEPLOYMENT_WITHDRAWN in found.blocked:
        # **배포가 먼저다** — 다시 배포받기 전에는 다른 것을 고쳐도 돌지 않는다 (ADR-0113).
        return DEPLOYMENT_GONE, DEPLOYMENT_GONE, tip
    if DEPLOYMENT_EXPIRED in found.blocked:
        return DEPLOYMENT_OVER, DEPLOYMENT_OVER, tip
    if EXTENSION_TURNED_OFF in found.blocked:
        # **「확장 없음」보다 먼저 본다** — 꺼진 것과 없는 것이 함께 걸렸으면 켜는 쪽이 먼저
        # 할 수 있는 일이다 (ADR-0043 — 「다시 깔기」로 안내하면 할 수 없는 일을 시킨다).
        return EXTENSION_OFF, EXTENSION_OFF, tip
    if set(found.blocked) & {TASK_TYPES_UNSUPPORTED, EXTENSIONS_UNUSABLE, MISSING_ENVIRONMENT}:
        return NO_EXTENSION, NO_EXTENSION, tip
    # 확장이 기여한 점검이 막았다 — 플랫폼은 그것이 무엇인지 모른다 (C13).
    return PREFLIGHT_BLOCKED, PREFLIGHT_BLOCKED, tip

PACKAGE_FILTER = "패키지 (*.zip)"

SOURCE_LABEL = {
    "job": "Center 작업",
    "manual": "수동",
    "watch": "감시",
    "schedule": "일정",
    "message": "메시지",
}


def last_run_item(last: LastRun | None, running: Any) -> QTableWidgetItem:
    """BUI-04 「최근 실행」 칸 — 시각 + 결과. 한 번도 안 돌았으면 빈칸이다."""
    if last is None:
        return QTableWidgetItem("")
    result = last.result
    tip = ""
    if not result:
        if running is not None and getattr(running, "run_id", None) == last.run_id:
            result = "실행 중"
        else:
            result, tip = "—", NO_ENDING
    item = QTableWidgetItem(f"{last.at} {result}")
    color = theme.status_color("실행·노드", result, part="fg")
    if color is not None:
        item.setForeground(QColor(color))
    item.setToolTip(tip)
    return item


def _form_from(raw: Any) -> Form | None:
    """요청 본문의 폼 (C6). 읽을 수 없으면 `None` — 창은 그림의 폼으로라도 떠야 한다."""
    if not raw:
        return None
    try:
        return Form.model_validate(raw)
    except ValueError:
        return None

class MainWindow(QMainWindow):
    """메인 창. 데이터는 `Agent`에서만 읽는다 (화면은 보여 주기만)."""

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self._agent = agent
        #: 「실행 기록」에 마지막으로 쓴 글 — 같으면 다시 쓰지 않는다 (선택이 날아간다).
        self._run_log_text = ""
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(*WINDOW_SIZE)

        self._build_menu()
        tabs = QTabWidget()
        self.tabs = tabs
        tabs.addTab(self._bots_tab(), "BPM 프로세스")
        tabs.addTab(self._run_log_tab(), "실행 기록")
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

        self._tools_menu = self.menuBar().addMenu("도구")
        self._fill_tools()

    def _fill_tools(self) -> None:
        """「도구」를 채운다 — **BUI-11이 확장을 끄고 켜면 다시 부른다** (ADR-0043).

        메뉴를 통째로 다시 만들지 않고 이 메뉴만 비우고 채운다 — 메뉴 막대를 비우면 쓰지 않는
        옛 메뉴가 자식으로 남아 같은 이름이 둘이 된다.
        """
        tools = self._tools_menu
        tools.clear()
        tools.addAction("확장...", self.open_extensions)

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

        self.bots_title = QLabel("설치된 BPM 프로세스")
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
            self.running_label.setText("실행 중인 BPM 프로세스가 없습니다.")
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

        self.refresh_run_log()
        self.statusBar().showMessage(agent.status_line())

    def _refresh_bots(self) -> None:
        """설치된 BPM 프로세스 목록 (BUI-04 [L]). **모르는 것은 적지 않는다** — 「최근 실행」은 기록 파일에서 읽는다."""
        from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415 - 설정이 가리키는 곳

        self._bots = installed(data_dir())
        latest = last_runs(data_dir())
        running = self._agent.current_run
        self.bots_title.setText(
            f"설치된 BPM 프로세스 {len(self._bots)}개"
            if self._bots
            else "설치된 BPM 프로세스가 없습니다. "
            "Center에서 이 PC에 배포하거나 「패키지 파일에서 설치...」로 설치하세요."
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
                    color = theme.status_color("BPM 프로세스 준비", token, part="fg")
                    if color is not None:
                        item.setForeground(QColor(color))
                    item.setToolTip(tip)
                self.bots_table.setItem(row, column, item)
            self.bots_table.setItem(row, LAST_RUN_COLUMN, last_run_item(latest.get(bot.id), running))
        self._bots_changed()

    def _bots_changed(self) -> None:
        chosen = self.selected_bot()
        self.run_button.setEnabled(chosen is not None)
        self.run_button.setToolTip("" if chosen else "실행할 BPM 프로세스를 고르세요.")

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
            f"실행 중인 BPM 프로세스 「{running.bot.name}」을 멈출까요?",
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
        # **무엇을 판단하는지는 실행 프로세스가 쓴 본문이 말한다** (ADR-0078) — 제목·설명·검토 자료.
        # 아직 쓰이지 않았으면 그림에서 폼만 읽어 승인·반려라도 할 수 있게 한다.
        body = running.body_of(asked.request_id) or {}
        form = _form_from(body.get("form")) or self._form_of(running, asked.node_id)
        kind = "확인" if asked.is_confirmation else "결재"
        title = str(body.get("title") or "") or f"{running.bot.name} — {asked.node_id}"
        if asked.is_confirmation:
            title = f"실행 확인 요청 — {title}"
        answer = ApprovalDialog.ask(
            self,
            title=title,
            description=str(body.get("description") or "") or f"{running.bot.name}의 {kind} 요청입니다.",
            form=form,
            review=body.get("review") or None,
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

    def show_bots(self) -> None:
        """BUI-04 「BPM 프로세스」 탭 — 배포·준비 알림이 가리키는 자리다."""
        self.tabs.setCurrentIndex(0)
        self.refresh()

    def open_extensions(self) -> None:
        """BUI-11. 창이 **그 자리에서** 확장을 끄고 켜므로, 끈 것이 있으면 메뉴를 다시 만든다.

        꺼진 확장은 기여를 내지 않는다 (ADR-0043).
        """
        dialog = ExtensionsDialog(self._agent, self)
        dialog.exec()
        if dialog.changed:
            self._fill_tools()
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
    "SOURCE_LABEL",
    "WINDOW_SIZE",
    "WINDOW_TITLE",
    "MainWindow",
]

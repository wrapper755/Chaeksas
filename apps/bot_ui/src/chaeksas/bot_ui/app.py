"""Bot UI 앱 조립 — 트레이·창·하트비트 스레드 (BUI-01·02·03).

**트레이가 없는 환경이면 메인 창을 띄운다** (U15). 종료 순서는 BUI-01 10번 그대로다:
새 요청 막기 → 대기열의 Center 작업을 「거절 — Bot UI 종료」로 보고 → 실행기 취소 →
Worker 프로세스 종료 → 앱 종료.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from chaeksas.bot_ui.agent import Agent, make_agent
from chaeksas.bot_ui.heartbeat import HeartbeatWorker
from chaeksas.bot_ui.main_window import MainWindow
from chaeksas.bot_ui.settings_dialog import SettingsDialog
from chaeksas.bot_ui.tray import Tray
from chaeksas.contracts.bot_ui import JobAck
from chaeksas.qt import theme

log = logging.getLogger(__name__)

#: 종료할 때 실행 중 Bot을 기다리는 시간 (BUI-01 — 최대 20초).
SHUTDOWN_WAIT_S = 20


class BotUiApp:
    """앱 한 벌. `run()`이 Qt 이벤트 고리를 돈다."""

    def __init__(self, app: QApplication, agent: Agent) -> None:
        self.app = app
        self.agent = agent
        self.theme = theme.apply_theme(app)
        self.window = MainWindow(agent)

        self.tray: Tray | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(agent, current_theme=self.theme)
            self.tray.open_window.connect(self.show_window)
            self.tray.open_settings.connect(self.open_settings)
            self.tray.quit_requested.connect(self.quit)
            self.tray.show()
        else:
            # 트레이가 없으면 창이 앱이다 (U15) — 창을 닫으면 끝난다.
            log.info("시스템 트레이가 없어 메인 창으로 돈다")
            self.app.setQuitOnLastWindowClosed(True)

        self.thread = QThread()
        self.worker = HeartbeatWorker(agent)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.start)
        self.worker.beat_done.connect(self.refresh)
        self.worker.problem.connect(self.on_problem)

    # ── 화면 ──

    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.agent, self.window if self.window.isVisible() else None)
        if dialog.exec():
            self.refresh()

    def refresh(self) -> None:
        """하트비트가 끝났다 — **GUI 스레드에서** 다시 그린다."""
        if self.tray is not None:
            self.tray.refresh()
        if self.window.isVisible():
            self.window.refresh()

    def on_problem(self, message: str) -> None:
        if not message:
            return
        log.warning("Center: %s", message)
        if self.tray is not None:
            self.tray.showMessage("Chaeksas Bot UI", message, QSystemTrayIcon.MessageIcon.Warning)

    # ── 생애 ──

    def start(self) -> None:
        """처음 실행이면 설정 창을 먼저 띄운다 (BUI-03), 그다음 하트비트를 시작한다."""
        if not self.agent.credentials.center_api_key():
            self.show_window()
            self.open_settings()
        self.thread.start()

    def quit(self) -> None:
        """BUI-01 10번 — 묻고, 순서대로 정리한다."""
        agent = self.agent
        waiting = len(agent.queue)
        center_jobs = sum(1 for item in agent.queue if item.job_id)
        if agent.current_run is not None or waiting:
            running = agent.current_run.bpm_process_id if agent.current_run else "없음"
            answer = QMessageBox.question(
                self.window,
                "종료할까요?",
                f"실행 중인 Bot {running}을 멈추고, 대기열 {waiting}건"
                f"(Center 작업 {center_jobs}건은 Center로 돌려보냄)을 버리고 종료할까요?",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Cancel,  # 기본은 「취소」
            )
            if answer != QMessageBox.StandardButton.Ok:
                return
        self.shutdown()
        self.app.quit()

    def shutdown(self) -> None:
        """종료 순서 (BUI-01 10번). 화면 없이도 부를 수 있게 떼어 두었다."""
        agent = self.agent
        # 1. 새 요청 막기 — 하트비트를 멈춘다.
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(SHUTDOWN_WAIT_S * 1000)

        # 2. 대기열의 Center 작업을 「거절 — Bot UI 종료」로 보고한다 (C4 `bot_ui_shutdown`).
        pending = [item for item in list(agent.queue) if item.job_id]
        for item in pending:
            agent.store.remember_ack(
                JobAck(job_id=str(item.job_id), result="rejected", reason="bot_ui_shutdown")
            )
            agent.store.state.queue.remove(item)
            agent.store.state.inputs.pop(item.queue_id, None)
        agent.store.save()
        if pending:
            # 마지막 하트비트로 ack를 보낸다. 닿지 못하면 디스크에 남아 다음에 간다 (C4).
            try:
                agent.beat()
            except Exception as e:  # noqa: BLE001 — 종료 중이다. 막지 않는다
                log.warning("종료 보고를 보내지 못했다 (다음에 보낸다): %s", e)

        # 3·4. 실행기 취소 → Worker 프로세스 종료 (ADR-0023 — 트리째).
        for supervisor in agent.supervisors.values():
            supervisor.stop()

    def run(self) -> int:
        self.start()
        return self.app.exec()


def main(argv: list[str] | None = None) -> int:
    """`chk-bot-ui` 진입점."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Chaeksas Bot UI")
    # 창을 닫아도 트레이에서 돈다 (BUI-02).
    app.setQuitOnLastWindowClosed(False)
    return BotUiApp(app, make_agent()).run()


__all__ = ["SHUTDOWN_WAIT_S", "BotUiApp", "main"]

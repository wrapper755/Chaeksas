"""Bot UI 앱 조립 — 트레이·창·하트비트 스레드 (BUI-01·02·03).

**트레이가 없는 환경이면 메인 창을 띄운다** (U15). 종료 순서는 BUI-01 10번 그대로다:
새 요청 막기 → 대기열의 Center 작업을 「거절 — Bot UI 종료」로 보고 → 실행기 취소 →
Worker 프로세스 종료 → 앱 종료.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from chaeksas.bot_ui.agent import Agent, make_agent
from chaeksas.bot_ui.heartbeat import HeartbeatWorker
from chaeksas.bot_ui.main_window import MainWindow
from chaeksas.bot_ui.runtimes import RUNTIME_FLAG, serve
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
            self.tray = Tray(agent, current_theme=self.theme, parent=app)
            self.tray.open_window.connect(self.show_window)
            self.tray.open_settings.connect(self.open_settings)
            # 트레이에서 고른 유틸리티도 **메인 창이 연다** — 같은 것을 두 번 열지 않는 자리가 거기다.
            self.tray.open_utility.connect(self.open_utility)
            self.tray.open_extensions.connect(self.open_extensions)
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

    def open_extensions(self) -> None:
        """트레이 「도구」 → 「확장...」 (BUI-11). **메인 창이 연다** — 끄고 켠 뒤 「도구」 메뉴를
        다시 만드는 자리가 거기다."""
        self.window.open_extensions()
        self.refresh()

    def open_utility(self, extension_id: str, utility_id: str) -> None:
        """트레이 「도구」가 고른 유틸리티 (BUI-01). **창을 띄우지 않고도** 열 수 있다 —
        유틸리티는 별도 창이 기본이라 메인 창은 그대로 둔다 (BUI-02 [K])."""
        self.window.open_utility(extension_id, utility_id)

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
        # 1. 새 요청 막기 — 하트비트를 멈추고, **대기열에서 새 Bot을 띄우지 않는다**.
        agent.stopping = True
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

        # 3. 실행기 취소 — **협조 중지를 먼저** 준다 (돌던 Bot이 `cancelled`를 남길 틈, ADR-0031).
        if agent.runner().running is not None:
            agent.runner().stop()
        # 4. 로컬 런타임(Worker 프로세스 등) 종료 (ADR-0023 — 트리째).
        agent.runtimes().stop_all()

    def run(self) -> int:
        self.start()
        return self.app.exec()


def main(argv: list[str] | None = None) -> int:
    """`chk-bot-ui` 진입점.

    `--local-runtime <확장 id>:<런타임 id>`로 불리면 **화면 없이** 그 런타임으로 돈다 —
    Bot UI가 자기 실행 파일을 그렇게 자식으로 다시 띄운다 (C13·ADR-0024).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = list(argv if argv is not None else sys.argv)
    if RUNTIME_FLAG in args:
        return run_local_runtime(args)
    app = QApplication(args)
    app.setApplicationName("Chaeksas Bot UI")
    # 창을 닫아도 트레이에서 돈다 (BUI-02).
    app.setQuitOnLastWindowClosed(False)
    return BotUiApp(app, make_agent()).run()


def run_local_runtime(args: list[str]) -> int:
    """자식으로 뜬 쪽 (C13 — `--local-runtime <확장>:<런타임> --port <p> --token-dir <폴더>`).

    **Qt를 띄우지 않는다.** 인자를 직접 읽는 것은 Qt가 모르는 깃발이기 때문이다.
    """
    parser = argparse.ArgumentParser(prog="chk-bot-ui", add_help=False)
    parser.add_argument(RUNTIME_FLAG, dest="spec", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token-dir", dest="token_dir", default=None)
    found, _ = parser.parse_known_args(args[1:])
    where = Path(found.token_dir) if found.token_dir else None
    log.info("로컬 런타임으로 돈다: %s (포트 %s)", found.spec, found.port)
    return serve(found.spec, port=found.port, token_dir=where)


__all__ = ["SHUTDOWN_WAIT_S", "BotUiApp", "main", "run_local_runtime"]

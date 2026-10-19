"""`chk-tool-ui` 진입점 — Tool UI 창 하나 (TOL-01, ADR-0077).

들어오는 길은 셋이다.

- 소스 실행: `chk-tool-ui [--open <확장>:<도구>]` 또는 `python -m chaeksas.tool_ui …`
- 묶은 앱: **Bot UI 실행 파일**이 `--tool-ui`로 불리면 이 `main`으로 간다 (`packaging/botui_main.py`
  — 실행 파일을 늘리지 않는다, ADR-0024·0077 §6).
- Bot UI 「도구」 바로가기: 런타임을 먼저 띄운 뒤 위 둘 중 하나를 `--open`과 함께 **따로** 띄운다.

**한 로그인 세션에 하나만** 뜬다 — 이미 떠 있으면 그 창에 `--open`을 넘기고 이 프로세스는 끝난다
(`QLocalServer`, 이름에 사용자 이름이 들어간다).
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from PySide6.QtCore import QByteArray
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from chaeksas.qt import theme
from chaeksas.tool_ui.host import ToolHost, parse_spec
from chaeksas.tool_ui.settings_dialog import ToolSettingsDialog
from chaeksas.tool_ui.window import WINDOW_TITLE, ToolWindow

log = logging.getLogger(__name__)

#: 묶은 Bot UI 실행 파일이 Tool UI로 도는 깃발 (ADR-0077 §6). **Tool UI는 이것을 그냥 넘긴다.**
TOOL_UI_FLAG = "--tool-ui"
OPEN_FLAG = "--open"
#: 두 번째 실행이 첫 창을 찾는 이름 — 사용자마다 따로다.
SERVER_PREFIX = "chaeksas-tool-ui-"
#: 두 번째 실행이 첫 창에 닿기를 기다리는 시간 (ms).
CONNECT_MS = 500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 — 사용자 이름을 모르면 하나로 묶는다
        user = "user"
    return SERVER_PREFIX + "".join(one if one.isalnum() else "_" for one in user)


def parse_args(argv: list[str]) -> str | None:
    """`--open <확장>:<도구>`만 읽는다 — 나머지(`--tool-ui`, Qt 깃발)는 모른 척한다."""
    parser = argparse.ArgumentParser(prog="chk-tool-ui", add_help=False)
    parser.add_argument(OPEN_FLAG, dest="open", default=None)
    found, _ = parser.parse_known_args(argv)
    return str(found.open) if found.open else None


def hand_over(spec: str | None, *, name: str | None = None) -> bool:
    """이미 떠 있는 Tool UI에 넘긴다. 넘겼으면 `True` — 이 프로세스는 창을 띄우지 않는다."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(CONNECT_MS):
        return False
    socket.write(QByteArray((spec or "").encode("utf-8")))
    socket.flush()
    socket.waitForBytesWritten(CONNECT_MS)
    socket.disconnectFromServer()
    return True


def listen(window: ToolWindow, *, name: str | None = None) -> QLocalServer:
    """두 번째 실행을 받는다 — 앞으로 부르고, 넘긴 도구가 있으면 연다."""
    where = name or server_name()
    QLocalServer.removeServer(where)  # 죽은 첫 창이 남긴 자리
    server = QLocalServer(window)
    if not server.listen(where):
        log.warning("두 번째 실행을 받지 못한다: %s", server.errorString())
        return server

    def accept() -> None:
        while server.hasPendingConnections():
            client = server.nextPendingConnection()

            def read(c: QLocalSocket = client) -> None:
                spec = parse_spec(bytes(c.readAll().data()).decode("utf-8", errors="replace").strip())
                window.bring_forward()
                if spec is not None:
                    window.open_tool(*spec)

            client.readyRead.connect(read)
            client.disconnected.connect(client.deleteLater)

    server.newConnection.connect(accept)
    return server


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = list(argv if argv is not None else sys.argv)
    spec = parse_args(args[1:])
    app = QApplication.instance() or QApplication(args)
    assert isinstance(app, QApplication)
    app.setApplicationName(WINDOW_TITLE)
    if hand_over(spec):
        return 0
    theme.apply_theme(app)

    tools = ToolHost.load()
    window: ToolWindow

    def open_settings() -> None:
        dialog = ToolSettingsDialog(tools.host, tools.settings, tools.credentials, window)
        if dialog.exec() and dialog.saved is not None:
            tools.settings = dialog.saved

    window = ToolWindow(tools, open_settings=open_settings)
    listen(window)
    window.show()
    found = parse_spec(spec)
    if found is not None:
        window.open_tool(*found)
    return int(app.exec())


__all__ = [
    "OPEN_FLAG",
    "SERVER_PREFIX",
    "TOOL_UI_FLAG",
    "hand_over",
    "listen",
    "main",
    "parse_args",
    "server_name",
]

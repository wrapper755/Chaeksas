"""`chk-admin-ui` 진입점 — Admin UI 창 하나 (ADR-0089)."""

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtWidgets import QApplication

from chaeksas.admin import connection
from chaeksas.admin.client import Center
from chaeksas.admin.dialogs import Prompter, connected, describe
from chaeksas.admin.window import WINDOW_TITLE, AdminWindow
from chaeksas.qt import theme


def ensure_connection(prompter: Prompter | None = None, *, center: Any = Center.from_env) -> bool:
    """주 창보다 먼저 **연결을 확인한다** (일종의 로그인, ADM-05 「시작할 때」).

    저장된 주소·토큰이 맞으면 묻지 않는다. 처음이거나 맞지 않으면 ADM-05를 띄우고(까닭과 함께),
    「취소」하면 `False` — Admin UI를 닫는다. 「저장」은 확인한 뒤에만 되므로 한 번이면 끝난다.
    """
    line = describe(center())
    if connected(line):
        return True
    reason = "" if not connection.stored_url() and not connection.stored_token() else line
    return (prompter or Prompter()).connection(reason)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = list(argv if argv is not None else sys.argv)
    app = QApplication.instance() or QApplication(args)
    assert isinstance(app, QApplication)
    app.setApplicationName(WINDOW_TITLE)
    theme.apply_theme(app)
    if not ensure_connection():
        return 0
    window = AdminWindow()
    window.show()
    window.refresh()
    return int(app.exec())


__all__ = ["ensure_connection", "main"]

"""Studio를 띄운다 — `uv run chk-studio` 또는 `python -m chaeksas.studio`.

테마는 `chaeksas.qt.apply_theme()` 한 줄이다 (글꼴 등록 + 생성된 QSS + 팔레트, ADR-0017).
WebEngine은 **QApplication보다 먼저** 공유 OpenGL을 켜 두어야 한다 (Qt 요구 사항).
"""

from __future__ import annotations

import logging
import sys

from chaeksas.studio.settings import Settings

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from PySide6.QtCore import QCoreApplication, Qt  # noqa: PLC0415
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    # QtWebEngine을 쓰려면 QApplication을 만들기 전에 켜 둔다 (Qt가 그렇게 요구한다).
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    from chaeksas.qt.theme import apply_theme  # noqa: PLC0415
    from chaeksas.studio.main_window import MainWindow  # noqa: PLC0415

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Chaeksas Studio")
    apply_theme(app)

    settings = Settings.load()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    window = MainWindow(settings)
    window.show()
    return int(app.exec())


__all__ = ["main"]

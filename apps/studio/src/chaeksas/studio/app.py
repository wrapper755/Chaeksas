"""Studio를 띄운다 — `uv run chk-studio` 또는 `python -m chaeksas.studio`.

테마는 `chaeksas.qt.apply_theme()` 한 줄이다 (글꼴 등록 + 생성된 QSS + 팔레트, ADR-0017).
WebEngine은 **QApplication보다 먼저** 공유 OpenGL을 켜 두어야 한다 (Qt 요구 사항).
"""

from __future__ import annotations

import logging
import sys

from chaeksas.core.selftest import SELFTEST_FLAG
from chaeksas.studio.settings import Settings

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """`chk-studio` 진입점.

    `--selftest [파일]`은 **묶은 실행 파일의 빌드 검사**다 (ADR-0024) — Bot UI와 **같은 깃발·
    같은 검사**이고(`core.selftest`) 화면을 띄우지 않는다.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = list(argv if argv is not None else sys.argv)
    if SELFTEST_FLAG in args:
        return _selftest(args)

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


def _selftest(args: list[str]) -> int:
    """빌드 검사 — **Qt를 띄우지 않는다** (묶인 앱은 콘솔 없이 뜰 수 있어 파일로 받는다)."""
    from chaeksas.core.selftest import main  # noqa: PLC0415

    return main(args[1:], prog="chk-studio")


__all__ = ["main"]

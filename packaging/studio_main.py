"""PyInstaller 진입 스크립트 — Studio ([ADR-0024](../docs/decisions/0024-desktop-packaging-extensions.md)).

**QtWebEngine이 여기만 있다** (`botui_main.py`에는 없다) — Studio 캔버스가 bpmn-js를
QtWebEngine 안에서 돌린다 ([ADR-0022](../docs/decisions/0022-studio-canvas.md)). import 한 줄로
PyInstaller가 그것을 함께 묶는다.
"""

from __future__ import annotations

import multiprocessing
import sys

import PySide6.QtWebEngineWidgets  # noqa: F401 — 묶을 때 함께 들어가게 하는 import

from chaeksas.studio.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())

"""PyInstaller 진입 스크립트 — Bot UI ([ADR-0024](../docs/decisions/0024-desktop-packaging-extensions.md)).

**콘솔 스크립트(`chk-bot-ui`)를 묶지 않는다** — PyInstaller는 모듈이 아니라 **스크립트 하나**를
받는다. 그래서 진입점을 부르는 얇은 파일을 둔다.

**확장 옵션을 여기 적지 않는다.** `core`가 주는 PyInstaller 훅이 설치된 엔트리 포인트를 훑어
넣는다 (ADR-0024 — 빌드가 확장 이름을 알 필요가 없다, ADR-0018).

**QtWebEngine을 import하지 않는다** — Studio만 쓴다 (Bot UI는 모든 현장 PC에 깔리므로 작게
둔다: Studio 551MB ↔ Bot UI 113MB).
"""

from __future__ import annotations

import multiprocessing
import sys

from chaeksas.bot_ui.app import main

if __name__ == "__main__":
    # 묶인 앱이 자식을 띄울 때 **같은 실행 파일이 다시 돌아 창이 여럿 뜨는 것**을 막는다
    # (PyInstaller 권고). Bot UI는 자기 실행 파일로 로컬 런타임을 띄운다 (C13·ADR-0024).
    multiprocessing.freeze_support()
    sys.exit(main())

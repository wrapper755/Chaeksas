"""PyInstaller 진입 스크립트 — Bot UI ([ADR-0024](../docs/decisions/0024-desktop-packaging-extensions.md)).

**콘솔 스크립트(`chk-bot-ui`)를 묶지 않는다** — PyInstaller는 모듈이 아니라 **스크립트 하나**를
받는다. 그래서 진입점을 부르는 얇은 파일을 둔다.

**확장 옵션을 여기 적지 않는다.** `core`가 주는 PyInstaller 훅이 설치된 엔트리 포인트를 훑어
넣는다 (ADR-0024 — 빌드가 확장 이름을 알 필요가 없다, ADR-0018).

**Tool UI도 이 실행 파일이다** ([ADR-0077](../docs/decisions/0077-tool-ui.md) §6) — `--tool-ui`로 불리면
Tool UI의 `main`으로 간다. 실행 파일을 늘리지 않으려는 것이고(파이썬·Qt·DPI 선언을 함께 쓴다),
**가르는 자리가 여기**인 까닭은 앱끼리 import하지 않기 때문이다 (Bot UI가 Tool UI를 모른다).

**QtWebEngine을 import하지 않는다** — Studio만 쓴다 (Bot UI는 모든 현장 PC에 깔리므로 작게
둔다: Studio 551MB ↔ Bot UI 113MB).
"""

from __future__ import annotations

import multiprocessing
import sys

#: `chaeksas.tool_ui.app.TOOL_UI_FLAG`·`chaeksas.bot_ui.tool_launch.TOOL_UI_FLAG`와 같은 글이다.
TOOL_UI_FLAG = "--tool-ui"


def run(argv: list[str]) -> int:
    """깃발로 가른다 — `--tool-ui`면 Tool UI, 아니면 Bot UI(로컬 런타임·빌드 검사 포함)."""
    if TOOL_UI_FLAG in argv:
        from chaeksas.tool_ui.app import main as tool_ui  # noqa: PLC0415 — 고른 쪽만 싣는다

        return tool_ui(argv)
    from chaeksas.bot_ui.app import main as bot_ui  # noqa: PLC0415

    return bot_ui(argv)


if __name__ == "__main__":
    # 묶인 앱이 자식을 띄울 때 **같은 실행 파일이 다시 돌아 창이 여럿 뜨는 것**을 막는다
    # (PyInstaller 권고). Bot UI는 자기 실행 파일로 로컬 런타임을 띄운다 (C13·ADR-0024).
    multiprocessing.freeze_support()
    sys.exit(run(list(sys.argv)))

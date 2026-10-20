"""「도구」 바로가기 — 확장의 도구는 **Tool UI가** 띄운다 (ADR-0077).

Bot UI는 그 도구가 쓰는 런타임을 먼저 띄우고(`Runtimes.ensure`) Tool UI를 **따로** 띄울 뿐이다.

- **자식으로 감시하지 않는다** — `core.processes`(Job Object·프로세스 그룹)에 넣지 않는다. Bot UI를
  다시 띄워도 도구 창은 남아야 한다(그 사이 Worker가 다시 뜨는 것은 Tool UI가 받는다).
- Bot UI는 Tool UI를 **import하지 않는다**(앱끼리 import하지 않는다) — 명령줄만 안다.
  묶은 앱에서는 **같은 실행 파일**이 `--tool-ui`로 Tool UI가 되고(`packaging/botui_main.py`),
  소스 실행에서는 `python -m chaeksas.tool_ui`다.
- 한 세션에 하나만 뜨는 것은 Tool UI가 지킨다 — 이미 떠 있으면 그 창이 `--open`을 받는다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from chaeksas.bot_ui.runtimes import frozen

#: 묶은 실행 파일이 Tool UI로 도는 깃발 — `chaeksas.tool_ui.app.TOOL_UI_FLAG`와 같은 글이다
#: (앱끼리 import하지 않아 베낀다 — `tests/test_tool_ui_launch.py`가 대조한다).
TOOL_UI_FLAG = "--tool-ui"
OPEN_FLAG = "--open"
TOOL_UI_MODULE = "chaeksas.tool_ui"


def tool_ui_command(extension_id: str, tool_id: str) -> list[str]:
    """Tool UI를 그 도구와 함께 띄우는 명령줄. **비밀은 싣지 않는다.**"""
    head = [sys.executable, TOOL_UI_FLAG] if frozen() else [sys.executable, "-m", TOOL_UI_MODULE]
    return [*head, OPEN_FLAG, f"{extension_id}:{tool_id}"]


def launch(command: list[str]) -> None:
    """따로 띄운다 — 기다리지 않고, 묶지 않는다. 띄우지 못하면 `OSError`."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        # 한글을 찍다 죽지 않게 (Bot UI의 다른 자식과 같다 — ADR-0023).
        "env": {**os.environ, "PYTHONUTF8": "1"},
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)  # noqa: S603 — 인자 리스트, 셸 없음


__all__ = ["OPEN_FLAG", "TOOL_UI_FLAG", "TOOL_UI_MODULE", "launch", "tool_ui_command"]

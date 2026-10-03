"""`python -m chaeksas.bot_ui` — 자동 시작 등록이 이 형태를 쓴다 (`autostart.launch_command`)."""

from __future__ import annotations

import sys

from chaeksas.bot_ui.app import main

if __name__ == "__main__":
    sys.exit(main())

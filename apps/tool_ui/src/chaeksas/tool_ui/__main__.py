"""`python -m chaeksas.tool_ui` — PC 실행기 「도구」 바로가기가 소스 실행에서 이 형태를 쓴다."""

from __future__ import annotations

import sys

from chaeksas.tool_ui.app import main

if __name__ == "__main__":
    sys.exit(main())

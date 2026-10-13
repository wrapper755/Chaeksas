"""`python -m chaeksas.server_runner` — systemd·compose가 이 형태를 쓸 수 있다.

설치하면 `chk-server-runner`가 같은 것을 부른다 (`pyproject.toml`의 `[project.scripts]`).
"""

from __future__ import annotations

import sys

from chaeksas.server_runner.main import main

if __name__ == "__main__":
    sys.exit(main())

"""S5 호스트 진입점 (PyInstaller 스크립트) — Studio 흉내. WebEngine을 명시적으로 import해 묶음에 넣는다."""

import chaeksas.s5host.studio  # noqa: F401
from chaeksas.s5host.app import main

main()

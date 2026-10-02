"""S5 시험용 확장. 호스트는 엔트리 포인트 `chaeksas.extensions` → `EXTENSION`만 본다.

기여는 모두 **문자열 진입점**이다 (C13 `entry`). 호스트가 필요할 때 import한다 — 그래서 PyInstaller의
정적 분석은 이 모듈들을 보지 못한다. S5가 확인하려는 것이 바로 그것이다.
"""

import json
from importlib import resources

EXTENSION = {
    "id": "s5demo",
    "bot_ui.utilities": [{"id": "demo-utility", "label": "시험 유틸리티",
                          "entry": "chaeksas.ext.s5demo.widget:DemoUtility"}],
    "bot_ui.local_runtimes": [{"id": "worker", "label": "시험 Worker",
                               "entry": "chaeksas.ext.s5demo.runtime:main", "health": "/v1/health"}],
}


def manifest() -> dict:
    """확장 정의(C13)는 패키지 데이터 파일로 들어 있다 — 묶인 앱에서도 읽혀야 한다."""
    return json.loads(resources.files(__package__).joinpath("extension.json").read_text(encoding="utf-8"))

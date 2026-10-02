"""묶인 뒤에도 확장 호스트가 확장을 찾는가 — 이 스크립트를 PyInstaller로 묶어 돌린다.

세 가지를 따로 찍는다. 하나라도 비면 원인이 다르다.

1. `entry_points(group="chaeksas.extensions")` — 패키지 **메타데이터**(dist-info)가 묶였나
2. 호스트가 읽은 확장 — `extension.json`(**데이터 파일**)이 묶였나
3. `executor`·`editor`·`utility` — 문자열로 import하는 **클라이언트 모듈**이 묶였나

(제품 코드는 이 폴더를 import하지 않는다 — spikes/README.md)
"""

from __future__ import annotations

import json
import sys
from importlib.metadata import entry_points

from chaeksas.contracts.extension import ENTRY_POINT_GROUP
from chaeksas.core import load_host, summarize

MARKER = "PROBE_JSON "


def try_resolve(label: str, call) -> dict:  # noqa: ANN001
    try:
        value = call()
    except Exception as e:  # 스파이크다 — 무엇이 터졌는지만 알면 된다
        return {label: None, f"{label}_error": f"{type(e).__name__}: {e}"}
    return {label: type(value).__name__ if value is not None else None}


def main() -> int:
    host = load_host()
    out: dict = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": getattr(sys, "_MEIPASS", None) is not None,
        "entry_points": sorted(ep.name for ep in entry_points(group=ENTRY_POINT_GROUP)),
        "summary": summarize(host),
        "task_types": [c.value.id for c in host.task_types()],
        "utilities": [c.value.id for c in host.utilities()],
        "local_runtimes": [c.value.id for c in host.local_runtimes()],
    }
    out.update(try_resolve("executor", lambda: host.executor("ui_task")))
    out.update(try_resolve("editor", lambda: host.editor("ui_task")))
    out.update(try_resolve("utility", lambda: host.utility("selector-registration")))
    out.update(try_resolve("preflight", lambda: (host.preflight_checks() or [None])[0]))
    print(MARKER + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

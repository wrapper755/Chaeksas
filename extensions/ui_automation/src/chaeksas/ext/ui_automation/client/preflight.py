"""사전 점검 「쓰는 화면이 레지스트리에 있나」.

BPM 프로세스 매니페스트(C1)의 `requires.resources`에 적힌 `ui_page`들이 레지스트리(C9)에 있는지
본다. Center 리소스 목록으로도 같은 대조를 하지만(C7 `missing()`), 사전 점검은 **실행 직전** 그
PC에서 한 번 더 본다.

> 상태: **뼈대만.** 레지스트리 조회는 M4다.
"""

from __future__ import annotations

from collections.abc import Sequence

from chaeksas.extension_api import Finding, PreflightTarget


class PagesRegisteredCheck:
    """`preflight` — `extension_api.PreflightCheck`."""

    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        raise NotImplementedError("화면 레지스트리 조회(C9)는 M4다")

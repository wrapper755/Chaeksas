"""사전 점검 「쓰는 화면이 레지스트리에 있나」.

BPM 프로세스 매니페스트(C1)의 `requires.resources`에 적힌 `ui_page`들이 레지스트리(C9)에 있는지
본다. Center 리소스 목록으로도 같은 대조를 하지만(C7 `missing()`), 사전 점검은 **실행 직전** 그
PC에서 한 번 더 본다.

> 상태: **뼈대만.** 아는 길은 레지스트리 조회(C9)뿐인데 **사전 점검은 서버를 부르지 않는다**
> (`core.preflight` — Bot UI가 하트비트마다 돌린다). 이 PC에서 답할 수 있는 자리(계획 캐시 등)를
> 찾기 전까지는 못 한다고 말한다. 터뜨려도 실행은 막지 않는다 — 호스트가 사유만 남긴다.
"""

from __future__ import annotations

from collections.abc import Sequence

from chaeksas.extension_api import Finding, PreflightTarget


class PagesRegisteredCheck:
    """`preflight` — `extension_api.PreflightCheck`."""

    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        raise NotImplementedError(
            "쓰는 화면이 등록됐는지 이 PC에서 알 길이 없다 (레지스트리 조회는 서버를 부른다)"
        )

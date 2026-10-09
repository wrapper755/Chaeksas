"""사전 점검 「쓰는 화면이 레지스트리에 있나」.

BPM 프로세스 매니페스트(C1)의 `requires.resources`에 적힌 `ui_page`들이 레지스트리(C9)에 있는지
본다. Center 리소스 목록으로도 같은 대조를 하지만(C7 `missing()`), 사전 점검은 **실행 직전** 그
PC에서 한 번 더 본다.

> 상태: **아직 대조하지 못한다.** 아는 길은 레지스트리 조회(C9)뿐인데 **사전 점검은 서버를
> 부르지 않는다** (`core.preflight` — 실행하는 쪽이 하트비트마다, Studio가 F6마다 돌린다).
> 이 PC에서 답할 수 있는 자리(계획 캐시 등)를 찾기 전까지는 **모른다고 말한다.**

**쓰는 화면이 없으면 아무 말도 하지 않는다.** 조건 없이 「모른다」고 하면 UI를 쓰지 않는 그림에도
경고가 뜨고, 그런 경고는 아무도 읽지 않는다 — ADR-0039가 B11에서 겪은 그대로다 (거짓 경고
열하나가 진짜 하나를 묻었다).
"""

from __future__ import annotations

from collections.abc import Sequence

from chaeksas.extension_api import SEVERITY_WARN, Finding, PreflightTarget

#: 이 확장이 기여하는 자원 종류 (`extension.json`의 `resources`).
UI_PAGE = "ui_page"

#: 점검 결과 코드 — **「없다」가 아니라 「모른다」**다 (C9를 부를 수 없다).
UNVERIFIED = "ui_pages_unverified"


class PagesRegisteredCheck:
    """`preflight` — `extension_api.PreflightCheck`."""

    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        pages = sorted({one.id for one in target.manifest.requires.resources if one.type == UI_PAGE})
        if not pages:
            return ()
        return [
            Finding(
                id=UNVERIFIED,
                severity=SEVERITY_WARN,
                message=f"쓰는 화면 {len(pages)}개가 등록됐는지 이 PC에서 확인하지 못했습니다",
                items=tuple(pages),
                fix_hint="UI 자동화 앱의 관리 콘솔(UIA-02)에서 등록 여부를 보세요",
            )
        ]


__all__ = ["UI_PAGE", "UNVERIFIED", "PagesRegisteredCheck"]

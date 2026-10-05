"""백엔드 둘을 하나로 — 세션의 화면이 웹이면 브라우저로, 데스크톱이면 UIA로 보낸다 (ADR-0033).

Worker 본체(`app.py`)는 백엔드가 하나인 줄 안다. 세션은 한 번에 하나라(ADR-0014) **지금 쓰는
쪽**만 기억하면 된다. 그 PC에 없는 쪽을 고르면 「없는데 된 척」하지 않고 503이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import DESKTOP, WEB
from chaeksas.ext.ui_automation.contracts.worker_local import BROWSER_UNAVAILABLE, SessionRequest


class BackendUnavailable(RuntimeError):
    """그 플랫폼의 백엔드가 이 PC에 없다 (C10 `browser_unavailable`)."""

    status = 503
    code = BROWSER_UNAVAILABLE
    detail: dict[str, Any] = {}


def platform_of(request: SessionRequest, plan: Any) -> str:
    """세션의 플랫폼 — **계획이 정한다** (화면 등록 C9). 계획이 없으면 앱 이름이 있을 때만 데스크톱이다."""
    if plan is not None:
        return str(getattr(plan, "platform", WEB) or WEB)
    return DESKTOP if request.app else WEB


@dataclass
class RoutingBackend:
    """C10 `Backend` — 브라우저·데스크톱 중 그 세션의 것으로 보낸다."""

    web: Any = None
    desktop: Any = None
    _active: Any = None

    def open(self, request: SessionRequest, plan: Any = None) -> str:
        platform = platform_of(request, plan)
        chosen = self.desktop if platform == DESKTOP else self.web
        if chosen is None:
            what = "데스크톱(UIA)" if platform == DESKTOP else "브라우저"
            raise BackendUnavailable(f"이 PC에는 {what} 백엔드가 없습니다")
        url = chosen.open(request, plan)
        self._active = chosen
        return str(url)

    def finder(self, business_key: str) -> Any:
        return self._active.finder(business_key) if self._active is not None else None

    def goto(self, session_id: str, url: str) -> str:
        if self._active is None:
            raise BackendUnavailable("열린 화면이 없습니다")
        return str(self._active.goto(session_id, url))

    def close(self, session_id: str) -> None:
        if self._active is not None:
            self._active.close(session_id)
        self._active = None

    def shutdown(self) -> None:
        for one in (self.web, self.desktop):
            stop = getattr(one, "shutdown", None)
            if callable(stop):
                stop()


__all__ = ["BackendUnavailable", "RoutingBackend", "platform_of"]

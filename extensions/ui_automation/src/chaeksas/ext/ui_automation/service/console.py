"""관리 콘솔이 읽는 길 — UIA-01~03 (C9 §관리 콘솔이 읽는 길).

**앱 고유 관리 경로다.** C11이 정한 `/admin/v1/status`·`keys`·`usage` 옆에 이 앱만의 읽기
경로를 둔다 — 콘솔 화면(UIA-01~03)이 레지스트리와 세션 기록을 봐야 하기 때문이다.

관문은 **하나다**: `service_kit.admin_guard`. 콘솔은 서비스 앱 키를 갖지 않으므로(ADR-0013)
`registry_write` 키 대신 **관리자 토큰**으로 읽는다 — 키를 발급하는 토큰이라 더 강하다.

**읽기만 한다.** 등록·삭제는 C9 작업(`/v1/ops/registry_*`)이고 Bot UI 유틸리티의 일이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from chaeksas.ext.ui_automation.service.registry import RegistryError
from chaeksas.service_kit import admin_guard

#: UIA-03 이력 기본·최대 개수 (C11 사용 기록과 같은 결 — 한도 안으로 자른다).
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


def _error(status: int, code: str, message: str) -> JSONResponse:
    """C11·C5와 같은 오류 본문."""
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": {}})


if TYPE_CHECKING:  # pragma: no cover - 순환 import를 피한다 (app.py가 이 모듈을 쓴다)
    from chaeksas.ext.ui_automation.service.app import Service


def create_router(service: Service) -> APIRouter:
    """`/admin/v1/…`에 붙는 앱 고유 읽기 경로. `create()`가 앱에 꽂는다."""
    router = APIRouter(prefix="/admin/v1", tags=["ui-automation"])

    @router.get("/overview")
    def overview(request: Request) -> Any:
        """UIA-01 개요 — 셀렉터 셈·모델·세션 셈·배포 전 확인."""
        refused = admin_guard(request)
        if refused is not None:
            return refused
        return service.overview().to_json_dict()

    @router.get("/pages")
    def pages(request: Request) -> Any:
        """UIA-02 화면 고르기 목록. **셀렉터는 나가지 않는다** (목록이다)."""
        refused = admin_guard(request)
        if refused is not None:
            return refused
        return service.page_listing().to_json_dict()

    @router.get("/pages/{page_id}")
    def page(request: Request, page_id: str) -> Any:
        """UIA-02 화면 하나 — **셀렉터가 나간다** (관리자 토큰으로만 오는 길이다)."""
        refused = admin_guard(request)
        if refused is not None:
            return refused
        try:
            return service.page_detail(page_id).to_json_dict()
        except RegistryError as e:
            return _error(404, "not_found", str(e))

    @router.get("/path")
    def path(request: Request, start: str = "", goal: str = "") -> Any:
        """UIA-02 「화면 간 경로 탐색」. 둘 중 하나가 비면 422 — 화면이 묻기 전이다."""
        refused = admin_guard(request)
        if refused is not None:
            return refused
        if not start or not goal:
            return _error(422, "input_invalid", "출발·도착 화면을 모두 적어야 한다")
        return service.page_path(start, goal).to_json_dict()

    @router.get("/sessions")
    def sessions(request: Request, limit: int = DEFAULT_LIMIT) -> Any:
        """UIA-03 — 이력·요약·폴백 분포. `limit`은 **한도 안으로 자른다** (C11 사용 기록과 같은 결)."""
        refused = admin_guard(request)
        if refused is not None:
            return refused
        return service.session_page(limit=min(max(limit, 1), MAX_LIMIT)).to_json_dict()

    return router


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "create_router"]

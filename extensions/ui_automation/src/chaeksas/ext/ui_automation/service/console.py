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

from chaeksas.service_kit import admin_guard

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

    return router


__all__ = ["create_router"]

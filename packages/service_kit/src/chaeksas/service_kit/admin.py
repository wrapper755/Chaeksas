"""관리 API (`/admin/v1/*`) — 서비스 앱 관리 콘솔이 쓰는 것 (C11, SVC-00~03).

**업무 호출과 권한이 다르다.** 서비스 앱 API 키로는 부를 수 없고, 앱 설정의 **관리자 토큰**으로만
부른다. 관리자 토큰이 없으면 관리 API 전체가 503이다 — 빈 토큰으로 열리지 않는다.

키 발급·폐기가 여기 있다 (ADR-0013: **키는 그 앱의 관리 콘솔에서 발급한다**. Center는 서비스 앱
키를 모른다).
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from chaeksas.contracts.service_app import (
    AdminKeyCreated,
    AdminKeyCreateRequest,
    AdminKeyInfo,
    AdminStatus,
    CenterRegistration,
    Dependency,
    OperationStatus,
    ServiceAppKey,
    ServiceAppManifest,
    UsagePage,
    admin_key_info,
)
from chaeksas.service_kit import keys as key_tools
from chaeksas.service_kit.stores import KeyStore, UsageLog

#: 통계를 세는 창 (SVC-01 「최근 24시간 호출 수·오류율」).
STATS_WINDOW_H = 24
#: 사용 기록 기본·최대 개수 (SVC-03).
USAGE_DEFAULT_LIMIT = 100
USAGE_MAX_LIMIT = 1000

#: 의존 상태를 알려 주는 함수. 앱이 자기 의존(Neo4j·LLM …)을 보고 돌려준다.
DependencyProbe = Callable[[], Sequence[Dependency]]


def _error(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    """C11·C5와 같은 오류 본문."""
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": detail or {}})


def _authorized(request: Request) -> JSONResponse | None:
    """관리자 토큰인가. 설정되지 않았으면 **열지 않는다.**"""
    expected: str | None = getattr(request.app.state, "admin_token", None)
    if not expected:
        return _error(
            503,
            "admin_disabled",
            "관리자 토큰이 설정되지 않아 관리 API를 쓸 수 없다 (CHK_SVC_<APP>__ADMIN_TOKEN)",
        )
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    token = value.strip() if scheme.lower() == "bearer" else ""
    if not token:
        return _error(401, "token_missing", "관리자 토큰이 없다")
    if not hmac.compare_digest(token, expected):
        return _error(403, "admin_only", "관리자 토큰이 아니다")
    return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def operation_stats(manifest: ServiceAppManifest, log: UsageLog, *, now: str) -> list[OperationStatus]:
    """작업별 선언 + 최근 24시간 통계 (SVC-01).

    수는 **앱 안의 사용 기록**에서 센다 (C11 — 값은 기록하지 않지만 호출은 센다).
    """
    since = datetime.fromisoformat(now) - timedelta(hours=STATS_WINDOW_H)
    counts: dict[str, list[int]] = {}
    for entry in getattr(log, "entries", []) or []:
        try:
            at = datetime.fromisoformat(entry.at)
        except ValueError:  # pragma: no cover - 기록이 깨진 경우
            continue
        if at < since:
            continue
        slot = counts.setdefault(entry.operation, [0, 0])
        slot[0] += 1
        if entry.status >= 400:
            slot[1] += 1

    out = []
    for operation in manifest.operations:
        calls, errors = counts.get(operation.name, [0, 0])
        out.append(
            OperationStatus(
                name=operation.name,
                description=operation.description,
                modes=operation.modes,
                fallback=operation.fallback,
                server_ok=operation.server_ok,
                calls_24h=calls,
                errors_24h=errors,
                error_rate=round(errors / calls, 4) if calls else 0.0,
            )
        )
    return out


def create_router(
    manifest: ServiceAppManifest,
    *,
    keys: KeyStore,
    usage_log: UsageLog,
    started_at: str,
    dependencies: DependencyProbe | None = None,
    center: CenterRegistration | None = None,
    now: Callable[[], str] = _now,
) -> APIRouter:
    """관리 API 경로 묶음. `create_app()`이 붙인다."""
    router = APIRouter(prefix="/admin/v1", tags=["admin"])

    @router.get("/status")
    def status(request: Request) -> Any:
        refused = _authorized(request)
        if refused is not None:
            return refused
        at = now()
        uptime = int((datetime.fromisoformat(at) - datetime.fromisoformat(started_at)).total_seconds())
        return AdminStatus(
            schema=1,
            app_id=manifest.app_id,
            name=manifest.name,
            version=manifest.version,
            category=manifest.category,
            console_url=manifest.console_url,
            started_at=started_at,
            uptime_s=max(uptime, 0),
            operations=operation_stats(manifest, usage_log, now=at),
            dependencies=list(dependencies()) if dependencies else [],
            center=center or CenterRegistration(),
        )

    @router.get("/keys")
    def list_keys(request: Request) -> Any:
        """**원문·해시는 돌려주지 않는다** (C11)."""
        refused = _authorized(request)
        if refused is not None:
            return refused
        at = now()
        return [admin_key_info(key, now=at) for key in keys.all_keys()]

    @router.post("/keys", status_code=201)
    async def create_key(request: Request) -> Any:
        refused = _authorized(request)
        if refused is not None:
            return refused
        try:
            body = await request.json()
        except ValueError:
            return _error(422, "input_invalid", "본문이 JSON이 아니다")
        try:
            wanted = AdminKeyCreateRequest.model_validate(body)
        except ValidationError as e:
            return _error(422, "input_invalid", "요청이 계약과 맞지 않는다", {"errors": e.error_count()})

        # 이름은 앱 안에서 유일하다 — 키 참조 이름과 맞추기를 권하므로 겹치면 어느 키인지 모른다.
        if any(key.name == wanted.name for key in keys.all_keys()):
            return _error(409, "name_conflict", f"키 이름 「{wanted.name}」이 이미 있다")

        raw, record = key_tools.issue(
            wanted.name,
            allowed_operations=wanted.allowed_operations,
            allowed_modes=wanted.allowed_modes,
            extra_scopes=wanted.extra_scopes,
            created_at=now(),
            expires_at=wanted.expires_at,
        )
        keys.add(record)
        # **원문은 이 응답에만** 실린다 (SVC-02 — 다시 볼 수 없다).
        return AdminKeyCreated(**admin_key_info(record, now=now()).model_dump(), key=raw)

    @router.delete("/keys/{name}")
    def revoke_key(request: Request, name: str) -> Any:
        """폐기. **지우지 않는다** — 사용 기록이 가리키는 이름을 남겨 둔다."""
        refused = _authorized(request)
        if refused is not None:
            return refused
        found: ServiceAppKey | None = next((k for k in keys.all_keys() if k.name == name), None)
        if found is None:
            return _error(404, "not_found", f"키 「{name}」이 없다")
        if found.revoked_at is None:
            keys.revoke(found, at=now())
        after = next((k for k in keys.all_keys() if k.name == name), found)
        return admin_key_info(after, now=now())

    @router.get("/usage")
    def usage(request: Request, limit: int = USAGE_DEFAULT_LIMIT) -> Any:
        """사용 기록 (최근 것부터). **입력·출력 값은 없다** (계약 원칙 6)."""
        refused = _authorized(request)
        if refused is not None:
            return refused
        entries = list(getattr(usage_log, "entries", []) or [])
        bounded = max(1, min(limit, USAGE_MAX_LIMIT))
        return UsagePage(items=list(reversed(entries))[:bounded], total=len(entries))

    return router


__all__ = ["AdminKeyInfo", "DependencyProbe", "create_router", "operation_stats"]

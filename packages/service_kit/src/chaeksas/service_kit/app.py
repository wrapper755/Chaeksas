"""C11을 지키는 FastAPI 앱을 만든다.

새 서비스 앱은 **작업 함수만** 쓴다. 나머지(`/healthz`, `/manifest`, 키 검증·권한, 멱등,
오류 형식, 사용 기록)는 여기서 계약대로 제공한다 (C11 「`service_kit`이 제공하는 것」).

    manifest = ServiceAppManifest(schema=1, app_id="tax-invoice", …)
    app = create_app(manifest, {"issue": issue_handler}, keys=store)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from chaeksas.contracts.service_app import (
    Caller,
    CenterRegistration,
    Dependency,
    HealthResponse,
    KeySelfResponse,
    Operation,
    OpRequest,
    OpResponse,
    ServiceAppKey,
    ServiceAppManifest,
    Usage,
    UsageRecord,
    authorize,
    idempotency_key,
    key_state,
    resolve_mode,
)
from chaeksas.service_kit.admin import DependencyProbe
from chaeksas.service_kit.admin import create_router as create_admin_router
from chaeksas.service_kit.keys import find_key
from chaeksas.service_kit.stores import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryUsageLog,
    KeyStore,
    UsageLog,
    body_hash,
)

if TYPE_CHECKING:
    from chaeksas.service_kit.llm import ServiceLlm


class OpError(Exception):
    """작업 함수가 계약의 오류 코드로 실패를 알린다.

    예: `raise OpError("dependency_down", "Neo4j에 닿지 않는다", status=503)`
    """

    def __init__(self, code: str, message: str, *, status: int = 503, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


class OpResult:
    """작업 함수의 결과. `usage`는 LLM을 쓴 경우에만."""

    def __init__(self, output: Mapping[str, Any], *, usage: Usage | None = None):
        self.output = dict(output)
        self.usage = usage


#: 작업 함수. 요청과 **실제로 쓸 모드**를 받고, 결과나 평범한 dict를 돌려준다.
Handler = Callable[[OpRequest, str], "OpResult | Mapping[str, Any]"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _error(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    """C11·C5와 같은 오류 본문: `{code, message, detail}`."""
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": detail or {}})


def _validation_detail(e: ValidationError) -> dict[str, Any]:
    """`detail`에 넣을 수 있는 모양으로 줄인다.

    pydantic의 `errors()`에는 예외 객체가 섞여 있어 그대로는 JSON이 되지 않는다.
    """
    return {
        "errors": [
            {"loc": ".".join(str(p) for p in err["loc"]), "msg": err["msg"], "type": err["type"]}
            for err in e.errors()
        ]
    }


def _is_schema_error(e: ValidationError) -> bool:
    """`schema` 필드 때문에 거부되었나 (별명이라 loc이 둘 중 하나로 온다)."""
    return any(err["loc"] in (("schema",), ("schema_version",)) for err in e.errors())


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def create_app(
    manifest: ServiceAppManifest,
    handlers: Mapping[str, Handler],
    *,
    keys: KeyStore,
    idempotency: IdempotencyStore | None = None,
    usage_log: UsageLog | None = None,
    health: Callable[[], HealthResponse] | None = None,
    admin_token: str | None = None,
    dependencies: DependencyProbe | None = None,
    center: CenterRegistration | None = None,
    llm: ServiceLlm | None = None,
    now: Callable[[], str] = _now,
) -> FastAPI:
    """계약을 지키는 앱 하나.

    `handlers`의 열쇠는 manifest의 작업 이름이어야 한다 — 어긋나면 만들 때 바로 멈춘다.

    `admin_token`을 주면 관리 API(`/admin/v1/*`, SVC-00~03)가 열린다. 주지 않으면 그 경로는
    503이다 — **빈 토큰으로 열리지 않는다** (C11).
    `dependencies`는 앱이 자기 바깥 의존(Neo4j·LLM …)의 상태를 돌려주는 함수다 (SVC-01).
    `llm`(모델 연결, C11 §모델 연결)을 주면 관리 상태에 `llm` 한 줄이 저절로 붙는다.
    """
    declared = {op.name for op in manifest.operations}
    if set(handlers) != declared:
        raise ValueError(
            f"manifest의 작업과 handlers가 다르다: manifest에만 {sorted(declared - set(handlers))}, "
            f"handlers에만 {sorted(set(handlers) - declared)}"
        )

    idem = idempotency or InMemoryIdempotencyStore()
    log = usage_log or InMemoryUsageLog()

    app = FastAPI(title=manifest.name, version=manifest.version)
    app.state.manifest = manifest
    app.state.keys = keys
    app.state.idempotency = idem
    app.state.usage_log = log
    app.state.admin_token = admin_token
    app.state.llm = llm
    started_at = now()

    def probe() -> Sequence[Dependency]:
        found = list(dependencies()) if dependencies else []
        return [*found, llm.dependency()] if llm is not None else found

    app.include_router(
        create_admin_router(
            manifest,
            keys=keys,
            usage_log=log,
            started_at=started_at,
            dependencies=probe,
            center=center,
            now=now,
        )
    )

    @app.get("/healthz")
    def healthz() -> HealthResponse:
        return health() if health else HealthResponse(status="ok", version=manifest.version)

    @app.get("/manifest")
    def get_manifest() -> ServiceAppManifest:
        # 인증 없음 — 비밀이 들어가지 않는다 (C7이 이것을 읽어 리소스 목록을 만든다).
        return manifest

    def _authenticate(request: Request) -> tuple[ServiceAppKey | None, JSONResponse | None]:
        raw = _bearer(request)
        if raw is None:
            return None, _error(401, "key_missing", "서비스 앱 API 키가 없다")
        key = find_key(raw, keys.all_keys())
        if key is None:
            return None, _error(401, "key_invalid", "모르는 키다")
        state = key_state(key, now=now())
        if state != "active":
            return None, _error(403, f"key_{state}", f"키 「{key.name}」은 {state} 상태다")
        return key, None

    @app.get("/v1/keys/self")
    def key_self(request: Request) -> Any:
        """「연결 테스트」용. **키 원문·해시는 돌려주지 않는다.**"""
        key, failure = _authenticate(request)
        if failure is not None:
            return failure
        assert key is not None
        return KeySelfResponse(
            name=key.name,
            prefix=key.prefix,
            allowed_operations=key.allowed_operations,
            allowed_modes=key.allowed_modes,
            extra_scopes=key.extra_scopes,
            expires_at=key.expires_at,
        )

    @app.post("/v1/ops/{operation}")
    async def call_operation(operation: str, request: Request) -> Any:
        started = time.monotonic()
        key, failure = _authenticate(request)
        if failure is not None:
            return failure
        assert key is not None

        def refuse(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
            """거부도 사용 기록에 남긴다 — 운영자가 「운영 키로 자율 수행 시도」를 봐야 한다.

            401(키를 모르는 경우)은 남길 키 이름이 없어 기록하지 않는다.
            """
            _log_refusal(log, key, operation, status, started, now())
            return _error(status, code, message, detail)

        op: Operation | None = manifest.operation(operation)
        if op is None or operation not in handlers:
            return refuse(404, "operation_not_found", f"작업 {operation}이 없다")

        try:
            body = await request.json()
        except ValueError:
            return refuse(422, "input_invalid", "본문이 JSON이 아니다")
        try:
            req = OpRequest.model_validate(body)
        except ValidationError as e:
            # 더 높은 schema는 따로 알린다 (부르는 쪽이 재시도하지 않게).
            if _is_schema_error(e):
                return refuse(422, "schema_unsupported", "모르는 schema다", _validation_detail(e))
            return refuse(422, "input_invalid", "요청이 계약과 맞지 않는다", _validation_detail(e))

        denied = authorize(
            key, operation=operation, mode=req.mode, now=now(), required_scopes=op.required_scopes
        )
        if denied:
            first = denied[0]
            return refuse(403, first.code or "forbidden", first.message, {"items": first.items})

        mode_used, problem = resolve_mode(op, requested=req.mode, key=key)
        if problem is not None or mode_used is None:
            assert problem is not None
            return refuse(422, problem.code or "mode_unsupported", problem.message, {"items": problem.items})

        ikey = idempotency_key(operation, req)
        outcome, stored = idem.begin(ikey, body=body_hash(req))
        if outcome == "conflict":
            return refuse(409, "idempotency_conflict", "같은 멱등 키인데 본문이 다르다")
        if outcome == "in_progress":
            return refuse(409, "in_progress", "같은 멱등 키가 아직 수행 중이다")
        if outcome == "replay" and stored is not None:
            _record(log, key, operation, req, mode_used, 200, started, stored.usage, now())
            return stored.model_copy(update={"replayed": True})

        try:
            result = handlers[operation](req, mode_used)
        except OpError as e:
            idem.abandon(ikey)
            _record(log, key, operation, req, mode_used, e.status, started, None, now())
            return _error(e.status, e.code, e.message, e.detail)
        except Exception as e:  # 예상 못 한 실패 — 멱등 자리를 비워 다시 부를 수 있게 한다
            idem.abandon(ikey)
            _record(log, key, operation, req, mode_used, 500, started, None, now())
            # C11 오류 표에 없는 코드다. 앱의 버그이므로 사람이 보고 고쳐야 한다.
            return _error(500, "internal", f"작업이 예상 못 한 오류로 실패했다: {type(e).__name__}")

        output = result.output if isinstance(result, OpResult) else dict(result)
        usage = result.usage if isinstance(result, OpResult) else None
        response = OpResponse(status="ok", output=output, mode_used=mode_used, replayed=False, usage=usage)
        idem.finish(ikey, response=response)
        keys.touch(key, at=now())
        _record(log, key, operation, req, mode_used, 200, started, usage, now())
        return response

    return app


def _log_refusal(log: UsageLog, key: ServiceAppKey, operation: str, status: int, started: float, at: str) -> None:
    """요청을 모델로 읽기 전에도 남길 수 있는 최소 기록 (모드·run_id를 모를 수 있다)."""
    log.record(
        UsageRecord(
            at=at,
            key_name=key.name,
            operation=operation,
            mode="-",
            status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    )


def _record(
    log: UsageLog,
    key: ServiceAppKey,
    operation: str,
    req: OpRequest,
    mode_used: str,
    status: int,
    started: float,
    usage: Usage | None,
    at: str,
) -> None:
    caller: Caller = req.caller
    log.record(
        UsageRecord(
            at=at,
            key_name=key.name,
            operation=operation,
            mode=mode_used,
            status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
            run_id=req.run_id,
            caller_type=caller.type,
            usage=usage,
        )
    )

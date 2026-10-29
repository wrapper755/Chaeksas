"""C11을 지키는 서비스 앱을 만든다 — **일꾼**이다 (ADR-0102).

새 서비스 앱은 **작업 함수만** 쓴다. 나머지(멱등, 수행 모드·폴백, 오류 형식, 사용 기록, `/healthz`,
관리 API)는 여기서 계약대로 제공한다 (C11 「`service_kit`이 제공하는 것」). 업무 호출은 HTTP로
받지 않는다 — `Consumer`(`service_kit.consumer`)가 Center에서 일감을 가져와 `Service.execute()`에 준다.

    manifest = ServiceAppManifest(schema=1, app_id="tax-invoice", …)
    app = create_app(manifest, {"issue": issue_handler})
    Consumer([app.state.ops], center_url=…, tokens=…).run(stop)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import FastAPI
from pydantic import ValidationError

from chaeksas.contracts.extension import Catalog
from chaeksas.contracts.external_task import LockedTask
from chaeksas.contracts.service_app import (
    CenterRegistration,
    Dependency,
    HealthResponse,
    OpRequest,
    OpResponse,
    ServiceAppManifest,
    Usage,
    UsageRecord,
    idempotency_key,
    resolve_mode,
)
from chaeksas.service_kit.admin import DependencyProbe
from chaeksas.service_kit.admin import create_router as create_admin_router
from chaeksas.service_kit.stores import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryUsageLog,
    UsageLog,
    body_hash,
)

if TYPE_CHECKING:
    from chaeksas.service_kit.llm import ServiceLlm


class OpError(Exception):
    """작업 함수가 계약의 실패 코드로 실패를 알린다 (C11 §오류).

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
#: 기여 자원 카탈로그를 주는 함수 (C15 `PUT …/catalogs/{type}` — 일꾼이 `revision`이 바뀌면 올린다).
CatalogSource = Callable[[], Catalog]

#: 실패 코드 → 사용 기록의 수 (C11 §오류 — HTTP는 없지만 SVC-01 오류율이 이 수로 센다).
_STATUS_OF = {
    "operation_not_found": 404,
    "idempotency_conflict": 409,
    "input_invalid": 422,
    "mode_unsupported": 422,
    "schema_unsupported": 422,
    "rate_limited": 429,
    "internal": 500,
}
#: 다시 해 볼 만한 실패 (C11 §오류 「다시 해 볼 만함」).
RETRYABLE = frozenset({"rate_limited", "dependency_down", "timeout"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Outcome:
    """일감 하나를 수행한 결과 — `complete`(성공) 또는 `fail`(실패) 하나가 C15로 간다.

    `skip`이면 아무것도 보내지 않는다 — 같은 멱등 칸이 **이 앱 안에서 아직 도는 중**이다(잠금이 지나
    다시 나왔다). 앞의 것이 끝내면 그것이 이긴다 (C15 「먼저 끝낸 쪽이 이긴다」).
    """

    response: OpResponse | None = None
    code: str | None = None
    message: str = ""
    retryable: bool = False
    #: 결과 모름 (C15, ADR-0107) — 요청이 상대에게 닿았을 수 있는데 답을 받지 못했다.
    outcome_unknown: bool = False
    detail: dict[str, Any] = field(default_factory=dict)
    skip: bool = False

    @property
    def ok(self) -> bool:
        return self.response is not None

    def complete_body(self) -> dict[str, Any]:
        assert self.response is not None
        body: dict[str, Any] = {
            "output": self.response.output,
            "mode_used": self.response.mode_used,
            "replayed": self.response.replayed,
        }
        if self.response.usage is not None:
            body["usage"] = self.response.usage.to_json_dict()
        return body

    def fail_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code or "internal", "message": self.message, "retryable": self.retryable}
        if self.outcome_unknown:
            body["outcome_unknown"] = True
        if self.detail:
            body["detail"] = self.detail
        return body


class TopicService(Protocol):
    """일꾼이 맡는 토픽 하나 — `Service`(C11 앱)와 어댑터 일꾼의 외부 확장이 같은 모양이다 (C15)."""

    @property
    def app_id(self) -> str: ...

    @property
    def manifest(self) -> ServiceAppManifest: ...

    @property
    def catalogs(self) -> Mapping[str, CatalogSource]: ...

    def execute(self, task: LockedTask) -> Outcome: ...


@dataclass
class Service:
    """서비스 앱 하나의 작업 수행기 — HTTP를 모른다. 일꾼 뼈대(`Consumer`)가 부른다."""

    manifest: ServiceAppManifest
    handlers: Mapping[str, Handler]
    idempotency: IdempotencyStore = field(default_factory=InMemoryIdempotencyStore)
    usage_log: UsageLog = field(default_factory=InMemoryUsageLog)
    catalogs: Mapping[str, CatalogSource] = field(default_factory=dict)
    now: Callable[[], str] = _now

    def __post_init__(self) -> None:
        declared = {op.name for op in self.manifest.operations}
        if set(self.handlers) != declared:
            raise ValueError(
                f"manifest의 작업과 handlers가 다르다: manifest에만 {sorted(declared - set(self.handlers))}, "
                f"handlers에만 {sorted(set(self.handlers) - declared)}"
            )

    @property
    def app_id(self) -> str:
        return self.manifest.app_id

    def request_of(self, task: LockedTask) -> OpRequest:
        """C15 `LockedTask` → 작업 함수가 받는 `OpRequest` (C11 §OpRequest)."""
        return OpRequest.model_validate(
            {
                "schema": 1,
                "mode": task.mode,
                "run_id": task.idempotency.run_id,
                "node_id": task.idempotency.node_id,
                "node_instance": task.idempotency.node_instance,
                "attempt": task.idempotency.attempt,
                "call_seq": task.idempotency.call_seq,
                "caller": task.caller.to_json_dict(),
                "business_key": task.business_key,
                "input": task.input,
                "origin": task.origin,
            }
        )

    def execute(self, task: LockedTask) -> Outcome:
        """일감 하나 — 멱등 → 모드 → 작업 함수 (C11). **예외를 올리지 않는다** — 모두 `Outcome`이다."""
        started = time.monotonic()
        operation = task.operation
        op = self.manifest.operation(operation)
        try:
            req = self.request_of(task)
        except ValidationError as e:
            return self._fail(task, None, "input_invalid", f"일감이 계약과 맞지 않는다: {e.error_count()}개", started)
        if op is None or operation not in self.handlers:
            return self._fail(task, req, "operation_not_found", f"작업 {operation}이 없다", started)

        mode_used, problem = resolve_mode(op, requested=req.mode, origin=req.origin)
        if problem is not None or mode_used is None:
            assert problem is not None
            return self._fail(task, req, problem.code or "mode_unsupported", problem.message, started)

        ikey = idempotency_key(operation, req)
        outcome, stored = self.idempotency.begin(ikey, body=body_hash(req))
        if outcome == "conflict":
            return self._fail(task, req, "idempotency_conflict", "같은 멱등 칸인데 본문이 다르다", started)
        if outcome == "in_progress":
            return Outcome(skip=True)
        if outcome == "replay" and stored is not None:
            self._record(task, req, mode_used, 200, started, stored.usage)
            return Outcome(response=stored.model_copy(update={"replayed": True}))

        try:
            result = self.handlers[operation](req, mode_used)
        except OpError as e:
            self.idempotency.abandon(ikey)
            self._record(task, req, mode_used, e.status, started, None)
            return Outcome(code=e.code, message=e.message, retryable=e.code in RETRYABLE, detail=dict(e.detail or {}))
        except Exception as e:  # noqa: BLE001 — 예상 못 한 실패. 멱등 자리를 비워 다시 받을 수 있게 한다
            self.idempotency.abandon(ikey)
            self._record(task, req, mode_used, 500, started, None)
            return Outcome(code="internal", message=f"작업이 예상 못 한 오류로 실패했다: {type(e).__name__}")

        output = result.output if isinstance(result, OpResult) else dict(result)
        usage = result.usage if isinstance(result, OpResult) else None
        response = OpResponse(status="ok", output=output, mode_used=mode_used, replayed=False, usage=usage)
        self.idempotency.finish(ikey, response=response)
        self._record(task, req, mode_used, 200, started, usage)
        return Outcome(response=response)

    def _fail(self, task: LockedTask, req: OpRequest | None, code: str, message: str, started: float) -> Outcome:
        self._record(task, req, "-", _STATUS_OF.get(code, 503), started, None)
        return Outcome(code=code, message=message, retryable=code in RETRYABLE)

    def _record(
        self, task: LockedTask, req: OpRequest | None, mode: str, status: int, started: float, usage: Usage | None
    ) -> None:
        caller = task.caller
        self.usage_log.record(
            UsageRecord(
                at=self.now(),
                key_name=f"{caller.type}:{caller.host or '-'}",
                operation=task.operation,
                mode=mode,
                status=status,
                duration_ms=int((time.monotonic() - started) * 1000),
                run_id=req.run_id if req is not None else task.idempotency.run_id,
                caller_type=caller.type,
                usage=usage,
            )
        )


def create_app(
    manifest: ServiceAppManifest,
    handlers: Mapping[str, Handler],
    *,
    idempotency: IdempotencyStore | None = None,
    usage_log: UsageLog | None = None,
    health: Callable[[], HealthResponse] | None = None,
    admin_token: str | None = None,
    dependencies: DependencyProbe | None = None,
    center: Callable[[], CenterRegistration] | CenterRegistration | None = None,
    llm: ServiceLlm | None = None,
    catalogs: Mapping[str, CatalogSource] | None = None,
    now: Callable[[], str] = _now,
) -> FastAPI:
    """서비스 앱 하나 — `/healthz`와 관리 API(SVC-00·01·03)를 여는 FastAPI. 작업 수행기는
    `app.state.ops`(`Service`)이고 일꾼 뼈대가 그것을 부른다.

    `handlers`의 열쇠는 manifest의 작업 이름이어야 한다 — 어긋나면 만들 때 바로 멈춘다.
    `admin_token`을 주면 관리 API가 열린다. 주지 않으면 503이다 — **빈 토큰으로 열리지 않는다** (C11).
    `center`는 「일꾼으로 들었나」를 알려 주는 것(SVC-01) — 보통 `Consumer.registration`이다.
    """
    service = Service(
        manifest=manifest,
        handlers=handlers,
        idempotency=idempotency or InMemoryIdempotencyStore(),
        usage_log=usage_log or InMemoryUsageLog(),
        catalogs=dict(catalogs or {}),
        now=now,
    )

    app = FastAPI(title=manifest.name, version=manifest.version)
    app.state.manifest = manifest
    #: 작업 수행기 (`Service`) — 일꾼(`Consumer`)이 부른다. 앱이 제 도메인 객체를 `service`로 둘 수
    #: 있게 이름을 따로 둔다.
    app.state.ops = service
    app.state.idempotency = service.idempotency
    app.state.usage_log = service.usage_log
    app.state.admin_token = admin_token
    app.state.llm = llm
    app.state.center = center
    started_at = now()

    def probe() -> Sequence[Dependency]:
        found = list(dependencies()) if dependencies else []
        if llm is not None:
            found = [*found, llm.dependency()]
        return found

    def registration() -> CenterRegistration:
        found = app.state.center
        if callable(found):
            return found()  # type: ignore[no-any-return]
        return found or CenterRegistration()

    app.include_router(
        create_admin_router(
            manifest,
            usage_log=service.usage_log,
            started_at=started_at,
            dependencies=probe,
            center=registration,
            now=now,
        )
    )

    @app.get("/healthz")
    def healthz() -> HealthResponse:
        return health() if health else HealthResponse(status="ok", version=manifest.version)

    return app


__all__ = ["CatalogSource", "Handler", "OpError", "OpResult", "Outcome", "Service", "TopicService", "create_app"]

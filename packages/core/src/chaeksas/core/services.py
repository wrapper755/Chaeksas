"""서비스 앱 태스크가 바깥 앱을 부르는 자리 — C11 (`chk:serviceCall`).

보내기(`core.senders`)와 같은 꼴이다. 엔진은 **무엇을 부를지**만 만들고, 실제로 부르는 일은
실행하는 쪽이 끼우는 어댑터가 한다. 그래야 주소·키·비밀을 엔진이 들고 있지 않는다
([ADR-0013](../../../../docs/decisions/0013-api-keys.md) — 키 값은 실행하는 쪽의 비밀 저장소에만).

**어댑터를 주지 않으면 부르지 않고 실패한다.** 조용히 건너뛰면 업무가 안 돌아간 채로 흘러간다.

재시도는 **엔진이** 한다 (`chk:serviceCall.retry`를 아는 쪽이 엔진이다). 어댑터는 한 번 왕복할
뿐이고, 다시 부를 만한 실패인지만 `ServiceCallError.retryable`로 알려 준다 (C11 §오류).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from chaeksas.contracts.service_app import Caller, OpRequest, OpResponse

#: C11 §오류 — 다시 불러 볼 만한 상태 코드. `chk:serviceCall.retry.on`의 기본값이기도 하다.
RETRYABLE_STATUS = (429, 503, 504)

#: 다시 불러도 똑같은 것 (키·권한·입력·없는 작업). 사람이 고쳐야 한다.
FATAL_CODES = frozenset(
    {
        "key_missing", "key_invalid", "key_revoked", "key_expired",
        "operation_not_allowed", "mode_not_allowed", "operation_not_found",
        "idempotency_conflict", "input_invalid", "mode_unsupported", "schema_unsupported",
    }
)


class ServiceCallError(RuntimeError):
    """서비스 앱 호출이 실패했다.

    `retryable`이 참이면 엔진이 `chk:serviceCall.retry`에 따라 `attempt`를 올려 다시 부른다.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class OpCall:
    """부를 작업 하나. **키 값은 들어 있지 않다** — `key_ref`(참조 이름)만 있다."""

    app_id: str
    operation: str
    mode: str  # autonomous | deterministic
    input: Mapping[str, Any]
    run_id: str
    node_id: str
    node_instance: int = 1
    attempt: int = 1
    call_seq: int = 1
    key_ref: str | None = None
    timeout_s: float | None = None
    bpm_process_id: str = ""
    version: str = "0.0.0"

    def request(self, caller: Caller) -> OpRequest:
        """C11 `OpRequest`. 멱등 키 `(operation, run_id, node_id, node_instance, attempt, call_seq)`."""
        return OpRequest(
            schema=1,
            mode=self.mode,
            run_id=self.run_id,
            node_id=self.node_id,
            node_instance=self.node_instance,
            attempt=self.attempt,
            call_seq=self.call_seq,
            caller=caller,
            input=dict(self.input),
        )


@dataclass(frozen=True)
class OpOutcome:
    """부른 결과. C3 `service_call`에 그대로 실린다 (**값은 `output`에만** 있다)."""

    output: Mapping[str, Any]
    status: int = 200
    mode_used: str = "deterministic"
    replayed: bool = False
    duration_ms: int = 0
    usage: Mapping[str, Any] | None = None

    @classmethod
    def of(cls, response: OpResponse, *, duration_ms: int, status: int = 200) -> OpOutcome:
        return cls(
            output=dict(response.output),
            status=status,
            mode_used=response.mode_used,
            replayed=response.replayed,
            duration_ms=duration_ms,
            usage=response.usage.model_dump() if response.usage else None,
        )

    def event_data(self, call: OpCall) -> dict[str, Any]:
        """C3 `service_call`의 `data` (필수 키는 C3 표 그대로). **업무 값은 담지 않는다.**"""
        data: dict[str, Any] = {
            "app_id": call.app_id,
            "operation": call.operation,
            "mode": call.mode,
            "mode_used": self.mode_used,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "key_ref": call.key_ref or "",
            "node_instance": call.node_instance,
            "attempt": call.attempt,
            "call_seq": call.call_seq,
            "replayed": self.replayed,
        }
        if self.usage:
            data.update({k: self.usage[k] for k in ("model", "input_tokens", "output_tokens") if k in self.usage})
        return data


class ServiceCaller(Protocol):
    """서비스 앱 호출 어댑터. 한 번 왕복한다. 실패는 `ServiceCallError`로 올린다."""

    def call(self, request: OpCall) -> OpOutcome: ...


class NoServiceCaller:
    """기본 — **부르지 않고 실패한다.** 실행하는 쪽이 어댑터를 끼워야 부를 수 있다."""

    def call(self, request: OpCall) -> OpOutcome:
        raise ServiceCallError(
            f"서비스 앱 호출 어댑터가 없다 ({request.app_id}/{request.operation}) — 실행하는 쪽이 끼워야 한다"
        )


@dataclass
class RecordingServiceCaller:
    """시험용 — 부르지 않고 **무엇을 부르려 했는지** 담아 두고, 정해 둔 답을 돌려준다.

    `outputs`는 `"<app_id>/<operation>"` → 출력이다. 없으면 빈 출력을 돌려준다.
    `fails`에 같은 열쇠를 넣으면 그 작업만 실패한다 (재시도·오류 경계 시험).
    """

    outputs: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    fails: dict[str, ServiceCallError] = field(default_factory=dict)
    calls: list[OpCall] = field(default_factory=list)

    def call(self, request: OpCall) -> OpOutcome:
        self.calls.append(request)
        key = f"{request.app_id}/{request.operation}"
        failure = self.fails.get(key)
        if failure is not None:
            raise failure
        return OpOutcome(
            output=self.outputs.get(key, {}),
            mode_used=request.mode,
            duration_ms=0,
        )


# ─────────────────────────── 진짜로 부르는 것 (HTTP) ───────────────────────────


class Addresses(Protocol):
    """`app_id` → 주소, `key_ref` → 키 값. 실행하는 쪽(Bot UI·Studio)이 준다.

    키 값은 **여기서만** 나온다 — 엔진·BPM 프로세스·실행 기록은 참조 이름만 안다 (ADR-0013).
    """

    def base_url(self, app_id: str) -> str | None: ...

    def key(self, key_ref: str) -> str | None: ...


@dataclass
class HttpServiceCaller:
    """C11 `POST /v1/ops/{operation}`를 부른다.

    `client`를 넣으면 그것을 쓴다 (시험에서 ASGI로 바로 붙인다 — `apps/center` 시험과 같은 수법).
    """

    addresses: Addresses
    caller_type: str = "bot_ui"  # C11 `caller.type`
    host: str = ""
    default_timeout_s: float = 60.0
    client: Any | None = None  # httpx.Client

    def call(self, request: OpCall) -> OpOutcome:
        import httpx  # noqa: PLC0415 — 부를 때만 든다 (화면 없는 실행에서 시작이 빨라진다)

        base = self.addresses.base_url(request.app_id)
        if not base:
            raise ServiceCallError(f"서비스 앱 주소를 모른다: {request.app_id} (리소스 목록·설정 확인)")
        if request.key_ref is None:
            raise ServiceCallError(f"{request.app_id}: 키 참조가 없다 (B7)", code="key_missing")
        key = self.addresses.key(request.key_ref)
        if not key:
            raise ServiceCallError(
                f"키 참조 「{request.key_ref}」의 값이 이 PC에 없다", code="key_missing"
            )

        caller = Caller(
            type=self.caller_type,
            host=self.host,
            bpm_process_id=request.bpm_process_id,
            version=request.version,
        )
        payload = request.request(caller).to_json_dict()
        timeout = request.timeout_s or self.default_timeout_s
        own = self.client is None
        client = self.client or httpx.Client(timeout=timeout)
        started = time.monotonic()
        try:
            response = client.post(
                f"{base.rstrip('/')}/v1/ops/{request.operation}",
                json=payload,
                # 키·토큰은 ASCII만 (CLAUDE.md §5 — 헤더에 한글을 넣지 않는다).
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise ServiceCallError(
                f"{request.app_id}에 닿지 못했다 ({type(e).__name__})", retryable=True
            ) from e
        finally:
            if own:
                client.close()
        duration_ms = int((time.monotonic() - started) * 1000)

        if response.status_code >= 400:
            raise _problem(request, response)
        try:
            found = OpResponse.model_validate(response.json())
        except ValueError as e:
            raise ServiceCallError(f"{request.app_id}의 응답이 C11 모양이 아니다: {e}") from e
        return OpOutcome.of(found, duration_ms=duration_ms, status=response.status_code)


def _problem(call: OpCall, response: Any) -> ServiceCallError:
    """C11 §오류의 본문(`{code, message, detail}`)을 예외로 바꾼다."""
    code, message = None, None
    try:
        body = response.json()
        code, message = body.get("code"), body.get("message")
    except ValueError:
        pass
    shown = message or f"{call.app_id}이 {response.status_code}를 돌려줬다"
    retryable = response.status_code in RETRYABLE_STATUS and code not in FATAL_CODES
    return ServiceCallError(shown, code=code, status=response.status_code, retryable=retryable)


__all__ = [
    "FATAL_CODES",
    "RETRYABLE_STATUS",
    "Addresses",
    "HttpServiceCaller",
    "NoServiceCaller",
    "OpCall",
    "OpOutcome",
    "RecordingServiceCaller",
    "ServiceCallError",
    "ServiceCaller",
]

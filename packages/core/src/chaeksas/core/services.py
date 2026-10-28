"""서비스 앱 태스크가 바깥 앱을 부르는 자리 — `chk:serviceCall` (C11·C15).

보내기(`core.senders`)와 같은 꼴이다. 엔진은 **무엇을 부를지**만 만들고, 실제로 부르는 일은
실행하는 쪽이 끼우는 어댑터가 한다. 제품의 어댑터는 `CenterServiceCaller` 하나다 — Center에
외부 작업으로 올리고 일꾼이 끝내기를 기다린다 ([ADR-0102](../../../../docs/decisions/0102-calling-outside-is-pull.md)).
부르는 쪽은 바깥 앱의 주소도 키도 모른다.

**어댑터를 주지 않으면 부르지 않고 실패한다.** 조용히 건너뛰면 업무가 안 돌아간 채로 흘러간다.

재시도는 **엔진이** 한다 (`chk:serviceCall.retry`를 아는 쪽이 엔진이다). 어댑터는 한 번 왕복할
뿐이고, 다시 부를 만한 실패인지만 `ServiceCallError.retryable`로 알려 준다 (C11 §오류).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from chaeksas.contracts.service_app import Caller

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


@dataclass(frozen=True)
class OpOutcome:
    """부른 결과. C3 `service_call`에 그대로 실린다 (**값은 `output`에만** 있다)."""

    output: Mapping[str, Any]
    status: int = 200
    mode_used: str = "deterministic"
    replayed: bool = False
    duration_ms: int = 0
    usage: Mapping[str, Any] | None = None

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


# ─────────────────────────── 진짜로 부르는 것 — C15 외부 작업 ───────────────────────────

#: C15 실패 코드 → C14 `retry.on`이 읽는 HTTP 숫자 (C14 — `dependency_down`=503·`rate_limited`=429·`timeout`=504).
STATUS_OF_CODE = {"dependency_down": 503, "rate_limited": 429, "timeout": 504, "no_consumer": 504}
#: 결과를 한 번 기다릴 때 물고 있는 시간 (초, C15 상한).
_WAIT_S = 25
#: 기한 뒤에도 Center가 만료를 적을 때까지 더 기다려 주는 여유 (초).
_SLACK_S = 30.0


TokenSource = Any  # () -> str | None — 부를 때마다 읽는다(호출 토큰은 24시간마다 바뀐다)


@dataclass
class CenterServiceCaller:
    """`chk:serviceCall`을 **Center에 외부 작업으로 올리고** 결과를 기다린다 (C15, ADR-0102).

    부르는 쪽은 서비스 앱·외부 앱의 주소도 키도 모른다 — Center 주소와 토큰(서버 실행기·Studio는
    제 Center API 키, Bot UI의 실행기 자식은 호출 토큰)뿐이다. 엔진은 무엇이 바뀌었는지 모른다 —
    `ServiceCaller` 자리에 들어갈 뿐이다.

    - 같은 멱등 칸(C11 여섯 칸)이면 Center가 **같은 일감**을 돌려준다 — 되살린 실행이 다시 불러도
      한 번만 수행된다 (원칙 9).
    - 실패는 C15 `error.code`를 그대로 싣고, `retry.on`이 읽게 HTTP 숫자로도 옮긴다(`STATUS_OF_CODE`).
    - 결과를 받으면 `ack`한다 — 그래야 Center가 업무 값을 지운다 (C15 셋째 규칙).
    """

    base_url: str
    token: TokenSource
    caller_type: str = "bot_ui"  # C11 `caller.type`
    host: str = ""
    default_timeout_s: float = 60.0
    client: Any | None = None  # httpx.Client (시험은 ASGI로 바로 붙인다)
    sleep: Any = time.sleep

    def _client(self) -> Any:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        return self.client or httpx.Client(base_url=self.base_url, timeout=_WAIT_S + 15.0)

    def _headers(self) -> dict[str, str]:
        token = self.token() if callable(self.token) else self.token
        if not token:
            raise ServiceCallError("Center에 올릴 토큰이 없다 (호출 토큰·Center API 키)", code="token_missing")
        return {"Authorization": f"Bearer {token}"}

    def call(self, request: OpCall) -> OpOutcome:
        import httpx  # noqa: PLC0415

        timeout = int(request.timeout_s or self.default_timeout_s)
        body = {
            "schema": 1,
            "topic": request.app_id,
            "operation": request.operation,
            "mode": request.mode,
            "idempotency": {
                "run_id": request.run_id,
                "node_id": request.node_id,
                "node_instance": request.node_instance,
                "attempt": request.attempt,
                "call_seq": request.call_seq,
            },
            "caller": Caller(
                type=self.caller_type, host=self.host, bpm_process_id=request.bpm_process_id, version=request.version
            ).to_json_dict(),
            "input": dict(request.input),
            "timeout_s": timeout,
            "origin": "test" if request.run_id.startswith("test_") else "run",
        }
        own = self.client is None
        client = self._client()
        started = time.monotonic()
        try:
            made = client.post("/api/v1/external-tasks", json=body, headers=self._headers())
            if made.status_code >= 400:
                raise _refused(request, made)
            task_id = str(made.json()["task_id"])
            until = started + timeout + _SLACK_S
            while True:
                got = client.get(
                    f"/api/v1/external-tasks/{task_id}", params={"wait_s": _WAIT_S}, headers=self._headers()
                )
                if got.status_code == 503:
                    self.sleep(1.0)  # 롱폴링 상한 — 잠깐 쉬고 다시 건다
                    continue
                if got.status_code >= 400:
                    raise _refused(request, got)
                result = got.json()
                if result.get("state") in ("completed", "failed", "expired", "cancelled"):
                    break
                if time.monotonic() > until:
                    raise ServiceCallError(
                        f"{request.app_id}/{request.operation}: 기한이 지났는데 끝나지 않았다", code="timeout",
                        status=504, retryable=True,
                    )
            with contextlib.suppress(httpx.HTTPError):
                client.post(f"/api/v1/external-tasks/{task_id}/ack", headers=self._headers())
        except httpx.HTTPError as e:
            raise ServiceCallError(f"Center에 닿지 못했다 ({type(e).__name__})", retryable=True) from e
        finally:
            if own:
                client.close()
        duration_ms = int((time.monotonic() - started) * 1000)
        state = result.get("state")
        if state != "completed":
            error = result.get("error") or {}
            code = str(error.get("code") or state or "failed")
            raise ServiceCallError(
                str(error.get("message") or f"{request.app_id}/{request.operation}: {state}"),
                code=code,
                status=STATUS_OF_CODE.get(code),
                retryable=bool(error.get("retryable")),
            )
        return OpOutcome(
            output=dict(result.get("output") or {}),
            status=200,
            mode_used=str(result.get("mode_used") or request.mode),
            replayed=bool(result.get("replayed")),
            duration_ms=duration_ms,
            usage=result.get("usage") or None,
        )


def _refused(call: OpCall, response: Any) -> ServiceCallError:
    """Center가 올리기를 거절했다 (C15 §오류) — 「불러도 되나」는 다시 해도 같다."""
    code, message = None, None
    try:
        found = response.json()
        code, message = found.get("code"), found.get("message")
    except ValueError:
        pass
    shown = message or f"Center가 {call.app_id}/{call.operation}을 {response.status_code}로 거절했다"
    return ServiceCallError(shown, code=code, status=response.status_code, retryable=False)


__all__ = [
    "FATAL_CODES",
    "RETRYABLE_STATUS",
    "STATUS_OF_CODE",
    "CenterServiceCaller",
    "NoServiceCaller",
    "OpCall",
    "OpOutcome",
    "RecordingServiceCaller",
    "ServiceCallError",
    "ServiceCaller",
]

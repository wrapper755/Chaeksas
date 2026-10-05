"""UI 태스크 수행기 — Bot이 Worker 프로세스에 UI 조작을 맡긴다 (C10).

흐름은 하나다 (01-architecture §3).

1. `chk:task`의 UI 태스크 속성(C14)과 `key_ref`로 푼 서비스 앱 키를 들고
2. 127.0.0.1의 Worker에 세션을 열고 (`business_key`가 세션을 잇는다)
3. 스텝을 하나씩 보낸다 — **사다리는 Worker가 로컬에서** 탄다 (C8)
4. 닫으면서 받은 요약으로 C3 `ui_session`을 만든다

지키는 것 넷.

- **시맨틱 키로만 말한다** — 셀렉터는 이 경계를 넘지 않는다.
- **토큰은 호출마다 파일에서 읽는다.** Worker가 다시 뜨면 토큰이 바뀐다 (ADR-0023) — 401을
  받으면 한 번 다시 읽고 재시도한다.
- **Worker가 다시 떴을 때 함부로 다시 하지 않는다** (C10 §3). 성공한 조작 스텝이 하나라도
  있었으면 **확인으로 사람에게 넘긴다** — 같은 입력이 두 번 들어간다.
- **전환(`escalated`)은 실패가 아니다** — 확인으로 넘긴다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registration import (
    AnalyzeRequest,
    AnalyzeResult,
    Candidate,
    VerifyResult,
)
from chaeksas.ext.ui_automation.contracts.worker_local import (
    CALLER_BOT,
    DEFAULT_PORT,
    LOCAL_HOST,
    RESULT_ESCALATED,
    RESULT_FAILED,
    SESSION_HEADER,
    SESSION_LOCKED,
    STEP_TIMEOUT_S,
    TOKEN_FILE,
    TOKEN_HEADER,
    Caller,
    CloseResult,
    SessionInfo,
    SessionRequest,
    StepRequest,
    StepResult,
    business_key,
    can_retry_whole_task,
)
from chaeksas.extension_api import TaskContext, TaskFailed, TaskOutcome

log = logging.getLogger(__name__)

#: 확인으로 넘길 때 사람에게 보일 말 (CMN-01).
RESTARTED_MESSAGE = (
    "화면 조작 도중 Worker가 다시 시작되었습니다. 화면 상태를 확인한 뒤 계속/중단을 고르세요."
)
ESCALATED_MESSAGE = "화면에서 요소를 찾지 못했습니다. 화면을 확인한 뒤 계속/중단을 고르세요."

#: C13 §4의 「결과를 모른다」 — 실행기가 확인(CMN-01)으로 넘긴다.
ESCALATE_CONFIRMATION = "confirmation"


class WorkerUnreachable(RuntimeError):
    """Worker에 닿지 못했다 — Bot UI가 띄우지 못했거나 죽었다."""


@dataclass
class WorkerClient:
    """Worker 로컬 API를 부르는 쪽 (C10).

    **토큰은 호출마다 파일에서 읽는다** — Worker가 다시 뜨면 바뀐다.
    """

    token_dir: Path
    port: int = DEFAULT_PORT
    timeout_s: float = STEP_TIMEOUT_S + 10
    client: Any = None  # httpx.Client (시험이 끼운다)

    @property
    def base_url(self) -> str:
        return f"http://{LOCAL_HOST}:{self.port}"

    def token(self) -> str:
        path = self.token_dir / TOKEN_FILE
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def call(
        self, method: str, path: str, *, body: Any = None, secret: str | None = None
    ) -> dict[str, Any]:
        """한 번 부른다. **401이면 토큰을 다시 읽고 한 번만** 다시 부른다 (ADR-0023)."""
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        for retry in (False, True):
            headers = {TOKEN_HEADER: self.token()}
            if secret:
                headers[SESSION_HEADER] = secret
            own = self.client is None
            client = self.client or httpx.Client(timeout=self.timeout_s)
            try:
                response = client.request(
                    method, f"{self.base_url}{path}", json=body, headers=headers
                )
            except httpx.HTTPError as e:
                raise WorkerUnreachable(f"Worker에 닿지 못했다 ({type(e).__name__})") from e
            finally:
                if own:
                    client.close()

            if response.status_code == 401 and not retry:
                continue  # 토큰이 바뀌었다 — 다시 읽어 한 번 더
            return _checked(response)
        raise WorkerUnreachable("Worker 토큰이 계속 맞지 않는다")  # pragma: no cover

    # ── C10 경로 ──

    def open(self, request: SessionRequest) -> SessionInfo:
        return SessionInfo.model_validate(self.call("POST", "/v1/sessions", body=request.to_json_dict()))

    def step(self, session_id: str, secret: str, request: StepRequest) -> StepResult:
        return StepResult.model_validate(
            self.call(
                "POST", f"/v1/sessions/{session_id}/steps", body=request.to_json_dict(), secret=secret
            )
        )

    def info(self, session_id: str, secret: str) -> SessionInfo:
        return SessionInfo.model_validate(self.call("GET", f"/v1/sessions/{session_id}", secret=secret))

    def close(self, session_id: str, secret: str) -> CloseResult:
        return CloseResult.model_validate(
            self.call("DELETE", f"/v1/sessions/{session_id}", secret=secret)
        )

    # ── 셀렉터 등록 (C10 §5) — **여기만 물리 정보가 넘어온다** ──

    def open_registration(self, start_url: str, *, headed: bool = True) -> SessionInfo:
        return SessionInfo.model_validate(
            self.call("POST", "/v1/registration/browser", body={"start_url": start_url, "headed": headed})
        )

    def analyze(self, session_id: str, secret: str, request: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult.model_validate(
            self.call(
                "POST",
                f"/v1/registration/{session_id}/analyze",
                body=request.to_json_dict(),
                secret=secret,
            )
        )

    def pick(self, session_id: str, secret: str, *, on: bool) -> None:
        self.call(
            "POST" if on else "DELETE", f"/v1/registration/{session_id}/pick", secret=secret
        )

    def picked(self, session_id: str, secret: str) -> tuple[list[Candidate], bool]:
        """담은 것을 **비워** 가져온다 (C10 §5)."""
        found = self.call("GET", f"/v1/registration/{session_id}/pick/events", secret=secret)
        return (
            [Candidate.model_validate(one) for one in found.get("candidates", [])],
            bool(found.get("picking")),
        )

    def highlight(self, session_id: str, secret: str, locators: Sequence[LocatorSpec]) -> int:
        found = self.call(
            "POST",
            f"/v1/registration/{session_id}/highlight",
            body={"locators": [one.to_json_dict() for one in locators]},
            secret=secret,
        )
        return int(found.get("found") or 0)

    def verify(
        self, session_id: str, secret: str, ladders: Mapping[str, Sequence[LocatorSpec]]
    ) -> VerifyResult:
        body = {"ladders": {key: [one.to_json_dict() for one in value] for key, value in ladders.items()}}
        return VerifyResult.model_validate(
            self.call("POST", f"/v1/registration/{session_id}/verify", body=body, secret=secret)
        )


def _checked(response: Any) -> dict[str, Any]:
    """C10 오류 본문을 우리 예외로 옮긴다."""
    if response.status_code < 400:
        found = response.json()
        return dict(found) if isinstance(found, dict) else {}
    body = response.json() if response.content else {}
    code = str(body.get("code") or f"http_{response.status_code}")
    message = str(body.get("message") or "Worker가 거절했다")
    if response.status_code == 404 and code == "session_not_found":
        raise SessionGone(message)
    if code == SESSION_LOCKED:
        raise ScreenLocked(message)
    raise TaskFailed(code, message, retryable=response.status_code >= 500)


class SessionGone(RuntimeError):
    """세션이 사라졌다 (Worker 재시작·유휴 시간 초과) — C10 §3으로 판단한다."""


class ScreenLocked(RuntimeError):
    """화면이 잠겨 있다 — **재시도 가능**하다 (풀릴 수 있다)."""


@dataclass
class UiTaskExecutor:
    """`task_types[].executor` — `extension_api.TaskExecutor`."""

    #: Bot UI가 토큰 파일을 두는 곳. 실행기가 환경에서 받는다.
    token_dir: Path | None = None
    port: int = DEFAULT_PORT
    client: WorkerClient | None = None
    #: 세션이 사라졌을 때 **읽기만 했으면** 한 번 다시 한다 (C10 §3).
    _done: list[StepResult] = field(default_factory=list)

    def worker(self, ctx: TaskContext) -> WorkerClient:
        if self.client is not None:
            return self.client
        where = self.token_dir or Path.cwd()
        return WorkerClient(token_dir=where, port=self.port)

    def execute(self, ctx: TaskContext) -> TaskOutcome:
        """UI 태스크 한 번. **다시 할지 말지는 C10 §3이 정한다.**"""
        try:
            return self._once(ctx, attempt=ctx.attempt)
        except SessionGone as e:
            # 세션이 사라졌다. 조작한 적이 없으면 **처음부터 한 번** 다시 한다.
            if not self._touched_the_screen():
                log.info("Worker가 다시 떴다 — 조작한 적이 없어 처음부터 다시 한다")
                return self._once(ctx, attempt=ctx.attempt + 1)
            # 조작했다면 같은 입력이 두 번 들어갈 수 있다 — **사람에게 넘긴다**.
            raise TaskFailed(
                "worker_restarted", RESTARTED_MESSAGE, escalate=ESCALATE_CONFIRMATION
            ) from e
        except WorkerUnreachable as e:
            raise TaskFailed("worker_unreachable", str(e), retryable=True) from e

    def _touched_the_screen(self) -> bool:
        return any(one.ok and one.action not in ("read", "read_table", "read_options", "read_selection")
                   for one in self._done)

    def _once(self, ctx: TaskContext, *, attempt: int) -> TaskOutcome:
        worker = self.worker(ctx)
        spec = dict(ctx.properties)
        steps = list(spec.get("steps") or [])
        key = ctx.business_key or business_key(ctx.run_id, ctx.node_id, ctx.node_instance, attempt)

        info = worker.open(
            SessionRequest(
                schema=1,
                caller=Caller(
                    type=CALLER_BOT,
                    run_id=ctx.run_id,
                    node_id=ctx.node_id,
                    node_instance=ctx.node_instance,
                    attempt=attempt,
                    bpm_process_id=spec.get("bpm_process_id"),
                ),
                mode=str(ctx.mode),
                business_key=key,
                page_id=str(spec.get("page_id") or ""),
                start_url=spec.get("start_url"),
                heal=bool(spec.get("heal", True)),
                service_key=ctx.extension.secret(ctx.key_ref) if ctx.key_ref else None,
            )
        )

        outputs: dict[str, Any] = {}
        self._done = []
        try:
            for raw in steps:
                result = worker.step(info.session_id, info.session_secret, _step(raw))
                self._done.append(result)
                if result.escalated:
                    # **실패가 아니다** — 사람이 화면을 보고 정한다 (CMN-01).
                    raise TaskFailed(
                        "ui_escalated", ESCALATED_MESSAGE, escalate=ESCALATE_CONFIRMATION
                    )
                if not result.ok:
                    raise TaskFailed(result.error_code or "ui_step_failed", result.error or "스텝 실패")
                # 읽은 값은 **BPM 프로세스 변수로** 간다 (기록에는 남지 않는다 — 원칙 6).
                if raw.get("result") and result.text is not None:
                    outputs[str(raw["result"])] = result.text
        finally:
            closed = _closed(worker, info)
            if closed is not None:
                outputs.setdefault("_ui_session", closed.summary.to_json_dict())
        return TaskOutcome(outputs=outputs)


def _step(raw: dict[str, Any]) -> StepRequest:
    return StepRequest(
        semantic_key=raw.get("key") or raw.get("semantic_key"),
        action=str(raw.get("action") or ""),
        value=raw.get("value"),
    )


def _closed(worker: WorkerClient, info: SessionInfo) -> CloseResult | None:
    """닫는다. **닫다 실패해도 태스크 결과를 바꾸지 않는다** (유휴 시간이 닫아 준다)."""
    try:
        return worker.close(info.session_id, info.session_secret)
    except Exception as e:  # noqa: BLE001 — 이미 끝난 일이다
        log.warning("세션을 닫지 못했다: %s", e)
        return None


def session_event(closed: CloseResult, *, business_key_: str, page_id: str) -> dict[str, Any]:
    """C3 `ui_session`의 `data` — 부르는 쪽이 이것으로 이벤트를 만든다.

    **값은 담지 않는다** (원칙 6) — 진행·폴백·치유만.
    """
    summary = closed.summary
    return {
        "business_key": business_key_,
        "page_id": page_id,
        "result": summary.result,
        "steps": summary.steps,
        "fallback_depth_max": summary.fallback_depth_max,
        "healed": summary.healed,
    }


__all__ = [
    "ESCALATED_MESSAGE",
    "ESCALATE_CONFIRMATION",
    "RESTARTED_MESSAGE",
    "RESULT_ESCALATED",
    "RESULT_FAILED",
    "ScreenLocked",
    "SessionGone",
    "UiTaskExecutor",
    "WorkerClient",
    "WorkerUnreachable",
    "can_retry_whole_task",
    "session_event",
]

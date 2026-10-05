"""C10 Worker 로컬 API — **127.0.0.1에만** 뜨는 작은 서버.

규칙은 C10이 정한 그대로다.

- **127.0.0.1 고정.** 주소는 바꿀 수 없고 포트만 바꾼다. 다른 PC에서 닿으면 안 된다.
- **토큰은 파일로** 주고받는다 (명령줄은 프로세스 목록에 뜬다). 사용 토큰과 관리 토큰 둘이고,
  다시 띄우면 둘 다 바뀐다. `/v1/health`만 토큰 없이 답한다 (기동 확인).
- **세션은 한 번에 하나** (ADR-0014 §4). 다른 쪽이 열면 409 `worker_busy`.
- **세션 비밀**이 있어야 그 세션을 만질 수 있다 — 남의 세션을 닫지 못하게.
- **실행 예약**(관리 토큰)이 걸려 있으면 그 `run_id`의 세션만 열린다.
- **화면을 실제로 만지는 일은 백엔드가 한다** (`Backend`). 여기서는 경계·상태·오류만 지킨다 —
  Windows UIA·브라우저 백엔드는 다음 조각이다. **없는 것을 되는 척하지 않는다.**
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from chaeksas.ext.ui_automation.contracts.plan import (
    ORIGIN_RUN,
    ORIGIN_TEST,
    STATUS_ESCALATED,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    AttemptReport,
    Escalation,
    ExecutionPlan,
    HealedReport,
    LocatorSpec,
    PlanStep,
    SessionReport,
)
from chaeksas.ext.ui_automation.contracts.registration import (
    AnalyzeRequest,
    AnalyzeResult,
    VerifyResult,
)
from chaeksas.ext.ui_automation.contracts.worker_local import (
    ADMIN_HEADER,
    ADMIN_ONLY,
    BROWSER_UNAVAILABLE,
    CALLER_REGISTRATION,
    RESERVED,
    RESULT_ESCALATED,
    RESULT_FAILED,
    RESULT_SUCCESS,
    SCHEMA_UNSUPPORTED,
    SESSION_HEADER,
    SESSION_IDLE_S,
    SESSION_LOCKED,
    SESSION_NOT_FOUND,
    SESSION_SECRET_INVALID,
    STEP_TIMEOUT_S,
    TOKEN_HEADER,
    TOKEN_INVALID,
    UNKNOWN_SEMANTIC_KEY,
    WORKER_BUSY,
    Caller,
    CloseResult,
    Health,
    Holder,
    SessionBrief,
    SessionInfo,
    SessionRequest,
    SessionSummary,
    Status,
    StepRequest,
    StepResult,
    check_step,
)
from chaeksas.ext.ui_automation.worker.ladder import Finder, Healer, run_step

#: 최근 세션을 몇 개까지 들고 있나 (BUI-09).
RECENT_MAX = 20


class WorkerProblem(Exception):
    """C10 오류 하나 — `{code, message, detail}`로 나간다."""

    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


class Backend(Protocol):
    """화면을 실제로 만지는 쪽 (브라우저·Windows UIA).

    **여기가 바깥 세계다.** 주지 않으면 세션을 열 수 없다 — 「없는데 된 척」하지 않는다.

    **사다리는 여기서 타지 않는다** — 세션이 계획을 들고 `ladder.run_step()`을 부르고, 이쪽은
    `finder()`가 주는 찾기·조작만 한다 (C8: 폴백은 로컬에서).
    """

    def open(self, request: SessionRequest) -> str:
        """화면을 열고 지금 주소를 돌려준다."""
        ...

    def finder(self, business_key: str) -> Finder | None:
        """그 세션의 화면 — 사다리가 이것으로 찾고 조작한다."""
        ...

    def goto(self, session_id: str, url: str) -> str: ...

    def close(self, session_id: str) -> None: ...


@dataclass
class Session:
    """열린 세션 하나. **비밀은 연 쪽만 안다.**"""

    session_id: str
    secret: str
    request: SessionRequest
    opened_at: float
    current_url: str | None = None
    steps_run: int = 0
    mutating_steps_ok: int = 0
    fallback_depth_max: int = 0
    healed: bool = False
    escalated: bool = False
    failed: bool = False
    last_step: dict[str, Any] | None = None
    touched_at: float = 0.0
    #: 이 세션의 계획 (C8). 없으면 스텝을 밟을 수 없다.
    plan: ExecutionPlan | None = None
    plan_source: str = "server"
    #: 이 세션이 쓰는 계획·보고 길 (C8). **키가 세션마다 다르다** (C10 `service_key`).
    plans: Any = None
    #: 보고 재료 (C8 §report) — **업무 값은 담지 않는다**.
    attempts: list[AttemptReport] = field(default_factory=list)
    healed_locators: list[HealedReport] = field(default_factory=list)
    escalation: Escalation | None = None

    @property
    def holder(self) -> Holder:
        caller = self.request.caller
        return Holder(type=caller.type, run_id=caller.run_id, bpm_process_id=caller.bpm_process_id)

    def info(self) -> SessionInfo:
        return SessionInfo(
            session_id=self.session_id,
            session_secret=self.secret,
            page_id=self.request.page_id,
            current_url=self.current_url,
            plan_source=self.plan_source,
            steps_run=self.steps_run,
            mutating_steps_ok=self.mutating_steps_ok,
            last_step=self.last_step,
        )

    def report(self, *, duration_ms: int = 0) -> SessionReport:
        """C8 보고 — **읽은 값은 들어가지 않는다** (원칙 6)."""
        summary = self.summary()
        status = {
            RESULT_SUCCESS: STATUS_SUCCEEDED,
            RESULT_ESCALATED: STATUS_ESCALATED,
            RESULT_FAILED: STATUS_FAILED,
        }[summary.result]
        return SessionReport(
            schema=1,
            business_key=self.request.business_key,
            page_id=self.request.page_id or "",
            plan_id=self.plan.plan_id if self.plan else None,
            revision=self.plan.revision if self.plan else 1,
            origin=ORIGIN_TEST if self.request.caller.type == CALLER_REGISTRATION else ORIGIN_RUN,
            status=status,
            steps_completed=self.mutating_steps_ok + sum(1 for a in self.attempts if a.succeeded),
            steps_total=len(self.plan.steps) if self.plan else self.steps_run,
            attempts=list(self.attempts),
            healed=list(self.healed_locators),
            escalation=self.escalation,
            duration_ms=duration_ms,
        )

    def summary(self) -> SessionSummary:
        result = RESULT_SUCCESS
        if self.failed:
            result = RESULT_FAILED
        elif self.escalated:
            result = RESULT_ESCALATED
        return SessionSummary(
            result=result,
            steps=self.steps_run,
            fallback_depth_max=self.fallback_depth_max,
            healed=self.healed,
            escalated=self.escalated,
        )


@dataclass
class Worker:
    """Worker 한 벌의 상태. **세션은 하나**, 예약은 하나 (ADR-0014)."""

    token: str
    admin_token: str
    backend: Backend | None = None
    #: 계획을 받아 오고 보고를 보내는 쪽 (C8). 없으면 스텝을 밟을 수 없다.
    plans: Any = None
    #: 세션마다 그 길을 만드는 함수 (키가 세션마다 다르다). 있으면 `plans`보다 먼저 쓴다.
    plans_factory: Callable[[SessionRequest], Any] | None = None
    #: 치유를 묻는 길 (C8). 없으면 사다리가 다 실패했을 때 바로 전환이다.
    healer: Healer | None = None
    idle_s: float = SESSION_IDLE_S
    clock: Callable[[], float] = time.monotonic
    version: str = "0.1.0"

    session: Session | None = None
    reserved_for: str | None = None
    recent: list[SessionBrief] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)

    # ── 자리 ──

    def sweep(self) -> None:
        """유휴 세션을 닫는다 — 부르는 쪽이 죽어도 자리가 영원히 묶이지 않게 (C10 §전송)."""
        found = self.session
        if found is None:
            return
        if self.clock() - (found.touched_at or found.opened_at) > self.idle_s:
            self._end(found, failed=True)

    def open(self, request: SessionRequest) -> tuple[SessionInfo, bool]:
        """세션을 연다. 같은 `business_key`면 **열려 있는 그것**을 돌려준다 (멱등)."""
        self.sweep()
        found = self.session
        if found is not None:
            if found.request.business_key == request.business_key:
                found.touched_at = self.clock()
                return found.info(), False
            raise WorkerProblem(
                409, WORKER_BUSY, "다른 쪽이 UI 세션을 쥐고 있습니다", {"holder": found.holder.to_json_dict()}
            )
        if self.reserved_for and request.caller.run_id != self.reserved_for:
            raise WorkerProblem(
                409, RESERVED, "Worker가 다른 실행에 예약되어 있습니다", {"run_id": self.reserved_for}
            )
        if self.backend is None:
            # **없는 것을 되는 척하지 않는다** — 화면을 만질 수단이 없다.
            raise WorkerProblem(503, "browser_unavailable", "화면을 조작할 수단이 없습니다 (백엔드 없음)")

        made = Session(
            session_id=f"ses_{secrets.token_hex(4)}",
            secret=secrets.token_urlsafe(16),
            request=request,
            opened_at=self.clock(),
            touched_at=self.clock(),
        )
        try:
            made.current_url = self.backend.open(request)
        except Exception as e:  # noqa: BLE001 — 브라우저가 안 뜰 수 있다 (바이너리 없음·화면 없음)
            # **「없는데 된 척」하지 않는다.** 500으로 흘리면 부르는 쪽이 버그로 읽는다.
            raise WorkerProblem(
                503, BROWSER_UNAVAILABLE, f"화면을 열지 못했습니다 ({type(e).__name__})"
            ) from e
        made.plans = self._plans_for(request)
        if made.plans is not None and request.page_id:
            made.plan, made.plan_source = self._fetch_plan(request, made.plans)
            # 주소를 비워 보냈으면 **화면의 기본 주소**로 간다 (C10 `start_url`).
            if not request.start_url and made.plan is not None and made.plan.start_url:
                made.current_url = self.backend.goto(made.session_id, made.plan.start_url)
        self.session = made
        return made.info(), True

    def _plans_for(self, request: SessionRequest) -> Any:
        """이 세션의 계획·보고 길. **키는 세션이 준다** (ADR-0013)."""
        if self.plans_factory is not None:
            return self.plans_factory(request)
        return self.plans

    def _fetch_plan(self, request: SessionRequest, plans: Any) -> tuple[ExecutionPlan | None, str]:
        """계획을 받아 온다 (C8). 닿지 못하고 캐시도 없으면 502 — **없는 채로 열지 않는다**."""
        from chaeksas.ext.ui_automation.worker.plans import OpsUnreachable  # noqa: PLC0415

        try:
            found, source = plans.plan(
                page_id=request.page_id,
                platform="web",
                steps=[],
                start_url=request.start_url,
            )
        except OpsUnreachable as e:
            raise WorkerProblem(
                502, "ui_automation_unreachable", "UI 자동화 앱에 닿지 못했고 캐시도 없습니다"
            ) from e
        return found, str(source)

    def get(self, session_id: str, secret: str) -> Session:
        found = self.session
        if found is None or found.session_id != session_id:
            raise WorkerProblem(404, SESSION_NOT_FOUND, "그 세션이 없습니다 (닫혔거나 다시 떴습니다)")
        if secret != found.secret:
            raise WorkerProblem(401, SESSION_SECRET_INVALID, "다른 세션의 비밀입니다")
        found.touched_at = self.clock()
        return found

    # ── 스텝 ──

    def step(self, session_id: str, secret: str, request: StepRequest) -> StepResult:
        found = self.get(session_id, secret)
        problem = check_step(request, deterministic=found.request.mode == "deterministic")
        if problem is not None:
            raise WorkerProblem(422, problem, "요청 모양이 맞지 않습니다")
        if self.backend is None:  # pragma: no cover — 세션이 있으면 백엔드도 있다
            raise WorkerProblem(503, "browser_unavailable", "화면을 조작할 수단이 없습니다")

        result = self._climb(found, request)
        found.steps_run += 1
        found.fallback_depth_max = max(found.fallback_depth_max, result.fallback_depth)
        found.healed = found.healed or result.healed
        found.escalated = found.escalated or result.escalated
        if result.ok and request.action not in ("read", "read_table", "read_options", "read_selection"):
            found.mutating_steps_ok += 1
        if not result.ok and not result.escalated:
            found.failed = True
        if result.current_url:
            found.current_url = result.current_url
        # **값은 남기지 않는다** (원칙 6) — 무엇을 했는지만 (`data`·`text`는 빼고).
        found.last_step = {
            "semantic_key": result.semantic_key,
            "action": result.action,
            "ok": result.ok,
            "escalated": result.escalated,
        }
        return result

    def _climb(self, found: Session, request: StepRequest) -> StepResult:
        """계획의 사다리를 **로컬에서** 탄다 (C8) — 보고 재료도 여기서 모은다."""
        if found.plan is None:
            raise WorkerProblem(422, "unknown_semantic_key", "이 세션에 계획이 없습니다")
        finder = self.backend.finder(found.request.business_key) if self.backend else None
        if finder is None:  # pragma: no cover — 세션이 있으면 화면도 있다
            raise WorkerProblem(503, "browser_unavailable", "열린 화면이 없습니다")

        step = PlanStep(
            semantic_key=request.semantic_key or "",
            action=request.action,
            value=request.value,
        )
        if not found.plan.ladder(step.semantic_key):
            # 계획에 없는 요소다 — 등록하지 않았거나 모두 `deprecated`다 (C8·C10 같은 코드).
            raise WorkerProblem(
                422, UNKNOWN_SEMANTIC_KEY, f"계획에 없는 요소입니다: {step.semantic_key}"
            )
        attempt = run_step(step, found.plan, finder, heal=self.healer)
        self._remember(found, attempt)
        return StepResult(
            ok=attempt.ok,
            semantic_key=attempt.semantic_key,
            action=attempt.action,
            text=attempt.text,
            fallback_depth=attempt.fallback_depth,
            healed=attempt.healed,
            escalated=attempt.escalated,
            error_code=attempt.error_code,
            error=attempt.error,
            current_url=finder.url(),
            duration_ms=attempt.duration_ms,
        )

    def _remember(self, found: Session, attempt: Any) -> None:
        """보고 재료 (C8 §report). **읽은 값은 담지 않는다** (원칙 6)."""
        for index, key in enumerate(attempt.tried):
            last = index == len(attempt.tried) - 1
            found.attempts.append(
                AttemptReport(
                    semantic_key=attempt.semantic_key,
                    locator_key=key,
                    succeeded=attempt.ok and last,
                    elapsed_ms=attempt.duration_ms if last else 0,
                    failure_reason=None if (attempt.ok and last) else attempt.error_code,
                )
            )
        if attempt.healed and attempt.used is not None:
            found.healed_locators.append(
                HealedReport(
                    semantic_key=attempt.semantic_key,
                    locator=attempt.used,
                    supersedes=[k for k in attempt.tried if k != attempt.used.key],
                )
            )
        if attempt.escalated:
            found.escalation = Escalation(
                semantic_key=attempt.semantic_key,
                reason=attempt.error or "",
                attempts=len(attempt.tried),
            )

    def goto(self, session_id: str, secret: str, url: str) -> SessionInfo:
        found = self.get(session_id, secret)
        if self.backend is None:  # pragma: no cover
            raise WorkerProblem(503, "browser_unavailable", "화면을 조작할 수단이 없습니다")
        found.current_url = self.backend.goto(session_id, url)
        return found.info()

    def close(self, session_id: str, secret: str) -> CloseResult:
        found = self.get(session_id, secret)
        return self._end(found)

    def _end(self, found: Session, *, failed: bool = False) -> CloseResult:
        if failed:
            found.failed = True
        if self.backend is not None:
            self.backend.close(found.session_id)
        self.session = None
        summary = found.summary()
        sent = "queued"
        plans = found.plans if found.plans is not None else self.plans
        if plans is not None and found.request.report:
            sent = plans.report(found.report(duration_ms=_ms(self.clock() - found.opened_at)))
        self.recent.insert(
            0,
            SessionBrief(
                session_id=found.session_id,
                business_key=found.request.business_key,
                page_id=found.request.page_id,
                result=summary.result,
                steps=summary.steps,
                at=datetime.now(UTC).isoformat(),
            ),
        )
        del self.recent[RECENT_MAX:]
        return CloseResult(steps_run=summary.steps, summary=summary, report=sent)

    # ── 셀렉터 등록 (C10 §5) ──

    def registration_open(self, start_url: str, *, headed: bool = True) -> tuple[SessionInfo, bool]:
        """등록용 세션을 연다 (BUI-06 「브라우저 열기」).

        `business_key`는 **Worker가 짓는다** (`reg_<hex8>`, C10 §2) — 등록 화면이 실행 키를
        흉내 낼 일이 없다. `page_id`를 비워 두니 계획도 받아 오지 않는다 (아직 없는 쪽이다).
        """
        return self.open(
            SessionRequest(
                schema=1,
                caller=Caller(type=CALLER_REGISTRATION),
                mode="autonomous",
                business_key=f"reg_{secrets.token_hex(4)}",
                start_url=start_url or None,
                headed=headed,
                heal=False,
            )
        )

    def _registering(self, session_id: str, secret: str) -> Session:
        """등록 세션이어야 한다 — 실행 중인 Bot의 화면을 등록 화면이 헤집지 못하게."""
        found = self.get(session_id, secret)
        if found.request.caller.type != CALLER_REGISTRATION:
            raise WorkerProblem(403, SESSION_LOCKED, "등록용 세션이 아닙니다")
        return found

    def _surface(self, found: Session) -> Any:
        """분석이 들여다볼 화면. **없으면 없다고 말한다** — 데스크톱 백엔드는 아직 없다."""
        finder = self.backend.finder(found.request.business_key) if self.backend else None
        page = getattr(finder, "page", None)
        if page is None:
            raise WorkerProblem(
                503, BROWSER_UNAVAILABLE, "이 백엔드는 화면 분석을 지원하지 않습니다"
            )
        return page

    def analyze(self, session_id: str, secret: str, request: AnalyzeRequest) -> AnalyzeResult:
        from chaeksas.ext.ui_automation.worker.registration import analyze  # noqa: PLC0415

        found = self._registering(session_id, secret)
        return analyze(self._surface(found), request)

    def pick(self, session_id: str, secret: str, *, on: bool) -> None:
        """직접 고르기를 켜고 끈다 (BUI-06 3번)."""
        from chaeksas.ext.ui_automation.worker import registration  # noqa: PLC0415

        found = self._registering(session_id, secret)
        page = self._surface(found)
        registration.start_pick(page) if on else registration.stop_pick(page)

    def picked(self, session_id: str, secret: str) -> dict[str, Any]:
        """담은 것을 **비워** 가져온다. 한 번 준 것은 다시 주지 않는다."""
        from chaeksas.ext.ui_automation.worker import registration  # noqa: PLC0415

        found = self._registering(session_id, secret)
        candidates, picking = registration.drain_pick(self._surface(found))
        return {
            "candidates": [one.to_json_dict() for one in candidates],
            "picking": picking,
        }

    def highlight(self, session_id: str, secret: str, locators: list[LocatorSpec]) -> dict[str, Any]:
        from chaeksas.ext.ui_automation.worker import registration  # noqa: PLC0415

        found = self._registering(session_id, secret)
        return {"found": registration.highlight(self._surface(found), locators)}

    def verify(
        self, session_id: str, secret: str, ladders: dict[str, list[LocatorSpec]]
    ) -> VerifyResult:
        from chaeksas.ext.ui_automation.worker.registration import verify  # noqa: PLC0415

        found = self._registering(session_id, secret)
        finder = self.backend.finder(found.request.business_key) if self.backend else None
        if finder is None:  # pragma: no cover — 세션이 있으면 화면도 있다
            raise WorkerProblem(503, BROWSER_UNAVAILABLE, "열린 화면이 없습니다")
        return verify(finder, ladders)

    # ── 관리 (Bot UI만) ──

    def reserve(self, run_id: str) -> None:
        self.sweep()
        if self.session is not None and self.session.request.caller.run_id != run_id:
            raise WorkerProblem(
                409, WORKER_BUSY, "다른 쪽이 UI 세션을 쥐고 있습니다",
                {"holder": self.session.holder.to_json_dict()},
            )
        self.reserved_for = run_id

    def unreserve(self) -> None:
        """예약을 푼다 — 열린 세션도 닫는다 (실행이 끝났다)."""
        if self.session is not None:
            self._end(self.session, failed=True)
        self.reserved_for = None

    def force_close(self, session_id: str) -> bool:
        found = self.session
        if found is None or found.session_id != session_id:
            return False
        self._end(found, failed=True)
        return True

    # ── 보기 ──

    def health(self) -> Health:
        self.sweep()
        return Health(
            version=self.version,
            session="idle" if self.session is None else self.session.request.caller.type,
        )

    def status(self) -> Status:
        base = self.health()
        return Status(
            status=base.status,
            version=base.version,
            session=base.session,
            pid=os.getpid(),
            uptime_s=round(self.clock() - self.started_at, 3),
            reserved_for=self.reserved_for,
            holder=self.session.holder if self.session else None,
            recent_sessions=list(self.recent),
            unsent_reports=0,
        )


# ─────────────────────────── HTTP ───────────────────────────


def _ms(seconds: float) -> int:
    return int(seconds * 1000)


def create_app(worker: Worker) -> FastAPI:
    """C10 경로 한 벌. **`/v1/health`만 토큰 없이** 답한다."""
    app = FastAPI(title="Chaeksas Worker", version=worker.version)
    app.state.worker = worker
    router = APIRouter(prefix="/v1")

    def check_token(request: Request) -> None:
        if request.headers.get(TOKEN_HEADER) != worker.token:
            raise WorkerProblem(401, TOKEN_INVALID, "토큰이 맞지 않습니다 (Worker가 다시 떴을 수 있습니다)")

    def check_admin(request: Request) -> None:
        if request.headers.get(ADMIN_HEADER) != worker.admin_token:
            raise WorkerProblem(403, ADMIN_ONLY, "관리 토큰이 필요합니다")

    def secret_of(request: Request) -> str:
        return request.headers.get(SESSION_HEADER, "")

    @app.exception_handler(WorkerProblem)
    async def handle(_: Request, problem: WorkerProblem) -> JSONResponse:
        return JSONResponse(
            status_code=problem.status,
            content={"code": problem.code, "message": problem.message, "detail": problem.detail},
        )

    @router.get("/health")
    def health() -> Any:
        return worker.health()

    @router.get("/status")
    def status(request: Request) -> Any:
        check_token(request)
        return worker.status()

    @router.post("/sessions", status_code=201)
    async def open_session(request: Request) -> Any:
        check_token(request)
        body = await request.json()
        if int(body.get("schema") or 1) > SessionRequest.SCHEMA:
            raise WorkerProblem(422, SCHEMA_UNSUPPORTED, "이 Worker가 모르는 schema입니다")
        try:
            wanted = SessionRequest.model_validate(body)
        except ValueError as e:
            raise WorkerProblem(422, "input_invalid", "요청이 계약과 맞지 않습니다") from e
        info, fresh = worker.open(wanted)
        return JSONResponse(status_code=201 if fresh else 200, content=info.to_json_dict())

    @router.get("/sessions/{session_id}")
    def read_session(session_id: str, request: Request) -> Any:
        check_token(request)
        return worker.get(session_id, secret_of(request)).info()

    @router.post("/sessions/{session_id}/steps")
    async def run_step(session_id: str, request: Request) -> Any:
        check_token(request)
        body = await request.json()
        try:
            wanted = StepRequest.model_validate(body)
        except ValueError as e:
            raise WorkerProblem(422, "input_invalid", "요청이 계약과 맞지 않습니다") from e
        if wanted.timeout_s is None:
            wanted = wanted.model_copy(update={"timeout_s": STEP_TIMEOUT_S})
        return worker.step(session_id, secret_of(request), wanted)

    @router.post("/sessions/{session_id}/goto")
    async def goto(session_id: str, request: Request) -> Any:
        check_token(request)
        body = await request.json()
        return worker.goto(session_id, secret_of(request), str(body.get("url") or ""))

    @router.delete("/sessions/{session_id}")
    def close_session(session_id: str, request: Request) -> Any:
        check_token(request)
        return worker.close(session_id, secret_of(request))

    # ── 셀렉터 등록 (C10 §5) — **여기만 물리 정보가 나간다** ──

    @router.post("/registration/browser", status_code=201)
    async def registration_browser(request: Request) -> Any:
        check_token(request)
        body = await request.json()
        info, fresh = worker.registration_open(
            str(body.get("start_url") or ""), headed=bool(body.get("headed", True))
        )
        return JSONResponse(status_code=201 if fresh else 200, content=info.to_json_dict())

    @router.post("/registration/{session_id}/analyze")
    async def registration_analyze(session_id: str, request: Request) -> Any:
        check_token(request)
        body = await request.json()
        try:
            wanted = AnalyzeRequest.model_validate(body)
        except ValueError as e:
            raise WorkerProblem(422, "input_invalid", "요청이 계약과 맞지 않습니다") from e
        return worker.analyze(session_id, secret_of(request), wanted)

    @router.post("/registration/{session_id}/pick")
    def registration_pick(session_id: str, request: Request) -> Any:
        check_token(request)
        worker.pick(session_id, secret_of(request), on=True)
        return {"picking": True}

    @router.delete("/registration/{session_id}/pick")
    def registration_unpick(session_id: str, request: Request) -> Any:
        check_token(request)
        worker.pick(session_id, secret_of(request), on=False)
        return {"picking": False}

    @router.get("/registration/{session_id}/pick/events")
    def registration_picked(session_id: str, request: Request) -> Any:
        check_token(request)
        return worker.picked(session_id, secret_of(request))

    @router.post("/registration/{session_id}/highlight")
    async def registration_highlight(session_id: str, request: Request) -> Any:
        check_token(request)
        body = await request.json()
        try:
            locators = [LocatorSpec.model_validate(one) for one in (body.get("locators") or [])]
        except ValueError as e:
            raise WorkerProblem(422, "input_invalid", "요청이 계약과 맞지 않습니다") from e
        return worker.highlight(session_id, secret_of(request), locators)

    @router.post("/registration/{session_id}/verify")
    async def registration_verify(session_id: str, request: Request) -> Any:
        check_token(request)
        body = await request.json()
        try:
            ladders = {
                str(key): [LocatorSpec.model_validate(one) for one in value]
                for key, value in (body.get("ladders") or {}).items()
            }
        except (AttributeError, ValueError) as e:
            raise WorkerProblem(422, "input_invalid", "요청이 계약과 맞지 않습니다") from e
        return worker.verify(session_id, secret_of(request), ladders)

    @router.post("/admin/reserve")
    async def reserve(request: Request) -> Any:
        check_admin(request)
        body = await request.json()
        worker.reserve(str(body.get("run_id") or ""))
        return {"reserved_for": worker.reserved_for}

    @router.delete("/admin/reserve")
    def unreserve(request: Request) -> Any:
        check_admin(request)
        worker.unreserve()
        return {"reserved_for": None}

    @router.delete("/admin/sessions/{session_id}")
    def force_close(session_id: str, request: Request) -> Any:
        check_admin(request)
        return {"closed": worker.force_close(session_id)}

    app.include_router(router)
    return app


def write_tokens(token_dir: Path) -> tuple[str, str]:
    """토큰 파일 둘을 쓴다 (C10 §전송) — **다시 띄우면 둘 다 바뀐다**.

    현재 사용자만 읽을 수 있게 둔다. Windows는 ACL이라 `chmod`가 소용없지만, 사용자 데이터
    폴더 자체가 그 사용자 것이다.
    """
    from chaeksas.ext.ui_automation.contracts.worker_local import ADMIN_TOKEN_FILE, TOKEN_FILE

    token_dir.mkdir(parents=True, exist_ok=True)
    token, admin = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    for name, value in ((TOKEN_FILE, token), (ADMIN_TOKEN_FILE, admin)):
        path = token_dir / name
        path.write_text(value + "\n", encoding="utf-8", newline="\n")
        path.chmod(0o600)
    return token, admin


def read_token(token_dir: Path, name: str) -> str:
    """토큰 파일 하나 — **호출마다(또는 401을 받으면) 다시 읽는다** (ADR-0023)."""
    path = token_dir / name
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


__all__ = [
    "RECENT_MAX",
    "Backend",
    "Session",
    "Worker",
    "WorkerProblem",
    "create_app",
    "read_token",
    "write_tokens",
]

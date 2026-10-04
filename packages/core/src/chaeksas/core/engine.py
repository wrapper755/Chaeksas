"""BPMN 실행 — 엔진 뼈대 (M3 조각 2).

**한 걸음씩 돈다.** `step()`이 노드 하나를 수행하고 다음 자리로 토큰을 옮긴다. 사람을 기다리면
거기서 멈추고(`State.WAITING`) 답이 오면 이어 간다 — PC Bot은 기다리는 동안에도 **실행 자리를
쥐고 있다** (ADR-0014). 그래서 엔진은 스레드를 만들지 않는다: 부르는 쪽(Bot UI·Studio)이 돈다.

지금 다루는 노드는 시작·종료·스크립트·배타 게이트웨이·결재/확인이다. 나머지 C14 노드(AI·서비스
앱·DMN·반복·타이머·메시지 …)는 **수행기를 끼우는 자리**(`Engine.handlers`)로 열어 두었다 —
조각 3에서 더한다. 모르는 노드를 만나면 조용히 지나가지 않고 **멈춘다**.

기록은 C3 그대로 남긴다 (`run_log.RunLog`). 업무 값은 담지 않는다 (계약 원칙 6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from chaeksas.contracts.approvals import Form, FormField, request_id_for
from chaeksas.contracts.bpmn_ext import BpmnProcess, Flow, Node
from chaeksas.core.expr import ExprError, Scope, evaluate, fill, run_script, truthy
from chaeksas.core.helpers import bind
from chaeksas.core.run_log import RunLog, summarize

log = logging.getLogger(__name__)

#: 한 번 `run_until_blocked()`에서 밟을 노드 수 한도 (돌고 도는 그림을 막는 그물).
MAX_STEPS = 10_000

#: 엔진이 늘 주는 변수 (C14 §9). 이름이 늘면 `contracts.bpmn_ext.BUILTIN_VARS`도 함께 고친다.
BUILTIN_TODAY = "오늘"
BUILTIN_NOW = "지금"
BUILTIN_RUN_ID = "run_id"

#: 결재·확인에서 폼을 주지 않았을 때의 답 (C6 — 「없으면 승인 / 반려 두 단추」).
DECISION_KEY = "decision"


class State(StrEnum):
    """실행의 지금 상태."""

    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"  # 사람·메시지·타이머를 기다린다
    DONE = "done"
    FAILED = "failed"


class EngineError(RuntimeError):
    """실행을 멈춰야 하는 문제. 노드 id를 달고 나온다."""

    def __init__(self, message: str, *, node_id: str | None = None, code: str = "engine_error") -> None:
        self.node_id = node_id
        self.code = code
        super().__init__(f"[{node_id}] {message}" if node_id else message)


@dataclass
class Pending:
    """사람을 기다리는 중인 요청 (결재·확인)."""

    request_id: str
    node_id: str
    layer: str  # approval | confirmation
    title: str
    form: Form | None
    #: 결재자에게 보여 줄 값 (C6 `review` — 원칙 6의 예외다).
    review: dict[str, Any] = field(default_factory=dict)
    where: str = "field"  # field | center
    node_instance: int = 1


#: 노드 수행기 — 노드를 받아 **끝났는가**를 돌려준다. 거짓이면 기다린다 (사람·메시지).
Handler = Callable[["Run", Node], bool]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Run:
    """실행 하나. 변수·토큰·기록을 들고 있다."""

    run_id: str
    process: BpmnProcess
    log: RunLog
    variables: dict[str, Any] = field(default_factory=dict)
    state: State = State.READY
    #: 토큰이 놓인 노드 (다음에 수행할 것). 비면 끝났다.
    token: str | None = None
    pending: Pending | None = None
    mode: str = "autonomous"
    started: datetime = field(default_factory=_utc_now)
    error: EngineError | None = None
    #: 노드마다 몇 번째 수행인지 (C6 `node_instance`·C10 `business_key`).
    instances: dict[str, int] = field(default_factory=dict)
    helpers: Mapping[str, Callable[..., Any]] = field(default_factory=dict)

    # ── 자주 쓰는 것 ──

    def node(self, node_id: str) -> Node:
        found = next((n for n in self.process.all_nodes() if n.id == node_id), None)
        if found is None:
            raise EngineError(f"노드를 찾지 못했다: {node_id}", code="node_missing")
        return found

    def scope(self, node_id: str | None = None) -> Scope:
        """식이 볼 것. **변수를 그대로 넘긴다** — 스크립트가 여기에 대입한다."""
        return Scope(variables=self.variables, helpers=self.helpers, where=node_id)

    def outgoing(self, node_id: str) -> list[Flow]:
        flows = list(self.process.flows) + [f for n in self.process.all_nodes() for f in n.child_flows]
        return [f for f in flows if f.source == node_id]

    @property
    def finished(self) -> bool:
        return self.state in (State.DONE, State.FAILED)


class Engine:
    """노드 수행기를 모아 놓은 것. 수행기를 더하면 다루는 노드가 늘어난다."""

    def __init__(self, *, handlers: Mapping[str, Handler] | None = None) -> None:
        self.handlers: dict[str, Handler] = {**DEFAULT_HANDLERS, **(handlers or {})}

    # ── 시작 ──

    def start(
        self,
        process: BpmnProcess,
        *,
        run_id: str,
        log: RunLog,
        inputs: Mapping[str, Any] | None = None,
        mode: str = "autonomous",
        source: str = "manual",
        executor: str = "bot_ui",
        version: str = "0.0.0",
        now: datetime | None = None,
        job_id: str | None = None,
    ) -> Run:
        """실행을 만들고 `run_started`를 남긴다. 토큰은 시작 이벤트에 놓인다."""
        at = now or _utc_now()
        run = Run(
            run_id=run_id,
            process=process,
            log=log,
            mode=mode,
            started=at,
            helpers=bind(now=at),
        )
        run.variables.update(self._seed(process, inputs or {}, run_id=run_id, now=at))

        log.emit(
            "run_started",
            bpm_process_id=process.id,
            version=version,
            run_location=process.info.run_location or "pc",
            executor=executor,
            mode=mode,
            source=source,
            **({"job_id": job_id} if job_id else {}),
        )
        run.token = self._start_node(process)
        run.state = State.RUNNING
        return run

    def _seed(
        self, process: BpmnProcess, inputs: Mapping[str, Any], *, run_id: str, now: datetime
    ) -> dict[str, Any]:
        """프로세스 변수의 처음 값.

        선언한 입력은 **준 값 → 기본값 → `None`** 순이다 (C14 §6 — 그래서
        `대상월 = 대상월 or 지난달()`이 된다). 선언하지 않은 입력을 주면 거부한다 — 이름을
        잘못 적은 것을 조용히 흘리면 식이 `None`으로 돌아 엉뚱한 값이 나온다.
        """
        declared = {decl.name for decl in process.info.inputs}
        unknown = sorted(set(inputs) - declared)
        if unknown:
            raise EngineError(
                f"선언하지 않은 입력이다: {', '.join(unknown)} "
                f"(선언된 것: {', '.join(sorted(declared)) or '없음'})",
                code="input_unknown",
            )

        variables: dict[str, Any] = {}
        for decl in process.info.inputs:
            if decl.name in inputs:
                variables[decl.name] = inputs[decl.name]
            elif decl.has_default:
                variables[decl.name] = decl.default
            else:
                if decl.required:
                    raise EngineError(f"입력 「{decl.name}」이 필요하다", code="input_required")
                variables[decl.name] = None

        # 엔진이 늘 주는 변수 (C14 §9).
        variables[BUILTIN_TODAY] = now.date().isoformat()
        variables[BUILTIN_NOW] = now.isoformat()
        variables[BUILTIN_RUN_ID] = run_id
        return variables

    def _start_node(self, process: BpmnProcess) -> str:
        starts = [n for n in process.nodes if n.kind == "startEvent"]
        if not starts:
            raise EngineError("시작 이벤트가 없다", code="no_start")
        if len(starts) > 1:
            # 여러 시작(메시지·타이머)은 조각 3이다 — 지금은 어느 것인지 고를 수 없다.
            raise EngineError(
                f"시작 이벤트가 {len(starts)}개다 — 메시지·타이머 시작은 아직 다루지 않는다",
                code="many_starts",
            )
        return starts[0].id

    # ── 한 걸음 ──

    def step(self, run: Run) -> State:
        """노드 하나를 수행하고 다음으로 옮긴다. 기다리게 되면 `WAITING`을 돌려준다."""
        if run.finished:
            return run.state
        if run.state is State.WAITING:
            return run.state
        if run.token is None:
            return self._finish(run, "success")

        node = run.node(run.token)
        handler = self.handlers.get(node.kind)
        if handler is None:
            return self._fail(
                run,
                EngineError(
                    f"아직 다루지 않는 노드다: {node.kind} (조각 3에서 더한다)",
                    node_id=node.id,
                    code="node_kind_unsupported",
                ),
            )

        run.instances[node.id] = run.instances.get(node.id, 0) + 1
        run.log.emit("node_state", node_id=node.id, state="started", task_type=_task_type(node))
        # 수행과 **다음 자리 고르기**를 같은 자리에서 받는다 — 둘 다 실행을 실패로 끝내야 한다
        # (게이트웨이의 「조건이 모두 거짓」이 밖으로 터져 나오면 부르는 쪽이 실행을 잃는다).
        try:
            done = handler(run, node)
            if not done:
                # 사람·메시지를 기다린다. PC Bot은 `node_state: waiting`만 남긴다 (C3).
                run.log.emit("node_state", node_id=node.id, state="waiting", task_type=_task_type(node))
                run.state = State.WAITING
                return run.state

            run.log.emit("node_state", node_id=node.id, state="completed", task_type=_task_type(node))
            if node.kind == "endEvent":
                run.token = None
                return self._finish(run, "success")
            next_id = self._next(run, node)
        except ExprError as e:
            return self._fail(run, EngineError(e.reason, node_id=node.id, code="expr_error"))
        except EngineError as e:
            return self._fail(run, e)

        run.token = next_id
        return run.state

    def run_until_blocked(self, run: Run, *, max_steps: int = MAX_STEPS) -> State:
        """멈출 때까지 (끝·실패·기다림) 돈다."""
        for _ in range(max_steps):
            if run.finished or run.state is State.WAITING:
                return run.state
            self.step(run)
        return self._fail(
            run, EngineError(f"노드를 {max_steps}번 밟았는데 끝나지 않았다 (돌고 도는 그림?)", code="too_many_steps")
        )

    def _next(self, run: Run, node: Node) -> str:
        """다음 노드. 갈림길(배타 게이트웨이)은 조건식으로 고른다."""
        flows = run.outgoing(node.id)
        if not flows:
            raise EngineError("나가는 흐름이 없다 (종료 이벤트로 끝내야 한다)", node_id=node.id, code="no_outgoing")

        if node.kind == "exclusiveGateway":
            return self._choose(run, node, flows)
        if len(flows) > 1:
            raise EngineError(
                f"나가는 흐름이 {len(flows)}개다 — 병렬·포함 게이트웨이는 아직 다루지 않는다",
                node_id=node.id,
                code="many_outgoing",
            )
        return flows[0].target

    def _choose(self, run: Run, node: Node, flows: list[Flow]) -> str:
        """배타 게이트웨이 — **적힌 순서대로** 보고 처음 참인 길로 간다 (B3가 짝을 검사한다)."""
        default: Flow | None = None
        for flow in flows:
            if flow.is_default or not flow.condition:
                default = default or flow
                continue
            if truthy(flow.condition, run.scope(node.id)):
                run.log.emit("log", node_id=node.id, level="info", message=f"조건 참: {flow.condition}")
                return flow.target
        if default is not None:
            run.log.emit("log", node_id=node.id, level="info", message="조건이 모두 거짓 — 기본 흐름")
            return default.target
        raise EngineError(
            "조건이 모두 거짓이고 기본 흐름도 없다", node_id=node.id, code="no_matching_flow"
        )

    # ── 끝 ──

    def _finish(self, run: Run, status: str, *, error: EngineError | None = None) -> State:
        duration = max(0.0, (_utc_now() - run.started).total_seconds())
        run.log.emit(
            "run_finished",
            status=status,
            duration_s=round(duration, 3),
            **summarize(run.log.events),
            **({"error_code": error.code, "error_message": str(error)} if error else {}),
        )
        run.state = State.DONE if status == "success" else State.FAILED
        run.token = None
        return run.state

    def _fail(self, run: Run, error: EngineError) -> State:
        run.error = error
        if error.node_id:
            run.log.emit(
                "node_state",
                node_id=error.node_id,
                state="failed",
                task_type=_task_type(run.node(error.node_id)) if _has(run, error.node_id) else None,
                error_code=error.code,
                message=str(error),
            )
        log.warning("실행 %s 실패: %s", run.run_id, error)
        return self._finish(run, "failed", error=error)

    # ── 사람 (결재·확인) ──

    def answer(self, run: Run, request_id: str, answer: Mapping[str, Any], *, answered_by: str) -> State:
        """결재·확인의 답을 받아 이어 간다 (C6).

        답의 칸은 **변수로 들어간다** (폼이 없으면 `decision` 하나). 답 **값은 기록에 남기지
        않는다** (C3 `human_answered`는 값이 없다).
        """
        pending = run.pending
        if pending is None or pending.request_id != request_id:
            raise EngineError(
                f"기다리는 요청이 아니다: {request_id} (기다리는 것: {pending.request_id if pending else '없음'})",
                code="not_waiting",
            )
        missing = _missing_fields(pending.form, answer)
        if missing:
            raise EngineError(
                f"답에 빠진 칸이 있다: {', '.join(missing)}",
                node_id=pending.node_id,
                code="answer_incomplete",
            )

        run.variables.update(dict(answer))
        run.log.emit("human_answered", node_id=pending.node_id, request_id=request_id, answered_by=answered_by)
        run.log.emit("node_state", node_id=pending.node_id, state="completed", task_type=pending.layer)

        node = run.node(pending.node_id)
        run.pending = None
        run.state = State.RUNNING
        try:
            run.token = self._next(run, node)
        except EngineError as e:
            return self._fail(run, e)
        return run.state

    def timeout(self, run: Run, request_id: str) -> State:
        """시간 초과 (C3 `human_timeout`). 실행은 실패로 끝낸다 — 되돌릴 길은 M5다."""
        if run.pending is None or run.pending.request_id != request_id:
            raise EngineError(f"기다리는 요청이 아니다: {request_id}", code="not_waiting")
        node_id = run.pending.node_id
        run.log.emit("human_timeout", node_id=node_id, request_id=request_id)
        run.pending = None
        return self._fail(run, EngineError("결재 시간이 지났다", node_id=node_id, code="human_timeout"))


# ─────────────────────────── 노드 수행기 ───────────────────────────


def _has(run: Run, node_id: str) -> bool:
    return any(n.id == node_id for n in run.process.all_nodes())


def _task_type(node: Node) -> str | None:
    """C3 `node_state.task_type`."""
    return {
        "serviceTask": "service_task",
        "userTask": "approval",
        "manualTask": "confirmation",
        "scriptTask": "script",
        "businessRuleTask": "rule",
        "callActivity": "call",
        "sendTask": "send",
        "receiveTask": "receive",
    }.get(node.kind)


def _missing_fields(form: Form | None, answer: Mapping[str, Any]) -> list[str]:
    """필수 칸이 답에 있나. 폼이 없으면 `decision` 하나를 본다 (C6)."""
    if form is None or not form.fields:
        return [] if DECISION_KEY in answer else [DECISION_KEY]
    return [f.key for f in form.fields if f.required and f.key not in answer]


def handle_pass(run: Run, node: Node) -> bool:
    """할 일이 없는 노드 (시작·종료). 토큰만 지나간다."""
    return True


def handle_script(run: Run, node: Node) -> bool:
    """`scriptTask` — 대입문을 돌려 변수를 바꾼다 (ADR-0025)."""
    if not node.script:
        raise EngineError("스크립트가 비어 있다", node_id=node.id, code="script_empty")
    changed = run_script(node.script, run.scope(node.id))
    # **이름만** 남긴다 (값은 계약 원칙 6).
    run.log.emit("log", node_id=node.id, level="info", message=f"변수 {len(changed)}개를 정했다")
    return True


def handle_gateway(run: Run, node: Node) -> bool:
    """`exclusiveGateway` — 고르기는 `_next()`가 한다 (여기서는 할 일이 없다)."""
    return True


def handle_approval(run: Run, node: Node) -> bool:
    """`userTask`(결재)·`manualTask`(확인) — 요청을 올리고 **기다린다**.

    PC Bot은 기다리는 동안에도 실행 자리를 쥔다 (ADR-0014). 어디서 답하는지(`where`)는
    BPM 프로세스의 `location`과 Bot UI 설정이 함께 정하는데, 설정을 보는 것은 조각 3이다 —
    지금은 현장(`field`)으로 둔다.
    """
    approval = node.prop("approval")
    if approval is None:
        raise EngineError("`chk:approval`이 없다", node_id=node.id, code="approval_missing")

    instance = run.instances.get(node.id, 1)
    request_id = request_id_for(run.run_id, node.id, instance)
    layer = "approval" if node.kind == "userTask" else "confirmation"
    form = Form(fields=list(approval.fields)) if approval.fields else None

    # 「표시 변수」만 담는다 (C6 `review` — 결재자가 판단할 값, 원칙 6의 예외).
    review = {name: run.variables.get(name) for name in approval.show}

    run.pending = Pending(
        request_id=request_id,
        node_id=node.id,
        layer=layer,
        title=fill(approval.title, run.scope(node.id)) if "{" in approval.title else approval.title,
        form=form,
        review=review,
        node_instance=instance,
    )
    run.log.emit(
        "human_requested",
        node_id=node.id,
        layer=layer,
        request_id=request_id,
        where=run.pending.where,
        **({"form_key": ",".join(f.key for f in form.fields)} if form else {}),
    )
    return False  # 기다린다


#: 기본 수행기. 조각 3에서 AI·서비스 앱·DMN·반복·타이머·메시지가 더해진다.
DEFAULT_HANDLERS: dict[str, Handler] = {
    "startEvent": handle_pass,
    "endEvent": handle_pass,
    "scriptTask": handle_script,
    "exclusiveGateway": handle_gateway,
    "userTask": handle_approval,
    "manualTask": handle_approval,
}


def new_run_id(*, now: datetime | None = None, test: bool = False) -> str:
    """C3 `run_id` — `run_<YYYYMMDD>_<HHMMSS>_<hex6>` (시험 실행은 `test_`)."""
    import secrets  # noqa: PLC0415

    at = (now or _utc_now()).strftime("%Y%m%d_%H%M%S")
    return f"{'test' if test else 'run'}_{at}_{secrets.token_hex(3)}"


__all__ = [
    "DECISION_KEY",
    "DEFAULT_HANDLERS",
    "MAX_STEPS",
    "Engine",
    "EngineError",
    "Form",
    "FormField",
    "Handler",
    "Pending",
    "Run",
    "State",
    "evaluate",
    "new_run_id",
]

"""BPMN 실행 (M3 조각 2~3).

**토큰이 여러 개일 수 있다.** 병렬·포함 게이트웨이가 갈라고 합치며, 하위 프로세스는 안쪽에
토큰을 하나 만들어 끝날 때까지 바깥 토큰을 세워 둔다. 반복(다중 인스턴스)은 한 노드를 여러 번
밟는다. PC에서는 실행 자리가 하나라 **한 번에 토큰 하나씩** 번갈아 밟는다 (ADR-0014·C14 §반복).

사람을 기다리면 그 토큰만 멈춘다 (`State.WAITING`). 엔진은 스레드를 만들지 않는다 — 부르는
쪽(Bot UI·Studio)이 `step()`을 돈다.

노드 종류를 더하는 자리는 `Engine.handlers`다. 수행기는 `Context`를 받아 **다음에 무엇을 할지**를
돌려준다 (`Go`·`Wait`·`Consume`). **모르는 노드는 조용히 지나가지 않고 실행을 실패로 끝낸다.**

기록은 C3 그대로 남긴다 (`run_log.RunLog`). 업무 값은 담지 않는다 (계약 원칙 6).
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable, Iterable, Mapping
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

#: 오류 경계가 만드는 변수 (C14 §이벤트).
ERROR_CODE_VAR = "error_code"
ERROR_MESSAGE_VAR = "error_message"
FAILED_TASK_VAR = "failed_task"

#: 표준 오류 코드 (C14 §이벤트).
ERROR_TASK_FAILED = "TASK_FAILED"
ERROR_SEND_FAILED = "SEND_FAILED"


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


class TaskFailed(EngineError):
    """태스크가 실패했다 — **오류 경계로 받을 수 있는** 실패 (C14 `TASK_FAILED`).

    그림이 잘못된 것(식 오류·흐름 없음)은 경계로 받지 않는다. 그것은 고쳐야 할 버그다.
    """

    def __init__(self, message: str, *, node_id: str, code: str = ERROR_TASK_FAILED) -> None:
        super().__init__(message, node_id=node_id, code=code)


# ─────────────────────────── 토큰·상태 ───────────────────────────


@dataclass
class LoopState:
    """반복(다중 인스턴스) 한 묶음 (C14 §반복)."""

    items: list[Any]
    item_name: str
    result_name: str | None
    collect_into: str
    index: int = 0
    results: list[Any] = field(default_factory=list)
    sequential: bool = True

    @property
    def finished(self) -> bool:
        return self.index >= len(self.items)


@dataclass
class Token:
    """실행 중인 자리 하나."""

    id: str
    node_id: str
    #: 하위 프로세스 안이면 그 노드 id들 (범위 경로). 비면 맨 바깥이다.
    scope: tuple[str, ...] = ()
    #: 기다리는 것의 열쇠 (결재 `request_id`, 하위 프로세스 `sub:<노드>`).
    waiting_for: str | None = None
    loop: LoopState | None = None

    @property
    def waiting(self) -> bool:
        return self.waiting_for is not None


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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_token_id() -> str:
    return f"t_{secrets.token_hex(3)}"


@dataclass
class Run:
    """실행 하나. 토큰·변수·기록을 들고 있다."""

    run_id: str
    process: BpmnProcess
    log: RunLog
    variables: dict[str, Any] = field(default_factory=dict)
    state: State = State.READY
    tokens: list[Token] = field(default_factory=list)
    #: 기다리는 사람 요청 (`request_id` → 요청). 병렬 가지면 여럿일 수 있다.
    pendings: dict[str, Pending] = field(default_factory=dict)
    #: 합류 게이트웨이에 도착한 토큰 (`범위:노드` → 토큰 id 묶음).
    arrivals: dict[str, set[str]] = field(default_factory=dict)
    #: 포함 분기가 실제로 띄운 가지 수 (`범위:합류` → 수). 포함 합류가 이만큼 기다린다.
    expected: dict[str, int] = field(default_factory=dict)
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

    def scope(self, node_id: str | None = None, **extra: Any) -> Scope:
        """식이 볼 것. **변수를 그대로 넘긴다** — 스크립트가 여기에 대입한다.

        반복의 `item`처럼 그 노드에서만 보이는 이름은 `extra`로 얹는다.
        """
        found = Scope(variables=self.variables, helpers=self.helpers, where=node_id)
        return found.child(**extra) if extra else found

    def flows(self, scope: tuple[str, ...] = ()) -> list[Flow]:
        """그 범위의 흐름 (맨 바깥이면 프로세스의 흐름, 안쪽이면 그 하위 프로세스의 흐름)."""
        if not scope:
            return list(self.process.flows)
        return list(self.node(scope[-1]).child_flows)

    def outgoing(self, node_id: str, scope: tuple[str, ...] = ()) -> list[Flow]:
        return [f for f in self.flows(scope) if f.source == node_id]

    def incoming(self, node_id: str, scope: tuple[str, ...] = ()) -> list[Flow]:
        return [f for f in self.flows(scope) if f.target == node_id]

    def boundaries(self, node_id: str) -> list[Node]:
        """그 노드에 붙은 경계 이벤트."""
        return [n for n in self.process.all_nodes() if n.attached_to == node_id]

    @property
    def pending(self) -> Pending | None:
        """기다리는 요청 하나 (대개 하나다 — 병렬 가지면 `pendings`를 본다)."""
        return next(iter(self.pendings.values()), None)

    @property
    def finished(self) -> bool:
        return self.state in (State.DONE, State.FAILED)

    def runnable(self) -> Token | None:
        return next((t for t in self.tokens if not t.waiting), None)


# ─────────────────────────── 수행기가 돌려주는 것 ───────────────────────────


@dataclass
class Go:
    """다음으로 간다. `targets`가 비면 **나가는 흐름**을 따른다 (여럿이면 갈라진다)."""

    targets: list[str] | None = None


@dataclass
class Wait:
    """이 토큰은 멈춘다. `key`로 무엇을 기다리는지 가린다 (결재 `request_id` 등)."""

    key: str


@dataclass
class Consume:
    """이 토큰은 여기서 사라진다 (합류가 아직 안 찼거나, 끝났다)."""


Outcome = Go | Wait | Consume


@dataclass
class Context:
    """수행기가 받는 것 — 실행·토큰·노드."""

    engine: Engine
    run: Run
    token: Token
    node: Node

    @property
    def node_id(self) -> str:
        return self.node.id

    def scope(self) -> Scope:
        """식이 볼 것.

        반복의 `item`은 **프로세스 변수로 넣어 둔다** (`_prepare_iteration`) — 자식 스코프에
        넣으면 스크립트의 대입이 사본으로 들어가 사라진다.
        """
        return self.run.scope(self.node.id)

    def emit(self, kind: str, **data: Any) -> None:
        self.run.log.emit(kind, node_id=self.node.id, **data)

    def instance(self) -> int:
        return self.run.instances.get(self.node.id, 1)


Handler = Callable[[Context], Outcome]


# ─────────────────────────── 엔진 ───────────────────────────


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
        run = Run(run_id=run_id, process=process, log=log, mode=mode, started=at, helpers=bind(now=at))
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
        run.tokens = [Token(id=_new_token_id(), node_id=self._start_node(process))]
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
            elif decl.required:
                raise EngineError(f"입력 「{decl.name}」이 필요하다", code="input_required")
            else:
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
            # 여러 시작(메시지·타이머)은 뒤 조각이다 — 지금은 어느 것인지 고를 수 없다.
            raise EngineError(
                f"시작 이벤트가 {len(starts)}개다 — 메시지·타이머 시작은 아직 다루지 않는다",
                code="many_starts",
            )
        return starts[0].id

    # ── 한 걸음 ──

    def step(self, run: Run) -> State:
        """토큰 하나를 한 노드만큼 밟는다."""
        if run.finished:
            return run.state
        token = run.runnable()
        if token is None:
            # 밟을 토큰이 없다 — 기다리는 것이 있으면 기다리고, 없으면 끝났다.
            if any(t.waiting for t in run.tokens):
                run.state = State.WAITING
                return run.state
            return self._finish(run, "success")

        run.state = State.RUNNING
        node = run.node(token.node_id)
        handler = self.handlers.get(node.kind)
        if handler is None:
            return self._fail(
                run,
                EngineError(
                    f"아직 다루지 않는 노드다: {node.kind} (뒤 조각에서 더한다)",
                    node_id=node.id,
                    code="node_kind_unsupported",
                ),
            )

        context = Context(engine=self, run=run, token=token, node=node)
        try:
            self._prepare_loop(context)
            if token.loop is not None and token.loop.finished:
                # 반복할 것이 없다 — 수행기를 부르지 않고 지나간다 (C3 `skipped`).
                run.log.emit("node_state", node_id=node.id, state="skipped", task_type=_task_type(node))
                run.variables[token.loop.collect_into] = []
                token.loop = None
                return self._move(context, None)

            self._prepare_iteration(context)
            if token.loop is None or token.loop.index == 0:
                run.instances[node.id] = run.instances.get(node.id, 0) + 1
                run.log.emit("node_state", node_id=node.id, state="started", task_type=_task_type(node))
            outcome = handler(context)
            return self._apply(context, outcome)
        except ExprError as e:
            return self._handle_failure(context, EngineError(e.reason, node_id=node.id, code="expr_error"))
        except EngineError as e:
            return self._handle_failure(context, e)

    def run_until_blocked(self, run: Run, *, max_steps: int = MAX_STEPS) -> State:
        """멈출 때까지 (끝·실패·기다림) 돈다."""
        for _ in range(max_steps):
            if run.finished:
                return run.state
            if run.runnable() is None and any(t.waiting for t in run.tokens):
                run.state = State.WAITING
                return run.state
            self.step(run)
        return self._fail(
            run, EngineError(f"노드를 {max_steps}번 밟았는데 끝나지 않았다 (돌고 도는 그림?)", code="too_many_steps")
        )

    # ── 결과 적용 ──

    def _apply(self, context: Context, outcome: Outcome) -> State:
        run, token, node = context.run, context.token, context.node

        if isinstance(outcome, Wait):
            run.log.emit("node_state", node_id=node.id, state="waiting", task_type=_task_type(node))
            token.waiting_for = outcome.key
            run.state = State.WAITING
            return run.state

        if isinstance(outcome, Consume):
            run.tokens.remove(token)
            return self._settle(run)

        # 반복이 남았으면 같은 노드를 다시 밟는다 (PC는 차례로, C14 §반복).
        loop = token.loop
        if loop is not None:
            self._collect_iteration(context, loop)
            if not loop.finished:
                return run.state  # 다음 `step()`이 같은 노드를 또 밟는다
            run.variables[loop.collect_into] = list(loop.results)
            run.variables.pop(loop.item_name, None)  # 반복 안에서만 보이는 이름이다
            token.loop = None

        run.log.emit("node_state", node_id=node.id, state="completed", task_type=_task_type(node))
        return self._move(context, outcome.targets)

    def _move(self, context: Context, targets: list[str] | None) -> State:
        """토큰을 다음 자리로 옮긴다. `targets`가 비면 나가는 흐름을 따르고, 없으면 끝난다."""
        run, token, node = context.run, context.token, context.node
        if targets is None:
            targets = self._default_targets(run, token, node)
        if not targets:
            run.tokens.remove(token)  # 끝났다 (종료 이벤트·갈 곳 없음)
            return self._settle(run)

        token.node_id = targets[0]
        for extra in targets[1:]:
            run.tokens.append(Token(id=_new_token_id(), node_id=extra, scope=token.scope))
        return run.state

    def pass_through(self, run: Run, token: Token) -> None:
        """그 토큰을 **지금 노드를 지나** 다음으로 옮긴다 (하위 프로세스가 끝났을 때).

        다시 밟으면 하위 프로세스에 끝없이 들어간다.
        """
        node = run.node(token.node_id)
        run.log.emit("node_state", node_id=node.id, state="completed", task_type=_task_type(node))
        self._move(Context(engine=self, run=run, token=token, node=node), None)

    def _settle(self, run: Run) -> State:
        """토큰이 사라진 뒤 — 아무 토큰도 없으면 실행이 끝났다."""
        if run.tokens:
            return run.state
        return self._finish(run, "success")

    def _default_targets(self, run: Run, token: Token, node: Node) -> list[str]:
        """나가는 흐름을 그대로 따른다. 여럿이면 갈라진다 (병렬 분기)."""
        flows = run.outgoing(node.id, token.scope)
        if not flows:
            raise EngineError(
                "나가는 흐름이 없다 (종료 이벤트로 끝내야 한다)", node_id=node.id, code="no_outgoing"
            )
        return [f.target for f in flows]

    # ── 반복 (다중 인스턴스) ──

    def _prepare_loop(self, context: Context) -> None:
        """반복을 처음 만나면 목록을 펼쳐 둔다 (C14 §반복)."""
        token, node, run = context.token, context.node, context.run
        if token.loop is not None:
            return
        spec = node.prop("loop")
        if spec is None:
            return
        if not spec.collect_into:
            # B4가 미리 잡지만 엔진도 그냥 돌지 않는다 (프로토타입은 여기서 멈췄다).
            raise EngineError("반복에 `collect_into`가 없다", node_id=node.id, code="loop_no_collect")

        items = evaluate(spec.collection, run.scope(node.id))
        if isinstance(items, str | bytes) or not isinstance(items, Iterable):
            raise EngineError(
                f"반복할 목록이 아니다: {type(items).__name__}", node_id=node.id, code="loop_not_a_list"
            )
        token.loop = LoopState(
            items=list(items),
            item_name=spec.item,
            result_name=spec.result,
            collect_into=spec.collect_into,
            sequential=node.is_sequential is not False,
        )
        # 병렬로 적혀 있어도 PC에서는 차례로 돈다 (C14 §반복).
        context.emit("log", level="info", message=f"반복 {len(token.loop.items)}건 (차례로)")

    def _prepare_iteration(self, context: Context) -> None:
        """이번 번째의 `item`을 변수로 올려 둔다 (C14 §반복)."""
        loop = context.token.loop
        if loop is not None and not loop.finished:
            context.run.variables[loop.item_name] = loop.items[loop.index]

    def _collect_iteration(self, context: Context, loop: LoopState) -> None:
        """한 번 돈 결과를 모은다 (`result` 변수 → `collect_into`, 순서는 입력 순서)."""
        if loop.finished:
            return
        if loop.result_name:
            loop.results.append(context.run.variables.get(loop.result_name))
        loop.index += 1

    # ── 실패·오류 경계 ──

    def _handle_failure(self, context: Context, error: EngineError) -> State:
        """오류 경계가 붙어 있으면 그 길로 보내고, 없으면 실행을 실패로 끝낸다 (C14 §이벤트)."""
        run, token, node = context.run, context.token, context.node
        boundary = self._error_boundary(run, node, error)
        if boundary is None:
            return self._fail(run, error)

        run.log.emit(
            "node_state",
            node_id=node.id,
            state="failed",
            task_type=_task_type(node),
            error_code=error.code,
            message=str(error),
        )
        # 오류 경로에 생기는 변수 (C14).
        run.variables[ERROR_CODE_VAR] = error.code
        run.variables[ERROR_MESSAGE_VAR] = str(error)
        run.variables[FAILED_TASK_VAR] = node.id
        context.emit("log", level="warn", message=f"오류 경계로 간다: {boundary.id}")

        token.loop = None
        flows = run.outgoing(boundary.id, token.scope)
        if not flows:
            return self._fail(
                run, EngineError("오류 경계에 나가는 흐름이 없다", node_id=boundary.id, code="no_outgoing")
            )
        token.node_id = flows[0].target
        for extra in flows[1:]:
            run.tokens.append(Token(id=_new_token_id(), node_id=extra.target, scope=token.scope))
        return run.state

    def _error_boundary(self, run: Run, node: Node, error: EngineError) -> Node | None:
        """그 실패를 받을 오류 경계. 코드가 맞는 것이 먼저, 없으면 코드를 적지 않은 것."""
        if not isinstance(error, TaskFailed):
            return None  # 식 오류·구조 오류는 경계로 받지 않는다 (그림이 잘못된 것이다)
        catches = [b for b in run.boundaries(node.id) if "errorEventDefinition" in b.event_definitions]
        if not catches:
            return None
        named = next((b for b in catches if run.process.errors.get(error.code) == b.error_ref), None)
        return named or next((b for b in catches if b.error_ref is None), None)

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
        run.tokens = []
        return run.state

    def _fail(self, run: Run, error: EngineError) -> State:
        run.error = error
        if error.node_id and any(n.id == error.node_id for n in run.process.all_nodes()):
            run.log.emit(
                "node_state",
                node_id=error.node_id,
                state="failed",
                task_type=_task_type(run.node(error.node_id)),
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
        pending = run.pendings.get(request_id)
        token = next((t for t in run.tokens if t.waiting_for == request_id), None)
        if pending is None or token is None:
            waiting = ", ".join(run.pendings) or "없음"
            raise EngineError(
                f"기다리는 요청이 아니다: {request_id} (기다리는 것: {waiting})", code="not_waiting"
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
        del run.pendings[request_id]
        token.waiting_for = None

        node = run.node(pending.node_id)
        context = Context(engine=self, run=run, token=token, node=node)
        try:
            return self._apply(context, Go())
        except EngineError as e:
            return self._fail(run, e)

    def timeout(self, run: Run, request_id: str) -> State:
        """시간 초과 (C3 `human_timeout`). 실행은 실패로 끝낸다 — 되돌릴 길은 M5다."""
        pending = run.pendings.get(request_id)
        if pending is None:
            raise EngineError(f"기다리는 요청이 아니다: {request_id}", code="not_waiting")
        run.log.emit("human_timeout", node_id=pending.node_id, request_id=request_id)
        del run.pendings[request_id]
        return self._fail(run, EngineError("결재 시간이 지났다", node_id=pending.node_id, code="human_timeout"))


# ─────────────────────────── 노드 수행기 ───────────────────────────


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
        "subProcess": "subprocess",
    }.get(node.kind)


def _missing_fields(form: Form | None, answer: Mapping[str, Any]) -> list[str]:
    """필수 칸이 답에 있나. 폼이 없으면 `decision` 하나를 본다 (C6)."""
    if form is None or not form.fields:
        return [] if DECISION_KEY in answer else [DECISION_KEY]
    return [f.key for f in form.fields if f.required and f.key not in answer]


def _join_key(token: Token, node: Node) -> str:
    return f"{'/'.join(token.scope)}:{node.id}"


def handle_pass(context: Context) -> Outcome:
    """할 일이 없는 노드 (시작). 토큰만 지나간다."""
    return Go()


def handle_end(context: Context) -> Outcome:
    """종료 이벤트. 하위 프로세스 안이면 **바깥 토큰을 깨워 그 노드를 지나게 한다.**"""
    token, run = context.token, context.run
    if token.scope:
        parent_id = token.scope[-1]
        key = f"sub:{parent_id}"
        parent = next((t for t in run.tokens if t.waiting_for == key), None)
        if parent is not None:
            parent.waiting_for = None
            context.engine.pass_through(run, parent)
    return Consume()


def handle_script(context: Context) -> Outcome:
    """`scriptTask` — 대입문을 돌려 변수를 바꾼다 (ADR-0025)."""
    node = context.node
    if not node.script:
        raise EngineError("스크립트가 비어 있다", node_id=node.id, code="script_empty")
    changed = run_script(node.script, context.scope())
    # **이름만** 남긴다 (값은 계약 원칙 6).
    context.emit("log", level="info", message=f"변수 {len(changed)}개를 정했다")
    return Go()


def handle_exclusive(context: Context) -> Outcome:
    """배타 게이트웨이 — **적힌 순서대로** 보고 처음 참인 길 하나로 간다 (B3가 짝을 검사한다)."""
    run, token, node = context.run, context.token, context.node
    flows = run.outgoing(node.id, token.scope)
    if not flows:
        return Go([])

    default: Flow | None = None
    for flow in flows:
        if flow.is_default or not flow.condition:
            default = default or flow
            continue
        if truthy(flow.condition, context.scope()):
            context.emit("log", level="info", message=f"조건 참: {flow.condition}")
            return Go([flow.target])
    if default is not None:
        context.emit("log", level="info", message="조건이 모두 거짓 — 기본 흐름")
        return Go([default.target])
    raise EngineError("조건이 모두 거짓이고 기본 흐름도 없다", node_id=node.id, code="no_matching_flow")


def handle_parallel(context: Context) -> Outcome:
    """병렬 게이트웨이 — 들어오는 흐름이 여럿이면 **모두 올 때까지 기다린다** (합류)."""
    run, token, node = context.run, context.token, context.node
    incoming = run.incoming(node.id, token.scope)
    if len(incoming) > 1:
        key = _join_key(token, node)
        arrived = run.arrivals.setdefault(key, set())
        arrived.add(token.id)
        if len(arrived) < len(incoming):
            context.emit("log", level="info", message=f"합류 {len(arrived)}/{len(incoming)}")
            return Consume()
        run.arrivals.pop(key, None)
        context.emit("log", level="info", message="합류 완료")
    return Go()  # 나가는 흐름이 여럿이면 `_apply`가 갈라 준다


def handle_inclusive(context: Context) -> Outcome:
    """포함 게이트웨이 — 참인 길 **모두**로 갈라지고, 합류는 **갈라진 수만큼** 기다린다.

    「포함 분기는 포함 합류로 닫는다」(B3)를 믿는다. 몇 갈래가 올지 분기에서 적어 두지 않으면
    합류가 영원히 기다린다.
    """
    run, token, node = context.run, context.token, context.node
    incoming = run.incoming(node.id, token.scope)

    if len(incoming) > 1:  # 합류
        key = _join_key(token, node)
        arrived = run.arrivals.setdefault(key, set())
        arrived.add(token.id)
        wanted = run.expected.get(key, len(incoming))
        if len(arrived) < wanted:
            context.emit("log", level="info", message=f"합류 {len(arrived)}/{wanted}")
            return Consume()
        run.arrivals.pop(key, None)
        run.expected.pop(key, None)
        context.emit("log", level="info", message="합류 완료")
        return Go()

    chosen: list[str] = []
    default: Flow | None = None
    for flow in run.outgoing(node.id, token.scope):
        if flow.is_default or not flow.condition:
            default = default or flow
            continue
        if truthy(flow.condition, context.scope()):
            chosen.append(flow.target)
    if not chosen and default is not None:
        chosen = [default.target]
    if not chosen:
        raise EngineError("참인 길이 없고 기본 흐름도 없다", node_id=node.id, code="no_matching_flow")

    join = _matching_inclusive_join(context)
    if join is not None:
        run.expected[f"{'/'.join(token.scope)}:{join}"] = len(chosen)
    context.emit("log", level="info", message=f"{len(chosen)}갈래로 갈라진다")
    return Go(chosen)


def _matching_inclusive_join(context: Context) -> str | None:
    """분기에서 앞으로 나아가며 처음 만나는 포함 합류 (같은 범위 안)."""
    run, token, node = context.run, context.token, context.node
    seen: set[str] = set()
    frontier = [f.target for f in run.outgoing(node.id, token.scope)]
    while frontier:
        current = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        found = run.node(current)
        if found.kind == "inclusiveGateway" and len(run.incoming(current, token.scope)) > 1:
            return current
        frontier.extend(f.target for f in run.outgoing(current, token.scope))
    return None


def handle_subprocess(context: Context) -> Outcome:
    """하위 프로세스 — 안쪽에 토큰을 만들고 **바깥 토큰은 세워 둔다** (범위가 따로다)."""
    run, token, node = context.run, context.token, context.node
    starts = [n for n in node.children if n.kind == "startEvent"]
    if not starts:
        raise EngineError("하위 프로세스에 시작 이벤트가 없다", node_id=node.id, code="no_start")
    if len(starts) > 1:
        raise EngineError(
            f"하위 프로세스의 시작 이벤트가 {len(starts)}개다", node_id=node.id, code="many_starts"
        )
    run.tokens.append(Token(id=_new_token_id(), node_id=starts[0].id, scope=(*token.scope, node.id)))
    return Wait(key=f"sub:{node.id}")


def handle_approval(context: Context) -> Outcome:
    """`userTask`(결재)·`manualTask`(확인) — 요청을 올리고 **기다린다**.

    PC Bot은 기다리는 동안에도 실행 자리를 쥔다 (ADR-0014). 어디서 답하는지(`where`)는
    BPM 프로세스의 `location`과 Bot UI 설정이 함께 정하는데, 설정을 보는 것은 뒤 조각이다 —
    지금은 현장(`field`)으로 둔다.
    """
    run, node = context.run, context.node
    approval = node.prop("approval")
    if approval is None:
        raise EngineError("`chk:approval`이 없다", node_id=node.id, code="approval_missing")

    instance = context.instance()
    request_id = request_id_for(run.run_id, node.id, instance)
    layer = "approval" if node.kind == "userTask" else "confirmation"
    form = Form(fields=list(approval.fields)) if approval.fields else None
    # 「표시 변수」만 담는다 (C6 `review` — 결재자가 판단할 값, 원칙 6의 예외).
    review = {name: run.variables.get(name) for name in approval.show}

    run.pendings[request_id] = Pending(
        request_id=request_id,
        node_id=node.id,
        layer=layer,
        title=fill(approval.title, context.scope()) if "{" in approval.title else approval.title,
        form=form,
        review=review,
        node_instance=instance,
    )
    context.emit(
        "human_requested",
        layer=layer,
        request_id=request_id,
        where="field",
        **({"form_key": ",".join(f.key for f in form.fields)} if form else {}),
    )
    return Wait(key=request_id)


#: 기본 수행기. 뒤 조각에서 AI·서비스 앱·DMN·타이머·메시지가 더해진다.
DEFAULT_HANDLERS: dict[str, Handler] = {
    "startEvent": handle_pass,
    "endEvent": handle_end,
    "scriptTask": handle_script,
    "exclusiveGateway": handle_exclusive,
    "parallelGateway": handle_parallel,
    "inclusiveGateway": handle_inclusive,
    "subProcess": handle_subprocess,
    "userTask": handle_approval,
    "manualTask": handle_approval,
}


def new_run_id(*, now: datetime | None = None, test: bool = False) -> str:
    """C3 `run_id` — `run_<YYYYMMDD>_<HHMMSS>_<hex6>` (시험 실행은 `test_`)."""
    at = (now or _utc_now()).strftime("%Y%m%d_%H%M%S")
    return f"{'test' if test else 'run'}_{at}_{secrets.token_hex(3)}"


__all__ = [
    "DECISION_KEY",
    "DEFAULT_HANDLERS",
    "ERROR_CODE_VAR",
    "ERROR_MESSAGE_VAR",
    "ERROR_SEND_FAILED",
    "ERROR_TASK_FAILED",
    "FAILED_TASK_VAR",
    "MAX_STEPS",
    "Consume",
    "Context",
    "Engine",
    "EngineError",
    "Form",
    "FormField",
    "Go",
    "Handler",
    "LoopState",
    "Outcome",
    "Pending",
    "Run",
    "State",
    "TaskFailed",
    "Token",
    "Wait",
    "evaluate",
    "new_run_id",
]

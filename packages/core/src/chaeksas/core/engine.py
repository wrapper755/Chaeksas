"""BPMN 실행 — 엔진 (M3 조각 2~3b).

**토큰이 여러 개일 수 있다.** 병렬·포함 게이트웨이가 갈라고 합치며, 하위 프로세스는 안쪽에
토큰을 하나 만들어 끝날 때까지 바깥 토큰을 세워 둔다. 반복(다중 인스턴스)은 한 노드를 여러 번
밟는다. PC에서는 실행 자리가 하나라 **한 번에 토큰 하나씩** 번갈아 밟는다 (ADR-0014·C14 §반복).

사람을 기다리면 그 토큰만 멈춘다 (`State.WAITING`). 엔진은 스레드를 만들지 않는다 — 부르는
쪽(Bot UI·Studio)이 `step()`을 돈다.

세 모듈로 나뉘어 있고, **쓰는 쪽은 여기 하나만 보면 된다** (나머지를 다시 내보낸다).

| 모듈 | 무엇 |
| --- | --- |
| `core.run_state` | 상태와 수행기 규약 (`Run`·`Token`·`RunEnv`·`Context`·`Go`/`Wait`/`Consume`) |
| `core.nodes` | 노드마다 무엇을 하는지 (`DEFAULT_HANDLERS`) |
| `core.engine` | 한 걸음씩 돌리는 것 — 토큰 옮기기·반복·오류 경계·끝내기 |

노드 종류를 더하는 자리는 `core.nodes`이고, 엔진은 `Engine(handlers=…)`로 바꿔 끼울 수 있다.
**모르는 노드는 조용히 지나가지 않고 실행을 실패로 끝낸다.**

기록은 C3 그대로 남긴다 (`run_log.RunLog`). 업무 값은 담지 않는다 (계약 원칙 6).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from chaeksas.contracts.approvals import Form, FormField
from chaeksas.contracts.bpmn_ext import BpmnProcess, DataOutput, Node, duration_hours
from chaeksas.core.expr import ExprError, evaluate
from chaeksas.core.files import FileTaskError, PathDenied, Workspace, write_output
from chaeksas.core.helpers import bind
from chaeksas.core.nodes import DEFAULT_HANDLERS
from chaeksas.core.run_log import RunLog, summarize
from chaeksas.core.run_state import (
    BUILTIN_NOW,
    BUILTIN_RUN_ID,
    BUILTIN_TODAY,
    CODE_PATH_DENIED,
    CODE_UNSUPPORTED,
    DECISION_KEY,
    ERROR_APPROVAL_EXPIRED,
    ERROR_APPROVAL_WITHDRAWN,
    ERROR_CODE_VAR,
    ERROR_MESSAGE_VAR,
    ERROR_SEND_FAILED,
    ERROR_TASK_FAILED,
    FAILED_TASK_VAR,
    MAX_STEPS,
    WAIT_MESSAGE,
    WAIT_SIGNAL,
    WAIT_TIMER,
    WHERE_CENTER,
    WHERE_FIELD,
    Consume,
    Context,
    EngineError,
    Go,
    Handler,
    LoopState,
    Outcome,
    Pending,
    Run,
    RunEnv,
    State,
    TaskFailed,
    Token,
    Wait,
    Waiting,
    correlation_of,
    event_kind,
    new_run_id,
    new_token_id,
    task_type,
    utc_now,
)

log = logging.getLogger(__name__)


def _as_duration(value: str, *, node_id: str) -> timedelta:
    """ISO 기간(`PT30M`·`P3D`) 또는 **ISO 시각**(케이스의 `$now_plus`가 주는 것)."""
    body = value.strip()
    hours = duration_hours(body)
    if hours is not None:
        return timedelta(hours=hours)
    try:
        at = datetime.fromisoformat(body)
    except ValueError:
        raise EngineError(
            f"타이머를 읽을 수 없다: {body} (ISO 기간 `PT30M`이나 ISO 시각)",
            node_id=node_id,
            code="timer_unreadable",
        ) from None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return max(timedelta(0), at - datetime.now(UTC))


def _missing_fields(form: Form | None, answer: Mapping[str, Any]) -> list[str]:
    """필수 칸이 답에 있나. 폼이 없으면 `decision` 하나를 본다 (C6)."""
    if form is None or not form.fields:
        return [] if DECISION_KEY in answer else [DECISION_KEY]
    return [f.key for f in form.fields if f.required and f.key not in answer]


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
        env: RunEnv | None = None,
        nested: bool = False,
    ) -> Run:
        """실행을 만들고 `run_started`를 남긴다. 토큰은 시작 이벤트에 놓인다.

        `nested`면 호출(`callActivity`)이 띄운 안쪽 실행이다 — 같은 `run_id`를 쓰고
        `run_started`·`run_finished`를 남기지 않는다 (C3는 실행 하나에 하나씩만 둔다).
        """
        at = now or utc_now()
        run = Run(
            run_id=run_id,
            process=process,
            log=log,
            env=env or RunEnv(),
            mode=mode,
            executor=executor,
            version=version,
            started=at,
            nested=nested,
            helpers=bind(now=at),
        )
        run.variables.update(self._seed(process, inputs or {}, run_id=run_id, now=at))

        if nested:
            run.tokens = [Token(id=new_token_id(), node_id=self._start_node(process))]
            run.state = State.RUNNING
            return run

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
        run.tokens = [Token(id=new_token_id(), node_id=self._start_node(process))]
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
            # 호출한 안쪽 실행이 있으면 그것을 먼저 민다 (같은 `run_id`·같은 기록).
            if self._step_children(run):
                return run.state
            # 밟을 토큰이 없다 — 기다리는 것이 있으면 기다리고, 없으면 끝났다.
            if any(t.waiting for t in run.tokens):
                run.state = State.WAITING
                return run.state
            return self._finish(run, "success")
        return self._step_token(run, token)

    def _step_token(self, run: Run, token: Token) -> State:
        run.last_token_id = token.id
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
                run.log.emit("node_state", node_id=node.id, state="skipped", task_type=task_type(node))
                run.variables[token.loop.collect_into] = []
                token.loop = None
                return self._move(context, None)

            self._prepare_iteration(context)
            if token.loop is None or token.loop.index == 0:
                run.instances[node.id] = run.instances.get(node.id, 0) + 1
                run.log.emit("node_state", node_id=node.id, state="started", task_type=task_type(node))
            outcome = handler(context)
            return self._apply(context, outcome)
        except ExprError as e:
            return self._handle_failure(context, EngineError(e.reason, node_id=node.id, code="expr_error"))
        except EngineError as e:
            return self._handle_failure(context, e)

    def blocked(self, run: Run) -> bool:
        """더 밟을 것이 없나 — 토큰도, 호출한 안쪽 실행도.

        `step()`이 아니라 이것이 「멈췄다」의 기준이다. `_apply`는 토큰 하나가 멈출 때마다
        `WAITING`을 쓰므로, 그것만 보면 다른 토큰이 남아 있어도 멈춘 줄 안다.
        """
        if run.finished or run.runnable() is not None:
            return False
        for key, child in run.children.items():
            if not any(t.waiting_for == key for t in run.tokens):
                continue  # 주인 없는 자식 — `_step_children`이 걷는다
            if child.finished or not self.blocked(child):
                return False
        return True

    def _step_children(self, run: Run) -> bool:
        """호출(`callActivity`)이 띄운 안쪽 실행을 한 걸음 민다. 민 것이 있으면 참.

        안쪽이 끝나면 `chk:call.output`대로 값을 올려 보내고 바깥 토큰을 이어 간다.
        안쪽이 실패하면 그 실패를 **호출 노드의 업무 실패**로 올린다 (오류 경계가 받는다).
        """
        for key, child in list(run.children.items()):
            token = next((t for t in run.tokens if t.waiting_for == key), None)
            if token is None:
                del run.children[key]
                continue
            if not child.finished:
                if child.runnable() is None and not child.children:
                    continue  # 안쪽도 사람·메시지를 기다린다 — 바깥이 할 일은 없다
                self.step(child)
                return True

            del run.children[key]
            node = run.node(token.node_id)
            token.waiting_for = None
            self.disarm(run, token.id)
            context = Context(engine=self, run=run, token=token, node=node)
            if child.state is State.FAILED:
                error = child.error or EngineError("호출한 BPM 프로세스가 실패했다", node_id=node.id)
                self._handle_failure(context, TaskFailed(str(error), node_id=node.id))
                return True
            try:
                self._collect_call(context, child)
                self.pass_through(run, token)
            except EngineError as e:
                self._handle_failure(context, e)
            return True
        return False

    def _collect_call(self, context: Context, child: Run) -> None:
        """`chk:call.output` — **적은 것만** 올려 보낸다 (프로토타입의 「비면 전부」는 없앴다)."""
        run, node = context.run, context.node
        spec = node.prop("call")
        for variable, theirs in (spec.output if spec else {}).items():
            if theirs not in child.variables:
                raise EngineError(
                    f"호출 대상에 없는 변수를 받는다: {theirs}", node_id=node.id, code="call_output_missing"
                )
            run.variables[variable] = child.variables[theirs]

    def run_until_blocked(self, run: Run, *, max_steps: int = MAX_STEPS) -> State:
        """멈출 때까지 (끝·실패·기다림) 돈다."""
        for _ in range(max_steps):
            if run.finished:
                return run.state
            if self.blocked(run):
                if any(t.waiting for t in run.tokens):
                    run.state = State.WAITING
                    return run.state
                return self._finish(run, "success")
            self.step(run)
        return self._fail(
            run, EngineError(f"노드를 {max_steps}번 밟았는데 끝나지 않았다 (돌고 도는 그림?)", code="too_many_steps")
        )

    # ── 결과 적용 ──

    def _apply(self, context: Context, outcome: Outcome) -> State:
        run, token, node = context.run, context.token, context.node

        if isinstance(outcome, Wait):
            run.log.emit("node_state", node_id=node.id, state="waiting", task_type=task_type(node))
            token.waiting_for = outcome.key
            # 멈춰 있는 동안에만 경계가 울릴 수 있다 (기한 초과·독촉·중단 신호).
            self.arm_boundaries(context, token)
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

        # 파일 출력은 **그 태스크가 끝날 때** 쓴다 (C14 §파일 출력) — 「완료」보다 먼저여서,
        # 쓰다 실패하면 완료로 남지 않고 오류 경계로 간다.
        self.write_data_outputs(context)
        run.log.emit("node_state", node_id=node.id, state="completed", task_type=task_type(node))
        return self._move(context, outcome.targets)

    def write_data_outputs(self, context: Context) -> None:
        """`dataOutputAssociation`으로 이어진 파일 출력을 쓴다 (C14 §파일 출력).

        반복이 붙은 태스크는 **다 돌고 나서 한 번** 쓴다 (`collect_into`가 찬 뒤다).
        """
        run, node = context.run, context.node
        for ref in node.data_outputs:
            target = run.process.node(ref)
            if target is None:
                raise EngineError(
                    f"dataOutputAssociation의 대상이 없다: {ref}", node_id=node.id, code="data_object_missing"
                )
            spec: DataOutput | None = target.prop("dataOutput")
            if spec is None:
                continue  # `chk:dataOutput`이 없는 평범한 데이터 객체 — 쓸 것이 없다
            if not spec.store_as:
                raise EngineError(
                    f"{target.id}의 파일 출력에 store_as가 없다 (B5)", node_id=node.id, code="data_no_store"
                )
            try:
                written = write_output(run.env.workspace, spec, run.scope(node.id))
            except PathDenied as e:
                raise EngineError(str(e), node_id=node.id, code=CODE_PATH_DENIED) from e
            except FileTaskError as e:
                raise TaskFailed(str(e), node_id=node.id) from e
            run.variables[spec.store_as] = written.path
            # **경로는 남기지 않는다** (파일 이름에 거래처·사람 이름이 들어간다 — 원칙 6).
            run.log.emit(
                "log", node_id=target.id, level="info",
                message=f"파일을 썼다 ({spec.format}, {written.size}바이트)",
            )

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
            run.tokens.append(Token(id=new_token_id(), node_id=extra, scope=token.scope))
        if len(targets) > 1:
            # 갈라진 가지는 **맨 앞부터** 번갈아 민다. 첫 가지가 원래 토큰을 이어 쓰므로,
            # 그대로 두면 「방금 민 것」으로 보여 둘째 가지가 먼저 달린다 (신호가 어긋난다).
            run.last_token_id = ""
        return run.state

    def pass_through(self, run: Run, token: Token) -> None:
        """그 토큰을 **지금 노드를 지나** 다음으로 옮긴다 (하위 프로세스가 끝났을 때).

        다시 밟으면 하위 프로세스에 끝없이 들어간다.
        """
        node = run.node(token.node_id)
        context = Context(engine=self, run=run, token=token, node=node)
        self.write_data_outputs(context)
        run.log.emit("node_state", node_id=node.id, state="completed", task_type=task_type(node))
        self._move(context, None)

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
            task_type=task_type(node),
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
            run.tokens.append(Token(id=new_token_id(), node_id=extra.target, scope=token.scope))
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
        run.state = State.DONE if status == "success" else State.FAILED
        run.tokens = []
        if run.nested:
            return run.state  # 안쪽 실행은 C3에 자기 끝을 남기지 않는다 (부르는 쪽이 이어 간다)
        duration = max(0.0, (utc_now() - run.started).total_seconds())
        run.log.emit(
            "run_finished",
            status=status,
            duration_s=round(duration, 3),
            **summarize(run.log.events),
            **({"error_code": error.code, "error_message": str(error)} if error else {}),
        )
        return run.state

    def cancel(self, run: Run, *, reason: str = "") -> State:
        """실행을 **취소로 끝낸다** (사람이 중지했다 — BUI-04 「중지」, C3 `cancelled`).

        실패가 아니다 — `run.error`를 두지 않는다. 쥐고 있던 결재 요청·기다림은 걷는다
        (아무도 답할 사람이 없어진다).
        """
        if run.finished:
            return run.state
        if reason:
            run.log.emit("log", level="warn", message=reason)
        run.pendings.clear()
        run.waits.clear()
        for child in run.children.values():
            self.cancel(child)
        return self._finish(run, "cancelled")

    def _fail(self, run: Run, error: EngineError) -> State:
        run.error = error
        if error.node_id and any(n.id == error.node_id for n in run.process.all_nodes()):
            run.log.emit(
                "node_state",
                node_id=error.node_id,
                state="failed",
                task_type=task_type(run.node(error.node_id)),
                error_code=error.code,
                message=str(error),
            )
        log.warning("실행 %s 실패: %s", run.run_id, error)
        return self._finish(run, "failed", error=error)

    # ── 기다림 (메시지·타이머·신호) ──

    def arm(self, context: Context, waiting: Waiting) -> None:
        """기다릴 것을 등록한다. 타이머면 **지금부터** 잰다."""
        run = context.run
        if waiting.kind == WAIT_TIMER and waiting.due_at is None:
            raise EngineError("타이머에 시각이 없다", node_id=waiting.node_id, code="timer_unset")
        run.waits[waiting.key] = waiting

    def arm_boundaries(self, context: Context, token: Token) -> None:
        """그 노드에 붙은 **오류가 아닌** 경계를 켠다 (타이머·메시지·신호).

        토큰이 멈출 때만 켠다 — 한 걸음에 끝나는 노드에서는 경계가 울릴 틈이 없다.
        """
        run, node = context.run, context.node
        for boundary in run.boundaries(node.id):
            kind = event_kind(boundary)
            if kind is None:
                continue  # 오류 경계는 `_handle_failure`가 따로 본다
            key = f"{kind}:{boundary.id}:{token.id}"
            self.arm(
                context,
                Waiting(
                    key=key,
                    node_id=boundary.id,
                    kind=kind,
                    name=self.event_name(run, boundary, kind),
                    correlation=correlation_of(run, boundary),
                    due_at=self.due_at(run, boundary) if kind == WAIT_TIMER else None,
                    attached_to=node.id,
                    interrupting=boundary.cancel_activity,
                    token_id=token.id,
                ),
            )

    def disarm(self, run: Run, token_id: str) -> None:
        """그 토큰에 걸린 경계를 끈다 (호스트가 기다림을 끝냈다)."""
        for key in [k for k, w in run.waits.items() if w.token_id == token_id and w.on_boundary]:
            del run.waits[key]

    def event_name(self, run: Run, node: Node, kind: str) -> str:
        """메시지·신호의 **이름** (정의 수준 `bpmn:message`·`bpmn:signal`의 `name`)."""
        if kind == WAIT_MESSAGE:
            table, ref = run.process.messages, node.message_ref
        elif kind == WAIT_SIGNAL:
            table, ref = run.process.signals, node.signal_ref
        else:
            return ""
        return next((name for name, id_ in table.items() if id_ == ref), ref or "")

    def due_at(self, run: Run, node: Node) -> datetime:
        """타이머가 울릴 시각. 기간(`PT30M`)이거나 **변수 이름**이다 (C14 §이벤트)."""
        timer = node.timer
        now = run.env.clock()
        if timer is None:
            raise EngineError("타이머 정의가 비어 있다", node_id=node.id, code="timer_unset")
        if timer.kind == "timeCycle":
            raise EngineError(
                "경계·중간 타이머에 반복(`timeCycle`)은 schema 1에서 쓰지 않는다 (C14)",
                node_id=node.id,
                code="timer_cycle",
            )
        value = timer.value
        if timer.is_variable:
            if value not in run.variables:
                raise EngineError(f"타이머가 가리키는 변수가 없다: {value}", node_id=node.id, code="timer_var")
            value = str(run.variables[value])
        return now + _as_duration(value, node_id=node.id)

    def deliver(
        self,
        run: Run,
        name: str,
        *,
        correlation: Any = None,
        payload: Mapping[str, Any] | None = None,
    ) -> State:
        """메시지를 넣는다 (C12 Center 메시지 API·Bot UI 수신이 부른다).

        **상관 키가 맞는 것만** 깨운다. 받을 곳이 없으면 아무 일도 없다 — 케이스가 `no_receiver`로
        기록만 하고 실패시키지 않는 것과 같은 태도다 (C14 시험 케이스 형식).
        """
        found = next(
            (
                w for w in run.waits.values()
                if w.kind == WAIT_MESSAGE and w.name == name
                and (w.correlation is None or correlation is None or w.correlation == correlation)
            ),
            None,
        )
        if found is None:
            run.log.emit("log", level="warn", message=f"받을 곳이 없는 메시지다: {name}")
            return run.state
        node = run.node(found.node_id)
        receive = node.prop("receive")
        if payload and receive is not None:
            # **적은 이름만** 변수가 된다 (C14 `chk:receive.payload`).
            run.variables.update({k: v for k, v in payload.items() if k in receive.payload})
        return self._wake(run, found)

    def signal(self, run: Run, name: str) -> State:
        """신호를 보낸다 — **한 실행 안의 가지 사이에서만** (C14 §이벤트). 기다리는 것을 모두 깨운다."""
        waiting = [w for w in run.waits.values() if w.kind == WAIT_SIGNAL and w.name == name]
        if not waiting:
            run.log.emit("log", level="info", message=f"받는 가지가 없는 신호다: {name}")
        for found in waiting:
            if found.key in run.waits:  # 앞 신호가 끊었을 수 있다
                self._wake(run, found)
        return run.state

    def tick(self, run: Run, now: datetime | None = None) -> State:
        """시간이 된 타이머를 울린다. 부르는 쪽(Bot UI·서버 실행기)이 주기적으로 부른다."""
        at = now or run.env.clock()
        for found in run.due(at):
            if found.key in run.waits:
                self._wake(run, found)
        return self.run_until_blocked(run)

    def _wake(self, run: Run, waiting: Waiting) -> State:
        """기다리던 것이 왔다. 경계면 호스트를 끊거나(중단) 가지를 하나 띄운다(비중단)."""
        run.waits.pop(waiting.key, None)
        node = run.node(waiting.node_id)
        if not waiting.on_boundary:
            token = next((t for t in run.tokens if t.waiting_for == waiting.key), None)
            if token is None:
                return run.state
            token.waiting_for = None
            self.disarm(run, token.id)
            run.log.emit("log", node_id=node.id, level="info", message=f"{waiting.kind}을 받았다")
            self.pass_through(run, token)
            return run.state

        host = run.token(waiting.token_id)
        if host is None:
            return run.state
        flows = run.outgoing(node.id, host.scope)
        if not flows:
            return self._fail(
                run, EngineError("경계 이벤트에 나가는 흐름이 없다", node_id=node.id, code="no_outgoing")
            )
        run.log.emit("node_state", node_id=node.id, state="completed", task_type=None)

        if not waiting.interrupting:
            # 비중단 — 호스트는 그대로 기다리고, 가지 하나가 따로 간다.
            for flow in flows:
                run.tokens.append(Token(id=new_token_id(), node_id=flow.target, scope=host.scope))
            return run.state

        # 중단 — 호스트가 기다리던 것을 걷어 내고 경계 길로 보낸다.
        self._cancel(run, host)
        host.node_id = flows[0].target
        for extra in flows[1:]:
            run.tokens.append(Token(id=new_token_id(), node_id=extra.target, scope=host.scope))
        return run.state

    def _cancel(self, run: Run, host: Token) -> None:
        """끊긴 호스트가 쥐고 있던 것을 걷는다 (결재 요청·안쪽 토큰·자기 기다림·경계)."""
        key = host.waiting_for
        host.waiting_for = None
        self.disarm(run, host.id)
        if key is None:
            return
        run.pendings.pop(key, None)
        run.waits.pop(key, None)
        if key.startswith("sub:"):
            inside = key[len("sub:") :]
            run.tokens = [t for t in run.tokens if inside not in t.scope]
        run.children.pop(key, None)

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
        self.disarm(run, token.id)

        node = run.node(pending.node_id)
        context = Context(engine=self, run=run, token=token, node=node)
        try:
            return self._apply(context, Go())
        except ExprError as e:
            return self._handle_failure(context, EngineError(e.reason, node_id=node.id, code="expr_error"))
        except EngineError as e:
            # 답 뒤에 쓰는 파일이 실패할 수 있다 — 그것도 오류 경계가 받는다.
            return self._handle_failure(context, e)

    def withdraw(self, run: Run, request_id: str, *, reason: str) -> State:
        """Center 결재가 **답 없이 끝났다** — 관리자 회수·만료 (C6, ADR-0038).

        답이 아니다. 그 노드에 오류 경계가 있으면 그리로 가고(`APPROVAL_WITHDRAWN`·`APPROVAL_EXPIRED`),
        없으면 실행이 실패로 끝난다. 기록에는 사유만 남긴다 (C3 `human_withdrawn`).
        """
        pending = run.pendings.get(request_id)
        token = next((t for t in run.tokens if t.waiting_for == request_id), None)
        if pending is None or token is None:
            raise EngineError(f"기다리는 요청이 아니다: {request_id}", code="not_waiting")
        run.log.emit("human_withdrawn", node_id=pending.node_id, request_id=request_id, reason=reason)
        del run.pendings[request_id]
        token.waiting_for = None
        self.disarm(run, token.id)
        expired = reason == "expired"
        error = TaskFailed(
            "결재 기한이 지났습니다" if expired else f"결재가 회수되었습니다 ({reason})",
            node_id=pending.node_id,
            code=ERROR_APPROVAL_EXPIRED if expired else ERROR_APPROVAL_WITHDRAWN,
        )
        node = run.node(pending.node_id)
        return self._handle_failure(Context(engine=self, run=run, token=token, node=node), error)

    def timeout(self, run: Run, request_id: str) -> State:
        """시간 초과 (C3 `human_timeout`). 실행은 실패로 끝낸다 — 되돌릴 길은 M5다."""
        pending = run.pendings.get(request_id)
        if pending is None:
            raise EngineError(f"기다리는 요청이 아니다: {request_id}", code="not_waiting")
        run.log.emit("human_timeout", node_id=pending.node_id, request_id=request_id)
        del run.pendings[request_id]
        return self._fail(run, EngineError("결재 시간이 지났다", node_id=pending.node_id, code="human_timeout"))


__all__ = [
    "BUILTIN_NOW",
    "BUILTIN_RUN_ID",
    "BUILTIN_TODAY",
    "CODE_PATH_DENIED",
    "CODE_UNSUPPORTED",
    "DECISION_KEY",
    "DEFAULT_HANDLERS",
    "ERROR_CODE_VAR",
    "ERROR_MESSAGE_VAR",
    "ERROR_APPROVAL_EXPIRED",
    "ERROR_APPROVAL_WITHDRAWN",
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
    "RunEnv",
    "State",
    "TaskFailed",
    "Token",
    "WAIT_MESSAGE",
    "WAIT_SIGNAL",
    "WAIT_TIMER",
    "WHERE_CENTER",
    "WHERE_FIELD",
    "Wait",
    "Waiting",
    "Workspace",
    "evaluate",
    "new_run_id",
]

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
from datetime import datetime
from typing import Any

from chaeksas.contracts.approvals import Form, FormField
from chaeksas.contracts.bpmn_ext import BpmnProcess, DataOutput, Node
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
    ERROR_CODE_VAR,
    ERROR_MESSAGE_VAR,
    ERROR_SEND_FAILED,
    ERROR_TASK_FAILED,
    FAILED_TASK_VAR,
    MAX_STEPS,
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
    new_run_id,
    new_token_id,
    task_type,
    utc_now,
)

log = logging.getLogger(__name__)


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
    ) -> Run:
        """실행을 만들고 `run_started`를 남긴다. 토큰은 시작 이벤트에 놓인다."""
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
            run.log.emit("node_state", node_id=node.id, state="waiting", task_type=task_type(node))
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
        duration = max(0.0, (utc_now() - run.started).total_seconds())
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
                task_type=task_type(run.node(error.node_id)),
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
        except ExprError as e:
            return self._handle_failure(context, EngineError(e.reason, node_id=node.id, code="expr_error"))
        except EngineError as e:
            # 답 뒤에 쓰는 파일이 실패할 수 있다 — 그것도 오류 경계가 받는다.
            return self._handle_failure(context, e)

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
    "Wait",
    "Workspace",
    "evaluate",
    "new_run_id",
]

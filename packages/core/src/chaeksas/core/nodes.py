"""노드 수행기 — `Engine.handlers`에 꽂히는 것들 (C14 §태스크 종류·§이벤트).

수행기 하나는 `Context`를 받아 **다음에 무엇을 할지**를 돌려준다 (`Go`·`Wait`·`Consume`).
노드 종류를 더하는 일은 여기에 함수 하나를 쓰고 `DEFAULT_HANDLERS`에 줄 하나를 더하는 것이다.

갈림은 둘뿐이다.

- **업무 실패는 `TaskFailed`로 올린다** — 오류 경계가 받는다 (바깥 시스템이 500을 줬다,
  공유 폴더가 안 붙었다).
- **그림·설정이 잘못된 것은 `EngineError`다** — 경계로 받지 않는다 (식 오류, 허용 밖 경로,
  없는 DMN). 흐름으로 우회할 일이 아니라 고쳐야 한다.

**모르는 노드는 조용히 지나가지 않는다** — 뒤 조각에서 더할 것은 `CODE_UNSUPPORTED`로 멈춘다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chaeksas.contracts.approvals import Form, request_id_for
from chaeksas.contracts.bpmn_ext import (
    PC_ONLY_DOMAINS,
    WEBHOOK_BODY_ALL,
    AiTask,
    Email,
    FileList,
    Flow,
    Node,
    Rule,
    ServiceCall,
    Webhook,
)
from chaeksas.contracts.dmn import DmnError
from chaeksas.core.agent import AgentError, run_agent
from chaeksas.core.expr import Scope, evaluate, fill, run_script, truthy
from chaeksas.core.files import FileTaskError, PathDenied, list_files
from chaeksas.core.run_state import (
    CODE_PATH_DENIED,
    CODE_UNSUPPORTED,
    ERROR_SEND_FAILED,
    Consume,
    Context,
    EngineError,
    Go,
    Handler,
    Outcome,
    Pending,
    TaskFailed,
    Token,
    Wait,
    new_token_id,
)
from chaeksas.core.senders import EmailMessage, SendError, WebhookRequest
from chaeksas.core.services import RETRYABLE_STATUS, OpCall, OpOutcome, ServiceCallError

#: 웹훅 본문 적는 법 (C14 — `all` | `fields:[…]` | `template:"…"`).
_WEBHOOK_FIELDS = re.compile(r"^fields\s*:\s*\[(.*)\]$", re.S)
_WEBHOOK_TEMPLATE = re.compile(r"^template\s*:\s*(.*)$", re.S)


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
    run.tokens.append(Token(id=new_token_id(), node_id=starts[0].id, scope=(*token.scope, node.id)))
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


def handle_milestone(context: Context) -> Outcome:
    """이정표 (`intermediateThrowEvent`, 이벤트 정의 없음) — 지나가면서 기록만 남긴다.

    「어디까지 왔는지」를 콘솔·Studio가 `node_state`(`task_type: milestone`)로 보인다 (C14).
    신호·메시지 던지기는 다른 것이라 여기서 멈춘다 (조각 3d).
    """
    node = context.node
    if node.event_definitions:
        raise EngineError(
            f"아직 다루지 않는 중간 던지기다: {', '.join(node.event_definitions)} (조각 3d)",
            node_id=node.id,
            code=CODE_UNSUPPORTED,
        )
    context.emit("log", level="info", message=f"이정표: {node.name or node.id}")
    return Go()


# ─────────────────────────── 규칙 (DMN) ───────────────────────────


def handle_rule(context: Context) -> Outcome:
    """`businessRuleTask` — 같은 패키지의 DMN 결정으로 **한 건**을 판정한다 (C14).

    표가 잘못된 것(`UNIQUE`인데 둘이 맞음, 입력이 빠짐)은 **오류 경계로 받지 않는다** — 고쳐야
    할 그림이다. 적중한 줄이 없는 것은 실패가 아니다 (출력이 `None`·빈 목록이고, 게이트웨이로
    가른다).
    """
    run, node = context.run, context.node
    spec: Rule | None = node.prop("rule")
    if spec is None:
        raise EngineError("`chk:rule`이 없다", node_id=node.id, code="rule_missing")
    decision = run.env.decisions.get(spec.decision)
    if decision is None:
        known = ", ".join(sorted(run.env.decisions)) or "없음"
        raise EngineError(
            f"DMN 결정을 찾지 못했다: {spec.decision} (패키지에 있는 것: {known})",
            node_id=node.id,
            code="decision_missing",
        )

    scope = context.scope()
    values = {name: evaluate(expression, scope) for name, expression in spec.input.items()}
    try:
        decided = decision.decide(values)
    except DmnError as e:
        raise EngineError(str(e), node_id=node.id, code="dmn_error") from e

    for variable, output in spec.output.items():
        if output not in decided:
            raise EngineError(
                f"DMN 출력에 없는 것을 받는다: {output} (있는 것: {', '.join(decided)})",
                node_id=node.id,
                code="dmn_output_missing",
            )
        run.variables[variable] = decided[output]
    # **값은 남기지 않는다** (원칙 6) — 어느 표로 몇 개를 정했는지만.
    context.emit("log", level="info", message=f"규칙 {spec.decision}: 변수 {len(spec.output)}개")
    return Go()


# ─────────────────────────── 파일 (목록·출력) ───────────────────────────


def handle_service_task(context: Context) -> Outcome:
    """`serviceTask` 하나에 세 가지가 올라탄다 — 무엇인지는 `chk:*`가 가린다 (C14 §태스크 종류).

    | 속성 | 무엇 |
    | --- | --- |
    | `chk:fileList` | 파일 목록 (ADR-0026) |
    | `chk:serviceCall` | 서비스 앱 태스크 (C11) |
    | `chk:aiTask` | AI 태스크 (ADR-0008 「운전사」, ADR-0027) |
    | `chk:task` | 확장 태스크 (UI 태스크 등) — M4 |
    """
    node = context.node
    files: FileList | None = node.prop("fileList")
    if files is not None:
        return handle_file_list(context, files)
    call: ServiceCall | None = node.prop("serviceCall")
    if call is not None:
        return handle_service_call(context, call)
    ai: AiTask | None = node.prop("aiTask")
    if ai is not None:
        return handle_ai_task(context, ai)
    if node.prop("task") is not None:
        raise EngineError(
            "확장 태스크는 아직 수행하지 않는다 (UI 자동화는 M4)", node_id=node.id, code=CODE_UNSUPPORTED
        )
    raise EngineError("무엇을 하는 서비스 태스크인지 모른다 (`chk:*`가 없다)", node_id=node.id, code="task_empty")


def handle_ai_task(context: Context, spec: AiTask) -> Outcome:
    """`chk:aiTask` — 운전사에게 목표를 주고 결과 필드를 받는다 (ADR-0008·ADR-0027).

    PC에서만 되는 환경(`web`·`desktop`)은 M4다. 그 밖(`llm`·`doc`·`api`)은 지금 돈다.

    실행 기록에는 **단계와 사용량만** 남는다 (C3 `agent`·`llm_usage`) — 목표·도구 인자·결과
    값은 업무 값이라 담지 않는다 (원칙 6).
    """
    run, node = context.run, context.node
    if spec.domain in PC_ONLY_DOMAINS:
        raise EngineError(
            f"`domain: {spec.domain}` AI 태스크는 아직 수행하지 않는다 (UI 자동화와 함께 M4)",
            node_id=node.id,
            code=CODE_UNSUPPORTED,
        )

    def note(step: int, action: str, tool: str) -> None:
        # C3 `agent` — 필수 키는 `step`·`action`. **값은 담지 않는다** (`summary`를 비워 둔다).
        run.log.emit("agent", node_id=node.id, step=step, action=action, **({"tool": tool} if tool else {}))

    try:
        outcome = run_agent(spec, llm=run.env.llm, tools=run.env.tools, on_step=note)
    except AgentError as e:
        if e.business:
            raise TaskFailed(str(e), node_id=node.id) from e
        raise EngineError(str(e), node_id=node.id, code="agent_error") from e

    trace = outcome.trace
    if trace.model:
        run.log.emit(
            "llm_usage",
            node_id=node.id,
            model=trace.model,
            input_tokens=trace.input_tokens,
            output_tokens=trace.output_tokens,
        )
    run.variables.update(outcome.results)
    context.emit("log", level="info", message=f"AI 결과 {len(outcome.results)}개 (도구 {len(trace.steps)}회)")
    return Go()


def handle_service_call(context: Context, spec: ServiceCall) -> Outcome:
    """`chk:serviceCall` — 서비스 앱의 작업 하나를 부른다 (C11).

    재시도는 **여기서** 한다 — `retry.on`에 든 상태 코드이거나 닿지 못한 것이면 `attempt`를
    올려 다시 부른다. 멱등 키에 `attempt`가 들어가므로 같은 번호로 다시 부르면 앱이 저장된
    결과를 돌려준다 (C11 §전송).

    마지막까지 실패하면 `TaskFailed`라서 **오류 경계가 받는다** (`TASK_FAILED`). 키가 틀렸거나
    없는 작업을 부른 것(`FATAL_CODES`)은 다시 불러도 똑같으므로 바로 그만둔다.
    """
    run, node = context.run, context.node
    key_ref = spec.key_ref or run.process.info.service_keys.get(spec.app_id)
    scope = context.scope()
    arguments = {name: evaluate(expression, scope) for name, expression in spec.input.items()}

    retry = spec.retry
    codes = tuple(retry.on) if (retry and retry.on) else RETRYABLE_STATUS
    attempts = (retry.max if retry else 0) + 1
    call_seq = run.call_seqs.get(node.id, 0) + 1
    run.call_seqs[node.id] = call_seq

    last: ServiceCallError | None = None
    for attempt in range(1, attempts + 1):
        call = OpCall(
            app_id=spec.app_id,
            operation=spec.operation,
            mode=run.mode,
            input=arguments,
            run_id=run.run_id,
            node_id=node.id,
            node_instance=context.instance(),
            attempt=attempt,
            call_seq=call_seq,
            key_ref=key_ref,
            timeout_s=spec.timeout_s,
            bpm_process_id=run.process.id,
            version=run.version,
        )
        try:
            outcome = run.env.services.call(call)
        except ServiceCallError as e:
            last = e
            # 실패도 C3에 남긴다 — 「몇 번 불렀고 왜 실패했나」가 보여야 한다.
            run.log.emit(
                "service_call",
                node_id=node.id,
                **OpOutcome(output={}, status=e.status or 0, mode_used=run.mode).event_data(call),
                error_code=e.code or "unreachable",
            )
            if not (e.retryable and (e.status is None or e.status in codes)) or attempt >= attempts:
                break
            context.emit("log", level="warn", message=f"다시 부른다 ({attempt + 1}/{attempts})")
            continue

        run.log.emit("service_call", node_id=node.id, **outcome.event_data(call))
        for variable, output in spec.output.items():
            if output not in outcome.output:
                raise EngineError(
                    f"{spec.app_id}/{spec.operation}의 출력에 없는 것을 받는다: {output} "
                    f"(있는 것: {', '.join(outcome.output) or '없음'})",
                    node_id=node.id,
                    code="service_output_missing",
                )
            run.variables[variable] = outcome.output[output]
        return Go()

    assert last is not None
    raise TaskFailed(f"{spec.app_id}/{spec.operation}: {last}", node_id=node.id) from last


def handle_file_list(context: Context, spec: FileList) -> Outcome:
    """`chk:fileList` — 폴더를 훑어 파일 경로 목록을 변수에 담는다 (C14, ADR-0026)."""
    run, node = context.run, context.node
    if not spec.store_as:
        raise EngineError("파일 목록에 `store_as`가 없다 (B5)", node_id=node.id, code="file_list_no_store")
    try:
        listing = list_files(run.env.workspace, spec, context.scope())
    except PathDenied as e:
        raise EngineError(str(e), node_id=node.id, code=CODE_PATH_DENIED) from e
    except FileTaskError as e:
        raise TaskFailed(str(e), node_id=node.id) from e

    run.variables[spec.store_as] = listing.paths
    if spec.count_as:
        run.variables[spec.count_as] = listing.count
    context.emit("log", level="info", message=f"파일 {listing.count}건")
    return Go()


# ─────────────────────────── 보내기 (메일·웹훅) ───────────────────────────


def handle_send(context: Context) -> Outcome:
    """`sendTask` — `chk:email` 또는 `chk:webhook`. 실패는 `SEND_FAILED`로 올린다 (C14)."""
    node = context.node
    email: Email | None = node.prop("email")
    if email is not None:
        return _send_email(context, email)
    webhook: Webhook | None = node.prop("webhook")
    if webhook is not None:
        return _send_webhook(context, webhook)
    raise EngineError("`chk:email`·`chk:webhook`이 모두 없다", node_id=node.id, code="send_missing")


def _send_email(context: Context, spec: Email) -> Outcome:
    run, node = context.run, context.node
    scope = context.scope()
    message = EmailMessage(
        to=tuple(fill(one, scope) for one in spec.to),
        cc=tuple(fill(one, scope) for one in spec.cc),
        subject=fill(spec.subject, scope),
        body=fill(spec.body, scope),
        attachments=tuple(p for name in spec.attachments for p in _attachments(context, name)),
    )
    try:
        result = run.env.sender.send_email(message)
    except SendError as e:
        raise TaskFailed(str(e), node_id=node.id, code=ERROR_SEND_FAILED) from e

    if spec.store_as:
        run.variables[spec.store_as] = result.email_summary(recipients=len(message.to))
    # 받는 사람·제목은 업무 값이다 — **개수만** 남긴다 (원칙 6).
    context.emit(
        "log", level="info",
        message=f"메일 보냄 (받는 사람 {len(message.to)}, 첨부 {len(message.attachments)})",
    )
    return Go()


def _attachments(context: Context, name: str) -> list[Path]:
    """첨부 변수 하나가 가리키는 파일들. 값은 경로 하나이거나 경로 목록이다."""
    run, node = context.run, context.node
    if name not in run.variables:
        raise EngineError(f"첨부가 가리키는 변수가 없다: {name}", node_id=node.id, code="attachment_missing")
    value = run.variables[name]
    raw = [value] if isinstance(value, str) else list(value or [])
    out = []
    for one in raw:
        try:
            out.append(run.env.workspace.for_read(str(one)))
        except PathDenied as e:
            raise EngineError(str(e), node_id=node.id, code=CODE_PATH_DENIED) from e
    return out


def _send_webhook(context: Context, spec: Webhook) -> Outcome:
    run, node = context.run, context.node
    scope = context.scope()
    request = WebhookRequest(
        url=fill(spec.url, scope),
        method=spec.method,
        body=_webhook_body(context, spec, scope),
        timeout_s=spec.timeout_s,
    )
    try:
        result = run.env.sender.send_webhook(request)
    except SendError as e:
        raise TaskFailed(str(e), node_id=node.id, code=ERROR_SEND_FAILED) from e

    if spec.store_as:
        run.variables[spec.store_as] = result.webhook_summary()
    context.emit("log", level="info", message=f"웹훅 보냄 ({spec.method}, 상태 {result.status})")
    return Go()


def _webhook_body(context: Context, spec: Webhook, scope: Scope) -> Mapping[str, Any] | str:
    """`all` | `fields:[이름, 이름]` | `template:"…"` (C14)."""
    run, node = context.run, context.node
    body = (spec.body or WEBHOOK_BODY_ALL).strip()
    if body == WEBHOOK_BODY_ALL:
        return dict(run.variables)  # B13이 「비밀이 섞일 수 있다」고 경고하는 자리다

    found = _WEBHOOK_FIELDS.match(body)
    if found is not None:
        names = [one.strip() for one in found.group(1).split(",") if one.strip()]
        missing = [one for one in names if one not in run.variables]
        if missing:
            raise EngineError(
                f"웹훅이 없는 변수를 보낸다: {', '.join(missing)}", node_id=node.id, code="webhook_var_missing"
            )
        return {one: run.variables[one] for one in names}

    found = _WEBHOOK_TEMPLATE.match(body)
    if found is not None:
        text = found.group(1).strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1]
        return fill(text, scope)

    raise EngineError(
        f"웹훅 body를 모른다: {body} (`all`·`fields:[…]`·`template:\"…\"`)",
        node_id=node.id,
        code="webhook_body_unknown",
    )


#: 기본 수행기. 뒤 조각에서 AI·서비스 앱(3c)·타이머·메시지·신호(3d)가 더해진다.
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
    "businessRuleTask": handle_rule,
    "serviceTask": handle_service_task,
    "sendTask": handle_send,
    "intermediateThrowEvent": handle_milestone,
}


__all__ = [
    "DEFAULT_HANDLERS",
    "handle_ai_task",
    "handle_approval",
    "handle_end",
    "handle_exclusive",
    "handle_file_list",
    "handle_inclusive",
    "handle_milestone",
    "handle_parallel",
    "handle_pass",
    "handle_rule",
    "handle_script",
    "handle_send",
    "handle_service_call",
    "handle_service_task",
    "handle_subprocess",
]

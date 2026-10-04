"""AI 태스크의 운전사 — 목표를 주고, 도구를 빌려 주고, 결과 필드를 받아 낸다.

[ADR-0008](../../../../docs/decisions/0008-map-driver-hands-boundary.md)의 「운전사」가 여기다.
지도(BPMN)는 순서를, 운전사는 **방법**을 안다. 모델에 닿는 길은
[ADR-0027](../../../../docs/decisions/0027-llm-connection.md)이 정했고, 루프는 **우리가** 돈다 —
그래야 도구를 고르고, 허용 밖을 막고, 궤적을 적어 재생할 수 있다.

갈림은 둘이다 (C14·`core.nodes`와 같은 규칙).

- **모델이 틀린 답을 낸 것은 업무 실패**(`TaskFailed`)다 — 결과 필드가 빠졌거나 타입이 다르면
  오류 경계가 받을 수 있다. 모델은 가끔 틀리고, 그것은 흐름으로 대처할 거리다.
- **허용하지 않은 도구를 부르거나 단계 한도를 넘은 것은 실행 오류**다 — 그림·설정이 잘못된
  것이라 경계로 받지 않는다.

**값은 실행 기록에 담지 않는다** (원칙 6). 단계는 C3 `agent`로, 사용량은 `llm_usage`로 남고
둘 다 값이 없다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts.bpmn_ext import AiTask
from chaeksas.core.llm import Llm, LlmError, Reply, ToolCall, ToolSpec

#: 한 AI 태스크에서 모델에게 물어볼 수 있는 횟수의 기본 한도 (`limits.max_steps`가 이긴다).
DEFAULT_MAX_STEPS = 8

#: C14 `results`의 타입 → 받아도 되는 파이썬 타입 (B8의 `VALUE_TYPES`와 짝이다).
RESULT_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "date": (str,),  # `YYYY-MM-DD` 문자열이다 (C14)
    "int": (int,),
    "number": (int, float),
    "bool": (bool,),
    "list": (list,),
    "dict": (dict,),
}

#: 도구 하나 — 이름 있는 인자를 받아 **글**을 돌려준다 (모델에게 다시 넣어야 하므로).
Tool = Callable[..., str]

SYSTEM_PROMPT = (
    "너는 업무 절차의 한 단계를 수행한다. 아래 목표만 하고, 순서·승인 규칙은 스스로 바꾸지 않는다.\n"
    "할 수 있는 일이 끝나면 **설명 없이 JSON 객체 하나만** 낸다."
)


class AgentError(RuntimeError):
    """운전사가 멈춰야 하는 문제. `business`면 업무 실패(오류 경계가 받는다)다."""

    def __init__(self, message: str, *, business: bool = False) -> None:
        super().__init__(message)
        self.business = business


@dataclass
class Step:
    """궤적 한 걸음. 재생(결정 수행)이 이것을 되밟는다 (ADR-0028)."""

    tool: str
    arguments: dict[str, Any]
    #: 도구가 돌려준 글. 길면 잘라 둔다 — 기억은 「무엇을 어떤 차례로」가 중요하다.
    result: str = ""


@dataclass
class Trace:
    """자율 수행 한 번이 남긴 것 — 재생(결정 수행)의 재료다.

    **지금은 적기만 한다.** 무엇을 재사용할지(도구 차례만 되밟을지, 마지막 답까지 쓸지)는
    아직 정하지 않았다 (ADR-0010은 「LLM 쓰지 않거나 최소」라고만 적었다).
    """

    steps: list[Step] = field(default_factory=list)
    #: 마지막 답 (JSON 글 그대로).
    answer: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Outcome:
    """AI 태스크 한 번의 결과."""

    results: dict[str, Any]
    trace: Trace
    #: 모델을 쓰지 않고 되밟았나 (C3 `node_state: replayed`). **재생은 아직 없다** —
    #: 무엇을 재사용할지(도구 차례만 / 마지막 답까지)가 열려 있다 (조각 3c의 남은 일).
    replayed: bool = False


def tool_specs(spec: AiTask, tools: Mapping[str, Tool]) -> list[ToolSpec]:
    """모델에게 알려 줄 도구 — **`chk:aiTask.tools`에 적힌 것만**. 없는 도구는 알려 주지 않는다."""
    return [ToolSpec(name=name) for name in spec.tools if name in tools]


def opening_messages(spec: AiTask, *, context: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """첫 물음. `goal`(Markdown)과 받아야 할 결과 필드를 적는다.

    `context`를 주지 않으면 **업무 파라미터**(`chk:aiTask.params`)를 쓴다 — 주소 같은 값을
    목표 문장이 아니라 파라미터로 두어야 재생이 그 문장에 묶이지 않는다 (예제 FX-01·BX-02).
    """
    wanted = ", ".join(f"{name}({kind})" for name, kind in spec.results.items()) or "없음"
    user = [spec.goal, "", f"## 반환\n다음 필드를 가진 JSON 객체 하나: {wanted}"]
    context = spec.params if context is None else context
    if context:
        # 업무 파라미터(`chk:aiTask.params`)는 **값**이다 — 모델에는 주되 기록에는 남기지 않는다.
        user += ["", "## 파라미터", json.dumps(dict(context), ensure_ascii=False)]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user)},
    ]


def run_agent(
    spec: AiTask,
    *,
    llm: Llm,
    tools: Mapping[str, Tool],
    max_steps: int | None = None,
    on_step: Callable[[int, str, str], None] | None = None,
) -> Outcome:
    """자율 수행 — 모델에게 묻고, 허용된 도구를 빌려 주고, 마지막 JSON을 검증해 돌려준다."""
    limit = max_steps or (spec.limits.max_steps if spec.limits and spec.limits.max_steps else DEFAULT_MAX_STEPS)
    available = tool_specs(spec, tools)
    messages = opening_messages(spec)
    trace = Trace()

    for step in range(1, limit + 1):
        try:
            reply = llm.ask(messages, tools=available)
        except LlmError as e:
            # 모델에 닿지 못한 것은 업무 실패다 — 재시도·대체 흐름으로 대처할 거리다.
            raise AgentError(f"모델을 부르지 못했다: {e}", business=True) from e
        trace.model = reply.model or trace.model
        trace.input_tokens += reply.input_tokens
        trace.output_tokens += reply.output_tokens

        if not reply.wants_tools:
            if on_step is not None:
                on_step(step, "finish", "")
            trace.answer = reply.text
            return Outcome(results=check_results(spec, reply.text), trace=trace)

        if on_step is not None:
            on_step(step, "plan", ",".join(c.name for c in reply.tool_calls))
        messages.append(_assistant_message(reply))
        for call in reply.tool_calls:
            result = _use_tool(spec, tools, call)
            trace.steps.append(Step(tool=call.name, arguments=dict(call.arguments), result=result))
            if on_step is not None:
                on_step(step, "tool", call.name)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    raise AgentError(f"{limit}단계 안에 끝내지 못했다 (`limits.max_steps`를 보라)")


def _assistant_message(reply: Reply) -> dict[str, Any]:
    """모델이 한 말을 그대로 되돌려 넣는다 (OpenAI 호환 모양)."""
    return {
        "role": "assistant",
        "content": reply.text or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
            }
            for call in reply.tool_calls
        ],
    }


def _use_tool(spec: AiTask, tools: Mapping[str, Tool], call: ToolCall) -> str:
    """허용 목록 안인지 보고 부른다. **밖이면 실행 오류다** (경계로 받지 않는다)."""
    if call.name not in spec.tools:
        allowed = ", ".join(spec.tools) or "없음"
        raise AgentError(f"허용하지 않은 도구를 불렀다: {call.name} (허용: {allowed})")
    found = tools.get(call.name)
    if found is None:
        # 그림은 맞는데 이 PC에 도구가 없다 — 업무 실패로 올려 대체 흐름을 쓸 수 있게 한다.
        raise AgentError(f"도구 {call.name}이 이 PC에 없다", business=True)
    return _call(found, call.name, call.arguments)


def _call(tool: Tool, name: str, arguments: Mapping[str, Any]) -> str:
    try:
        return str(tool(**dict(arguments)))
    except Exception as e:  # noqa: BLE001 — 도구가 무엇을 낼지 모른다
        raise AgentError(f"도구 {name}이 실패했다: {e}", business=True) from e


def check_results(spec: AiTask, text: str) -> dict[str, Any]:
    """마지막 답이 `results: {이름: 타입}`대로인지 (C14 §태스크 종류·B8).

    모델이 틀리는 것은 흔하다 — **업무 실패**로 올려 오류 경계가 받게 한다. 값은 메시지에
    담지 않는다 (원칙 6).
    """
    body = _as_json(text)
    bad: list[str] = []
    for name, kind in spec.results.items():
        if name not in body:
            bad.append(f"{name} 없음")
            continue
        wanted = RESULT_TYPES.get(kind)
        value = body[name]
        if wanted is None:
            continue  # B8이 모르는 타입을 미리 잡는다
        # `True`는 수가 아니다 (파이썬에서는 `True == 1`이다).
        if isinstance(value, bool) and kind != "bool":
            bad.append(f"{name}: {kind}가 아니라 bool")
        elif not isinstance(value, wanted):
            bad.append(f"{name}: {kind}가 아니라 {type(value).__name__}")
    if bad:
        raise AgentError(f"결과 필드가 맞지 않는다 ({', '.join(bad)})", business=True)
    return {name: body[name] for name in spec.results}


def _as_json(text: str) -> dict[str, Any]:
    """모델이 ```json 울타리를 두르는 일이 잦다 — 벗겨 내고 읽는다."""
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.partition("\n")[2].rpartition("```")[0].strip()
    try:
        found = json.loads(body)
    except ValueError as e:
        raise AgentError(f"마지막 답이 JSON이 아니다: {e}", business=True) from e
    if not isinstance(found, dict):
        raise AgentError(f"마지막 답이 JSON 객체가 아니다: {type(found).__name__}", business=True)
    return found


def tool_names(specs: Sequence[ToolSpec]) -> list[str]:
    return [s.name for s in specs]


__all__ = [
    "DEFAULT_MAX_STEPS",
    "RESULT_TYPES",
    "SYSTEM_PROMPT",
    "AgentError",
    "Outcome",
    "Step",
    "Tool",
    "Trace",
    "check_results",
    "opening_messages",
    "run_agent",
    "tool_names",
    "tool_specs",
]

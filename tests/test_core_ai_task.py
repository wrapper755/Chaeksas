"""AI 태스크 (`chk:aiTask`) — 운전사 (ADR-0008·ADR-0027).

여기서 거듭 보는 것은 셋이다.

1. **도구 화이트리스트** — `chk:aiTask.tools`에 없는 것을 모델이 부르면 **실행 오류**다
   (그림·모델이 잘못된 것이라 오류 경계로 우회할 일이 아니다).
2. **결과 필드 검증** — `results: {이름: 타입}`대로 오지 않으면 **업무 실패**다 (모델은 가끔
   틀리고, 그것은 흐름으로 대처할 거리다).
3. **값은 기록에 남지 않는다** — C3 `agent`는 단계와 도구 이름만, `llm_usage`는 토큰 수만.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import AiTask, read_process
from chaeksas.contracts.events import REQUIRED_DATA_KEYS
from chaeksas.core.agent import AgentError, check_results, opening_messages, run_agent, tool_specs
from chaeksas.core.engine import Engine, Run, RunEnv, State
from chaeksas.core.llm import (
    LlmError,
    NoLlm,
    OpenAiCompatibleLlm,
    RecordingLlm,
    Reply,
    ToolCall,
    parse_reply,
)
from chaeksas.core.run_log import RunLog

NOW = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
RUN_ID = "run_20261004_093000_abc123"

SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="test.proc" name="시험">
    <bpmn:extensionElements><chk:process>{{}}</chk:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""

AI = (
    '{"goal": "## 할 일\\n청구서에서 공급사와 금액을 뽑는다.", "domain": "doc",'
    ' "tools": ["pdf_text_tool"], "results": {"공급사": "string", "금액": "int"}}'
)


def flow(id_: str, source: str, target: str) -> str:
    return f'<bpmn:sequenceFlow id="{id_}" sourceRef="{source}" targetRef="{target}" />'


def process(ai: str = AI, *, boundary: bool = False) -> Any:
    catcher = (
        '<bpmn:boundaryEvent id="Bnd_Fail" attachedToRef="Task_Ai">'
        "<bpmn:errorEventDefinition/></bpmn:boundaryEvent>"
        '<bpmn:scriptTask id="Task_Recover" scriptFormat="chk-expr">'
        "<bpmn:script>복구 = error_code</bpmn:script></bpmn:scriptTask>"
        '<bpmn:endEvent id="End_2"/>'
        + flow("f3", "Bnd_Fail", "Task_Recover")
        + flow("f4", "Task_Recover", "End_2")
        if boundary
        else ""
    )
    body = (
        '<bpmn:startEvent id="Start_1"/>'
        f'<bpmn:serviceTask id="Task_Ai"><bpmn:extensionElements><chk:aiTask>{ai}'
        "</chk:aiTask></bpmn:extensionElements></bpmn:serviceTask>"
        '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Ai")
        + flow("f2", "Task_Ai", "End_1")
        + catcher
    )
    return read_process(SHELL.format(body=body))


def start(found: Any, env: RunEnv | None = None, **kwargs: Any) -> tuple[Engine, Run]:
    engine = Engine()
    log = RunLog(run_id=RUN_ID)
    return engine, engine.start(found, run_id=RUN_ID, log=log, now=NOW, env=env, **kwargs)


def answer(**fields: Any) -> Reply:
    return Reply(text=json.dumps(fields, ensure_ascii=False), model="stub-1", input_tokens=120, output_tokens=30)


def wants(tool: str, **arguments: Any) -> Reply:
    return Reply(
        tool_calls=(ToolCall(id="c1", name=tool, arguments=arguments),),
        model="stub-1",
        input_tokens=100,
        output_tokens=12,
    )


def spec(**over: Any) -> AiTask:
    return AiTask.model_validate({**json.loads(AI), **over})


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_an_ai_task_without_tools_asks_once_and_fills_the_result_fields() -> None:
    """예제 31곳 중 18곳이 이 모양이다 — 묻고, 구조화된 답을 받는다 (스파이크 S7)."""
    model = RecordingLlm(replies=[answer(공급사="한빛상사", 금액=1250000)])
    engine, run = start(process(), RunEnv(llm=model))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["공급사"] == "한빛상사" and run.variables["금액"] == 1250000
    assert len(model.asked) == 1

    (first,) = model.asked
    assert first[0]["role"] == "system"
    assert "공급사(string), 금액(int)" in first[1]["content"], "받아야 할 필드를 적어 준다"


def test_a_tool_loop_runs_and_the_tool_result_goes_back_to_the_model() -> None:
    seen: list[str] = []

    def pdf(path: str) -> str:
        seen.append(path)
        return "공급사: 한빛상사 / 금액: 1,250,000"

    model = RecordingLlm(
        replies=[wants("pdf_text_tool", path="a.pdf"), answer(공급사="한빛상사", 금액=1250000)]
    )
    engine, run = start(process(), RunEnv(llm=model, tools={"pdf_text_tool": pdf}))
    assert engine.run_until_blocked(run) is State.DONE
    assert seen == ["a.pdf"]
    # 두 번째 물음에는 도구 결과가 붙어 있다.
    assert model.asked[1][-1]["role"] == "tool"
    assert "한빛상사" in model.asked[1][-1]["content"]


def test_a_tool_outside_the_whitelist_stops_the_run_and_is_not_caught() -> None:
    """허용 목록은 그림이 정한다 — 모델이 벗어나면 **흐름으로 우회하지 않는다**."""
    model = RecordingLlm(replies=[wants("shell_tool", cmd="rm -rf /")])
    engine, run = start(
        process(boundary=True), RunEnv(llm=model, tools={"shell_tool": lambda **kw: "ㅇ"})
    )
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "agent_error"
    assert "허용하지 않은 도구" in str(run.error)
    assert "복구" not in run.variables


def test_a_declared_tool_missing_on_this_pc_is_a_business_failure() -> None:
    """그림은 맞는데 도구가 없다 — 대체 흐름을 쓸 수 있게 경계로 보낸다."""
    model = RecordingLlm(replies=[wants("pdf_text_tool", path="a.pdf")])
    engine, run = start(process(boundary=True), RunEnv(llm=model, tools={}))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


def test_without_a_model_the_task_fails_and_the_boundary_catches_it() -> None:
    engine, run = start(process(boundary=True), RunEnv(llm=NoLlm()))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


def test_a_pc_only_domain_is_not_run_yet() -> None:
    ai = AI.replace('"domain": "doc"', '"domain": "desktop"')
    engine, run = start(process(ai), RunEnv(llm=RecordingLlm(replies=[answer()])))
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "node_kind_unsupported"


# ─────────────────────────── 결과 필드 검증 ───────────────────────────


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ('{"공급사": "한빛"}', "금액 없음"),
        ('{"공급사": "한빛", "금액": "많음"}', "금액: int가 아니라 str"),
        ('{"공급사": "한빛", "금액": true}', "금액: int가 아니라 bool"),
        ("설명이 섞인 글", "JSON이 아니다"),
        ("[1, 2]", "JSON 객체가 아니다"),
    ],
)
def test_a_bad_answer_is_a_business_failure_with_a_reason(text: str, complaint: str) -> None:
    with pytest.raises(AgentError, match=complaint.split(":")[0]) as caught:
        check_results(spec(), text)
    assert caught.value.business is True
    assert complaint in str(caught.value)


def test_a_fenced_json_answer_is_still_read() -> None:
    """모델이 ```json 울타리를 두르는 일이 잦다."""
    found = check_results(spec(), '```json\n{"공급사": "한빛", "금액": 1}\n```')
    assert found == {"공급사": "한빛", "금액": 1}


def test_only_the_declared_result_fields_come_back() -> None:
    """모델이 더 얹어 줘도 **그림이 적은 것만** 변수가 된다."""
    found = check_results(spec(), '{"공급사": "한빛", "금액": 1, "군더더기": "버린다"}')
    assert set(found) == {"공급사", "금액"}


def test_a_wrong_answer_reaches_the_error_boundary() -> None:
    model = RecordingLlm(replies=[answer(공급사="한빛")])
    engine, run = start(process(boundary=True), RunEnv(llm=model))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


# ─────────────────────────── 한도·궤적 ───────────────────────────


def test_the_step_limit_stops_a_loop_that_never_finishes() -> None:
    model = RecordingLlm(replies=[wants("pdf_text_tool", path="a.pdf") for _ in range(10)])
    with pytest.raises(AgentError, match="단계 안에 끝내지 못했다"):
        run_agent(
            spec(limits={"max_steps": 3}),
            llm=model,
            tools={"pdf_text_tool": lambda **kw: "ㅇ"},
        )
    assert len(model.asked) == 3


def test_the_trace_records_what_was_done_for_later_replay() -> None:
    """재생(결정 수행)의 재료다 — 도구 이름·인자·결과와 마지막 답."""
    model = RecordingLlm(
        replies=[wants("pdf_text_tool", path="a.pdf"), answer(공급사="한빛", 금액=1)]
    )
    found = run_agent(spec(), llm=model, tools={"pdf_text_tool": lambda path: f"({path})"})
    assert [(s.tool, s.arguments, s.result) for s in found.trace.steps] == [
        ("pdf_text_tool", {"path": "a.pdf"}, "(a.pdf)")
    ]
    assert json.loads(found.trace.answer)["공급사"] == "한빛"
    assert (found.trace.input_tokens, found.trace.output_tokens) == (220, 42)
    assert found.replayed is False


def test_only_declared_tools_are_offered_to_the_model() -> None:
    """적었지만 이 PC에 없는 도구는 **알려 주지도 않는다** (모델이 괜히 부르지 않게)."""
    assert [t.name for t in tool_specs(spec(), {"pdf_text_tool": str})] == ["pdf_text_tool"]
    assert tool_specs(spec(), {}) == []


def test_business_parameters_go_to_the_model_in_the_prompt() -> None:
    """FX-01의 교훈 — 주소 같은 값은 목표 문장이 아니라 업무 파라미터로 둔다."""
    messages = opening_messages(spec(params={"주소": "https://api.test/fx"}))
    assert "https://api.test/fx" in messages[1]["content"]


# ─────────────────────────── 실행 기록 (C3) ───────────────────────────


def test_the_agent_and_usage_events_carry_no_business_values() -> None:
    model = RecordingLlm(
        replies=[wants("pdf_text_tool", path="비밀문서.pdf"), answer(공급사="한빛상사", 금액=1250000)]
    )
    engine, run = start(process(), RunEnv(llm=model, tools={"pdf_text_tool": lambda path: "비밀 내용"}))
    engine.run_until_blocked(run)

    steps = [e for e in run.log.events if e.kind == "agent"]
    assert [e.data["action"] for e in steps] == ["plan", "tool", "finish"]
    for event in steps:
        assert not [k for k in REQUIRED_DATA_KEYS["agent"] if k not in event.data]

    (usage,) = [e for e in run.log.events if e.kind == "llm_usage"]
    assert usage.data == {"model": "stub-1", "input_tokens": 220, "output_tokens": 42}
    assert run.log.events[-1].data["ai_tasks"] == 1, "run_finished의 셈에 들어간다"

    text = str(run.log.events)
    assert "비밀문서.pdf" not in text and "비밀 내용" not in text and "한빛상사" not in text


# ─────────────────────────── OpenAI 호환 어댑터 (ADR-0027) ───────────────────────────


class FakeModel:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status, self.body = status, body
        self.seen: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
        self.seen.append({"url": url, "json": json, "headers": headers})
        import httpx  # noqa: PLC0415

        return httpx.Response(self.status, json=self.body, request=httpx.Request("POST", url))

    def close(self) -> None:  # pragma: no cover
        pass


CHAT = {
    "model": "local-7b",
    "choices": [{"message": {"role": "assistant", "content": '{"공급사": "한빛"}'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 3},
}


def test_the_openai_compatible_adapter_speaks_the_wire_format() -> None:
    model = FakeModel(body=CHAT)
    found = OpenAiCompatibleLlm(
        base_url="http://llm.test", api_key="sk-stub", model="local-7b", client=model
    ).ask([{"role": "user", "content": "묻는다"}], tools=tool_specs(spec(), {"pdf_text_tool": str}))

    assert found.text == '{"공급사": "한빛"}'
    assert (found.model, found.input_tokens, found.output_tokens) == ("local-7b", 11, 3)
    (sent,) = model.seen
    assert sent["url"] == "http://llm.test/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-stub"
    assert sent["json"]["tools"][0]["function"]["name"] == "pdf_text_tool"


def test_tool_calls_come_back_with_their_arguments_parsed() -> None:
    body = {
        "model": "local-7b",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "pdf_text_tool", "arguments": '{"path": "a.pdf"}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    found = parse_reply(body)
    assert found.wants_tools
    assert found.tool_calls[0].name == "pdf_text_tool"
    assert found.tool_calls[0].arguments == {"path": "a.pdf"}


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)])
def test_model_errors_say_whether_to_try_again(status: int, retryable: bool) -> None:
    model = FakeModel(status=status, body={"error": {"message": "안 된다"}})
    with pytest.raises(LlmError) as caught:
        OpenAiCompatibleLlm(base_url="http://llm.test", api_key="k", model="m", client=model).ask([])
    assert caught.value.retryable is retryable
    assert "안 된다" in str(caught.value)


def test_tool_arguments_that_are_not_json_are_refused() -> None:
    body = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "t", "arguments": "{not json"}}
                    ]
                }
            }
        ]
    }
    with pytest.raises(ValueError, match="도구 인자가 JSON이 아니다"):
        parse_reply(body)


def test_a_model_without_a_key_sends_no_authorization_header() -> None:
    """키가 필요 없는 로컬 모델(Ollama·vLLM)이 그 자리다.

    `Bearer `(빈 값)는 **잘못된 헤더 값**이라 보내는 쪽 라이브러리가 요청 자체를 거부한다
    (`LocalProtocolError`) — 인수 시험에서 모든 AI 태스크가 여기서 막혔다.
    """
    from chaeksas.core.llm import OpenAiCompatibleLlm

    없는키 = OpenAiCompatibleLlm(base_url="http://127.0.0.1:1", api_key="", model="m")
    assert "Authorization" not in 없는키.headers()

    있는키 = OpenAiCompatibleLlm(base_url="http://127.0.0.1:1", api_key="sk-1", model="m")
    assert 있는키.headers()["Authorization"] == "Bearer sk-1"
    assert all(v.isascii() for v in 있는키.headers().values()), "헤더는 ASCII만 (CLAUDE.md §5)"

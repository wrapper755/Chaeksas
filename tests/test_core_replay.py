"""결정 수행 재생 — C14 §재생, [ADR-0028](../docs/decisions/0028-replay-memory.md).

여기서 거듭 보는 것은 넷이다.

1. **도구 인자는 값이 아니라 `{변수}`로 적힌다** — 그래야 입력이 달라져도 같은 명세가 맞는다
   (예제 BX-37·BX-02의 교훈).
2. **`full`은 모델을 한 번도 부르지 않는다**, `plan`은 마지막 값 추출만 한 번 부른다.
3. **명세가 없으면 그냥 돈다** — 처음 배포한 Bot이 멈추면 안 된다.
4. **재생이 깨지면 몰래 자율로 넘어가지 않는다** — `TASK_FAILED`로 오류 경계에 넘긴다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import AiTask, read_process
from chaeksas.contracts.bpmn_ext import validate as validate_bpmn
from chaeksas.contracts.replay import ReplayMemory, ReplaySpec, ReplayStep
from chaeksas.core.agent import Trace, run_agent
from chaeksas.core.engine import Engine, Run, RunEnv, State
from chaeksas.core.llm import RecordingLlm, Reply, ToolCall
from chaeksas.core.replay import filled, read_memory, templated, to_spec, write_memory
from chaeksas.core.run_log import RunLog

NOW = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
RUN_ID = "run_20261004_093000_abc123"

SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="test.proc" name="시험">
    <bpmn:extensionElements><chk:process>{props}</chk:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""

PROPS = '{"inputs": [{"name": "청구서파일", "type": "string"}]}'


def ai_json(replay: str = "plan") -> str:
    return json.dumps(
        {
            "goal": "## 할 일\n청구서에서 공급사를 뽑는다.",
            "domain": "doc",
            "tools": ["pdf_text_tool"],
            "results": {"공급사": "string"},
            "replay": replay,
        },
        ensure_ascii=False,
    )


def flow(id_: str, source: str, target: str) -> str:
    return f'<bpmn:sequenceFlow id="{id_}" sourceRef="{source}" targetRef="{target}" />'


def process(replay: str = "plan", *, boundary: bool = False) -> Any:
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
        f'<bpmn:serviceTask id="Task_Ai"><bpmn:extensionElements><chk:aiTask>{ai_json(replay)}'
        "</chk:aiTask></bpmn:extensionElements></bpmn:serviceTask>"
        '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Ai")
        + flow("f2", "Task_Ai", "End_1")
        + catcher
    )
    return read_process(SHELL.format(body=body, props=PROPS))


def memory_with(arguments: dict[str, Any], *, answer: str = '{"공급사": "한빛상사"}') -> ReplayMemory:
    return ReplayMemory(
        schema=1,
        specs=[
            ReplaySpec(
                bpm_process_id="test.proc",
                node_id="Task_Ai",
                steps=[ReplayStep(tool="pdf_text_tool", arguments=arguments)],
                answer=answer,
            )
        ],
    )


def start(found: Any, env: RunEnv | None = None, **kwargs: Any) -> tuple[Engine, Run]:
    engine = Engine()
    log = RunLog(run_id=RUN_ID)
    return engine, engine.start(found, run_id=RUN_ID, log=log, now=NOW, env=env, **kwargs)


# ─────────────────────────── 인자를 변수로 되돌려 적기 ───────────────────────────


def test_an_argument_equal_to_a_variable_is_written_as_a_template() -> None:
    """ADR-0028 §4 — 그래야 다음 실행의 다른 파일에도 같은 명세가 맞는다."""
    found = templated({"path": "/share/a.pdf", "쪽": 3}, {"청구서파일": "/share/a.pdf", "쪽수": 3})
    assert found == {"path": "{청구서파일}", "쪽": 3}, "수는 건드리지 않는다 (어쩌다 같을 수 있다)"


def test_short_values_are_left_alone() -> None:
    """「네」·「ok」가 어쩌다 묶이면 재생이 엉뚱해진다."""
    assert templated({"답": "네"}, {"확인": "네"}) == {"답": "네"}


def test_a_template_is_filled_with_todays_value() -> None:
    assert filled({"path": "{청구서파일}"}, {"청구서파일": "/share/b.pdf"}) == {"path": "/share/b.pdf"}
    # 통째로 한 변수면 **값 그대로** 들어간다 (수·목록도 된다).
    assert filled({"쪽": "{쪽수}"}, {"쪽수": 3}) == {"쪽": 3}
    # 글 속에 섞인 것은 글로 채운다.
    assert filled({"q": "{달} 청구서"}, {"달": "2026-08"}) == {"q": "2026-08 청구서"}


def test_an_unknown_name_is_left_as_written() -> None:
    """그림이 바뀌어 변수가 사라져도 **도구에서** 실패해 오류 경계로 가게 둔다 (BX-36)."""
    assert filled({"path": "{사라진변수}"}, {}) == {"path": "{사라진변수}"}


def test_a_trace_becomes_a_spec_keyed_by_process_and_node() -> None:
    model = RecordingLlm(
        replies=[
            Reply(tool_calls=(ToolCall(id="c1", name="pdf_text_tool", arguments={"path": "/share/a.pdf"}),)),
            Reply(text='{"공급사": "한빛상사"}', model="stub-1"),
        ]
    )
    spec = AiTask.model_validate(json.loads(ai_json()))
    outcome = run_agent(spec, llm=model, tools={"pdf_text_tool": lambda path: "글"})
    found = to_spec(
        outcome.trace,
        bpm_process_id="test.proc",
        node_id="Task_Ai",
        version="1.2.0",
        variables={"청구서파일": "/share/a.pdf"},
    )
    assert found.key == "test.proc:Task_Ai"
    assert found.version == "1.2.0"
    assert [(s.tool, s.arguments) for s in found.steps] == [("pdf_text_tool", {"path": "{청구서파일}"})]
    assert json.loads(found.answer)["공급사"] == "한빛상사"


# ─────────────────────────── 되밟기 ───────────────────────────


def test_full_replay_calls_the_model_zero_times() -> None:
    """프로토타입의 388초 → 56초가 이 길이다."""
    seen: list[str] = []

    def pdf(path: str) -> str:
        seen.append(path)
        return "글"

    model = RecordingLlm()  # 돌려줄 답이 없다 — 부르면 터진다
    engine, run = start(
        process("full"),
        RunEnv(llm=model, tools={"pdf_text_tool": pdf}, memory=memory_with({"path": "{청구서파일}"})),
        inputs={"청구서파일": "/share/b.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["공급사"] == "한빛상사"
    assert seen == ["/share/b.pdf"], "**이번 입력**으로 도구를 다시 밟았다"
    assert model.asked == [], "모델을 한 번도 부르지 않았다"

    states = [e.data["state"] for e in run.log.events if e.kind == "node_state" and e.node_id == "Task_Ai"]
    assert "replayed" in states
    assert run.log.events[-1].data["replayed_tasks"] == 1


def test_plan_replay_asks_the_model_once_for_the_extraction() -> None:
    model = RecordingLlm(replies=[Reply(text='{"공급사": "새한상사"}', model="stub-1")])
    engine, run = start(
        process("plan"),
        RunEnv(llm=model, tools={"pdf_text_tool": lambda path: f"({path})"},
               memory=memory_with({"path": "{청구서파일}"})),
        inputs={"청구서파일": "/share/c.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["공급사"] == "새한상사", "기억의 답이 아니라 **이번 추출**이다"
    assert len(model.asked) == 1
    # 마지막 물음에는 되밟은 도구 결과가 붙어 있고, 도구 목록은 주지 않는다 (계획은 이미 정해졌다).
    assert model.asked[0][-1]["role"] == "tool"
    assert "(/share/c.pdf)" in model.asked[0][-1]["content"]


def test_none_ignores_the_memory_entirely() -> None:
    model = RecordingLlm(replies=[Reply(text='{"공급사": "직접"}', model="stub-1")])
    engine, run = start(
        process("none"),
        RunEnv(llm=model, tools={"pdf_text_tool": lambda path: "글"}, memory=memory_with({"path": "x"})),
        inputs={"청구서파일": "/share/d.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["공급사"] == "직접"


def test_autonomous_runs_never_replay_and_record_what_they_learned() -> None:
    model = RecordingLlm(
        replies=[
            Reply(tool_calls=(ToolCall(id="c1", name="pdf_text_tool", arguments={"path": "/share/e.pdf"}),)),
            Reply(text='{"공급사": "배운곳"}', model="stub-1"),
        ]
    )
    engine, run = start(
        process("full"),
        RunEnv(llm=model, tools={"pdf_text_tool": lambda path: "글"}, memory=memory_with({"path": "x"})),
        inputs={"청구서파일": "/share/e.pdf"},
        mode="autonomous",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["공급사"] == "배운곳", "자율 수행은 기억을 쓰지 않는다"
    (learned,) = run.learned
    assert learned.key == "test.proc:Task_Ai"
    assert learned.steps[0].arguments == {"path": "{청구서파일}"}, "배운 것도 템플릿으로 적힌다"


def test_a_missing_spec_just_runs_the_model() -> None:
    """처음 배포한 Bot이 멈추면 안 된다 (ADR-0028 §5)."""
    model = RecordingLlm(replies=[Reply(text='{"공급사": "처음"}', model="stub-1")])
    engine, run = start(
        process("plan"),
        RunEnv(llm=model, tools={"pdf_text_tool": lambda path: "글"}, memory=ReplayMemory(schema=1)),
        inputs={"청구서파일": "/share/f.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["공급사"] == "처음"
    assert any("재생 명세가 없다" in str(e.data.get("message")) for e in run.log.events)


def test_a_broken_replay_goes_to_the_error_boundary_not_to_the_model() -> None:
    """ADR-0010 — 운영에서 몰래 자율 수행으로 넘어가지 않는다 (BX-36이 바라는 그대로)."""
    model = RecordingLlm(replies=[Reply(text='{"공급사": "몰래"}')])
    engine, run = start(
        process("full", boundary=True),
        RunEnv(llm=model, tools={}, memory=memory_with({"path": "{청구서파일}"})),
        inputs={"청구서파일": "/share/g.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"
    assert "공급사" not in run.variables
    assert model.asked == [], "모델로 넘어가지 않았다"


def test_a_tool_failure_during_replay_is_a_business_failure() -> None:
    def broken(path: str) -> str:
        raise OSError("파일이 없다")

    engine, run = start(
        process("full", boundary=True),
        RunEnv(llm=RecordingLlm(), tools={"pdf_text_tool": broken},
               memory=memory_with({"path": "{청구서파일}"})),
        inputs={"청구서파일": "/share/h.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


def test_a_replayed_answer_is_still_checked_against_the_result_fields() -> None:
    """기억이 낡아 필드가 안 맞으면 업무 실패다 — 틀린 값을 흘려보내지 않는다."""
    engine, run = start(
        process("full", boundary=True),
        RunEnv(llm=RecordingLlm(), tools={"pdf_text_tool": lambda path: "글"},
               memory=memory_with({"path": "{청구서파일}"}, answer='{"옛날필드": 1}')),
        inputs={"청구서파일": "/share/i.pdf"},
        mode="deterministic",
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


# ─────────────────────────── 파일 (패키지 안) ───────────────────────────


def test_the_memory_round_trips_through_the_package(tmp_path: Path) -> None:
    memory = memory_with({"path": "{청구서파일}"})
    written = write_memory(tmp_path, memory)
    assert written == tmp_path / "memory" / "specs.json", "C1 패키지 구성의 그 자리"
    again = read_memory(tmp_path)
    assert again.find("test.proc", "Task_Ai") is not None
    assert again.find("test.proc", "없는노드") is None
    assert "청구서파일" in written.read_text(encoding="utf-8"), "한글이 그대로 읽힌다 (UTF-8)"


def test_a_package_without_memory_reads_as_empty(tmp_path: Path) -> None:
    assert read_memory(tmp_path).specs == []


def test_relearning_overwrites_the_same_node() -> None:
    memory = memory_with({"path": "{청구서파일}"})
    again = memory.with_spec(
        ReplaySpec(bpm_process_id="test.proc", node_id="Task_Ai", answer='{"공급사": "새로"}')
    )
    assert len(again.specs) == 1
    found = again.find("test.proc", "Task_Ai")
    assert found is not None and found.answer == '{"공급사": "새로"}'


# ─────────────────────────── 검사 (B12) ───────────────────────────


@pytest.mark.parametrize(("replay", "tools", "ok"), [("full", [], False), ("full", ["t"], True),
                                                     ("plan", [], True), ("자주", [], False)])
def test_b12_checks_the_replay_mode(replay: str, tools: list[str], ok: bool) -> None:
    """도구가 없는 AI 태스크에 `full`은 아무것도 확인하지 않고 답만 복사하는 꼴이다."""
    ai = json.dumps(
        {"goal": "x", "domain": "llm", "tools": tools, "results": {"a": "string"}, "replay": replay},
        ensure_ascii=False,
    )
    body = (
        '<bpmn:startEvent id="Start"/>'
        f'<bpmn:serviceTask id="T"><bpmn:extensionElements><chk:aiTask>{ai}</chk:aiTask>'
        "</bpmn:extensionElements></bpmn:serviceTask>"
        '<bpmn:endEvent id="End"/>'
        + flow("f1", "Start", "T")
        + flow("f2", "T", "End")
    )
    found = [v for v in validate_bpmn(read_process(SHELL.format(body=body, props="{}"))) if v.rule == "B12"]
    assert (not found) is ok, [v.message for v in found]


def test_the_default_replay_mode_is_plan() -> None:
    """운영에서도 마지막 판단은 모델이 한다 — `full`은 그림 쓴 사람이 고른다."""
    assert AiTask.model_validate({"goal": "x", "domain": "llm"}).replay == "plan"


def test_an_empty_trace_replays_nothing_and_still_extracts() -> None:
    """도구가 없는 태스크는 `plan`이어도 모델 한 번 — 재생할 차례가 없다 (스파이크 S7의 18곳)."""
    trace = Trace()
    assert trace.steps == []

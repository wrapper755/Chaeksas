"""`web`·`desktop` AI 태스크의 환경 — 확장이 눈과 손을 주고 엔진은 domain으로 묻기만 한다 (ADR-0037).

진짜 Worker·화면 없이 엔진의 몫만 본다: 환경을 묻고, 세션을 열고, 그 도구를 **저절로 허용**하고,
끝나면(실패해도) 닫는다. 환경이 없으면 그림·설치 오류, 환경을 못 열면 업무 실패다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.core.agent import DEFAULT_MAX_STEPS_SCREEN
from chaeksas.core.engine import Engine, Run, RunEnv, State
from chaeksas.core.llm import RecordingLlm, Reply, ToolCall
from chaeksas.core.run_log import RunLog
from chaeksas.extension_api import AgentTool, TaskContext, TaskFailed

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
RUN_ID = "run_20261005_090000_abc123"

SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="test.proc" name="시험">
    <bpmn:extensionElements><chk:process>{{}}</chk:process>{defaults}</bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""

AI = {
    "goal": "## 할 일\n계산기 앱을 연다. `식`을 계산해 결과 표시값을 읽는다.",
    "domain": "desktop",
    "results": {"결과": "number"},
}


def process(ai: dict[str, Any] | None = None, *, defaults: dict[str, Any] | None = None, boundary: bool = False) -> Any:
    catcher = (
        '<bpmn:boundaryEvent id="Bnd_Fail" attachedToRef="Task_Ai"><bpmn:errorEventDefinition/></bpmn:boundaryEvent>'
        '<bpmn:scriptTask id="Task_Recover" scriptFormat="chk-expr"><bpmn:script>복구 = error_code</bpmn:script>'
        '</bpmn:scriptTask><bpmn:endEvent id="End_2"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Bnd_Fail" targetRef="Task_Recover"/>'
        '<bpmn:sequenceFlow id="f4" sourceRef="Task_Recover" targetRef="End_2"/>'
        if boundary
        else ""
    )
    body = (
        '<bpmn:startEvent id="Start_1"/>'
        f'<bpmn:serviceTask id="Task_Ai"><bpmn:extensionElements><chk:aiTask>{json.dumps(ai or AI, ensure_ascii=False)}'
        "</chk:aiTask></bpmn:extensionElements></bpmn:serviceTask>"
        '<bpmn:endEvent id="End_1"/>'
        '<bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Task_Ai"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Task_Ai" targetRef="End_1"/>' + catcher
    )
    extra = f"<chk:defaults>{json.dumps(defaults, ensure_ascii=False)}</chk:defaults>" if defaults else ""
    return read_process(SHELL.format(body=body, defaults=extra))


def start(found: Any, env: RunEnv, **kwargs: Any) -> tuple[Engine, Run]:
    engine = Engine()
    return engine, engine.start(found, run_id=RUN_ID, log=RunLog(run_id=RUN_ID), now=NOW, env=env, **kwargs)


def answer(**fields: Any) -> Reply:
    return Reply(text=json.dumps(fields, ensure_ascii=False), model="stub-1")


def wants(tool: str, **arguments: Any) -> Reply:
    return Reply(tool_calls=(ToolCall(id="c1", name=tool, arguments=arguments),), model="stub-1")


class Session:
    def __init__(self, fails: bool = False) -> None:
        self.calls: list[str] = []
        self.closed = 0
        self.fails = fails

    def tools(self) -> list[AgentTool]:
        def look() -> str:
            self.calls.append("look")
            if self.fails:
                raise RuntimeError("Worker가 죽었다")
            return 'Button "1" aid=key1'

        return [AgentTool(name="desktop_look", description="본다", parameters={"type": "object"}, run=look)]

    def close(self) -> None:
        self.closed += 1


class Environment:
    def __init__(self, session: Session | None = None, refuse: bool = False) -> None:
        self.session = session or Session()
        self.opened: list[TaskContext] = []
        self.refuse = refuse

    def open(self, ctx: TaskContext) -> Session:
        self.opened.append(ctx)
        if self.refuse:
            raise TaskFailed("app_not_running", "계산기 창이 없다")
        return self.session


class Extensions:
    def __init__(self, environment: Environment | None) -> None:
        self._environment = environment
        self.asked: list[str] = []

    def executor(self, task_type: str) -> Any | None:
        return None

    def environment(self, domain: str) -> Any | None:
        self.asked.append(domain)
        return self._environment

    def environment_owner(self, domain: str) -> str | None:
        return "ui-automation"

    def context(self, extension_id: str) -> Any:
        return {"owner": extension_id}


def test_the_environment_tools_are_allowed_without_being_listed_and_the_session_is_closed() -> None:
    environment = Environment()
    model = RecordingLlm(replies=[wants("desktop_look"), answer(결과=408)])
    defaults = {"desktop": {"app": "Calculator"}}
    engine, run = start(
        process(defaults=defaults), RunEnv(llm=model, extensions=Extensions(environment)), inputs={}
    )
    assert engine.run_until_blocked(run) is State.DONE, run.error
    assert run.variables["결과"] == 408
    assert environment.session.calls == ["look"], "`tools[]`에 없어도 환경의 도구는 쓸 수 있다"
    assert environment.session.closed == 1
    opened = environment.opened[0]
    assert opened.properties["desktop"] == {"app": "Calculator"}, "`chk:defaults.desktop`이 환경에 간다"
    assert opened.properties["domain"] == "desktop"
    assert opened.extension == {"owner": "ui-automation"}, "그 환경을 준 확장의 바깥 세상"  # type: ignore[comparison-overlap]


def test_the_task_value_wins_over_the_default_app() -> None:
    environment = Environment()
    ai = {**AI, "desktop": {"app": "MyCalc"}}
    engine, run = start(
        process(ai, defaults={"desktop": {"app": "Calculator"}}),
        RunEnv(llm=RecordingLlm(replies=[answer(결과=1)]), extensions=Extensions(environment)),
    )
    engine.run_until_blocked(run)
    assert environment.opened[0].properties["desktop"] == {"app": "MyCalc"}


def test_without_an_environment_it_is_an_installation_error_not_a_business_failure() -> None:
    engine, run = start(
        process(boundary=True), RunEnv(llm=RecordingLlm(replies=[answer(결과=1)]), extensions=Extensions(None))
    )
    assert engine.run_until_blocked(run) is State.FAILED, "오류 경계로 받지 않는다 (재시도로 안 풀린다)"
    assert run.error is not None and run.error.code == "node_kind_unsupported"


def test_an_environment_that_cannot_open_is_a_business_failure() -> None:
    environment = Environment(refuse=True)
    engine, run = start(
        process(boundary=True), RunEnv(llm=RecordingLlm(replies=[]), extensions=Extensions(environment))
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "app_not_running", "확장의 업무 실패는 오류 경계가 받는다"


def test_the_session_is_closed_even_when_a_tool_fails() -> None:
    environment = Environment(Session(fails=True))
    model = RecordingLlm(replies=[wants("desktop_look"), answer(결과=1)])
    engine, run = start(process(boundary=True), RunEnv(llm=model, extensions=Extensions(environment)))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"
    assert environment.session.closed == 1


def test_screen_tasks_get_a_larger_step_limit_and_defaults_limits_reach_ai_tasks() -> None:
    """화면을 다루면 UI 동작 하나가 한 단계다 (ADR-0037). `chk:defaults.limits`도 AI 태스크에 간다 (C14)."""
    looks = [wants("desktop_look") for _ in range(12)]
    engine, run = start(
        process(), RunEnv(llm=RecordingLlm(replies=[*looks, answer(결과=1)]), extensions=Extensions(Environment()))
    )
    assert engine.run_until_blocked(run) is State.DONE, "8단계를 넘어도 된다"
    assert DEFAULT_MAX_STEPS_SCREEN >= 13

    looks = [wants("desktop_look") for _ in range(6)]
    engine, run = start(
        process(defaults={"limits": {"max_steps": 3}}),
        RunEnv(llm=RecordingLlm(replies=[*looks, answer(결과=1)]), extensions=Extensions(Environment())),
    )
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and "3단계" in str(run.error), "기본값의 한도 3에 걸렸다"

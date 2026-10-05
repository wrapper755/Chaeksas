"""엔진이 확장 태스크를 수행한다 (`chk:task`, C13·ADR-0018, M4 조각 14).

**엔진은 확장을 모른다** — 태스크 종류 이름으로 수행기를 찾아 넘기고 출력만 받는다.
그래서 여기 시험도 가짜 확장 하나로 돈다 (UI 자동화를 들이지 않는다).

거듭 보는 것 다섯.

1. **출력은 변수로** 들어간다.
2. 업무 실패는 **오류 경계가 받는다** — 확장의 `TaskFailed`를 엔진의 것으로 옮긴다.
3. 확장이 없으면 **그림·설치 오류**다 (경계로 받지 않는다) — 재시도로 풀리지 않는다.
4. 수행기가 받는 것은 C14 속성과 **키 참조 이름**이다 (값이 아니다, ADR-0013).
5. **값은 기록에 남지 않는다** (원칙 6).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.core.engine import Engine, RunEnv, State
from chaeksas.core.run_log import RunLog
from chaeksas.extension_api import TaskContext, TaskFailed, TaskOutcome

RUN = "run_20261005_120000_abcdef"

PROCESS = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1"
                  targetNamespace="urn:chaeksas:example">
  <bpmn:process id="Proc_ext" name="확장 태스크" isExecutable="true">
    <bpmn:extensionElements>
      <chk:process>{"run_location": "pc", "service_keys": {"demo": "demo-key"}}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start" />
    <bpmn:serviceTask id="Task_Ext" name="확장 태스크">
      <bpmn:extensionElements>
        <chk:task type="demo_task" extension="demo">{"page_id": "p", "steps": []}</chk:task>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Task_Ext" />
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Ext" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
"""

#: 오류 경계가 붙은 같은 그림 — 업무 실패가 **경계로 간다**는 것을 보려고.
WITH_BOUNDARY = PROCESS.replace(
    "<bpmn:endEvent id=\"End\" />",
    """<bpmn:endEvent id="End" />
    <bpmn:boundaryEvent id="Boundary" attachedToRef="Task_Ext">
      <bpmn:errorEventDefinition id="err" />
    </bpmn:boundaryEvent>
    <bpmn:endEvent id="End_error" />
    <bpmn:sequenceFlow id="f3" sourceRef="Boundary" targetRef="End_error" />""",
)


class FakeExecutor:
    """`extension_api.TaskExecutor` — 받은 것을 남기고 정해진 답을 준다."""

    def __init__(self, *, outputs: dict[str, Any] | None = None, fail: Exception | None = None) -> None:
        self.outputs = outputs or {}
        self.fail = fail
        self.seen: list[TaskContext] = []

    def execute(self, ctx: TaskContext) -> TaskOutcome:
        self.seen.append(ctx)
        if self.fail is not None:
            raise self.fail
        return TaskOutcome(outputs=self.outputs)


class Host:
    """`core.run_state.ExtensionTasks` — 태스크 종류로 수행기를 찾아 준다."""

    def __init__(self, executors: dict[str, Any]) -> None:
        self.executors = executors

    def executor(self, task_type: str) -> Any | None:
        return self.executors.get(task_type)


def run_it(tmp_path: Path, xml: str, host: Any, **variables: Any) -> Any:
    engine = Engine()
    process = read_process(xml)
    run = engine.start(
        process,
        run_id=RUN,
        log=RunLog(run_id=RUN, path=tmp_path / "run.jsonl"),
        env=RunEnv(extensions=host),
        inputs=variables,
    )
    for _ in range(50):
        if run.state in (State.DONE, State.FAILED) or engine.blocked(run):
            break
        engine.step(run)
    return run


def events(tmp_path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (tmp_path / "run.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ─────────────────────────── 수행 ───────────────────────────


def test_defaults_web_and_desktop_reach_the_task_and_the_task_wins(tmp_path: Path) -> None:
    """`chk:defaults`의 `web`·`desktop`은 확장 태스크 속성의 기본값이다 — **태스크에 적은 값이 이긴다**
    (C14, ADR-0033). UI 태스크가 띄울 앱 이름을 이렇게 받는다."""
    with_defaults = PROCESS.replace(
        '<chk:process>{"run_location": "pc", "service_keys": {"demo": "demo-key"}}</chk:process>',
        '<chk:process>{"run_location": "pc", "service_keys": {"demo": "demo-key"}}</chk:process>'
        '<chk:defaults>{"desktop": {"app": "ERP Client"}, "web": {"profile": "업무"}}</chk:defaults>',
    ).replace('{"page_id": "p", "steps": []}', '{"page_id": "p", "steps": [], "web": {"profile": "태스크"}}')
    executor = FakeExecutor()
    run = run_it(tmp_path, with_defaults, Host({"demo_task": executor}))
    assert run.state == State.DONE
    seen = executor.seen[0].properties
    assert seen["desktop"] == {"app": "ERP Client"}
    assert seen["web"] == {"profile": "태스크"}
    assert seen["page_id"] == "p"



def test_the_outputs_become_variables(tmp_path: Path) -> None:
    executor = FakeExecutor(outputs={"제출메시지": "접수되었습니다", "번호": 7})
    run = run_it(tmp_path, PROCESS, Host({"demo_task": executor}))
    assert run.state == State.DONE
    assert run.variables["제출메시지"] == "접수되었습니다"
    assert run.variables["번호"] == 7


def test_the_executor_sees_the_contract_shape(tmp_path: Path) -> None:
    """C14 속성과 **키 참조 이름**이 간다 — 값은 확장이 호스트에게 묻는다 (ADR-0013)."""
    executor = FakeExecutor()
    run_it(tmp_path, PROCESS, Host({"demo_task": executor}))
    seen = executor.seen[0]
    assert seen.properties == {"page_id": "p", "steps": []}
    assert seen.run_id == RUN and seen.node_id == "Task_Ext"
    assert seen.business_key == f"{RUN}:Task_Ext:1:1", "C10 세션을 잇는 키다"
    assert seen.key_ref == "demo-key", "BPM 프로세스의 키 참조를 물려받는다"
    assert seen.mode == "autonomous" or seen.mode == "deterministic"
    assert seen.run_location == "pc"


def test_the_task_properties_are_not_the_values(tmp_path: Path) -> None:
    """**비밀은 가지 않는다** — 참조 이름뿐이다."""
    executor = FakeExecutor()
    run_it(tmp_path, PROCESS, Host({"demo_task": executor}))
    assert "key_ref" in executor.seen[0].__dict__ or executor.seen[0].key_ref
    assert "chk_svc_" not in json.dumps(executor.seen[0].properties, ensure_ascii=False)


# ─────────────────────────── 실패 ───────────────────────────


def test_a_business_failure_goes_to_the_error_boundary(tmp_path: Path) -> None:
    """확장의 `TaskFailed`를 **엔진의 것으로 옮긴다** — 그대로 두면 경계가 못 받는다."""
    executor = FakeExecutor(fail=TaskFailed("screen_changed", "화면이 바뀌었습니다"))
    run = run_it(tmp_path, WITH_BOUNDARY, Host({"demo_task": executor}))
    assert run.state == State.DONE, "경계가 받아 다른 길로 끝났다"
    assert run.variables.get("error_code") == "screen_changed"


def test_a_missing_extension_is_a_setup_error(tmp_path: Path) -> None:
    """**경계로 받지 않는다** — 그 PC에 확장이 없는 것이고 재시도로 풀리지 않는다."""
    run = run_it(tmp_path, WITH_BOUNDARY, Host({}))
    assert run.state == State.FAILED
    finished = [one for one in events(tmp_path) if one["kind"] == "run_finished"]
    assert finished and finished[-1]["data"]["status"] == "failed"
    node = [one for one in events(tmp_path) if one["kind"] == "node_state"][-1]
    assert node["data"]["error_code"] == "node_kind_unsupported", "경계가 받을 실패가 아니다"


def test_the_default_env_cannot_run_extension_tasks(tmp_path: Path) -> None:
    """기본값은 **아무 확장도 없다** — 조용히 넘어가지 않는다 (RunEnv의 규칙)."""
    engine = Engine()
    run = engine.start(
        read_process(PROCESS), run_id=RUN, log=RunLog(run_id=RUN, path=tmp_path / "run.jsonl")
    )
    for _ in range(10):
        if run.state in (State.DONE, State.FAILED):
            break
        engine.step(run)
    assert run.state == State.FAILED


# ─────────────────────────── 기록 (원칙 6) ───────────────────────────


def test_the_values_do_not_reach_the_log(tmp_path: Path) -> None:
    executor = FakeExecutor(outputs={"연락처": "010-1234-5678"})
    run_it(tmp_path, PROCESS, Host({"demo_task": executor}))
    raw = (tmp_path / "run.jsonl").read_text(encoding="utf-8")
    assert "010-1234-5678" not in raw, "업무 값은 기록에 남지 않는다 (원칙 6)"
    assert "demo_task" in raw, "무엇을 했는지는 남는다"


@pytest.mark.parametrize("mode", ["autonomous", "deterministic"])
def test_both_modes_reach_the_executor(tmp_path: Path, mode: str) -> None:
    """**모드를 바꾸지 않는다** (계약 원칙 7) — 받은 그대로 넘긴다."""
    executor = FakeExecutor()
    engine = Engine()
    run = engine.start(
        read_process(PROCESS),
        run_id=RUN,
        log=RunLog(run_id=RUN, path=tmp_path / "run.jsonl"),
        env=RunEnv(extensions=Host({"demo_task": executor})),
        mode=mode,
    )
    for _ in range(10):
        if run.state in (State.DONE, State.FAILED):
            break
        engine.step(run)
    assert executor.seen[0].mode == mode

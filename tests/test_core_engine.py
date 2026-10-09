"""BPMN 실행 엔진 뼈대 (M3 조각 2) — 시작·종료·스크립트·배타 게이트웨이·결재.

C3 이벤트가 **계약대로** 남는지도 함께 본다 (`kind`·필수 `data` 키·`seq`·값이 안 새는지).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.dmn import read_decisions
from chaeksas.contracts.events import REQUIRED_DATA_KEYS
from chaeksas.core.engine import DECISION_KEY, Engine, EngineError, Run, RunEnv, State, new_run_id
from chaeksas.core.files import Workspace
from chaeksas.core.llm import Reply
from chaeksas.core.run_log import RunLog, sanitize
from chaeksas.core.senders import RecordingSender
from chaeksas.core.services import RecordingServiceCaller

NOW = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)

#: 쓰기 쉬운 BPMN 뼈대. `{body}`에 노드·흐름을 끼운다.
SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="{process_id}" name="시험">
    <bpmn:extensionElements><chk:process>{process_props}</chk:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""


def make(body: str, *, process_props: str = "{}", process_id: str = "test.proc") -> Any:
    return read_process(SHELL.format(body=body, process_props=process_props, process_id=process_id))


def flow(id_: str, source: str, target: str, condition: str | None = None) -> str:
    inner = f"<bpmn:conditionExpression>{condition}</bpmn:conditionExpression>" if condition else ""
    return f'<bpmn:sequenceFlow id="{id_}" sourceRef="{source}" targetRef="{target}">{inner}</bpmn:sequenceFlow>'


def script(id_: str, body: str, name: str = "스크립트") -> str:
    return (
        f'<bpmn:scriptTask id="{id_}" name="{name}" scriptFormat="chk-expr">'
        f"<bpmn:script>{body}</bpmn:script></bpmn:scriptTask>"
    )


#: C3가 `run_id`의 모양을 정해 둔다 (`^(run|test)_\d{8}_\d{6}_[0-9a-f]{6}$`).
RUN_ID = "run_20261004_093000_abc123"


def started(run_id: str = RUN_ID, path: Path | None = None) -> RunLog:
    return RunLog(run_id=run_id, path=path)


def start(process: Any, log: RunLog | None = None, **kwargs: Any) -> tuple[Engine, Run]:
    engine = Engine()
    found = log or started()
    return engine, engine.start(process, run_id=found.run_id, log=found, now=NOW, **kwargs)


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_a_straight_line_runs_to_the_end() -> None:
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Set", "결과 = 1 + 1")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Set")
        + flow("f2", "Task_Set", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["결과"] == 2

    kinds = [e.kind for e in run.log.events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    assert [e.seq for e in run.log.events] == list(range(1, len(run.log.events) + 1))


def test_the_engine_gives_the_builtin_variables() -> None:
    """C14 §9 — `오늘`·`지금`·`run_id`는 선언하지 않아도 쓸 수 있다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Set", "경로 = '일일/' + 오늘 + '.md'\n이번것 = run_id")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Set")
        + flow("f2", "Task_Set", "End_1")
    )
    engine, run = start(process, started(run_id="run_20261004_093000_abcdef"))
    engine.run_until_blocked(run)
    assert run.variables["경로"] == "일일/2026-10-04.md"
    assert run.variables["이번것"] == "run_20261004_093000_abcdef"


def test_declared_inputs_fall_back_to_default_then_none() -> None:
    """C14 §6 — 주지 않았고 기본값도 없으면 `None`이라 `or`로 메울 수 있다."""
    props = (
        '{"inputs": [{"name": "대상월", "type": "string"},'
        ' {"name": "폴더", "type": "string", "default": "/share"}]}'
    )
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Set", "대상월 = 대상월 or 지난달()\n경로 = 폴더 + '/' + 대상월")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Set")
        + flow("f2", "Task_Set", "End_1"),
        process_props=props,
    )
    engine, run = start(process)
    engine.run_until_blocked(run)
    assert run.variables["경로"] == "/share/2026-09"


def test_a_given_input_wins() -> None:
    props = '{"inputs": [{"name": "대상월", "type": "string"}]}'
    process = make(
        '<bpmn:startEvent id="Start_1"/><bpmn:endEvent id="End_1"/>' + flow("f1", "Start_1", "End_1"),
        process_props=props,
    )
    engine, run = start(process, inputs={"대상월": "2026-01"})
    assert run.variables["대상월"] == "2026-01"
    assert engine.run_until_blocked(run) is State.DONE


def test_an_undeclared_input_is_refused() -> None:
    """이름을 잘못 적은 입력을 조용히 흘리면 식이 `None`으로 돌아 엉뚱한 값이 나온다."""
    process = make('<bpmn:startEvent id="Start_1"/><bpmn:endEvent id="End_1"/>' + flow("f1", "Start_1", "End_1"))
    with pytest.raises(EngineError, match="선언하지 않은 입력"):
        start(process, inputs={"없는입력": 1})


def test_a_required_input_must_be_given() -> None:
    props = '{"inputs": [{"name": "신청번호", "type": "string", "required": true}]}'
    process = make(
        '<bpmn:startEvent id="Start_1"/><bpmn:endEvent id="End_1"/>' + flow("f1", "Start_1", "End_1"),
        process_props=props,
    )
    with pytest.raises(EngineError, match="필요하다"):
        start(process)


# ─────────────────────────── 배타 게이트웨이 ───────────────────────────


def gateway_process() -> Any:
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Count", "보류건수 = len(보류)")
        + '<bpmn:exclusiveGateway id="Gw_HasHold" default="f_no"/>'
        + script("Task_Hold", "길 = '보류'")
        + script("Task_Pay", "길 = '지급'")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Task_Count")
        + flow("f2", "Task_Count", "Gw_HasHold")
        + flow("f_yes", "Gw_HasHold", "Task_Hold", "보류건수 &gt; 0")
        + flow("f_no", "Gw_HasHold", "Task_Pay")
        + flow("f3", "Task_Hold", "End_1")
        + flow("f4", "Task_Pay", "End_2"),
        process_props='{"inputs": [{"name": "보류", "type": "list", "default": []}]}',
    )


def test_a_true_condition_takes_that_branch() -> None:
    engine, run = start(gateway_process(), inputs={"보류": [{"id": "a"}]})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["길"] == "보류"


def test_all_false_takes_the_default_flow() -> None:
    engine, run = start(gateway_process(), inputs={"보류": []})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["길"] == "지급"


def test_no_matching_flow_and_no_default_fails_with_a_reason() -> None:
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:exclusiveGateway id="Gw_1"/>'
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Gw_1")
        + flow("f2", "Gw_1", "End_1", "거짓")
    )
    engine, run = start(process, inputs=None)
    run.variables["거짓"] = False
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "no_matching_flow"
    assert run.error.node_id == "Gw_1"


# ─────────────────────────── 실패 ───────────────────────────


def test_a_bad_expression_fails_the_run_with_the_node() -> None:
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Bad", "값 = 없는변수 + 1")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Bad")
        + flow("f2", "Task_Bad", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None
    assert run.error.code == "expr_error" and run.error.node_id == "Task_Bad"

    failed = [e for e in run.log.events if e.data.get("state") == "failed"]
    assert len(failed) == 1 and failed[0].node_id == "Task_Bad"
    finished = run.log.events[-1]
    assert finished.kind == "run_finished" and finished.data["status"] == "failed"
    assert finished.data["error_code"] == "expr_error"


def test_an_unsupported_node_stops_instead_of_skipping() -> None:
    """schema 1에서 쓰지 않는 노드를 만나면 **조용히 지나가지 않는다** (잘못된 결과보다 멈추는 게 낫다)."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:transaction id="Tx_1" name="트랜잭션"/>'
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Tx_1")
        + flow("f2", "Tx_1", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "node_kind_unsupported"


def test_a_service_task_without_any_chk_property_says_so() -> None:
    """`serviceTask` 하나에 네 가지가 올라탄다 — 아무것도 없으면 무엇인지 알 수 없다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:serviceTask id="Task_Call" name="서비스"/>'
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Call")
        + flow("f2", "Task_Call", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "task_empty"


def test_a_process_without_a_start_is_refused() -> None:
    with pytest.raises(EngineError, match="시작 이벤트가 없다"):
        start(make('<bpmn:endEvent id="End_1"/>'))


def test_two_outgoing_flows_fork_into_two_tokens() -> None:
    """나가는 흐름이 여럿이면 갈라진다 (병렬 분기). 둘 다 돌고 나서 끝난다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_A", "가 = 1")
        + script("Task_B", "나 = 2")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Task_A")
        + flow("f2", "Start_1", "Task_B")
        + flow("f3", "Task_A", "End_1")
        + flow("f4", "Task_B", "End_2")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert (run.variables["가"], run.variables["나"]) == (1, 2)


# ─────────────────────────── 결재·확인 ───────────────────────────


APPROVAL_PROPS = (
    '{"title": "보류건 확인", "description": "승인하면 지급합니다.", "show": ["보류건수"],'
    ' "fields": [{"key": "진행", "label": "어떻게", "type": "choice",'
    ' "choices": ["지급", "보류"], "required": true},'
    ' {"key": "의견", "label": "의견", "type": "text"}]}'
)


def approval_process(kind: str = "userTask", props: str = APPROVAL_PROPS) -> Any:
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Count", "보류건수 = 2")
        + f'<bpmn:{kind} id="Approve_Hold"><bpmn:extensionElements>'
        + f"<chk:approval>{props}</chk:approval></bpmn:extensionElements></bpmn:{kind}>"
        + script("Task_After", "결정 = 진행")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Count")
        + flow("f2", "Task_Count", "Approve_Hold")
        + flow("f3", "Approve_Hold", "Task_After")
        + flow("f4", "Task_After", "End_1")
    )


def test_an_approval_waits_and_keeps_the_slot() -> None:
    """ADR-0014 — 기다리는 동안에도 실행 자리를 쥔다 (엔진은 `WAITING`으로 멈춰 있다)."""
    engine, run = start(approval_process())
    assert engine.run_until_blocked(run) is State.WAITING
    assert run.pending is not None
    assert run.pending.request_id == f"apr_{run.run_id}_Approve_Hold_1"
    assert run.pending.layer == "approval"
    assert run.pending.title == "보류건 확인"
    # 「표시 변수」만 담는다 (C6 `review`).
    assert run.pending.review == {"보류건수": 2}

    requested = next(e for e in run.log.events if e.kind == "human_requested")
    assert requested.data["layer"] == "approval"
    assert requested.data["where"] == "field"
    # 기다리는 중에는 `node_state: waiting`만 남긴다 (C3 — `run_waiting`은 서버만).
    states = {e.data.get("state") for e in run.log.events if e.kind == "node_state"}
    assert states == {"started", "completed", "waiting"}
    assert not any(e.kind == "run_waiting" for e in run.log.events)

    # 더 돌려도 기다린 자리에 그대로 있다.
    assert engine.step(run) is State.WAITING


def test_an_answer_becomes_variables_and_the_run_continues() -> None:
    engine, run = start(approval_process())
    engine.run_until_blocked(run)
    assert run.pending is not None

    engine.answer(run, run.pending.request_id, {"진행": "보류", "의견": "다음 달에"}, answered_by="홍길동")
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["결정"] == "보류"

    answered = next(e for e in run.log.events if e.kind == "human_answered")
    assert answered.data["answered_by"] == "홍길동"
    # **답 값은 기록에 없다** (C3 `human_answered`는 값이 없다).
    assert "진행" not in str(answered.data) and "다음 달에" not in str(run.log.events)


def test_a_manual_task_is_a_confirmation() -> None:
    """`manualTask`는 화면에 「확인」으로 보인다 (C14)."""
    engine, run = start(approval_process(kind="manualTask"))
    engine.run_until_blocked(run)
    assert run.pending is not None and run.pending.layer == "confirmation"


def test_an_approval_without_a_form_takes_a_decision() -> None:
    """C6 — 폼이 없으면 「승인 / 반려」 두 단추다."""
    engine, run = start(approval_process(props='{"title": "승인해 주세요"}'))
    engine.run_until_blocked(run)
    assert run.pending is not None and run.pending.form is None

    with pytest.raises(EngineError, match="빠진 칸이 있다: decision"):
        engine.answer(run, run.pending.request_id, {"엉뚱한": 1}, answered_by="홍길동")
    engine.answer(run, run.pending.request_id, {DECISION_KEY: "approve", "진행": "지급"}, answered_by="홍길동")
    assert engine.run_until_blocked(run) is State.DONE


def test_a_missing_required_field_is_refused() -> None:
    engine, run = start(approval_process())
    engine.run_until_blocked(run)
    assert run.pending is not None
    with pytest.raises(EngineError, match="빠진 칸이 있다: 진행"):
        engine.answer(run, run.pending.request_id, {"의견": "없음"}, answered_by="홍길동")
    assert run.state is State.WAITING, "거부했으면 그대로 기다린다"


def test_answering_the_wrong_request_is_refused() -> None:
    engine, run = start(approval_process())
    engine.run_until_blocked(run)
    with pytest.raises(EngineError, match="기다리는 요청이 아니다"):
        engine.answer(run, "apr_엉뚱한것", {"진행": "지급"}, answered_by="홍길동")


def test_a_timeout_fails_the_run() -> None:
    engine, run = start(approval_process())
    engine.run_until_blocked(run)
    assert run.pending is not None
    assert engine.timeout(run, run.pending.request_id) is State.FAILED
    assert [e.kind for e in run.log.events if e.kind == "human_timeout"] == ["human_timeout"]
    assert run.error is not None and run.error.code == "human_timeout"


def test_the_request_id_matches_the_contract_shape() -> None:
    """C6 `request_id_for` — 답이 엉뚱한 노드로 돌아가지 않게 모양이 정해져 있다."""
    from chaeksas.contracts.approvals import ApprovalCreateRequest  # noqa: PLC0415

    engine, run = start(approval_process())
    engine.run_until_blocked(run)
    assert run.pending is not None
    # 이 모양이어야 C6 요청을 만들 수 있다 (모델이 `request_id`를 검사한다).
    ApprovalCreateRequest(
        schema=1,
        request_id=run.pending.request_id,
        layer="approval",
        run_id=run.run_id,
        node_id=run.pending.node_id,
        node_instance=run.pending.node_instance,
        bpm_process_id=run.process.id,
        version="1.0.0",
        title=run.pending.title,
    )


# ─────────────────────────── 실행 기록 (C3) ───────────────────────────


def test_events_match_the_contract_required_keys() -> None:
    engine, run = start(approval_process())
    engine.run_until_blocked(run)
    assert run.pending is not None
    engine.answer(run, run.pending.request_id, {"진행": "지급"}, answered_by="홍길동")
    engine.run_until_blocked(run)

    for event in run.log.events:
        needed = REQUIRED_DATA_KEYS.get(event.kind)
        if needed is None:
            continue
        missing = [key for key in needed if key not in event.data]
        assert not missing, f"{event.kind}에 {missing}이 없다"


def test_the_log_is_written_as_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "runs" / f"{RUN_ID}.jsonl"
    engine, run = start(
        make(
            '<bpmn:startEvent id="Start_1"/>'
            + script("Task_Set", "값 = 1")
            + '<bpmn:endEvent id="End_1"/>'
            + flow("f1", "Start_1", "Task_Set")
            + flow("f2", "Task_Set", "End_1")
        ),
        started(path=path),
    )
    engine.run_until_blocked(run)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(run.log.events)
    again = list(RunLog.read(path))
    assert [e.kind for e in again] == [e.kind for e in run.log.events]


def test_business_values_do_not_reach_the_log() -> None:
    """계약 원칙 6 — 목록·사전은 **개수만**, 긴 문자열은 잘라서 남는다."""
    found = sanitize({"목록": [{"비밀": "값"}] * 3, "글": "가" * 500, "수": 7, "없음": None})
    assert found["목록"] == {"개수": 3}
    assert "비밀" not in str(found)
    assert len(found["글"]) <= 201 and found["글"].endswith("…")
    assert found["수"] == 7 and found["없음"] is None


def test_unsent_counting_for_the_heartbeat() -> None:
    """C4 `unsent_events` — Center가 확인한 데까지만 보낸 것으로 센다."""
    log = started()
    log.emit("log", level="info", message="가")
    log.emit("log", level="info", message="나")
    assert log.unsent_count == 2
    log.mark_sent(1)
    assert log.unsent_count == 1
    assert [e.seq for e in log.unsent()] == [2]


def test_run_id_shape() -> None:
    assert new_run_id(now=NOW).startswith("run_20261004_093000_")
    assert new_run_id(now=NOW, test=True).startswith("test_20261004_093000_")


# ─────────────────────── 업무 예제로 한 바퀴 ───────────────────────


EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


def test_a_real_example_stops_where_the_adr_says_it_will() -> None:
    """실제 예제(bx01)를 돌려 **어디까지 가는지** 본다.

    예전에는 첫 스크립트의 `파일목록()`에서 멈췄다 (ADR-0025가 식에서 뺀 함수다). 조각 3f가
    그것을 **파일 목록 태스크**로 옮겼으니 이제는 더 간다 — 스크립트를 지나 `Task_Collect`까지
    가고, 거기서 **실행하는 쪽이 폴더를 주지 않아서** 멈춘다.

    그 차이가 중요하다. 전자는 **그림이 틀린 것**이고 후자는 **환경이 빈 것**이다. 둘 다
    `EngineError`이지만 고칠 자리가 다르다 (ADR-0026 — 기본 `RunEnv`는 아무것도 못 한다).
    """
    process = read_process((EXAMPLE / "bx01_invoice_reconciliation.bpmn").read_text(encoding="utf-8"))
    engine, run = start(process, inputs={"청구서폴더": "/share/invoices"})
    assert engine.run_until_blocked(run) is State.FAILED

    assert run.error is not None
    assert run.error.code == "path_denied"
    assert run.error.node_id == "Task_Collect"
    # 거기까지 가면서 시작은 돌았고, 기록은 계약 모양이다.
    assert run.log.events[0].kind == "run_started"
    assert run.log.events[0].data["bpm_process_id"] == process.id
    assert run.log.events[-1].data["status"] == "failed"


#: 선언한 입력에 넣어 줄 자리 값 (예제를 돌려 보려면 필수 입력이 있어야 한다).
DUMMY_BY_TYPE: dict[str, Any] = {
    "string": "시험값",
    "date": "2026-10-04",
    "int": 1,
    "number": 1,
    "bool": True,
    "list": [],
    "dict": {},
}


def dummy_inputs(process: Any) -> dict[str, Any]:
    return {decl.name: DUMMY_BY_TYPE.get(decl.type, "시험값") for decl in process.info.inputs}


def example_service_outputs() -> dict[str, dict[str, Any]]:
    """예제가 서비스 앱에서 **받으려는 필드**에 자리 값을 채워 둔다.

    진짜 앱은 M5의 `samples/mock-*`다. 여기서는 「엔진이 어디까지 가는가」만 보므로, 각
    `chk:serviceCall.output`이 가리키는 응답 필드를 그대로 돌려주는 시늉만 한다.
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(EXAMPLE.glob("*.bpmn")):
        for node in read_process(path.read_text(encoding="utf-8")).all_nodes():
            call = node.prop("serviceCall")
            if call is not None:
                found = out.setdefault(f"{call.app_id}/{call.operation}", {})
                found.update(dict.fromkeys(call.output.values(), "시험값"))
    return out


#: 「다음 필드를 가진 JSON 객체 하나: 공급사(string), 금액(int)」에서 이름·타입을 뽑는다.
WANTED = re.compile(r"JSON 객체 하나: (.+)$", re.M)
PLACEHOLDER: dict[str, Any] = {
    "string": "시험값", "date": "2026-10-04", "int": 1, "number": 1.0,
    "bool": True, "list": [], "dict": {},
}


class FieldEchoLlm:
    """시험용 모델 — **물음에 적힌 결과 필드대로** 자리 값을 채운 JSON을 돌려준다.

    진짜 모델 대신 「형식만 맞는 답」을 내준다. 엔진이 어디까지 가는지 보는 눈금용이라
    값의 뜻은 보지 않는다 (업무 예제의 인수 시험은 조각 3f다).
    """

    def ask(self, messages: Any, *, tools: Any = (), timeout_s: float | None = None) -> Reply:
        found = WANTED.search(str(messages[-1].get("content", "")))
        fields: dict[str, Any] = {}
        for part in (found.group(1) if found else "").split(", "):
            name, _, kind = part.partition("(")
            if name.strip() and name.strip() != "없음":
                fields[name.strip()] = PLACEHOLDER.get(kind.rstrip(")"), "시험값")
        return Reply(text=json.dumps(fields, ensure_ascii=False), model="stub", input_tokens=10, output_tokens=5)


def example_env(tmp_path: Path) -> RunEnv:
    """예제를 돌릴 바깥 세계 — 임시 출력 폴더, 시험용 어댑터들, 예제의 DMN·정의 전부."""
    outputs = tmp_path / "outputs"
    outputs.mkdir(exist_ok=True)
    decisions: dict[str, Any] = {}
    for path in sorted(EXAMPLE.glob("*.dmn")):
        decisions.update(read_decisions(path.read_text(encoding="utf-8")))
    # 호출(`callActivity`)이 찾을 다른 BPM 프로세스 — 예제 묶음이 한 패키지인 셈 치고 모은다.
    processes: dict[str, Any] = {}
    for path in sorted(EXAMPLE.glob("*.bpmn")):
        found = read_process(path.read_text(encoding="utf-8"))
        processes[found.id] = found
    return RunEnv(
        processes=processes,
        workspace=Workspace(output_dir=outputs, readable=(outputs,)),
        sender=RecordingSender(),
        decisions=decisions,
        services=RecordingServiceCaller(outputs=dict(example_service_outputs())),
        llm=FieldEchoLlm(),
    )


def test_no_example_breaks_the_engine_in_an_unexpected_way(tmp_path: Path) -> None:
    """예제 50개를 모두 돌려 본다 (선언한 입력에는 자리 값을 넣는다).

    중요한 것은 「멈추는 이유가 우리가 아는 것인가」다 — 모르는 이유로 터지면 엔진 쪽 구멍이다.
    **이 수가 조각마다 올라가는 눈금이다** (조각 2: 끝 3·대기 1 → 3b: 끝 11·대기 2 →
    3c: 끝 19·대기 6 → 3d: 끝 20·대기 9 → 3f: 끝 23·대기 9 — 합치면 50개 중 **32개**가
    사람이나 끝까지 간다).

    남은 18개는 둘 중 하나다. **UI 자동화(M4)** 5개, 그리고 **자리 값 탓** 13개 — 선언만 보고
    넣는 `"시험값"`으로는 점 표기·반복·기간이 성립하지 않는다. 진짜 입력은 Studio 시험 실행의
    케이스에서 온다 (인수 시험).
    """
    known = {
        "node_kind_unsupported",  # UI 태스크·`desktop` AI 태스크 (M4)
        "no_matching_flow",  # 자리 값으로는 어느 조건도 참이 아닐 수 있다
        # 아래 넷은 **자리 값 탓**이다 (예제가 아니라).
        "expr_error",  # 자리 값이 문자열이라 점 표기·`표를사전`·`기간`이 성립하지 않는다
        "loop_not_a_list",  # 자리 값이 문자열이라 반복할 목록이 아니다
        "timer_unreadable",  # 기한 변수에 자리 값(`시험값`)이 들어갔다
        "TASK_FAILED",  # 자리 값 폴더가 없다·호출한 BPM 프로세스가 자리 값 때문에 실패했다
    }
    env = example_env(tmp_path)
    reasons: dict[str, int] = {}
    done: list[str] = []
    waiting: list[str] = []
    for path in sorted(EXAMPLE.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        log = started()
        engine = Engine()
        try:
            run = engine.start(
                process, run_id=log.run_id, log=log, now=NOW, env=env, inputs=dummy_inputs(process)
            )
        except EngineError as e:
            reasons[e.code] = reasons.get(e.code, 0) + 1
            assert e.code in known, f"{path.name}: {e}"
            continue

        state = engine.run_until_blocked(run)
        if state is State.DONE:
            done.append(path.name)
        elif state is State.WAITING:
            waiting.append(path.name)
        else:
            assert run.error is not None, path.name
            reasons[run.error.code] = reasons.get(run.error.code, 0) + 1
            assert run.error.code in known, f"{path.name}: {run.error}"

    assert len(done) + len(waiting) + sum(reasons.values()) == 50
    # 끝까지 가는 것·사람을 기다리는 것 — **다음 조각이 이 목록을 늘린다. 늘면 여기를 고쳐 적는다.**
    assert done == [
        "bx02_morning_fx_report.bpmn",  # API AI 태스크 + 통화마다 범위 점검 (3f)
        "bx03_expense_approval.bpmn",  # 메시지 시작 + 타이머 경계 + 웹훅 (3f)
        "bx06_bulk_credit_check.bpmn",  # 규칙(DMN) + 반복 + xlsx 출력 + 메일
        "bx07_corporate_card_review.bpmn",  # AI 분류 반복 + DMN COLLECT + xlsx (3f)
        "bx12_shipping_fee.bpmn",  # 규칙(DMN) 공유 BPM 프로세스
        "bx17_erp_po_entry.bpmn",
        "bx22_offboarding_access.bpmn",  # 서비스 앱 + 반복
        "bx31_request_triage.bpmn",  # AI 태스크 + 메일
        "bx36_legacy_migration.bpmn",  # 서비스 앱
        "bx37_clause_review.bpmn",  # 같은 AI 태스크를 한 실행에서 세 번
        "fx01_api_call.bpmn",  # AI 태스크 (`domain: api`) + 업무 파라미터
        "fx02_business_rule.bpmn",  # 규칙(DMN)
        "fx03_call_mapping.bpmn",  # 호출 (입력·출력 매핑)
        "fx03b_amount_branch.bpmn",
        "fx06_document_read.bpmn",  # AI 태스크 (`domain: doc`)
        "fx07_email.bpmn",  # 파일 출력 + 메일
        "fx09_sequential_loop.bpmn",
        "fx10_operator_routing.bpmn",  # AI 태스크 + 웹훅
        "fx11_parallel.bpmn",
        "fx12_daily_report.bpmn",
        "fx17_webhook.bpmn",  # 웹훅
        "fx18_parallel_loop.bpmn",
        "fx20_external_adapter.bpmn",  # 서비스 앱 (외부 확장 어댑터)
    ], done
    assert waiting == [
        "bx05_month_end_close.bpmn",  # 받기 태스크 3개 + 비중단 타이머 경계
        "bx13_return_processing.bpmn",  # 받기 태스크
        "bx20_employee_onboarding.bpmn",  # 하위 프로세스에 붙은 비중단 타이머 경계
        "bx32_customer_inquiry.bpmn",
        "bx33_access_request.bpmn",
        "fx08_error_boundary.bpmn",
        "fx13_signal.bpmn",  # 신호 받기
        "fx14_timers.bpmn",  # 중간 받기 타이머 + 타이머 경계
        "fx19_manual_task_pc.bpmn",
    ], waiting


# ─────────────── 병렬·포함 게이트웨이, 하위 프로세스, 반복, 오류 경계 ───────────────


def test_a_parallel_gateway_forks_and_joins() -> None:
    """병렬 합류는 **두 가지가 모두 올 때까지** 기다린다 (C14)."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:parallelGateway id="Gw_Fork"/>'
        + script("Task_A", "가 = 1")
        + script("Task_B", "나 = 2")
        + '<bpmn:parallelGateway id="Gw_Join"/>'
        + script("Task_After", "합 = 가 + 나")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Gw_Fork")
        + flow("f2", "Gw_Fork", "Task_A")
        + flow("f3", "Gw_Fork", "Task_B")
        + flow("f4", "Task_A", "Gw_Join")
        + flow("f5", "Task_B", "Gw_Join")
        + flow("f6", "Gw_Join", "Task_After")
        + flow("f7", "Task_After", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    # 합류 뒤의 노드는 **한 번만** 돈다 (토큰이 하나로 합쳐졌다).
    assert run.variables["합"] == 3
    assert run.instances["Task_After"] == 1
    joins = [e for e in run.log.events if e.data.get("message") == "합류 완료"]
    assert len(joins) == 1


def test_an_inclusive_gateway_takes_every_true_branch() -> None:
    """포함 분기는 참인 길 **모두**로 갈라지고, 합류는 갈라진 수만큼 기다린다 (B3 짝)."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:inclusiveGateway id="Gw_Which"/>'
        + script("Task_Mail", "메일 = 1")
        + script("Task_Hook", "훅 = 1")
        + '<bpmn:inclusiveGateway id="Gw_Join"/>'
        + script("Task_After", "뒤 = 1")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Gw_Which")
        + flow("f2", "Gw_Which", "Task_Mail", "메일보냄")
        + flow("f3", "Gw_Which", "Task_Hook", "훅보냄")
        + flow("f4", "Task_Mail", "Gw_Join")
        + flow("f5", "Task_Hook", "Gw_Join")
        + flow("f6", "Gw_Join", "Task_After")
        + flow("f7", "Task_After", "End_1"),
        process_props=(
            '{"inputs": [{"name": "메일보냄", "type": "bool"}, {"name": "훅보냄", "type": "bool"}]}'
        ),
    )
    # 둘 다 참 → 두 갈래, 합류는 2를 기다린다.
    engine, run = start(process, inputs={"메일보냄": True, "훅보냄": True})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.instances["Task_After"] == 1
    assert run.variables["메일"] == 1 and run.variables["훅"] == 1

    # 하나만 참 → 한 갈래, 합류는 **1만** 기다려야 한다 (안 그러면 영원히 기다린다).
    engine, run = start(process, inputs={"메일보냄": True, "훅보냄": False})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["메일"] == 1 and "훅" not in run.variables


def test_a_subprocess_runs_inside_and_comes_back() -> None:
    """하위 프로세스는 **범위가 따로**다. 안쪽이 끝나면 바깥 토큰이 이어 간다."""
    inner = (
        '<bpmn:startEvent id="Sub_Start"/>'
        + script("Sub_Task", "안쪽 = 1")
        + '<bpmn:endEvent id="Sub_End"/>'
        + flow("sf1", "Sub_Start", "Sub_Task")
        + flow("sf2", "Sub_Task", "Sub_End")
    )
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + f'<bpmn:subProcess id="Sub_1" name="묶음">{inner}</bpmn:subProcess>'
        + script("Task_After", "뒤 = 안쪽 + 1")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Sub_1")
        + flow("f2", "Sub_1", "Task_After")
        + flow("f3", "Task_After", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["안쪽"] == 1 and run.variables["뒤"] == 2


def test_a_sequential_loop_collects_results_in_order() -> None:
    """C14 §반복 — `collect_into`에 **입력 순서대로** 모인다. PC에서는 차례로 돈다."""
    loop = '{"collection": "줄목록", "item": "줄", "result": "값", "collect_into": "모음"}'
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:scriptTask id="Task_Each" scriptFormat="chk-expr">'
        + "<bpmn:extensionElements>"
        + f"<chk:loop>{loop}</chk:loop>"
        + "</bpmn:extensionElements>"
        + "<bpmn:script>값 = 줄 * 10</bpmn:script>"
        + '<bpmn:multiInstanceLoopCharacteristics isSequential="true"/>'
        + "</bpmn:scriptTask>"
        + script("Task_After", "합 = sum(모음)")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Each")
        + flow("f2", "Task_Each", "Task_After")
        + flow("f3", "Task_After", "End_1"),
        process_props='{"inputs": [{"name": "줄목록", "type": "list"}]}',
    )
    engine, run = start(process, inputs={"줄목록": [1, 2, 3]})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["모음"] == [10, 20, 30]
    assert run.variables["합"] == 60


def test_an_empty_loop_collects_an_empty_list() -> None:
    loop = '{"collection": "줄목록", "item": "줄", "result": "값", "collect_into": "모음"}'
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:scriptTask id="Task_Each" scriptFormat="chk-expr">'
        + f"<bpmn:extensionElements><chk:loop>{loop}</chk:loop></bpmn:extensionElements>"
        + "<bpmn:script>값 = 줄</bpmn:script>"
        + '<bpmn:multiInstanceLoopCharacteristics isSequential="true"/>'
        + "</bpmn:scriptTask>"
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Each")
        + flow("f2", "Task_Each", "End_1"),
        process_props='{"inputs": [{"name": "줄목록", "type": "list", "default": []}]}',
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["모음"] == []


def test_a_loop_over_something_that_is_not_a_list_fails() -> None:
    loop = '{"collection": "하나", "item": "줄", "result": "값", "collect_into": "모음"}'
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:scriptTask id="Task_Each" scriptFormat="chk-expr">'
        + f"<bpmn:extensionElements><chk:loop>{loop}</chk:loop></bpmn:extensionElements>"
        + "<bpmn:script>값 = 줄</bpmn:script>"
        + '<bpmn:multiInstanceLoopCharacteristics isSequential="true"/>'
        + "</bpmn:scriptTask>"
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Each")
        + flow("f2", "Task_Each", "End_1"),
        process_props='{"inputs": [{"name": "하나", "type": "int", "default": 7}]}',
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "loop_not_a_list"


def test_an_error_boundary_catches_a_task_failure() -> None:
    """C14 §이벤트 — 오류 경로에 `error_code`·`error_message`·`failed_task`가 생긴다."""
    from chaeksas.core.engine import Context, Go, TaskFailed  # noqa: PLC0415

    def failing(context: Context) -> Go:
        raise TaskFailed("바깥 시스템이 500을 돌려줬다", node_id=context.node.id)

    process = make(
        '<bpmn:definitions-error/>'.replace("<bpmn:definitions-error/>", "")
        + '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:serviceTask id="Task_Call" name="바깥 호출"/>'
        + '<bpmn:boundaryEvent id="Bnd_Fail" attachedToRef="Task_Call">'
        + "<bpmn:errorEventDefinition/></bpmn:boundaryEvent>"
        + script("Task_Recover", "복구 = error_code + ':' + failed_task")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Task_Call")
        + flow("f2", "Task_Call", "End_1")
        + flow("f3", "Bnd_Fail", "Task_Recover")
        + flow("f4", "Task_Recover", "End_2")
    )
    engine = Engine(handlers={"serviceTask": failing})
    log = started()
    run = engine.start(process, run_id=log.run_id, log=log, now=NOW)

    assert engine.run_until_blocked(run) is State.DONE, "경계로 받았으면 실행은 실패가 아니다"
    assert run.variables["복구"] == "TASK_FAILED:Task_Call"
    assert run.variables["error_message"].endswith("500을 돌려줬다")
    failed = [e for e in run.log.events if e.data.get("state") == "failed"]
    assert len(failed) == 1 and failed[0].node_id == "Task_Call"


def test_a_broken_drawing_is_not_caught_by_an_error_boundary() -> None:
    """식 오류는 경계로 받지 않는다 — 고쳐야 할 버그다 (업무 실패가 아니다)."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Bad", "값 = 없는변수 + 1")
        + '<bpmn:boundaryEvent id="Bnd_Fail" attachedToRef="Task_Bad">'
        + "<bpmn:errorEventDefinition/></bpmn:boundaryEvent>"
        + script("Task_Recover", "복구 = 1")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Task_Bad")
        + flow("f2", "Task_Bad", "End_1")
        + flow("f3", "Bnd_Fail", "Task_Recover")
        + flow("f4", "Task_Recover", "End_2")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "expr_error"
    assert "복구" not in run.variables


def test_run_started_carries_the_optional_fields_only_when_known() -> None:
    """C3 `run_started`의 선택 칸은 **아는 쪽이** 준다 — 모르면 **넣지 않는다**.

    0·빈 글을 넣으면 「대기 없이 바로 돌았다」와 「모른다」가 같은 값이 된다 (CON-01이 그것을
    「—」로 가른다).
    """
    process = make('<bpmn:startEvent id="Start_1"/><bpmn:endEvent id="End_1"/>'
                   + flow("f1", "Start_1", "End_1"))
    bare = started()
    start(process, bare)
    assert set(bare.events[0].data) == {
        "bpm_process_id", "version", "run_location", "executor", "mode", "source"
    }

    told = started()
    start(process, told, job_id="job_8f3e", case_id="정상 건", queued_s=42.4567)
    data = told.events[0].data
    assert data["job_id"] == "job_8f3e"
    assert data["case_id"] == "정상 건", "Studio 시험 실행이 어느 케이스였나 (C3)"
    assert data["queued_s"] == 42.457, "소수 셋째 자리까지"


def test_a_run_that_waited_nothing_says_zero_not_nothing() -> None:
    """0초는 **값이다** — 「모른다」와 다르다."""
    process = make('<bpmn:startEvent id="Start_1"/><bpmn:endEvent id="End_1"/>'
                   + flow("f1", "Start_1", "End_1"))
    told = started()
    start(process, told, queued_s=0)
    assert told.events[0].data["queued_s"] == 0

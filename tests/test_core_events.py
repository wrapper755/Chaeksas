"""M3 조각 3d — 타이머·메시지·신호·호출 (C14 §이벤트).

여기서 거듭 보는 것은 넷이다.

1. **엔진은 스레드를 만들지 않는다.** 시간은 `RunEnv.clock`이 주고, 부르는 쪽이 `tick()`을
   돌린다. 메시지는 `deliver()`로 들어온다.
2. **경계는 멈춰 있는 동안에만 울린다.** 중단(`cancelActivity`)이면 호스트가 쥔 것(결재 요청·
   안쪽 토큰)을 걷고 경계 길로, 비중단이면 가지 하나가 따로 간다.
3. **신호는 한 실행 안에서만** 오간다 (C14).
4. **호출은 적은 것만 오간다** — 안쪽은 같은 `run_id`·같은 기록을 쓰고 `run_started`를 두 번
   남기지 않는다 (C3는 실행 하나에 하나씩만 둔다).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.core.delegation import RecordingDelegator
from chaeksas.core.engine import Engine, EngineError, Run, RunEnv, State
from chaeksas.core.run_log import RunLog

NOW = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
RUN_ID = "run_20261004_093000_abc123"

SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpm="urn:chaeksas:bpmn:1" id="Defs">
  {definitions}
  <bpmn:process id="{process_id}" name="시험">
    <bpmn:extensionElements><bpm:process>{props}</bpm:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""


class Clock:
    """시험이 쥐고 있는 시계 — 엔진은 스레드를 만들지 않으므로 이것만 밀면 된다."""

    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        self.at += timedelta(**delta)
        return self.at


def make(body: str, *, props: str = "{}", definitions: str = "", process_id: str = "test.proc") -> Any:
    return read_process(
        SHELL.format(body=body, props=props, definitions=definitions, process_id=process_id)
    )


def flow(id_: str, source: str, target: str) -> str:
    return f'<bpmn:sequenceFlow id="{id_}" sourceRef="{source}" targetRef="{target}" />'


def script(id_: str, body: str) -> str:
    return (
        f'<bpmn:scriptTask id="{id_}" scriptFormat="bpm-expr">'
        f"<bpmn:script>{body}</bpmn:script></bpmn:scriptTask>"
    )


def start(found: Any, env: RunEnv | None = None, **kwargs: Any) -> tuple[Engine, Run]:
    engine = Engine()
    log = RunLog(run_id=RUN_ID)
    return engine, engine.start(found, run_id=RUN_ID, log=log, now=NOW, env=env, **kwargs)


# ─────────────────────────── 타이머 ───────────────────────────


def catch_timer(value: str = "PT30M", *, props: str = "{}") -> Any:
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:intermediateCatchEvent id="Wait_1" name="잠깐"><bpmn:timerEventDefinition>'
        + f"<bpmn:timeDuration>{value}</bpmn:timeDuration>"
        + "</bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>"
        + script("Task_After", "뒤 = 1")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Wait_1")
        + flow("f2", "Wait_1", "Task_After")
        + flow("f3", "Task_After", "End_1"),
        props=props,
    )


def test_an_intermediate_timer_waits_until_its_time() -> None:
    clock = Clock()
    engine, run = start(catch_timer("PT30M"), RunEnv(clock=clock))
    assert engine.run_until_blocked(run) is State.WAITING
    assert run.next_due() == NOW + timedelta(minutes=30)

    clock.advance(minutes=29)
    assert engine.tick(run) is State.WAITING, "아직 멀었다"
    assert "뒤" not in run.variables

    clock.advance(minutes=2)
    assert engine.tick(run) is State.DONE
    assert run.variables["뒤"] == 1


def test_a_timer_can_point_at_a_variable() -> None:
    """C14 §이벤트 — `timeDuration`에 **변수 이름**을 적을 수 있다 (`마감기한`)."""
    clock = Clock()
    props = '{"inputs": [{"name": "마감기한", "type": "string"}]}'
    engine, run = start(catch_timer("마감기한", props=props), RunEnv(clock=clock), inputs={"마감기한": "PT5S"})
    assert engine.run_until_blocked(run) is State.WAITING
    assert run.next_due() == NOW + timedelta(seconds=5)
    clock.advance(seconds=5)
    assert engine.tick(run) is State.DONE


def test_a_timer_variable_that_is_not_a_duration_stops_the_run() -> None:
    props = '{"inputs": [{"name": "마감기한", "type": "string"}]}'
    engine, run = start(catch_timer("마감기한", props=props), inputs={"마감기한": "언젠가"})
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "timer_unreadable"


def test_a_cycle_on_a_boundary_is_refused() -> None:
    """C14 — 경계의 반복(`timeCycle`)은 schema 1에서 지원하지 않는다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:intermediateCatchEvent id="Wait_1"><bpmn:timerEventDefinition>'
        + "<bpmn:timeCycle>0 9 * * *</bpmn:timeCycle>"
        + "</bpmn:timerEventDefinition></bpmn:intermediateCatchEvent>"
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Wait_1")
        + flow("f2", "Wait_1", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "timer_cycle"


# ─────────────────────────── 경계 (중단·비중단) ───────────────────────────


APPROVAL = '{"title": "결재해 주세요"}'


def approval_with_boundary(*, cancel: str = "true", duration: str = "PT1H") -> Any:
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + f'<bpmn:userTask id="Approve_1"><bpmn:extensionElements><bpm:approval>{APPROVAL}'
        + "</bpm:approval></bpmn:extensionElements></bpmn:userTask>"
        + f'<bpmn:boundaryEvent id="Bnd_Late" attachedToRef="Approve_1" cancelActivity="{cancel}">'
        + f"<bpmn:timerEventDefinition><bpmn:timeDuration>{duration}</bpmn:timeDuration>"
        + "</bpmn:timerEventDefinition></bpmn:boundaryEvent>"
        + script("Task_After", "답받음 = 1")
        + script("Task_Late", "독촉 = 1")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Approve_1")
        + flow("f2", "Approve_1", "Task_After")
        + flow("f3", "Task_After", "End_1")
        + flow("f4", "Bnd_Late", "Task_Late")
        + flow("f5", "Task_Late", "End_2")
    )


def test_an_interrupting_timer_boundary_cancels_the_approval() -> None:
    """기한 초과 — 결재 요청을 걷고 경계 길로 간다."""
    clock = Clock()
    engine, run = start(approval_with_boundary(cancel="true"), RunEnv(clock=clock))
    assert engine.run_until_blocked(run) is State.WAITING
    assert run.pending is not None

    clock.advance(hours=2)
    assert engine.tick(run) is State.DONE
    assert run.variables["독촉"] == 1
    assert "답받음" not in run.variables
    assert run.pendings == {}, "기다리던 결재 요청을 걷었다"
    assert run.waits == {}


def test_a_non_interrupting_timer_boundary_runs_beside_the_approval() -> None:
    """독촉 — 결재는 그대로 기다리고 가지 하나가 따로 간다 (BX-03·BX-05가 이렇게 쓴다)."""
    clock = Clock()
    engine, run = start(approval_with_boundary(cancel="false"), RunEnv(clock=clock))
    assert engine.run_until_blocked(run) is State.WAITING
    pending = run.pending
    assert pending is not None

    clock.advance(hours=2)
    assert engine.tick(run) is State.WAITING, "결재는 아직 기다린다"
    assert run.variables["독촉"] == 1
    assert run.pending is not None, "요청이 살아 있다"

    engine.answer(run, pending.request_id, {"decision": "approve"}, answered_by="홍길동")
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["답받음"] == 1


def test_a_boundary_is_disarmed_once_the_host_moves_on() -> None:
    """답이 온 뒤에는 기한 타이머가 울리지 않는다."""
    clock = Clock()
    engine, run = start(approval_with_boundary(cancel="true"), RunEnv(clock=clock))
    engine.run_until_blocked(run)
    assert run.pending is not None
    engine.answer(run, run.pending.request_id, {"decision": "approve"}, answered_by="홍길동")
    assert run.waits == {}, "경계를 껐다"
    clock.advance(hours=5)
    assert engine.tick(run) is State.DONE
    assert "독촉" not in run.variables


def test_a_boundary_only_arms_while_the_host_waits() -> None:
    """한 걸음에 끝나는 노드에는 경계가 울릴 틈이 없다 — 켜지도 않는다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Quick", "값 = 1")
        + '<bpmn:boundaryEvent id="Bnd_Late" attachedToRef="Task_Quick">'
        + "<bpmn:timerEventDefinition><bpmn:timeDuration>PT1S</bpmn:timeDuration>"
        + "</bpmn:timerEventDefinition></bpmn:boundaryEvent>"
        + script("Task_Late", "늦음 = 1")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Task_Quick")
        + flow("f2", "Task_Quick", "End_1")
        + flow("f3", "Bnd_Late", "Task_Late")
        + flow("f4", "Task_Late", "End_2")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert "늦음" not in run.variables


# ─────────────────────────── 메시지 ───────────────────────────

MESSAGE = '<bpmn:message id="Msg_done" name="work_done" />'
RECEIVE = '{"correlation": "주문번호", "payload": ["검수통과", "메모"]}'


def receive_process(*, correlation: bool = True) -> Any:
    body = RECEIVE if correlation else '{"payload": ["검수통과", "메모"]}'
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:receiveTask id="Recv_1" messageRef="Msg_done"><bpmn:extensionElements>'
        + f"<bpm:receive>{body}</bpm:receive></bpmn:extensionElements></bpmn:receiveTask>"
        + script("Task_After", "결과 = 검수통과")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Recv_1")
        + flow("f2", "Recv_1", "Task_After")
        + flow("f3", "Task_After", "End_1"),
        props='{"inputs": [{"name": "주문번호", "type": "string"}]}',
        definitions=MESSAGE,
    )


def test_a_receive_task_waits_for_its_message_and_takes_the_payload() -> None:
    engine, run = start(receive_process(), inputs={"주문번호": "ORD-1"})
    assert engine.run_until_blocked(run) is State.WAITING

    engine.deliver(run, "work_done", correlation="ORD-1", payload={"검수통과": True, "비밀": "버린다"})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["결과"] is True
    assert "비밀" not in run.variables, "`payload`에 적은 이름만 변수가 된다"


def test_a_message_with_another_correlation_is_ignored() -> None:
    """C14 — 상관 키가 같은 메시지만 받는다 (여러 실행이 같은 이름을 쓴다)."""
    engine, run = start(receive_process(), inputs={"주문번호": "ORD-1"})
    engine.run_until_blocked(run)
    engine.deliver(run, "work_done", correlation="ORD-9", payload={"검수통과": True})
    assert run.state is State.WAITING
    engine.deliver(run, "work_done", correlation="ORD-1", payload={"검수통과": True})
    assert engine.run_until_blocked(run) is State.DONE


def test_a_message_nobody_waits_for_is_only_recorded() -> None:
    """케이스의 `no_receiver`와 같은 태도 — 기록만 하고 실패시키지 않는다."""
    engine, run = start(receive_process(), inputs={"주문번호": "ORD-1"})
    engine.run_until_blocked(run)
    engine.deliver(run, "다른메시지")
    assert run.state is State.WAITING
    assert any("받을 곳이 없는 메시지" in str(e.data.get("message")) for e in run.log.events)


def test_a_message_boundary_interrupts_a_receive_task() -> None:
    """BX-13의 모양 — 기다리는 동안 다른 메시지가 오면 그 길로 샌다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:receiveTask id="Recv_1" messageRef="Msg_done"><bpmn:extensionElements>'
        + '<bpm:receive>{"payload": ["검수통과"]}</bpm:receive></bpmn:extensionElements></bpmn:receiveTask>'
        + '<bpmn:boundaryEvent id="Bnd_Cancel" attachedToRef="Recv_1">'
        + '<bpmn:messageEventDefinition messageRef="Msg_cancel"/></bpmn:boundaryEvent>'
        + script("Task_After", "결과 = 1")
        + script("Task_Cancel", "취소 = 1")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Recv_1")
        + flow("f2", "Recv_1", "Task_After")
        + flow("f3", "Task_After", "End_1")
        + flow("f4", "Bnd_Cancel", "Task_Cancel")
        + flow("f5", "Task_Cancel", "End_2"),
        definitions=MESSAGE + '<bpmn:message id="Msg_cancel" name="order_cancelled" />',
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.WAITING
    engine.deliver(run, "order_cancelled")
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["취소"] == 1 and "결과" not in run.variables


# ─────────────────────────── 신호 ───────────────────────────


def test_a_signal_wakes_another_branch_of_the_same_run() -> None:
    """C14 — 신호는 **한 실행 안의 가지 사이에서만** 오간다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:parallelGateway id="Gw_Fork"/>'
        + '<bpmn:intermediateCatchEvent id="Wait_Ready">'
        + '<bpmn:signalEventDefinition signalRef="Sig_ready"/></bpmn:intermediateCatchEvent>'
        + script("Task_Go", "출발 = 1")
        + script("Task_Prepare", "준비 = 1")
        + '<bpmn:intermediateThrowEvent id="Thr_Ready">'
        + '<bpmn:signalEventDefinition signalRef="Sig_ready"/></bpmn:intermediateThrowEvent>'
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Gw_Fork")
        + flow("f2", "Gw_Fork", "Wait_Ready")
        + flow("f3", "Wait_Ready", "Task_Go")
        + flow("f4", "Task_Go", "End_1")
        + flow("f5", "Gw_Fork", "Task_Prepare")
        + flow("f6", "Task_Prepare", "Thr_Ready")
        + flow("f7", "Thr_Ready", "End_2"),
        definitions='<bpmn:signal id="Sig_ready" name="ready" />',
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["준비"] == 1 and run.variables["출발"] == 1


def test_a_signal_boundary_aborts_a_waiting_approval() -> None:
    """FX-13의 모양 — 다른 가지가 「그만」을 보내면 결재를 걷는다."""
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:parallelGateway id="Gw_Fork"/>'
        + f'<bpmn:userTask id="Approve_1"><bpmn:extensionElements><bpm:approval>{APPROVAL}'
        + "</bpm:approval></bpmn:extensionElements></bpmn:userTask>"
        + '<bpmn:boundaryEvent id="Bnd_Abort" attachedToRef="Approve_1">'
        + '<bpmn:signalEventDefinition signalRef="Sig_abort"/></bpmn:boundaryEvent>'
        + script("Task_Done", "승인 = 1")
        + script("Task_Aborted", "중단 = 1")
        + '<bpmn:intermediateThrowEvent id="Thr_Abort">'
        + '<bpmn:signalEventDefinition signalRef="Sig_abort"/></bpmn:intermediateThrowEvent>'
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/><bpmn:endEvent id="End_3"/>'
        + flow("f1", "Start_1", "Gw_Fork")
        + flow("f2", "Gw_Fork", "Approve_1")
        + flow("f3", "Approve_1", "Task_Done")
        + flow("f4", "Task_Done", "End_1")
        + flow("f5", "Bnd_Abort", "Task_Aborted")
        + flow("f6", "Task_Aborted", "End_2")
        + flow("f7", "Gw_Fork", "Thr_Abort")
        + flow("f8", "Thr_Abort", "End_3"),
        definitions='<bpmn:signal id="Sig_abort" name="abort" />',
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["중단"] == 1 and "승인" not in run.variables
    assert run.pendings == {}


# ─────────────────────────── 호출 (callActivity) ───────────────────────────

CHILD = make(
    '<bpmn:startEvent id="Sub_Start"/>'
    + script("Sub_Calc", "결과 = 받은값 * 2")
    + '<bpmn:endEvent id="Sub_End"/>'
    + flow("sf1", "Sub_Start", "Sub_Calc")
    + flow("sf2", "Sub_Calc", "Sub_End"),
    props='{"inputs": [{"name": "받은값", "type": "int"}], "outputs": ["결과"]}',
    process_id="other.proc",
)


def caller_process(mapping: str) -> Any:
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Set", "값 = 21")
        + '<bpmn:callActivity id="Call_1" calledElement="other.proc"><bpmn:extensionElements>'
        + f"<bpm:call>{mapping}</bpm:call></bpmn:extensionElements></bpmn:callActivity>"
        + script("Task_After", "최종 = 답 + 0")
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Set")
        + flow("f2", "Task_Set", "Call_1")
        + flow("f3", "Call_1", "Task_After")
        + flow("f4", "Task_After", "End_1")
    )


def test_a_call_activity_runs_the_other_process_and_maps_only_what_is_listed() -> None:
    """C14 — **적은 것만 오간다** (프로토타입의 「비면 전부」는 없앴다)."""
    mapping = '{"input": {"받은값": "값"}, "output": {"답": "결과"}}'
    engine, run = start(caller_process(mapping), RunEnv(processes={"other.proc": CHILD}))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["답"] == 42 and run.variables["최종"] == 42
    assert "받은값" not in run.variables, "안쪽 변수는 올라오지 않는다"

    kinds = [e.kind for e in run.log.events]
    assert kinds.count("run_started") == 1 and kinds.count("run_finished") == 1, "C3는 실행 하나에 하나씩"


def test_a_missing_call_target_stops_the_run() -> None:
    engine, run = start(caller_process('{"input": {}, "output": {}}'), RunEnv(processes={}))
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "call_target_missing"


#: 위임 하나 — 값 하나를 주고 하나를 받는다 (`bpm:call.delegate`, ADR-0062).
DELEGATION = (
    '{"delegate": {"bpm_process_id": "fin.erp-input", "version": "1.2.0"}, '
    '"input": {"전표번호": "값"}, "output": {"답": "결과코드"}}'
)


def test_a_delegation_is_handed_over_and_waits() -> None:
    """**맡기고 기다린다** (ADR-0062 §2) — 자리와 기다림의 짝 칸은 작업 id다."""
    port = RecordingDelegator()
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    assert engine.run_until_blocked(run) is State.WAITING

    # **입력은 맡길 때 값으로** 풀어 보낸다 (PC 쪽은 서버 그림을 모른다).
    (call,) = port.calls
    assert call.bpm_process_id == "fin.erp-input" and call.version == "1.2.0"
    assert call.inputs == {"전표번호": 21} and call.node_instance == 1
    assert call.run_id == run.run_id and call.node_id == "Call_1"
    # 기다림의 짝 칸이 그 작업이다 (C12 `waiting[].job_id`로 그대로 올라간다).
    (waiting,) = [w for w in run.waits.values() if w.kind == "delegation"]
    assert waiting.job_id == "job_dlg001"
    # **안쪽을 여기서 돌리지 않았다** — 기록에 안쪽 실행이 없다.
    assert [e.kind for e in run.log.events].count("run_started") == 1


def test_a_finished_delegation_maps_only_what_is_listed() -> None:
    """돌아온 값 중 **적은 것만** 변수가 된다 (C14 — `bpm:call.output`)."""
    port = RecordingDelegator()
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    engine.delegation_done(
        run, "job_dlg001", state="finished", outputs={"결과코드": 7, "덤": "버린다"}
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["답"] == 7 and "덤" not in run.variables
    assert run.variables["최종"] == 7, "위임 뒤의 걸음이 그 값을 쓴다"
    # **값은 기록에 남지 않는다** (원칙 6) — 받았다는 사실만이다.
    assert not any("버린다" in str(e.data) for e in run.log.events)


def test_a_failed_delegation_goes_to_the_error_boundary() -> None:
    """실패·거절·만료는 **업무 실패**다 (고쳐야 할 버그가 아니다)."""
    port = RecordingDelegator()
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    assert engine.delegation_done(run, "job_dlg001", state="rejected", reason="not_ready") is State.FAILED
    assert run.error is not None and run.error.code == "DELEGATION_FAILED"


def test_a_delegation_that_does_not_return_what_we_read_fails() -> None:
    """선언한 값이 오지 않으면 **업무 실패**다 — 빈 값으로 이어 가지 않는다."""
    port = RecordingDelegator()
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    assert engine.delegation_done(run, "job_dlg001", state="finished", outputs={}) is State.FAILED
    assert run.error is not None and run.error.code == "DELEGATION_FAILED"


def test_an_unknown_job_is_not_a_delegation_we_wait_for() -> None:
    port = RecordingDelegator()
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    with pytest.raises(EngineError) as caught:
        engine.delegation_done(run, "job_other", state="finished")
    assert caught.value.code == "not_waiting"


def test_a_refused_handover_is_a_task_failure() -> None:
    """**맡기지 못한 것**(배포된 PC가 없다 …)도 업무 실패다 — 오류 경계가 받는다."""
    port = RecordingDelegator(fails={"Call_1": "no_deployment"})
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "no_deployment"


def test_a_delegated_call_stops_instead_of_running_it_here() -> None:
    """**PC 위임은 서버에서 대신 돌리지 않는다** ([ADR-0062](../docs/decisions/0062-pc-delegation.md)).

    대상은 다른 패키지라 이 패키지 안에 정의가 없고, 맡길 포트도 아직 없다 — 그래서 **그림·설치
    오류로 멈춘다**. 폴백을 두면 화면을 만지는 정의를 서버에서 돌리다 「확장 없음」으로 터져
    운영자가 엉뚱한 곳을 고친다.
    """
    mapping = '{"delegate": {"bpm_process_id": "fin.erp-input"}, "input": {}, "output": {}}'
    engine, run = start(caller_process(mapping), RunEnv(processes={"other.proc": CHILD}))
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "node_kind_unsupported"


def test_an_output_the_called_process_does_not_have_stops_the_run() -> None:
    mapping = '{"input": {"받은값": "값"}, "output": {"답": "없는것"}}'
    engine, run = start(caller_process(mapping), RunEnv(processes={"other.proc": CHILD}))
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "call_output_missing"


def test_a_failure_inside_the_called_process_reaches_the_boundary() -> None:
    """안쪽 실패는 **호출 노드의 업무 실패**다 — 바깥 흐름으로 받을 수 있다."""
    broken = make(
        '<bpmn:startEvent id="Sub_Start"/>'
        + script("Sub_Bad", "값 = 없는변수 + 1")
        + '<bpmn:endEvent id="Sub_End"/>'
        + flow("sf1", "Sub_Start", "Sub_Bad")
        + flow("sf2", "Sub_Bad", "Sub_End"),
        process_id="broken.proc",
    )
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:callActivity id="Call_1" calledElement="broken.proc"/>'
        + '<bpmn:boundaryEvent id="Bnd_Fail" attachedToRef="Call_1">'
        + "<bpmn:errorEventDefinition/></bpmn:boundaryEvent>"
        + script("Task_Recover", "복구 = error_code")
        + '<bpmn:endEvent id="End_1"/><bpmn:endEvent id="End_2"/>'
        + flow("f1", "Start_1", "Call_1")
        + flow("f2", "Call_1", "End_1")
        + flow("f3", "Bnd_Fail", "Task_Recover")
        + flow("f4", "Task_Recover", "End_2")
    )
    engine, run = start(process, RunEnv(processes={"broken.proc": broken}))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


def test_a_called_process_can_wait_for_a_human() -> None:
    """안쪽이 결재를 기다리면 바깥도 함께 기다린다 (실행 자리는 하나다)."""
    child = make(
        '<bpmn:startEvent id="Sub_Start"/>'
        + f'<bpmn:userTask id="Sub_Approve"><bpmn:extensionElements><bpm:approval>{APPROVAL}'
        + "</bpm:approval></bpmn:extensionElements></bpmn:userTask>"
        + script("Sub_After", "결과 = 7")
        + '<bpmn:endEvent id="Sub_End"/>'
        + flow("sf1", "Sub_Start", "Sub_Approve")
        + flow("sf2", "Sub_Approve", "Sub_After")
        + flow("sf3", "Sub_After", "Sub_End"),
        props='{"outputs": ["결과"]}',
        process_id="human.proc",
    )
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:callActivity id="Call_1" calledElement="human.proc"><bpmn:extensionElements>'
        + '<bpm:call>{"output": {"답": "결과"}}</bpm:call></bpmn:extensionElements></bpmn:callActivity>'
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Call_1")
        + flow("f2", "Call_1", "End_1")
    )
    engine, run = start(process, RunEnv(processes={"human.proc": child}))
    assert engine.run_until_blocked(run) is State.WAITING

    (child_run,) = run.children.values()
    pending = child_run.pending
    assert pending is not None
    engine.answer(child_run, pending.request_id, {"decision": "approve"}, answered_by="홍길동")
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["답"] == 7


def test_a_called_process_speaks_with_the_outer_package_id() -> None:
    """안쪽 실행은 **같은 실행**이다 — 결재 요청(C6)이 안쪽 그림 id를 말하면 안 된다 (ADR-0086)."""
    from chaeksas.core import requests

    child = make(
        '<bpmn:startEvent id="Sub_Start"/>'
        + f'<bpmn:userTask id="Sub_Approve"><bpmn:extensionElements><bpm:approval>{APPROVAL}'
        + "</bpm:approval></bpmn:extensionElements></bpmn:userTask>"
        + '<bpmn:endEvent id="Sub_End"/>'
        + flow("sf1", "Sub_Start", "Sub_Approve")
        + flow("sf2", "Sub_Approve", "Sub_End"),
        process_id="human.proc",
    )
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:callActivity id="Call_1" calledElement="human.proc"/>'
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Call_1")
        + flow("f2", "Call_1", "End_1")
    )
    engine, run = start(process, RunEnv(processes={"human.proc": child}), bpm_process_id="fin.pay")
    assert engine.run_until_blocked(run) is State.WAITING

    (child_run,) = run.children.values()
    assert child_run.pending is not None
    assert child_run.identity == "fin.pay"
    assert requests.create_request(child_run, child_run.pending).bpm_process_id == "fin.pay"


# ─────────────────────────── 읽기 (C14 reader) ───────────────────────────


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ("<bpmn:timeDuration>PT30M</bpmn:timeDuration>", ("timeDuration", "PT30M")),
        ("<bpmn:timeCycle>0 9 * * 1-5</bpmn:timeCycle>", ("timeCycle", "0 9 * * 1-5")),
        ("<bpmn:timeDate>2026-10-05T09:00:00+09:00</bpmn:timeDate>", ("timeDate", "2026-10-05T09:00:00+09:00")),
    ],
)
def test_the_reader_picks_up_the_timer_body(xml: str, expected: tuple[str, str]) -> None:
    process = make(
        f'<bpmn:startEvent id="Start_1"><bpmn:timerEventDefinition>{xml}'
        + "</bpmn:timerEventDefinition></bpmn:startEvent>"
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "End_1")
    )
    timer = process.node("Start_1")
    assert timer is not None and timer.timer is not None
    assert (timer.timer.kind, timer.timer.value) == expected


def test_cancel_activity_defaults_to_interrupting() -> None:
    """BPMN 기본값이다 — 적지 않으면 끊는다."""
    process = approval_with_boundary(cancel="true")
    node = process.node("Bnd_Late")
    assert node is not None and node.cancel_activity is True
    other = approval_with_boundary(cancel="false").node("Bnd_Late")
    assert other is not None and other.cancel_activity is False


def test_timer_is_variable_tells_a_duration_from_a_name() -> None:
    from chaeksas.contracts.bpmn_ext import Timer  # noqa: PLC0415

    assert Timer(kind="timeDuration", value="PT30M").is_variable is False
    assert Timer(kind="timeDuration", value="마감기한").is_variable is True


def test_an_unknown_timer_without_a_body_is_refused() -> None:
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:intermediateCatchEvent id="Wait_1"><bpmn:timerEventDefinition/>'
        + "</bpmn:intermediateCatchEvent>"
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Wait_1")
        + flow("f2", "Wait_1", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "timer_unset"


def test_an_intermediate_catch_without_a_definition_is_refused() -> None:
    process = make(
        '<bpmn:startEvent id="Start_1"/>'
        + '<bpmn:intermediateCatchEvent id="Wait_1"/>'
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Wait_1")
        + flow("f2", "Wait_1", "End_1")
    )
    engine, run = start(process)
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "event_undefined"


def test_delivering_to_a_finished_run_is_harmless() -> None:
    engine, run = start(receive_process(), inputs={"주문번호": "ORD-1"})
    engine.run_until_blocked(run)
    engine.deliver(run, "work_done", correlation="ORD-1", payload={"검수통과": True})
    engine.run_until_blocked(run)
    assert run.state is State.DONE
    with pytest.raises(EngineError, match="기다리는 요청이 아니다"):
        engine.answer(run, "apr_없는것", {"decision": "approve"}, answered_by="홍길동")


def test_the_contract_picks_the_same_receiver_as_the_engine() -> None:
    """**규칙이 두 자리에 있으면 안 된다** (C12 §메시지).

    Center는 보고된 `waiting[]` 줄로 받는 곳을 고르고(계약의 `message_matches`), 실행기는 그
    실행의 `waits`로 고른다(`Engine.message_target`). 어긋나면 Center가 「전달했다」고 하고
    실행기가 `no_receiver`로 돌려보낸다 — **그 메시지는 영영 전달되지 않는다**.

    그래서 여기서 **같은 경우들을 양쪽에 물어 답을 맞춰 본다**.
    """
    from chaeksas.contracts.server_runner import WaitingRun, message_matches

    cases: list[tuple[bool, Any, str, Any]] = [
        # (기다리는 쪽에 상관 키가 있나, 그 값, 보낼 이름, 보낼 상관 키)
        (True, "ORD-1", "work_done", "ORD-1"),
        (True, "ORD-1", "work_done", "ORD-9"),
        (True, "ORD-1", "work_done", None),
        (False, None, "work_done", "ORD-1"),
        (False, None, "work_done", None),
        (True, "ORD-1", "다른메시지", "ORD-1"),
        (False, None, "다른메시지", None),
    ]
    for has, value, name, sent in cases:
        engine, run = start(receive_process(correlation=has), inputs={"주문번호": value or "ORD-1"})
        engine.run_until_blocked(run)
        waiting = next(w for w in run.waits.values() if w.kind == "message")
        row = WaitingRun(
            run_id=run.run_id,
            bpm_process_id="x.y",
            version="1.0.0",
            waiting_for="message",
            message_name=waiting.name,
            correlation=waiting.correlation,
            since=NOW.isoformat(),
        )
        engine_says = engine.message_target(run, name, correlation=sent) is not None
        contract_says = message_matches(row, name=name, correlation=sent)
        assert engine_says == contract_says, (
            f"엔진과 계약이 다르게 고른다: {name=} {sent=} 기다림={waiting.correlation!r}"
        )


# ─────────────── 반복 위임 — 일괄 기동 (ADR-0082) ───────────────


def batch_process(
    *, sequential: bool = True, location: str = "server", boundary: str = ""
) -> Any:
    """세 건을 맡기고 결과를 모은다 (C14 §반복 — 호출에도 쓴다).

    `boundary`는 `Call_Batch`에 붙일 경계 정의 하나다 (`error`·`timer`) — 그 길은 `Task_Caught`로 간다.
    """
    call = (
        '{"delegate": {"bpm_process_id": "ops.intake-item"}, '
        '"input": {"번호": "건"}, "output": {"답": "처리결과"}}'
    )
    loop = '{"collection": "건들", "item": "건", "result": "답", "collect_into": "답들"}'
    attached = ""
    if boundary == "error":
        attached = (
            '<bpmn:boundaryEvent id="Bnd_Batch" attachedToRef="Call_Batch">'
            "<bpmn:errorEventDefinition/></bpmn:boundaryEvent>"
        )
    elif boundary == "timer":
        attached = (
            '<bpmn:boundaryEvent id="Bnd_Batch" attachedToRef="Call_Batch" cancelActivity="true">'
            "<bpmn:timerEventDefinition><bpmn:timeDuration>PT1H</bpmn:timeDuration>"
            "</bpmn:timerEventDefinition></bpmn:boundaryEvent>"
        )
    caught = (
        attached + script("Task_Caught", "잡힘 = True") + flow("f4", "Bnd_Batch", "Task_Caught")
        + flow("f5", "Task_Caught", "End_1")
    ) if attached else ""
    return make(
        '<bpmn:startEvent id="Start_1"/>'
        + script("Task_Set", "건들 = [10, 20, 30]")
        + '<bpmn:callActivity id="Call_Batch" calledElement="Proc_item"><bpmn:extensionElements>'
        + f"<bpm:call>{call}</bpm:call><bpm:loop>{loop}</bpm:loop></bpmn:extensionElements>"
        + f'<bpmn:multiInstanceLoopCharacteristics isSequential="{str(sequential).lower()}" />'
        + "</bpmn:callActivity>"
        + '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Set")
        + flow("f2", "Task_Set", "Call_Batch")
        + flow("f3", "Call_Batch", "End_1")
        + caught,
        props=f'{{"run_location": "{location}"}}',
    )


def test_a_loop_of_delegations_hands_over_one_job_per_turn() -> None:
    """**차례마다 작업 하나** — 반복 차례가 실려 받는 쪽이 멱등 키를 가른다.

    엔진은 반복 중에 `node_instance`를 올리지 않는다 — 차례 없이 맡기면 2건째부터 같은 작업이다.
    """
    port = RecordingDelegator()
    engine, run = start(batch_process(), RunEnv(processes={}, delegate=port))
    for turn, job in enumerate(("job_dlg001", "job_dlg002", "job_dlg003")):
        assert engine.run_until_blocked(run) is State.WAITING
        call = port.calls[turn]
        assert (call.inputs, call.loop_index, call.node_instance) == ({"번호": 10 * (turn + 1)}, turn, 1)
        engine.delegation_done(run, job, state="finished", outputs={"처리결과": f"등록{turn}"})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["답들"] == ["등록0", "등록1", "등록2"], "입력 순서대로 모인다"


def test_a_failed_turn_stops_the_batch() -> None:
    """한 건의 위임이 끝나지 못하면 **남은 건은 기동하지 않는다** (ADR-0082 §3)."""
    port = RecordingDelegator()
    engine, run = start(batch_process(), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    engine.delegation_done(run, "job_dlg001", state="finished", outputs={"처리결과": "등록"})
    engine.run_until_blocked(run)
    assert engine.delegation_done(run, "job_dlg002", state="failed") is State.FAILED
    assert len(port.calls) == 2


def test_a_plain_delegation_has_no_loop_index() -> None:
    port = RecordingDelegator()
    engine, run = start(caller_process(DELEGATION), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    assert port.calls[0].loop_index is None


# ─────────────── 서버의 병렬 반복 — 함께 맡기고 함께 기다린다 (ADR-0087) ───────────────


def node_states(run: Run, node_id: str) -> list[str]:
    return [
        e.data["state"] for e in run.log.events
        if e.kind == "node_state" and e.node_id == node_id
    ]


def test_a_parallel_loop_on_the_server_hands_over_every_item_at_once() -> None:
    """**N건을 한 번에 맡긴다** — 한 건이 끝나기를 기다리지 않는다 (C14 §반복, ADR-0087 §2).

    결과는 **끝난 순서와 상관없이 입력 순서**이고, 노드의 시작·끝은 한 번이다.
    """
    port = RecordingDelegator()
    engine, run = start(batch_process(sequential=False), RunEnv(processes={}, delegate=port))
    assert engine.run_until_blocked(run) is State.WAITING
    assert [(c.inputs, c.loop_index, c.node_instance) for c in port.calls] == [
        ({"번호": 10}, 0, 1), ({"번호": 20}, 1, 1), ({"번호": 30}, 2, 1)
    ], "세 건이 한 번에, 차례마다 제 자리로 맡겨진다"
    jobs = sorted(str(w.job_id) for w in run.waits.values() if w.kind == "delegation")
    assert jobs == ["job_dlg001", "job_dlg002", "job_dlg003"], "셋을 함께 기다린다"

    # 끝나는 순서를 뒤섞는다 — 모으는 것은 입력 순서다.
    for job, answer in (("job_dlg003", "셋"), ("job_dlg001", "하나"), ("job_dlg002", "둘")):
        engine.delegation_done(run, job, state="finished", outputs={"처리결과": answer})
        engine.run_until_blocked(run)
    assert run.state is State.DONE
    assert run.variables["답들"] == ["하나", "둘", "셋"]
    assert "건" not in run.variables, "반복 항목은 반복 안에서만 보인다"
    states = node_states(run, "Call_Batch")
    assert states.count("started") == 1 and states.count("completed") == 1, states


def test_a_parallel_loop_on_a_pc_still_runs_one_at_a_time() -> None:
    """PC에서는 그림이 병렬이어도 **차례로** 돈다 — 실행 자리가 하나다 (ADR-0014, C14 §반복)."""
    port = RecordingDelegator()
    engine, run = start(
        batch_process(sequential=False, location="pc"), RunEnv(processes={}, delegate=port)
    )
    engine.run_until_blocked(run)
    assert len(port.calls) == 1


def test_one_failed_item_withdraws_the_rest_and_the_boundary_catches_once() -> None:
    """**한 건 실패는 나머지를 거둔다** (ADR-0087 §4) — 맡겨 둔 작업은 포트로 거두고 경계가 한 번 받는다."""
    port = RecordingDelegator()
    engine, run = start(
        batch_process(sequential=False, boundary="error"), RunEnv(processes={}, delegate=port)
    )
    engine.run_until_blocked(run)
    engine.delegation_done(run, "job_dlg001", state="finished", outputs={"처리결과": "하나"})
    engine.delegation_done(run, "job_dlg002", state="failed", reason="거절")
    assert sorted(port.withdrawn) == ["job_dlg003"], "끝난 것은 두고 기다리던 것만 거둔다"
    assert not run.waits, "걷힌 기다림이 남지 않는다"
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["잡힘"] is True
    assert run.variables["error_code"] == "DELEGATION_FAILED"
    assert "답들" not in run.variables, "반복이 끝나지 않았으니 모은 목록은 없다"
    assert node_states(run, "Call_Batch").count("failed") == 1


def test_one_failed_item_without_a_boundary_fails_the_run_and_withdraws_the_rest() -> None:
    port = RecordingDelegator()
    engine, run = start(batch_process(sequential=False), RunEnv(processes={}, delegate=port))
    engine.run_until_blocked(run)
    assert engine.delegation_done(run, "job_dlg001", state="failed") is State.FAILED
    assert sorted(port.withdrawn) == ["job_dlg002", "job_dlg003"]


def test_a_handover_that_fails_at_once_withdraws_what_was_already_handed_over() -> None:
    """맡기는 자리에서 실패해도 같다 — 먼저 맡긴 건을 거두고 아직 안 맡긴 건은 맡기지 않는다."""
    port = RecordingDelegator(fails={"Call_Batch": "no_deployment"})
    engine, run = start(
        batch_process(sequential=False, boundary="error"), RunEnv(processes={}, delegate=port)
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert len(port.calls) == 1, "첫 건에서 멈춘다"
    assert run.variables["잡힘"] is True


def test_the_deadline_of_a_parallel_loop_withdraws_every_item() -> None:
    """반복 노드의 기한(중단 타이머 경계)은 **활동 전체**의 것이다 — 울리면 모두 거둔다."""
    clock = Clock()
    port = RecordingDelegator()
    engine, run = start(
        batch_process(sequential=False, boundary="timer"),
        RunEnv(processes={}, delegate=port, clock=clock),
    )
    engine.run_until_blocked(run)
    timers = [w for w in run.waits.values() if w.kind == "timer"]
    assert len(timers) == 1, "경계는 차례마다가 아니라 주인 하나에 걸린다"
    engine.delegation_done(run, "job_dlg002", state="finished", outputs={"처리결과": "둘"})
    engine.run_until_blocked(run)
    clock.advance(hours=2)
    assert engine.tick(run) is State.DONE
    assert sorted(port.withdrawn) == ["job_dlg001", "job_dlg003"]
    assert run.variables["잡힘"] is True


def test_the_deadline_of_a_plain_delegation_withdraws_its_job() -> None:
    """위임 호출의 기한이 울리면 **그 작업도 거둔다** — 받을 쪽이 없는 일을 남기지 않는다 (ADR-0087 §4)."""
    clock = Clock()
    port = RecordingDelegator()
    engine, run = start(
        batch_process(sequential=True, boundary="timer"),
        RunEnv(processes={}, delegate=port, clock=clock),
    )
    engine.run_until_blocked(run)
    clock.advance(hours=2)
    assert engine.tick(run) is State.DONE
    assert port.withdrawn == ["job_dlg001"]
    assert run.variables["잡힘"] is True

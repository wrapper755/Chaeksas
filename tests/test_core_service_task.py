"""서비스 앱 태스크 (`chk:serviceCall`) — C11 호출, 멱등 키, 재시도, C3 기록.

여기서 거듭 보는 것은 셋이다.

1. **키 값은 어댑터만 안다** — 엔진·BPM 프로세스·실행 기록에는 **참조 이름**만 간다 (ADR-0013).
2. **멱등 키가 제대로 붙는다** — `(operation, run_id, node_id, node_instance, attempt, call_seq)`.
   재시도는 `attempt`를 올려 부르고, 서버 실행기가 재시작해도 같은 키라 한 번만 수행된다.
3. **어댑터가 없으면 부르지 않고 실패한다** — 조용히 건너뛰면 업무가 안 돌아간 채로 흘러간다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.events import REQUIRED_DATA_KEYS
from chaeksas.contracts.service_app import Caller, OpResponse, Usage
from chaeksas.core.engine import Engine, Run, RunEnv, State
from chaeksas.core.run_log import RunLog
from chaeksas.core.services import (
    HttpServiceCaller,
    NoServiceCaller,
    OpCall,
    RecordingServiceCaller,
    ServiceCallError,
)

NOW = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
RUN_ID = "run_20261004_093000_abc123"

SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="test.proc" name="시험">
    <bpmn:extensionElements><chk:process>{process_props}</chk:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""

#: 키 참조는 프로세스에 적는다 (B7 — 태스크에 `key_ref`가 없으면 여기서 상속한다).
PROPS = '{"service_keys": {"erp": "erp_key"}, "inputs": [{"name": "사번", "type": "string"}]}'

CALL = (
    '{"app_id": "erp", "operation": "lookup", "input": {"emp_no": "사번"},'
    ' "output": {"이름": "name", "부서": "dept"}}'
)


def flow(id_: str, source: str, target: str) -> str:
    return f'<bpmn:sequenceFlow id="{id_}" sourceRef="{source}" targetRef="{target}" />'


def process(call: str = CALL, *, boundary: bool = False, props: str = PROPS) -> Any:
    catcher = (
        '<bpmn:boundaryEvent id="Bnd_Fail" attachedToRef="Task_Call">'
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
        f'<bpmn:serviceTask id="Task_Call"><bpmn:extensionElements><chk:serviceCall>{call}'
        "</chk:serviceCall></bpmn:extensionElements></bpmn:serviceTask>"
        '<bpmn:endEvent id="End_1"/>'
        + flow("f1", "Start_1", "Task_Call")
        + flow("f2", "Task_Call", "End_1")
        + catcher
    )
    return read_process(SHELL.format(body=body, process_props=props))


def start(found: Any, env: RunEnv | None = None, **kwargs: Any) -> tuple[Engine, Run]:
    engine = Engine()
    log = RunLog(run_id=RUN_ID)
    return engine, engine.start(found, run_id=RUN_ID, log=log, now=NOW, env=env, **kwargs)


def caller(**kwargs: Any) -> RecordingServiceCaller:
    return RecordingServiceCaller(outputs={"erp/lookup": {"name": "홍길동", "dept": "재무"}}, **kwargs)


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_a_service_task_maps_input_and_output() -> None:
    """`input`은 식, `output`은 `{변수: 응답 필드}` — **적은 것만** 오간다 (C14)."""
    service = caller()
    engine, run = start(
        process(), RunEnv(services=service), inputs={"사번": "2026-001"}, mode="deterministic"
    )
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["이름"] == "홍길동" and run.variables["부서"] == "재무"

    (sent,) = service.calls
    assert sent.app_id == "erp" and sent.operation == "lookup"
    assert sent.input == {"emp_no": "2026-001"}, "입력은 식으로 계산한다"
    assert sent.mode == "deterministic", "수행 모드는 실행이 정한다 (받는 쪽은 바꾸지 않는다)"
    # **키 참조만** 간다 — 값은 어댑터가 자기 비밀 저장소에서 푼다 (ADR-0013).
    assert sent.key_ref == "erp_key"


def test_the_idempotency_key_is_filled_in() -> None:
    """C11 §전송 — `(operation, run_id, node_id, node_instance, attempt, call_seq)`."""
    service = caller()
    engine, run = start(process(), RunEnv(services=service), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    (sent,) = service.calls
    assert (sent.run_id, sent.node_id, sent.node_instance, sent.attempt, sent.call_seq) == (
        RUN_ID, "Task_Call", 1, 1, 1,
    )
    assert sent.bpm_process_id == "test.proc"


def test_a_task_level_key_ref_wins_over_the_process_one() -> None:
    call = CALL[:-1] + ', "key_ref": "erp_운영키"}'
    service = caller()
    engine, run = start(process(call), RunEnv(services=service), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    assert service.calls[0].key_ref == "erp_운영키"


def test_an_output_the_app_did_not_return_stops_the_run() -> None:
    """응답에 없는 필드를 받으려 하면 **조용히 `None`을 넣지 않는다** (B14가 미리 잡는 자리다)."""
    service = RecordingServiceCaller(outputs={"erp/lookup": {"name": "홍길동"}})
    engine, run = start(process(), RunEnv(services=service), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.FAILED
    assert run.error is not None and run.error.code == "service_output_missing"


# ─────────────────────────── 실패·재시도 ───────────────────────────


def test_without_an_adapter_the_call_is_not_made_and_the_boundary_catches_it() -> None:
    """기본은 **부르지 않고 실패**다 (`TASK_FAILED`)."""
    engine, run = start(process(boundary=True), RunEnv(services=NoServiceCaller()), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


def test_a_retryable_failure_is_called_again_with_the_next_attempt() -> None:
    call = CALL[:-1] + ', "retry": {"max": 2, "on": [503]}}'
    service = RecordingServiceCaller(
        fails={"erp/lookup": ServiceCallError("의존이 죽었다", code="dependency_down", status=503, retryable=True)}
    )
    engine, run = start(process(call, boundary=True), RunEnv(services=service), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.DONE, "마지막엔 경계가 받는다"
    assert [c.attempt for c in service.calls] == [1, 2, 3], "재시도마다 attempt가 오른다"
    assert {c.call_seq for c in service.calls} == {1}, "같은 노드의 한 번은 call_seq가 같다"


def test_a_fatal_failure_is_not_retried() -> None:
    """키가 틀린 것은 다시 불러도 똑같다 (C11 §오류 — 재시도하지 않음)."""
    call = CALL[:-1] + ', "retry": {"max": 3, "on": [503]}}'
    service = RecordingServiceCaller(
        fails={"erp/lookup": ServiceCallError("키를 모른다", code="key_invalid", status=401)}
    )
    engine, run = start(process(call), RunEnv(services=service), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.FAILED
    assert len(service.calls) == 1
    assert run.error is not None and run.error.code == "TASK_FAILED"


def test_a_retryable_failure_outside_the_listed_codes_is_not_retried() -> None:
    call = CALL[:-1] + ', "retry": {"max": 3, "on": [503]}}'
    service = RecordingServiceCaller(
        fails={"erp/lookup": ServiceCallError("너무 많다", code="rate_limited", status=429, retryable=True)}
    )
    engine, run = start(process(call), RunEnv(services=service), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.FAILED
    assert len(service.calls) == 1, "`on`에 적지 않은 코드는 다시 부르지 않는다"


# ─────────────────────────── 실행 기록 (C3) ───────────────────────────


def test_the_service_call_event_matches_the_contract() -> None:
    service = caller()
    engine, run = start(process(), RunEnv(services=service), inputs={"사번": "2026-001"})
    engine.run_until_blocked(run)

    (event,) = [e for e in run.log.events if e.kind == "service_call"]
    missing = [k for k in REQUIRED_DATA_KEYS["service_call"] if k not in event.data]
    assert not missing, missing
    assert event.data["app_id"] == "erp" and event.data["key_ref"] == "erp_key"
    # **업무 값은 없다** (원칙 6) — 사번도 이름도.
    assert "홍길동" not in str(run.log.events) and "2026-001" not in str(run.log.events)
    assert run.log.events[-1].data["service_calls"] == 1, "run_finished의 셈에도 들어간다"


def test_a_failed_call_is_recorded_too() -> None:
    """「몇 번 불렀고 왜 실패했나」가 보여야 한다."""
    call = CALL[:-1] + ', "retry": {"max": 1, "on": [503]}}'
    service = RecordingServiceCaller(
        fails={"erp/lookup": ServiceCallError("죽었다", code="dependency_down", status=503, retryable=True)}
    )
    engine, run = start(process(call), RunEnv(services=service), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    events = [e for e in run.log.events if e.kind == "service_call"]
    assert [e.data["attempt"] for e in events] == [1, 2]
    assert {e.data["error_code"] for e in events} == {"dependency_down"}


# ─────────────────────────── HTTP 어댑터 (C11) ───────────────────────────


class FakeApp:
    """C11을 흉내 내는 최소 서버. `httpx.Client`가 쓰는 자리만 맞춘다."""

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = body
        self.seen: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
        self.seen.append({"url": url, "json": json, "headers": headers})
        import httpx  # noqa: PLC0415

        return httpx.Response(self.status, json=self.body, request=httpx.Request("POST", url))

    def close(self) -> None:  # pragma: no cover — 쓰지 않는다 (client를 넣어 주므로)
        pass


class Book:
    def __init__(self, url: str | None = "http://erp.test", key: str | None = "chk_svc_abcdefgh00") -> None:
        self.url, self._key = url, key

    def base_url(self, app_id: str) -> str | None:
        return self.url

    def key(self, key_ref: str) -> str | None:
        return self._key


def op_call(**kwargs: Any) -> OpCall:
    defaults: dict[str, Any] = {
        "app_id": "erp", "operation": "lookup", "mode": "deterministic",
        "input": {"emp_no": "1"}, "run_id": RUN_ID, "node_id": "Task_Call", "key_ref": "erp_key",
    }
    return OpCall(**{**defaults, **kwargs})


def test_the_http_adapter_speaks_c11() -> None:
    app = FakeApp(
        body=OpResponse(
            output={"name": "홍길동"}, mode_used="deterministic",
            usage=Usage(model="local-7b", input_tokens=10, output_tokens=2),
        ).to_json_dict()
    )
    found = HttpServiceCaller(addresses=Book(), caller_type="studio", host="pc1", client=app).call(op_call())
    assert found.output == {"name": "홍길동"}
    assert found.usage is not None and found.usage["model"] == "local-7b"

    (sent,) = app.seen
    assert sent["url"] == "http://erp.test/v1/ops/lookup"
    assert sent["headers"]["Authorization"] == "Bearer chk_svc_abcdefgh00"
    assert sent["json"]["caller"] == {
        "type": "studio", "host": "pc1", "bpm_process_id": "", "version": "0.0.0"
    }
    assert sent["json"]["node_instance"] == 1 and sent["json"]["attempt"] == 1


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(503, "dependency_down", True), (429, "rate_limited", True), (401, "key_invalid", False),
     (422, "input_invalid", False), (504, "timeout", True)],
)
def test_http_errors_say_whether_to_try_again(status: int, code: str, retryable: bool) -> None:
    """C11 §오류 표 — 다시 불러 볼 것과 사람이 고쳐야 할 것을 가른다."""
    app = FakeApp(status=status, body={"code": code, "message": "안 된다"})
    with pytest.raises(ServiceCallError) as caught:
        HttpServiceCaller(addresses=Book(), client=app).call(op_call())
    assert caught.value.code == code
    assert caught.value.retryable is retryable


def test_a_missing_address_or_key_fails_before_any_request() -> None:
    app = FakeApp()
    with pytest.raises(ServiceCallError, match="주소를 모른다"):
        HttpServiceCaller(addresses=Book(url=None), client=app).call(op_call())
    with pytest.raises(ServiceCallError, match="이 PC에 없다"):
        HttpServiceCaller(addresses=Book(key=None), client=app).call(op_call())
    assert not app.seen, "주소·키가 없으면 아예 보내지 않는다"


def test_the_caller_model_is_the_contract_one() -> None:
    """C11 `OpRequest`를 그대로 만든다 — 모델이 검사해 준다."""
    request = op_call(node_instance=2, attempt=3, call_seq=4).request(Caller(type="bot_ui"))
    assert request.schema_version == 1
    assert (request.node_instance, request.attempt, request.call_seq) == (2, 3, 4)
    assert request.to_json_dict()["schema"] == 1, "전선 위에서는 `schema`다 (별명)"

"""서비스 앱 태스크 (`chk:serviceCall`) — 멱등 칸, 재시도, C3 기록, 그리고 Center로 올리기 (C15).

| 보는 것 | 왜 |
| --- | --- |
| `input`·`output`은 적은 것만 오간다 | C14 |
| 멱등 칸 `(operation, run_id, node_id, node_instance, attempt, call_seq)`이 붙는다 | 한 번만 수행된다 (원칙 9) |
| 어댑터가 없으면 **부르지 않고 실패**한다 | 조용히 건너뛰면 업무가 안 돈 채로 흘러간다 |
| 다시 해 볼 만한 실패만 `attempt`를 올려 다시 부른다 | C11 §오류 |
| 실행 기록에 업무 값이 없다 | 원칙 6 |
| `CenterServiceCaller`는 C15 일감으로 올리고 결과를 기다려 `ack`한다 — 앱 주소·키를 모른다 | ADR-0102 |
| 실패는 C15 코드 그대로, `retry.on`이 읽을 숫자로도 | 오류 경계·재시도가 코드에 걸려 있다 |
| 엔진 → Center → 일꾼 한 바퀴가 in-process로 맞물린다 | 조각마다 본 것이 정말 붙는가 |
| 넘겨받은 일감은 **기다림**이 되고, 결과를 넣으면 동기 호출과 **같은 규칙**으로 이어 간다 | ADR-0103 |
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.events import REQUIRED_DATA_KEYS
from chaeksas.core.engine import Engine, EngineError, Run, RunEnv, State
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_snapshot import dump, restore
from chaeksas.core.run_state import WAIT_EXTERNAL_TASK
from chaeksas.core.services import (
    CenterServiceCaller,
    NoServiceCaller,
    OpCall,
    OpOutcome,
    RecordingServiceCaller,
    ServiceCallError,
    ServicePending,
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

#: 옛 그림처럼 키 참조를 적어 둔다 — 이제는 부르는 데 쓰지 않는다 (ADR-0102).
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
    # 키는 가지 않는다 — 참조 이름조차 (ADR-0102, 키는 어댑터 일꾼의 설정이 든다).
    assert sent.key_ref is None


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


def test_a_written_key_ref_is_not_sent() -> None:
    """옛 그림이 적어 둔 `key_ref`·`service_keys`는 **부르는 데 쓰지 않는다** (ADR-0102)."""
    call = CALL[:-1] + ', "key_ref": "erp_운영키"}'
    service = caller()
    engine, run = start(process(call), RunEnv(services=service), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.DONE
    assert service.calls[0].key_ref is None


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
    assert event.data["app_id"] == "erp" and not event.data.get("key_ref"), "키 참조는 실리지 않는다"
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


# ─────────────────────────── Center로 올리기 (C15) ───────────────────────────


class FakeCenter:
    """C15 `external-tasks`를 흉내 내는 최소 Center. `httpx.Client`가 쓰는 자리만 맞춘다.

    `results`는 `GET …/external-tasks/{id}`가 차례로 돌려줄 `(상태 코드, 본문)`이다 — 마지막 것이 남는다.
    """

    def __init__(self, *results: tuple[int, dict[str, Any]], made: tuple[int, dict[str, Any]] | None = None) -> None:
        self.results = list(results) or [(200, {"task_id": "et_1", "state": "completed", "output": {}})]
        self.made = made or (201, {"task_id": "et_1", "state": "pending"})
        self.posted: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []
        self.acked: list[str] = []

    @staticmethod
    def _answer(method: str, url: str, status: int, body: dict[str, Any]) -> Any:
        import httpx  # noqa: PLC0415

        return httpx.Response(status, json=body, request=httpx.Request(method, f"http://center{url}"))

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any] | None = None) -> Any:
        if url.endswith("/ack"):
            self.acked.append(url)
            return self._answer("POST", url, 200, {})
        self.posted.append({"url": url, "json": json, "headers": headers})
        return self._answer("POST", url, *self.made)

    def get(self, url: str, *, params: dict[str, Any], headers: dict[str, str]) -> Any:
        self.gets.append({"url": url, "params": params})
        status, body = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return self._answer("GET", url, status, body)


def op_call(**kwargs: Any) -> OpCall:
    defaults: dict[str, Any] = {
        "app_id": "erp", "operation": "lookup", "mode": "deterministic",
        "input": {"emp_no": "1"}, "run_id": RUN_ID, "node_id": "Task_Call",
        "bpm_process_id": "hr.lookup", "version": "1.2.0",
    }
    return OpCall(**{**defaults, **kwargs})


def center_caller(center: Any, **kwargs: Any) -> CenterServiceCaller:
    sleeps: list[float] = []
    return CenterServiceCaller(
        base_url="http://center", token=kwargs.pop("token", "chk_ck_server"), client=center,
        sleep=sleeps.append, **kwargs,
    )


def test_a_call_becomes_an_external_task_and_its_result_comes_back() -> None:
    center = FakeCenter(
        (200, {"task_id": "et_1", "state": "pending"}),
        (200, {"task_id": "et_1", "state": "completed", "output": {"name": "홍길동"}, "mode_used": "deterministic",
               "replayed": True, "usage": {"model": "local-7b", "input_tokens": 10, "output_tokens": 2}}),
    )
    found = center_caller(center, caller_type="server_runner", host="srv_01").call(
        op_call(node_instance=2, attempt=3, call_seq=4)
    )
    assert found.output == {"name": "홍길동"} and found.replayed is True
    assert found.usage is not None and found.usage["model"] == "local-7b"

    (sent,) = center.posted
    assert sent["url"] == "/api/v1/external-tasks"
    assert sent["headers"]["Authorization"] == "Bearer chk_ck_server"
    body = sent["json"]
    assert (body["topic"], body["operation"], body["mode"], body["origin"]) == ("erp", "lookup", "deterministic", "run")
    assert body["idempotency"] == {
        "run_id": RUN_ID, "node_id": "Task_Call", "node_instance": 2, "attempt": 3, "call_seq": 4,
    }, "C11 여섯 칸이 그대로 간다 — Center가 같은 칸이면 같은 일감을 준다"
    assert body["caller"] == {"type": "server_runner", "host": "srv_01", "bpm_process_id": "hr.lookup",
                              "version": "1.2.0"}
    assert body["input"] == {"emp_no": "1"} and body["timeout_s"] == 60
    assert "key_ref" not in str(body), "부르는 쪽은 앱의 키를 모른다"
    assert [one["url"] for one in center.gets] == ["/api/v1/external-tasks/et_1"] * 2, "끝날 때까지 기다린다"
    assert center.acked == ["/api/v1/external-tasks/et_1/ack"], "받았으면 ack — Center가 값을 지운다"


def test_a_studio_test_run_is_a_test_task_and_the_token_is_read_each_time() -> None:
    center = FakeCenter()
    reads: list[int] = []

    def token() -> str:
        reads.append(1)
        return "chk_call_token"

    center_caller(center, token=token).call(op_call(run_id="test_20261004_093000_abc123", timeout_s=5))
    body = center.posted[0]["json"]
    assert body["origin"] == "test", "시험 일감이라 일꾼이 폴백·시험 주소를 고를 수 있다"
    assert body["timeout_s"] == 5
    assert len(reads) >= 3, "호출 토큰은 24시간마다 바뀐다 — 부를 때마다 읽는다"


@pytest.mark.parametrize(
    ("code", "retryable", "status"),
    [("dependency_down", True, 503), ("rate_limited", True, 429), ("timeout", True, 504),
     ("no_consumer", False, 504), ("input_invalid", False, None)],
)
def test_a_failure_carries_the_code_and_a_status_retry_on_can_read(
    code: str, retryable: bool, status: int | None
) -> None:
    """C15 `error`가 그대로 오고, `retry.on`이 읽게 HTTP 숫자로도 옮긴다 (C14)."""
    center = FakeCenter((200, {"task_id": "et_1", "state": "failed",
                               "error": {"code": code, "message": "안 된다", "retryable": retryable}}))
    with pytest.raises(ServiceCallError) as caught:
        center_caller(center).call(op_call())
    assert (caught.value.code, caught.value.retryable, caught.value.status) == (code, retryable, status)
    assert center.acked, "실패도 받았으면 ack한다"


def test_a_refusal_is_not_retried_and_nothing_is_awaited() -> None:
    """「불러도 되나」는 다시 해도 같다 — Center의 코드를 그대로 싣는다."""
    center = FakeCenter(made=(403, {"code": "topic_not_required", "message": "이 Bot은 erp를 요구하지 않는다"}))
    with pytest.raises(ServiceCallError) as caught:
        center_caller(center).call(op_call())
    assert (caught.value.code, caught.value.status, caught.value.retryable) == ("topic_not_required", 403, False)
    assert "요구하지 않는다" in str(caught.value)
    assert center.gets == []


def test_the_long_poll_limit_is_waited_out() -> None:
    """롱폴링 상한(503)은 실패가 아니다 — 잠깐 쉬고 다시 건다."""
    center = FakeCenter(
        (503, {"code": "too_many_waiters"}),
        (200, {"task_id": "et_1", "state": "completed", "output": {"name": "홍길동"}}),
    )
    assert center_caller(center).call(op_call()).output == {"name": "홍길동"}
    assert len(center.gets) == 2


def test_without_a_token_nothing_is_sent() -> None:
    center = FakeCenter()
    with pytest.raises(ServiceCallError) as caught:
        center_caller(center, token=lambda: None).call(op_call())
    assert caught.value.code == "token_missing"
    assert center.posted == []


def test_an_unreachable_center_is_worth_trying_again() -> None:
    import httpx  # noqa: PLC0415

    class Down:
        def post(self, *_a: Any, **_k: Any) -> Any:
            raise httpx.ConnectError("닿지 못함")

    with pytest.raises(ServiceCallError) as caught:
        center_caller(Down()).call(op_call())
    assert caught.value.retryable is True


def test_a_task_that_never_finishes_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """기한(+여유)이 지나도 끝나지 않으면 `timeout`으로 실패한다 — 영원히 기다리지 않는다."""
    import chaeksas.core.services as services  # noqa: PLC0415

    clock = iter([0.0, 10.0, 1000.0, 1000.0, 1000.0])

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return next(clock)

    monkeypatch.setattr(services, "time", Clock)
    center = FakeCenter((200, {"task_id": "et_1", "state": "locked"}))
    with pytest.raises(ServiceCallError) as caught:
        center_caller(center).call(op_call(timeout_s=30))
    assert (caught.value.code, caught.value.retryable, caught.value.status) == ("timeout", True, 504)


# ─────────────────────────── 진짜 Center와 일꾼 (in-process) ───────────────────────────


class FinishOnPost:
    """Center `TestClient` 앞에 서서, 일감이 올라가면 **그 자리에서 일꾼을 한 바퀴** 돌린다.

    스레드·롱폴링 없이 한 바퀴를 본다 — 롱폴링과 진짜 소켓은 `test_c15_round_trip.py`가 본다.
    """

    def __init__(self, center: Any, consumer: Any) -> None:
        self.center, self.consumer = center, consumer

    def post(self, url: str, **kw: Any) -> Any:
        answer = self.center.post(url, **kw)
        if url == "/api/v1/external-tasks":
            self.consumer.run_once(wait_s=0)
        return answer

    def get(self, url: str, **kw: Any) -> Any:
        return self.center.get(url, **kw)


def test_the_engine_calls_through_center_to_a_consumer(tmp_path: Any) -> None:
    """엔진 → `CenterServiceCaller` → Center → 일꾼의 작업 함수 → 변수. 엔진은 무엇이 바뀌었는지 모른다."""
    from consumers import ADMIN, enroll  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from chaeksas.center.app import create_app as create_center  # noqa: PLC0415
    from chaeksas.center.settings import Settings as CenterSettings  # noqa: PLC0415
    from chaeksas.center.storage import Store  # noqa: PLC0415
    from chaeksas.contracts.service_app import ServiceAppManifest  # noqa: PLC0415
    from chaeksas.service_kit import Consumer, create_app  # noqa: PLC0415

    manifest = ServiceAppManifest.model_validate(
        {"schema": 1, "app_id": "erp", "name": "ERP", "version": "1.0.0", "category": "business",
         "console_url": "", "operations": [{"name": "lookup", "modes": ["deterministic"]}]}
    )
    erp = create_app(manifest, {"lookup": lambda req, mode: {"name": f"사원 {req.input['emp_no']}", "dept": "재무"}})
    store = Store(tmp_path / "center.sqlite3")
    settings = CenterSettings(admin_token="t-admin", package_dir=tmp_path / "pkg")
    with TestClient(create_center(settings, store=store)) as center:
        tokens = enroll(center, topics=["erp"], manifests=[manifest.to_json_dict()], folder=tmp_path / "c")
        consumer = Consumer([erp.state.ops], center_url="", tokens=tokens, wait_s=0, client=center)
        key = center.post("/api/v1/center-keys", json={"name": "설계자", "type": "studio"}, headers=ADMIN)
        caller = CenterServiceCaller(
            base_url="", token=key.json()["key"], caller_type="studio", client=FinishOnPost(center, consumer)
        )
        engine = Engine()
        run = engine.start(
            process(), run_id="test_20261004_093000_abc123", log=RunLog(run_id="test_20261004_093000_abc123"), now=NOW,
            env=RunEnv(services=caller), inputs={"사번": "2026-001"}, mode="deterministic",
        )
        assert engine.run_until_blocked(run) is State.DONE, run.error
        assert run.variables["이름"] == "사원 2026-001" and run.variables["부서"] == "재무"
        row = store.row("SELECT input_json, output_json, acked_at FROM external_tasks")
        assert row is not None and row["input_json"] is None and row["acked_at"], "받았으니 값이 지워졌다"
    store.close()


# ─────────────────────────── 긴 외부 작업 (ADR-0103) ───────────────────────────


class Parking:
    """올리면 **넘겨받는다**(`ServicePending`) — 서버 실행기의 `park_after_s`가 지난 자리를 흉내 낸다."""

    def __init__(self) -> None:
        self.calls: list[OpCall] = []
        self.withdrawn: list[str] = []

    def call(self, request: OpCall) -> Any:
        self.calls.append(request)
        raise ServicePending(f"xt_{request.attempt}")

    def withdraw(self, task_id: str) -> None:
        self.withdrawn.append(task_id)


def test_a_handed_back_task_waits_and_its_result_continues_the_run() -> None:
    service = Parking()
    engine, run = start(process(), RunEnv(services=service), inputs={"사번": "1"})
    assert engine.run_until_blocked(run) is State.WAITING
    ((owner, waiting),) = engine.external_waits(run)
    assert owner is run and waiting.kind == WAIT_EXTERNAL_TASK and waiting.task_id == "xt_1"
    assert (waiting.attempt, waiting.call_seq) == (1, 1)
    assert engine.external_call(run, "xt_1").input == {"emp_no": "1"}

    # 기다리는 동안 담았다가 되살려도 **어느 일감인지** 안다 (스냅샷과 함께 간다).
    run = restore(dump(run), process=process(), log=run.log, env=RunEnv(services=service))
    engine.external_done(run, "xt_1", OpOutcome(output={"name": "홍길동", "dept": "재무"}))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["이름"] == "홍길동"
    assert len(service.calls) == 1, "끝난 것은 다시 올리지 않는다"
    kinds = [e.kind for e in run.log.events]
    assert kinds.count("service_call") == 1, "결과를 넣을 때 한 줄 — 동기 호출과 같다"


def test_a_retryable_result_goes_to_the_next_attempt_and_may_wait_again() -> None:
    call = CALL[:-1] + ', "retry": {"max": 1, "on": [503]}}'
    service = Parking()
    engine, run = start(process(call, boundary=True), RunEnv(services=service), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    failed = ServiceCallError("의존이 죽었다", code="dependency_down", status=503, retryable=True)
    assert engine.external_done(run, "xt_1", failed) is State.WAITING
    assert [c.attempt for c in service.calls] == [1, 2] and {c.call_seq for c in service.calls} == {1}
    ((_, waiting),) = engine.external_waits(run)
    assert waiting.task_id == "xt_2" and waiting.attempt == 2

    engine.external_done(run, "xt_2", failed)
    assert engine.run_until_blocked(run) is State.DONE, "다 실패하면 오류 경계가 받는다"
    assert run.variables["복구"] == "TASK_FAILED"


def test_a_fatal_result_goes_straight_to_the_boundary() -> None:
    service = Parking()
    engine, run = start(process(boundary=True), RunEnv(services=service), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    engine.external_done(run, "xt_1", ServiceCallError("없는 작업", code="operation_not_found", status=422))
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["복구"] == "TASK_FAILED"


def test_cancelling_withdraws_the_waited_task() -> None:
    service = Parking()
    engine, run = start(process(), RunEnv(services=service), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    engine.cancel(run, reason="사람이 멈췄다")
    assert service.withdrawn == ["xt_1"]
    assert engine.external_waits(run) == []


def test_a_task_nobody_waits_for_is_refused() -> None:
    engine, run = start(process(), RunEnv(services=Parking()), inputs={"사번": "1"})
    engine.run_until_blocked(run)
    with pytest.raises(EngineError) as caught:
        engine.external_done(run, "xt_9", OpOutcome(output={}))
    assert caught.value.code == "not_waiting"

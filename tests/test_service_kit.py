"""C11 + `service_kit` — 서비스 앱 하나를 세우고 **일감을 계약대로 수행하는지** 본다 (ADR-0102).

앱은 업무 호출을 HTTP로 받지 않는다 — 일꾼(`Consumer`)이 Center에서 가져온 C15 `LockedTask`를
`Service.execute()`에 준다. 그래서 여기서는 HTTP 없이 **수행기**를 바로 부른다. 일꾼이 Center와
오가는 것은 `test_service_kit_consumer.py`가, 한 바퀴는 `test_c15_round_trip.py`가 본다.

| 보는 것 | 왜 |
| --- | --- |
| HTTP로 남는 것은 `/healthz`와 관리 API뿐이다 (`/manifest`·`/v1/ops`가 없다) | 앱이 업무 포트를 열지 않는다 |
| 작업 함수의 결과가 `complete` 본문이 된다 (`mode_used`·`replayed`·`usage`) | C15 끝내기의 모양 |
| 받지 않는 모드는 `mode_unsupported` — **폴백은 시험 일감(`origin: test`)만** | 운영에서 LLM이 몰래 끼지 않는다 |
| 같은 멱등 칸은 **다시 수행하지 않고** `replayed`로 돌려준다 | 잠금이 지나 같은 일감이 다시 온다 (최소 한 번) |
| 아직 도는 같은 칸은 `skip` — 아무것도 보내지 않는다 | 먼저 끝낸 쪽이 이긴다 (C15) |
| 같은 칸에 다른 본문은 `idempotency_conflict` | 다른 일을 같은 이름으로 하지 않는다 |
| 실패하면 멱등 자리를 비운다, `retryable`은 아는 코드만 | 같은 시도로 다시 받을 수 있어야 한다 |
| 예외를 올리지 않는다 — 모르는 오류는 `internal` | 일꾼 루프가 멈추지 않는다 |
| 사용 기록에 업무 값이 없고 `key_name`은 `<부른 쪽>:<호스트>` | 원칙 6, 앱 안의 키가 없다 |
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.external_task import LockedTask
from chaeksas.contracts.service_app import (
    MODE_AUTONOMOUS,
    MODE_DETERMINISTIC,
    OpRequest,
    ServiceAppManifest,
    Usage,
    idempotency_key,
)
from chaeksas.service_kit import (
    InMemoryIdempotencyStore,
    InMemoryUsageLog,
    OpError,
    OpResult,
    Service,
    body_hash,
    create_app,
)

NOW = "2026-10-02T10:00:00+09:00"
LATER = "2026-10-02T10:10:00+09:00"


def manifest(**over: Any) -> ServiceAppManifest:
    base: dict[str, Any] = {
        "schema": 1,
        "app_id": "tax-invoice",
        "name": "세금계산서 앱",
        "version": "0.1.0",
        "category": "business",
        "console_url": "http://localhost:8011",
        "operations": [
            {"name": "issue", "description": "세금계산서를 발행한다", "modes": [MODE_DETERMINISTIC]},
            {"name": "summarize", "description": "요약한다", "modes": [MODE_AUTONOMOUS, MODE_DETERMINISTIC]},
            {"name": "guess", "description": "결정 수행이 실패하면 자율로", "modes": [MODE_AUTONOMOUS],
             "fallback": MODE_AUTONOMOUS},
            {"name": "only_pc", "description": "현장에서만", "modes": [MODE_DETERMINISTIC], "server_ok": False},
        ],
    }
    return ServiceAppManifest.model_validate(base | over)


class Calls:
    """작업 함수가 몇 번 불렸나 — 멱등이 정말 **다시 수행하지 않는지** 센다."""

    def __init__(self) -> None:
        self.n: dict[str, int] = {}

    def hit(self, name: str) -> None:
        self.n[name] = self.n.get(name, 0) + 1


def handlers(calls: Calls) -> dict[str, Any]:
    def issue_op(req: OpRequest, mode: str) -> OpResult:
        calls.hit("issue")
        return OpResult({"invoice_no": "2026100100001", "mode_seen": mode})

    def summarize_op(req: OpRequest, mode: str) -> OpResult:
        calls.hit("summarize")
        return OpResult({"summary": "요약"}, usage=Usage(model="local-7b", input_tokens=10, output_tokens=3))

    def guess_op(req: OpRequest, mode: str) -> dict[str, Any]:
        calls.hit("guess")
        return {"guessed": True, "mode_seen": mode}  # 평범한 dict도 받는다

    def only_pc_op(req: OpRequest, mode: str) -> OpResult:
        return OpResult({"ok": True})

    return {"issue": issue_op, "summarize": summarize_op, "guess": guess_op, "only_pc": only_pc_op}


def locked(**over: Any) -> LockedTask:
    """Center가 일꾼에게 내준 일감 하나 (C15 `LockedTask`)."""
    body: dict[str, Any] = {
        "task_id": "et_0001",
        "topic": "tax-invoice",
        "operation": "issue",
        "mode": MODE_DETERMINISTIC,
        "origin": "run",
        "idempotency": {"run_id": "run_20261002_100000_a1b2c3", "node_id": "Task_issue", "node_instance": 1,
                        "attempt": 1},
        "caller": {"type": "server_runner", "host": "srv_01", "bpm_process_id": "finance.invoice-issue",
                   "version": "1.0.0"},
        "input": {"buyer_biz_no": "123-45-67890", "amount": 1100000},
        "lock_until": LATER,
        "deadline": LATER,
    }
    for name in ("attempt", "node_id", "run_id"):
        if name in over:
            body["idempotency"] = {**body["idempotency"], name: over.pop(name)}
    return LockedTask.model_validate(body | over)


@pytest.fixture
def calls() -> Calls:
    return Calls()


@pytest.fixture
def log() -> InMemoryUsageLog:
    return InMemoryUsageLog()


@pytest.fixture
def app(calls: Calls, log: InMemoryUsageLog) -> Any:
    return create_app(manifest(), handlers(calls), usage_log=log, now=lambda: NOW)


@pytest.fixture
def service(app: Any) -> Service:
    found = app.state.ops
    assert isinstance(found, Service)
    return found


# ─────────────── HTTP로 남은 것 ───────────────


def test_healthz(app: Any) -> None:
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok" and r.json()["version"] == "0.1.0"


def test_the_app_opens_no_business_port(app: Any) -> None:
    """**업무 호출을 받는 길이 없다** (ADR-0102) — manifest는 일꾼이 Center에 올린다."""
    with TestClient(app) as client:
        assert client.get("/manifest").status_code == 404
        assert client.post("/v1/ops/issue", json={}).status_code == 404
        assert client.get("/v1/keys/self").status_code == 404


def test_the_service_carries_the_manifest(service: Service) -> None:
    assert service.app_id == "tax-invoice"
    assert service.manifest.operation("only_pc") is not None
    assert service.manifest.operation("only_pc").server_ok is False  # type: ignore[union-attr]


def test_handlers_must_match_the_manifest(calls: Calls) -> None:
    """manifest에 적었는데 함수가 없으면 일감이 올 때가 아니라 **만들 때** 터져야 한다."""
    with pytest.raises(ValueError, match="manifest의 작업과 handlers가 다르다"):
        create_app(manifest(), {"issue": handlers(calls)["issue"]})


# ─────────────── 수행 ───────────────


def test_a_task_runs_the_operation(service: Service) -> None:
    done = service.execute(locked())
    assert done.ok and not done.skip
    body = done.complete_body()
    assert body["output"] == {"invoice_no": "2026100100001", "mode_seen": MODE_DETERMINISTIC}
    assert body["mode_used"] == MODE_DETERMINISTIC and body["replayed"] is False
    assert "usage" not in body, "모델을 쓰지 않았으면 싣지 않는다"


def test_usage_travels_in_the_complete_body(service: Service) -> None:
    body = service.execute(locked(operation="summarize", node_id="Task_sum")).complete_body()
    assert body["usage"] == {"model": "local-7b", "input_tokens": 10, "output_tokens": 3}


def test_the_operation_sees_the_task_as_an_op_request(calls: Calls) -> None:
    """`LockedTask` → `OpRequest` — 칸이 그대로 옮겨진다 (C11 §OpRequest)."""
    seen: list[OpRequest] = []

    def grab(req: OpRequest, mode: str) -> dict[str, Any]:
        seen.append(req)
        return {}

    one = create_app(
        manifest(operations=[{"name": "issue", "modes": [MODE_DETERMINISTIC]}]), {"issue": grab}
    ).state.ops
    one.execute(locked(business_key="INV-7", origin="test", run_id="test_aaaaaa"))
    [req] = seen
    assert (req.run_id, req.node_id, req.node_instance, req.attempt, req.call_seq) == (
        "test_aaaaaa", "Task_issue", 1, 1, 1
    )
    assert req.business_key == "INV-7" and req.origin == "test"
    assert req.caller.type == "server_runner" and req.input["amount"] == 1100000


def test_unknown_operation(service: Service) -> None:
    done = service.execute(locked(operation="nope"))
    assert not done.ok
    assert done.fail_body() == {"code": "operation_not_found", "message": done.message, "retryable": False}


def test_mode_unsupported_by_the_operation(service: Service) -> None:
    """작업이 그 모드를 지원하지 않으면 실패 — 받는 쪽이 모드를 바꾸지 않는다 (원칙 7)."""
    done = service.execute(locked(mode=MODE_AUTONOMOUS))  # issue는 deterministic만
    assert done.code == "mode_unsupported" and done.retryable is False


def test_fallback_only_for_test_tasks(service: Service, calls: Calls) -> None:
    """폴백은 **시험 일감일 때만** 일어난다 (운영에서 LLM이 몰래 끼지 않게, C11)."""
    field = service.execute(locked(operation="guess", node_id="Task_guess"))
    assert field.code == "mode_unsupported"
    assert calls.n.get("guess") is None, "현장 일감은 작업 함수까지 가지 않는다"

    trial = service.execute(locked(operation="guess", node_id="Task_guess", origin="test", run_id="test_bbbbbb"))
    assert trial.ok
    body = trial.complete_body()
    assert body["mode_used"] == MODE_AUTONOMOUS, "넘어간 것이 `mode_used`로 드러난다"
    assert body["output"]["mode_seen"] == MODE_AUTONOMOUS


def test_autonomous_runs_when_the_operation_supports_it(service: Service) -> None:
    """자율 수행을 들일지는 **Center가** 가린다(Studio 시험 실행만) — 앱은 작업의 선언만 본다."""
    done = service.execute(locked(operation="summarize", node_id="Task_sum", mode=MODE_AUTONOMOUS))
    assert done.ok and done.complete_body()["mode_used"] == MODE_AUTONOMOUS


# ─────────────── 멱등 ───────────────


def test_same_slot_replays_without_running_again(service: Service, calls: Calls) -> None:
    first = service.execute(locked())
    second = service.execute(locked(task_id="et_0001", delivery=2))
    assert first.complete_body()["replayed"] is False
    assert second.ok and second.complete_body()["replayed"] is True
    assert second.complete_body()["output"] == first.complete_body()["output"]
    assert calls.n["issue"] == 1, "다시 수행하지 않았다"


def test_different_attempt_is_a_new_call(service: Service, calls: Calls) -> None:
    service.execute(locked())
    again = service.execute(locked(attempt=2))
    assert again.complete_body()["replayed"] is False
    assert calls.n["issue"] == 2


def test_same_slot_with_a_different_body_conflicts(service: Service) -> None:
    service.execute(locked())
    done = service.execute(locked(input={"amount": 1}))
    assert done.code == "idempotency_conflict" and done.retryable is False


def test_a_slot_still_running_is_skipped(service: Service) -> None:
    """잠금이 지나 같은 일감이 다시 왔는데 **앞의 것이 아직 돈다** — 아무것도 보내지 않는다."""
    task = locked()
    req = service.request_of(task)
    assert service.idempotency.begin(idempotency_key(task.operation, req), body=body_hash(req)) == ("new", None)

    done = service.execute(task)
    assert done.skip and not done.ok


def test_float_input_does_not_break_idempotency(service: Service) -> None:
    """C2의 canonical_json은 실수를 금지하지만, 작업 입력은 서명 대상이 아니다."""
    assert service.execute(locked(input={"rate": 0.075})).ok
    assert service.execute(locked(input={"rate": 0.075})).complete_body()["replayed"] is True


def test_a_failure_frees_the_slot_and_says_whether_to_retry() -> None:
    """실패한 수행은 자리를 비운다 — 같은 시도로 한 번 더 받을 수 있어야 한다."""
    calls = {"n": 0}

    def flaky(req: OpRequest, mode: str) -> OpResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OpError("dependency_down", "LLM이 죽었다", status=503)
        return OpResult({"ok": True})

    m = ServiceAppManifest.model_validate(
        {"schema": 1, "app_id": "a", "name": "a", "version": "0.1.0", "category": "system",
         "console_url": "http://x", "operations": [{"name": "flaky", "modes": [MODE_DETERMINISTIC]}]}
    )
    service = create_app(m, {"flaky": flaky}, now=lambda: NOW).state.ops
    first = service.execute(locked(topic="a", operation="flaky"))
    assert first.fail_body() == {"code": "dependency_down", "message": "LLM이 죽었다", "retryable": True}
    second = service.execute(locked(topic="a", operation="flaky"))
    assert second.ok and second.complete_body()["replayed"] is False
    assert calls["n"] == 2


def test_a_business_failure_is_not_retryable() -> None:
    def refuse(req: OpRequest, mode: str) -> OpResult:
        raise OpError("input_invalid", "사업자 번호가 틀렸다", status=422)

    m = manifest(operations=[{"name": "issue", "modes": [MODE_DETERMINISTIC]}])
    done = create_app(m, {"issue": refuse}).state.ops.execute(locked())
    assert (done.code, done.retryable) == ("input_invalid", False)


def test_an_unexpected_error_is_internal_and_does_not_escape() -> None:
    """작업 함수가 터져도 **예외를 올리지 않는다** — 일꾼 루프가 멈추면 다른 일감도 못 한다."""

    def boom(req: OpRequest, mode: str) -> OpResult:
        raise RuntimeError("비밀 1100000")

    m = manifest(operations=[{"name": "issue", "modes": [MODE_DETERMINISTIC]}])
    service = create_app(m, {"issue": boom}).state.ops
    done = service.execute(locked())
    assert done.code == "internal" and done.retryable is False
    assert "1100000" not in done.message, "예외 글(업무 값이 섞일 수 있다)을 싣지 않는다"
    assert isinstance(service.idempotency, InMemoryIdempotencyStore)
    assert service.idempotency.entries == {}, "자리를 비웠다"


# ─────────────── 사용 기록 ───────────────


def test_usage_log_records_no_business_values(service: Service, log: InMemoryUsageLog) -> None:
    """시각·부른 쪽·작업·모드·결과·소요·run_id만. **입력·출력 값은 기록하지 않는다.**"""
    service.execute(locked(operation="summarize", node_id="Task_sum"))
    [entry] = log.entries
    assert entry.key_name == "server_runner:srv_01", "앱 안의 키가 없다 — 부른 쪽이 이름이다"
    assert (entry.operation, entry.status, entry.mode, entry.at) == ("summarize", 200, MODE_DETERMINISTIC, NOW)
    assert entry.caller_type == "server_runner" and entry.run_id == "run_20261002_100000_a1b2c3"
    assert entry.usage is not None and entry.usage.model == "local-7b"
    dumped = entry.to_json_dict()
    assert "input" not in dumped and "output" not in dumped
    assert "1100000" not in str(dumped)  # 업무 값이 새지 않는다


def test_a_caller_without_a_host_is_named_with_a_dash(service: Service, log: InMemoryUsageLog) -> None:
    service.execute(locked(caller={"type": "studio"}))
    assert log.entries[0].key_name == "studio:-"


def test_failures_are_logged_too(service: Service, log: InMemoryUsageLog) -> None:
    """실패도 센다 — SVC-01 오류율이 이 수로 센다."""
    service.execute(locked(mode=MODE_AUTONOMOUS))
    service.execute(locked(operation="nope"))
    assert [(e.operation, e.status, e.mode) for e in log.entries] == [("issue", 422, "-"), ("nope", 404, "-")]


def test_a_replay_is_logged_as_a_call(service: Service, log: InMemoryUsageLog) -> None:
    service.execute(locked())
    service.execute(locked())
    assert [e.status for e in log.entries] == [200, 200]

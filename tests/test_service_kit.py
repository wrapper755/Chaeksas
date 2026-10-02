"""C11 + `service_kit` — 빈 서비스 앱 하나를 세우고 계약대로 답하는지 본다.

M1 완료 기준: "`service_kit`으로 만든 빈 서비스 앱이 `/healthz`, `/manifest`에 답하고,
관리 콘솔에서 발급한 API 키로만 호출되며, 허용되지 않은 모드를 거부함".
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import (
    MODE_AUTONOMOUS,
    MODE_DETERMINISTIC,
    OpRequest,
    ServiceAppManifest,
    Usage,
)
from chaeksas.service_kit import (
    InMemoryIdempotencyStore,
    InMemoryKeyStore,
    InMemoryUsageLog,
    OpError,
    OpResult,
    create_app,
    issue,
)

NOW = "2026-10-02T10:00:00+09:00"


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


def handlers() -> dict[str, Any]:
    def issue_op(req: OpRequest, mode: str) -> OpResult:
        return OpResult({"invoice_no": "2026100100001", "mode_seen": mode})

    def summarize_op(req: OpRequest, mode: str) -> OpResult:
        return OpResult({"summary": "요약"}, usage=Usage(model="local-7b", input_tokens=10, output_tokens=3))

    def guess_op(req: OpRequest, mode: str) -> dict[str, Any]:
        return {"guessed": True, "mode_seen": mode}  # 평범한 dict도 받는다

    def only_pc_op(req: OpRequest, mode: str) -> OpResult:
        return OpResult({"ok": True})

    return {"issue": issue_op, "summarize": summarize_op, "guess": guess_op, "only_pc": only_pc_op}


@pytest.fixture
def app_fixture() -> tuple[TestClient, str, InMemoryKeyStore, InMemoryUsageLog, InMemoryIdempotencyStore]:
    keys = InMemoryKeyStore()
    raw, record = issue("운영-재무", created_at=NOW)  # 기본 권한 = 결정 수행만
    keys.add(record)
    log = InMemoryUsageLog()
    idem = InMemoryIdempotencyStore()
    app = create_app(manifest(), handlers(), keys=keys, idempotency=idem, usage_log=log, now=lambda: NOW)
    return TestClient(app), raw, keys, log, idem


def op_body(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": 1,
        "mode": MODE_DETERMINISTIC,
        "run_id": "run_20261002_100000_a1b2c3",
        "node_id": "Task_issue",
        "node_instance": 1,
        "attempt": 1,
        "caller": {"type": "server_runner", "host": "srv_01", "bpm_process_id": "finance.invoice-issue",
                   "version": "1.0.0"},
        "input": {"buyer_biz_no": "123-45-67890", "amount": 1100000},
    }
    return base | over


# ─────────────── 인증 없는 두 엔드포인트 ───────────────


def test_healthz(app_fixture: Any) -> None:
    client, *_ = app_fixture
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_manifest_needs_no_auth_and_has_no_secret(app_fixture: Any) -> None:
    """C7이 이것을 읽어 리소스 목록을 만든다 — 비밀이 들어가면 안 된다."""
    client, *_ = app_fixture
    r = client.get("/manifest")
    assert r.status_code == 200
    body = r.json()
    assert body["app_id"] == "tax-invoice"
    assert [o["name"] for o in body["operations"]] == ["issue", "summarize", "guess", "only_pc"]
    assert "chk_svc_" not in r.text  # 키 원문·앞자리가 섞여 나가지 않는다


def test_manifest_matches_the_contract_model(app_fixture: Any) -> None:
    client, *_ = app_fixture
    parsed = ServiceAppManifest.model_validate(client.get("/manifest").json())
    assert parsed.operation("issue") is not None
    assert parsed.operation("only_pc") is not None
    assert parsed.operation("only_pc").server_ok is False  # type: ignore[union-attr]


# ─────────────── 키로만 호출된다 ───────────────


def test_no_key_is_refused(app_fixture: Any) -> None:
    client, *_ = app_fixture
    r = client.post("/v1/ops/issue", json=op_body())
    assert r.status_code == 401
    assert r.json()["code"] == "key_missing"


def test_unknown_key_is_refused(app_fixture: Any) -> None:
    client, *_ = app_fixture
    r = client.post("/v1/ops/issue", json=op_body(), headers={"Authorization": "Bearer chk_svc_" + "x" * 40})
    assert r.status_code == 401
    assert r.json()["code"] == "key_invalid"


def test_valid_key_works(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    r = client.post("/v1/ops/issue", json=op_body(), headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["output"]["invoice_no"] == "2026100100001"
    assert body["mode_used"] == MODE_DETERMINISTIC
    assert body["replayed"] is False


def test_revoked_key_is_403_not_401(app_fixture: Any) -> None:
    """「모르는 키」와 「폐기된 키」를 구분해 알린다 — 부르는 쪽의 안내가 달라진다."""
    client, raw, keys, _, _ = app_fixture
    keys.keys[0].revoked_at = NOW
    r = client.post("/v1/ops/issue", json=op_body(), headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 403
    assert r.json()["code"] == "key_revoked"


def test_expired_key_is_403(app_fixture: Any) -> None:
    client, raw, keys, _, _ = app_fixture
    keys.keys[0].expires_at = "2026-10-01T00:00:00+09:00"
    r = client.post("/v1/ops/issue", json=op_body(), headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 403
    assert r.json()["code"] == "key_expired"


def test_keys_self_does_not_leak_the_raw_key(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    r = client.get("/v1/keys/self", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "운영-재무"
    assert body["prefix"] == raw[:16]
    assert raw not in r.text  # 원문은 돌려주지 않는다
    assert "hash" not in body


# ─────────────── 권한: 작업·모드 ───────────────


def test_operation_not_allowed(app_fixture: Any) -> None:
    client, _, keys, _, _ = app_fixture
    keys.keys[0].allowed_operations = ["summarize"]
    raw2, record = issue("좁은-키", allowed_operations=["summarize"], created_at=NOW)
    keys.add(record)
    r = client.post("/v1/ops/issue", json=op_body(), headers={"Authorization": f"Bearer {raw2}"})
    assert r.status_code == 403
    assert r.json()["code"] == "operation_not_allowed"


def test_operation_mode_not_allowed(app_fixture: Any) -> None:
    """운영 키(결정 수행만)로 자율 수행을 부르는 것을 막는다 — 계약의 핵심 하나."""
    client, raw, *_ = app_fixture
    r = client.post(
        "/v1/ops/summarize",
        json=op_body(mode=MODE_AUTONOMOUS, node_id="Task_sum"),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "mode_not_allowed"


def test_studio_key_may_use_autonomous(app_fixture: Any) -> None:
    client, _, keys, _, _ = app_fixture
    raw2, record = issue("개발-Studio", allowed_modes=[MODE_AUTONOMOUS, MODE_DETERMINISTIC], created_at=NOW)
    keys.add(record)
    r = client.post(
        "/v1/ops/summarize",
        json=op_body(mode=MODE_AUTONOMOUS, node_id="Task_sum"),
        headers={"Authorization": f"Bearer {raw2}"},
    )
    assert r.status_code == 200
    assert r.json()["mode_used"] == MODE_AUTONOMOUS


def test_mode_unsupported_by_the_operation(app_fixture: Any) -> None:
    """작업이 그 모드를 지원하지 않으면 422 — 받는 쪽이 모드를 바꾸지 않는다 (원칙 7)."""
    client, _, keys, _, _ = app_fixture
    raw2, record = issue("개발", allowed_modes=[MODE_AUTONOMOUS, MODE_DETERMINISTIC], created_at=NOW)
    keys.add(record)
    r = client.post(
        "/v1/ops/issue",  # issue는 deterministic만
        json=op_body(mode=MODE_AUTONOMOUS),
        headers={"Authorization": f"Bearer {raw2}"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "mode_unsupported"


def test_fallback_only_when_the_key_allows_autonomous(app_fixture: Any) -> None:
    """폴백은 **호출한 키가 자율 수행을 허용할 때만** 일어난다 (운영에서 LLM이 몰래 끼지 않게)."""
    client, raw, keys, _, _ = app_fixture
    # 운영 키 → 폴백하지 않고 실패
    r = client.post("/v1/ops/guess", json=op_body(node_id="Task_guess"),
                    headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 422
    assert r.json()["code"] == "mode_unsupported"

    # 개발 키 → 자율 수행으로 넘어가고, mode_used로 드러난다
    raw2, record = issue("개발", allowed_modes=[MODE_AUTONOMOUS, MODE_DETERMINISTIC], created_at=NOW)
    keys.add(record)
    r = client.post("/v1/ops/guess", json=op_body(node_id="Task_guess"),
                    headers={"Authorization": f"Bearer {raw2}"})
    assert r.status_code == 200
    assert r.json()["mode_used"] == MODE_AUTONOMOUS
    assert r.json()["output"]["mode_seen"] == MODE_AUTONOMOUS


def test_unknown_operation(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    r = client.post("/v1/ops/nope", json=op_body(), headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 404
    assert r.json()["code"] == "operation_not_found"


# ─────────────── 멱등 ───────────────


def test_same_idempotency_key_replays_without_running_again(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    h = {"Authorization": f"Bearer {raw}"}
    first = client.post("/v1/ops/issue", json=op_body(), headers=h)
    second = client.post("/v1/ops/issue", json=op_body(), headers=h)
    assert first.json()["replayed"] is False
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["output"] == first.json()["output"]


def test_different_attempt_is_a_new_call(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    h = {"Authorization": f"Bearer {raw}"}
    client.post("/v1/ops/issue", json=op_body(), headers=h)
    again = client.post("/v1/ops/issue", json=op_body(attempt=2), headers=h)
    assert again.json()["replayed"] is False


def test_same_key_with_a_different_body_conflicts(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    h = {"Authorization": f"Bearer {raw}"}
    client.post("/v1/ops/issue", json=op_body(), headers=h)
    r = client.post("/v1/ops/issue", json=op_body(input={"amount": 1}), headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "idempotency_conflict"


def test_float_input_does_not_break_idempotency(app_fixture: Any) -> None:
    """C2의 canonical_json은 실수를 금지하지만, 작업 입력은 서명 대상이 아니다."""
    client, raw, *_ = app_fixture
    h = {"Authorization": f"Bearer {raw}"}
    body = op_body(input={"rate": 0.075})
    assert client.post("/v1/ops/issue", json=body, headers=h).status_code == 200
    assert client.post("/v1/ops/issue", json=body, headers=h).json()["replayed"] is True


def test_failed_call_frees_the_idempotency_slot(app_fixture: Any) -> None:
    """실패한 호출은 자리를 비운다 — 같은 attempt로 한 번 더 부를 수 있어야 한다 (504·503 안내)."""
    keys = InMemoryKeyStore()
    raw, record = issue("운영", created_at=NOW)
    keys.add(record)
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
    client = TestClient(create_app(m, {"flaky": flaky}, keys=keys, now=lambda: NOW))
    h = {"Authorization": f"Bearer {raw}"}
    first = client.post("/v1/ops/flaky", json=op_body(), headers=h)
    assert first.status_code == 503
    assert first.json()["code"] == "dependency_down"
    second = client.post("/v1/ops/flaky", json=op_body(), headers=h)
    assert second.status_code == 200
    assert calls["n"] == 2


# ─────────────── 요청 검증 ───────────────


def test_higher_schema_is_refused_with_its_own_code(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    r = client.post("/v1/ops/issue", json=op_body(schema=2), headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 422
    assert r.json()["code"] == "schema_unsupported"


def test_missing_required_field_is_input_invalid(app_fixture: Any) -> None:
    client, raw, *_ = app_fixture
    body = op_body()
    del body["attempt"]
    r = client.post("/v1/ops/issue", json=body, headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 422
    assert r.json()["code"] == "input_invalid"


def test_error_body_shape_is_the_contract_one(app_fixture: Any) -> None:
    client, *_ = app_fixture
    body = client.post("/v1/ops/issue", json=op_body()).json()
    assert set(body) == {"code", "message", "detail"}


# ─────────────── 사용 기록 ───────────────


def test_usage_log_records_no_business_values(app_fixture: Any) -> None:
    """시각·키 이름·작업·모드·결과·소요·run_id·caller만. **입력·출력 값은 기록하지 않는다.**"""
    client, raw, _, log, _ = app_fixture
    client.post("/v1/ops/summarize", json=op_body(mode=MODE_DETERMINISTIC, node_id="Task_sum"),
                headers={"Authorization": f"Bearer {raw}"})
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.key_name == "운영-재무"
    assert entry.operation == "summarize"
    assert entry.status == 200
    assert entry.caller_type == "server_runner"
    assert entry.usage is not None
    assert entry.usage.model == "local-7b"
    dumped = entry.to_json_dict()
    assert "input" not in dumped
    assert "output" not in dumped
    assert "1100000" not in str(dumped)  # 업무 값이 새지 않는다


def test_failures_are_logged_too(app_fixture: Any) -> None:
    client, raw, _, log, _ = app_fixture
    client.post("/v1/ops/summarize", json=op_body(mode=MODE_AUTONOMOUS, node_id="Task_sum"),
                headers={"Authorization": f"Bearer {raw}"})
    assert [e.status for e in log.entries] == [403]


def test_last_used_at_is_updated(app_fixture: Any) -> None:
    client, raw, keys, _, _ = app_fixture
    assert keys.keys[0].last_used_at is None
    client.post("/v1/ops/issue", json=op_body(), headers={"Authorization": f"Bearer {raw}"})
    assert keys.keys[0].last_used_at == NOW


# ─────────────── 앱을 세울 때의 안전장치 ───────────────


def test_handlers_must_match_the_manifest() -> None:
    """manifest에 적었는데 함수가 없으면 404가 아니라 **만들 때** 터져야 한다."""
    with pytest.raises(ValueError, match="manifest의 작업과 handlers가 다르다"):
        create_app(manifest(), {"issue": handlers()["issue"]}, keys=InMemoryKeyStore())


def test_issued_key_shape() -> None:
    raw, record = issue("x")
    assert raw.startswith("chk_svc_")
    assert len(raw) == len("chk_svc_") + 40
    assert record.prefix == raw[:16]
    assert record.hash != raw  # 원문을 저장하지 않는다
    assert record.allowed_modes == [MODE_DETERMINISTIC]  # 기본은 운영 키

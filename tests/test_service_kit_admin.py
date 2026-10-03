"""C11 관리 API (`/admin/v1/*`) — 서비스 앱 관리 콘솔이 쓰는 것 (SVC-00~03).

업무 호출(`/v1/ops`)과 **권한이 다르다**. 그 경계가 이 파일의 핵심이다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import (
    CenterRegistration,
    Dependency,
    Operation,
    ServiceAppManifest,
    UsageRecord,
)
from chaeksas.service_kit import InMemoryKeyStore, InMemoryUsageLog, create_app

ADMIN = {"Authorization": "Bearer t-svc-admin"}


def manifest() -> ServiceAppManifest:
    return ServiceAppManifest(
        schema=1,
        app_id="ui-automation",
        name="UI 자동화",
        version="0.1.0",
        category="system",
        console_url="http://localhost:8001",
        operations=[
            Operation(name="plan", description="화면 계획", modes=["autonomous", "deterministic"]),
            Operation(name="heal", description="치유 제안", modes=["autonomous"], fallback="none"),
        ],
    )


@pytest.fixture
def store() -> InMemoryKeyStore:
    return InMemoryKeyStore()


@pytest.fixture
def log() -> InMemoryUsageLog:
    return InMemoryUsageLog()


@pytest.fixture
def client(store: InMemoryKeyStore, log: InMemoryUsageLog) -> Iterator[TestClient]:
    app = create_app(
        manifest(),
        {"plan": lambda _req, _mode: {"ok": True}, "heal": lambda _req, _mode: {"ok": True}},
        keys=store,
        usage_log=log,
        admin_token="t-svc-admin",
        dependencies=lambda: [Dependency(name="neo4j", status="ok"), Dependency(name="llm", status="degraded")],
        center=CenterRegistration(registered=True, base_url="http://svc-uia:8000"),
    )
    with TestClient(app) as found:
        yield found


# ─────────────────────────── 권한 경계 ───────────────────────────


def test_admin_api_is_closed_without_an_admin_token() -> None:
    """**빈 토큰으로 열리지 않는다** (C11). 설정하지 않으면 경로 전체가 503이다."""
    app = create_app(manifest(), {"plan": lambda _r, _m: {}, "heal": lambda _r, _m: {}}, keys=InMemoryKeyStore())
    with TestClient(app) as bare:
        for path in ("/admin/v1/status", "/admin/v1/keys", "/admin/v1/usage"):
            response = bare.get(path)
            assert response.status_code == 503, path
            assert response.json()["code"] == "admin_disabled"


def test_service_app_key_cannot_call_the_admin_api(client: TestClient) -> None:
    """업무 키로는 관리 API를 부를 수 없다 — 키를 가진 Bot이 다른 키를 발급하지 못한다."""
    created = client.post("/admin/v1/keys", json={"name": "운영"}, headers=ADMIN)
    assert created.status_code == 201
    business = {"Authorization": f"Bearer {created.json()['key']}"}
    assert client.get("/admin/v1/status", headers=business).status_code == 403
    assert client.get("/admin/v1/keys", headers=business).json()["code"] == "admin_only"


def test_missing_and_wrong_tokens_are_distinguished(client: TestClient) -> None:
    assert client.get("/admin/v1/status").json()["code"] == "token_missing"
    # 헤더 값은 ASCII다 — 틀린 토큰도 ASCII로 보낸다 (CLAUDE.md §5).
    wrong = {"Authorization": "Bearer wrong-token"}
    assert client.get("/admin/v1/status", headers=wrong).json()["code"] == "admin_only"


# ─────────────────────────── SVC-01 상태 ───────────────────────────


def test_status_carries_the_manifest_dependencies_and_center(client: TestClient) -> None:
    body = client.get("/admin/v1/status", headers=ADMIN).json()
    assert (body["app_id"], body["category"], body["version"]) == ("ui-automation", "system", "0.1.0")
    assert body["uptime_s"] >= 0
    assert [(o["name"], o["calls_24h"], o["error_rate"]) for o in body["operations"]] == [
        ("plan", 0, 0.0),
        ("heal", 0, 0.0),
    ]
    assert [(d["name"], d["status"]) for d in body["dependencies"]] == [("neo4j", "ok"), ("llm", "degraded")]
    assert body["center"]["registered"] is True


def test_status_counts_calls_and_errors_in_the_last_24h(client: TestClient, log: InMemoryUsageLog) -> None:
    now = datetime.now(UTC)
    for status, at in ((200, now), (200, now), (503, now), (200, now - timedelta(hours=30))):
        log.record(
            UsageRecord(
                at=at.isoformat(),
                key_name="운영",
                operation="plan",
                mode="deterministic",
                status=status,
                duration_ms=12,
            )
        )
    plan = next(o for o in client.get("/admin/v1/status", headers=ADMIN).json()["operations"] if o["name"] == "plan")
    # 30시간 전 호출은 창 밖이다.
    assert (plan["calls_24h"], plan["errors_24h"]) == (3, 1)
    assert plan["error_rate"] == pytest.approx(1 / 3, abs=1e-4)


# ─────────────────────────── SVC-02 키 ───────────────────────────


def test_issued_key_shows_its_raw_value_only_once(client: TestClient) -> None:
    created = client.post("/admin/v1/keys", json={"name": "finance-invoice"}, headers=ADMIN)
    assert created.status_code == 201
    raw = created.json()["key"]
    assert raw.startswith("chk_svc_")
    # 기본 권한은 **결정 수행만** (운영 키가 자율 수행을 못 하게, CLAUDE.md §5).
    assert created.json()["allowed_modes"] == ["deterministic"]

    listed = client.get("/admin/v1/keys", headers=ADMIN).json()
    assert [k["name"] for k in listed] == ["finance-invoice"]
    assert "key" not in listed[0] and "hash" not in listed[0], "원문·해시가 목록에 실리면 안 된다"
    assert listed[0]["prefix"] == raw[:16]


def test_key_names_are_unique(client: TestClient) -> None:
    """키 참조 이름과 맞추기를 권하므로(SVC-02), 이름이 겹치면 어느 키인지 알 수 없다."""
    assert client.post("/admin/v1/keys", json={"name": "운영"}, headers=ADMIN).status_code == 201
    again = client.post("/admin/v1/keys", json={"name": "운영"}, headers=ADMIN)
    assert again.status_code == 409 and again.json()["code"] == "name_conflict"


def test_issued_key_can_call_operations_and_a_revoked_one_cannot(client: TestClient) -> None:
    created = client.post(
        "/admin/v1/keys", json={"name": "운영", "allowed_operations": ["plan"]}, headers=ADMIN
    ).json()
    auth = {"Authorization": f"Bearer {created['key']}"}
    body = {
        "schema": 1,
        "mode": "deterministic",
        "run_id": "run_1",
        "node_id": "Task_plan",
        "node_instance": 1,
        "attempt": 1,
        "caller": {"type": "bot_ui"},
        "input": {},
    }
    assert client.post("/v1/ops/plan", json=body, headers=auth).status_code == 200
    # 허용 작업 밖은 403 (C11 `operation_not_allowed`).
    assert client.post("/v1/ops/heal", json=body, headers=auth).json()["code"] == "operation_not_allowed"

    revoked = client.delete("/admin/v1/keys/운영", headers=ADMIN)
    assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
    assert client.post("/v1/ops/plan", json=body, headers=auth).status_code == 403


def test_revoking_keeps_the_record(client: TestClient) -> None:
    """지우지 않는다 — 사용 기록이 그 이름을 가리킨다."""
    client.post("/admin/v1/keys", json={"name": "운영"}, headers=ADMIN)
    client.delete("/admin/v1/keys/운영", headers=ADMIN)
    listed = client.get("/admin/v1/keys", headers=ADMIN).json()
    assert [(k["name"], k["state"]) for k in listed] == [("운영", "revoked")]


def test_revoking_a_missing_key_is_404(client: TestClient) -> None:
    assert client.delete("/admin/v1/keys/없는키", headers=ADMIN).json()["code"] == "not_found"


def test_creating_a_key_without_a_name_is_refused(client: TestClient) -> None:
    assert client.post("/admin/v1/keys", json={}, headers=ADMIN).status_code == 422


# ─────────────────────────── SVC-03 사용 기록 ───────────────────────────


def test_usage_has_no_business_values(client: TestClient) -> None:
    """계약 원칙 6 — 입력·출력 값을 기록하지 않는다."""
    created = client.post("/admin/v1/keys", json={"name": "운영"}, headers=ADMIN).json()
    body = {
        "schema": 1,
        "mode": "deterministic",
        "run_id": "run_1",
        "node_id": "Task_plan",
        "node_instance": 1,
        "attempt": 1,
        "caller": {"type": "bot_ui"},
        "input": {"비밀번호": "절대 기록되면 안 된다"},
    }
    client.post("/v1/ops/plan", json=body, headers={"Authorization": f"Bearer {created['key']}"})

    page = client.get("/admin/v1/usage", headers=ADMIN)
    assert page.status_code == 200
    found = page.json()
    assert found["total"] == 1
    entry = found["items"][0]
    assert (entry["operation"], entry["status"], entry["key_name"]) == ("plan", 200, "운영")
    assert "절대 기록되면 안 된다" not in page.text
    assert "input" not in entry and "output" not in entry


def test_usage_limit_is_bounded(client: TestClient, log: InMemoryUsageLog) -> None:
    for i in range(5):
        log.record(
            UsageRecord(
                at=datetime.now(UTC).isoformat(),
                key_name="운영",
                operation="plan",
                mode="deterministic",
                status=200,
                duration_ms=i,
            )
        )
    assert len(client.get("/admin/v1/usage?limit=2", headers=ADMIN).json()["items"]) == 2
    assert client.get("/admin/v1/usage?limit=99999", headers=ADMIN).json()["total"] == 5

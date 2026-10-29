"""C11 관리 API (`/admin/v1/*`) — 서비스 앱 관리 콘솔이 쓰는 것 (SVC-00·01·03).

| 보는 것 | 왜 |
| --- | --- |
| 관리자 토큰이 없으면 **전부 503** — 빈 토큰으로 열리지 않는다 | C11 |
| 토큰이 없는 것과 틀린 것을 가른다 (`token_missing`·`admin_only`) | 콘솔이 할 일을 말한다 |
| 키 관리 경로(`/admin/v1/keys`)가 **없다** | 앱 안의 키가 없다 (ADR-0102) |
| 상태에 manifest·의존·「일꾼으로 들었나」가 실린다, 24시간 창으로 센다 | SVC-01 |
| 사용 기록에 업무 값이 없다, 개수 상한이 있다 | SVC-03, 원칙 6 |
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.external_task import LockedTask
from chaeksas.contracts.service_app import (
    CenterRegistration,
    Dependency,
    ExtensionRef,
    Operation,
    ServiceAppManifest,
    UsageRecord,
)
from chaeksas.service_kit import InMemoryUsageLog, create_app

ADMIN = {"Authorization": "Bearer t-svc-admin"}


def manifest() -> ServiceAppManifest:
    return ServiceAppManifest(
        schema=1,
        app_id="ui-automation",
        name="UI 자동화",
        version="0.1.0",
        category="system",
        console_url="http://localhost:8001",
        extension=ExtensionRef(id="ui-automation", version="0.4.0"),
        operations=[
            Operation(name="plan", description="화면 계획", modes=["autonomous", "deterministic"]),
            Operation(name="heal", description="치유 제안", modes=["autonomous"], fallback="none"),
        ],
    )


@pytest.fixture
def log() -> InMemoryUsageLog:
    return InMemoryUsageLog()


@pytest.fixture
def client(log: InMemoryUsageLog) -> Iterator[TestClient]:
    app = create_app(
        manifest(),
        {"plan": lambda _req, _mode: {"ok": True}, "heal": lambda _req, _mode: {"ok": True}},
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
    app = create_app(manifest(), {"plan": lambda _r, _m: {}, "heal": lambda _r, _m: {}})
    with TestClient(app) as bare:
        for path in ("/admin/v1/status", "/admin/v1/usage"):
            response = bare.get(path)
            assert response.status_code == 503, path
            assert response.json()["code"] == "admin_disabled"


def test_there_is_no_key_management(client: TestClient) -> None:
    """**앱 안의 키가 없다** (ADR-0102) — 「불러도 되나」는 Center가 배포로 가린다."""
    assert client.get("/admin/v1/keys", headers=ADMIN).status_code == 404
    assert client.post("/admin/v1/keys", json={"name": "운영"}, headers=ADMIN).status_code in (404, 405)


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
    # 콘솔이 이것으로 그 확장의 고유 화면(C13 `console.pages`)을 고른다 (ADR-0042).
    assert body["extension"] == {"id": "ui-automation", "version": "0.4.0"}


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


# ─────────────────────────── SVC-03 사용 기록 ───────────────────────────


def task(**over: Any) -> LockedTask:
    body: dict[str, Any] = {
        "task_id": "et_1",
        "topic": "ui-automation",
        "operation": "plan",
        "mode": "deterministic",
        "origin": "run",
        "idempotency": {"run_id": "run_1", "node_id": "Task_plan", "node_instance": 1, "attempt": 1},
        "caller": {"type": "bot_ui", "host": "pc_01"},
        "input": {"비밀번호": "절대 기록되면 안 된다"},
        "lock_until": "2026-10-02T10:10:00+09:00",
        "deadline": "2026-10-02T10:10:00+09:00",
    }
    return LockedTask.model_validate(body | over)


def test_usage_has_no_business_values(client: TestClient) -> None:
    """계약 원칙 6 — 입력·출력 값을 기록하지 않는다. 수행은 일꾼이 부르는 `app.state.ops`다."""
    ops = client.app.state.ops  # type: ignore[attr-defined]
    assert ops.execute(task()).ok

    page = client.get("/admin/v1/usage", headers=ADMIN)
    assert page.status_code == 200
    found = page.json()
    assert found["total"] == 1
    entry = found["items"][0]
    assert (entry["operation"], entry["status"], entry["key_name"]) == ("plan", 200, "bot_ui:pc_01")
    assert "절대 기록되면 안 된다" not in page.text
    assert "input" not in entry and "output" not in entry


def test_executed_tasks_show_up_in_the_status(client: TestClient) -> None:
    """일꾼이 수행한 일감이 SVC-01 통계로 센다 — 실패도 센다."""
    ops = client.app.state.ops  # type: ignore[attr-defined]
    ops.execute(task())
    ops.execute(task(operation="heal", mode="deterministic"))  # heal은 자율만 — 실패
    found = client.get("/admin/v1/status", headers=ADMIN).json()["operations"]
    stats = {o["name"]: (o["calls_24h"], o["errors_24h"]) for o in found}
    assert stats == {"plan": (1, 0), "heal": (1, 1)}


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

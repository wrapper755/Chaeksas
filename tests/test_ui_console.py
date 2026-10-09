"""관리 콘솔이 앱을 읽는 길 — UIA-01 개요 (C9 §관리 콘솔이 읽는 길, ADR-0042).

**관문은 하나다** — C11 관리 API와 같은 관리자 토큰(`service_kit.admin_guard`). 콘솔은 서비스
앱 키를 갖지 않으므로(ADR-0013) `registry_write` 키 대신 더 강한 관리자 토큰으로 읽는다.

거듭 보는 것 넷.

1. **토큰 없이는 안 열린다** — 업무 키로도 안 된다.
2. 셈은 레지스트리를 **그대로** 센 것이다 (공개 카탈로그와 같은 규칙).
3. 세션 기록은 **보고가 도착한 것만**이고 **시험은 따로 센다** (C8 `origin: test`).
4. 「배포 전 확인」은 **이 앱이 자기 힘으로 볼 수 있는 것만**이고 **막지 않는다**.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.ext.ui_automation.contracts.console import CHECK_OK, CHECK_WARN, ConsoleOverview
from chaeksas.ext.ui_automation.contracts.plan import (
    HealedReport,
    LocatorSpec,
    SessionReport,
)
from chaeksas.ext.ui_automation.contracts.registry import ElementHint, PageRegistration
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, Service, create
from chaeksas.ext.ui_automation.service.store import MAX_SESSIONS, Database, SessionStore
from chaeksas.service_kit import ServiceLlm, issue

ADMIN = {"Authorization": "Bearer t-admin"}
AT = "2026-10-09T10:15:00+00:00"
TODAY = AT[:10]


def page(page_id: str = "erp.order.form") -> PageRegistration:
    return PageRegistration(
        schema=1,
        page_id=page_id,
        name="ERP 주문 입력",
        platform="web",
        elements={"order.qty": ElementHint(name="수량", role="textbox")},
        locators={
            "order.qty": [
                LocatorSpec(type="test_id", value="qty"),
                LocatorSpec(type="css", value="#qty"),
            ]
        },
    )


def report(key: str, **over: Any) -> SessionReport:
    base: dict[str, Any] = {
        "schema": 1,
        "business_key": key,
        "page_id": "erp.order.form",
        "status": "succeeded",
        "origin": "run",
        "steps_completed": 3,
        "steps_total": 3,
    }
    return SessionReport.model_validate(base | over)


@pytest.fixture
def made(tmp_path: Path) -> Iterator[tuple[TestClient, Service]]:
    app = create(db_path=tmp_path / "uia.sqlite3", admin_token="t-admin", llm=ServiceLlm())
    service: Service = app.state.service
    with TestClient(app) as client:
        yield client, service


def overview(client: TestClient) -> ConsoleOverview:
    response = client.get("/admin/v1/overview", headers=ADMIN)
    assert response.status_code == 200, response.text
    return ConsoleOverview.model_validate(response.json())


# ─────────────────────────── 관문 ───────────────────────────


def test_the_console_path_is_closed_without_the_admin_token(made: tuple[TestClient, Service]) -> None:
    client, _ = made
    assert client.get("/admin/v1/overview").status_code == 401
    assert client.get("/admin/v1/overview", headers={"Authorization": "Bearer nope"}).status_code == 403


def test_a_business_key_cannot_read_the_console_path(made: tuple[TestClient, Service]) -> None:
    """**진짜 업무 키로도 못 본다** — 키를 가진 Bot이 콘솔 자료를 읽지 못한다 (C11 권한 경계).

    `registry_write`까지 있는 키로 해 본다 — 셀렉터를 보는 권한이어도 관리 경로는 다른 문이다.
    """
    client, service = made
    assert service.keys is not None
    raw, record = issue("등록 담당자", extra_scopes=[REGISTRY_WRITE])
    service.keys.add(record)
    assert client.get("/admin/v1/overview", headers={"Authorization": f"Bearer {raw}"}).status_code == 403


def test_the_path_is_disabled_without_an_admin_token_at_all(tmp_path: Path) -> None:
    """**빈 토큰으로 열리지 않는다** (C11) — 앱 고유 경로도 같다."""
    app = create(db_path=tmp_path / "uia.sqlite3", admin_token=None, llm=ServiceLlm())
    with TestClient(app) as bare:
        response = bare.get("/admin/v1/overview", headers=ADMIN)
        assert response.status_code == 503
        assert response.json()["code"] == "admin_disabled"


# ─────────────────────────── 셈 (UIA-01) ───────────────────────────


def test_the_counts_are_the_registry_counted(made: tuple[TestClient, Service]) -> None:
    client, service = made
    service.registry.register(page())
    service.flush()
    found = overview(client)
    assert (found.counts.pages, found.counts.elements, found.counts.locators) == (1, 1, 2)
    # **사람이 등록해도 `unverified`다** — 승격은 실행 통계로만 (C8).
    assert (found.counts.unverified, found.counts.active, found.counts.deprecated) == (2, 0, 0)
    assert found.revision >= 1


def test_the_counts_match_the_public_catalog_rule(made: tuple[TestClient, Service]) -> None:
    """화면별 셈(공개 카탈로그)을 더한 것과 같아야 한다 — 두 자리가 다르게 세면 안 된다."""
    client, service = made
    service.registry.register(page())
    service.registry.register(page("erp.order.list"))
    service.flush()
    catalog = service.registry.catalog()
    items = catalog["items"]
    assert isinstance(items, list)
    summed = sum(one["data"]["locator_summary"]["unverified"] for one in items)
    assert overview(client).counts.unverified == summed


# ─────────────────────────── 모델 (UIA-01) ───────────────────────────


def test_the_llm_section_says_it_is_not_connected(made: tuple[TestClient, Service]) -> None:
    client, _ = made
    found = overview(client).llm
    assert found.configured is False
    assert found.model == ""
    assert found.max_healing_attempts == 3, "계획에 실어 보내는 한도 (C8 Policy)"


def test_the_llm_section_never_shows_the_address_or_key(tmp_path: Path) -> None:
    """**주소·키는 보이지 않는다** (C11 §모델 연결)."""
    app = create(
        db_path=tmp_path / "uia.sqlite3",
        admin_token="t-admin",
        llm=ServiceLlm(client=object(), model="gpt-4o-mini"),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        raw = client.get("/admin/v1/overview", headers=ADMIN).text
    assert "gpt-4o-mini" in raw, "모델 이름은 보인다 (비밀이 아니다)"
    assert "api_key" not in raw and "base_url" not in raw


# ─────────────────────────── 세션 기록 (C8 → UIA-01) ───────────────────────────


def test_a_report_leaves_a_record(made: tuple[TestClient, Service]) -> None:
    """보고는 **기록으로도 남는다** — 세션이 끝날 때 오는 유일한 소식이다."""
    client, service = made
    service.registry.register(page())
    service.flush()
    assert service.sessions is not None
    service.sessions.record(report("run_20261009_101500_aaaaaa:T:1:1"), at=AT)
    service.sessions.record(
        report(
            "run_20261009_101600_bbbbbb:T:1:1",
            status="escalated",
            healed=[
                HealedReport(semantic_key="order.qty", locator=LocatorSpec(type="css", value="#qty2")).to_json_dict()
            ],
        ),
        at=AT,
    )
    found = overview(client).sessions
    assert (found.total, found.succeeded, found.escalated, found.healed) == (2, 1, 1, 1)


def test_a_test_report_is_counted_apart(made: tuple[TestClient, Service]) -> None:
    """셀렉터 시험(BUI-08)이 운영 통계를 흔들지 않는다 (C8 `origin: test`)."""
    client, service = made
    assert service.sessions is not None
    service.sessions.record(report("reg_12345678", origin="test"), at=AT)
    found = overview(client).sessions
    assert (found.total, found.test) == (0, 1)


def test_the_record_has_no_place_for_business_values(made: tuple[TestClient, Service]) -> None:
    """원칙 6 — C8 보고 자체에 읽은 값이 없고, 기록도 보고를 그대로 둔다."""
    client, service = made
    assert service.sessions is not None
    service.sessions.record(report("run_20261009_101500_aaaaaa:T:1:1"), at=AT)
    assert "주식회사" not in client.get("/admin/v1/overview", headers=ADMIN).text
    kept = service.sessions.recent(limit=1)[0].to_json_dict()
    assert set(kept) <= set(SessionReport.model_fields) | {"schema"}


def test_today_counts_only_today(tmp_path: Path) -> None:
    sessions = SessionStore(db=Database(path=tmp_path / "uia.sqlite3"))
    sessions.record(report("run_20261008_101500_aaaaaa:T:1:1"), at="2026-10-08T23:00:00+00:00")
    sessions.record(report("run_20261009_101500_bbbbbb:T:1:1"), at=AT)
    found = sessions.counts(today=TODAY)
    assert (found.total, found.today) == (2, 1)


def test_the_newest_report_for_a_key_wins(tmp_path: Path) -> None:
    sessions = SessionStore(db=Database(path=tmp_path / "uia.sqlite3"))
    key = "run_20261009_101500_aaaaaa:T:1:1"
    sessions.record(report(key), at=AT)
    sessions.record(report(key, status="failed"), at="2026-10-09T10:20:00+00:00")
    found = sessions.counts(today=TODAY)
    assert (found.total, found.failed, found.succeeded) == (1, 1, 0)


def test_old_records_fall_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """**오래된 것부터 버린다** — 모니터링 자료라 영원히 쌓지 않는다."""
    monkeypatch.setattr("chaeksas.ext.ui_automation.service.store.MAX_SESSIONS", 3)
    sessions = SessionStore(db=Database(path=tmp_path / "uia.sqlite3"))
    for n in range(5):
        sessions.record(report(f"run_20261009_1015{n:02d}_aaaaaa:T:1:1"), at=f"2026-10-09T10:1{n}:00+00:00")
    assert len(sessions.recent(limit=99)) == 3
    assert MAX_SESSIONS > 3, "기본값은 넉넉하다 (시험만 줄여 본다)"


# ─────────────────────────── 배포 전 확인 (UIA-01) ───────────────────────────


def test_the_checks_say_what_is_missing_and_do_not_block(made: tuple[TestClient, Service]) -> None:
    client, service = made
    found = {one.id: one for one in overview(client).checks}
    assert set(found) == {"llm", "registrar_key", "pages"}
    assert all(one.level == CHECK_WARN for one in found.values()), "빈 앱이면 셋 다 경고다"
    assert found["registrar_key"].detail and REGISTRY_WRITE in found["registrar_key"].detail
    # **막지 않는다** — 앱은 그대로 돈다 (업무 호출이 살아 있다).
    assert client.get("/healthz").status_code == 200
    assert service.registry.pages == {}


def test_a_registrar_key_turns_its_check_green(made: tuple[TestClient, Service]) -> None:
    client, service = made
    assert service.keys is not None
    service.keys.add(
        ServiceAppKey(name="등록 담당자", hash="a" * 64, prefix="chk_svc_111111", extra_scopes=[REGISTRY_WRITE])
    )
    service.keys.add(ServiceAppKey(name="운영", hash="b" * 64, prefix="chk_svc_222222"))
    found = {one.id: one for one in overview(client).checks}
    assert found["registrar_key"].level == CHECK_OK
    assert found["registrar_key"].detail == "1개", "권한 없는 키는 세지 않는다"


def test_a_revoked_registrar_key_does_not_count(made: tuple[TestClient, Service]) -> None:
    client, service = made
    assert service.keys is not None
    service.keys.add(
        ServiceAppKey(
            name="떠난 사람",
            hash="c" * 64,
            prefix="chk_svc_333333",
            extra_scopes=[REGISTRY_WRITE],
            revoked_at=AT,
        )
    )
    assert {one.id: one.level for one in overview(client).checks}["registrar_key"] == CHECK_WARN

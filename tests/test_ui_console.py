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

from chaeksas.contracts.service_app import Caller, OpRequest, ServiceAppKey
from chaeksas.ext.ui_automation.contracts.console import (
    CHECK_OK,
    CHECK_WARN,
    ConsoleOverview,
    PageDetail,
    PathResult,
    SessionPage,
)
from chaeksas.ext.ui_automation.contracts.plan import (
    AttemptReport,
    HealedReport,
    LocatorSpec,
    SessionReport,
)
from chaeksas.ext.ui_automation.contracts.registry import (
    CatalogEntry,
    ElementHint,
    LocatorStats,
    PageRegistration,
)
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


# ─────────── UIA-02 셀렉터 (화면 목록·화면 하나·경로) ───────────


def with_pages(service: Service) -> None:
    """두 화면 — 주문 입력(요소 둘, 저장이 완료 화면으로 이동)과 주문 완료."""
    service.registry.register(
        PageRegistration(
            schema=1,
            page_id="erp.order.form",
            name="ERP 주문 입력",
            platform="web",
            url_pattern="https://erp.example.com/order/*",
            elements={
                "order.qty": ElementHint(name="수량", role="textbox", description="주문 수량", kind="control"),
                "order.save": ElementHint(name="저장", role="button", kind="control"),
            },
            catalog={
                "order.qty": CatalogEntry(actions=["fill", "read"], concepts=["수량"]),
                "order.save": CatalogEntry(
                    actions=["click"], depends_on=["order.qty"], navigates_to="erp.order.done"
                ),
            },
            locators={
                "order.qty": [LocatorSpec(type="test_id", value="qty"), LocatorSpec(type="css", value="#qty")],
                "order.save": [LocatorSpec(type="role", value="button", name="저장")],
            },
        )
    )
    service.registry.register(
        PageRegistration(
            schema=1,
            page_id="erp.order.done",
            name="ERP 주문 완료",
            platform="web",
            locators={"done.msg": [LocatorSpec(type="css", value=".done")]},
        )
    )
    service.flush()


def test_the_page_listing_has_no_selectors(made: tuple[TestClient, Service]) -> None:
    """고르기 목록이다 — **셀렉터는 화면 하나를 열 때만** 나간다 (C9)."""
    client, service = made
    with_pages(service)
    response = client.get("/admin/v1/pages", headers=ADMIN)
    assert response.status_code == 200
    body = response.text
    assert "erp.order.form" in body and "ERP 주문 입력" in body
    assert "#qty" not in body and "test_id" not in body


def test_the_page_detail_carries_locators_stats_and_elements(made: tuple[TestClient, Service]) -> None:
    client, service = made
    with_pages(service)
    service.registry.stats[("erp.order.form", "order.qty", "test_id|qty|")] = LocatorStats(
        success=12, fail=9, streak=0
    )
    found = PageDetail.model_validate(
        client.get("/admin/v1/pages/erp.order.form", headers=ADMIN).json()
    )
    assert [one.semantic_key for one in found.locators] == ["order.qty", "order.qty", "order.save"]
    first = found.locators[0]
    assert (first.type, first.value, first.rank) == ("test_id", "qty", 2), "사다리 순서대로 (rank)"
    assert (first.success, first.fail) == (12, 9)
    assert first.success_rate == round(12 / 21, 4)
    # **센 적이 없으면 `None`** — 0%와 다르다.
    assert found.locators[1].success_rate is None
    assert [one.type for one in found.strategies] == ["css", "role", "test_id"]
    keys = {one.semantic_key: one for one in found.elements}
    assert keys["order.save"].navigates_to == "erp.order.done"
    assert keys["order.save"].depends_on == ["order.qty"]
    assert keys["order.qty"].concepts == ["수량"]


def test_a_page_we_do_not_have_is_404(made: tuple[TestClient, Service]) -> None:
    client, _ = made
    response = client.get("/admin/v1/pages/nope", headers=ADMIN)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_the_warning_band_comes_from_the_demotion_rule(made: tuple[TestClient, Service]) -> None:
    """C8 강등 규칙 — 최근 실패율이 높은 `active`를 **경고만** 한다 (자동 강등은 없다)."""
    client, service = made
    with_pages(service)
    page = service.registry.page("erp.order.form")
    page.locators["order.save"][0] = page.locators["order.save"][0].model_copy(update={"status": "active"})
    service.registry.stats[("erp.order.form", "order.save", "role|button|저장")] = LocatorStats(
        success=2, fail=9, streak=0
    )
    found = PageDetail.model_validate(
        client.get("/admin/v1/pages/erp.order.form", headers=ADMIN).json()
    )
    assert found.warnings and "order.save" in found.warnings[0]
    assert [one.status for one in found.locators if one.semantic_key == "order.save"] == ["active"]


def test_the_path_is_the_shortest_one_breadth_first(made: tuple[TestClient, Service]) -> None:
    """간선은 요소의 `navigates_to`다 (ADR-0040) — SQL에 밀어 넣지 않는다."""
    client, service = made
    with_pages(service)
    found = PathResult.model_validate(
        client.get("/admin/v1/path?start=erp.order.form&goal=erp.order.done", headers=ADMIN).json()
    )
    assert found.found and found.path == ["erp.order.form", "erp.order.done"]


def test_no_path_says_so_instead_of_pretending(made: tuple[TestClient, Service]) -> None:
    client, service = made
    with_pages(service)
    found = PathResult.model_validate(
        client.get("/admin/v1/path?start=erp.order.done&goal=erp.order.form", headers=ADMIN).json()
    )
    assert found.found is False and found.path == []
    # 등록되지 않은 화면도 「없다」다 (지어내지 않는다).
    assert service.registry.path("nope", "erp.order.form") == []
    assert service.registry.path("erp.order.form", "erp.order.form") == ["erp.order.form"]


def test_the_path_needs_both_ends(made: tuple[TestClient, Service]) -> None:
    client, _ = made
    response = client.get("/admin/v1/path?start=erp.order.form", headers=ADMIN)
    assert response.status_code == 422 and response.json()["code"] == "input_invalid"


# ─────────── UIA-03 모니터링 (이력·폴백 분포) ───────────


def op(report: SessionReport, *, host: str = "재무팀 PC-03") -> dict[str, Any]:
    """C11 봉투에 보고를 실어 보내는 모양 — `caller`·`mode`가 여기 있다."""
    return OpRequest(
        schema=1,
        mode="deterministic",
        run_id="run_20261009_101500_aaaaaa",
        node_id="Task_Fill",
        node_instance=1,
        attempt=1,
        caller=Caller(type="bot_ui", host=host, bpm_process_id="erp.order-entry", version="2.1.0"),
        input=report.to_json_dict(),
    ).to_json_dict()


def test_the_report_path_writes_what_the_envelope_said(made: tuple[TestClient, Service]) -> None:
    """UIA-03의 「Bot」·「Bot UI」·「요청 쪽」·「수행 모드」는 **봉투에서** 온다 (C8 보고에 없다)."""
    client, service = made
    with_pages(service)
    request = OpRequest.model_validate(op(report("run_20261009_101500_aaaaaa:Task_Fill:1:1")))
    service.report(request, "deterministic")
    row = SessionPage.model_validate(client.get("/admin/v1/sessions", headers=ADMIN).json()).rows[0]
    assert (row.caller, row.mode) == ("bot_ui", "deterministic")
    assert (row.bpm_process_id, row.host) == ("erp.order-entry", "재무팀 PC-03")
    assert row.report["business_key"] == "run_20261009_101500_aaaaaa:Task_Fill:1:1"


def test_a_healed_locator_is_marked_in_the_selector_table(made: tuple[TestClient, Service]) -> None:
    """레지스트리에는 「치유로 들어왔다」는 표시가 없다 — **보고에서** 모은다 (UIA-02)."""
    client, service = made
    with_pages(service)
    healed = report(
        "run_20261009_111500_bbbbbb:Task_Fill:1:1",
        healed=[
            HealedReport(
                semantic_key="order.qty",
                locator=LocatorSpec(type="css", value="#qty-new"),
                supersedes=["test_id|qty|"],
                reasoning="테스트 id가 사라졌다",
            ).to_json_dict()
        ],
    )
    service.report(OpRequest.model_validate(op(healed)), "deterministic")
    found = PageDetail.model_validate(
        client.get("/admin/v1/pages/erp.order.form", headers=ADMIN).json()
    )
    marked = [one for one in found.locators if one.healed]
    assert [one.value for one in marked] == ["#qty-new"], "사다리에 더해지고 치유 표시가 붙는다"
    assert marked[0].supersedes == ["test_id|qty|"]
    assert marked[0].status == "unverified", "치유가 찾은 것도 검증 전이다 (C8)"


def test_the_fallback_spread_counts_how_deep_we_went(made: tuple[TestClient, Service]) -> None:
    """`0`이 **1순위로 바로 성공**한 것이다. 끝까지 실패한 요소는 깊이가 아니다."""
    client, service = made
    assert service.sessions is not None
    service.sessions.record(
        report(
            "run_20261009_101500_aaaaaa:T:1:1",
            attempts=[
                AttemptReport(semantic_key="order.qty", locator_key="test_id|qty|", succeeded=True).to_json_dict(),
                AttemptReport(semantic_key="order.save", locator_key="role|button|저장", succeeded=True).to_json_dict(),
            ],
        ),
        at=AT,
    )
    service.sessions.record(
        report(
            "run_20261009_111500_bbbbbb:T:1:1",
            attempts=[
                AttemptReport(
                    semantic_key="order.qty", locator_key="test_id|qty|", succeeded=False, failure_reason="not_found"
                ).to_json_dict(),
                AttemptReport(semantic_key="order.qty", locator_key="css|#qty|", succeeded=True).to_json_dict(),
                AttemptReport(
                    semantic_key="order.save", locator_key="role|button|저장", succeeded=False
                ).to_json_dict(),
            ],
        ),
        at=AT,
    )
    found = SessionPage.model_validate(client.get("/admin/v1/sessions", headers=ADMIN).json()).fallback
    assert found.depths == {"0": 2, "1": 1}, "성공한 요소만 센다 (끝까지 실패한 것은 빠진다)"
    assert (found.first_hit, found.counted) == (2, 3)


def test_the_history_is_newest_first_and_bounded(made: tuple[TestClient, Service]) -> None:
    client, service = made
    assert service.sessions is not None
    for n in range(3):
        service.sessions.record(
            report(f"run_20261009_1015{n:02d}_aaaaaa:T:1:1"), at=f"2026-10-09T10:1{n}:00+00:00"
        )
    found = SessionPage.model_validate(client.get("/admin/v1/sessions?limit=2", headers=ADMIN).json())
    assert len(found.rows) == 2, "`limit`을 지킨다"
    assert found.rows[0].at and found.rows[0].at > (found.rows[1].at or ""), "새 것이 위"
    assert found.counts.total == 3, "요약은 기록 전부를 센다 (`limit`과 무관하다)"


def test_the_history_has_no_business_values(made: tuple[TestClient, Service]) -> None:
    """원칙 6 — 보고에 읽은 값이 없으니 이력에도 없다."""
    client, service = made
    assert service.sessions is not None
    service.sessions.record(report("run_20261009_101500_aaaaaa:T:1:1"), at=AT)
    raw = client.get("/admin/v1/sessions", headers=ADMIN).text
    assert "주식회사" not in raw and "010-" not in raw


def test_the_console_paths_need_the_admin_token(made: tuple[TestClient, Service]) -> None:
    """UIA-02·03도 같은 문이다 — 열어 둔 구멍이 없다."""
    client, _ = made
    for path in ("/admin/v1/pages", "/admin/v1/pages/x", "/admin/v1/path?start=a&goal=b", "/admin/v1/sessions"):
        assert client.get(path).status_code == 401, path


def test_an_old_database_gets_the_new_columns(tmp_path: Path) -> None:
    """이미 있는 파일에 **열만 더한다** — 기존 기록을 버리지 않는다."""
    import sqlite3

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE sessions (business_key TEXT PRIMARY KEY, at TEXT NOT NULL, page_id TEXT NOT NULL, "
            "origin TEXT NOT NULL, status TEXT NOT NULL, healed INTEGER NOT NULL DEFAULT 0, "
            "report_json TEXT NOT NULL);"
        )
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run_20261008_101500_aaaaaa:T:1:1", AT, "erp.order.form", "run", "succeeded", 0,
             report("run_20261008_101500_aaaaaa:T:1:1").model_dump_json()),
        )
    sessions = SessionStore(db=Database(path=path))
    rows = sessions.rows(limit=9)
    assert len(rows) == 1, "옛 기록이 남아 있다"
    assert (rows[0].caller, rows[0].mode) == ("", ""), "모르는 것은 비어 있다 (화면이 「—」로 보인다)"
    sessions.record(
        report("run_20261009_101500_bbbbbb:T:1:1"),
        at="2026-10-09T11:00:00+00:00",
        caller="studio",
        mode="autonomous",
    )
    assert [one.caller for one in sessions.rows(limit=9)] == ["studio", ""], "새 것이 위"

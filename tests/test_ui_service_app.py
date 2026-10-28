"""UI 자동화 앱 — 레지스트리의 서버 부분 (C9·C11·C15, M4 조각 8).

**진짜 Center에 일꾼으로 붙이고 진짜 클라이언트로 부른다** (ADR-0102 — 앱은 HTTP로 불리지 않는다).
그래야 일감·권한·저장이 한 줄로 맞물리는지 보인다. 작업 함수의 답만 볼 때(보고·멱등)는 작업 수행기
(`app.state.ops`)를 바로 부른다.

| 보는 것 | 왜 |
| --- | --- |
| 등록·셀렉터가 나가는 작업은 「셀렉터 등록」을 켠 PC만 (`registry_write`) | 셀렉터가 나간다 (C9·C15) |
| 목록·보고는 추가 권한이 없다 | BUI-06 콤보·실행 중 Bot의 보고 (C8) |
| 공개 카탈로그(Center에 올라간 것)에는 셀렉터가 없다 | 호출 토큰이면 누구나 읽는다 (C13 §5) |
| 등록은 더하기다, 바뀐 것이 없으면 `revision`도 안 오른다 | Worker 계획 캐시 (C9) |
| 다시 띄워도 남는다 (SQLite) | 메모리에만 있으면 되는 척이다 |
| 거절은 다시 보내지 않는다 (`permanent`) | 큐가 막힌다 |
| 같은 멱등 칸은 한 번만 한다 | 원칙 9 |

옛 시험 중 **키 권한**(`scope_missing` 403을 앱이 냈다)·**`/v1/catalog`·`/manifest` 경로**는 없어졌다 —
권한은 Center가 보고(C15 §올리기), 카탈로그·manifest는 일꾼이 Center에 올린다. 같은 뜻을 Center 쪽에서 본다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from uia_center import BOT, VERSION, UiaCenter, execute, running

from chaeksas.ext.ui_automation.client.registry_client import RegistryClient, RegistryProblem
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, SessionReport
from chaeksas.ext.ui_automation.contracts.registry import CatalogEntry, ElementHint, PageRegistration
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, create
from chaeksas.ext.ui_automation.worker.plans import CenterOps, OpsRefused


@pytest.fixture
def center(tmp_path: Path) -> Iterator[UiaCenter]:
    with running(tmp_path) as found:
        yield found


@pytest.fixture
def writer(center: UiaCenter) -> RegistryClient:
    """「셀렉터 등록」을 켠 PC의 도구 (TOL-03)."""
    return RegistryClient(base_url=center.url, call_token=center.pc_token())


@pytest.fixture
def stranger(center: UiaCenter) -> RegistryClient:
    """「셀렉터 등록」이 꺼진 PC의 도구."""
    return RegistryClient(base_url=center.url, call_token=center.pc_token(selector_registration=False))


def studio(center: UiaCenter) -> CenterOps:
    """Studio 시험 실행 (`test_…`) — 호출 토큰은 있지만 등록 권한은 없다."""
    return CenterOps(
        base_url=center.url, call_token=center.studio_token(), business_key="test_a1b2c3:Task_Ui:1:1",
        caller_type="studio",
    )


def page(page_id: str = "erp.order.form", **extra: Any) -> PageRegistration:
    body: dict[str, Any] = {
        "schema": 1,
        "page_id": page_id,
        "platform": "web",
        "name": "주문 입력",
        "locators": {
            "order.qty": [LocatorSpec(type="css", value="#qty")],
            "order.save": [LocatorSpec(type="role", value="button", name="저장", exact=True)],
        },
        "elements": {
            "order.qty": ElementHint(name="수량", kind="control"),
            "order.save": ElementHint(name="저장", kind="control"),
        },
    }
    body.update(extra)
    return PageRegistration.model_validate(body)


# ─────────────────────────── 권한 (C9·C15) ───────────────────────────


def test_a_pc_without_selector_registration_cannot_register(stranger: RegistryClient) -> None:
    """**「셀렉터 등록」을 켜지 않은 PC는 등록하지 못한다** — 셀렉터가 나가는 자리다 (C9, CON-03)."""
    with pytest.raises(RegistryProblem) as caught:
        stranger.register(page())
    assert caught.value.status == 403
    assert caught.value.code == "registration_off"
    assert caught.value.permanent, "4xx는 다시 보내지 않는다"


def test_without_registry_write_selectors_do_not_go_out(center: UiaCenter, writer: RegistryClient) -> None:
    """Studio 시험 실행도 **셀렉터는 못 읽는다** — `registry_write`는 그 PC의 스위치다 (C15)."""
    writer.register(page())
    with pytest.raises(OpsRefused) as caught:
        studio(center).call("registry_get_page", {"page_id": "erp.order.form"}, call_seq=1)
    assert (caught.value.status, caught.value.code) == (403, "scope_missing")


def test_listing_pages_needs_no_extra_scope(center: UiaCenter, writer: RegistryClient) -> None:
    """목록에는 셀렉터가 없다 — 등록 권한 없이 본다 (BUI-06 「화면 ID」 콤보)."""
    writer.register(page())
    found = studio(center).call("registry_list_pages", {}, call_seq=1)
    assert [one["page_id"] for one in found["pages"]] == ["erp.order.form"]
    assert found["pages"][0]["element_count"] == 2


def test_the_operations_that_carry_selectors_declare_registry_write(center: UiaCenter) -> None:
    """Center가 거는 권한은 **앱이 manifest에 적은 것**이다 (C11 `required_scopes`)."""
    scoped = {one.name for one in center.app.state.ops.manifest.operations if REGISTRY_WRITE in one.required_scopes}
    assert scoped == {"registry_get_page", "registry_register", "registry_delete"}


# ─────────────────────────── 등록 (C9) ───────────────────────────


def test_registering_a_new_page(writer: RegistryClient) -> None:
    found = writer.register(page())
    assert found.created_page
    assert len(found.created) == 2
    assert not found.unchanged


def test_registering_the_same_thing_changes_nothing(writer: RegistryClient) -> None:
    """같은 것을 다시 올려도 **Worker 계획 캐시가 버려지지 않는다** (C9)."""
    first = writer.register(page())
    again = writer.register(page())
    assert again.unchanged and again.created == []
    assert again.revision == first.revision, "바뀐 것이 없으면 revision도 그대로다"


def test_registering_adds_without_deleting(writer: RegistryClient) -> None:
    """**기존 것을 지우지 않는다** — 새 로케이터를 더한다 (C9)."""
    writer.register(page())
    writer.register(
        page(
            locators={"order.qty": [LocatorSpec(type="test_id", value="qty-input")]},
            elements={"order.qty": ElementHint(name="수량", kind="control")},
        )
    )
    found, _ = writer.get_page("erp.order.form")
    assert [one.type for one in found.locators["order.qty"]] == ["css", "test_id"]
    assert "order.save" in found.locators, "다른 요소는 그대로다"


def test_a_new_locator_is_unverified(writer: RegistryClient) -> None:
    """**사람이 검증해도 `unverified`**다 — `active`는 실행 통계로만 (C9·C8)."""
    writer.register(page())
    found, _ = writer.get_page("erp.order.form")
    assert {one.status for ladder in found.locators.values() for one in ladder} == {"unverified"}


def test_a_page_without_a_ladder_is_refused(writer: RegistryClient) -> None:
    """**사다리 없는 정보는 받지 않는다** (C9) — 보낸 쪽을 고쳐야 한다."""
    with pytest.raises(RegistryProblem) as caught:
        writer.register(page(locators={}, elements={"order.qty": ElementHint(name="수량"),
                                                    "order.save": ElementHint(name="저장")}))
    assert caught.value.status == 422
    assert caught.value.permanent


# ─────────────────────────── 삭제 (C9) ───────────────────────────


def test_deleting_an_element_says_what_went(writer: RegistryClient) -> None:
    writer.register(page())
    found = writer.delete("erp.order.form", "order.qty")
    assert (found.elements, found.locators) == (1, 1)
    left, _ = writer.get_page("erp.order.form")
    assert list(left.locators) == ["order.save"]


def test_deleting_something_pointed_at_needs_a_second_look(writer: RegistryClient) -> None:
    """끊길 경로가 있으면 `force` 없이는 막는다 (U9)."""
    writer.register(page())
    writer.register(
        page(
            "erp.order.list",
            locators={"list.new": [LocatorSpec(type="css", value="#new")]},
            elements={"list.new": ElementHint(name="새로", kind="control")},
            catalog={"list.new": CatalogEntry(actions=["click"], navigates_to="erp.order.form")},
        )
    )
    with pytest.raises(RegistryProblem) as caught:
        writer.delete("erp.order.form")
    assert caught.value.code == "has_links"
    assert caught.value.permanent

    forced = writer.delete("erp.order.form", force=True)
    assert forced.broken_links and forced.elements == 2


def test_the_links_that_would_break_reach_the_tool(writer: RegistryClient) -> None:
    """TOL-03은 「다른 화면이 가리키고 있습니다 — …」에 **끊길 경로**를 보인다 (U9)."""
    writer.register(page())
    writer.register(
        page(
            "erp.order.list",
            locators={"list.new": [LocatorSpec(type="css", value="#new")]},
            elements={"list.new": ElementHint(name="새로", kind="control")},
            catalog={"list.new": CatalogEntry(actions=["click"], navigates_to="erp.order.form")},
        )
    )
    with pytest.raises(RegistryProblem) as caught:
        writer.delete("erp.order.form")
    assert caught.value.detail["links"][0]["page_id"] == "erp.order.list"


def test_deleting_what_is_not_there(writer: RegistryClient) -> None:
    with pytest.raises(RegistryProblem) as caught:
        writer.delete("없는.화면")
    assert caught.value.code == "not_found"
    assert caught.value.permanent


# ─────────────────────────── 보고·승격 (C8) ───────────────────────────


def report(status: str = "succeeded", *, origin: str = "run") -> SessionReport:
    return SessionReport.model_validate(
        {
            "schema": 1,
            "business_key": "run_1:Task:1:1",
            "page_id": "erp.order.form",
            "origin": origin,
            "status": status,
            "attempts": [
                {
                    "semantic_key": "order.qty",
                    "locator_key": LocatorSpec(type="css", value="#qty").key,
                    "succeeded": True,
                }
            ],
        }
    )


def reported(center: UiaCenter, body: SessionReport, *, run: int = 1) -> dict[str, Any]:
    """보고 한 장을 작업 수행기에 준다 (보고는 결과를 기다리지 않으니 — C15 `want_result: false` — 답은 여기서 본다)."""
    found = execute(center.app, "report", body.to_json_dict(), run_id=f"run_20261029_09000{run}_aaaaaa")
    assert found.ok and found.response is not None, found
    return dict(found.response.output)


def test_three_runs_promote_a_locator(center: UiaCenter, writer: RegistryClient) -> None:
    """`active`는 **실행에서 세 번 연속 성공**해야 준다 (C9)."""
    writer.register(page())
    for run in (1, 2):
        assert reported(center, report(), run=run)["promoted"] == []
    promoted = reported(center, report(), run=3)["promoted"]
    assert promoted, "세 번째에 올라간다"
    found, _ = writer.get_page("erp.order.form")
    assert found.locators["order.qty"][0].status == "active"


def test_a_test_report_does_not_count(center: UiaCenter, writer: RegistryClient) -> None:
    """**`test` 보고는 통계에 넣지 않는다** — 셀렉터 시험은 승격 근거가 아니다 (BUI-08)."""
    writer.register(page())
    for run in range(5):
        reported(center, report(origin="test"), run=run)
    found, _ = writer.get_page("erp.order.form")
    assert found.locators["order.qty"][0].status == "unverified"


def test_a_report_needs_no_extra_scope(center: UiaCenter, writer: RegistryClient) -> None:
    """보고는 **실행 중 Bot의 호출 토큰**으로 온다 — 「셀렉터 등록」을 요구하면 안 된다 (C8)."""
    writer.register(page())
    bot = CenterOps(
        base_url=center.url,
        call_token=center.pc_token(selector_registration=False),
        business_key="run_20261029_100000_bbbbbb:Task_Ui:1:1",
        bpm_process_id=BOT,
        version=VERSION,
    )
    assert bot.call("report", report().to_json_dict(), call_seq=1) == {}, "보고는 결과를 기다리지 않는다"
    stats = center.app.state.service.registry.stats
    deadline = time.monotonic() + 10
    while not stats and time.monotonic() < deadline:
        time.sleep(0.05)
    assert stats, "일꾼이 가져가 통계에 넣었다"


# ─────────────────────────── 카탈로그·저장 ───────────────────────────


def test_the_public_catalog_has_no_selectors(center: UiaCenter, writer: RegistryClient) -> None:
    """일꾼이 Center에 올린 카탈로그는 **호출 토큰이면 누구나** 읽는다 — 셀렉터가 새면 안 된다 (C9·C13 §5)."""
    writer.register(page())
    body = str(center.catalog(center.studio_token()))
    assert "erp.order.form" in body
    assert "#qty" not in body and "css" not in body


def test_the_registry_survives_a_restart(tmp_path: Path, center: UiaCenter, writer: RegistryClient) -> None:
    """**메모리에만 있으면 되는 척이다** — 다시 띄워도 남아야 한다."""
    writer.register(page())
    again = create(db_path=tmp_path / "uia.sqlite3")
    found = again.state.service.registry.page("erp.order.form")
    assert list(found.locators) == ["order.qty", "order.save"]


def test_the_manifest_lists_the_operations(center: UiaCenter) -> None:
    """일꾼이 Center에 올리는 manifest (C15) — C7이 읽어 CON-07에 띄운다. **비밀이 들어가지 않는다**."""
    body = center.app.state.ops.manifest.to_json_dict()
    assert body["app_id"] == "ui-automation"
    names = {one["name"] for one in body["operations"]}
    assert names == {
        "registry_list_pages", "registry_get_page", "registry_register", "registry_delete",
        "plan", "heal", "report",
    }
    plan = next(one for one in body["operations"] if one["name"] == "plan")
    assert plan["modes"] == ["deterministic", "autonomous"], "자율 수행은 목표로 계획한다 (ADR-0035)"


# ─────────────────────────── 멱등 (C11) ───────────────────────────


def test_the_same_call_twice_is_done_once(center: UiaCenter, writer: RegistryClient) -> None:
    """C11 멱등 — 같은 `(run_id, node_id, node_instance, attempt, call_seq)`는 **한 번만** 한다.

    잠금이 지나 같은 일감이 다시 나가는 경우다 (C15 최소 한 번 실행, 원칙 9).
    """
    writer.register(page())
    slot = {"run_id": "reg_abcd1234", "node_id": "registry"}
    first = execute(center.app, "registry_delete", {"page_id": "erp.order.form"}, **slot)
    assert first.response is not None
    assert first.response.output["elements"] == 2 and not first.response.replayed

    writer.register(page())  # 다시 만들어 둔다 — 멱등이 아니면 또 지울 것이다
    again = execute(center.app, "registry_delete", {"page_id": "erp.order.form"}, **slot)
    assert again.response is not None and again.response.replayed, "저장된 답을 돌려준다"
    assert [one.page_id for one in writer.list_pages()] == ["erp.order.form"], (
        "두 번째 삭제가 실제로 일어나지 않았다"
    )


def test_a_resend_counts_as_a_new_attempt(center: UiaCenter, writer: RegistryClient) -> None:
    """C9 — 다시 보낼 때는 **`attempt`를 올린다**. 같은 `run_id`로, 등록은 늘 결정 수행이다."""
    for _ in range(2):
        with pytest.raises(RegistryProblem):
            writer.call("registry_register", {"page": {}}, run_id="reg_abcd1234")
    rows = center.store.rows("SELECT idempotency_json, mode FROM external_tasks ORDER BY created_at")
    slots = [json.loads(row["idempotency_json"]) for row in rows]
    assert [(one["run_id"], one["node_id"], one["attempt"]) for one in slots] == [
        ("reg_abcd1234", "registry", 1),
        ("reg_abcd1234", "registry", 2),
    ]
    assert {row["mode"] for row in rows} == {"deterministic"}, "등록은 LLM을 쓰지 않는다"

"""UI 화면 레지스트리와 승격 (C9·C8, M4 조각 5).

거듭 보는 것 여섯.

1. **사다리 없는 정보는 받지 않는다** — 설명만 있고 찾을 수 없는 요소는 쓸모가 없다.
2. **등록은 지우지 않는다** — 더한다. 같은 로케이터는 그대로 둔다.
3. **사람이 검증해도 `unverified`**다 — `active`는 **실행 통계로만** 준다 (C8).
4. **바뀐 것이 있을 때만 `revision`**이 오른다 — 아니면 Worker 계획 캐시가 공연히 버려진다.
5. **`test` 보고는 통계에 넣지 않는다** (셀렉터 시험, BUI-08).
6. **공개 카탈로그에 셀렉터가 없다** (C13 §5).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from chaeksas.ext.ui_automation.contracts.plan import (
    ACTIVE,
    DEPRECATED,
    ORIGIN_TEST,
    UNVERIFIED,
    AttemptReport,
    HealedReport,
    LocatorSpec,
    SessionReport,
)
from chaeksas.ext.ui_automation.contracts.registry import (
    CatalogEntry,
    ElementHint,
    PageRegistration,
    validate,
)
from chaeksas.ext.ui_automation.service.registry import HasLinks, Registry, RegistryError

PAGE = "erp.order.form"
KEY = "customer.name"


def locator(value: str, **extra: Any) -> LocatorSpec:
    return LocatorSpec(type="css", value=value, **extra)


def page(**extra: Any) -> PageRegistration:
    body: dict[str, Any] = {
        "schema": 1,
        "page_id": PAGE,
        "name": "ERP 주문 입력",
        "locators": {KEY: [locator("#customer")]},
        "elements": {KEY: ElementHint(description="고객명 칸", role="textbox", name="고객명")},
    }
    body.update(extra)
    return PageRegistration(**body)


def report(**extra: Any) -> SessionReport:
    body: dict[str, Any] = {
        "schema": 1,
        "business_key": "run_1:Task_Fill:1:1",
        "page_id": PAGE,
    }
    body.update(extra)
    return SessionReport(**body)


def ok(semantic_key: str, locator_key: str, *, succeeded: bool = True) -> AttemptReport:
    return AttemptReport(semantic_key=semantic_key, locator_key=locator_key, succeeded=succeeded)


# ─────────────────────────── 검사 (C9) ───────────────────────────


def test_information_without_a_ladder_is_refused() -> None:
    """설명만 있고 찾을 수 없는 요소는 쓸모가 없다."""
    problems = validate(page(elements={"없는키": ElementHint(description="뭔가")}))
    assert any(one.code == "no_ladder_for_info" for one in problems)


def test_a_role_locator_needs_a_name() -> None:
    """이름 없이 role 하나면 여럿이 맞는다 — 사다리가 쓸 수 없다."""
    problems = validate(page(locators={KEY: [LocatorSpec(type="role", value="textbox")]}))
    assert any(one.code == "role_needs_name" for one in problems)


def test_a_desktop_strategy_cannot_be_used_on_the_web() -> None:
    problems = validate(
        page(platform="web", locators={KEY: [LocatorSpec(type="automation_id", value="qty")]})
    )
    assert any(one.code == "strategy_mismatch" for one in problems)


def test_a_self_dependency_is_refused() -> None:
    problems = validate(page(catalog={KEY: CatalogEntry(depends_on=[KEY])}))
    assert any(one.code == "self_dependency" for one in problems)


def test_an_unknown_action_is_refused() -> None:
    """C10의 동작 목록 안에서만 쓴다."""
    problems = validate(page(catalog={KEY: CatalogEntry(actions=["춤추기"])}))
    assert any(one.code == "unknown_action" for one in problems)


@pytest.mark.parametrize("bad", ["Erp.Order", "1page", "한글화면"])
def test_a_bad_page_id_is_refused(bad: str) -> None:
    assert any(one.code == "page_id_invalid" for one in validate(page(page_id=bad)))


# ─────────────────────────── 등록 ───────────────────────────


def test_a_new_locator_is_unverified_even_if_a_human_checked_it() -> None:
    """사람이 화면에서 통과시켰어도 **그 순간 그 화면**에서만 참이다 (C8)."""
    registry = Registry()
    registry.register(page(locators={KEY: [locator("#customer", status=ACTIVE)]}))
    assert registry.page(PAGE).locators[KEY][0].status == UNVERIFIED


def test_registering_again_adds_and_keeps() -> None:
    """**기존 것을 지우지 않는다** — 화면 개편은 더하기와 `deprecated`로 한다."""
    registry = Registry()
    registry.register(page())
    found = registry.register(page(locators={KEY: [locator("#customer"), locator("#cust-name")]}))

    assert [one.locator_key for one in found.kept] == ["css|#customer|"]
    assert [one.locator_key for one in found.created] == ["css|#cust-name|"]
    assert len(registry.page(PAGE).locators[KEY]) == 2


def test_the_same_registration_does_not_bump_the_revision() -> None:
    """올라가면 Worker 계획 캐시가 공연히 버려진다 (C8 캐시 열쇠에 `revision`이 있다)."""
    registry = Registry()
    first = registry.register(page())
    again = registry.register(page())

    assert again.revision == first.revision
    assert again.unchanged and not again.created


def test_a_change_bumps_the_revision() -> None:
    registry = Registry()
    first = registry.register(page())
    again = registry.register(page(locators={KEY: [locator("#cust-name")]}))
    assert again.revision == first.revision + 1


def test_a_bad_page_is_refused_whole() -> None:
    registry = Registry()
    with pytest.raises(RegistryError):
        registry.register(page(locators={}))
    assert registry.pages_list() == []


# ─────────────────────────── 조회 ───────────────────────────


def test_the_ladder_uses_unverified_too() -> None:
    """치유로 찾은 것이 **바로 돌아야** 한다 (C8 — 조회는 `unverified`도 쓴다)."""
    registry = Registry()
    registry.register(page())
    assert [one.key for one in registry.ladder(PAGE, KEY)] == ["css|#customer|"]


def test_a_deprecated_locator_leaves_the_ladder() -> None:
    registry = Registry()
    registry.register(page())
    registry.page(PAGE).locators[KEY][0] = locator("#customer", status=DEPRECATED)
    assert registry.ladder(PAGE, KEY) == []


def test_listing_can_be_narrowed() -> None:
    registry = Registry()
    registry.register(page())
    registry.register(page(page_id="erp.order.done", locators={"done.msg": [locator("#done")]}, elements={}))
    assert [one.page_id for one in registry.pages_list(query="done")] == ["erp.order.done"]
    assert len(registry.pages_list()) == 2


# ─────────────────────────── 승격 (C8) ───────────────────────────


def test_three_runs_in_a_row_promote_a_locator() -> None:
    """**실행이 말해 주는 것**으로만 올린다."""
    registry = Registry()
    registry.register(page())
    for _ in range(2):
        registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    assert registry.page(PAGE).locators[KEY][0].status == UNVERIFIED

    promoted = registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    assert promoted == ["css|#customer|"]
    assert registry.page(PAGE).locators[KEY][0].status == ACTIVE


def test_a_failure_breaks_the_streak() -> None:
    registry = Registry()
    registry.register(page())
    registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    registry.apply(report(attempts=[ok(KEY, "css|#customer|", succeeded=False)]))
    registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    assert registry.page(PAGE).locators[KEY][0].status == UNVERIFIED, "연속이어야 한다"


def test_a_test_report_does_not_count() -> None:
    """셀렉터 시험(BUI-08)은 승격 근거가 아니다 (C8)."""
    registry = Registry()
    registry.register(page())
    for _ in range(5):
        registry.apply(report(origin=ORIGIN_TEST, attempts=[ok(KEY, "css|#customer|")]))
    assert registry.page(PAGE).locators[KEY][0].status == UNVERIFIED


def test_a_healed_locator_joins_the_ladder_as_unverified() -> None:
    """치유로 찾은 것은 사다리에 더해져 **바로 쓰인다** (C8)."""
    registry = Registry()
    registry.register(page())
    registry.apply(
        report(healed=[HealedReport(semantic_key=KEY, locator=locator("#cust-new"))])
    )
    ladder = registry.page(PAGE).locators[KEY]
    assert [one.key for one in ladder] == ["css|#customer|", "css|#cust-new|"]
    assert ladder[1].status == UNVERIFIED


def test_a_promoted_locator_deprecates_what_kept_failing() -> None:
    """새 것이 자리를 잡으면 **계속 실패하던 것**을 내린다."""
    registry = Registry()
    registry.register(page(locators={KEY: [locator("#old"), locator("#new")]}))
    for _ in range(3):
        registry.apply(
            report(attempts=[ok(KEY, "css|#old|", succeeded=False), ok(KEY, "css|#new|")])
        )
    found = {one.key: one.status for one in registry.page(PAGE).locators[KEY]}
    assert found["css|#new|"] == ACTIVE
    assert found["css|#old|"] == DEPRECATED


def test_failures_only_warn_they_do_not_demote() -> None:
    """자동 강등은 하지 않는다 — 사람이 본다 (UIA-02 띠)."""
    registry = Registry()
    registry.register(page())
    for _ in range(3):
        registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    for _ in range(12):
        registry.apply(report(attempts=[ok(KEY, "css|#customer|", succeeded=False)]))

    assert registry.page(PAGE).locators[KEY][0].status == ACTIVE, "내리지 않는다"
    assert registry.warnings(PAGE), "대신 경고한다"


# ─────────────────────────── 삭제 ───────────────────────────


def test_deleting_says_what_was_lost() -> None:
    """**되돌릴 수 없는 일이라 숫자로 남긴다** (C9)."""
    registry = Registry()
    registry.register(page(locators={KEY: [locator("#a"), locator("#b")]}))
    found = registry.delete(PAGE)
    assert found.elements == 1 and found.locators == 2
    assert registry.pages_list() == []


def test_deleting_an_element_keeps_the_page() -> None:
    registry = Registry()
    registry.register(page(locators={KEY: [locator("#a")], "submit": [locator("#save")]}))
    registry.delete(PAGE, KEY)
    assert list(registry.page(PAGE).locators) == ["submit"]


def test_a_linked_page_needs_a_second_look() -> None:
    """지우면 끊기는 길이 있다 — 사람이 한 번 더 본다 (U9)."""
    registry = Registry()
    registry.register(page())
    registry.register(
        page(
            page_id="erp.order.list",
            locators={"open": [locator("#open")]},
            elements={},
            catalog={"open": CatalogEntry(navigates_to=PAGE)},
        )
    )
    with pytest.raises(HasLinks) as caught:
        registry.delete(PAGE)
    assert caught.value.links[0].kind == "navigates_to"

    found = registry.delete(PAGE, force=True)
    assert found.broken_links, "무엇이 끊겼는지 남긴다"


def test_deleting_forgets_the_stats() -> None:
    registry = Registry()
    registry.register(page())
    registry.apply(report(attempts=[ok(KEY, "css|#customer|")]))
    registry.delete(PAGE)
    assert not registry.stats


# ─────────────────────────── 공개 카탈로그 (C13 §5) ───────────────────────────


def test_the_catalog_has_no_selectors() -> None:
    """**서버망 안에서만** 열지만, 그래도 셀렉터는 넣지 않는다."""
    registry = Registry()
    registry.register(
        page(catalog={KEY: CatalogEntry(actions=["fill", "read"], concepts=["고객"])})
    )
    raw = json.dumps(registry.catalog(), ensure_ascii=False)
    assert "#customer" not in raw and "css" not in raw
    assert "고객명 칸" not in raw, "치유 프롬프트용 설명도 빠진다"
    assert "고객명" in raw, "사람이 읽는 이름은 들어간다"


def test_the_catalog_revision_rises_with_any_change() -> None:
    """Center는 이 값이 같으면 다시 읽지 않는다 (C9)."""
    registry = Registry()
    before = registry.catalog()["revision"]
    registry.register(page())
    assert registry.catalog()["revision"] > before  # type: ignore[operator]


def test_the_catalog_counts_locator_states() -> None:
    registry = Registry()
    registry.register(page())
    data = registry.catalog()["items"][0]["data"]  # type: ignore[index]
    assert data["locator_summary"][UNVERIFIED] == 1
    assert data["elements"][0]["semantic_key"] == KEY

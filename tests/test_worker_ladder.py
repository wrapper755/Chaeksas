"""로케이터 사다리와 치유 (C8, M4 조각 2) — **Worker가 로컬에서 돈다**.

화면을 모르는 채로 시험한다 (`Finder`가 바깥 세계다). 그래서 브라우저 없이 사다리의 규칙을
모두 볼 수 있다.

거듭 보는 것 여섯.

1. **안정한 것부터** 탄다 (우선순위). `deprecated`는 **시도하지 않는다**.
2. **정확히 하나**에 맞아야 쓴다 — 둘 이상이면 엉뚱한 것을 누른다.
3. 폴백 도중에는 **네트워크를 타지 않는다** — 사다리가 다 실패해야 치유를 부른다.
4. **치유 제안도 확인한 뒤에 쓴다.**
5. 한도를 넘으면 **전환**이다 — 실패가 아니라 **사람에게 넘길 거리**다.
6. **치유 요청에 업무 값을 싣지 않는다** (원칙 6).
"""

from __future__ import annotations

from typing import Any

import pytest

from chaeksas.ext.ui_automation.contracts.plan import (
    DEPRECATED,
    ElementInfo,
    ExecutionPlan,
    HealRequest,
    HealResponse,
    LocatorSpec,
    PlanStep,
    Policy,
    masked,
)
from chaeksas.ext.ui_automation.worker.ladder import Match, run_step

KEY = "주문.수량"


def locator(type_: str, value: str, **extra: Any) -> LocatorSpec:
    return LocatorSpec(type=type_, value=value, **extra)


def plan(ladder: list[LocatorSpec], **extra: Any) -> ExecutionPlan:
    return ExecutionPlan(
        schema=1,
        plan_id="plan_1",
        page_id="erp.order.form",
        steps=[PlanStep(semantic_key=KEY, action="fill", value="3")],
        locators={KEY: ladder},
        elements={KEY: ElementInfo(description="주문 수량 입력칸", role="textbox")},
        **extra,
    )


class FakeScreen:
    """`Finder` — 어떤 로케이터가 몇 개에 맞는지 미리 정해 둔다."""

    def __init__(self, counts: dict[str, int], *, act_fails: bool = False) -> None:
        self.counts = counts
        self.looked: list[str] = []
        self.acted: list[PlanStep] = []
        self.act_fails = act_fails
        self.snapshots = 0

    def find(self, locator_: LocatorSpec, *, timeout_ms: int) -> Match:
        self.looked.append(locator_.key)
        count = self.counts.get(locator_.key, 0)
        return Match(count=count, handle=f"el:{locator_.key}" if count else None)

    def act(self, handle: object, step: PlanStep, *, timeout_ms: int) -> str | None:
        if self.act_fails:
            raise RuntimeError("칸이 읽기 전용이다")
        self.acted.append(step)
        return "한빛상사" if step.action.startswith("read") else None

    def snapshot(self) -> tuple[str, str]:
        self.snapshots += 1
        return ("<form>…</form>", "<input/>")

    def url(self) -> str:
        return "https://erp.example/orders"


# ─────────────────────────── 사다리 ───────────────────────────


def test_the_most_stable_locator_is_tried_first() -> None:
    """우선순위대로 — `role` 1, `test_id` 2, `css` 3, `xpath` 4 (C8)."""
    screen = FakeScreen({"css|#qty|": 1})
    ladder = [locator("xpath", "//input[1]"), locator("css", "#qty"), locator("role", "textbox", name="수량")]

    found = run_step(PlanStep(semantic_key=KEY, action="fill", value="3"), plan(ladder), screen)

    assert found.ok
    # 적은 차례가 아니라 **안정한 차례**로 탄다.
    assert screen.looked == ["role|textbox|수량", "css|#qty|"]
    assert found.fallback_depth == 1, "두 번째 로케이터로 성공했다"


def test_depth_zero_is_the_healthy_state() -> None:
    screen = FakeScreen({"role|textbox|수량": 1})
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("role", "textbox", name="수량"), locator("css", "#qty")]),
        screen,
    )
    assert found.ok and found.fallback_depth == 0 and not found.healed


def test_a_deprecated_locator_is_not_tried() -> None:
    """등록에서 버린 로케이터다 — 다시 시도하면 버린 뜻이 없다."""
    screen = FakeScreen({"css|#qty|": 1, "xpath|//old|": 1})
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("xpath", "//old", status=DEPRECATED), locator("css", "#qty")]),
        screen,
    )
    assert found.ok
    assert "xpath|//old|" not in screen.looked


def test_two_matches_are_refused() -> None:
    """둘 이상 맞으면 **엉뚱한 것을 누른다** — 다음 사다리로 간다."""
    screen = FakeScreen({"css|.qty|": 3, "xpath|//input[@id='qty']|": 1})
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", ".qty"), locator("xpath", "//input[@id='qty']")]),
        screen,
    )
    assert found.ok and found.fallback_depth == 1


def test_many_matches_are_allowed_when_the_policy_says_so() -> None:
    screen = FakeScreen({"css|.qty|": 3})
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", ".qty")], policy=Policy(require_unique_match=False)),
        screen,
    )
    assert found.ok


def test_a_step_without_a_ladder_says_so() -> None:
    """그림과 레지스트리가 어긋났다 — 조용히 넘어가지 않는다."""
    found = run_step(
        PlanStep(semantic_key="없는키", action="click"),
        plan([locator("css", "#qty")]),
        FakeScreen({}),
    )
    assert not found.ok and found.error_code == "unknown_semantic_key"


def test_a_failing_action_is_not_an_escalation() -> None:
    """찾기는 됐는데 조작이 실패했다 — 사람을 부를 일이 아니라 **오류**다."""
    screen = FakeScreen({"css|#qty|": 1}, act_fails=True)
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", "#qty")]),
        screen,
    )
    assert not found.ok and not found.escalated and found.error_code == "action_failed"


# ─────────────────────────── 치유 ───────────────────────────


def test_healing_is_not_called_while_the_ladder_still_works() -> None:
    """폴백 도중에는 **네트워크를 타지 않는다** (C8)."""
    called: list[HealRequest] = []
    screen = FakeScreen({"css|#qty|": 1})
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("role", "textbox", name="수량"), locator("css", "#qty")]),
        screen,
        heal=lambda request: called.append(request) or HealResponse(),  # type: ignore[func-returns-value]
    )
    assert found.ok and not called and screen.snapshots == 0


def test_healing_runs_only_after_the_whole_ladder_failed() -> None:
    screen = FakeScreen({"css|#qty-new|": 1})
    asked: list[HealRequest] = []

    def heal(request: HealRequest) -> HealResponse:
        asked.append(request)
        return HealResponse(locator=locator("css", "#qty-new"), reasoning="id가 바뀌었다")

    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("role", "textbox", name="수량"), locator("css", "#qty")]),
        screen,
        heal=heal,
    )
    assert found.ok and found.healed
    assert found.used is not None and found.used.key == "css|#qty-new|"
    assert asked[0].heal_attempt == 1
    assert asked[0].failure.tried == ["role|textbox|수량", "css|#qty|"], asked[0].failure.tried


def test_a_healed_locator_is_verified_before_use() -> None:
    """제안을 그대로 믿으면 **엉뚱한 것을 누른다** — 하나에 맞는지 본다."""
    screen = FakeScreen({"css|.many|": 5})
    tries = []

    def heal(request: HealRequest) -> HealResponse:
        tries.append(request.heal_attempt)
        return HealResponse(locator=locator("css", ".many"))

    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", "#qty")], policy=Policy(max_healing_attempts=3)),
        screen,
        heal=heal,
    )
    assert not found.ok and found.escalated
    assert tries == [1, 2, 3], "한도까지 다시 물어본다"


def test_no_suggestion_is_a_normal_branch() -> None:
    """제안할 것이 없을 수 있다 — 오류가 아니다 (횟수는 Worker가 센다)."""
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", "#qty")], policy=Policy(max_healing_attempts=2)),
        FakeScreen({}),
        heal=lambda request: HealResponse(locator=None),
    )
    assert found.escalated and found.error_code == "element_not_found"


def test_an_unreachable_app_stops_asking() -> None:
    """닿지 못하면 더 물어도 소용없다 — 캐시도 없다 (C8)."""
    calls = []

    def heal(request: HealRequest) -> HealResponse | None:
        calls.append(request)
        return None

    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", "#qty")], policy=Policy(max_healing_attempts=3)),
        FakeScreen({}),
        heal=heal,
    )
    assert len(calls) == 1
    assert found.escalated and found.error_code == "ui_automation_unreachable"


def test_without_a_healer_the_ladder_failure_escalates() -> None:
    found = run_step(
        PlanStep(semantic_key=KEY, action="fill", value="3"),
        plan([locator("css", "#qty")]),
        FakeScreen({}),
    )
    assert found.escalated and not found.healed


# ─────────────────────────── 값 가리기 (원칙 6) ───────────────────────────


def test_business_values_are_masked_before_healing() -> None:
    """스냅샷에 입력 값·표 셀이 그대로 나가면 업무 값이 바깥으로 샌다."""
    html = '<input value="한빛상사"/><td>1,250,000</td>'
    found = masked(html, ["한빛상사", "1,250,000"])
    assert "한빛상사" not in found and "1,250,000" not in found
    assert "<input value=" in found and "<td>" in found, "구조와 라벨은 남는다"


def test_masking_handles_overlapping_values() -> None:
    """긴 것부터 가린다 — 짧은 것을 먼저 가리면 긴 것이 조각나 남는다."""
    assert masked("한빛상사 주식회사", ["한빛상사", "한빛상사 주식회사"]) == "•••"


# ─────────────────────────── 사다리 모양 (C8) ───────────────────────────


def test_the_locator_key_leaves_out_control_type() -> None:
    """`control_type`은 좁히는 조건일 뿐 — 열쇠에 넣으면 같은 로케이터의 통계가 갈린다."""
    one = locator("class_name", "Edit", control_type="Edit", platform="desktop")
    other = locator("class_name", "Edit", platform="desktop")
    assert one.key == other.key == "class_name|Edit|"


@pytest.mark.parametrize(
    ("type_", "rank"),
    [("role", 1), ("test_id", 2), ("css", 3), ("xpath", 4), ("automation_id", 1), ("class_name", 2)],
)
def test_the_default_priority_is_stability_order(type_: str, rank: int) -> None:
    assert locator(type_, "값").rank == rank


def test_a_plan_knows_which_steps_have_no_ladder() -> None:
    made = ExecutionPlan(
        schema=1,
        plan_id="plan_1",
        page_id="p",
        steps=[PlanStep(semantic_key="가", action="click"), PlanStep(semantic_key="나", action="click")],
        locators={"가": [locator("css", "#a")]},
    )
    assert made.missing_keys() == ["나"]

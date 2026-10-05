"""계획·치유·보고 (C8, M4 조각 3) — 캐시와 큐.

거듭 보는 것 넷.

1. **계획은 캐시한다** — 서버에 닿지 못해도 돌던 Bot이 멈추지 않는다 (C10 `plan_source`).
2. **자율 수행(`goal`)은 캐시하지 않는다** — 같은 목표라도 계획이 다르다.
3. **보고는 먼저 디스크에 쓰고** 보낸다 — 보내다 죽어도 사라지지 않는다.
4. **4xx는 다시 보내지 않는다** — 한 번 거부된 것이 큐를 영원히 막는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chaeksas.ext.ui_automation.contracts.plan import (
    ExecutionPlan,
    LocatorSpec,
    PlanStep,
    SessionReport,
)
from chaeksas.ext.ui_automation.worker.plans import (
    DEAD_DIR,
    OP_PLAN,
    OP_REPORT,
    OpsRefused,
    OpsUnreachable,
    PlanCache,
    PlanService,
    ReportQueue,
    plan_key,
)

PLAN = {
    "schema": 1,
    "plan_id": "plan_1",
    "page_id": "erp.order.form",
    "revision": 3,
    "steps": [{"semantic_key": "주문.수량", "action": "fill", "value": "3"}],
    "locators": {"주문.수량": [{"type": "css", "value": "#qty"}]},
}


class FakeApp:
    """UI 자동화 앱 — 무엇을 물었는지 적어 두고, 시킨 대로 실패한다."""

    def __init__(self, *, unreachable: bool = False, refuse: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any], int]] = []
        self.unreachable = unreachable
        self.refuse = refuse

    def call(self, operation: str, body: dict[str, Any], *, call_seq: int) -> dict[str, Any]:
        self.calls.append((operation, body, call_seq))
        if self.unreachable:
            raise OpsUnreachable("닿지 못했다")
        if self.refuse:
            raise OpsRefused("계약과 맞지 않는다", status=422)
        return PLAN if operation == OP_PLAN else {}


def service(tmp_path: Path, app: FakeApp) -> PlanService:
    return PlanService(
        ops=app,
        cache=PlanCache(folder=tmp_path / "plans"),
        queue=ReportQueue(folder=tmp_path / "reports"),
    )


def report(key: str = "run_1:Task_Fill:1:1") -> SessionReport:
    return SessionReport(schema=1, business_key=key, page_id="erp.order.form")


def steps() -> list[PlanStep]:
    return [PlanStep(semantic_key="주문.수량", action="fill", value="3")]


# ─────────────────────────── 계획 ───────────────────────────


def test_a_plan_comes_from_the_server_and_is_cached(tmp_path: Path) -> None:
    app = FakeApp()
    made = service(tmp_path, app)

    plan, source = made.plan(page_id="erp.order.form", platform="web", steps=steps(), revision=3)
    assert source == "server" and plan.plan_id == "plan_1"
    assert made.cache.get(plan_key("erp.order.form", "web", steps(), 3)) is not None


def test_an_unreachable_app_falls_back_to_the_cache(tmp_path: Path) -> None:
    """서버가 꺼져도 돌던 Bot이 멈추지 않는다 (C10 `plan_source: cache`)."""
    made = service(tmp_path, FakeApp())
    made.plan(page_id="erp.order.form", platform="web", steps=steps(), revision=3)

    offline = service(tmp_path, FakeApp(unreachable=True))
    plan, source = offline.plan(page_id="erp.order.form", platform="web", steps=steps(), revision=3)
    assert source == "cache" and plan.plan_id == "plan_1"


def test_without_a_cache_an_unreachable_app_is_an_error(tmp_path: Path) -> None:
    """**없는데 된 척하지 않는다** — 계획 없이 화면을 만질 수 없다."""
    with pytest.raises(OpsUnreachable):
        service(tmp_path, FakeApp(unreachable=True)).plan(
            page_id="erp.order.form", platform="web", steps=steps()
        )


def test_an_autonomous_plan_is_not_cached(tmp_path: Path) -> None:
    """같은 목표라도 계획이 다르다 — 캐시하면 지난 계획을 다시 쓴다."""
    made = service(tmp_path, FakeApp())
    made.plan(page_id="erp.order.form", platform="web", steps=[], goal="주문을 넣는다")
    assert not list((tmp_path / "plans").glob("*.json"))


def test_a_different_revision_is_a_different_plan(tmp_path: Path) -> None:
    """레지스트리가 바뀌면 캐시도 바뀐다 (C9 `revision`)."""
    assert plan_key("p", "web", steps(), 1) != plan_key("p", "web", steps(), 2)


def test_different_steps_are_a_different_plan() -> None:
    other = [PlanStep(semantic_key="주문.저장", action="click")]
    assert plan_key("p", "web", steps(), 1) != plan_key("p", "web", other, 1)


def test_the_same_steps_with_other_values_share_a_plan() -> None:
    """**값은 열쇠가 아니다** — 수량이 3이든 5든 계획(사다리)은 같다."""
    other = [PlanStep(semantic_key="주문.수량", action="fill", value="5")]
    assert plan_key("p", "web", steps(), 1) == plan_key("p", "web", other, 1)


def test_a_broken_cache_file_is_ignored(tmp_path: Path) -> None:
    cache = PlanCache(folder=tmp_path / "plans")
    cache.folder.mkdir(parents=True)
    cache.path("키").write_text("{망가진", encoding="utf-8")
    assert cache.get("키") is None


def test_the_call_seq_counts_per_operation(tmp_path: Path) -> None:
    """C11 멱등 키가 겹치지 않게 — 세션 안에서 작업별로 센다 (C8 §전송)."""
    app = FakeApp()
    made = service(tmp_path, app)
    made.plan(page_id="p", platform="web", steps=steps())
    made.plan(page_id="p", platform="web", steps=steps())
    made.report(report())

    seqs = {(op, seq) for op, _, seq in app.calls}
    assert (OP_PLAN, 1) in seqs and (OP_PLAN, 2) in seqs
    assert (OP_REPORT, 1) in seqs, "작업마다 따로 센다"


# ─────────────────────────── 보고 ───────────────────────────


def test_a_report_is_written_before_it_is_sent(tmp_path: Path) -> None:
    """보내다 죽어도 보고가 사라지지 않는다."""
    app = FakeApp(unreachable=True)
    made = service(tmp_path, app)
    assert made.report(report()) == "queued"
    assert len(made.queue.waiting()) == 1


def test_a_sent_report_leaves_the_queue(tmp_path: Path) -> None:
    made = service(tmp_path, FakeApp())
    assert made.report(report()) == "sent"
    assert made.queue.waiting() == []


def test_a_refused_report_is_not_retried_forever(tmp_path: Path) -> None:
    """4xx는 다시 보내도 같다 — 큐를 막지 않게 옮긴다 (BUI-09 「밀린 보고」)."""
    made = service(tmp_path, FakeApp(refuse=True))
    assert made.report(report()) == "queued"
    assert made.queue.waiting() == []
    assert list((tmp_path / DEAD_DIR).glob("*.json")), "버린 자리에 남는다"


def test_the_queue_flushes_in_order_and_stops_at_the_first_outage(tmp_path: Path) -> None:
    """차례를 지킨다 — 막힌 뒤의 것을 먼저 보내지 않는다."""
    queue = ReportQueue(folder=tmp_path / "reports")
    queue.add(report("run_1:A:1:1"))
    queue.add(report("run_1:B:1:1"))

    sent, rejected = queue.flush(FakeApp(unreachable=True))
    assert (sent, rejected) == (0, 0) and len(queue.waiting()) == 2

    sent, rejected = queue.flush(FakeApp())
    assert (sent, rejected) == (2, 0) and queue.waiting() == []


def test_flushing_moves_refused_ones_aside(tmp_path: Path) -> None:
    queue = ReportQueue(folder=tmp_path / "reports")
    queue.add(report())
    sent, rejected = queue.flush(FakeApp(refuse=True))
    assert (sent, rejected) == (0, 1) and queue.waiting() == []


def test_the_queued_report_is_the_contract_shape(tmp_path: Path) -> None:
    queue = ReportQueue(folder=tmp_path / "reports")
    path = queue.add(report())
    body = json.loads(path.read_text(encoding="utf-8"))
    assert SessionReport.model_validate(body).business_key == "run_1:Task_Fill:1:1"


# ─────────────────────────── 치유 ───────────────────────────


def test_healing_through_the_service(tmp_path: Path) -> None:
    class Healing(FakeApp):
        def call(self, operation: str, body: dict[str, Any], *, call_seq: int) -> dict[str, Any]:
            self.calls.append((operation, body, call_seq))
            return {"locator": {"type": "css", "value": "#qty-new"}, "reasoning": "id가 바뀌었다"}

    from chaeksas.ext.ui_automation.contracts.plan import HealRequest

    made = service(tmp_path, Healing())
    answer = made.heal(HealRequest(schema=1, page_id="p", semantic_key="주문.수량"))
    assert answer is not None and answer.locator is not None
    assert answer.locator.key == "css|#qty-new|"


def test_an_unreachable_app_gives_no_suggestion(tmp_path: Path) -> None:
    """닿지 못하면 `None` — 사다리가 전환으로 넘긴다 (예외를 던지지 않는다)."""
    from chaeksas.ext.ui_automation.contracts.plan import HealRequest

    made = service(tmp_path, FakeApp(unreachable=True))
    assert made.heal(HealRequest(schema=1, page_id="p", semantic_key="가")) is None


def test_a_plan_knows_its_ladder() -> None:
    made = ExecutionPlan.model_validate(PLAN)
    assert [one.key for one in made.ladder("주문.수량")] == ["css|#qty|"]
    assert made.missing_keys() == []
    assert isinstance(made.locators["주문.수량"][0], LocatorSpec)

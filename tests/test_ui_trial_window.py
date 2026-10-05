"""BUI-08 셀렉터 시험 화면 (M4 조각 12).

화면 없이 돈다 (`QT_QPA_PLATFORM=offscreen`). Worker·레지스트리는 가짜다 — **진짜로
도는 한 바퀴**는 `tests/test_ui_end_to_end.py`가 본다.

거듭 보는 것 다섯.

1. **기본은 보고하지 않는다** — 시험이 서버 통계를 건드리면 안 된다.
2. 보고를 켜도 **`test`로 간다** (등록 세션이라 C8이 그렇게 표시한다) — 승격에 안 들어간다.
3. **읽어온 값은 화면에만** 보인다 (원칙 6).
4. **전환은 실패가 아니다** — 거기서 멈추고 「사람에게 전환」이라고 적는다.
5. 세션은 한 번에 하나라 **시험을 시작하면 등록 탭이 쥔 것을 놓는다** (ADR-0014).
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.ext.ui_automation.client.trial_window import TrialWidget  # noqa: E402
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec  # noqa: E402
from chaeksas.ext.ui_automation.contracts.registry import (  # noqa: E402
    ElementHint,
    PageRegistration,
)
from chaeksas.ext.ui_automation.contracts.worker_local import (  # noqa: E402
    CloseResult,
    SessionInfo,
    SessionSummary,
    StepResult,
)

KEY = "chk_svc_" + "t" * 40


class FakeWorker:
    """C10을 흉내 낸다. **무엇을 보냈는지**를 남긴다."""

    def __init__(self, *, results: list[StepResult] | None = None) -> None:
        self.opened: list[Any] = []
        self.steps: list[Any] = []
        self.closed: list[str] = []
        self.results = results or []
        self.report_state = "sent"

    def open(self, request: Any) -> SessionInfo:
        self.opened.append(request)
        return SessionInfo(session_id="ses_t", session_secret="s3cret", plan_source="server")

    def step(self, session_id: str, secret: str, request: Any) -> StepResult:
        self.steps.append(request)
        if self.results:
            return self.results.pop(0)
        return StepResult(ok=True, semantic_key=request.semantic_key, action=request.action)

    def close(self, session_id: str, secret: str) -> CloseResult:
        self.closed.append(session_id)
        return CloseResult(steps_run=len(self.steps), summary=SessionSummary(result="success"),
                           report=self.report_state)


class FakeRegistry:
    def __init__(self, *, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or []

    def get_page(self, page_id: str) -> tuple[PageRegistration, list[str]]:
        return (
            PageRegistration(
                schema=1,
                page_id=page_id,
                url_pattern="https://erp.example/orders",
                revision=3,
                locators={
                    "order.qty": [LocatorSpec(type="css", value="#qty")],
                    "order.total": [LocatorSpec(type="css", value="#total")],
                },
                elements={
                    "order.qty": ElementHint(name="수량", kind="control"),
                    "order.total": ElementHint(name="합계", kind="text"),
                },
            ),
            self.warnings,
        )


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


@pytest.fixture
def made(app: Any) -> Any:
    worker = FakeWorker()
    widget = TrialWidget(worker, FakeRegistry(), service_key=KEY)
    widget.page_id.setCurrentText("erp.order.form")
    yield widget, worker
    widget.close()


def text(widget: Any) -> str:
    return str(widget.output.toPlainText())


# ─────────────────────────── 가져오기 ───────────────────────────


def test_fetching_fills_the_steps_from_the_registry(made: Any) -> None:
    """자연어 목표가 없으니 **등록된 것에서 출발**한다 — 사람이 고친다."""
    widget, _ = made
    widget.fetch()
    assert widget.steps.rowCount() == 2
    assert [one[0] for one in widget.plan_steps()] == ["order.qty", "order.total"]
    assert widget.start_url.text() == "https://erp.example/orders", "계획의 주소를 채운다"
    assert "판 3" in text(widget)


def test_the_default_action_follows_the_kind(made: Any) -> None:
    widget, _ = made
    widget.fetch()
    by_key = {one[0]: one[1] for one in widget.plan_steps()}
    assert by_key["order.qty"] == "click"
    assert by_key["order.total"] == "read", "글자는 읽기가 기본이다"


def test_a_goal_is_off_and_says_why(made: Any) -> None:
    """**없는 것을 되는 척하지 않는다** — 목표로 계획은 모델이 붙는다."""
    widget, _ = made
    assert not widget.goal.isEnabled()
    assert "자율 수행" in widget.goal.toolTip()


def test_warnings_from_the_registry_are_shown(app: Any) -> None:
    widget = TrialWidget(FakeWorker(), FakeRegistry(warnings=["order.qty 실패가 잦습니다"]), service_key=KEY)
    widget.page_id.setCurrentText("erp.order.form")
    widget.fetch()
    assert "경고: order.qty 실패가 잦습니다" in text(widget)
    widget.close()


# ─────────────────────────── 실행 ───────────────────────────


def test_running_sends_each_step_and_says_the_result(made: Any) -> None:
    widget, worker = made
    widget.fetch()
    widget.run()
    assert [one.semantic_key for one in worker.steps] == ["order.qty", "order.total"]
    assert "[계획 출처: 서버]" in text(widget)
    assert "결과: 성공 — 2/2 스텝" in text(widget)


def test_nothing_to_run_is_said_plainly(made: Any) -> None:
    widget, worker = made
    widget.run()
    assert "스텝이 없습니다" in text(widget)
    assert worker.opened == []


def test_the_read_value_stays_on_the_screen(made: Any) -> None:
    """**읽어온 값은 화면에만** 보인다 — 보고에는 들어가지 않는다 (원칙 6)."""
    worker = FakeWorker(
        results=[
            StepResult(ok=True, semantic_key="order.qty", action="click"),
            StepResult(ok=True, semantic_key="order.total", action="read", text="합계 1,200,000원"),
        ]
    )
    widget = TrialWidget(worker, FakeRegistry(), service_key=KEY)
    widget.page_id.setCurrentText("erp.order.form")
    widget.fetch()
    widget.run()
    assert "1,200,000" in text(widget)
    widget.close()


def test_an_escalation_stops_and_is_not_called_a_failure(made: Any) -> None:
    """**전환은 실패가 아니다** — 사람이 봐야 한다는 뜻이다 (C10)."""
    worker = FakeWorker(
        results=[StepResult(ok=False, semantic_key="order.qty", action="click", escalated=True,
                            error="사다리가 모두 실패했다")]
    )
    widget = TrialWidget(worker, FakeRegistry(), service_key=KEY)
    widget.page_id.setCurrentText("erp.order.form")
    widget.fetch()
    widget.run()
    assert "사람에게 전환" in text(widget)
    assert "결과: 사람에게 전환 — 0/2 스텝" in text(widget)
    assert len(worker.steps) == 1, "전환에서 멈춘다"
    widget.close()


def test_a_fallback_is_shown(made: Any) -> None:
    worker = FakeWorker(
        results=[StepResult(ok=True, semantic_key="order.qty", action="click", fallback_depth=2, healed=True)]
    )
    widget = TrialWidget(worker, FakeRegistry(), service_key=KEY)
    widget.page_id.setCurrentText("erp.order.form")
    widget._add_step("order.qty", "click", "")  # noqa: SLF001
    widget.run()
    assert "사다리 3번째 칸" in text(widget) and "자가 치유" in text(widget)
    widget.close()


# ─────────────────────────── 보고 ───────────────────────────


def test_reporting_is_off_by_default(made: Any) -> None:
    """**시험이 서버 통계를 건드리지 않는다** — 아예 보내지 않는다 (C10 `report`)."""
    widget, worker = made
    assert not widget.report.isChecked()
    widget.fetch()
    widget.run()
    assert worker.opened[0].report is False
    widget.close_browser()
    assert "보고하지 않았습니다" in text(widget)


def test_reporting_can_be_turned_on(made: Any) -> None:
    widget, worker = made
    widget.report.setChecked(True)
    widget.fetch()
    widget.run()
    assert worker.opened[0].report is True
    widget.close_browser()
    assert "승격 통계에는 들어가지 않습니다" in text(widget)


def test_a_queued_report_says_so(made: Any) -> None:
    widget, worker = made
    worker.report_state = "queued"
    widget.report.setChecked(True)
    widget.fetch()
    widget.run()
    widget.close_browser()
    assert "큐에 쌓았습니다" in text(widget)


def test_the_session_is_a_registration_one(made: Any) -> None:
    """등록 세션이라 **보고가 `test`로** 간다 (C8) — 승격 통계에 들어가지 않는다."""
    widget, worker = made
    widget.fetch()
    widget.run()
    sent = worker.opened[0]
    assert sent.caller.type == "selector_registration"
    assert sent.business_key.startswith("reg_")
    assert sent.service_key == KEY, "계획을 받아 오려면 키가 있어야 한다"


def test_without_a_key_it_does_not_pretend(app: Any) -> None:
    widget = TrialWidget(FakeWorker(), FakeRegistry(), service_key=None)
    widget.page_id.setCurrentText("erp.order.form")
    widget.fetch()
    widget.run()
    assert "등록 담당자 키가 없어" in text(widget)
    widget.close()


# ─────────────────────────── 브라우저 ───────────────────────────


def test_the_browser_stays_open_by_default(made: Any) -> None:
    widget, worker = made
    widget.fetch()
    widget.run()
    assert worker.closed == [], "끝나도 열어 둔다 (무엇이 잘못됐는지 보려면 화면이 있어야 한다)"
    assert "브라우저를 열어 두었습니다" in text(widget)
    assert widget.close_button.isEnabled()


def test_it_can_close_when_asked(made: Any) -> None:
    widget, worker = made
    widget.keep_open.setChecked(False)
    widget.fetch()
    widget.run()
    assert worker.closed == ["ses_t"]
    assert not widget.close_button.isEnabled()


def test_starting_a_trial_releases_the_other_tab(app: Any) -> None:
    """**세션은 한 번에 하나다** (ADR-0014) — 등록 탭이 쥐고 있으면 놓게 한다."""
    released: list[bool] = []
    widget = TrialWidget(
        FakeWorker(), FakeRegistry(), service_key=KEY, release_other=lambda: released.append(True)
    )
    widget.page_id.setCurrentText("erp.order.form")
    widget.fetch()
    widget.run()
    assert released == [True]
    widget.close()

"""확장이 플랫폼 화면에 칸을 그린다 (C13 `bot_ui.panels`, ADR-0042) — BUI-09 「최근 UI 세션」.

**플랫폼은 칸 안을 모른다.** Bot UI는 자리(`surface`)만 주고, 표의 열(화면·폴백 깊이·치유)은
확장이 그린다 (ADR-0018). 그래서 여기서 보는 것은 셋이다.

1. 호스트가 **자리 이름으로** 칸을 고른다 — 모르는 자리를 가리키는 칸은 조용히 사라진다.
2. Bot UI가 그 칸을 BUI-09에 끼우고 **주기마다 `refresh()`를 부른다** (패널이 타이머를 만들지
   않는다). `runtime`을 적은 칸은 그 런타임이 떠 있을 때만 보인다.
3. 칸이 터져도 **화면은 산다** — 그 칸만 접고 사유를 보인다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import FakeCredentials  # noqa: E402

from chaeksas.bot_ui.agent import Agent  # noqa: E402
from chaeksas.bot_ui.settings import Settings  # noqa: E402
from chaeksas.bot_ui.store import Store  # noqa: E402
from chaeksas.contracts.extension import SURFACE_BOT_UI_RUNTIMES  # noqa: E402
from chaeksas.core.extensions import load_host  # noqa: E402
from chaeksas.ext.ui_automation.client.panels import (  # noqa: E402
    COLUMNS,
    EMPTY,
    UNREACHABLE,
    RecentSessionsPanel,
    rows_of,
)
from chaeksas.ext.ui_automation.contracts.worker_local import SessionBrief, Status  # noqa: E402
from chaeksas.extension_api import BotUiPanel  # noqa: E402

PANEL_ID = "recent-ui-sessions"
BUILTIN_ID = "ui-automation"
AT = "2026-10-09T09:15:30+09:00"


@pytest.fixture
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
def agent(tmp_path: Path) -> Agent:
    return Agent(
        settings=Settings(name="재무팀 PC-03"),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
        host=load_host(),
    )


class FakeWorker:
    """C10 `/v1/status`를 흉내 낸다. `fail`이면 닿지 못한 것으로 둔다."""

    def __init__(self, status: Status | None = None, *, fail: bool = False) -> None:
        self.status = status or Status()
        self.fail = fail
        self.calls: list[str] = []

    def call(self, method: str, path: str, **_: Any) -> dict[str, Any]:
        self.calls.append(f"{method} {path}")
        if self.fail:
            raise RuntimeError("Worker에 닿지 못했다")
        return self.status.to_json_dict()


def brief(**over: Any) -> SessionBrief:
    base: dict[str, Any] = {
        "session_id": "s1",
        "business_key": "run_20261009_091500_abcdef:Task_Fill:1:1",
        "caller": "bot",
        "page_id": "erp.order.form",
        "result": "success",
        "steps": 6,
        "fallback_depth_max": 1,
        "healed": False,
        "at": AT,
    }
    return SessionBrief.model_validate(base | over)


# ─────────────────── 호스트가 자리로 고른다 ───────────────────


def test_the_host_picks_panels_by_surface() -> None:
    host = load_host()
    found = host.panels(SURFACE_BOT_UI_RUNTIMES)
    assert [c.value.id for c in found] == [PANEL_ID]
    assert found[0].value.runtime == "worker", "Worker가 떠 있을 때만 보이는 칸이다"
    assert host.panels("bot_ui.nowhere") == [], "모르는 자리는 조용히 사라진다 (ADR-0042)"


def test_the_panel_resolves_and_matches_the_interface() -> None:
    host = load_host()
    assert isinstance(host.panel(BUILTIN_ID, PANEL_ID), BotUiPanel)
    with pytest.raises(LookupError, match="화면 칸이 아니다"):
        host.panel(BUILTIN_ID, "nope")


# ─────────────────── 표의 줄 (C10 → BUI-09) ───────────────────


def test_the_rows_are_the_columns_the_screen_asks_for() -> None:
    """BUI-09 문서의 열 그대로다 — 시각·요청한 쪽·화면·결과·폴백 깊이·치유."""
    assert COLUMNS == ("시각", "요청한 쪽", "화면", "결과", "폴백 깊이", "치유")
    rows = rows_of(Status(recent_sessions=[brief(), brief(caller="studio", result="escalated", healed=True)]))
    assert rows[0] == ("09:15:30", "Bot", "erp.order.form", "성공", "1", "아니오")
    assert rows[1] == ("09:15:30", "Studio", "erp.order.form", "사람에게 전환", "1", "예")


def test_the_rows_carry_no_business_values() -> None:
    """원칙 6 — 무엇을 입력했고 읽었는지는 C10 요약에 없고 표에도 없다."""
    rows = rows_of(Status(recent_sessions=[brief()]))
    flat = " ".join(rows[0])
    assert "run_20261009" not in flat, "실행 id(업무 키)는 열이 아니다"


def test_an_unknown_caller_or_result_is_shown_as_it_came() -> None:
    """열린 문자열이다 (원칙 10) — 모르는 값을 지어내지 않는다."""
    rows = rows_of(Status(recent_sessions=[brief(caller="server_runner", result="weird")]))
    assert rows[0][1] == "server_runner" and rows[0][3] == "weird"


# ─────────────────── 칸이 그려지는 길 ───────────────────


def test_the_panel_fills_the_table_from_the_worker(app: Any, agent: Agent) -> None:
    worker = FakeWorker(Status(recent_sessions=[brief(), brief(session_id="s2")]))
    panel = RecentSessionsPanel(client=worker)
    made = panel.widget(agent.extension_context(BUILTIN_ID))  # 호스트가 들고 있는다 (Qt 자식이 살아 있게)
    assert made is not None
    assert worker.calls == ["GET /v1/status"], "한 번만 묻는다 (화면을 붙잡지 않는다)"
    assert panel._table.rowCount() == 2
    assert panel._note.text() == ""


def test_an_empty_worker_says_so(app: Any, agent: Agent) -> None:
    panel = RecentSessionsPanel(client=FakeWorker(Status()))
    made = panel.widget(agent.extension_context(BUILTIN_ID))
    assert made is not None
    assert panel._note.text() == EMPTY


def test_a_worker_we_cannot_reach_says_so_and_does_not_raise(app: Any, agent: Agent) -> None:
    """**없는데 된 척하지 않는다** — 빈 표를 성공처럼 보이지 않게 사유를 적는다."""
    panel = RecentSessionsPanel(client=FakeWorker(fail=True))
    made = panel.widget(agent.extension_context(BUILTIN_ID))
    assert made is not None
    assert panel._table.rowCount() == 0
    assert panel._note.text() == UNREACHABLE


# ─────────────────── Bot UI가 끼운다 (BUI-09) ───────────────────


def boxes(window: Any) -> dict[str, Any]:
    from PySide6.QtWidgets import QGroupBox  # noqa: PLC0415

    return {box.title(): box for box in window.findChildren(QGroupBox)}


def test_the_bot_ui_puts_the_contributed_box_in_the_runtimes_tab(app: Any, agent: Agent) -> None:
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415

    window = MainWindow(agent)
    found = boxes(window)
    assert "최근 UI 세션" in found, "확장이 기여한 칸이 BUI-09에 들어온다"
    assert len(window._panels) == 1
    assert window._panels[0].runtime == "worker"


def test_a_box_waiting_for_a_runtime_is_hidden_while_it_is_down(app: Any, agent: Agent) -> None:
    """Worker가 꺼져 있을 때 **빈 표를 보이지 않는다** — 칸이 없는 것이 정직하다 (ADR-0042)."""
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415

    window = MainWindow(agent)
    assert not boxes(window)["최근 UI 세션"].isVisibleTo(window)


def test_the_host_refreshes_the_panel_when_the_runtime_is_up(app: Any, agent: Agent) -> None:
    """**주기는 호스트가 정한다** — 패널이 자기 타이머를 만들지 않는다 (ADR-0042)."""
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415

    class Counter:
        def __init__(self) -> None:
            self.widget_calls = 0
            self.refreshes = 0

        def widget(self, _ctx: Any) -> object:
            from PySide6.QtWidgets import QLabel  # noqa: PLC0415

            self.widget_calls += 1
            return QLabel("칸")

        def refresh(self) -> None:
            self.refreshes += 1

    counted = Counter()
    window = MainWindow(agent)
    window._panels[0].panel = counted
    window._panels[0].runtime = None  # 런타임을 기다리지 않는 칸
    window.refresh()
    window.refresh()
    assert counted.refreshes == 2


def test_a_broken_panel_only_folds_its_own_box(app: Any, agent: Agent, monkeypatch: Any) -> None:
    """**확장이 깨져도 Bot UI는 산다** — 그 칸만 접고 사유를 보인다."""
    from PySide6.QtWidgets import QLabel  # noqa: PLC0415

    from chaeksas.bot_ui.main_window import PANEL_BROKEN, MainWindow  # noqa: PLC0415

    assert agent.host is not None
    monkeypatch.setattr(
        agent.host, "panel", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("확장이 터졌다"))
    )
    window = MainWindow(agent)
    box = boxes(window)["최근 UI 세션"]
    said = [one.text() for one in box.findChildren(QLabel)]
    assert any(PANEL_BROKEN in one and "확장이 터졌다" in one for one in said), said
    assert window._panels == [], "만들지 못한 칸은 새로 고침 목록에 넣지 않는다"
    assert window.runtime_label.text(), "나머지 화면은 그대로 그린다"

"""BUI-06 셀렉터 등록 화면 — 담기·검증 (M4 조각 7).

화면 없이 돈다 (`QT_QPA_PLATFORM=offscreen`). **보이는 글과 켜짐/꺼짐만** 본다 — Worker는
가짜다 (진짜 브라우저로 도는 것은 `tests/test_ui_registration.py`가 본다).

거듭 보는 것 다섯.

1. **안내 줄 하나로만 말한다** — 진행·결과·오류가 다른 데로 새지 않는다.
2. **범위가 비면 「못 찾았다」고 말하고 표를 바꾸지 않는다** — 전체로 몰래 넓히지 않는다.
3. **잘렸으면 잘렸다고 말한다.**
4. **키가 겹치면 검증하지 않는다** — 겹친 채로 등록하면 하나가 사라진다.
5. 창을 닫으면 **UI 세션을 놓는다** (한 번에 하나다, ADR-0014).
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.ext.ui_automation.client.registration_window import (  # noqa: E402
    PORT_SETTING,
    TOKEN_DIR_SETTING,
    RegistrationWidget,
    worker_client,
)
from chaeksas.ext.ui_automation.contracts.registration import (  # noqa: E402
    AnalyzeResult,
    Candidate,
    CheckRow,
    VerifyResult,
)
from chaeksas.ext.ui_automation.contracts.worker_local import SessionInfo  # noqa: E402


class FakeWorker:
    """C10을 흉내 낸다. **화면이 무엇을 보냈는지**를 남긴다."""

    def __init__(self, *, result: AnalyzeResult | None = None, refuse: Exception | None = None) -> None:
        self.result = result or AnalyzeResult(
            candidates=[
                Candidate(tag="input", role="textbox", name="수량", element_id="qty",
                          test_id="qty-input", css=["#qty"], suggested_key="qty_input"),
                Candidate(tag="button", role="button", name="저장", element_id="save",
                          css=["#save"], suggested_key="save"),
            ],
            total=2,
        )
        self.refuse = refuse
        self.opened: list[str] = []
        self.analyzed: list[Any] = []
        self.verified: list[dict[str, Any]] = []
        self.closed: list[str] = []

    def open_registration(self, start_url: str, *, headed: bool = True) -> SessionInfo:
        if self.refuse is not None:
            raise self.refuse
        self.opened.append(start_url)
        return SessionInfo(session_id="ses_1", session_secret="s3cret", current_url=start_url or "about:blank")

    def analyze(self, session_id: str, secret: str, request: Any) -> AnalyzeResult:
        self.analyzed.append(request)
        return self.result

    def verify(self, session_id: str, secret: str, ladders: dict[str, Any]) -> VerifyResult:
        self.verified.append(ladders)
        return VerifyResult(
            rows=[
                CheckRow(semantic_key=key, rank=index, strategy=one.type, selector=one.value, passed=True)
                for key, ladder in ladders.items()
                for index, one in enumerate(ladder)
            ]
        )

    def close(self, session_id: str, secret: str) -> dict[str, Any]:
        self.closed.append(session_id)
        return {}


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
    widget = RegistrationWidget(worker)
    yield widget, worker
    widget.close()


def opened(widget: Any) -> None:
    widget.start_url.setText("https://erp.example/orders")
    widget.open_browser()


# ─────────────────────────── 열기·분석 ───────────────────────────


def test_nothing_works_until_the_browser_is_open(made: Any) -> None:
    widget, _ = made
    assert not widget.analyze_button.isEnabled()
    assert not widget.verify_button.isEnabled()
    assert not widget.close_button.isEnabled()


def test_opening_tells_the_person_what_to_do_next(made: Any) -> None:
    """주소는 **시작점일 뿐이다** — 등록할 화면까지는 사람이 간다 (BUI-06 1번)."""
    widget, worker = made
    opened(widget)
    assert worker.opened == ["https://erp.example/orders"]
    assert "이동한 뒤" in widget.hint.text()
    assert widget.analyze_button.isEnabled()
    assert widget.open_button.text() == "주소로 이동"


def test_analyze_fills_the_table_with_suggested_keys(made: Any) -> None:
    widget, _ = made
    opened(widget)
    widget.analyze()
    assert widget.elements.rowCount() == 2
    assert widget.elements.item(0, 1).text() == "qty_input"
    assert widget.elements.item(0, 8).text() == "#qty", "CSS 후보는 등록 화면에서만 보인다 (C10 §5)"


def test_an_empty_scope_does_not_widen_silently(app: Any) -> None:
    """**전체로 몰래 넓히지 않는다** — 범위를 잘못 적은 것을 알아야 한다 (BUI-06 2번)."""
    worker = FakeWorker(result=AnalyzeResult(scope_empty=True))
    widget = RegistrationWidget(worker)
    opened(widget)
    widget.scope.setText("#없는범위")
    widget.analyze()
    assert "아무것도 찾지 못했습니다" in widget.hint.text()
    assert widget.elements.rowCount() == 0
    widget.close()


def test_truncation_is_announced(app: Any) -> None:
    """조용히 자르면 **없는 것을 없다고 단정한다**."""
    worker = FakeWorker(
        result=AnalyzeResult(candidates=[Candidate(tag="input", suggested_key="a")], total=900, truncated=True)
    )
    widget = RegistrationWidget(worker)
    opened(widget)
    widget.analyze()
    assert "900개 중 1개만" in widget.hint.text()
    assert "최대치를 올리세요" in widget.hint.text()
    widget.close()


def test_the_scope_and_max_go_to_the_worker(made: Any) -> None:
    widget, worker = made
    opened(widget)
    widget.scope.setText("#main")
    widget.max_count.setValue(60)
    widget.include_read.setChecked(True)
    widget.analyze()
    sent = worker.analyzed[0]
    assert (sent.scope_css, sent.max, sent.include_read) == ("#main", 60, True)


# ─────────────────────────── 키 고치기 ───────────────────────────


def test_editing_a_key_checks_the_row_and_clearing_it_unchecks(made: Any) -> None:
    """키를 고치면 자동 체크, 지우면 체크 해제 (BUI-06 4번)."""
    from PySide6.QtCore import Qt  # noqa: PLC0415

    widget, _ = made
    opened(widget)
    widget.analyze()
    widget.elements.item(0, 1).setText("")
    assert widget.elements.item(0, 0).checkState() == Qt.CheckState.Unchecked
    widget.elements.item(0, 1).setText("주문.수량")
    assert widget.elements.item(0, 0).checkState() == Qt.CheckState.Checked


def test_duplicate_keys_are_refused_at_verify(made: Any) -> None:
    """겹친 채로 등록하면 하나가 사라진다 — 검증 전에 막는다."""
    widget, worker = made
    opened(widget)
    widget.analyze()
    widget.elements.item(1, 1).setText("qty_input")
    widget.verify()
    assert "겹칩니다" in widget.hint.text()
    assert worker.verified == [], "겹친 채로는 Worker를 부르지 않는다"


def test_nothing_chosen_is_said_plainly(made: Any) -> None:
    widget, _ = made
    opened(widget)
    widget.analyze()
    widget.remove_all()
    widget.verify()
    assert "쓸 요소를 고르세요" in widget.hint.text() or not widget.verify_button.isEnabled()


# ─────────────────────────── 검증 ───────────────────────────


def test_verify_sends_the_ladder_of_each_chosen_row(made: Any) -> None:
    """사다리는 **안정한 것부터** — 후보 하나에서 그 자리에서 만든다 (C8)."""
    widget, worker = made
    opened(widget)
    widget.analyze()
    widget.verify()
    sent = worker.verified[0]
    assert set(sent) == {"qty_input", "save"}
    assert [one.type for one in sent["qty_input"]] == ["role", "test_id", "css"]
    assert widget.checks.rowCount() == len(sent["qty_input"]) + len(sent["save"])
    assert "등록해도 좋습니다" in widget.hint.text()


def test_changing_the_table_after_verifying_needs_another_check(made: Any) -> None:
    """표를 바꾸면 검증을 다시 해야 한다 (단추 켜짐 규칙)."""
    widget, _ = made
    opened(widget)
    widget.analyze()
    widget.verify()
    assert widget._verified is not None  # noqa: SLF001
    widget.elements.item(0, 1).setText("주문.수량")
    assert widget._verified is None  # noqa: SLF001


def test_registering_is_not_pretended(made: Any) -> None:
    """**없는 것을 되는 척하지 않는다** — 레지스트리에 올리는 것(C9)은 다음 조각이다."""
    widget, _ = made
    opened(widget)
    widget.analyze()
    widget.verify()
    assert not widget.register_button.isEnabled()
    assert "다음 조각" in widget.register_button.toolTip()
    assert not widget.pick_button.isEnabled()


# ─────────────────────────── 놓아 주기 ───────────────────────────


def test_closing_releases_the_ui_session(made: Any) -> None:
    """세션은 한 번에 하나다 (ADR-0014) — 창을 닫으면 Bot이 쓸 수 있어야 한다."""
    widget, worker = made
    opened(widget)
    widget.release()
    assert worker.closed == ["ses_1"]
    assert not widget.analyze_button.isEnabled()


def test_reset_keeps_the_browser(made: Any) -> None:
    widget, worker = made
    opened(widget)
    widget.analyze()
    widget.reset()
    assert widget.elements.rowCount() == 0
    assert worker.closed == [], "브라우저는 유지한다 (BUI-06 「초기화」)"
    assert widget.analyze_button.isEnabled()


def test_a_busy_worker_is_explained(app: Any) -> None:
    """Bot이 쓰는 중이면 창은 열려 있고 **왜 안 되는지** 안내 줄이 말한다."""
    widget = RegistrationWidget(FakeWorker(refuse=RuntimeError("worker_busy: 다른 쪽이 쥐고 있습니다")))
    widget.start_url.setText("https://erp.example/")
    widget.open_browser()
    assert "사용 중" in widget.hint.text()
    assert not widget.analyze_button.isEnabled()
    widget.close()


# ─────────────────────────── 호스트가 주는 자리 (C13) ───────────────────────────


def test_the_worker_address_comes_from_the_host(tmp_path: Any) -> None:
    """확장이 포트를 다시 계산하거나 토큰 자리를 추측하지 않는다 (C13 예약 키)."""

    class Settings:
        def get(self, key: str, default: Any = None) -> Any:
            return {PORT_SETTING: 9999, TOKEN_DIR_SETTING: str(tmp_path)}.get(key, default)

    found = worker_client(Settings())
    assert found.port == 9999
    assert found.token_dir == tmp_path

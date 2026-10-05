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
    ELEMENT_COLUMNS,
    PORT_SETTING,
    TOKEN_DIR_SETTING,
    RegistrationWidget,
    worker_client,
)
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec  # noqa: E402
from chaeksas.ext.ui_automation.contracts.registration import (  # noqa: E402
    AnalyzeResult,
    Candidate,
    CheckRow,
    VerifyResult,
)
from chaeksas.ext.ui_automation.contracts.registry import (  # noqa: E402
    CatalogEntry,
    DeletionResult,
    ElementHint,
    PageRegistration,
    RegistrationResult,
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
    css = ELEMENT_COLUMNS.index("CSS 후보")
    assert widget.elements.item(0, css).text() == "#qty", "CSS 후보는 등록 화면에서만 보인다 (C10 §5)"


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


def test_registering_without_a_key_is_not_pretended(made: Any) -> None:
    """**없는 것을 되는 척하지 않는다** — 키가 없으면 꺼 두고 어디서 넣는지 말한다."""
    widget, _ = made
    opened(widget)
    widget.analyze()
    widget.verify()
    assert not widget.register_button.isEnabled()
    assert "등록 담당자 키" in widget.register_button.toolTip()
    assert not widget.pick_button.isEnabled(), "직접 고르기는 다음 조각이다"


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


# ─────────────────────────── 레지스트리 (C9) ───────────────────────────


class FakeRegistry:
    """C9를 흉내 낸다. **화면이 무엇을 올렸는지**를 남긴다."""

    def __init__(self, *, known: Any = None, fail: Exception | None = None) -> None:
        self.known = known
        self.fail = fail
        self.registered: list[Any] = []
        self.deleted: list[tuple[str, str | None, bool]] = []

    def get_page(self, page_id: str) -> tuple[Any, list[str]]:
        if self.fail is not None:
            raise self.fail
        if self.known is None:
            raise Problem("그 화면이 없다", code="not_found", status=404)
        return self.known, []

    def register(self, page: Any) -> Any:
        if self.fail is not None:
            raise self.fail
        self.registered.append(page)
        return RegistrationResult(page_id=page.page_id, revision=2, created=[], kept=[], created_page=True)

    def delete(self, page_id: str, semantic_key: str | None = None, *, force: bool = False) -> Any:
        self.deleted.append((page_id, semantic_key, force))
        if self.fail is not None and not force:
            raise self.fail
        return DeletionResult(page_id=page_id, semantic_key=semantic_key, elements=1, locators=2)


class Problem(RuntimeError):
    def __init__(self, message: str, *, code: str = "", status: int = 0, detail: Any = None) -> None:
        super().__init__(message)
        self.code, self.status, self.detail = code, status, detail or {}

    @property
    def permanent(self) -> bool:
        return 400 <= self.status < 500


def registered_page() -> Any:
    return PageRegistration(
        schema=1,
        page_id="erp.order.form",
        locators={"order.qty": [LocatorSpec(type="css", value="#qty")]},
        elements={"order.qty": ElementHint(name="수량", kind="control")},
        catalog={"order.qty": CatalogEntry(actions=["fill"], depends_on=["order.customer"])},
        revision=4,
    )


def with_registry(app: Any, registry: Any) -> Any:
    widget = RegistrationWidget(FakeWorker(), registry)
    widget.page_id.setCurrentText("erp.order.form")
    return widget


def test_a_new_page_says_it_will_be_created(app: Any) -> None:
    widget = with_registry(app, FakeRegistry())
    widget.look_up()
    assert "새 화면" in widget.page_state.text()
    assert not widget.load_button.isEnabled()
    widget.close()


def test_an_existing_page_says_it_will_be_added_to(app: Any) -> None:
    widget = with_registry(app, FakeRegistry(known=registered_page()))
    widget.look_up()
    assert "기존 화면" in widget.page_state.text() and "1개" in widget.page_state.text()
    assert widget.load_button.isEnabled()
    widget.close()


def test_an_unreachable_server_is_not_guessed(app: Any) -> None:
    """**모르는 것을 안다고 하지 않는다** (U8) — 「새 화면」으로 단정하면 덮어쓴다."""
    widget = with_registry(app, FakeRegistry(fail=Problem("닿지 못함")))
    widget.look_up()
    assert "알 수 없습니다" in widget.page_state.text()
    assert not widget.register_button.isEnabled()
    widget.close()


def test_loading_brings_the_registered_ladder(app: Any) -> None:
    """불러온 줄은 **서버의 사다리를 그대로** 가진다 — 다시 등록해도 정의가 바뀌지 않는다."""
    widget = with_registry(app, FakeRegistry(known=registered_page()))
    widget.look_up()
    widget.load_page()
    assert widget.elements.rowCount() == 1
    assert widget.elements.item(0, 1).text() == "order.qty"
    assert [one.value for one in widget._rows[0].ladder()] == ["#qty"]  # noqa: SLF001
    assert widget._rows[0].depends_on == ["order.customer"], "계획 정보도 함께 온다"  # noqa: SLF001
    widget.close()


def test_registering_needs_a_check_first(app: Any) -> None:
    """**검증을 마쳐야 등록이 켜진다.** 그 뒤 표를 바꾸면 다시 꺼진다."""
    registry = FakeRegistry()
    widget = with_registry(app, registry)
    opened(widget)
    widget.analyze()
    assert not widget.register_button.isEnabled()
    widget.verify()
    assert widget.register_button.isEnabled()
    widget.elements.item(0, 1).setText("order.qty")
    assert not widget.register_button.isEnabled(), "표를 바꾸면 다시 검증해야 한다"
    widget.close()


def test_registering_sends_only_the_chosen_rows(app: Any) -> None:
    from PySide6.QtCore import Qt  # noqa: PLC0415

    registry = FakeRegistry()
    widget = with_registry(app, registry)
    opened(widget)
    widget.analyze()
    widget.elements.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    widget.verify()
    widget.register()
    sent = registry.registered[0]
    assert list(sent.locators) == ["qty_input"], "체크하지 않은 줄은 가지 않는다"
    assert sent.page_id == "erp.order.form"
    assert sent.elements["qty_input"].name == "수량"
    assert "등록했습니다" in widget.hint.text()
    widget.close()


def test_a_refused_registration_says_to_fix_it(app: Any) -> None:
    """**4xx는 다시 눌러도 같은 답이다** — 보낸 내용을 고쳐야 한다고 말한다."""
    widget = with_registry(app, FakeRegistry(fail=Problem("사다리가 없다", code="page_invalid", status=422)))
    opened(widget)
    widget.analyze()
    widget.verify()
    widget.register()
    assert "거부했습니다" in widget.hint.text() and "고쳐야" in widget.hint.text()
    widget.close()


def test_an_unreachable_registration_says_to_try_again(app: Any) -> None:
    widget = with_registry(app, FakeRegistry(fail=Problem("닿지 못함")))
    opened(widget)
    widget.analyze()
    widget.verify()
    widget.register()
    assert "닿지 못했습니다" in widget.hint.text() and "다시 누르세요" in widget.hint.text()
    widget.close()


def test_deleting_a_page_asks_first(app: Any, monkeypatch: Any) -> None:
    """**되돌릴 수 없는 일**이다 — 기본은 「취소」다 (U9)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    asked: list[str] = []

    def answer(_parent: Any, _title: str, text: str, *_a: Any, **_k: Any) -> Any:
        asked.append(text)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "question", answer)
    registry = FakeRegistry(known=registered_page())
    widget = with_registry(app, registry)
    widget.look_up()
    widget.unregister(element=False)
    assert registry.deleted == [], "「취소」면 지우지 않는다"
    assert "되돌릴 수 없습니다" in asked[0]
    widget.close()


def test_deleting_what_others_point_at_asks_twice(app: Any, monkeypatch: Any) -> None:
    """끊길 경로가 있으면 **두 번째 확인** 뒤에 강제로 지운다 (C9)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    asked: list[str] = []

    def answer(_parent: Any, _title: str, text: str, *_a: Any, **_k: Any) -> Any:
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    links = Problem("가리키는 곳이 있다", code="has_links", status=409,
                    detail={"links": [{"page_id": "erp.order.list", "semantic_key": "list.new"}]})
    registry = FakeRegistry(known=registered_page(), fail=links)
    widget = with_registry(app, registry)
    widget._known = registered_page()  # noqa: SLF001
    widget.unregister(element=False)
    assert [one[2] for one in registry.deleted] == [False, True], "두 번째는 강제로"
    assert "경로가 끊깁니다" in asked[-1]
    widget.close()


# ─────────────────────────── BUI-07 계획 정보 ───────────────────────────


def test_the_hints_go_with_the_registration(app: Any) -> None:
    from chaeksas.ext.ui_automation.client.registration_window import HintDialog  # noqa: PLC0415

    registry = FakeRegistry()
    widget = with_registry(app, registry)
    opened(widget)
    widget.analyze()
    dialog = HintDialog(widget._rows[0], widget)  # noqa: SLF001
    dialog.depends_on.setText("order.customer, order.date")
    dialog.concepts.setText("수량")
    assert dialog.values() == (["order.customer", "order.date"], ["수량"])

    widget._rows[0].depends_on, widget._rows[0].concepts = dialog.values()  # noqa: SLF001
    widget.verify()
    widget.register()
    sent = registry.registered[0]
    assert sent.catalog["qty_input"].depends_on == ["order.customer", "order.date"]
    assert sent.catalog["qty_input"].concepts == ["수량"]
    widget.close()


def test_a_page_id_is_guessed_from_the_url() -> None:
    """사람이 고치기 쉬운 출발점만 준다 — **C9의 모양**(영소문자·숫자·`_`·`.`)을 지킨다."""
    from chaeksas.ext.ui_automation.client.registration_window import page_id_from  # noqa: PLC0415

    assert page_id_from("https://erp.example/orders/new") == "erp.example.orders.new"
    assert page_id_from("https://한글.example/주문") == "example"

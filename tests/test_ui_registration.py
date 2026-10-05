"""셀렉터 등록 — 분석·키 제안·검증 (C10 §5, BUI-06, M4 조각 6).

키 제안과 사다리 만들기는 **브라우저 없이** 본다. 분석·검증은 **진짜 Chromium**이 있어야
뜻이 있어 Playwright가 없으면 건너뛴다.

거듭 보는 것 다섯.

1. **한글 이름은 음역하지 않는다** — `고객명`을 `gogaegmyeong`으로 바꾸면 아무도 못 읽는다.
2. **범위가 아무것도 못 찾으면 전체로 몰래 넓히지 않는다** (BUI-06 2번).
3. **잘렸으면 잘렸다고 말한다** — 조용히 자르면 없는 것을 없다고 단정한다.
4. 검증은 **하나에 맞아야** 통과다 — 여럿이면 실행에서 엉뚱한 것을 누른다.
5. 요약은 **막지 않는다** — 사람이 보고 정한다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registration import (
    AnalyzeRequest,
    Candidate,
    CheckRow,
    VerifyResult,
    actions_for,
    kind_for,
    ladder_for,
    suggest_key,
)
from chaeksas.ext.ui_automation.worker.browser import BrowserFinder, available
from chaeksas.ext.ui_automation.worker.registration import analyze, summarize, verify

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>주문</title></head>
<body>
  <form id="main">
    <input id="qty" data-testid="qty-input" aria-label="수량" />
    <input id="memo" aria-label="메모" />
    <select id="grade" aria-label="등급"><option>A</option><option>B</option></select>
    <button id="save">저장</button>
    <input class="dup" /><input class="dup" />
  </form>
  <div id="side"><button id="help">도움말</button></div>
  <table id="lines"><tr><th>거래처</th></tr><tr><td>한빛상사</td></tr></table>
</body></html>"""


# ─────────────────────────── 키 제안 (브라우저 없이) ───────────────────────────


def test_a_test_id_wins() -> None:
    """등록한 사람이 일부러 붙인 것이다 — 가장 안정하다."""
    found = Candidate(tag="input", test_id="qty-input", element_id="qty", name="수량")
    assert suggest_key(found, set()) == "qty_input"


def test_an_id_is_next() -> None:
    assert suggest_key(Candidate(tag="input", element_id="customerName"), set()) == "customername"


def test_the_form_field_name_is_next() -> None:
    """서버로 보내는 칸 이름이다 — 사람이 지은 것이라 역할보다 낫다 (BUI-06 4번)."""
    found = Candidate(tag="input", role="textbox", field_name="order_qty", name="수량")
    assert suggest_key(found, set()) == "order_qty"


def test_a_korean_name_is_not_transliterated() -> None:
    """`고객명` → `gogaegmyeong`은 **아무도 못 읽는다** — 역할로 짓고 사람이 고친다."""
    found = suggest_key(Candidate(tag="input", role="textbox", name="고객명"), set())
    assert found == "textbox"
    assert "gogaeg" not in found


def test_duplicate_keys_get_numbers() -> None:
    taken = {"textbox"}
    assert suggest_key(Candidate(tag="input", role="textbox", name="메모"), taken) == "textbox_2"


def test_a_key_is_safe_for_the_contract() -> None:
    """C9의 `semantic_key` 모양 — 영소문자·숫자·`_`·`.`."""
    found = suggest_key(Candidate(tag="input", element_id="Customer Name!"), set())
    assert found == "customer_name"


# ─────────────────────────── 사다리 만들기 ───────────────────────────


def test_the_ladder_is_built_stable_first() -> None:
    found = ladder_for(
        Candidate(tag="input", role="textbox", name="수량", test_id="qty-input", css=["#qty", "input.field"])
    )
    assert [one.type for one in found] == ["role", "test_id", "css", "css"]
    assert found[0].exact, "이름은 정확히 맞춰야 여럿이 안 잡힌다"


def test_a_nameless_element_gets_no_role_locator() -> None:
    """이름 없는 `role` 하나는 여럿이 맞는다 — 사다리에 넣지 않는다 (C9도 거부한다)."""
    found = ladder_for(Candidate(tag="input", role="textbox", css=["#qty"]))
    assert [one.type for one in found] == ["css"]


@pytest.mark.parametrize(
    ("role", "tag", "kind"),
    [
        ("table", "table", "table"),
        ("listbox", "select", "list"),
        ("heading", "h1", "text"),
        ("button", "button", "control"),
    ],
)
def test_the_kind_comes_from_the_role(role: str, tag: str, kind: str) -> None:
    assert kind_for(role, tag) == kind


def test_the_actions_come_from_the_role() -> None:
    assert "fill" in actions_for("textbox", "input")
    assert actions_for("table", "table") == ["read_table"]
    assert actions_for("모르는역할", "모르는태그") == ["read"], "모르면 읽기만 제안한다"


# ─────────────────────────── 요약 (BUI-06 7번) ───────────────────────────


def rows(*pairs: tuple[str, bool]) -> VerifyResult:
    return VerifyResult(
        rows=[
            CheckRow(semantic_key=key, rank=index, strategy="css", selector="#x", passed=passed)
            for index, (key, passed) in enumerate(pairs)
        ]
    )


def test_the_summary_says_what_will_happen() -> None:
    assert "자가 치유" in summarize(rows(("가", False), ("가", False)))
    assert "하나뿐" in summarize(rows(("가", True), ("나", True), ("나", True)))
    assert "등록해도 좋습니다" in summarize(rows(("가", True), ("가", True)))
    assert "검증할 요소가 없습니다" in summarize(VerifyResult())


def test_an_element_passes_if_any_rung_holds() -> None:
    """사다리 한 칸만 잡혀도 그 요소는 잡힌다 — 나머지는 대체다."""
    found = rows(("가", False), ("가", True))
    assert found.unreachable == [] and found.single == ["가"]


# ─────────────────────────── 분석·검증 (진짜 화면) ───────────────────────────

pytestmark_browser = pytest.mark.skipif(not available(), reason="Playwright가 없다")


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            raw = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_: object) -> None:
            pass

    made = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=made.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{made.server_address[1]}/"
    finally:
        made.shutdown()
        made.server_close()
        thread.join(timeout=2)


@pytest.fixture
def page(site: str) -> Iterator[Any]:
    if not available():
        pytest.skip("Playwright가 없다")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"브라우저를 띄우지 못했다: {type(e).__name__}")
        found = browser.new_page()
        found.goto(site)
        try:
            yield found
        finally:
            browser.close()


@pytestmark_browser
def test_analyze_finds_the_controls(page: Any) -> None:
    found = analyze(page, AnalyzeRequest(schema=1))
    keys = {one.suggested_key for one in found.candidates}
    assert "qty_input" in keys, "test_id가 이긴다"
    assert any(one.element_id == "save" for one in found.candidates)
    assert not found.truncated and not found.scope_empty


@pytestmark_browser
def test_analyze_can_be_scoped(page: Any) -> None:
    found = analyze(page, AnalyzeRequest(schema=1, scope_css="#side"))
    assert [one.element_id for one in found.candidates] == ["help"]


@pytestmark_browser
def test_an_empty_scope_is_said_not_widened(page: Any) -> None:
    """**전체로 몰래 넓히지 않는다** — 범위를 잘못 적은 것을 알아야 한다 (BUI-06 2번)."""
    found = analyze(page, AnalyzeRequest(schema=1, scope_css="#없는범위"))
    assert found.scope_empty and found.candidates == []


@pytestmark_browser
def test_truncation_is_announced(page: Any) -> None:
    """조용히 자르면 **없는 것을 없다고 단정한다**."""
    found = analyze(page, AnalyzeRequest(schema=1, max=10))
    assert found.truncated or found.total <= 10
    if found.truncated:
        assert len(found.candidates) == 10 and found.total > 10


@pytestmark_browser
def test_read_targets_come_only_when_asked(page: Any) -> None:
    without = analyze(page, AnalyzeRequest(schema=1))
    with_read = analyze(page, AnalyzeRequest(schema=1, include_read=True))
    assert not any(one.kind == "table" for one in without.candidates)
    assert any(one.kind == "table" for one in with_read.candidates)


@pytestmark_browser
def test_verify_checks_each_rung(page: Any) -> None:
    finder = BrowserFinder(page=page)
    found = verify(
        finder,
        {
            "수량": [LocatorSpec(type="css", value="#qty"), LocatorSpec(type="css", value="#없음")],
            "중복": [LocatorSpec(type="css", value=".dup")],
        },
    )
    by_key = {(one.semantic_key, one.selector): one for one in found.rows}
    assert by_key[("수량", "#qty")].passed
    assert not by_key[("수량", "#없음")].passed and "못 찾았다" in by_key[("수량", "#없음")].reason
    assert "2개가 잡힌다" in by_key[("중복", ".dup")].reason, "여럿이면 실패다"

    assert found.unreachable == ["중복"]
    assert found.single == ["수량"]


@pytestmark_browser
def test_an_analyzed_element_verifies(page: Any) -> None:
    """분석 → 사다리 → 검증이 한 줄로 맞물린다 (BUI-06의 길)."""
    found = analyze(page, AnalyzeRequest(schema=1))
    one = next(candidate for candidate in found.candidates if candidate.element_id == "qty")
    checked = verify(BrowserFinder(page=page), {"수량": ladder_for(one)})
    assert checked.unreachable == [], [row.reason for row in checked.rows]


# ─────────────────────────── 경로 (C10 §5) ───────────────────────────


class Screen:
    """시험용 백엔드. `page`가 없으면 **분석을 지원하지 않는다**고 말해야 한다."""

    def __init__(self, *, has_page: bool = True) -> None:
        self.finder_value = BrowserFinder(page=object()) if has_page else NoPage()

    def open(self, request: Any) -> str:
        return request.start_url or "about:blank"

    def finder(self, business_key: str) -> Any:
        return self.finder_value

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


class NoPage:
    """화면은 있는데 **들여다볼 수는 없는** 백엔드 (데스크톱 UIA가 올 자리)."""

    def find(self, locator: Any, *, timeout_ms: int) -> Any:  # pragma: no cover — 안 불린다
        raise AssertionError("분석이 먼저 막혀야 한다")


def served(**kwargs: Any) -> tuple[Any, Any]:
    from fastapi.testclient import TestClient

    from chaeksas.ext.ui_automation.worker.app import Worker, create_app

    worker = Worker(token="t-use", admin_token="t-admin", backend=Screen(**kwargs))
    return worker, TestClient(create_app(worker))


def test_the_worker_names_the_registration_session() -> None:
    """`business_key`는 **Worker가 짓는다** — 등록 화면이 실행 키를 흉내 내지 않는다."""
    worker, client = served()
    answer = client.post(
        "/v1/registration/browser",
        json={"start_url": "https://erp.example/"},
        headers={"X-CHK-Local-Token": "t-use"},
    )
    assert answer.status_code == 201, answer.text
    assert worker.session is not None
    assert worker.session.request.business_key.startswith("reg_")
    assert worker.session.request.caller.type == "selector_registration"
    assert worker.session.request.page_id is None, "등록 세션은 계획을 받아 오지 않는다"


def test_a_bot_session_cannot_be_analyzed() -> None:
    """실행 중인 Bot의 화면을 등록 화면이 헤집지 못한다."""
    worker, client = served()
    body = {
        "schema": 1,
        "caller": {"type": "bot", "run_id": "run_20261005_120000_abcdef"},
        "mode": "deterministic",
        "business_key": "run_20261005_120000_abcdef:Task_Fill:1:1",
    }
    opened = client.post("/v1/sessions", json=body, headers={"X-CHK-Local-Token": "t-use"}).json()
    answer = client.post(
        f"/v1/registration/{opened['session_id']}/analyze",
        json={"schema": 1},
        headers={"X-CHK-Local-Token": "t-use", "X-CHK-Session": opened["session_secret"]},
    )
    assert answer.status_code == 403
    assert answer.json()["code"] == "session_locked"


def test_a_backend_without_a_page_says_so() -> None:
    """**없는 것을 되는 척하지 않는다** — 데스크톱 백엔드에는 아직 분석이 없다."""
    _, client = served(has_page=False)
    opened = client.post(
        "/v1/registration/browser", json={"start_url": ""}, headers={"X-CHK-Local-Token": "t-use"}
    ).json()
    answer = client.post(
        f"/v1/registration/{opened['session_id']}/analyze",
        json={"schema": 1},
        headers={"X-CHK-Local-Token": "t-use", "X-CHK-Session": opened["session_secret"]},
    )
    assert answer.status_code == 503
    assert answer.json()["code"] == "browser_unavailable"


def test_registration_needs_the_token() -> None:
    _, client = served()
    assert client.post("/v1/registration/browser", json={}).status_code == 401

"""브라우저 백엔드 (M4 조각 2) — 로케이터를 Playwright 말로 옮기고 한 번 조작한다.

**Playwright가 없으면 건너뛴다.** 브라우저 바이너리(~150 MB)를 CI에 내려받지 않는다 —
사다리의 규칙은 `tests/test_worker_ladder.py`가 브라우저 없이 모두 본다. 여기서는 **옮기는
말이 맞는지**만 본다.

거듭 보는 것 넷.

1. **셀렉터는 이 안에만** 있다 (C10 — 시맨틱 키만 경계를 넘는다).
2. **몇 개 맞았는지**를 돌려준다 — 하나가 아니면 쓰지 않는다 (사다리가 판단한다).
3. **값을 가려서** 스냅샷을 만든다 (원칙 6).
4. 브라우저가 없으면 **세션을 열지 않는다** — 「없는데 된 척」하지 않는다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, PlanStep
from chaeksas.ext.ui_automation.contracts.worker_local import SessionRequest, business_key
from chaeksas.ext.ui_automation.worker.browser import (
    ARIA_MAX,
    BrowserBackend,
    BrowserFinder,
    available,
)
from chaeksas.ext.ui_automation.worker.ladder import TableRead

pytestmark = pytest.mark.skipif(not available(), reason="Playwright가 없다 (브라우저 백엔드 시험)")

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>주문</title></head>
<body>
  <form>
    <label for="qty">수량</label>
    <input id="qty" data-testid="qty-input" class="field" />
    <label for="memo">메모</label>
    <input id="memo" class="field" />
    <button id="save">저장</button>
  </form>
  <table id="lines">
    <tr><th>거래처</th><th>금액</th></tr>
    <tr><td>한빛상사</td><td>1,250,000</td></tr>
  </table>
</body></html>"""


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    """127.0.0.1에 뜬 한 쪽짜리 화면 — **바깥으로 나가지 않는다**."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — http.server가 정한 이름
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
def opened(site: str) -> Iterator[tuple[BrowserBackend, BrowserFinder]]:
    backend = BrowserBackend()
    key = business_key("test_20261005_120000_abcdef", "Task_Fill")
    request = SessionRequest(
        schema=1,
        caller={"type": "studio"},  # type: ignore[arg-type]
        mode="deterministic",
        business_key=key,
        page_id="주문.화면",
        start_url=site,
    )
    try:
        backend.open(request)
    except Exception as e:  # noqa: BLE001 — 브라우저 바이너리가 없을 수 있다
        pytest.skip(f"브라우저를 띄우지 못했다: {type(e).__name__}: {e}")
    found = backend.finder(key)
    assert found is not None
    try:
        yield backend, found
    finally:
        backend.close("")
        backend.shutdown()


def locator(type_: str, value: str, **extra: Any) -> LocatorSpec:
    return LocatorSpec(type=type_, value=value, **extra)


# ─────────────────────────── 찾기 ───────────────────────────


@pytest.mark.parametrize(
    "spec",
    [
        LocatorSpec(type="css", value="#qty"),
        LocatorSpec(type="test_id", value="qty-input"),
        LocatorSpec(type="xpath", value="//input[@id='qty']"),
        LocatorSpec(type="role", value="textbox", name="수량"),
    ],
)
def test_every_web_strategy_finds_the_same_element(
    opened: tuple[BrowserBackend, BrowserFinder], spec: LocatorSpec
) -> None:
    """C8의 웹 전략 넷이 모두 같은 칸을 찾는다 — 사다리가 쓸 수 있는 말들이다."""
    _, finder = opened
    assert finder.find(spec, timeout_ms=2000).unique


def test_a_locator_that_matches_many_says_how_many(
    opened: tuple[BrowserBackend, BrowserFinder],
) -> None:
    """하나가 아니면 **쓰지 않는다** — 판단은 사다리가 한다."""
    _, finder = opened
    found = finder.find(locator("css", ".field"), timeout_ms=2000)
    assert found.count == 2 and not found.unique


def test_a_locator_that_matches_nothing_is_not_an_exception(
    opened: tuple[BrowserBackend, BrowserFinder],
) -> None:
    _, finder = opened
    assert finder.find(locator("css", "#없는칸"), timeout_ms=500).count == 0


def test_a_broken_selector_is_reported_not_raised(
    opened: tuple[BrowserBackend, BrowserFinder],
) -> None:
    """깨진 셀렉터 하나가 사다리를 죽이면 안 된다 — 다음 칸으로 가야 한다."""
    _, finder = opened
    found = finder.find(locator("xpath", "//["), timeout_ms=500)
    assert found.count == 0 and found.error


# ─────────────────────────── 조작·읽기 ───────────────────────────


def test_fill_and_read_back(opened: tuple[BrowserBackend, BrowserFinder]) -> None:
    _, finder = opened
    handle = finder.find(locator("css", "#qty"), timeout_ms=2000).handle
    assert finder.act(handle, PlanStep(semantic_key="수량", action="fill", value="3"), timeout_ms=2000) is None
    assert finder.act(handle, PlanStep(semantic_key="수량", action="read_selection"), timeout_ms=2000) == "3"


def test_a_table_comes_back_as_headers_and_rows(opened: tuple[BrowserBackend, BrowserFinder]) -> None:
    """표는 머리글과 줄, 칸은 글 그대로 (C10 `data`). `text`는 사람이 읽는 TSV다 (ADR-0036)."""
    _, finder = opened
    handle = finder.find(locator("css", "#lines"), timeout_ms=2000).handle
    found = finder.act(handle, PlanStep(semantic_key="줄", action="read_table"), timeout_ms=2000)
    assert isinstance(found, TableRead)
    assert found.data()["headers"] == ["거래처", "금액"]
    assert found.data()["rows"][0] == ["한빛상사", "1,250,000"], "수 규칙은 부르는 쪽이 쓴다"
    assert found.text.splitlines()[1] == "한빛상사\t1,250,000"


def test_an_unknown_action_says_so(opened: tuple[BrowserBackend, BrowserFinder]) -> None:
    _, finder = opened
    handle = finder.find(locator("css", "#qty"), timeout_ms=2000).handle
    with pytest.raises(ValueError, match="모르는 동작"):
        finder.act(handle, PlanStep(semantic_key="수량", action="춤추기"), timeout_ms=2000)


# ─────────────────────────── 스냅샷 (원칙 6) ───────────────────────────


def test_what_was_typed_is_masked_in_the_snapshot(
    opened: tuple[BrowserBackend, BrowserFinder],
) -> None:
    """치유 요청에 업무 값이 그대로 나가면 안 된다 (C8 §heal)."""
    _, finder = opened
    handle = finder.find(locator("css", "#memo"), timeout_ms=2000).handle
    finder.act(handle, PlanStep(semantic_key="메모", action="fill", value="한빛상사-대외비"), timeout_ms=2000)

    aria, sub_dom = finder.snapshot()
    assert "한빛상사-대외비" not in aria and "한빛상사-대외비" not in sub_dom
    assert len(aria) <= ARIA_MAX
    assert "수량" in aria or "수량" in sub_dom, "구조와 라벨은 남는다"


def test_goto_moves_the_page(opened: tuple[BrowserBackend, BrowserFinder], site: str) -> None:
    backend, finder = opened
    assert backend.goto("", f"{site}?2").endswith("?2")
    assert finder.url().endswith("?2")


# ─────────────────────────── 없을 때 ───────────────────────────


def test_the_backend_does_not_pretend_to_step() -> None:
    """계획(C8 plan)을 받아 오는 길이 아직 없다 — 되는 척하지 않는다."""
    from chaeksas.ext.ui_automation.contracts.worker_local import StepRequest

    with pytest.raises(NotImplementedError):
        BrowserBackend().step("ses_1", StepRequest(semantic_key="가", action="click"))

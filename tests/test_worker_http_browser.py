"""Worker를 **진짜 HTTP로** 부른다 — uvicorn 루프 + 진짜 Chromium (현장 경로).

다른 시험은 Worker **객체를 직접** 부른다 (`test_m4_acceptance`·`test_ui_end_to_end`). 그래서
현장에서만 지나는 길 — 창구가 uvicorn의 asyncio 루프 안에서 Playwright **동기** API를 부르는 길 —
을 한 번도 밟지 않았고, 시나리오 3 현장 실행에서 「화면을 열지 못했습니다 (Error)」로 드러났다
(Playwright가 루프 안의 동기 API를 거부한다). 이 시험은 그 길을 밟는다.

거듭 보는 것 둘.

1. **루프 안에서 연다** — 창구가 진짜 소켓의 uvicorn 위에 있다 (`TestClient`가 아니다).
2. **연 스레드에서 이어 만진다** — 열기 뒤에 분석·닫기가 같은 브라우저를 만진다
   (Playwright는 띄운 스레드에서만 만질 수 있다).
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn

from chaeksas.ext.ui_automation.contracts.worker_local import SESSION_HEADER, TOKEN_HEADER
from chaeksas.ext.ui_automation.worker.app import Worker, create_app
from chaeksas.ext.ui_automation.worker.browser import BrowserBackend, available
from chaeksas.ext.ui_automation.worker.screen import THREAD_NAME
from chaeksas.mock_apps import sites

pytestmark = pytest.mark.skipif(not available(), reason="Playwright가 없다")

TOKEN = "t-worker"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def portal() -> Iterator[str]:
    """BX-04의 공급사 포털 — 현장 PC가 `chk-mock-apps serve`로 여는 것과 **같은 HTML**."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            raw = sites.page(self.path.split("?", 1)[0]).encode("utf-8")
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
        yield f"http://127.0.0.1:{made.server_address[1]}"
    finally:
        made.shutdown()
        made.server_close()


@pytest.fixture
def worker_url(tmp_path: Path) -> Iterator[str]:
    """Worker 창구를 **진짜 uvicorn**에 올린다 — `serve()`가 하는 것과 같은 루프다."""
    backend = BrowserBackend(headless=True)
    worker = Worker(token=TOKEN, admin_token="a", backend=backend)
    app = create_app(worker)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    until = time.monotonic() + 20
    while time.monotonic() < until:
        try:
            if httpx.get(f"{base}/v1/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    try:
        yield base
    finally:
        try:
            httpx.post(f"{base}/v1/admin/shutdown", headers={"X-CHK-Local-Admin": "a"}, timeout=10)
        except httpx.HTTPError:
            pass
        server.should_exit = True
        thread.join(timeout=10)
        # 브라우저도 **띄운 스레드에서** 닫는다.
        app.state.screen.nudge(backend.shutdown).result(timeout=20)
        app.state.screen.close()


def _call(method: str, url: str, **kwargs: Any) -> httpx.Response:
    headers = {TOKEN_HEADER: TOKEN, **kwargs.pop("headers", {})}
    return httpx.request(method, url, headers=headers, timeout=60, **kwargs)


def test_registration_opens_a_browser_through_the_real_http_loop(worker_url: str, portal: str) -> None:
    """BUI-06 「브라우저 열기」 → 「분석」 → 닫기 — 현장과 같은 길로."""
    opened = _call("POST", f"{worker_url}/v1/registration/browser", json={"start_url": f"{portal}/transactions"})
    assert opened.status_code in (200, 201), opened.text
    info = opened.json()
    session_id, secret = info["session_id"], info["session_secret"]
    assert info["current_url"].endswith("/transactions")

    # 연 스레드에서 이어 만진다 — 다른 스레드에서 만지면 Playwright가 깨진다.
    analyzed = _call(
        "POST",
        f"{worker_url}/v1/registration/{session_id}/analyze",
        json={"schema": 1, "include_read": True},
        headers={SESSION_HEADER: secret},
    )
    assert analyzed.status_code == 200, analyzed.text
    ids = {one["element_id"] for one in analyzed.json()["candidates"]}
    assert {"month", "search", "transactions"} <= ids, ids

    closed = _call("DELETE", f"{worker_url}/v1/sessions/{session_id}", headers={SESSION_HEADER: secret})
    assert closed.status_code == 200, closed.text


def test_health_answers_without_waiting_for_the_screen(worker_url: str) -> None:
    """살아 있나 확인은 화면 스레드를 기다리지 않는다 — 긴 스텝 중에도 답해야 한다."""
    found = httpx.get(f"{worker_url}/v1/health", timeout=5)
    assert found.status_code == 200
    assert found.json()["session"] == "idle"
    assert THREAD_NAME  # 이름이 있어야 덤프에서 알아본다

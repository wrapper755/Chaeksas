"""UI 자동화 한 바퀴 — 등록 → 계획 → 실행 → 보고 → 승격 (M4 조각 11).

여기만 **진짜 다섯을 한 줄로** 붙인다: 진짜 소켓 Center, 그 일꾼인 진짜 UI 자동화 앱, 진짜 Worker,
진짜 Chromium, 진짜 화면 하나. 조각마다 가짜로 본 것이 **정말 맞물리는지**는 이것만 안다. Worker는
앱을 모른다 — Center 주소와 세션이 준 **호출 토큰**으로 C15 외부 작업을 올린다 (ADR-0102).

거듭 보는 것 다섯.

1. **계획은 레지스트리에서 온다** — 등록하지 않은 요소를 가리키면 422다.
2. **사다리는 Worker가 로컬에서 탄다** — 첫 칸이 깨져도 다음 칸으로 간다.
3. **읽은 값은 보고에 들어가지 않는다** (원칙 6).
4. **`test` 보고는 승격 통계에 넣지 않는다** — 실행 보고 세 번이어야 올라간다.
5. 결정 수행의 목표는 **거절한다** — `mode_unsupported`로 분명히 (되는 척하지 않는다).

보고는 결과를 기다리지 않는다(C15 `want_result: false`) — 승격은 일꾼이 가져갈 때까지 기다려 본다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from uia_center import BOT, VERSION, UiaCenter, running

from chaeksas.ext.ui_automation.client.registry_client import RegistryClient, RegistryProblem
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registry import ElementHint, PageRegistration
from chaeksas.ext.ui_automation.contracts.worker_local import (
    Caller,
    SessionRequest,
    StepRequest,
)
from chaeksas.ext.ui_automation.worker import plans_for
from chaeksas.ext.ui_automation.worker.app import Worker, WorkerProblem
from chaeksas.ext.ui_automation.worker.browser import BrowserBackend, available

PAGE_ID = "erp.order.form"
RUN = "run_20261005_120000_abcdef"

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>주문</title></head>
<body>
  <form id="main">
    <input id="qty" aria-label="수량" />
    <div id="total">합계 1,200,000원</div>
    <button id="save">저장</button>
  </form>
</body></html>"""

pytestmark = pytest.mark.skipif(not available(), reason="Playwright가 없다")


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
def center(tmp_path: Path) -> Iterator[UiaCenter]:
    """진짜 Center + 그 일꾼인 UI 자동화 앱."""
    with running(tmp_path) as found:
        yield found


@pytest.fixture
def token(center: UiaCenter) -> str:
    """현장 PC 하나의 호출 토큰 — 「셀렉터 등록」을 켰고 그 토픽을 요구하는 Bot이 배포돼 있다."""
    return str(center.pc_token())


@pytest.fixture
def registry(center: UiaCenter, token: str) -> RegistryClient:
    return RegistryClient(base_url=center.url, call_token=token)


def register(registry: RegistryClient, site: str, *, broken: bool = False) -> None:
    """화면 하나를 등록한다. `broken`이면 **첫 칸이 깨진 사다리**를 함께 넣는다."""
    qty = [LocatorSpec(type="css", value="#qty")]
    if broken:
        qty = [LocatorSpec(type="css", value="#없는것", priority=1), *qty]
    registry.register(
        PageRegistration(
            schema=1,
            page_id=PAGE_ID,
            name="주문 입력",
            url_pattern=site,
            locators={
                "order.qty": qty,
                "order.total": [LocatorSpec(type="css", value="#total")],
                "order.save": [LocatorSpec(type="css", value="#save")],
            },
            elements={
                "order.qty": ElementHint(name="수량", role="textbox"),
                "order.total": ElementHint(name="합계", kind="text"),
                "order.save": ElementHint(name="저장", role="button"),
            },
        )
    )


@pytest.fixture
def worker(center: UiaCenter, tmp_path: Path) -> Iterator[Worker]:
    """진짜 Worker + 진짜 브라우저 백엔드. 계획·보고는 **제품과 같은 길**(`plans_for`)로 Center에 간다."""
    backend = BrowserBackend(headless=True)
    made = Worker(
        token="t", admin_token="a", backend=backend,
        plans_factory=plans_for(tmp_path / "worker", center.url),  # type: ignore[arg-type]
    )
    try:
        yield made
    finally:
        if made.session is not None:
            made.force_close(made.session.session_id)
        backend.shutdown()


def opened(worker: Worker, site: str, token: str, *, attempt: int = 1) -> tuple[str, str]:
    """세션 하나. **실행마다 다른 `business_key`**다 (C10) — 멱등 키의 뿌리다."""
    request = SessionRequest(
        schema=1,
        caller=Caller(
            type="bot", run_id=RUN, node_id="Task_Fill", attempt=attempt, bpm_process_id=BOT, version=VERSION
        ),
        mode="deterministic",
        business_key=f"{RUN}:Task_Fill:1:{attempt}",
        page_id=PAGE_ID,
        start_url=site,
        call_token=token,
    )
    info, _ = worker.open(request)
    return info.session_id, info.session_secret


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_a_registered_page_can_be_driven(registry: RegistryClient, worker: Worker, site: str, token: str) -> None:
    """등록 → 계획 → 조작·읽기 → 닫기. **한 줄로 맞물린다.**"""
    register(registry, site)
    session_id, secret = opened(worker, site, token)
    assert worker.session is not None and worker.session.plan is not None
    assert worker.session.plan_source == "server"
    assert set(worker.session.plan.locators) >= {"order.qty"}

    filled = worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    assert filled.ok and not filled.escalated

    read = worker.step(session_id, secret, StepRequest(semantic_key="order.total", action="read"))
    assert read.ok and "1,200,000" in str(read.text)

    closed = worker.close(session_id, secret)
    assert closed.summary.result == "success"
    assert closed.steps_run == 2


def test_the_ladder_falls_back_locally(registry: RegistryClient, worker: Worker, site: str, token: str) -> None:
    """**첫 칸이 깨져도 다음 칸으로 간다** — 폴백 도중에는 네트워크를 타지 않는다 (C8)."""
    register(registry, site, broken=True)
    session_id, secret = opened(worker, site, token)
    found = worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    assert found.ok
    assert found.fallback_depth == 1, "두 번째 칸으로 내려갔다"


def test_an_unregistered_key_is_refused(registry: RegistryClient, worker: Worker, site: str, token: str) -> None:
    """등록하지 않은 요소는 **계획이 거절한다** (C8 `unknown_semantic_key`)."""
    register(registry, site)
    session_id, secret = opened(worker, site, token)
    with pytest.raises(WorkerProblem) as caught:
        worker.step(session_id, secret, StepRequest(semantic_key="order.없는것", action="click"))
    assert caught.value.code == "unknown_semantic_key"


def test_the_report_carries_no_business_value(
    center: UiaCenter, registry: RegistryClient, worker: Worker, site: str, token: str
) -> None:
    """**읽은 값은 보고에 들어가지 않는다** (원칙 6) — 합계 금액이 Center로도 앱으로도 가면 안 된다."""
    register(registry, site)
    session_id, secret = opened(worker, site, token)
    worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    worker.step(session_id, secret, StepRequest(semantic_key="order.total", action="read"))
    assert worker.session is not None
    raw = worker.session.report().model_dump_json()
    assert "1,200,000" not in raw and '"7"' not in raw
    assert PAGE_ID in raw
    assert worker.close(session_id, secret).report == "sent"
    stored = str([dict(row) for row in center.store.rows("SELECT input_json, output_json FROM external_tasks")])
    assert "1,200,000" not in stored, "Center에 남은 일감에도 없다"


def wait_for_status(registry: RegistryClient, key: str, status: str) -> str:
    """보고는 결과를 기다리지 않는다 — 일꾼이 가져가 승격할 때까지 본다."""
    deadline = time.monotonic() + 15
    while True:
        found, _ = registry.get_page(PAGE_ID)
        now = found.locators[key][0].status
        if now == status or time.monotonic() > deadline:
            return now
        time.sleep(0.1)


def test_three_runs_promote_through_the_whole_chain(
    registry: RegistryClient, worker: Worker, site: str, token: str
) -> None:
    """보고가 통계를 올리고 **세 번째에 승격**한다 (C8·C9) — 끝에서 끝까지."""
    register(registry, site)
    for attempt in (1, 2, 3):
        session_id, secret = opened(worker, site, token, attempt=attempt)
        worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
        assert worker.close(session_id, secret).report == "sent"

    assert wait_for_status(registry, "order.qty", "active") == "active", "세 번 연속 성공이면 올라간다"
    found, _ = registry.get_page(PAGE_ID)
    assert found.locators["order.save"][0].status == "unverified", "쓰지 않은 것은 그대로다"


def test_a_trial_run_can_keep_its_hands_off_the_server(
    center: UiaCenter, registry: RegistryClient, worker: Worker, site: str, token: str
) -> None:
    """BUI-08의 「결과를 서버에 보고」가 꺼져 있으면 **아예 보내지 않는다** (C10 `report`)."""
    register(registry, site)
    request = SessionRequest(
        schema=1,
        caller=Caller(type="selector_registration"),
        mode="deterministic",
        business_key="reg_abcd1234",
        page_id=PAGE_ID,
        start_url=site,
        report=False,
        call_token=token,
    )
    info, _ = worker.open(request)
    worker.step(info.session_id, info.session_secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    closed = worker.close(info.session_id, info.session_secret)
    assert closed.report == "queued", "보내지 않았다 — 디스크 큐에만 남는다"

    assert not center.store.rows("SELECT 1 FROM external_tasks WHERE operation = 'report'"), "Center에도 없다"
    found, _ = registry.get_page(PAGE_ID)
    assert found.locators["order.qty"][0].status == "unverified", "통계가 움직이지 않았다"


def test_a_goal_in_deterministic_mode_is_refused(registry: RegistryClient, site: str) -> None:
    """결정 수행은 목표로 계획하지 않는다 — LLM을 몰래 부르지 않는다 (C8, ADR-0035)."""
    register(registry, site)
    with pytest.raises(RegistryProblem) as caught:
        registry.call("plan", {"page_id": PAGE_ID, "goal": "수량을 넣고 저장"})
    assert caught.value.code == "mode_unsupported"
    assert caught.value.permanent

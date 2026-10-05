"""UI 자동화 한 바퀴 — 등록 → 계획 → 실행 → 보고 → 승격 (M4 조각 11).

여기만 **진짜 넷을 한 줄로** 붙인다: 진짜 UI 자동화 앱(in-process), 진짜 Worker, 진짜
Chromium, 진짜 화면 하나. 조각마다 가짜로 본 것이 **정말 맞물리는지**는 이것만 안다.

거듭 보는 것 다섯.

1. **계획은 레지스트리에서 온다** — 등록하지 않은 요소를 가리키면 422다.
2. **사다리는 Worker가 로컬에서 탄다** — 첫 칸이 깨져도 다음 칸으로 간다.
3. **읽은 값은 보고에 들어가지 않는다** (원칙 6).
4. **`test` 보고는 승격 통계에 넣지 않는다** — 실행 보고 세 번이어야 올라간다.
5. 자연어 목표는 **아직 없다** — 422로 분명히 거절한다 (되는 척하지 않는다).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registry import ElementHint, PageRegistration
from chaeksas.ext.ui_automation.contracts.worker_local import (
    Caller,
    SessionRequest,
    StepRequest,
)
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, create
from chaeksas.ext.ui_automation.service.store import Database, SqliteKeyStore
from chaeksas.ext.ui_automation.worker.app import Worker
from chaeksas.ext.ui_automation.worker.browser import BrowserBackend, available
from chaeksas.ext.ui_automation.worker.plans import HttpOps, PlanCache, PlanService, ReportQueue
from chaeksas.service_kit import hash_key

KEY = "chk_svc_" + "e" * 40
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
def served(tmp_path: Path) -> Any:
    """진짜 UI 자동화 앱 + 등록 담당자 키."""
    path = tmp_path / "uia.sqlite3"
    app = create(db_path=path, admin_token="t-admin")
    SqliteKeyStore(db=Database(path=path)).add(
        ServiceAppKey(
            name="시험",
            hash=hash_key(KEY),
            prefix=KEY[:16],
            allowed_operations=["*"],
            allowed_modes=["deterministic", "autonomous"],
            extra_scopes=[REGISTRY_WRITE],
            created_at="2026-10-05T09:00:00+09:00",
        )
    )
    return app


def register(app: Any, site: str, *, broken: bool = False) -> None:
    """화면 하나를 등록한다. `broken`이면 **첫 칸이 깨진 사다리**를 함께 넣는다."""
    from chaeksas.ext.ui_automation.client.registry_client import RegistryClient

    qty = [LocatorSpec(type="css", value="#qty")]
    if broken:
        qty = [LocatorSpec(type="css", value="#없는것", priority=1), *qty]
    RegistryClient(base_url="http://app", api_key=KEY, client=TestClient(app)).register(
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
def worker(served: Any, tmp_path: Path) -> Iterator[Worker]:
    """진짜 Worker + 진짜 브라우저 백엔드. 계획·보고는 그 앱으로 간다."""
    backend = BrowserBackend(headless=True)
    client = TestClient(served)

    def plans(request: SessionRequest) -> PlanService:
        return PlanService(
            ops=HttpOps(
                base_url="http://app",
                api_key=request.service_key or "",
                business_key=request.business_key,
                client=client,
            ),
            cache=PlanCache(folder=tmp_path / "plans"),
            queue=ReportQueue(folder=tmp_path / "reports"),
        )

    made = Worker(token="t", admin_token="a", backend=backend, plans_factory=plans)
    try:
        yield made
    finally:
        if made.session is not None:
            made.force_close(made.session.session_id)
        backend.shutdown()


def opened(worker: Worker, site: str, *, attempt: int = 1) -> tuple[str, str]:
    """세션 하나. **실행마다 다른 `business_key`**다 (C10) — 멱등 키의 뿌리다."""
    request = SessionRequest(
        schema=1,
        caller=Caller(type="bot", run_id=RUN, node_id="Task_Fill", attempt=attempt),
        mode="deterministic",
        business_key=f"{RUN}:Task_Fill:1:{attempt}",
        page_id=PAGE_ID,
        start_url=site,
        service_key=KEY,
    )
    info, _ = worker.open(request)
    return info.session_id, info.session_secret


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_a_registered_page_can_be_driven(served: Any, worker: Worker, site: str) -> None:
    """등록 → 계획 → 조작·읽기 → 닫기. **한 줄로 맞물린다.**"""
    register(served, site)
    session_id, secret = opened(worker, site)
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


def test_the_ladder_falls_back_locally(served: Any, worker: Worker, site: str) -> None:
    """**첫 칸이 깨져도 다음 칸으로 간다** — 폴백 도중에는 네트워크를 타지 않는다 (C8)."""
    register(served, site, broken=True)
    session_id, secret = opened(worker, site)
    found = worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    assert found.ok
    assert found.fallback_depth == 1, "두 번째 칸으로 내려갔다"


def test_an_unregistered_key_is_refused(served: Any, worker: Worker, site: str) -> None:
    """등록하지 않은 요소는 **계획이 거절한다** (C8 `unknown_semantic_key`)."""
    register(served, site)
    session_id, secret = opened(worker, site)
    from chaeksas.ext.ui_automation.worker.app import WorkerProblem

    with pytest.raises(WorkerProblem) as caught:
        worker.step(session_id, secret, StepRequest(semantic_key="order.없는것", action="click"))
    assert caught.value.code == "unknown_semantic_key"


def test_the_report_carries_no_business_value(served: Any, worker: Worker, site: str) -> None:
    """**읽은 값은 보고에 들어가지 않는다** (원칙 6) — 합계 금액이 서버로 가면 안 된다."""
    register(served, site)
    session_id, secret = opened(worker, site)
    worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    worker.step(session_id, secret, StepRequest(semantic_key="order.total", action="read"))
    assert worker.session is not None
    raw = worker.session.report().model_dump_json()
    assert "1,200,000" not in raw and '"7"' not in raw
    assert PAGE_ID in raw


def test_three_runs_promote_through_the_whole_chain(served: Any, worker: Worker, site: str) -> None:
    """보고가 통계를 올리고 **세 번째에 승격**한다 (C8·C9) — 끝에서 끝까지."""
    from chaeksas.ext.ui_automation.client.registry_client import RegistryClient

    register(served, site)
    reader = RegistryClient(base_url="http://app", api_key=KEY, client=TestClient(served))
    for attempt in (1, 2, 3):
        session_id, secret = opened(worker, site, attempt=attempt)
        worker.step(session_id, secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
        assert worker.close(session_id, secret).report == "sent"

    found, _ = reader.get_page(PAGE_ID)
    assert found.locators["order.qty"][0].status == "active", "세 번 연속 성공이면 올라간다"
    assert found.locators["order.save"][0].status == "unverified", "쓰지 않은 것은 그대로다"


def test_a_trial_run_can_keep_its_hands_off_the_server(served: Any, worker: Worker, site: str) -> None:
    """BUI-08의 「결과를 서버에 보고」가 꺼져 있으면 **아예 보내지 않는다** (C10 `report`)."""
    from chaeksas.ext.ui_automation.client.registry_client import RegistryClient

    register(served, site)
    request = SessionRequest(
        schema=1,
        caller=Caller(type="selector_registration"),
        mode="deterministic",
        business_key="reg_abcd1234",
        page_id=PAGE_ID,
        start_url=site,
        report=False,
        service_key=KEY,
    )
    info, _ = worker.open(request)
    worker.step(info.session_id, info.session_secret, StepRequest(semantic_key="order.qty", action="fill", value="7"))
    closed = worker.close(info.session_id, info.session_secret)
    assert closed.report == "queued", "보내지 않았다 — 디스크 큐에만 남는다"

    found, _ = RegistryClient(base_url="http://app", api_key=KEY, client=TestClient(served)).get_page(PAGE_ID)
    assert found.locators["order.qty"][0].status == "unverified", "통계가 움직이지 않았다"


def test_a_goal_without_a_model_is_refused(served: Any, worker: Worker, site: str) -> None:
    """자연어 목표로 계획을 **지어내지 않는다** — 아직 없다고 분명히 말한다."""
    from chaeksas.ext.ui_automation.client.registry_client import RegistryClient, RegistryProblem

    register(served, site)
    client = RegistryClient(base_url="http://app", api_key=KEY, client=TestClient(served))
    with pytest.raises(RegistryProblem) as caught:
        client.call("plan", {"page_id": PAGE_ID, "goal": "수량을 넣고 저장"})
    assert caught.value.code == "plan_unsupported"
    assert caught.value.permanent

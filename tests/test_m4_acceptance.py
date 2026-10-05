"""M4 인수 시험 — 업무 예제의 M4 묶음을 **Studio 시험 실행**으로 돌린다 (조각 15).

로드맵의 M4 기준이다. M3과 다른 점은 **UI 태스크가 진짜로 돈다**는 것이다 — 진짜 UI 자동화
앱(in-process), 진짜 Worker, 진짜 Chromium, 시험이 띄운 진짜 화면. 데스크톱 예제는 Windows에서
진짜 UIA로 시험이 띄운 진짜 창(`fake_desktop_apps.py`)을 만진다.

**바깥에 나가지 않는다.** 앱도 화면도 127.0.0.1이고, 예제가 가리키는 화면은 시험이 그 자리에서
만들어 레지스트리에 등록한다 (사람이 BUI-06에서 하는 일을 시험이 대신한다).

**묶음 목록은 예제에서 읽는다** — `README.md`의 표를 사람이 옮겨 적으면 어긋난다.
"""

from __future__ import annotations

import json
import os  # noqa: E402
import re
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Case  # noqa: E402
from chaeksas.contracts.service_app import ServiceAppKey  # noqa: E402
from chaeksas.ext.ui_automation.client.agent_env import DesktopEnvironment  # noqa: E402
from chaeksas.ext.ui_automation.client.registry_client import RegistryClient  # noqa: E402
from chaeksas.ext.ui_automation.client.task import UiTaskExecutor  # noqa: E402
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, WindowSpec  # noqa: E402
from chaeksas.ext.ui_automation.contracts.registry import (  # noqa: E402
    ElementHint,
    PageRegistration,
)
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, create  # noqa: E402
from chaeksas.ext.ui_automation.service.store import Database, SqliteKeyStore  # noqa: E402
from chaeksas.ext.ui_automation.worker import desktop  # noqa: E402
from chaeksas.ext.ui_automation.worker.app import Worker  # noqa: E402
from chaeksas.ext.ui_automation.worker.browser import BrowserBackend, available  # noqa: E402
from chaeksas.ext.ui_automation.worker.desktop import AppLauncher, DesktopBackend  # noqa: E402
from chaeksas.ext.ui_automation.worker.plans import (  # noqa: E402
    HttpOps,
    PlanCache,
    PlanService,
    ReportQueue,
)
from chaeksas.ext.ui_automation.worker.routing import RoutingBackend  # noqa: E402
from chaeksas.service_kit import hash_key  # noqa: E402
from chaeksas.studio.run_dialog import AUTONOMOUS  # noqa: E402
from chaeksas.studio.runner import NO_EXPECT, PASS, CaseRun, Outcome, Plan, read_cases  # noqa: E402
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

#: 이 PC의 키 저장소에 든 UI 자동화 앱 키. 예제마다 **참조 이름이 다르다**
#: (`test-ui`·`purchase-portal` …) — 이름을 값으로 푸는 것은 PC의 몫이라, 시험은 어느
#: 이름이든 같은 키를 준다 (ADR-0013 — BPM 프로세스에는 이름만 있다).
KEY = "chk_svc_" + "m" * 40


def bundle() -> list[str]:
    """M4 묶음의 예제 파일 이름 — `README.md`의 표에서 읽는다 (M3 인수 시험과 같은 수법)."""
    body = (DOCS / "README.md").read_text(encoding="utf-8")
    row = next(line for line in body.splitlines() if line.startswith("| M4 |"))
    ids = [x.strip().lower().replace("-", "") for x in row.split("|")[2].split(",")]
    found = []
    for one in ids:
        match = next((p.stem for p in sorted(EXAMPLES.glob(f"{one}_*.bpmn"))), None)
        assert match, f"묶음에 적힌 {one}에 맞는 예제 파일이 없다"
        found.append(match)
    return found


M4 = bundle()

#: 아직 초록이 아닌 예제와 **그 이유**. 조용히 빼면 묶음이 거짓말을 한다.
REMAINING: dict[str, str] = {}

#: 데스크톱 UI 태스크 예제 — **Windows에서만** 돈다 (UIA). 다른 OS에서는 건너뛴다.
DESKTOP_EXAMPLES = {"bx17_erp_po_entry", "bx04_tax_invoice_issue", "fx05_desktop_autonomous"}

#: 공유 폴더를 흉내 내는 자리 — 예제가 적은 UNC 경로 대신 시험이 쓰기 허용 폴더를 준다
#: (ADR-0032). 경로만 그 PC의 것이고 **업무는 예제 그대로**다.
SHARE = "주문수집.xlsx"

#: 케이스가 모두 통과하는 예제. 줄어들면 회귀다.
GREEN = [one for one in M4 if one not in REMAINING]
WEB = [one for one in GREEN if one not in DESKTOP_EXAMPLES]


# ─────────────────────────── 시험이 띄우는 화면 ───────────────────────────

FORM = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>신청</title></head>
<body>
  <form id="main" action="/done" method="get">
    <input id="name" name="name" aria-label="이름" />
    <textarea id="body" name="body" aria-label="내용"></textarea>
    <button id="submit" type="submit">상신</button>
  </form>
</body></html>"""

DONE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>완료</title></head>
<body>
  <p id="message">접수되었습니다 (접수번호 R-2026-0042)</p>
  <p id="contact">담당자 김책사 02-1234-5678</p>
</body></html>"""

NOTICES = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공지</title></head>
<body>
  <table id="notices">
    <tr><th>번호</th><th>제목</th></tr>
    <tr><td>1</td><td><a id="first" href="/notice/1">정기 점검 안내</a></td></tr>
    <tr><td>2</td><td><a href="/notice/2">보안 교육 일정</a></td></tr>
  </table>
</body></html>"""

PORTAL = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공급사 포털</title></head>
<body>
  <input id="date" aria-label="조회일" />
  <button id="search">조회</button>
  <table id="orders">
    <tr><th>주문번호</th><th>공급사</th><th>금액</th></tr>
    <tr><td>PO-1001</td><td>한빛상사</td><td>1200000</td></tr>
    <tr><td>PO-1002</td><td>가온테크</td><td>850000</td></tr>
    <tr><td>PO-1003</td><td>다래물산</td><td>430000</td></tr>
  </table>
</body></html>"""

#: BX-04의 공급사 포털 거래 내역 — 4건, 합계 251,000 (예제의 「정상 발행」·「발행 대상 없음」이 갈린다).
TRANSACTIONS = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>거래 내역</title></head>
<body>
  <input id="month" aria-label="대상월" />
  <button id="search">조회</button>
  <table id="transactions">
    <tr><th>번호</th><th>거래처</th><th>금액</th></tr>
    <tr><td>1</td><td>한빛상사</td><td>120,000</td></tr>
    <tr><td>2</td><td>가온테크</td><td>85,000</td></tr>
    <tr><td>3</td><td>다래물산</td><td>43,000</td></tr>
    <tr><td>4</td><td>누리상회</td><td>3,000</td></tr>
  </table>
</body></html>"""

PAGES = {
    "/": FORM,
    "/form": FORM,
    "/done": DONE,
    "/notices": NOTICES,
    "/notice/1": DONE,
    "/portal": PORTAL,
    "/transactions": TRANSACTIONS,
}


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    """예제가 가리키는 화면 — 시험이 띄운다. **바깥에 나가지 않는다.**"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            raw = PAGES.get(path, NOTICES).encode("utf-8")
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
        thread.join(timeout=2)


def registrations(site: str) -> list[PageRegistration]:
    """예제의 `page_id`·시맨틱 키에 맞춰 등록한다 — 사람이 BUI-06에서 하는 일이다."""
    return [
        PageRegistration(
            schema=1,
            page_id="intranet.request.form",
            name="신청서",
            url_pattern=f"{site}/form",
            locators={
                "form.name": [LocatorSpec(type="css", value="#name")],
                "form.body": [LocatorSpec(type="css", value="#body")],
                "form.submit": [LocatorSpec(type="css", value="#submit")],
                # 상신 뒤 같은 세션에서 읽는다 (`navigates: true`).
                "result.message": [LocatorSpec(type="css", value="#message")],
            },
            elements={
                "form.name": ElementHint(name="이름", role="textbox"),
                "form.body": ElementHint(name="내용", role="textbox"),
                "form.submit": ElementHint(name="상신", role="button"),
                "result.message": ElementHint(name="접수 메시지", kind="text"),
            },
        ),
        PageRegistration(
            schema=1,
            page_id="intranet.request.done",
            name="접수 완료",
            url_pattern=f"{site}/done",
            locators={"owner.contact": [LocatorSpec(type="css", value="#contact")]},
            elements={"owner.contact": ElementHint(name="담당자 연락처", kind="text")},
        ),
        PageRegistration(
            schema=1,
            page_id="supplier.portal.orders",
            name="공급사 포털",
            url_pattern=f"{site}/portal",
            locators={
                "filter.date": [LocatorSpec(type="css", value="#date")],
                "filter.search": [LocatorSpec(type="css", value="#search")],
                "orders.table": [LocatorSpec(type="css", value="#orders")],
            },
            elements={
                "filter.date": ElementHint(name="조회일", role="textbox"),
                "filter.search": ElementHint(name="조회", role="button"),
                "orders.table": ElementHint(name="주문 표", kind="table"),
            },
        ),
        PageRegistration(
            schema=1,
            page_id="supplier.portal.transactions",
            name="공급사 포털 거래 내역",
            url_pattern=f"{site}/transactions",
            locators={
                "filter.month": [LocatorSpec(type="css", value="#month")],
                "filter.search": [LocatorSpec(type="css", value="#search")],
                "result.table": [LocatorSpec(type="css", value="#transactions")],
            },
            elements={
                "filter.month": ElementHint(name="대상월", role="textbox"),
                "filter.search": ElementHint(name="조회", role="button"),
                "result.table": ElementHint(name="거래 내역", kind="table"),
            },
        ),
        PageRegistration(
            schema=1,
            page_id="intranet.notice.list",
            name="공지 목록",
            url_pattern=f"{site}/notices",
            locators={
                "notice.table": [LocatorSpec(type="css", value="#notices")],
                "notice.first_link": [LocatorSpec(type="css", value="#first")],
            },
            elements={
                "notice.table": ElementHint(name="공지 표", kind="table"),
                "notice.first_link": ElementHint(name="첫 공지", role="link"),
            },
        ),
    ]


# ─────────────────────────── 진짜 앱·Worker ───────────────────────────


@pytest.fixture
def app(tmp_path: Path, site: str) -> Any:
    path = tmp_path / "uia.sqlite3"
    made = create(db_path=path, admin_token="t-admin")
    SqliteKeyStore(db=Database(path=path)).add(
        ServiceAppKey(
            name="인수 시험",
            hash=hash_key(KEY),
            prefix=KEY[:16],
            allowed_operations=["*"],
            allowed_modes=["deterministic", "autonomous"],
            extra_scopes=[REGISTRY_WRITE],
            created_at="2026-10-05T09:00:00+09:00",
        )
    )
    client = RegistryClient(base_url="http://app", api_key=KEY, client=TestClient(made))
    for page in registrations(site):
        client.register(page)
    return made


class Secrets:
    """`extension_api` 바깥 세상 — **키 참조 이름**을 값으로 푼다 (ADR-0013).

    이 PC에는 UI 자동화 앱 키가 하나다. 예제가 어떤 이름으로 가리키든 그 키를 준다.
    """

    def secret(self, ref: str) -> str | None:
        return KEY if ref else None


class Direct:
    """Worker를 **그 자리에서** 부른다 (HTTP 없이) — 인수 시험은 경계가 아니라 업무를 본다."""

    def __init__(self, worker: Worker) -> None:
        self.worker = worker

    def open(self, request: Any) -> Any:
        info, _ = self.worker.open(request)
        return info

    def step(self, session_id: str, secret: str, request: Any) -> Any:
        return self.worker.step(session_id, secret, request)

    def close(self, session_id: str, secret: str) -> Any:
        return self.worker.close(session_id, secret)

    def view(self, session_id: str, secret: str) -> Any:
        return self.worker.view(session_id, secret)


class Host:
    """`core.run_state.ExtensionTasks` — 태스크 종류로 수행기를, AI 태스크 domain으로 환경을 준다."""

    def __init__(self, worker: Worker) -> None:
        self._executor = UiTaskExecutor(client=Direct(worker))  # type: ignore[arg-type]
        # 데스크톱 AI 태스크의 눈과 손 — 같은 Worker 위에서 돈다 (ADR-0037).
        self._desktop = DesktopEnvironment(client=Direct(worker))  # type: ignore[arg-type]

    def executor(self, task_type: str) -> Any | None:
        return self._executor if task_type == "ui_task" else None

    def environment(self, domain: str) -> Any | None:
        return self._desktop if domain == "desktop" else None

    def environment_owner(self, domain: str) -> str | None:
        return "ui-automation" if domain == "desktop" else None

    def context(self, extension_id: str) -> Any:
        return Secrets()


@pytest.fixture
def host(app: Any, tmp_path: Path) -> Iterator[Host]:
    if not available():
        pytest.skip("Playwright가 없다")
    backend = BrowserBackend(headless=True)
    yield from _host(app, tmp_path, backend)


def _host(app: Any, tmp_path: Path, backend: Any) -> Iterator[Host]:
    client = TestClient(app)

    def plans(request: Any) -> PlanService:
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

    worker = Worker(token="t", admin_token="a", backend=backend, plans_factory=plans)
    try:
        yield Host(worker)
    finally:
        if worker.session is not None:
            worker.force_close(worker.session.session_id)
        backend.shutdown()


# ─────────────────────────── 데스크톱 (BX-17·BX-04) ───────────────────────────

FAKE_APPS = Path(__file__).resolve().parent / "fake_desktop_apps.py"


def erp_page(tag: str) -> PageRegistration:
    """BX-17의 `erp.desktop.po_entry` — 사람이 사다리를 적어 넣는 자리를 시험이 한다 (ADR-0033).

    창 조건에 시험마다 다른 꼬리표를 붙여 **이 시험이 띄운 창만** 맞게 한다.
    """
    aid = "QApplication.poEntry."  # Qt가 내보내는 AutomationId (`QApplication.<창>.<위젯>`)
    return PageRegistration(
        schema=1,
        page_id="erp.desktop.po_entry",
        platform="desktop",
        name="ERP 발주 입력",
        app="ERP Client",
        window=WindowSpec(title="^" + re.escape("ERP Client - 발주 입력" + tag) + "$"),
        locators={
            "po.item": [LocatorSpec(type="automation_id", value=aid + "itemCode", platform="desktop")],
            "po.qty": [LocatorSpec(type="automation_id", value=aid + "quantity", platform="desktop")],
            "po.save": [LocatorSpec(type="automation_id", value=aid + "saveButton", platform="desktop")],
            "po.number": [LocatorSpec(type="automation_id", value=aid + "poNumber", platform="desktop")],
        },
        elements={
            "po.item": ElementHint(name="품목", role="textbox"),
            "po.qty": ElementHint(name="수량", role="spinbutton"),
            "po.save": ElementHint(name="저장", role="button"),
            "po.number": ElementHint(name="발주번호", kind="text"),
        },
    )


def taxbook_page(tag: str) -> PageRegistration:
    """BX-04의 `accounting.taxbook.sheet` — 앱 이름 없이 화면(창 조건)만 가리키는 예제다 (ADR-0033)."""
    aid = "QApplication.taxbook."
    return PageRegistration(
        schema=1,
        page_id="accounting.taxbook.sheet",
        platform="desktop",
        name="세금계산서 발행대장",
        window=WindowSpec(title="^" + re.escape("회계 프로그램 - 세금계산서 발행대장" + tag) + "$"),
        locators={
            "row.next": [LocatorSpec(type="automation_id", value=aid + "nextRow", platform="desktop")],
            "menu.save": [LocatorSpec(type="automation_id", value=aid + "saveMenu", platform="desktop")],
            "cell.total": [LocatorSpec(type="automation_id", value=aid + "total", platform="desktop")],
        },
        elements={
            "row.next": ElementHint(name="다음 줄", role="textbox"),
            "menu.save": ElementHint(name="저장", role="button"),
            "cell.total": ElementHint(name="합계", kind="text"),
        },
    )


#: 데스크톱 예제마다 띄울 가짜 앱과 그 화면 등록 — **Windows에서만** 돈다 (UIA).
DESKTOP: dict[str, tuple[str, Any]] = {
    "bx17_erp_po_entry": ("erp", erp_page),
    "bx04_tax_invoice_issue": ("taxbook", taxbook_page),
    # 화면 등록이 없다 — Worker가 `desktop-apps.json`의 명령으로 띄우고 그 창 조건으로 붙는다 (ADR-0037).
    "fx05_desktop_autonomous": ("calc", None),
}
#: 웹 화면도 함께 쓰는 데스크톱 예제 — Chromium이 있어야 한다.
NEEDS_BROWSER = {"bx04_tax_invoice_issue"}


@pytest.fixture
def desktop_host(request: pytest.FixtureRequest, app: Any, tmp_path: Path) -> Iterator[Host]:
    """그 예제의 가짜 앱 창을 띄우고, Worker는 **경로 백엔드**로 웹·데스크톱을 함께 쓴다 (ADR-0033)."""
    example = str(request.param)
    if not desktop.available():
        pytest.skip("Windows UIA가 없다 — 데스크톱 예제는 Windows에서만 돈다")
    if example in NEEDS_BROWSER and not available():
        pytest.skip("Playwright가 없다 — 이 예제는 웹 화면도 쓴다")
    which, page_for = DESKTOP[example]
    tag = f" #{uuid.uuid4().hex[:8]}"
    web = BrowserBackend(headless=True) if example in NEEDS_BROWSER else None
    if page_for is None:
        yield from _launched_by_worker(app, tmp_path, which, tag)
        return
    page = page_for(tag)
    RegistryClient(base_url="http://app", api_key=KEY, client=TestClient(app)).register(page)
    # 시험 프로세스의 offscreen을 물려주지 않는다 — 창이 보여야 UIA가 본다.
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    proc = subprocess.Popen([sys.executable, str(FAKE_APPS), which, tag], env=env)
    try:
        deadline = time.monotonic() + 20
        while not desktop.find_windows(page.window) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert desktop.find_windows(page.window), f"가짜 앱 창({which})이 뜨지 않았다"
        yield from _host(app, tmp_path, RoutingBackend(web=web, desktop=DesktopBackend()))
    finally:
        if web is not None:
            web.shutdown()
        proc.kill()
        proc.wait(10)


def _launched_by_worker(app: Any, tmp_path: Path, which: str, tag: str) -> Iterator[Host]:
    """**창을 시험이 띄우지 않는다** — Worker가 그 PC의 앱 설정(`desktop-apps.json`)으로 띄운다 (C10)."""
    title = "^" + re.escape("계산기" + tag) + "$"
    apps = tmp_path / "desktop-apps.json"
    apps.write_text(
        json.dumps(
            {"Calculator": {"command": [sys.executable, str(FAKE_APPS), which, tag], "window": {"title": title}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        yield from _host(app, tmp_path, RoutingBackend(web=None, desktop=DesktopBackend(AppLauncher(apps))))
    finally:
        for window in desktop.find_windows(WindowSpec(title=title)):
            # Worker가 띄운 앱 — 시험이 끝나면 닫는다 (실제로는 Worker의 Job과 함께 꺼진다).
            pid = int(window.ProcessId)
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)


# ─────────────────────────── 스텁 모델 (BX-14의 doc AI 태스크) ───────────────────────────


class StubModel:
    """OpenAI 호환 `/v1/chat/completions` 하나.

    M3 인수 시험의 스텁과 다른 점: **도구를 진짜로 부른다.** BX-14의 일은 「시트에 덧붙이고
    중복은 건너뛴다」라서, 모델이 답만 지어내면 시험할 것이 남지 않는다 — 엑셀 쓰기
    도구(ADR-0032)가 실제로 돌고 그 결과를 그대로 답으로 쓴다.
    """

    def __init__(self, share: Path) -> None:
        self.share = share
        self.asked = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — http.server가 정한 이름
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.asked += 1
                raw = json.dumps(outer.reply(body)).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def reply(self, body: dict[str, Any]) -> dict[str, Any]:
        """처음에는 **도구를 부르고**, 도구 결과가 오면 그것을 답으로 옮긴다."""
        messages = body.get("messages") or []
        done = next(
            (m for m in reversed(messages) if m.get("role") == "tool"),
            None,
        )
        if done is None:
            rows = _rows_from(messages)
            call = {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "excel_writer_tool",
                    "arguments": json.dumps(
                        {"path": str(self.share), "rows": rows, "key": "주문번호"},
                        ensure_ascii=False,
                    ),
                },
            }
            return {
                "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            }
        found = json.loads(done.get("content") or "{}")
        answer = {"추가건수": int(found.get("added", 0)), "건너뜀": int(found.get("skipped", 0))}
        return {
            "choices": [{"message": {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

    def __enter__(self) -> StubModel:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class CalcModel(StubModel):
    """FX-05의 운전사 — **도구를 진짜로 부른다** (`desktop_look` → 단추 → `=` → 표시 칸 읽기).

    무엇을 누를지는 물음에 실려 온 `식`에서 정한다 — 시험하는 것은 모델의 똑똑함이 아니라
    「환경 도구가 진짜 창을 보고 누르고 읽어 결과가 변수로 오는가」다.
    """

    KEYS = {**{str(n): f"key{n}" for n in range(10)}, "*": "times", "+": "plus", "-": "minus", "/": "divide"}
    AID = "QApplication.calculator."

    def __init__(self) -> None:
        super().__init__(Path())
        self.looked = ""

    def reply(self, body: dict[str, Any]) -> dict[str, Any]:
        messages = body.get("messages") or []
        done = [m for m in messages if m.get("role") == "tool"]
        offered = {one["function"]["name"] for one in body.get("tools") or []}
        assert {"desktop_look", "desktop_act"} <= offered, f"환경 도구가 허용되지 않았다: {offered}"
        expression = _expression(messages)
        plan: list[tuple[str, dict[str, Any]]] = [("desktop_look", {})]
        plan += [("desktop_act", self._press(self.KEYS[ch])) for ch in expression]
        plan += [("desktop_act", self._press("equals"))]
        plan += [("desktop_act", {"target": {"type": "automation_id", "value": self.AID + "display"},
                                  "action": "read"})]
        if len(done) == 1:
            self.looked = str(done[0].get("content") or "")
        if len(done) < len(plan):
            name, arguments = plan[len(done)]
            call = {"id": f"call_{len(done) + 1}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}
            return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10}}
        shown = str(done[-1].get("content") or "")
        answer = {"결과": int(shown)}
        return {"choices": [{"message": {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10}}

    def _press(self, name: str) -> dict[str, Any]:
        return {"target": {"type": "automation_id", "value": self.AID + name}, "action": "click"}


def _expression(messages: list[dict[str, Any]]) -> str:
    """물음의 파라미터에 실린 `식` — 목표가 이름으로 가리킨 변수다 (C14 §AI 태스크가 보는 값)."""
    asked = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
    found = re.search(r'"식":\s*"([0-9+\-*/]+)"', asked)
    assert found, "모델에게 `식`이 가지 않았다"
    return found.group(1)


def _rows_from(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """물음에 실려 온 `주문`(포털 표 TSV)을 줄 목록으로 — **UI 태스크가 읽어 온 그것**이다.

    표는 JSON 글 안에 들어오기도 해서 (`\\t`) 둘 다 본다.
    """
    asked = "\n".join(str(m.get("content") or "") for m in messages)
    found = _json_rows(asked)
    if found:
        return found
    body = asked.replace("\\t", "\t").replace("\\n", "\n")
    rows = []
    for line in body.splitlines():
        cells = [one.strip().strip('"') for one in line.split("\t")]
        if len(cells) >= 3 and cells[0].startswith("PO-"):
            rows.append({"주문번호": cells[0], "공급사": cells[1], "금액": cells[2]})
    return rows


def _json_rows(text: str) -> list[dict[str, Any]]:
    """표가 **줄 목록**(ADR-0036)으로 실려 왔으면 그 사전들을 꺼낸다 — 글 안 어디에 있든."""
    decoder = json.JSONDecoder()
    rows: list[dict[str, Any]] = []
    for at, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text, at)
        except ValueError:
            continue
        if isinstance(value, dict) and str(value.get("주문번호", "")).startswith("PO-"):
            rows.append({"주문번호": value["주문번호"], "공급사": value.get("공급사"), "금액": value.get("금액")})
    return rows


# ─────────────────────────── 돌리기 ───────────────────────────


def drive(run: CaseRun, *, timeout_ms: int = 60_000) -> Outcome:
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

    loop = QEventLoop()
    box: list[Outcome] = []

    def done(outcome: Outcome) -> None:
        box.append(outcome)
        loop.quit()

    run.ended.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    run.start()
    loop.exec()
    if not box:
        pytest.fail(f"시험 실행이 {timeout_ms}ms 안에 끝나지 않았다")
    return box[0]


@pytest.fixture(scope="session")
def qt() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


def run_all(
    tmp_path: Path, example: str, host: Host, *, model: Any = None
) -> list[tuple[Case, Outcome]]:
    settings = replace(
        Settings(),
        data_dir=tmp_path / "studio",
        readable_dirs=(),
        writable_dirs=(tmp_path / "공유",),
        **({"llm_base_url": model.base_url, "llm_model": "stub"} if model is not None else {}),
    )
    (tmp_path / "공유").mkdir(parents=True, exist_ok=True)
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, example)
    definition = made.entry_definition
    assert definition is not None
    out = []
    for case in read_cases(made, definition):
        if case.manual:
            continue  # 사람이 창을 보는 케이스 — 자동으로 돌릴 것이 아니다
        plan = Plan(
            process=made,
            definition=definition,
            case=case,
            mode=AUTONOMOUS,
            settings=replace(settings),
            extensions=host,
        )
        out.append((case, drive(CaseRun(plan))))
    return out


# ─────────────────────────── 시험 ───────────────────────────


def test_the_bundle_is_read_from_the_examples() -> None:
    """묶음 목록을 사람이 옮겨 적지 않는다 — 어긋나는 순간 시험이 거짓말을 한다."""
    assert len(M4) == 6
    assert set(REMAINING) <= set(M4), "남은 목록에 묶음 밖 예제가 있다"
    assert len(GREEN) == 6, f"초록이 {len(GREEN)}개다 — 막힌 것이 있으면 REMAINING에 이유를 적는다"
    assert DESKTOP_EXAMPLES <= set(GREEN) and DESKTOP_EXAMPLES == set(DESKTOP)


def test_every_remaining_one_says_why() -> None:
    """**막힌 것은 이유를 적는다** — 「나중에」만 적으면 무엇을 고쳐야 할지 모른다."""
    for example, why in REMAINING.items():
        assert len(why) > 10 and ("없다" in why or "미뤘다" in why), f"{example}: {why}"
    assert set(REMAINING) == set(), "M4 묶음은 모두 초록이다"


#: AI 태스크가 있어 스텁 모델이 필요한 예제.
WITH_MODEL = {"bx14_supplier_portal_orders"}


@pytest.mark.skipif(not available(), reason="Playwright가 없다")
@pytest.mark.parametrize("example", WEB)
def test_an_m4_example_passes_all_its_cases(
    qt: Any, tmp_path: Path, host: Host, example: str
) -> None:
    """케이스가 **모두 통과**한다 — UI 태스크가 진짜 브라우저에서 돈다."""
    if example in WITH_MODEL:
        with StubModel(tmp_path / "공유" / SHARE) as model:
            results = run_all(tmp_path, example, host, model=model)
    else:
        results = run_all(tmp_path, example, host)
    assert results, f"{example}: 돌릴 케이스가 없다"
    bad = [(c.name, o.verdict, o.detail) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert not bad, f"{example}: {bad}"


@pytest.mark.parametrize("desktop_host", sorted(DESKTOP), indirect=True)
def test_a_desktop_example_passes_all_its_cases(qt: Any, tmp_path: Path, desktop_host: Host, request: Any) -> None:
    """데스크톱 예제 — **진짜 창**을 진짜 UIA로 (Windows). BX-04는 웹 포털 표를 읽어 회계 프로그램에 넣는다."""
    example = request.node.callspec.params["desktop_host"]
    if example == "fx05_desktop_autonomous":
        calc = CalcModel()
        with calc:
            results = run_all(tmp_path, example, desktop_host, model=calc)
        assert "QApplication.calculator.key1" in calc.looked, "desktop_look이 진짜 창의 트리를 보였다"
    else:
        results = run_all(tmp_path, example, desktop_host)
    assert results, f"{example}: 돌릴 케이스가 없다"
    bad = [(c.name, o.verdict, o.detail) for c, o in results if o.verdict not in (PASS, NO_EXPECT)]
    assert not bad, f"{example}: {bad}"


@pytest.mark.skipif(not available(), reason="Playwright가 없다")
def test_the_read_values_do_not_reach_the_report(qt: Any, tmp_path: Path, host: Host) -> None:
    """화면에서 읽은 값은 **BPM 프로세스 변수로** 가고 보고에는 안 간다 (원칙 6)."""
    results = run_all(tmp_path, "fx15_web_form", host)
    assert results and results[0][1].verdict in (PASS, NO_EXPECT)
    sent = list((tmp_path / "reports").glob("*.json")) + list(
        (tmp_path / "reports-rejected").glob("*.json")
    )
    for one in sent:
        raw = one.read_text(encoding="utf-8")
        assert "R-2026-0042" not in raw and "02-1234-5678" not in raw

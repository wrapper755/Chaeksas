"""M4 인수 시험 — 업무 예제의 M4 묶음을 **Studio 시험 실행**으로 돌린다 (조각 15).

로드맵의 M4 기준이다. M3과 다른 점은 **UI 태스크가 진짜로 돈다**는 것이다 — 진짜 UI 자동화
앱(in-process), 진짜 Worker, 진짜 Chromium, 시험이 띄운 진짜 화면.

**바깥에 나가지 않는다.** 앱도 화면도 127.0.0.1이고, 예제가 가리키는 화면은 시험이 그 자리에서
만들어 레지스트리에 등록한다 (사람이 BUI-06에서 하는 일을 시험이 대신한다).

**묶음 목록은 예제에서 읽는다** — `README.md`의 표를 사람이 옮겨 적으면 어긋난다.
"""

from __future__ import annotations

import os  # noqa: E402
import threading
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
from chaeksas.ext.ui_automation.client.registry_client import RegistryClient  # noqa: E402
from chaeksas.ext.ui_automation.client.task import UiTaskExecutor  # noqa: E402
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec  # noqa: E402
from chaeksas.ext.ui_automation.contracts.registry import (  # noqa: E402
    ElementHint,
    PageRegistration,
)
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, create  # noqa: E402
from chaeksas.ext.ui_automation.service.store import Database, SqliteKeyStore  # noqa: E402
from chaeksas.ext.ui_automation.worker.app import Worker  # noqa: E402
from chaeksas.ext.ui_automation.worker.browser import BrowserBackend, available  # noqa: E402
from chaeksas.ext.ui_automation.worker.plans import (  # noqa: E402
    HttpOps,
    PlanCache,
    PlanService,
    ReportQueue,
)
from chaeksas.service_kit import hash_key  # noqa: E402
from chaeksas.studio.run_dialog import AUTONOMOUS  # noqa: E402
from chaeksas.studio.runner import NO_EXPECT, PASS, CaseRun, Outcome, Plan, read_cases  # noqa: E402
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

#: 예제가 적어 둔 키 참조 이름 (`chk:process.service_keys`)과 그 값.
KEY_REF = "test-ui"
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
REMAINING: dict[str, str] = {
    "bx04_tax_invoice_issue": "데스크톱 UI 태스크 — Windows UIA 백엔드가 없다 (ADR-0020)",
    "bx17_erp_po_entry": "데스크톱 UI 태스크 — Windows UIA 백엔드가 없다 (ADR-0020)",
    "fx05_desktop_autonomous": "데스크톱 AI 태스크 (`domain: desktop`) — 데스크톱을 보는 길이 없다",
    "bx14_supplier_portal_orders": "엑셀 **쓰기** 도구가 없다 (ADR-0030이 미뤘다)",
}

#: 케이스가 모두 통과하는 예제. 줄어들면 회귀다.
GREEN = [one for one in M4 if one not in REMAINING]


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

PAGES = {"/": FORM, "/form": FORM, "/done": DONE, "/notices": NOTICES, "/notice/1": DONE}


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
    """`extension_api` 바깥 세상 — **키 참조 이름**을 값으로 푼다 (ADR-0013)."""

    def secret(self, ref: str) -> str | None:
        return KEY if ref == KEY_REF else None


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


class Host:
    """`core.run_state.ExtensionTasks` — 태스크 종류로 수행기를 준다."""

    def __init__(self, worker: Worker) -> None:
        self._executor = UiTaskExecutor(client=Direct(worker))  # type: ignore[arg-type]

    def executor(self, task_type: str) -> Any | None:
        return self._executor if task_type == "ui_task" else None

    def context(self, extension_id: str) -> Any:
        return Secrets()


@pytest.fixture
def host(app: Any, tmp_path: Path) -> Iterator[Host]:
    if not available():
        pytest.skip("Playwright가 없다")
    backend = BrowserBackend(headless=True)
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


def run_all(tmp_path: Path, example: str, host: Host) -> list[tuple[Case, Outcome]]:
    settings = replace(Settings(), data_dir=tmp_path / "studio", readable_dirs=())
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
    assert len(GREEN) == 2, f"초록이 {len(GREEN)}개다 — 막힌 것이 있으면 REMAINING에 이유를 적는다"


def test_every_remaining_one_says_why() -> None:
    """**막힌 것은 이유를 적는다** — 「나중에」만 적으면 무엇을 고쳐야 할지 모른다."""
    for example, why in REMAINING.items():
        assert len(why) > 10 and ("없다" in why or "미뤘다" in why), f"{example}: {why}"


@pytest.mark.skipif(not available(), reason="Playwright가 없다")
@pytest.mark.parametrize("example", GREEN)
def test_an_m4_example_passes_all_its_cases(
    qt: Any, tmp_path: Path, host: Host, example: str
) -> None:
    """케이스가 **모두 통과**한다 — UI 태스크가 진짜 브라우저에서 돈다."""
    results = run_all(tmp_path, example, host)
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

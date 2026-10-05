"""M4 인수 시험 — 업무 예제의 M4 묶음을 **Studio 시험 실행**으로 돌린다 (조각 15).

로드맵의 M4 기준이다. M3과 다른 점은 **UI 태스크가 진짜로 돈다**는 것이다 — 진짜 UI 자동화
앱(in-process), 진짜 Worker, 진짜 Chromium, 시험이 띄운 진짜 화면.

**바깥에 나가지 않는다.** 앱도 화면도 127.0.0.1이고, 예제가 가리키는 화면은 시험이 그 자리에서
만들어 레지스트리에 등록한다 (사람이 BUI-06에서 하는 일을 시험이 대신한다).

**묶음 목록은 예제에서 읽는다** — `README.md`의 표를 사람이 옮겨 적으면 어긋난다.
"""

from __future__ import annotations

import json
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
REMAINING: dict[str, str] = {
    "bx04_tax_invoice_issue": "데스크톱 UI 태스크 — Windows UIA 백엔드가 없다 (ADR-0020)",
    "bx17_erp_po_entry": "데스크톱 UI 태스크 — Windows UIA 백엔드가 없다 (ADR-0020)",
    "fx05_desktop_autonomous": "데스크톱 AI 태스크 (`domain: desktop`) — 데스크톱을 보는 길이 없다",
}

#: 공유 폴더를 흉내 내는 자리 — 예제가 적은 UNC 경로 대신 시험이 쓰기 허용 폴더를 준다
#: (ADR-0032). 경로만 그 PC의 것이고 **업무는 예제 그대로**다.
SHARE = "주문수집.xlsx"

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

PAGES = {
    "/": FORM,
    "/form": FORM,
    "/done": DONE,
    "/notices": NOTICES,
    "/notice/1": DONE,
    "/portal": PORTAL,
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


def _rows_from(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """물음에 실려 온 `주문`(포털 표 TSV)을 줄 목록으로 — **UI 태스크가 읽어 온 그것**이다.

    표는 JSON 글 안에 들어오기도 해서 (`\\t`) 둘 다 본다.
    """
    asked = "\n".join(str(m.get("content") or "") for m in messages)
    body = asked.replace("\\t", "\t").replace("\\n", "\n")
    rows = []
    for line in body.splitlines():
        cells = [one.strip().strip('"') for one in line.split("\t")]
        if len(cells) >= 3 and cells[0].startswith("PO-"):
            rows.append({"주문번호": cells[0], "공급사": cells[1], "금액": cells[2]})
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
    assert len(GREEN) == 3, f"초록이 {len(GREEN)}개다 — 막힌 것이 있으면 REMAINING에 이유를 적는다"


def test_every_remaining_one_says_why() -> None:
    """**막힌 것은 이유를 적는다** — 「나중에」만 적으면 무엇을 고쳐야 할지 모른다."""
    for example, why in REMAINING.items():
        assert len(why) > 10 and ("없다" in why or "미뤘다" in why), f"{example}: {why}"
    assert set(REMAINING) == {"bx04_tax_invoice_issue", "bx17_erp_po_entry", "fx05_desktop_autonomous"}
    assert all("데스크톱" in why for why in REMAINING.values()), "남은 셋은 모두 데스크톱이다"


#: AI 태스크가 있어 스텁 모델이 필요한 예제.
WITH_MODEL = {"bx14_supplier_portal_orders"}


@pytest.mark.skipif(not available(), reason="Playwright가 없다")
@pytest.mark.parametrize("example", GREEN)
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

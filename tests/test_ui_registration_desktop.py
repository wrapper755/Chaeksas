"""BUI-06 데스크톱 창에서 담기 (C10 §5, 09-gaps §6).

세 갈래다.

- **규칙** — UIA 컨트롤 줄 → 후보·사다리. UIA 없이 어느 OS에서나 돈다.
- **화면** — BUI-06의 「데스크톱 창」 방식. 가짜 Worker로 화면 없이 돈다.
- **진짜 창** — 가짜 회계 프로그램(`fake_desktop_apps.py taxbook`)을 **진짜 HTTP**(uvicorn)로
  붙고·분석하고·검증한다. 창구가 화면 스레드에서 UIA를 부르는 길을 밟는다 (Windows 전용).

거듭 보는 것 셋.

1. **창 안에서 겹치는 값은 사다리에 넣지 않는다** — Qt 라벨들은 AutomationId를 나눠 쓴다.
2. **창을 띄우지도 닫지도 않는다** — 사용자의 업무 앱이다.
3. 등록은 `platform: desktop`과 **창 조건**으로 간다 (C9).
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.ext.ui_automation.client.registration_window import (  # noqa: E402
    MODE_DESKTOP,
    RegistrationWidget,
)
from chaeksas.ext.ui_automation.contracts.plan import DESKTOP, WindowSpec  # noqa: E402
from chaeksas.ext.ui_automation.contracts.registration import (  # noqa: E402
    AnalyzeRequest,
    AnalyzeResult,
    Candidate,
    CheckRow,
    VerifyResult,
    ladder_for,
)
from chaeksas.ext.ui_automation.contracts.registry import RegistrationResult  # noqa: E402
from chaeksas.ext.ui_automation.contracts.worker_local import SessionInfo  # noqa: E402
from chaeksas.ext.ui_automation.worker import desktop  # noqa: E402
from chaeksas.ext.ui_automation.worker.registration import desktop_candidates  # noqa: E402

FAKE = Path(__file__).with_name("fake_desktop_apps.py")
TAXBOOK_TITLE = "회계 프로그램 - 세금계산서 발행대장"
AID = "QApplication.taxbook."


def control(control_type: str, name: str = "", aid: str = "", class_name: str = "") -> dict[str, str]:
    return {"control_type": control_type, "name": name, "automation_id": aid, "class_name": class_name}


#: 가짜 회계 프로그램의 UIA 트리를 줄로 옮긴 것 (실제로 훑어 본 모양 그대로).
TAXBOOK = [
    control("TextControl", "다음 줄", AID + "QLabel", "QLabel"),
    control("EditControl", "다음 줄", AID + "nextRow", "QLineEdit"),
    control("ButtonControl", "저장", AID + "saveMenu", "QPushButton"),
    control("TextControl", "발행대장", AID + "QLabel", "QLabel"),
    control("TableControl", "발행대장", AID + "sheet", "QTableWidget"),
    control("PaneControl", "", AID + "sheet", ""),  # 표의 안쪽 틀이 표와 같은 id를 쓴다
    control("TextControl", "합계", AID + "QLabel", "QLabel"),
    control("EditControl", "합계", AID + "total", "QLineEdit"),
]


def analyze(rows: list[dict[str, str]], **extra: Any) -> AnalyzeResult:
    return desktop_candidates(rows, AnalyzeRequest(schema=1, **extra))


# ─────────────────────────── 규칙 ───────────────────────────


def test_controls_are_taken_and_reads_only_when_asked() -> None:
    plain = analyze(TAXBOOK)
    assert [one.name for one in plain.candidates] == ["다음 줄", "저장", "합계"]
    assert {one.platform for one in plain.candidates} == {DESKTOP}
    with_reads = analyze(TAXBOOK, include_read=True)
    kinds = {one.control_type for one in with_reads.candidates}
    assert {"Text", "Table", "Edit", "Button"} <= kinds
    assert "Pane" not in kinds, "틀일 뿐인 것은 담지 않는다"


def test_shared_automation_ids_and_class_names_stay_out_of_the_ladder() -> None:
    """Qt 라벨 셋이 `…QLabel`을 나눠 쓴다 — 사다리에 넣으면 그 칸은 늘 「여럿이 잡힌다」다."""
    found = {(one.control_type, one.name): one for one in analyze(TAXBOOK, include_read=True).candidates}
    label = found[("Text", "합계")]
    assert label.element_id == "" and label.class_name == ""
    assert [one.type for one in ladder_for(label)] == ["control_name"]
    assert ladder_for(label)[0].control_type == "Text"

    total = found[("Edit", "합계")]
    assert total.element_id == AID + "total"
    assert total.class_name == "", "QLineEdit이 둘이다"
    assert [one.type for one in ladder_for(total)] == ["automation_id", "control_name"]

    table = found[("Table", "발행대장")]
    assert table.element_id == "", "표의 안쪽 틀(Pane)이 같은 AutomationId를 쓴다"
    assert [one.type for one in ladder_for(table)] == ["class_name", "control_name"]
    assert all(one.platform == DESKTOP for one in ladder_for(table))
    assert table.kind == "table"
    assert label.kind == "text" and label.actions == ["read"]


def test_keys_come_from_the_last_segment_of_the_automation_id() -> None:
    keys = {one.name: one.suggested_key for one in analyze(TAXBOOK).candidates}
    assert keys["다음 줄"] == "nextrow" or keys["다음 줄"].startswith("next")
    assert "qapplication" not in " ".join(keys.values())


def test_truncation_is_said() -> None:
    made = analyze(TAXBOOK, max=10, include_read=True)
    assert not made.truncated
    many = [control("ButtonControl", f"단추{n}", f"b{n}") for n in range(30)]
    cut = analyze(many, max=10)
    assert cut.truncated and cut.total == 30 and len(cut.candidates) == 10


# ─────────────────────────── 화면 ───────────────────────────


class FakeWorker:
    """C10을 흉내 낸다 — 데스크톱 창구만."""

    def __init__(self, *, refuse: Exception | None = None) -> None:
        self.refuse = refuse
        self.attached: list[dict[str, str]] = []
        self.analyzed: list[Any] = []
        self.closed: list[str] = []

    def registration_windows(self) -> list[dict[str, str]]:
        return [{"title": TAXBOOK_TITLE + " (1)", "class_name": "QWidget", "process": "python.exe"}]

    def open_registration_desktop(self, window: dict[str, str]) -> SessionInfo:
        if self.refuse is not None:
            raise self.refuse
        self.attached.append(window)
        return SessionInfo(session_id="ses_1", session_secret="s3cret", current_url="desktop:?")

    def analyze(self, session_id: str, secret: str, request: Any) -> AnalyzeResult:
        self.analyzed.append(request)
        return analyze(TAXBOOK, include_read=request.include_read)

    def verify(self, session_id: str, secret: str, ladders: dict[str, Any]) -> VerifyResult:
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


class Registry:
    def __init__(self) -> None:
        self.registered: list[Any] = []

    def get_page(self, page_id: str) -> Any:
        raise RuntimeError("닿지 못한다")

    def register(self, page: Any) -> Any:
        self.registered.append(page)
        return RegistrationResult(page_id=page.page_id, revision=1, created=[], kept=[], created_page=True)


class Refused(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


def desktop_mode(widget: RegistrationWidget) -> None:
    widget.mode.setCurrentText(MODE_DESKTOP)


def test_the_desktop_mode_lists_windows_and_turns_off_what_it_cannot_do(app: Any) -> None:
    widget = RegistrationWidget(FakeWorker())
    desktop_mode(widget)
    assert widget.window_pick.count() == 1
    assert widget.window_pick.itemText(0).endswith("— python.exe")
    assert widget.attach_button.isEnabled()
    assert not widget.pick_button.isEnabled() and "직접 고르기" in widget.pick_button.toolTip()
    assert not widget.scope.isEnabled()
    widget.close()


def test_attaching_sends_the_exact_title_and_never_guesses_the_page_id(app: Any) -> None:
    worker = FakeWorker()
    widget = RegistrationWidget(worker)
    desktop_mode(widget)
    widget.attach_window()
    sent = worker.attached[0]
    assert re.fullmatch(sent["title"], TAXBOOK_TITLE + " (1)"), "괄호까지 글자 그대로 맞춘다"
    assert sent["process"] == "python.exe"
    assert "붙었습니다" in widget.hint.text()
    assert not widget.mode.isEnabled(), "붙은 채로 방식을 바꾸지 않는다"

    widget.analyze()
    assert worker.analyzed[0].scope_css is None
    assert widget.page_id.currentText() == "", "창 제목에는 문서 이름이 섞인다"
    assert "화면 ID를 적으세요" in widget.hint.text()
    widget.close()


@pytest.mark.parametrize(
    ("code", "said"),
    [("window_ambiguous", "하나만 남기세요"), ("app_not_running", "새로 고침")],
)
def test_attaching_failures_say_what_to_do(app: Any, code: str, said: str) -> None:
    widget = RegistrationWidget(FakeWorker(refuse=Refused(code)))
    desktop_mode(widget)
    widget.attach_window()
    assert said in widget.hint.text()
    assert widget.attach_button.isEnabled(), "붙지 못했으니 다시 누를 수 있다"
    widget.close()


def test_a_desktop_page_goes_up_with_its_window(app: Any) -> None:
    registry = Registry()
    widget = RegistrationWidget(FakeWorker(), registry)
    desktop_mode(widget)
    widget.attach_window()
    widget.analyze()
    widget.page_id.setCurrentText("accounting.taxbook.sheet")
    widget.verify()
    widget.register()
    page = registry.registered[0]
    assert page.platform == DESKTOP
    assert page.url_pattern is None
    assert page.window is not None and page.window.process == "python.exe"
    assert re.fullmatch(page.window.title or "", TAXBOOK_TITLE + " (1)")
    assert all(one.platform == DESKTOP for ladder in page.locators.values() for one in ladder)
    widget.close()


def test_releasing_says_the_window_stays(app: Any) -> None:
    worker = FakeWorker()
    widget = RegistrationWidget(worker)
    desktop_mode(widget)
    widget.attach_window()
    widget.close_browser()
    assert worker.closed == ["ses_1"]
    assert "창은 그대로" in widget.hint.text()
    assert widget.mode.isEnabled()
    widget.close()


# ─────────────────────────── 진짜 창 (Windows) ───────────────────────────

needs_desktop = pytest.mark.skipif(
    not desktop.available(), reason="Windows UIA가 없다 (데스크톱 백엔드는 Windows 전용)"
)
TOKEN = "t-worker"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def launch(tag: str) -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    return subprocess.Popen([sys.executable, str(FAKE), "taxbook", tag], env=env)


def wait_for(tag: str, timeout_s: float = 20) -> Any:
    spec = WindowSpec(title=re.escape(TAXBOOK_TITLE + tag) + "$")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = desktop.find_windows(spec)
        if found:
            return found[0]
        time.sleep(0.2)
    raise AssertionError("가짜 회계 프로그램 창이 뜨지 않았다")


@pytest.fixture
def taxbook() -> Iterator[str]:
    tag = f" #{uuid.uuid4().hex[:8]}"
    proc = launch(tag)
    try:
        wait_for(tag)
        yield TAXBOOK_TITLE + tag
    finally:
        proc.kill()
        proc.wait(10)


@pytest.fixture
def worker_url() -> Iterator[str]:
    """Worker 창구를 **진짜 uvicorn**에 올린다 — 창구가 화면 스레드로 UIA를 넘기는 길."""
    import httpx  # noqa: PLC0415
    import uvicorn  # noqa: PLC0415

    from chaeksas.ext.ui_automation.worker.app import Worker, create_app  # noqa: PLC0415
    from chaeksas.ext.ui_automation.worker.desktop import DesktopBackend  # noqa: PLC0415
    from chaeksas.ext.ui_automation.worker.routing import RoutingBackend  # noqa: PLC0415

    worker = Worker(token=TOKEN, admin_token="a", backend=RoutingBackend(desktop=DesktopBackend()))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(worker), host="127.0.0.1", port=port, log_level="warning"))
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
        server.should_exit = True
        thread.join(10)


@needs_desktop
def test_attach_analyze_and_verify_a_real_window_over_http(worker_url: str, taxbook: str) -> None:
    import httpx  # noqa: PLC0415

    from chaeksas.ext.ui_automation.contracts.worker_local import SESSION_HEADER, TOKEN_HEADER  # noqa: PLC0415

    with httpx.Client(base_url=worker_url, headers={TOKEN_HEADER: TOKEN}, timeout=30) as http:
        listed = http.get("/v1/registration/windows")
        assert listed.status_code == 200, listed.text
        assert taxbook in [one["title"] for one in listed.json()["windows"]]

        exact = {"title": "^" + re.escape(taxbook) + "$"}
        opened = http.post("/v1/registration/desktop", json={"window": exact})
        assert opened.status_code == 201, opened.text
        session = opened.json()
        secret = {SESSION_HEADER: session["session_secret"]}
        where = f"/v1/registration/{session['session_id']}"

        result = http.post(f"{where}/analyze", json={"schema": 1, "include_read": True}, headers=secret)
        assert result.status_code == 200, result.text
        candidates = [Candidate.model_validate(one) for one in result.json()["candidates"]]
        ids = {one.element_id for one in candidates}
        assert {AID + "nextRow", AID + "saveMenu", AID + "total"} <= ids
        assert AID + "sheet" not in ids, "표와 그 안쪽 틀이 나눠 쓰는 id는 사다리에 넣지 않는다"
        assert "QTableWidget" in {one.class_name for one in candidates}
        assert not any(one.name in ("최소화", "닫기") for one in candidates), "창틀은 앱의 요소가 아니다"

        ladders = {
            f"k{index}": [one.to_json_dict() for one in ladder_for(found)]
            for index, found in enumerate(candidates)
        }
        checked = http.post(f"{where}/verify", json={"ladders": ladders}, headers=secret)
        assert checked.status_code == 200, checked.text
        rows = checked.json()["rows"]
        failed = [one for one in rows if not one["passed"]]
        assert not failed, failed

        closed = http.delete(f"/v1/sessions/{session['session_id']}", headers=secret)
        assert closed.status_code == 200, closed.text
    assert desktop.find_windows(WindowSpec(title=exact["title"])), "놓아도 창은 그대로다"


@needs_desktop
def test_a_window_that_is_not_there_is_a_409_and_nothing_is_launched(worker_url: str) -> None:
    import httpx  # noqa: PLC0415

    from chaeksas.ext.ui_automation.contracts.worker_local import TOKEN_HEADER  # noqa: PLC0415

    gone = {"title": "^없는 창 " + uuid.uuid4().hex + "$"}
    found = httpx.post(
        f"{worker_url}/v1/registration/desktop", json={"window": gone}, headers={TOKEN_HEADER: TOKEN}, timeout=30
    )
    assert found.status_code == 409
    assert found.json()["code"] == "app_not_running"

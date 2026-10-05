"""Windows 데스크톱 백엔드 (C10 `Backend`, C8 `Finder`, ADR-0020·0033).

두 갈래다.

- **규칙** — 로케이터·창 조건·키 이름·경로 백엔드·앱 설정. 어느 OS에서나 돈다.
- **진짜 창** — 시험이 띄운 가짜 ERP 창(`fake_desktop_apps.py`)을 UIA로 찾고 만진다. Windows에서
  `uiautomation`이 있을 때만 돈다. 사용자 창을 건드리지 않게 **창 조건에 시험마다 다른 꼬리표**를
  붙인다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from chaeksas.ext.ui_automation.contracts.plan import ExecutionPlan, LocatorSpec, PlanStep, WindowSpec
from chaeksas.ext.ui_automation.contracts.worker_local import Caller, SessionRequest, StepRequest
from chaeksas.ext.ui_automation.worker import desktop
from chaeksas.ext.ui_automation.worker.app import Worker, WorkerProblem
from chaeksas.ext.ui_automation.worker.desktop import (
    APP_NOT_RUNNING,
    WINDOW_AMBIGUOUS,
    AppLauncher,
    DesktopBackend,
    DesktopProblem,
    key_sequence,
    matches,
    window_matches,
)
from chaeksas.ext.ui_automation.worker.routing import BackendUnavailable, RoutingBackend, platform_of

FAKE = Path(__file__).with_name("fake_desktop_apps.py")
ERP_TITLE = "ERP Client - 발주 입력"
AID = "QApplication.poEntry."


def request(**extra: Any) -> SessionRequest:
    body: dict[str, Any] = {
        "schema": 1,
        "caller": Caller(type="bot", run_id="run_1", node_id="Task_Entry"),
        "mode": "deterministic",
        "business_key": "run_1:Task_Entry:1:1",
        "page_id": "erp.desktop.po_entry",
    }
    body.update(extra)
    return SessionRequest(**body)


def plan_for(tag: str, **extra: Any) -> ExecutionPlan:
    keys = {
        "po.item": LocatorSpec(type="automation_id", value=AID + "itemCode", platform="desktop"),
        "po.qty": LocatorSpec(type="class_name", value="QSpinBox", platform="desktop"),
        "po.save": LocatorSpec(type="automation_id", value=AID + "saveButton", platform="desktop"),
        "po.number": LocatorSpec(type="automation_id", value=AID + "poNumber", platform="desktop"),
    }
    body: dict[str, Any] = {
        "schema": 1,
        "plan_id": "plan_erp_1",
        "page_id": "erp.desktop.po_entry",
        "platform": "desktop",
        "app": "ERP Client",
        "window": WindowSpec(title=re.escape(ERP_TITLE + tag) + "$"),
        "locators": {key: [one] for key, one in keys.items()},
    }
    body.update(extra)
    return ExecutionPlan(**body)


# ─────────────────────────── 규칙 (어느 OS에서나) ───────────────────────────


def control(**kw: str) -> dict[str, str]:
    base = {"automation_id": "", "class_name": "", "name": "", "control_type": ""}
    base.update(kw)
    return base


def test_each_desktop_strategy_matches_its_own_property() -> None:
    edit = control(automation_id="txtItem", class_name="QLineEdit", name="품목 코드", control_type="EditControl")
    assert matches(LocatorSpec(type="automation_id", value="txtItem"), **edit)
    assert matches(LocatorSpec(type="class_name", value="QLineEdit"), **edit)
    # `control_name`은 `exact`가 아니면 부분 일치, `exact`면 정확히 (C8).
    assert matches(LocatorSpec(type="control_name", value="품목"), **edit)
    assert not matches(LocatorSpec(type="control_name", value="품목", exact=True), **edit)
    # `control_type`이 좁힌다 — UIA 이름(`Edit`)으로 적는다.
    assert matches(LocatorSpec(type="control_name", value="품목", control_type="Edit"), **edit)
    assert not matches(LocatorSpec(type="control_name", value="품목", control_type="Text"), **edit)


def test_a_web_strategy_is_refused_on_the_desktop() -> None:
    with pytest.raises(ValueError, match="데스크톱에서 쓸 수 없는 전략"):
        matches(LocatorSpec(type="css", value="#x"), **control())


def test_window_conditions_must_all_hold() -> None:
    spec = WindowSpec(title="^ERP Client", process="ERP.exe")
    assert window_matches(spec, title="ERP Client - 발주", class_name="Qt", process="erp.exe")
    assert not window_matches(spec, title="ERP Client - 발주", class_name="Qt", process="excel.exe")
    assert not window_matches(spec, title="메모장 - ERP Client", class_name="Qt", process="erp.exe")
    # 조건이 없으면 **아무 창도 아니다** — 앞에 있는 창에 입력하지 않게 (ADR-0033).
    assert not window_matches(WindowSpec(), title="아무 창", class_name="", process="")


def test_key_names_follow_the_web_ones_and_unknown_keys_are_refused() -> None:
    assert key_sequence("Enter") == "{Enter}"
    assert key_sequence("Control+A") == "{Ctrl}a"
    assert key_sequence("Shift+Tab") == "{Shift}{Tab}"
    assert key_sequence("F5") == "{F5}"
    with pytest.raises(ValueError):
        key_sequence("Hyper+Q")
    with pytest.raises(ValueError):
        key_sequence("글자")  # 키가 아니라 입력이다 — `fill`을 쓴다


def test_the_launcher_reads_only_its_own_app(tmp_path: Path) -> None:
    file = tmp_path / desktop.APPS_FILE
    file.write_text(
        json.dumps({"ERP Client": {"command": ["C:\\ERP\\erp.exe", "-q"], "start_timeout_s": 5}}), encoding="utf-8"
    )
    launcher = AppLauncher(apps_file=file)
    assert launcher.command("ERP Client") == (["C:\\ERP\\erp.exe", "-q"], 5.0)
    assert launcher.command("계산기") is None
    assert AppLauncher(apps_file=tmp_path / "없음.json").command("ERP Client") is None
    file.write_text("깨진 JSON", encoding="utf-8")
    assert launcher.command("ERP Client") is None


class Recorder:
    def __init__(self, name: str) -> None:
        self.name = name
        self.opened: list[Any] = []
        self.closed = 0

    def open(self, request: SessionRequest, plan: Any = None) -> str:
        self.opened.append(plan)
        return f"{self.name}:opened"

    def finder(self, business_key: str) -> str:
        return f"{self.name}-finder"

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        self.closed += 1


def test_the_plan_decides_which_backend_opens() -> None:
    web, screen = Recorder("web"), Recorder("desktop")
    routing = RoutingBackend(web=web, desktop=screen)
    assert routing.open(request(), plan_for("")) == "desktop:opened"
    assert routing.finder("k") == "desktop-finder"
    routing.close("s")
    assert screen.closed == 1
    assert routing.open(request(), plan_for("", platform="web")) == "web:opened"
    # 계획이 없으면 앱 이름이 있을 때만 데스크톱이다 (셀렉터 등록 세션은 웹).
    assert platform_of(request(), None) == "web"
    assert platform_of(request(app="ERP Client"), None) == "desktop"


def test_a_missing_backend_is_a_503_not_a_pretend() -> None:
    with pytest.raises(BackendUnavailable) as caught:
        RoutingBackend(web=Recorder("web"), desktop=None).open(request(), plan_for(""))
    assert caught.value.status == 503 and caught.value.code == "browser_unavailable"


def test_a_snapshot_line_hides_table_cells_and_the_window_title() -> None:
    def line(depth: int, kind: str, name: str) -> str:
        return desktop.snapshot_line(depth, control_type=kind, name=name, automation_id="a", class_name="c")

    assert '"•••"' in line(0, "WindowControl", "ERP Client - 거래처 한빛상사.xlsx")
    assert '"•••"' in line(3, "DataItemControl", "PO-0001")
    assert '"저장"' in line(2, "ButtonControl", "저장")
    assert '""' in line(3, "DataItemControl", ""), "빈 이름은 빈 채로 (가린 척하지 않는다)"


# ─────────────────────────── 진짜 창 (Windows) ───────────────────────────

needs_desktop = pytest.mark.skipif(
    not desktop.available(), reason="Windows UIA가 없다 (데스크톱 백엔드는 Windows 전용)"
)


def launch_erp(tag: str) -> subprocess.Popen[bytes]:
    """가짜 ERP 창을 띄운다. 시험 프로세스의 `offscreen`을 물려주지 않는다 (창이 보여야 UIA가 본다)."""
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    return subprocess.Popen([sys.executable, str(FAKE), "erp", tag], env=env)


def wait_window(tag: str, timeout_s: float = 20) -> Any:
    spec = WindowSpec(title=re.escape(ERP_TITLE + tag) + "$")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = desktop.find_windows(spec)
        if found:
            return found[0]
        time.sleep(0.2)
    raise AssertionError("가짜 ERP 창이 뜨지 않았다")


def kill_window(window: Any) -> None:
    subprocess.run(["taskkill", "/F", "/PID", str(window.ProcessId)], capture_output=True, check=False)


@pytest.fixture
def tag() -> str:
    return f" #{uuid.uuid4().hex[:8]}"


@pytest.fixture
def erp(tag: str) -> Iterator[Any]:
    proc = launch_erp(tag)
    try:
        window = wait_window(tag)
        yield window
        kill_window(window)
    finally:
        proc.kill()
        proc.wait(10)


@pytest.fixture
def opened(erp: Any, tag: str) -> Iterator[tuple[DesktopBackend, Any]]:
    backend = DesktopBackend()
    backend.open(request(), plan_for(tag))
    finder = backend.finder("run_1:Task_Entry:1:1")
    assert finder is not None
    yield backend, finder
    backend.close("s")


def find_one(finder: Any, locator: LocatorSpec) -> Any:
    found = finder.find(locator, timeout_ms=3000)
    assert found.unique, f"{locator.key} → {found.count}개 ({found.error})"
    return found.handle


def step(action: str, value: Any = None) -> PlanStep:
    return PlanStep(semantic_key="x", action=action, value=value)


@needs_desktop
def test_it_counts_matches_and_needs_exactly_one(opened: tuple[DesktopBackend, Any]) -> None:
    _, finder = opened
    find_one(finder, LocatorSpec(type="automation_id", value=AID + "itemCode", platform="desktop"))
    find_one(finder, LocatorSpec(type="class_name", value="QSpinBox", platform="desktop"))
    # 「품목」은 라벨과 입력칸 둘이 같은 이름이다 — 하나가 아니면 쓰지 않는다.
    both = finder.find(LocatorSpec(type="control_name", value="품목", platform="desktop"), timeout_ms=500)
    assert both.count == 2 and not both.unique
    find_one(finder, LocatorSpec(type="control_name", value="품목", control_type="Edit", platform="desktop"))
    missing = finder.find(LocatorSpec(type="automation_id", value="없는것", platform="desktop"), timeout_ms=300)
    assert missing.count == 0


@needs_desktop
def test_fill_types_the_value_as_is_and_checks_it(opened: tuple[DesktopBackend, Any]) -> None:
    _, finder = opened
    item = find_one(finder, LocatorSpec(type="automation_id", value=AID + "itemCode", platform="desktop"))
    # 키 문법으로 먹힐 글자들 — 그대로 들어가야 한다 (S1: pywinauto는 괄호를 먹었다).
    value = "P-100 {A} (B) +^%~ 품목"
    finder.act(item, step("fill", value), timeout_ms=3000)
    assert finder.read_value(item) == value
    # 키 입력으로 안 들어가는 글자는 값 패턴으로 넣고 확인한다 (ADR-0033).
    finder.act(item, step("fill", "품목😀"), timeout_ms=3000)
    assert finder.read_value(item) == "품목😀"
    quantity = find_one(finder, LocatorSpec(type="class_name", value="QSpinBox", platform="desktop"))
    finder.act(quantity, step("fill", "40"), timeout_ms=3000)
    assert finder.read_value(quantity) == "40"


@needs_desktop
def test_click_then_read_the_number_the_app_made(opened: tuple[DesktopBackend, Any]) -> None:
    _, finder = opened
    save = find_one(finder, LocatorSpec(type="automation_id", value=AID + "saveButton", platform="desktop"))
    number = find_one(finder, LocatorSpec(type="automation_id", value=AID + "poNumber", platform="desktop"))
    assert finder.act(number, step("read"), timeout_ms=3000) == ""
    finder.act(save, step("click"), timeout_ms=3000)
    finder.act(save, step("click"), timeout_ms=3000)
    assert finder.act(number, step("read"), timeout_ms=3000) == "PO-0002"
    # Qt는 표 안쪽 부품(머리줄 등)에도 같은 AutomationId를 붙인다 — 하나가 아니면 쓰지 않으니
    # 등록할 때 컨트롤 종류로 좁힌다 (C8 `control_type`). 사내 앱에서도 흔한 모양이다.
    assert not finder.find(LocatorSpec(type="automation_id", value=AID + "history", platform="desktop"),
                           timeout_ms=500).unique
    table = find_one(
        finder, LocatorSpec(type="automation_id", value=AID + "history", control_type="Table", platform="desktop")
    )
    rows = str(finder.act(table, step("read_table"), timeout_ms=3000)).splitlines()
    assert [row.split("\t")[-1] for row in rows[-2:]] == ["PO-0001", "PO-0002"]


@needs_desktop
def test_select_from_a_list_and_read_it_back(opened: tuple[DesktopBackend, Any]) -> None:
    _, finder = opened
    box = find_one(finder, LocatorSpec(type="automation_id", value=AID + "warehouse", platform="desktop"))
    assert finder.act(box, step("read_options"), timeout_ms=3000).splitlines() == [
        "본사 창고",
        "제2 물류센터",
        "외부 보관",
    ]
    finder.act(box, step("select", "제2 물류센터"), timeout_ms=3000)
    assert finder.read_value(box) == "제2 물류센터"


@needs_desktop
def test_the_snapshot_hides_what_was_typed_and_the_url_hides_the_title(opened: tuple[DesktopBackend, Any]) -> None:
    _, finder = opened
    item = find_one(finder, LocatorSpec(type="automation_id", value=AID + "itemCode", platform="desktop"))
    finder.act(item, step("fill", "비밀품목-7731"), timeout_ms=3000)
    save = find_one(finder, LocatorSpec(type="automation_id", value=AID + "saveButton", platform="desktop"))
    finder.act(save, step("click"), timeout_ms=3000)
    tree, _ = finder.snapshot()
    assert "itemCode" in tree and "비밀품목-7731" not in tree
    assert "PO-0001" not in tree, "표 칸의 글은 업무 값이다 (C8)"
    assert "발주 입력" not in tree, "창 제목에는 업무 값이 있을 수 있다"
    assert '"저장"' in tree, "버튼 이름(라벨)은 남는다 — 치유가 그것으로 찾는다"
    # 창 제목에는 업무 값이 있을 수 있다 — 주소는 앱 이름뿐이다 (C10).
    assert finder.url() == "desktop:ERP Client"


@needs_desktop
def test_two_matching_windows_are_ambiguous(erp: Any, tag: str) -> None:
    second = launch_erp(tag)
    try:
        deadline = time.monotonic() + 20
        while len(desktop.find_windows(plan_for(tag).window)) < 2 and time.monotonic() < deadline:  # type: ignore[arg-type]
            time.sleep(0.2)
        with pytest.raises(DesktopProblem) as caught:
            DesktopBackend().open(request(), plan_for(tag))
        assert caught.value.status == 409 and caught.value.code == WINDOW_AMBIGUOUS
        assert caught.value.detail == {"count": 2}
    finally:
        for window in desktop.find_windows(plan_for(tag).window):  # type: ignore[arg-type]
            if window.ProcessId != erp.ProcessId:
                kill_window(window)
        second.kill()
        second.wait(10)


@needs_desktop
def test_no_window_and_no_way_to_start_it(tag: str, tmp_path: Path) -> None:
    with pytest.raises(DesktopProblem) as caught:
        DesktopBackend(launcher=AppLauncher(apps_file=tmp_path / desktop.APPS_FILE)).open(request(), plan_for(tag))
    assert caught.value.status == 409 and caught.value.code == APP_NOT_RUNNING
    assert caught.value.detail == {"app": "ERP Client"}


@needs_desktop
def test_it_starts_the_app_from_this_pcs_settings(tag: str, tmp_path: Path) -> None:
    apps = tmp_path / desktop.APPS_FILE
    apps.write_text(
        json.dumps({"ERP Client": {"command": [sys.executable, str(FAKE), "erp", tag], "start_timeout_s": 30}}),
        encoding="utf-8",
    )
    backend = DesktopBackend(launcher=AppLauncher(apps_file=apps))
    previous = os.environ.pop("QT_QPA_PLATFORM", None)  # 띄운 앱이 보이는 창이어야 한다
    try:
        assert backend.open(request(), plan_for(tag)) == "desktop:ERP Client"
    finally:
        if previous is not None:
            os.environ["QT_QPA_PLATFORM"] = previous
        for window in desktop.find_windows(plan_for(tag).window):  # type: ignore[arg-type]
            kill_window(window)


class DesktopPlans:
    """세션을 열 때 데스크톱 계획을 준다 (C8)."""

    def __init__(self, plan: ExecutionPlan) -> None:
        self.value = plan

    def plan(self, **kwargs: Any) -> tuple[ExecutionPlan, str]:
        return self.value, "server"

    def report(self, report: Any) -> str:
        return "sent"


@needs_desktop
def test_a_locked_screen_is_a_retryable_503(erp: Any, tag: str, monkeypatch: Any) -> None:
    worker = Worker(
        token="t",
        admin_token="a",
        backend=RoutingBackend(desktop=DesktopBackend()),
        plans=DesktopPlans(plan_for(tag)),
    )
    info, _ = worker.open(request())
    assert info.current_url == "desktop:ERP Client"
    monkeypatch.setattr(desktop, "screen_locked", lambda: True)
    with pytest.raises(WorkerProblem) as caught:
        worker.step(info.session_id, info.session_secret, StepRequest(semantic_key="po.save", action="click"))
    assert caught.value.status == 503 and caught.value.code == "session_locked"
    monkeypatch.setattr(desktop, "screen_locked", lambda: False)
    done = worker.step(info.session_id, info.session_secret, StepRequest(semantic_key="po.save", action="click"))
    assert done.ok
    worker.close(info.session_id, info.session_secret)

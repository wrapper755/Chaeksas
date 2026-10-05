"""데스크톱 AI 태스크의 손 — 계획 없는 세션, `target` 스텝, `view` (C10, ADR-0037).

화면 없이 가짜 백엔드로 Worker의 규칙과 확장의 도구(`desktop_look`·`desktop_act`)를 본다.
진짜 창(Windows UIA)으로 도는 한 바퀴는 M4 인수 시험의 FX-05다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chaeksas.ext.ui_automation.client.agent_env import ACT, LOOK, DesktopEnvironment
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, WindowSpec
from chaeksas.ext.ui_automation.contracts.worker_local import (
    Caller,
    SessionRequest,
    StepRequest,
    check_step,
)
from chaeksas.ext.ui_automation.worker.app import Worker, WorkerProblem
from chaeksas.ext.ui_automation.worker.desktop import AppLauncher
from chaeksas.ext.ui_automation.worker.ladder import Match
from chaeksas.extension_api import TaskContext, TaskFailed

RUN = "run_20261005_120000_abcdef"


class Screen:
    """가짜 계산기 — `key1`은 하나, `Button` 종류로만 찾으면 여럿."""

    def __init__(self) -> None:
        self.done: list[str] = []

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match:
        if locator.type == "automation_id" and locator.value in ("key1", "display"):
            return Match(count=1, handle=locator.value)
        if locator.type == "class_name":
            return Match(count=16)
        return Match(count=0)

    def act(self, handle: object, step: Any, *, timeout_ms: int) -> str | None:
        self.done.append(f"{handle}:{step.action}")
        return "408" if step.action == "read" else None

    def snapshot(self) -> tuple[str, str]:
        return 'WindowControl "•••" aid= class=\n  ButtonControl "1" aid=key1 class=QPushButton', ""

    def url(self) -> str:
        return "desktop:Calculator"


class Backend:
    def __init__(self) -> None:
        self.screen = Screen()
        self.opened: list[tuple[Any, Any]] = []

    def open(self, request: Any, plan: Any = None) -> str:
        self.opened.append((request, plan))
        return "desktop:Calculator"

    def finder(self, business_key: str) -> Screen:
        return self.screen

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


def request(**over: Any) -> SessionRequest:
    body: dict[str, Any] = {
        "schema": 1,
        "caller": Caller(type="studio", run_id=RUN, node_id="Task_Calc"),
        "mode": "autonomous",
        "business_key": f"{RUN}:Task_Calc:1:1",
        "app": "Calculator",
        "heal": False,
        "report": False,
    }
    body.update(over)
    return SessionRequest(**body)


@pytest.fixture
def worker() -> tuple[Worker, Backend]:
    backend = Backend()
    return Worker(token="t", admin_token="a", backend=backend), backend


# ─────────────────────────── Worker ───────────────────────────


def test_a_planless_session_opens_with_only_the_app_name(worker: tuple[Worker, Backend]) -> None:
    made, backend = worker
    info, _ = made.open(request())
    assert backend.opened[0][1] is None, "계획 없이 연다 — 창 조건은 그 PC의 앱 설정에서"
    assert info.page_id is None


def test_a_target_step_acts_only_on_exactly_one(worker: tuple[Worker, Backend]) -> None:
    made, backend = worker
    info, _ = made.open(request())
    one = {"type": "automation_id", "value": "key1"}
    found = made.step(info.session_id, info.session_secret, StepRequest(target=one, action="click"))
    assert found.ok and backend.screen.done == ["key1:click"]

    many = {"type": "class_name", "value": "QPushButton"}
    found = made.step(info.session_id, info.session_secret, StepRequest(target=many, action="click"))
    assert not found.ok and found.error_code == "target_not_unique" and "16개" in (found.error or "")
    assert backend.screen.done == ["key1:click"], "여럿이면 누르지 않는다"

    read = {"type": "automation_id", "value": "display"}
    found = made.step(info.session_id, info.session_secret, StepRequest(target=read, action="read"))
    assert found.ok and found.text == "408"


def test_view_gives_the_masked_tree(worker: tuple[Worker, Backend]) -> None:
    made, _ = worker
    info, _ = made.open(request())
    seen = made.view(info.session_id, info.session_secret)
    assert "aid=key1" in seen["text"] and seen["current_url"] == "desktop:Calculator"


def test_a_target_is_refused_in_a_session_with_a_plan() -> None:
    from chaeksas.ext.ui_automation.contracts.plan import ExecutionPlan  # noqa: PLC0415

    class Plans:
        def plan(self, **kwargs: Any) -> tuple[ExecutionPlan, str]:
            made = ExecutionPlan(
                schema=1, plan_id="p", page_id="calc.main", platform="desktop",
                window=WindowSpec(title="^계산기"),
                locators={"calc.one": [LocatorSpec(type="automation_id", value="key1", platform="desktop")]},
            )
            return made, "server"

        def report(self, report: Any) -> str:
            return "sent"

    made = Worker(token="t", admin_token="a", backend=Backend(), plans=Plans())
    info, _ = made.open(request(page_id="calc.main", app=None))
    with pytest.raises(WorkerProblem) as caught:
        made.step(info.session_id, info.session_secret,
                  StepRequest(target={"type": "automation_id", "value": "key1"}, action="click"))
    assert caught.value.code == "target_not_allowed", "등록된 화면은 시맨틱 키로 부른다"


def test_only_one_way_to_point_at_an_element() -> None:
    both = StepRequest(semantic_key="calc.one", target={"type": "automation_id", "value": "key1"}, action="click")
    assert check_step(both, deterministic=False) == "instruction_not_allowed"
    alone = StepRequest(target={"type": "automation_id", "value": "key1"}, action="click")
    assert check_step(alone, deterministic=True) is None, "로케이터 조건은 자연어가 아니다 — 재생된다"


def test_the_window_condition_comes_from_the_pc_app_settings(tmp_path: Path) -> None:
    apps = tmp_path / "desktop-apps.json"
    apps.write_text(
        json.dumps({"Calculator": {"command": ["calc.exe"], "window": {"process": "CalculatorApp.exe"}},
                    "Broken": {"command": ["x.exe"], "window": {}}}),
        encoding="utf-8",
    )
    launcher = AppLauncher(apps)
    assert launcher.window("Calculator") == WindowSpec(process="CalculatorApp.exe")
    assert launcher.window("Broken") is None, "빈 조건은 조건이 아니다"
    assert launcher.window("없는앱") is None


# ─────────────────────────── 확장의 도구 ───────────────────────────


class Direct:
    def __init__(self, worker: Worker) -> None:
        self.worker = worker

    def open(self, request: SessionRequest) -> Any:
        return self.worker.open(request)[0]

    def step(self, session_id: str, secret: str, request: StepRequest) -> Any:
        return self.worker.step(session_id, secret, request)

    def view(self, session_id: str, secret: str) -> Any:
        return self.worker.view(session_id, secret)

    def close(self, session_id: str, secret: str) -> Any:
        return self.worker.close(session_id, secret)


def context(**properties: Any) -> TaskContext:
    return TaskContext(extension=None, run_id=RUN, node_id="Task_Calc", mode="autonomous",  # type: ignore[arg-type]
                       properties=properties, business_key=f"{RUN}:Task_Calc:1:1")


def test_the_desktop_tools_look_act_and_close(worker: tuple[Worker, Backend]) -> None:
    made, backend = worker
    session = DesktopEnvironment(client=Direct(made)).open(  # type: ignore[arg-type]
        context(domain="desktop", desktop={"app": "Calculator"})
    )
    tools = {one.name: one for one in session.tools()}
    assert set(tools) == {LOOK, ACT}
    assert backend.opened[0][0].app == "Calculator" and not backend.opened[0][0].report
    assert "aid=key1" in tools[LOOK].run()
    assert tools[ACT].run(target={"type": "automation_id", "value": "key1"}, action="click") == "완료"
    assert tools[ACT].run(target={"type": "automation_id", "value": "display"}, action="read") == "408"
    failed = tools[ACT].run(target={"type": "class_name", "value": "QPushButton"}, action="click")
    assert failed.startswith("실패 (target_not_unique)"), "모델이 고칠 수 있게 글로 알린다"
    session.close()
    session.close()
    assert made.session is None, "닫았다 (두 번 닫아도 된다)"


def test_without_an_app_name_the_environment_refuses(worker: tuple[Worker, Backend]) -> None:
    made, _ = worker
    with pytest.raises(TaskFailed) as caught:
        DesktopEnvironment(client=Direct(made)).open(context(domain="desktop"))  # type: ignore[arg-type]
    assert caught.value.code == "desktop_app_missing"

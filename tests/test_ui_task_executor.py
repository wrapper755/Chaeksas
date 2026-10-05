"""UI 태스크 수행기 (M4 조각 4) — 실행기가 Worker를 부른다 (C10).

**진짜 Worker를 띄워** 부른다 (가짜 화면 백엔드로). 그래야 토큰·세션 비밀·사다리까지 한 줄로
맞물리는지 본다.

거듭 보는 것 다섯.

1. **시맨틱 키로만** 말한다 — 셀렉터가 수행기까지 올라오지 않는다.
2. **읽은 값은 BPM 프로세스 변수로** 가고, **기록에는 남지 않는다** (원칙 6).
3. **전환은 실패가 아니다** — 확인(CMN-01)으로 넘긴다.
4. **Worker가 다시 떴을 때**: 읽기만 했으면 다시 하고, **조작했으면 사람에게 넘긴다** (C10 §3).
5. **토큰이 바뀌면 다시 읽고** 한 번 더 부른다 (ADR-0023).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.ext.ui_automation.client.task import (
    ESCALATE_CONFIRMATION,
    SessionGone,
    UiTaskExecutor,
    WorkerClient,
    WorkerUnreachable,
    read_value,
    render,
    screen_value,
    session_event,
    table_rows,
)
from chaeksas.ext.ui_automation.contracts.plan import ExecutionPlan, LocatorSpec
from chaeksas.ext.ui_automation.contracts.worker_local import CloseResult, SessionSummary, StepResult
from chaeksas.ext.ui_automation.worker.app import Worker, create_app, write_tokens
from chaeksas.ext.ui_automation.worker.ladder import Match
from chaeksas.extension_api import ExtensionContext, TaskContext, TaskFailed

RUN = "run_20261005_120000_abcdef"
PAGE = "erp.order.form"


class Screen:
    """가짜 화면 — 어떤 시맨틱 키가 어떻게 되는지 정해 둔다."""

    def __init__(self, *, missing: set[str] | None = None) -> None:
        self.missing = missing or set()
        self.acted: list[str] = []
        self.filled: list[Any] = []

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match:
        return Match(count=0) if locator.value in self.missing else Match(count=1, handle=locator.value)

    def act(self, handle: object, step: Any, *, timeout_ms: int) -> str | None:
        self.acted.append(f"{step.semantic_key}:{step.action}")
        if step.action == "fill":
            self.filled.append(step.value)
        return "한빛상사" if step.action.startswith("read") else None

    def snapshot(self) -> tuple[str, str]:
        return ("", "")

    def url(self) -> str:
        return "https://erp.example/orders"


class Backend:
    def __init__(self, screen: Screen) -> None:
        self.screen = screen

    def open(self, request: Any, plan: Any = None) -> str:
        return "https://erp.example/orders"

    def finder(self, business_key: str) -> Screen:
        return self.screen

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


class Plans:
    """계획 — 시맨틱 키마다 로케이터 하나."""

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.reports: list[Any] = []
        self.value = ExecutionPlan(
            schema=1,
            plan_id="plan_1",
            page_id=PAGE,
            locators={key: [LocatorSpec(type="css", value=f"#{key}")] for key in keys},
        )

    def plan(self, **kwargs: Any) -> tuple[ExecutionPlan, str]:
        return self.value, "server"

    def report(self, report: Any) -> str:
        self.reports.append(report)
        return "sent"


@pytest.fixture
def worker(tmp_path: Path) -> tuple[Worker, TestClient, Screen, Plans]:
    screen = Screen()
    plans = Plans(("주문.수량", "주문.공급사", "주문.저장"))
    token, admin = write_tokens(tmp_path)
    made = Worker(token=token, admin_token=admin, backend=Backend(screen), plans=plans)
    return made, TestClient(create_app(made)), screen, plans


def client_for(tmp_path: Path, http: TestClient) -> WorkerClient:
    return WorkerClient(token_dir=tmp_path, client=http)


def extension() -> ExtensionContext:
    """확장 하나에 주어지는 바깥 세상 — **키 값은 호스트가 푼다** (ADR-0013)."""
    import logging

    return ExtensionContext(
        extension_id="ui-automation",
        extension_version="0.1.0",
        api_version="1",
        host="bot_ui",
        settings=_Settings(),
        secrets=_Secrets(),
        log=logging.getLogger("시험"),
    )


class _Settings:
    def get(self, key: str, default: Any = None) -> Any:
        return default


class _Secrets:
    def resolve(self, ref: str) -> str | None:
        return "sk-ui-자동화"


def context(**extra: Any) -> TaskContext:
    properties: dict[str, Any] = {
        "page_id": PAGE,
        "steps": [
            {"key": "주문.수량", "action": "fill", "value": "3"},
            {"key": "주문.공급사", "action": "read", "result": "공급사"},
            {"key": "주문.저장", "action": "click"},
        ],
    }
    properties.update(extra.pop("properties", {}))
    return TaskContext(
        extension=extension(),
        run_id=RUN,
        node_id="Task_Fill",
        mode="deterministic",
        properties=properties,
        **extra,
    )


# ─────────────────────────── 스텝 값의 템플릿 (ADR-0033) ───────────────────────────


def test_a_template_is_filled_from_the_variables() -> None:
    variables = {"수량": 3, "건": {"품목": "A-100", "메모": None}, "행": {"금액": 1200}}
    assert render("{수량}", variables) == "3"
    assert render("품목 {건.품목} / {건.메모}", variables) == "품목 A-100 / "
    assert render("{행}", variables) == '{"금액": 1200}', "사전은 JSON으로 들어간다"
    assert render("{{그대로}}", variables) == "{그대로}"
    assert render(5, variables) == 5, "글이 아닌 값은 그대로"


@pytest.mark.parametrize("value", ["{없는것}", "{건.없는키}", "{수량.키}", "{}", "{건.}"])
def test_an_unknown_or_broken_template_fails_the_task(value: str) -> None:
    with pytest.raises(TaskFailed):
        render(value, {"수량": 3, "건": {"품목": "A-100"}})


def test_the_executor_fills_step_values_before_sending(
    tmp_path: Path, worker: tuple[Worker, TestClient, Screen, Plans]
) -> None:
    _, http, screen, _ = worker
    steps = [{"key": "주문.수량", "action": "fill", "value": "{주문.수량}개"}]
    UiTaskExecutor(client=client_for(tmp_path, http)).execute(
        context(properties={"steps": steps}, inputs={"주문": {"수량": 7}})
    )
    assert screen.filled == ["7개"], "글자 그대로가 아니라 변수 값이 입력된다"


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_a_ui_task_runs_its_steps_and_returns_what_it_read(
    tmp_path: Path, worker: tuple[Worker, TestClient, Screen, Plans]
) -> None:
    _, http, screen, plans = worker
    found = UiTaskExecutor(client=client_for(tmp_path, http)).execute(context())

    assert screen.acted == ["주문.수량:fill", "주문.공급사:read", "주문.저장:click"]
    assert found.outputs["공급사"] == "한빛상사", "읽은 값은 BPM 프로세스 변수로 간다"
    assert found.outputs["_ui_session"]["result"] == "success"
    assert plans.reports, "끝나면 보고가 간다 (C8)"


def test_the_report_has_no_business_values(
    tmp_path: Path, worker: tuple[Worker, TestClient, Screen, Plans]
) -> None:
    """원칙 6 — 읽은 값이 UI 자동화 앱으로 나가면 안 된다."""
    import json

    _, http, _, plans = worker
    UiTaskExecutor(client=client_for(tmp_path, http)).execute(context())
    raw = json.dumps(plans.reports[0].to_json_dict(), ensure_ascii=False)
    assert "한빛상사" not in raw


def test_a_step_that_escalates_goes_to_a_human(
    tmp_path: Path, worker: tuple[Worker, TestClient, Screen, Plans]
) -> None:
    """**실패가 아니다** — 사람이 화면을 보고 계속/중단을 고른다 (CMN-01)."""
    _, http, screen, _ = worker
    screen.missing = {"#주문.저장"}

    with pytest.raises(TaskFailed) as caught:
        UiTaskExecutor(client=client_for(tmp_path, http)).execute(context())

    assert caught.value.escalate == ESCALATE_CONFIRMATION
    assert caught.value.code == "ui_escalated"


def test_the_session_is_closed_even_when_a_step_fails(
    tmp_path: Path, worker: tuple[Worker, TestClient, Screen, Plans]
) -> None:
    """닫지 않으면 자리가 묶인다 (유휴 시간이 올 때까지 다음 Bot이 못 쓴다)."""
    made, http, screen, _ = worker
    screen.missing = {"#주문.저장"}
    with pytest.raises(TaskFailed):
        UiTaskExecutor(client=client_for(tmp_path, http)).execute(context())
    assert made.session is None


# ─────────────────────────── Worker가 다시 떴을 때 (C10 §3) ───────────────────────────


def test_after_a_restart_a_read_only_task_is_retried_whole(tmp_path: Path) -> None:
    """읽기만 했으면 **처음부터 한 번** 다시 한다 — 같은 입력이 두 번 들어갈 일이 없다."""
    screen = Screen()
    plans = Plans(("주문.공급사",))
    token, admin = write_tokens(tmp_path)
    made = Worker(token=token, admin_token=admin, backend=Backend(screen), plans=plans)
    http = TestClient(create_app(made))

    gone = {"n": 0}
    real_step = WorkerClient.step

    def flaky(self: WorkerClient, session_id: str, secret: str, request: Any) -> Any:
        gone["n"] += 1
        if gone["n"] == 1:
            raise SessionGone("Worker가 다시 떴다")
        return real_step(self, session_id, secret, request)

    found = UiTaskExecutor(client=client_for(tmp_path, http))
    WorkerClient.step = flaky  # type: ignore[method-assign]
    try:
        outcome = found.execute(
            context(properties={"steps": [{"key": "주문.공급사", "action": "read", "result": "공급사"}]})
        )
    finally:
        WorkerClient.step = real_step  # type: ignore[method-assign]

    assert outcome.outputs["공급사"] == "한빛상사"
    assert gone["n"] == 2, "한 번 다시 했다"


def test_after_a_restart_a_mutating_task_goes_to_a_human(tmp_path: Path) -> None:
    """조작했으면 **다시 하지 않는다** — 같은 입력이 두 번 들어간다 (C10 §3)."""
    screen = Screen()
    plans = Plans(("주문.수량", "주문.저장"))
    token, admin = write_tokens(tmp_path)
    made = Worker(token=token, admin_token=admin, backend=Backend(screen), plans=plans)
    http = TestClient(create_app(made))

    calls = {"n": 0}
    real_step = WorkerClient.step

    def flaky(self: WorkerClient, session_id: str, secret: str, request: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:  # 첫 스텝(조작)은 성공한 뒤에 사라진다
            raise SessionGone("Worker가 다시 떴다")
        return real_step(self, session_id, secret, request)

    WorkerClient.step = flaky  # type: ignore[method-assign]
    try:
        with pytest.raises(TaskFailed) as caught:
            UiTaskExecutor(client=client_for(tmp_path, http)).execute(
                context(
                    properties={
                        "steps": [
                            {"key": "주문.수량", "action": "fill", "value": "3"},
                            {"key": "주문.저장", "action": "click"},
                        ]
                    }
                )
            )
    finally:
        WorkerClient.step = real_step  # type: ignore[method-assign]

    assert caught.value.code == "worker_restarted"
    assert caught.value.escalate == ESCALATE_CONFIRMATION
    assert "확인한 뒤" in str(caught.value)


# ─────────────────────────── 토큰 (ADR-0023) ───────────────────────────


def test_a_changed_token_is_read_again(tmp_path: Path) -> None:
    """Worker가 다시 뜨면 토큰이 바뀐다 — 401을 받으면 다시 읽고 한 번 더 부른다."""
    screen = Screen()
    plans = Plans(("주문.공급사",))
    write_tokens(tmp_path)  # 실행기가 들고 있을 **옛 토큰**
    token, admin = write_tokens(tmp_path)  # Worker가 다시 떠서 **새 토큰**
    made = Worker(token=token, admin_token=admin, backend=Backend(screen), plans=plans)
    http = TestClient(create_app(made))

    found = UiTaskExecutor(client=client_for(tmp_path, http)).execute(
        context(properties={"steps": [{"key": "주문.공급사", "action": "read", "result": "공급사"}]})
    )
    assert found.outputs["공급사"] == "한빛상사"


def test_an_unreachable_worker_is_retryable(tmp_path: Path) -> None:
    """Bot UI가 Worker를 못 띄웠다 — 다시 해 볼 만하다 (다음 주기에 뜬다)."""
    client = WorkerClient(token_dir=tmp_path, port=1)
    with pytest.raises(TaskFailed) as caught:
        UiTaskExecutor(client=client).execute(context())
    assert caught.value.code == "worker_unreachable" and caught.value.retryable


def test_the_client_says_when_it_cannot_reach(tmp_path: Path) -> None:
    with pytest.raises(WorkerUnreachable):
        WorkerClient(token_dir=tmp_path, port=1).call("GET", "/v1/health")


# ─────────────────────────── C3 `ui_session` ───────────────────────────


def test_the_session_event_carries_no_values() -> None:
    """C3 — 진행·폴백·치유만 남는다 (원칙 6)."""
    closed = CloseResult(
        steps_run=3,
        summary=SessionSummary(result="success", steps=3, fallback_depth_max=1, healed=True),
    )
    found = session_event(closed, business_key_=f"{RUN}:Task_Fill:1:1", page_id=PAGE)
    assert found == {
        "business_key": f"{RUN}:Task_Fill:1:1",
        "page_id": PAGE,
        "result": "success",
        "steps": 3,
        "fallback_depth_max": 1,
        "healed": True,
    }


# ─────────────────────────── 읽은 값의 모양 (ADR-0036) ───────────────────────────


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("251", 251),
        (" 1,200,000 ", 1200000),
        ("-3.5", -3.5),
        ("0", 0),
        ("0.25", 0.25),
        ("007", "007"),
        ("02-1234-5678", "02-1234-5678"),
        ("1,23", "1,23"),
        ("12%", "12%"),
        ("₩1,000", "₩1,000"),
        ("1.2.3", "1.2.3"),
        ("PO-0001", "PO-0001"),
        ("", ""),
    ],
)
def test_a_screen_value_is_a_number_only_when_it_looks_like_one(text: str, value: Any) -> None:
    assert screen_value(text) == value
    assert type(screen_value(text)) is type(value)


def test_a_table_becomes_rows_keyed_by_the_header() -> None:
    rows = table_rows(
        {
            "headers": ["거래처", "", "금액", "금액"],
            "rows": [["한빛상사", "x", "1,250,000", "3"], ["가온테크"], ["다래", "y", "7", "8", "남는 칸"]],
        }
    )
    assert rows[0] == {"거래처": "한빛상사", "열2": "x", "금액": 1250000, "금액_2": 3}
    assert rows[1] == {"거래처": "가온테크", "열2": "", "금액": "", "금액_2": ""}, "모자란 칸은 빈 글"
    assert len(rows[2]) == 4, "남는 칸은 버린다"


def test_read_results_become_variables_by_action() -> None:
    def result(action: str, text: str, data: Any = None) -> StepResult:
        return StepResult(ok=True, action=action, text=text, data=data)

    assert read_value(result("read", "1,000")) == 1000
    assert read_value(result("read_options", "1\n2")) == "1\n2", "고를 거리의 이름은 글"
    table = result("read_table", "a\tb\n1\t2", {"headers": ["a", "b"], "rows": [["1", "2"]]})
    assert read_value(table) == [{"a": 1, "b": 2}]

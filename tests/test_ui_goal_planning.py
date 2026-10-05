"""목표로 계획 — 목표 한 줄로 모델이 스텝을 세우고, 앱이 거르고, 수행기가 값을 채운다 (ADR-0035, M4 조각 22).

모델은 시험이 정한 답을 주는 `RecordingLlm`이다. 보는 것:

1. 모델에게 가는 것은 **시맨틱 정보와 이름**뿐이다 — 업무 값도 셀렉터도 없다 (원칙 6·ADR-0008).
2. 앱이 거른다 — 등록된 요소·할 수 있는 동작·값 규칙·이름 규칙. 어긋나면 422 `goal_plan_invalid`.
3. 결정 수행은 목표로 계획하지 않는다 (앱·Worker·수행기 셋 다).
4. **한 바퀴:** 수행기 → Worker → 앱(모델) → `planned_steps` → 수행기가 채워 하나씩 → 읽은 값은 변수로.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.ext.ui_automation.client.registry_client import RegistryClient
from chaeksas.ext.ui_automation.client.task import UiTaskExecutor, goal_values
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registry import CatalogEntry, ElementHint, PageRegistration
from chaeksas.ext.ui_automation.contracts.worker_local import Caller, SessionRequest
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, create
from chaeksas.ext.ui_automation.service.planning import MAX_STEPS, GoalPlanInvalid, messages_for, steps_from
from chaeksas.ext.ui_automation.service.store import Database, SqliteKeyStore
from chaeksas.ext.ui_automation.worker.app import Worker, WorkerProblem
from chaeksas.ext.ui_automation.worker.ladder import Match
from chaeksas.ext.ui_automation.worker.plans import HttpOps, PlanCache, PlanService, ReportQueue
from chaeksas.extension_api import ExtensionContext, TaskContext, TaskFailed
from chaeksas.llm import RecordingLlm, Reply
from chaeksas.service_kit import ServiceLlm, hash_key

KEY = "chk_svc_" + "g" * 40
PAGE = "intranet.request.form"
RUN = "run_20261005_110000_a1b2c3"
SECRET_VALUE = "수량-7731"
GOAL = "{신청.수량}을 수량 칸에 넣고 상신한 뒤 접수 메시지를 읽는다"


def page() -> PageRegistration:
    return PageRegistration(
        schema=1,
        page_id=PAGE,
        name="신청서",
        url_pattern="https://intranet.example/form",
        locators={
            "form.qty": [LocatorSpec(type="css", value="#qty")],
            "form.submit": [LocatorSpec(type="css", value="#submit")],
            "result.message": [LocatorSpec(type="css", value="#message")],
        },
        elements={
            "form.qty": ElementHint(name="수량", role="textbox"),
            "form.submit": ElementHint(name="상신", role="button"),
            "result.message": ElementHint(name="접수 메시지", kind="text"),
        },
        catalog={
            "form.qty": CatalogEntry(actions=["fill", "read"]),
            "form.submit": CatalogEntry(actions=["click"], depends_on=["form.qty"]),
            "result.message": CatalogEntry(actions=["read"]),
        },
    )


GOOD = [
    {"semantic_key": "form.qty", "action": "fill", "value": "{신청.수량}"},
    {"semantic_key": "form.submit", "action": "click"},
    {"semantic_key": "result.message", "action": "read", "result": "접수결과"},
]


def said(steps: Any) -> Reply:
    return Reply(text=json.dumps({"steps": steps}, ensure_ascii=False), model="m-plan", input_tokens=200,
                 output_tokens=40)


# ─────────────────────────── 묻는 것 ───────────────────────────


def test_the_model_sees_meaning_and_names_but_no_values_or_selectors() -> None:
    system, user = messages_for(GOAL, page(), ["신청.수량"], ["접수결과"])
    body = json.loads(user["content"])
    assert body["values"] == ["신청.수량"] and body["results"] == ["접수결과"]
    qty = next(one for one in body["elements"] if one["semantic_key"] == "form.qty")
    assert qty["name"] == "수량" and qty["actions"] == ["fill", "read"]
    submit = next(one for one in body["elements"] if one["semantic_key"] == "form.submit")
    assert submit["depends_on"] == ["form.qty"]
    assert "#qty" not in user["content"] and "#submit" not in user["content"], "셀렉터는 나가지 않는다 (ADR-0008)"
    assert SECRET_VALUE not in user["content"] + system["content"]


# ─────────────────────────── 거르는 것 ───────────────────────────


def test_a_good_plan_passes() -> None:
    steps = steps_from(json.dumps({"steps": GOOD}, ensure_ascii=False), page(), ["신청.수량"], ["접수결과"])
    assert [(one.semantic_key, one.action, one.value, one.result) for one in steps] == [
        ("form.qty", "fill", "{신청.수량}", None),
        ("form.submit", "click", None, None),
        ("result.message", "read", None, "접수결과"),
    ]


def test_a_value_may_go_below_an_allowed_name() -> None:
    """`신청`을 허락했으면 `{신청.수량}`도 된다 (사전 안의 값)."""
    one = [{"semantic_key": "form.qty", "action": "fill", "value": "{신청.수량}"}]
    assert steps_from(json.dumps({"steps": one}), page(), ["신청"], [])


@pytest.mark.parametrize(
    ("steps", "why"),
    [
        ([{"semantic_key": "form.nope", "action": "click"}], "등록되지 않은 요소"),
        ([{"semantic_key": "form.submit", "action": "fill", "value": "x"}], "할 수 없는 동작"),
        ([{"semantic_key": "form.qty", "action": "drag", "value": "x"}], "모르는 동작"),
        ([{"semantic_key": "form.submit", "action": "click", "value": "x"}], "click에는 값이 없다"),
        ([{"semantic_key": "form.qty", "action": "fill"}], "값 규칙"),
        ([{"semantic_key": "result.message", "action": "read", "value": "x"}], "값 규칙"),
        ([{"semantic_key": "form.qty", "action": "fill", "value": "{신청.주소}"}], "쓸 값에 없는 이름"),
        ([{"semantic_key": "form.qty", "action": "fill", "value": "x", "result": "접수결과"}], "읽기 스텝이 아닌데"),
        ([{"semantic_key": "result.message", "action": "read", "result": "몰래"}], "결과 변수에 없는 이름"),
    ],
)
def test_a_bad_step_fails_the_whole_plan_with_reasons(steps: list[dict[str, Any]], why: str) -> None:
    with pytest.raises(GoalPlanInvalid) as caught:
        steps_from(json.dumps({"steps": [GOOD[0], *steps]}, ensure_ascii=False), page(), ["신청.수량"], ["접수결과"])
    assert any(why in one for one in caught.value.reasons), caught.value.reasons


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("수량을 넣고 상신하세요", "JSON이 아니다"),
        ('{"steps": []}', "스텝이 없다"),
        (json.dumps({"steps": [GOOD[1]] * (MAX_STEPS + 1)}), "넘는다"),
    ],
)
def test_an_unusable_answer_is_invalid(text: str, why: str) -> None:
    with pytest.raises(GoalPlanInvalid) as caught:
        steps_from(text, page(), [], [])
    assert why in str(caught.value)


# ─────────────────────────── 앱 ───────────────────────────


def served(tmp_path: Path, model: RecordingLlm | None) -> TestClient:
    path = tmp_path / "uia.sqlite3"
    llm = ServiceLlm(model, model="m-plan") if model is not None else ServiceLlm()
    app = create(db_path=path, admin_token="t-admin", llm=llm)
    SqliteKeyStore(db=Database(path=path)).add(
        ServiceAppKey(
            name="개발",
            hash=hash_key(KEY),
            prefix=KEY[:16],
            allowed_operations=["*"],
            allowed_modes=["deterministic", "autonomous"],
            extra_scopes=[REGISTRY_WRITE],
            created_at="2026-10-05T09:00:00+09:00",
        )
    )
    client = TestClient(app)
    RegistryClient(base_url="http://app", api_key=KEY, client=client).register(page())
    return client


def plan_call(client: TestClient, *, mode: str = "autonomous", **extra: Any) -> Any:
    body = {
        "schema": 1,
        "mode": mode,
        "run_id": RUN,
        "node_id": "Task_Form",
        "node_instance": 1,
        "attempt": 1,
        "caller": {"type": "worker"},
        "input": {"page_id": PAGE, "goal": GOAL, "values": ["신청.수량"], "results": ["접수결과"], **extra},
    }
    return client.post("/v1/ops/plan", json=body, headers={"Authorization": f"Bearer {KEY}"})


def test_the_app_plans_from_a_goal_and_reports_usage(tmp_path: Path) -> None:
    client = served(tmp_path, RecordingLlm(replies=[said(GOOD)]))
    answer = plan_call(client)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert [one["semantic_key"] for one in body["output"]["steps"]] == ["form.qty", "form.submit", "result.message"]
    assert set(body["output"]["locators"]) == {"form.qty", "form.submit", "result.message"}
    assert body["usage"] == {"model": "m-plan", "input_tokens": 200, "output_tokens": 40}


def test_the_app_refuses_a_goal_in_deterministic_mode(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said(GOOD)])
    answer = plan_call(served(tmp_path, model), mode="deterministic")
    assert (answer.status_code, answer.json()["code"]) == (422, "mode_unsupported")
    assert not model.asked, "결정 수행은 LLM을 부르지 않는다"


def test_an_invalid_plan_is_422_with_reasons(tmp_path: Path) -> None:
    client = served(tmp_path, RecordingLlm(replies=[said([{"semantic_key": "form.nope", "action": "click"}])]))
    answer = plan_call(client)
    assert (answer.status_code, answer.json()["code"]) == (422, "goal_plan_invalid")
    assert answer.json()["detail"]["reasons"]


def test_without_a_model_a_goal_is_503(tmp_path: Path) -> None:
    answer = plan_call(served(tmp_path, None))
    assert (answer.status_code, answer.json()["code"]) == (503, "llm_unavailable")


# ─────────────────────────── 한 바퀴 ───────────────────────────


class Screen:
    def __init__(self) -> None:
        self.done: list[str] = []

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match:
        return Match(count=1, handle=locator.value)

    def act(self, handle: object, step: Any, *, timeout_ms: int) -> str | None:
        self.done.append(f"{step.semantic_key}:{step.action}:{step.value}")
        return "접수되었습니다 (R-2026-0042)" if step.action == "read" else None

    def snapshot(self) -> tuple[str, str]:
        return "", ""

    def url(self) -> str:
        return "https://intranet.example/form"


class Backend:
    def __init__(self, screen: Screen) -> None:
        self.screen = screen

    def open(self, request: Any, plan: Any = None) -> str:
        return "https://intranet.example/form"

    def finder(self, business_key: str) -> Screen:
        return self.screen

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


class Direct:
    """Worker를 그 자리에서 부른다 (HTTP 없이)."""

    def __init__(self, worker: Worker) -> None:
        self.worker = worker
        self.opened: list[SessionRequest] = []

    def open(self, request: SessionRequest) -> Any:
        self.opened.append(request)
        try:
            info, _ = self.worker.open(request)
        except WorkerProblem as e:
            raise TaskFailed(e.code, str(e)) from e
        return info

    def step(self, session_id: str, secret: str, request: Any) -> Any:
        return self.worker.step(session_id, secret, request)

    def close(self, session_id: str, secret: str) -> Any:
        return self.worker.close(session_id, secret)


class _Settings:
    def get(self, key: str, default: Any = None) -> Any:
        return default


class _Secrets:
    def resolve(self, ref: str) -> str | None:
        return KEY


def context(mode: str, properties: dict[str, Any], inputs: dict[str, Any]) -> TaskContext:
    extension = ExtensionContext(
        extension_id="ui-automation",
        extension_version="0.1.0",
        api_version="1",
        host="studio",
        settings=_Settings(),
        secrets=_Secrets(),
        log=logging.getLogger("시험"),
    )
    return TaskContext(
        extension=extension,
        run_id=RUN,
        node_id="Task_Form",
        mode=mode,
        properties={"page_id": PAGE, **properties},
        inputs=inputs,
        key_ref="test-ui",
    )


def wired(tmp_path: Path, model: RecordingLlm) -> tuple[UiTaskExecutor, Direct, Screen]:
    client = served(tmp_path, model)
    screen = Screen()

    def plans(request: SessionRequest) -> PlanService:
        return PlanService(
            ops=HttpOps(base_url="http://app", api_key=request.service_key or "", business_key=request.business_key,
                        mode=request.mode, client=client),
            cache=PlanCache(folder=tmp_path / "plans"),
            queue=ReportQueue(folder=tmp_path / "reports"),
        )

    direct = Direct(Worker(token="t", admin_token="a", backend=Backend(screen), plans_factory=plans))
    return UiTaskExecutor(client=direct), direct, screen  # type: ignore[arg-type]


def test_a_goal_runs_end_to_end_and_the_value_never_leaves(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said(GOOD)])
    executor, direct, screen = wired(tmp_path, model)
    found = executor.execute(
        context("autonomous", {"goal": GOAL, "results": ["접수결과"]}, {"신청": {"수량": SECRET_VALUE}})
    )
    assert screen.done == [
        f"form.qty:fill:{SECRET_VALUE}",
        "form.submit:click:None",
        "result.message:read:None",
    ], "수행기가 템플릿을 채워 하나씩 보냈다"
    assert found.outputs["접수결과"] == "접수되었습니다 (R-2026-0042)", "읽은 값은 결과 변수로"
    asked = json.dumps(model.asked, ensure_ascii=False)
    assert SECRET_VALUE not in asked, "업무 값은 모델로 나가지 않는다 (원칙 6)"
    assert SECRET_VALUE not in direct.opened[0].model_dump_json(), "세션 요청에도 값은 없다 — 이름뿐"
    assert direct.opened[0].values == ["신청.수량"]


def test_an_invalid_plan_is_a_business_failure_before_touching_the_screen(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said([{"semantic_key": "form.nope", "action": "click"}])])
    executor, _, screen = wired(tmp_path, model)
    with pytest.raises(TaskFailed) as caught:
        executor.execute(context("autonomous", {"goal": GOAL}, {"신청": {"수량": "1"}}))
    assert caught.value.code == "goal_plan_invalid"
    assert screen.done == [], "화면에 손대기 전에 멈춘다"


def test_a_goal_only_task_fails_in_deterministic_mode_without_asking(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said(GOOD)])
    executor, direct, _ = wired(tmp_path, model)
    with pytest.raises(TaskFailed) as caught:
        executor.execute(context("deterministic", {"goal": GOAL}, {"신청": {"수량": "1"}}))
    assert caught.value.code == "ui_goal_needs_autonomous"
    assert not direct.opened and not model.asked


def test_deterministic_mode_runs_the_written_steps_even_if_a_goal_is_there(tmp_path: Path) -> None:
    model = RecordingLlm(replies=[said(GOOD)])
    executor, direct, screen = wired(tmp_path, model)
    steps = [{"key": "form.submit", "action": "click"}]
    executor.execute(context("deterministic", {"goal": GOAL, "steps": steps}, {"신청": {"수량": "1"}}))
    assert screen.done == ["form.submit:click:None"]
    assert direct.opened[0].goal is None and not model.asked


def test_an_unknown_name_in_the_goal_fails_before_opening() -> None:
    with pytest.raises(TaskFailed) as caught:
        goal_values("{신청.주소}를 넣는다", {"신청": {"수량": 1}})
    assert caught.value.code == "ui_value_unknown"
    assert goal_values("{{그대로}} {신청.수량} {신청.수량}", {"신청": {"수량": 1}}) == ["신청.수량"]


def test_the_worker_refuses_a_goal_in_deterministic_mode() -> None:
    worker = Worker(token="t", admin_token="a", backend=Backend(Screen()))
    with pytest.raises(WorkerProblem) as caught:
        worker.open(
            SessionRequest(
                schema=1,
                caller=Caller(type="bot", run_id=RUN, node_id="Task_Form"),
                mode="deterministic",
                business_key=f"{RUN}:Task_Form:1:1",
                page_id=PAGE,
                goal=GOAL,
            )
        )
    assert (caught.value.status, caught.value.code) == (422, "instruction_not_allowed")

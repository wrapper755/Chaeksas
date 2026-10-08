"""결재의 현장 연결 (ADR-0038) — 엔진 → 요청 파일 → Bot UI → Center → 하트비트 → 제어 파일.

거듭 보는 것 넷.

1. **어디서 답하나는 엔진이 고른다** — `location`과 실행하는 쪽의 기본값. 확인은 늘 현장이다.
2. **값은 실행 기록에 없다** (원칙 6) — 검토 자료는 요청 파일로만 올라가고 끝나면 지운다.
3. **회수·만료는 답이 아니다** — 「답 없이 끝남」으로 오류 경계가 받거나 실행이 실패한다.
4. **현장에서 먼저 답하면 Center에서 거둔다** (`answered_in_field`).

뒤쪽 한 바퀴는 **진짜 실행기(자식 프로세스)와 진짜 Center 앱**으로 돈다.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeCredentials
from fastapi.testclient import TestClient

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.agent import Agent  # noqa: E402
from chaeksas.bot_ui.bots import install  # noqa: E402
from chaeksas.bot_ui.center_client import CenterClient  # noqa: E402
from chaeksas.bot_ui.runner import runner_args  # noqa: E402
from chaeksas.bot_ui.settings import Settings  # noqa: E402
from chaeksas.bot_ui.store import Store  # noqa: E402
from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.contracts.approvals import ApprovalCreateRequest  # noqa: E402
from chaeksas.contracts.bot_ui import ApprovalDispatch  # noqa: E402
from chaeksas.contracts.bpmn_ext import read_process, validate  # noqa: E402
from chaeksas.core import control, requests  # noqa: E402
from chaeksas.core.engine import Engine, EngineError, Run, RunEnv, State  # noqa: E402
from chaeksas.core.run_log import RunLog, log_path  # noqa: E402
from chaeksas.studio.packaging import default_name, export  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
RUN_ID = "run_20261007_090000_abc123"

SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="test.proc" name="시험">
    <bpmn:extensionElements><chk:process>{{}}</chk:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>
"""


def approval_process(*, kind: str = "userTask", location: str = "follow", extra: str = "",
                     boundary: bool = False) -> Any:
    props = json.dumps(
        {"title": "지급 승인", "description": "승인하면 지급합니다.", "show": ["금액"],
         "location": location, **({"expires": extra} if extra else {})},
        ensure_ascii=False,
    )
    caught = (
        '<bpmn:boundaryEvent id="Bnd_Gone" attachedToRef="Approve">'
        "<bpmn:errorEventDefinition/></bpmn:boundaryEvent>"
        '<bpmn:scriptTask id="Task_Gone" scriptFormat="chk-expr">'
        "<bpmn:script>사유 = error_code</bpmn:script></bpmn:scriptTask>"
        '<bpmn:endEvent id="End_2"/>'
        '<bpmn:sequenceFlow id="g1" sourceRef="Bnd_Gone" targetRef="Task_Gone"/>'
        '<bpmn:sequenceFlow id="g2" sourceRef="Task_Gone" targetRef="End_2"/>'
        if boundary
        else ""
    )
    return read_process(SHELL.format(body=(
        '<bpmn:startEvent id="Start_1"/>'
        '<bpmn:scriptTask id="Task_Amount" scriptFormat="chk-expr">'
        "<bpmn:script>금액 = 1100000</bpmn:script></bpmn:scriptTask>"
        f'<bpmn:{kind} id="Approve"><bpmn:extensionElements><chk:approval>{props}</chk:approval>'
        f"</bpmn:extensionElements></bpmn:{kind}>"
        '<bpmn:endEvent id="End_1"/>'
        '<bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Task_Amount"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Task_Amount" targetRef="Approve"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Approve" targetRef="End_1"/>'
        + caught
    )))


def waiting(process: Any, *, where: str = "field") -> tuple[Engine, Run]:
    engine = Engine()
    run = engine.start(
        process, run_id=RUN_ID, log=RunLog(run_id=RUN_ID), now=NOW,
        env=RunEnv(clock=lambda: NOW, approval_where=where),
    )
    assert engine.run_until_blocked(run) is State.WAITING
    return engine, run


def requested(run: Run) -> dict[str, Any]:
    return next(e.data for e in run.log.events if e.kind == "human_requested")


# ─────────────────────────── 어디서 답하나 (엔진) ───────────────────────────


@pytest.mark.parametrize(
    ("location", "default", "where"),
    [
        ("center", "field", "center"),  # BPM 프로세스가 정한 것이 이긴다
        ("field", "center", "field"),
        ("follow", "center", "center"),  # 「Bot UI 설정을 따름」 — BUI-03 「원격 결재」
        ("follow", "field", "field"),
    ],
)
def test_the_engine_picks_where_to_answer(location: str, default: str, where: str) -> None:
    _, run = waiting(approval_process(location=location), where=default)
    assert run.pending is not None and run.pending.where == where
    assert requested(run)["where"] == where


def form_process(fields: list[dict[str, Any]]) -> Any:
    """결재 뒤에 그 칸 이름을 쓰는 그림 — 답하지 않은 칸이 변수가 되는지 본다."""
    props = json.dumps({"title": "폼", "show": [], "fields": fields}, ensure_ascii=False)
    return read_process(SHELL.format(body=(
        '<bpmn:startEvent id="Start_1"/>'
        f'<bpmn:userTask id="Approve"><bpmn:extensionElements><chk:approval>{props}</chk:approval>'
        "</bpmn:extensionElements></bpmn:userTask>"
        '<bpmn:scriptTask id="Task_Use" scriptFormat="chk-expr">'
        "<bpmn:script>본 = 기간</bpmn:script></bpmn:scriptTask>"
        '<bpmn:endEvent id="End_1"/>'
        '<bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Approve"/>'
        '<bpmn:sequenceFlow id="f2" sourceRef="Approve" targetRef="Task_Use"/>'
        '<bpmn:sequenceFlow id="f3" sourceRef="Task_Use" targetRef="End_1"/>'
    )))


#: 답하지 않아도 되는 칸 하나 — 기본값이 있는 쪽과 없는 쪽.
WITH_DEFAULT = [{"key": "기간", "label": "기간", "type": "number", "required": False, "default": 90}]
WITHOUT_DEFAULT = [{"key": "기간", "label": "기간", "type": "number", "required": False}]


def test_an_unanswered_field_with_a_default_becomes_a_variable() -> None:
    """**Center와 같은 `apply_defaults`**를 엔진도 쓴다 (C6) — 두 쪽이 다른 값을 보지 않게."""
    engine, run = waiting(form_process(WITH_DEFAULT))
    (request_id,) = run.pendings
    engine.answer(run, request_id, {}, answered_by="사람")
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["기간"] == 90
    assert run.variables["본"] == 90


def test_an_unanswered_field_without_a_default_becomes_none() -> None:
    """기본값이 없는 선택 칸도 **변수가 된다** (`None`) — 결재 창이 보내는 것과 같은 값이다.

    빼 두면 BPM 프로세스가 그 이름을 쓸 수 없고(BX-10의 웹훅이 `의견`을 보낸다), 더 나쁘게는
    이름이 식 도우미로 떨어져 **함수**가 서비스 앱 본문에 실린다 (M5 조각 14).

    **지나지 않은 결재의 칸은 채우지 않는다** — 그쪽은 그대로 실패해야 한다 (BX-33).
    """
    engine, run = waiting(form_process(WITHOUT_DEFAULT))
    (request_id,) = run.pendings
    engine.answer(run, request_id, {}, answered_by="사람")
    assert engine.run_until_blocked(run) is State.DONE
    assert run.variables["기간"] is None
    assert run.variables["본"] is None


def test_a_confirmation_is_always_answered_in_the_field() -> None:
    """확인은 화면 앞 사람만 답한다 (C6) — `location: center`여도 현장이고, 검사가 알린다 (B12)."""
    process = approval_process(kind="manualTask", location="center")
    _, run = waiting(process, where="center")
    assert run.pending is not None and run.pending.where == "field"

    warned = [v for v in validate(process) if v.rule == "B12"]
    assert warned and all(v.severity == "warning" for v in warned), warned
    assert "현장" in warned[0].message


def test_a_duration_becomes_a_deadline_from_the_run_clock() -> None:
    _, run = waiting(approval_process(location="center", extra="PT4H"))
    assert run.pending is not None
    assert run.pending.expires_at == (NOW + timedelta(hours=4)).isoformat()
    assert requested(run)["expires_at"] == run.pending.expires_at


def test_the_request_body_is_the_c6_contract_as_is() -> None:
    """요청 파일의 한 줄은 C6 `ApprovalCreateRequest` 그대로다 — Bot UI는 짓지 않고 나른다."""
    _, run = waiting(approval_process(location="center"))
    assert run.pending is not None
    body = requests.create_request(run, run.pending).to_json_dict()
    again = ApprovalCreateRequest.model_validate(body)
    assert again.request_id == run.pending.request_id
    assert again.review == {"금액": 1100000}, "「표시 변수」만 담는다 (C6 `review`)"
    assert again.description == "승인하면 지급합니다."
    # **값은 실행 기록에 없다** (원칙 6) — 검토 자료는 요청 파일에만 간다.
    assert "1100000" not in json.dumps([e.data for e in run.log.events], ensure_ascii=False)


# ─────────────────────────── 답 없이 끝남 (엔진) ───────────────────────────


@pytest.mark.parametrize(
    ("reason", "code"), [("admin_withdraw", "APPROVAL_WITHDRAWN"), ("expired", "APPROVAL_EXPIRED")]
)
def test_a_withdrawn_approval_goes_to_the_error_boundary(reason: str, code: str) -> None:
    engine, run = waiting(approval_process(location="center", boundary=True))
    assert run.pending is not None
    assert engine.withdraw(run, run.pending.request_id, reason=reason) is not State.FAILED
    assert engine.run_until_blocked(run) is State.DONE, "경계로 받았으면 실패가 아니다"
    assert run.variables["사유"] == code
    gone = next(e for e in run.log.events if e.kind == "human_withdrawn")
    assert gone.data == {"request_id": f"apr_{RUN_ID}_Approve_1", "reason": reason}


def test_without_a_boundary_a_withdrawn_approval_fails_the_run() -> None:
    engine, run = waiting(approval_process(location="center"))
    assert run.pending is not None
    assert engine.withdraw(run, run.pending.request_id, reason="admin_withdraw") is State.FAILED
    assert run.error is not None and run.error.code == "APPROVAL_WITHDRAWN"
    assert not run.pendings


def test_withdrawing_what_is_not_waiting_is_refused() -> None:
    engine, run = waiting(approval_process(location="center"))
    with pytest.raises(EngineError, match="기다리는 요청이 아니다"):
        engine.withdraw(run, "apr_엉뚱한것", reason="admin_withdraw")


# ─────────────────────────── 파일 두 벌 ───────────────────────────


def test_a_withdraw_command_rides_the_control_file(tmp_path: Path) -> None:
    path = control.control_path(tmp_path, RUN_ID)
    control.withdraw(path, "apr_x", reason="expired")
    (found,) = control.take(path)
    assert (found.kind, found.request_id, found.reason) == (control.WITHDRAW, "apr_x", "expired")


def test_the_request_file_remembers_what_was_sent(tmp_path: Path) -> None:
    path = requests.requests_path(tmp_path, RUN_ID)
    requests.append(path, {"request_id": "a"})
    requests.append(path, {"request_id": "b"})
    assert [n for n, _ in requests.unsent(path)] == [1, 2]
    requests.mark_sent(path, 1)
    assert [body["request_id"] for _, body in requests.unsent(path)] == ["b"]

    # 반쯤 쓰인 줄은 다음에 — 그 뒤도 순서를 지켜 기다린다.
    with path.open("a", encoding="utf-8") as f:
        f.write('{"request_id": "c"')
    assert [body["request_id"] for _, body in requests.unsent(path)] == ["b"]

    requests.clear(path)
    assert not path.exists() and not list(tmp_path.rglob("*.sent"))


def test_the_command_line_says_where_only_when_it_is_not_the_default(tmp_path: Path) -> None:
    common: dict[str, Any] = {
        "package": tmp_path, "run_id": RUN_ID, "data_dir": tmp_path, "inputs_path": None,
        "mode": "deterministic", "source": "manual", "job_id": None,
    }
    assert "--approval-where" not in runner_args(**common)
    args = runner_args(**common, approval_where="center")
    assert args[args.index("--approval-where") + 1] == "center"


# ─────────────────────────── 한 바퀴 (진짜 실행기 + 진짜 Center) ───────────────────────────

ADMIN = "t-center-admin"
ADMIN_AUTH = {"Authorization": f"Bearer {ADMIN}"}
BASE_URL = "http://testserver"
EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
EXAMPLE = "fx19_manual_task_pc"


@pytest.fixture
def center(tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=ADMIN
    )
    with TestClient(create_app(settings)) as client:
        yield client


def follow_package(tmp_path: Path) -> Path:
    """가장 작은 PC 예제의 확인을 **「설정을 따름」 결재**로 바꿔 Studio처럼 내보낸다."""
    source = tmp_path / "examples"
    source.mkdir()
    text = (EXAMPLES / f"{EXAMPLE}.bpmn").read_text(encoding="utf-8")
    text = text.replace("bpmn:manualTask", "bpmn:userTask").replace('"location": "field"', '"location": "follow"')
    (source / f"{EXAMPLE}.bpmn").write_text(text, encoding="utf-8")
    made = Workspace(tmp_path / "studio").ensure().import_example(source, EXAMPLE)
    return export(made, tmp_path / default_name(made))


@pytest.fixture
def agent(center: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Agent]:
    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    key = center.post(
        "/api/v1/center-keys", json={"name": "시험 PC", "type": "bot_ui"}, headers=ADMIN_AUTH
    ).json()["key"]

    def factory(base_url: str, api_key: str) -> CenterClient:
        return CenterClient(base_url=BASE_URL, api_key=api_key, client=center)

    made = Agent(
        settings=Settings(name="재무팀 PC-03", center_url=BASE_URL, remote_approval=True),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials(key),
        client_factory=factory,
    )
    bot = install(data_dir, follow_package(tmp_path))
    made.enqueue_manual(bot.id, version=bot.version)
    yield made
    launcher = made.runner()
    if launcher.running is not None:
        launcher.stop(grace_s=2.0)


def wait_for(check: Any, *, timeout_s: float = 30.0) -> bool:
    until = time.monotonic() + timeout_s
    while time.monotonic() < until:
        if check():
            return True
        time.sleep(0.1)
    return False


def raised(agent: Agent, center: TestClient) -> dict[str, Any]:
    """실행기가 요청 파일에 쓰면 Bot UI가 하트비트 뒤에 올린다 — 결재함(CON-04)에 보인다."""
    assert agent.beat() is not None  # 등록하고 실행기를 띄운다
    running = agent.runner().running
    assert running is not None
    assert wait_for(lambda: bool(requests.unsent(running.requests_path))), "요청 파일에 올라오지 않았다"
    assert wait_for(lambda: bool(seen(running))), "기록에 결재 요청이 없다"
    (asked,) = running.pendings
    assert asked.where == "center", "「원격 결재」가 켜져 있으면 「따름」 결재는 Center로 간다"

    agent.beat()
    listing = center.get("/api/v1/approvals", headers=ADMIN_AUTH).json()
    (found,) = [row for row in listing if row["request_id"] == asked.request_id]
    assert found["state"] == "open" and found["host"]["type"] == "bot_ui"
    assert "오늘" in found["review"], "검토 자료는 요청 파일로 올라간다"
    assert not requests.unsent(running.requests_path), "보낸 자리를 남긴다"
    return dict(found)


def finished(agent: Agent) -> str:
    running = agent.runner().running
    assert running is not None
    assert wait_for(lambda: not running.alive), "실행기가 끝나지 않았다"
    agent.pump()
    assert not running.requests_path.exists(), "요청 파일은 끝나면 지운다 (업무 값이 있다)"
    return running.finished


def events(agent: Agent, run_id: str) -> list[Any]:
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    return list(RunLog.read(log_path(data_dir(), run_id)))


def test_a_center_answer_comes_down_the_heartbeat(agent: Agent, center: TestClient) -> None:
    found = raised(agent, center)
    run_id = found["run_id"]
    answered = center.post(
        f"/api/v1/approvals/{found['request_id']}/answer",
        json={"answer": {"decision": "approve"}},
        headers={**ADMIN_AUTH, "X-CHK-Actor": "kim"},
    )
    assert answered.status_code == 200, answered.text

    agent.beat()  # 답이 내려와 제어 파일로 간다
    assert finished(agent) == "success"
    agent.beat()  # 받았다고 알린다 (`approval_acks`)
    row = center.get(f"/api/v1/approvals/{found['request_id']}", headers=ADMIN_AUTH).json()
    assert row["delivered"] is True and row["delivery_accepted"] is True
    answered_event = next(e for e in events(agent, run_id) if e.kind == "human_answered")
    assert answered_event.data["answered_by"] == "kim"


def test_an_admin_withdraw_ends_the_approval_without_an_answer(agent: Agent, center: TestClient) -> None:
    """관리자 회수는 답이 아니다 — 경계가 없으면 실행이 실패로 끝난다 (C6)."""
    found = raised(agent, center)
    gone = center.delete(f"/api/v1/approvals/{found['request_id']}", headers=ADMIN_AUTH)
    assert gone.status_code == 200, gone.text

    agent.beat()
    assert finished(agent) == "failed"
    kinds = {e.kind: e for e in events(agent, found["run_id"])}
    assert kinds["human_withdrawn"].data["reason"] == "admin_withdraw"
    assert kinds["run_finished"].data["status"] == "failed"


def test_answering_in_the_field_first_takes_it_back_from_center(agent: Agent, center: TestClient) -> None:
    found = raised(agent, center)
    running = agent.runner().running
    assert running is not None
    running.answer(found["request_id"], {"decision": "approve"}, answered_by="현장")

    agent.beat()  # 하트비트 뒤에 거둔다
    row = center.get(f"/api/v1/approvals/{found['request_id']}", headers=ADMIN_AUTH).json()
    assert (row["state"], row["withdraw_reason"]) == ("withdrawn", "answered_in_field")
    assert finished(agent) == "success"


def test_an_answer_for_something_not_waiting_is_handed_back(agent: Agent) -> None:
    """지금 기다리지 않는 결재의 답은 받지 않는다 — Center가 다시 연다 (`not_waiting`)."""
    (ack,) = agent.apply_approvals(
        [ApprovalDispatch(request_id="apr_run_20261007_090000_abc123_X_1", state="answered", answer={})]
    )
    assert (ack.accepted, ack.reason) == (False, "not_waiting")
    (gone,) = agent.apply_approvals(
        [ApprovalDispatch(request_id="apr_run_20261007_090000_abc123_X_1", state="withdrawn")]
    )
    assert gone.accepted, "거둔 것은 할 일이 없으니 받았다고만 한다"


def test_the_run_log_shipper_reads_only_run_logs(tmp_path: Path) -> None:
    """제어 파일·요청 파일은 같은 `runs/`에 있지만 C3가 아니다 — 실어 보내면 하트비트가 깨진다."""
    from chaeksas.core.run_shipping import Queue  # noqa: PLC0415

    RunLog(run_id=RUN_ID, path=log_path(tmp_path, RUN_ID)).emit("run_started", executor="bot_ui", mode="deterministic")
    control.stop(control.control_path(tmp_path, RUN_ID))
    requests.append(requests.requests_path(tmp_path, RUN_ID), {"request_id": "a"})

    queue = Queue(data_dir=tmp_path)
    assert [p.name for p in queue.files()] == [f"{RUN_ID}.jsonl"]
    assert queue.unsent_count() == 1


def seen(running: Any) -> list[Any]:
    """기록을 다시 읽고 기다리는 요청을 돌려준다."""
    running.read()
    return list(running.pendings)

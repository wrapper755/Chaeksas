"""C10 Worker 로컬 API (M4 조각 1) — 경계·토큰·세션 하나·예약.

**화면을 실제로 만지는 일은 백엔드가 한다** — 여기서는 경계가 계약대로인지만 본다 (실제
Windows UIA·브라우저 백엔드는 다음 조각이다).

거듭 보는 것 다섯.

1. **`/v1/health`만 토큰 없이** 답한다 (기동 확인). 나머지는 토큰이 있어야 한다.
2. **세션은 한 번에 하나** (ADR-0014 §4) — 다른 쪽이 열면 409 `worker_busy`.
3. **세션 비밀**이 있어야 만질 수 있다 — 남의 세션을 닫지 못한다.
4. **예약**이 걸리면 그 실행의 세션만 열린다.
5. **값은 남지 않는다** (원칙 6) — 세션 상태에 읽은 글·입력 값이 담기지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.ext.ui_automation.contracts.plan import ExecutionPlan, LocatorSpec, PlanStep
from chaeksas.ext.ui_automation.contracts.worker_local import (
    ADMIN_HEADER,
    ADMIN_TOKEN_FILE,
    SESSION_HEADER,
    TOKEN_FILE,
    TOKEN_HEADER,
    SessionInfo,
    SessionRequest,
    StepRequest,
    business_key,
    can_retry_whole_task,
    check_step,
)
from chaeksas.ext.ui_automation.worker.app import (
    Worker,
    create_app,
    read_token,
    write_tokens,
)
from chaeksas.ext.ui_automation.worker.ladder import Match

TOKEN = "t-use"
ADMIN = "t-admin"
RUN = "run_20261005_120000_abcdef"


class FakeFinder:
    """시험용 화면 — 로케이터는 늘 하나에 맞는다 (사다리 규칙은 따로 본다)."""

    def __init__(self, *, escalate: bool = False, fail: bool = False) -> None:
        self.escalate = escalate
        self.fail = fail
        self.acted: list[PlanStep] = []

    def find(self, locator: Any, *, timeout_ms: int) -> Match:
        return Match(count=0) if self.escalate else Match(count=1, handle="el")

    def act(self, handle: object, step: PlanStep, *, timeout_ms: int) -> str | None:
        if self.fail:
            raise RuntimeError("시간이 지났다")
        self.acted.append(step)
        return "한빛상사" if step.action.startswith("read") else None

    def snapshot(self) -> tuple[str, str]:
        return ("", "")

    def url(self) -> str:
        return "https://erp.example/orders"


class FakeScreen:
    """시험용 백엔드 — 화면을 만지는 척한다. **사다리는 세션이 돌린다**."""

    def __init__(self, *, escalate: bool = False, fail: bool = False) -> None:
        self.closed: list[str] = []
        self._finder = FakeFinder(escalate=escalate, fail=fail)

    def open(self, request: SessionRequest) -> str:
        return request.start_url or "https://erp.example/orders"

    def finder(self, business_key: str) -> FakeFinder:
        return self._finder

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        self.closed.append(session_id)


class FakePlans:
    """시험용 계획 — 스텝마다 로케이터 하나짜리 사다리를 준다."""

    def __init__(self, keys: tuple[str, ...] = ("주문.수량", "주문.공급사", "줄")) -> None:
        self.reports: list[Any] = []
        self.plan_value = ExecutionPlan(
            schema=1,
            plan_id="plan_1",
            page_id="erp.order.form",
            locators={key: [LocatorSpec(type="css", value=f"#{index}")] for index, key in enumerate(keys)},
        )

    def plan(self, **kwargs: Any) -> tuple[ExecutionPlan, str]:
        return self.plan_value, "server"

    def report(self, report: Any) -> str:
        self.reports.append(report)
        return "sent"


def make(backend: Any = None, *, plans: Any = None, **kwargs: Any) -> tuple[Worker, TestClient]:
    worker = Worker(
        token=TOKEN,
        admin_token=ADMIN,
        backend=backend or FakeScreen(),
        plans=plans if plans is not None else FakePlans(),
        **kwargs,
    )
    return worker, TestClient(create_app(worker))


def session_body(**extra: Any) -> dict[str, Any]:
    body = {
        "schema": 1,
        "caller": {"type": "bot", "run_id": RUN, "node_id": "Task_Fill", "bpm_process_id": "erp.order"},
        "mode": "deterministic",
        "business_key": business_key(RUN, "Task_Fill"),
        "page_id": "erp.order.form",
        "service_key": "sk-값",
    }
    body.update(extra)
    return body


def opened(client: TestClient, **extra: Any) -> tuple[str, str]:
    answer = client.post("/v1/sessions", json=session_body(**extra), headers={TOKEN_HEADER: TOKEN})
    assert answer.status_code in (200, 201), answer.text
    body = answer.json()
    return body["session_id"], body["session_secret"]


def head(secret: str) -> dict[str, str]:
    return {TOKEN_HEADER: TOKEN, SESSION_HEADER: secret}


# ─────────────────────────── 토큰 ───────────────────────────


def test_health_answers_without_a_token() -> None:
    """기동 확인이 토큰을 요구하면 Bot UI가 Worker가 떴는지 알 수 없다 (C10 기동 절차)."""
    _, client = make()
    found = client.get("/v1/health")
    assert found.status_code == 200 and found.json()["status"] == "ok"
    assert found.json()["session"] == "idle"


def test_everything_else_needs_the_token() -> None:
    _, client = make()
    assert client.get("/v1/status").status_code == 401
    assert client.post("/v1/sessions", json=session_body()).status_code == 401


def test_the_use_token_cannot_do_admin_things() -> None:
    _, client = make()
    found = client.post("/v1/admin/reserve", json={"run_id": RUN}, headers={TOKEN_HEADER: TOKEN})
    assert found.status_code == 403 and found.json()["code"] == "admin_only"


def test_tokens_are_files_and_change_every_time(tmp_path: Path) -> None:
    """**명령줄로 넘기지 않는다** — 프로세스 목록에 뜬다 (C10 §전송)."""
    first, first_admin = write_tokens(tmp_path)
    assert read_token(tmp_path, TOKEN_FILE) == first
    assert read_token(tmp_path, ADMIN_TOKEN_FILE) == first_admin

    again, again_admin = write_tokens(tmp_path)
    assert again != first and again_admin != first_admin, "다시 띄우면 둘 다 바뀐다"


# ─────────────────────────── 세션 하나 ───────────────────────────


def test_a_session_opens_and_closes() -> None:
    screen = FakeScreen()
    plans = FakePlans()
    _, client = make(screen, plans=plans)
    session_id, secret = opened(client)

    found = client.delete(f"/v1/sessions/{session_id}", headers=head(secret))
    assert found.status_code == 200
    assert found.json()["summary"]["result"] == "success"
    assert found.json()["report"] == "sent", "보고를 보냈다 (C8)"
    assert screen.closed == [session_id]
    assert plans.reports[0].business_key == business_key(RUN, "Task_Fill")


def test_the_report_carries_no_business_values() -> None:
    """원칙 6 — 읽은 값이 UI 자동화 앱으로 나가면 안 된다 (C8 §report)."""
    plans = FakePlans()
    _, client = make(plans=plans)
    session_id, secret = opened(client)
    client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.공급사", "action": "read"},
        headers=head(secret),
    )
    client.delete(f"/v1/sessions/{session_id}", headers=head(secret))

    raw = json.dumps(plans.reports[0].to_json_dict(), ensure_ascii=False)
    assert "한빛상사" not in raw
    assert "주문.공급사" in raw, "무엇을 시도했는지는 남는다 (통계가 쓴다)"


def test_a_session_without_a_plan_cannot_step() -> None:
    """계획이 없으면 사다리가 없다 — 조용히 넘어가지 않는다."""
    worker = Worker(token=TOKEN, admin_token=ADMIN, backend=FakeScreen(), plans=None)
    client = TestClient(create_app(worker))
    session_id, secret = opened(client)
    found = client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.수량", "action": "fill", "value": "3"},
        headers=head(secret),
    )
    assert found.status_code == 422 and found.json()["code"] == "unknown_semantic_key"


def test_only_one_session_at_a_time() -> None:
    """ADR-0014 §4 — 다른 쪽이 쥐고 있으면 누가 쥐었는지 말해 준다."""
    _, client = make()
    opened(client)
    other = client.post(
        "/v1/sessions",
        json=session_body(business_key="다른키", caller={"type": "studio"}),
        headers={TOKEN_HEADER: TOKEN},
    )
    assert other.status_code == 409 and other.json()["code"] == "worker_busy"
    assert other.json()["detail"]["holder"]["run_id"] == RUN


def test_the_same_business_key_gets_the_same_session() -> None:
    """멱등 — 응답을 못 받고 다시 불러도 세션이 둘 생기지 않는다 (C10 §전송)."""
    _, client = make()
    first, secret = opened(client)
    answer = client.post("/v1/sessions", json=session_body(), headers={TOKEN_HEADER: TOKEN})
    assert answer.status_code == 200
    assert answer.json()["session_id"] == first and answer.json()["session_secret"] == secret


def test_another_secret_cannot_touch_the_session() -> None:
    _, client = make()
    session_id, _ = opened(client)
    # **헤더는 ASCII다** (CLAUDE.md §5) — 비밀도 ASCII로 만든다 (`token_urlsafe`).
    found = client.delete(f"/v1/sessions/{session_id}", headers=head("someone-elses-secret"))
    assert found.status_code == 401 and found.json()["code"] == "session_secret_invalid"


def test_an_idle_session_is_swept(tmp_path: Path) -> None:
    """부르는 쪽이 죽어도 자리가 영원히 묶이지 않는다."""
    now = [0.0]
    worker, client = make(idle_s=10.0, clock=lambda: now[0])
    opened(client)
    now[0] = 11.0
    assert client.get("/v1/health").json()["session"] == "idle"
    assert worker.session is None


def test_a_closed_session_is_404() -> None:
    _, client = make()
    session_id, secret = opened(client)
    client.delete(f"/v1/sessions/{session_id}", headers=head(secret))
    assert client.get(f"/v1/sessions/{session_id}", headers=head(secret)).status_code == 404


# ─────────────────────────── 스텝 ───────────────────────────


def test_a_step_runs_and_counts() -> None:
    screen = FakeScreen()
    _, client = make(screen)
    session_id, secret = opened(client)

    found = client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.수량", "action": "fill", "value": "3"},
        headers=head(secret),
    )
    assert found.status_code == 200 and found.json()["ok"] is True
    assert screen.finder("").acted[0].action == "fill", "사다리를 거쳐 조작까지 갔다"

    info = client.get(f"/v1/sessions/{session_id}", headers=head(secret)).json()
    assert info["steps_run"] == 1 and info["mutating_steps_ok"] == 1


def test_a_reading_step_does_not_count_as_mutating() -> None:
    """다시 해도 되는지 가르는 값이다 (C10 §3) — 읽기는 두 번 해도 된다."""
    _, client = make()
    session_id, secret = opened(client)
    client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.공급사", "action": "read"},
        headers=head(secret),
    )
    info = client.get(f"/v1/sessions/{session_id}", headers=head(secret)).json()
    assert info["steps_run"] == 1 and info["mutating_steps_ok"] == 0
    assert can_retry_whole_task(SessionInfo.model_validate(info)), "읽기만 했으면 다시 해도 된다"


def test_after_a_mutating_step_the_task_must_not_be_retried() -> None:
    """같은 입력이 두 번 들어간다 — 확인으로 사람에게 넘긴다 (C10 §3)."""
    _, client = make()
    session_id, secret = opened(client)
    client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.수량", "action": "fill", "value": "3"},
        headers=head(secret),
    )
    info = client.get(f"/v1/sessions/{session_id}", headers=head(secret)).json()
    assert not can_retry_whole_task(SessionInfo.model_validate(info))


def test_the_session_state_keeps_no_business_values() -> None:
    """원칙 6 — 읽은 글·입력 값이 상태에 남으면 화면·기록으로 샌다."""
    _, client = make()
    session_id, secret = opened(client)
    client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.수량", "action": "fill", "value": "비밀값"},
        headers=head(secret),
    )
    info = client.get(f"/v1/sessions/{session_id}", headers=head(secret)).json()
    assert "비밀값" not in json.dumps(info, ensure_ascii=False)
    assert "한빛상사" not in json.dumps(info, ensure_ascii=False)


def test_an_escalation_is_not_a_failure() -> None:
    """전환은 **사람 확인으로 넘어갈 거리**다 — 실패로 치지 않는다 (C10)."""
    _, client = make(FakeScreen(escalate=True))
    session_id, secret = opened(client)
    client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.수량", "action": "fill", "value": "3"},
        headers=head(secret),
    )
    summary = client.delete(f"/v1/sessions/{session_id}", headers=head(secret)).json()["summary"]
    assert summary["result"] == "escalated" and summary["escalated"] is True


def test_a_failed_step_makes_the_session_failed() -> None:
    _, client = make(FakeScreen(fail=True))
    session_id, secret = opened(client)
    client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"semantic_key": "주문.수량", "action": "fill", "value": "3"},
        headers=head(secret),
    )
    summary = client.delete(f"/v1/sessions/{session_id}", headers=head(secret)).json()["summary"]
    assert summary["result"] == "failed"


# ─────────────────────────── 요청 모양 (C10 §오류) ───────────────────────────


@pytest.mark.parametrize(
    ("request_", "deterministic", "code"),
    [
        (StepRequest(semantic_key="가", instruction="나", action="click"), False, "instruction_not_allowed"),
        (StepRequest(instruction="수량에 3을 넣어라", action="fill", value="3"), True, "instruction_not_allowed"),
        (StepRequest(action="click"), False, "unknown_semantic_key"),
        (StepRequest(semantic_key="가", action="fill"), False, "value_required"),
        (StepRequest(semantic_key="가", action="read", value="3"), False, "value_not_allowed"),
        (StepRequest(semantic_key="가", action="click"), False, None),
        (StepRequest(semantic_key="가", action="read"), False, None),
    ],
)
def test_the_step_shape_is_checked_the_same_on_both_sides(
    request_: StepRequest, deterministic: bool, code: str | None
) -> None:
    """**부르는 쪽과 Worker가 같은 함수를 본다** — 돌려 보고야 아는 일을 없앤다."""
    assert check_step(request_, deterministic=deterministic) == code


def test_a_deterministic_session_refuses_natural_language() -> None:
    """결정 수행은 **몰래 자율로 넘어가지 않는다** (ADR-0010)."""
    _, client = make()
    session_id, secret = opened(client)
    found = client.post(
        f"/v1/sessions/{session_id}/steps",
        json={"instruction": "수량 칸에 3을 넣어라", "action": "fill", "value": "3"},
        headers=head(secret),
    )
    assert found.status_code == 422 and found.json()["code"] == "instruction_not_allowed"


def test_a_higher_schema_is_refused() -> None:
    _, client = make()
    found = client.post("/v1/sessions", json=session_body(schema=2), headers={TOKEN_HEADER: TOKEN})
    assert found.status_code == 422 and found.json()["code"] == "schema_unsupported"


def test_without_a_backend_nothing_is_pretended() -> None:
    """**없는 것을 되는 척하지 않는다** — 화면을 만질 수단이 없으면 503."""
    worker = Worker(token=TOKEN, admin_token=ADMIN, backend=None)
    client = TestClient(create_app(worker))
    found = client.post("/v1/sessions", json=session_body(), headers={TOKEN_HEADER: TOKEN})
    assert found.status_code == 503 and found.json()["code"] == "browser_unavailable"


# ─────────────────────────── 예약 (Bot UI만) ───────────────────────────


def test_a_reservation_keeps_others_out() -> None:
    """한 Bot의 UI 태스크 사이 빈틈을 다른 쪽이 가져가지 못한다 (C10 §전송)."""
    _, client = make()
    client.post("/v1/admin/reserve", json={"run_id": RUN}, headers={ADMIN_HEADER: ADMIN})

    other = client.post(
        "/v1/sessions",
        json=session_body(caller={"type": "studio", "run_id": "test_other"}, business_key="다른키"),
        headers={TOKEN_HEADER: TOKEN},
    )
    assert other.status_code == 409 and other.json()["code"] == "reserved"
    assert other.json()["detail"]["run_id"] == RUN

    mine = client.post("/v1/sessions", json=session_body(), headers={TOKEN_HEADER: TOKEN})
    assert mine.status_code == 201


def test_unreserving_closes_the_open_session() -> None:
    """실행이 끝났다 — 남은 세션을 들고 있지 않는다."""
    worker, client = make()
    client.post("/v1/admin/reserve", json={"run_id": RUN}, headers={ADMIN_HEADER: ADMIN})
    opened(client)
    client.delete("/v1/admin/reserve", headers={ADMIN_HEADER: ADMIN})
    assert worker.session is None and worker.reserved_for is None


def test_bot_ui_can_force_close_a_stuck_session() -> None:
    """실행기가 죽었을 때 정리하는 길 (C10 §4)."""
    worker, client = make()
    session_id, _ = opened(client)
    found = client.delete(f"/v1/admin/sessions/{session_id}", headers={ADMIN_HEADER: ADMIN})
    assert found.json()["closed"] is True and worker.session is None


def test_the_status_says_who_holds_it() -> None:
    """BUI-09가 읽는다."""
    _, client = make()
    opened(client)
    found = client.get("/v1/status", headers={TOKEN_HEADER: TOKEN}).json()
    assert found["session"] == "bot" and found["holder"]["run_id"] == RUN
    assert found["pid"] > 0


# ─────────────────────────── 기동 (C10 기동 절차) ───────────────────────────


def test_the_worker_really_comes_up_on_loopback(tmp_path: Path) -> None:
    """진짜로 띄워 `/v1/health`가 200이 될 때까지 기다린다 — Bot UI가 하는 그대로.

    **127.0.0.1에만** 떠야 한다. 다른 PC에서 닿으면 그 PC의 화면을 남이 조작할 수 있다.
    """
    import socket
    import subprocess
    import sys
    import time

    import httpx

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    child = subprocess.Popen(  # noqa: S603 — 인자 리스트, shell 없음
        [
            sys.executable,
            "-c",
            "from pathlib import Path;"
            "from chaeksas.ext.ui_automation.worker import serve;"
            f"serve(port={port}, token_dir=Path({str(tmp_path)!r}))",
        ],
    )
    try:
        until = time.monotonic() + 30
        found = None
        while time.monotonic() < until:
            try:
                found = httpx.get(f"http://127.0.0.1:{port}/v1/health", timeout=1.0)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        assert found is not None and found.status_code == 200, "30초 안에 뜨지 않았다"
        assert found.json()["status"] == "ok"

        # 토큰 파일이 먼저 쓰였다 (C10 기동 절차 1).
        assert read_token(tmp_path, TOKEN_FILE) and read_token(tmp_path, ADMIN_TOKEN_FILE)

        # 백엔드가 없으니 세션은 **열리지 않는다** — 「없는데 된 척」하지 않는다.
        answer = httpx.post(
            f"http://127.0.0.1:{port}/v1/sessions",
            json=session_body(),
            headers={TOKEN_HEADER: read_token(tmp_path, TOKEN_FILE)},
            timeout=5.0,
        )
        assert answer.status_code == 503 and answer.json()["code"] == "browser_unavailable"
    finally:
        child.terminate()
        child.wait(timeout=10)

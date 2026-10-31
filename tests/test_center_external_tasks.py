"""C15 외부 작업 — 부르는 쪽이 올리고, 일꾼이 가져가 끝낸다 (ADR-0102).

| 보는 것 | 왜 |
| --- | --- |
| 일꾼은 **요청 코드 승인**으로 들고, 토큰은 **봉해서** 받는다 | 사람이 토큰을 옮기지 않는다 (ADR-0092) |
| 토픽은 **승인할 때** 정해진다 — 요청한 것 안에서만 줄인다 | 일꾼이 제 손으로 남의 토픽을 열지 못한다 |
| 같은 멱등 칸은 **같은 일감**이다 | 되살린 실행이 다시 올린다 (원칙 9) |
| **그 BPM 프로세스가 그 토픽을 요구할 때만** 올린다 | 「불러도 되나」가 배포 한 자리다 |
| 자율 수행은 **Studio의 시험 실행만** | 운영에서 LLM이 몰래 끼지 않는다 |
| 잠금이 지나면 **다시 나간다**, 먼저 끝낸 쪽이 이긴다 | 최소 한 번 실행 |
| 기한이 지나면 `no_consumer`·`timeout`으로 **실패한다** | 조용히 쌓이지 않는다 |
| `ack`가 오면 **값이 지워진다**, 못 받은 것은 7일에 | 원칙 6 예외를 좁게 쓴다 |
| 롱폴링은 새 일감이 오면 **그 자리에서** 깨어난다 | 호출마다 수십 초가 붙지 않는다 |
"""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from center_admin import approve as approve_package
from center_admin import deploy
from fastapi.testclient import TestClient

from chaeksas.center import keys
from chaeksas.center.api import external_tasks as api
from chaeksas.center.app import create_app
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.contracts.external_task import FetchRequest
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip

ADMIN = {"Authorization": "Bearer t-admin"}
AT = "2026-10-28T09:00:00+09:00"
VERSION = "1.0.0"
BOT = "fin.order"
TOPIC = "nowview-sc01"
OPERATION = "submit_order"
RUN = "run_20261028_090000_aaaaaa"
BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">
  <bpmn:process id="Proc_x" isExecutable="true"><bpmn:startEvent id="S" /></bpmn:process>
</bpmn:definitions>
"""
MANIFEST = {
    "schema": 1,
    "app_id": TOPIC,
    "name": "NowView SC01",
    "version": "2.0.0",
    "category": "business",
    "console_url": "http://nowview.internal/console",
    "operations": [
        {
            "name": OPERATION,
            "modes": ["deterministic", "autonomous"],
            "timeout_s": 600,
            "output_schema": {"type": "object", "required": ["receipt"]},
        },
        {"name": "register_page", "modes": ["deterministic"], "required_scopes": ["registry_write"]},
    ],
}


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg")
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_key(center: TestClient, *, name: str, kind: str) -> str:
    made = center.post("/api/v1/center-keys", json={"name": name, "type": kind}, headers=ADMIN)
    assert made.status_code == 201, made.text
    return str(made.json()["key"])


def pc(center: TestClient, *, machine: str = "7" * 64) -> tuple[str, str]:
    """등록된 PC 실행기 — `(bot_ui_id, 키)`."""
    key = new_key(center, name="현장 1", kind="bot_ui")
    made = center.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": machine,
            "name": "현장 1",
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers=bearer(key),
    )
    assert made.status_code < 400, made.text
    return str(made.json()["bot_ui_id"]), key


def package_zip(*, bot: str, apps: list[str]) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": bot,
        "version": VERSION,
        "name": bot,
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_x",
        "requires": {"service_apps": [{"app_id": one, "operations": [OPERATION]} for one in apps]},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", BPMN)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def deployed(center: TestClient, bot_ui_id: str, *, bot: str = BOT, apps: list[str] | None = None) -> None:
    made = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(bot=bot, apps=apps or [TOPIC]), "application/zip")},
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    approve_package(center, bot, VERSION)
    answer = deploy(
        center, target={"type": "bot_ui", "id": bot_ui_id}, bpm_process_id=bot, version=VERSION, expect=None
    )
    assert answer.status_code in (200, 201), answer.text


def consumer(
    center: TestClient,
    *,
    seed: str = "c",
    topics: list[str] | None = None,
    manifest: dict[str, Any] | None = MANIFEST,
) -> str:
    """일꾼 하나를 들인다 — 일꾼 폴더가 하는 일 그대로 (ADR-0122). 돌려주는 것은 일꾼 토큰이다."""
    from consumers import enroll  # noqa: PLC0415

    tokens = enroll(
        center,
        topics=topics or [TOPIC],
        manifests=[manifest] if manifest is not None else [],
        name=f"일꾼 {seed}",
        machine=f"worker-{seed}",
    )
    return str(tokens.token())


def task_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": 1,
        "topic": TOPIC,
        "operation": OPERATION,
        "mode": "deterministic",
        "idempotency": {"run_id": RUN, "node_id": "Task_submit", "node_instance": 1, "attempt": 1},
        "caller": {"type": "bot_ui", "host": "현장 1", "bpm_process_id": BOT, "version": VERSION},
        "input": {"order_id": "PO-101"},
        **over,
    }
    return body


def post(center: TestClient, key: str, **over: Any) -> httpx.Response:
    made: httpx.Response = center.post("/api/v1/external-tasks", json=task_body(**over), headers=bearer(key))
    return made


def fetch(center: TestClient, token: str, **over: Any) -> dict[str, Any]:
    made = center.post(
        "/api/v1/consumers/fetch", json={"topics": [TOPIC], "wait_s": 0, **over}, headers=bearer(token)
    )
    assert made.status_code == 200, made.text
    return dict(made.json())


@pytest.fixture
def field(center: TestClient) -> str:
    """그 토픽을 요구하는 BPM 프로세스가 배포된 PC의 키."""
    bot_ui_id, key = pc(center)
    deployed(center, bot_ui_id)
    return key


def later(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def consumer_row(store: Store, token: str) -> Any:
    record = keys.find(store, token)
    assert record is not None
    return api.consumer_of(store, Caller(kind="key", actor="일꾼", key=record))


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_post_fetch_complete_result_ack(center: TestClient, store: Store, field: str) -> None:
    token = consumer(center)
    assert fetch(center, token)["tasks"] == []

    made = post(center, field)
    assert made.status_code == 201, made.text
    task_id = made.json()["task_id"]
    assert post(center, field).json() == {"task_id": task_id, "state": "pending"}  # 같은 칸 = 같은 일감

    got = fetch(center, token)["tasks"]
    assert [one["task_id"] for one in got] == [task_id]
    assert got[0]["input"] == {"order_id": "PO-101"} and got[0]["delivery"] == 1
    assert got[0]["origin"] == "run" and got[0]["idempotency"]["call_seq"] == 1
    assert fetch(center, token)["tasks"] == []  # 잠겨 있다

    done = center.post(
        f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "R-1"}}, headers=bearer(token)
    )
    assert done.status_code == 200, done.text

    seen = center.get(f"/api/v1/external-tasks/{task_id}", headers=bearer(field)).json()
    assert seen["state"] == "completed" and seen["output"] == {"receipt": "R-1"}
    assert seen["mode_used"] == "deterministic" and seen["deliveries"] == 1

    assert center.post(f"/api/v1/external-tasks/{task_id}/ack", headers=bearer(field)).status_code == 200
    row = store.row("SELECT input_json, output_json, acked_at, state FROM external_tasks WHERE task_id = ?", (task_id,))
    assert row is not None and row["input_json"] is None and row["output_json"] is None
    assert row["acked_at"] and row["state"] == "completed"  # 누가·언제·성패는 남는다


def test_posting_again_after_ack_queues_it_again(center: TestClient, field: str) -> None:
    """받아 간 뒤 같은 칸으로 다시 올리면 **다시 줄에 선다** — 값을 지운 옛 일감을 돌려주면 빈 결과다.

    반복 안의 UI 태스크가 차례마다 같은 칸으로 계획을 올린다(엔진은 반복 중에 `node_instance`를
    올리지 않는다, ADR-0082). 일꾼은 멱등 칸으로 저장해 둔 결과를 다시 준다.
    """
    token = consumer(center)
    task_id = post(center, field).json()["task_id"]
    fetch(center, token)
    finish = f"/api/v1/consumers/tasks/{task_id}/complete"
    center.post(finish, json={"output": {"receipt": "R-1"}}, headers=bearer(token))
    assert center.post(f"/api/v1/external-tasks/{task_id}/ack", headers=bearer(field)).status_code == 200

    again = post(center, field)
    assert again.status_code == 201 and again.json() == {"task_id": task_id, "state": "pending"}
    assert [one["task_id"] for one in fetch(center, token)["tasks"]] == [task_id]
    center.post(finish, json={"output": {"receipt": "R-1"}}, headers=bearer(token))
    seen = center.get(f"/api/v1/external-tasks/{task_id}", headers=bearer(field)).json()
    assert seen["state"] == "completed" and seen["output"] == {"receipt": "R-1"}


def test_someone_elses_task_is_not_found(center: TestClient, field: str) -> None:
    task_id = post(center, field).json()["task_id"]
    _, other = pc(center, machine="8" * 64)
    assert center.get(f"/api/v1/external-tasks/{task_id}", headers=bearer(other)).status_code == 404


def test_same_slot_with_another_body_is_a_conflict(center: TestClient, field: str) -> None:
    assert post(center, field).status_code == 201
    again = post(center, field, input={"order_id": "PO-999"})
    assert again.status_code == 409 and again.json()["code"] == "idempotency_conflict"


# ─────────────────────────── 불러도 되나 ───────────────────────────


def test_a_topic_the_bot_does_not_require_is_refused(center: TestClient, field: str) -> None:
    made = post(center, field, topic="nowview-sc02")
    assert made.status_code == 403 and made.json()["code"] == "topic_not_required"


def test_a_bot_not_deployed_here_is_refused(center: TestClient) -> None:
    _, key = pc(center)
    made = post(center, key)
    assert made.status_code == 403 and made.json()["code"] == "topic_not_required"


def test_autonomous_only_from_studio_test_runs(center: TestClient, field: str) -> None:
    made = post(center, field, mode="autonomous")
    assert made.status_code == 403 and made.json()["code"] == "mode_not_allowed"

    studio = new_key(center, name="설계자", kind="studio")
    refused = post(center, studio, mode="autonomous")
    assert refused.status_code == 403 and refused.json()["code"] == "run_not_owned"
    test_run = {"run_id": "test_0a1b2c", "node_id": "Task_submit", "node_instance": 1, "attempt": 1}
    ok = post(center, studio, mode="autonomous", idempotency=test_run, origin="test")
    assert ok.status_code == 201, ok.text


def test_a_run_owned_by_another_key_is_refused(center: TestClient, store: Store, field: str) -> None:
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO runs (run_id, owner_key_id, first_seen_at, last_seen_at) VALUES (?, 'ck_other00', ?, ?)",
            (RUN, AT, AT),
        )
    made = post(center, field)
    assert made.status_code == 403 and made.json()["code"] == "run_not_owned"


def test_the_consumers_manifest_checks_operation_mode_and_scope(center: TestClient, field: str) -> None:
    consumer(center)
    missing = post(center, field, operation="nope")
    assert missing.status_code == 422 and missing.json()["code"] == "operation_not_found"
    scoped = post(center, field, operation="register_page")
    assert scoped.status_code == 403 and scoped.json()["code"] == "scope_missing"


def test_an_integration_key_cannot_post(center: TestClient) -> None:
    key = new_key(center, name="연동", kind="integration")
    assert post(center, key).status_code == 403


# ─────────────────────────── 일꾼 (일꾼 폴더로 들인다, ADR-0122) ───────────────────────────


def test_topics_are_fixed_by_the_worker_file(center: TestClient) -> None:
    token = consumer(center, topics=["nowview-sc02"])
    refused = center.post(
        "/api/v1/consumers/fetch", json={"topics": [TOPIC], "wait_s": 0}, headers=bearer(token)
    )
    assert refused.status_code == 403 and refused.json()["code"] == "topic_not_granted"


def test_a_console_lists_consumers_and_topics(center: TestClient, field: str) -> None:
    consumer(center)
    post(center, field)
    listed = center.get("/api/v1/consumers", headers=ADMIN).json()
    assert [(one["topics"], one["apps"]) for one in listed] == [([TOPIC], [f"{TOPIC}@2.0.0"])]
    topic = center.get("/api/v1/external-topics", headers=ADMIN).json()
    assert topic[0]["topic"] == TOPIC and topic[0]["consumers"] == 1 and topic[0]["waiting"] == 1
    assert center.get("/api/v1/consumers", headers=bearer(field)).status_code == 403


def test_another_consumer_cannot_finish_a_task_it_never_locked(center: TestClient, field: str) -> None:
    first = consumer(center, seed="a")
    second = consumer(center, seed="b")
    task_id = post(center, field).json()["task_id"]
    fetch(center, first)
    stolen = center.post(
        f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "x"}}, headers=bearer(second)
    )
    assert stolen.status_code == 403 and stolen.json()["code"] == "not_locked_by_you"


# ─────────────────────────── 최소 한 번·기한 ───────────────────────────


def test_an_expired_lock_goes_out_again_and_the_first_finish_wins(
    center: TestClient, store: Store, field: str
) -> None:
    first = consumer(center, seed="a")
    second = consumer(center, seed="b")
    task_id = post(center, field).json()["task_id"]
    fetch(center, first, lock_s=1)

    again = api.take(store, consumer_row(store, second), FetchRequest(topics=[TOPIC]), now=later(5))
    assert [one.task_id for one in again] == [task_id] and again[0].delivery == 2

    late = center.post(
        f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "A"}}, headers=bearer(first)
    )
    assert late.status_code == 200, late.text  # 잠금이 지났어도 아직 안 끝났으면 받는다
    twice = center.post(
        f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "B"}}, headers=bearer(second)
    )
    assert twice.status_code == 409 and twice.json()["code"] == "already_completed"


def test_nobody_takes_it_so_it_fails_with_no_consumer(center: TestClient, store: Store, field: str) -> None:
    task_id = post(center, field, timeout_s=30).json()["task_id"]
    api.sweep(store, now=later(31))
    seen = center.get(f"/api/v1/external-tasks/{task_id}", headers=bearer(field)).json()
    assert seen["state"] == "expired" and seen["error"]["code"] == "no_consumer"


def test_taken_but_not_finished_fails_with_timeout(center: TestClient, store: Store, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field, timeout_s=30).json()["task_id"]
    fetch(center, token)
    api.sweep(store, now=later(31))
    seen = center.get(f"/api/v1/external-tasks/{task_id}", headers=bearer(field)).json()
    assert seen["state"] == "expired" and seen["error"] == {
        "code": "timeout",
        "message": seen["error"]["message"],
        "retryable": True,
        "outcome_unknown": False,
    }


def test_a_failure_is_only_retryable_for_known_codes(center: TestClient, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field).json()["task_id"]
    fetch(center, token)
    center.post(
        f"/api/v1/consumers/tasks/{task_id}/fail",
        json={"code": "input_invalid", "message": "주문 번호 없음", "retryable": True},
        headers=bearer(token),
    )
    seen = center.get(f"/api/v1/external-tasks/{task_id}", headers=bearer(field)).json()
    assert seen["state"] == "failed" and seen["error"]["retryable"] is False


def slot(node_id: str) -> dict[str, Any]:
    return {"run_id": RUN, "node_id": node_id, "node_instance": 1, "attempt": 1}


def test_outcome_unknown_reaches_the_caller_but_not_with_retryable(center: TestClient, field: str) -> None:
    """결과 모름은 그대로 간다 — 다시 불러도 안전하다고 하면 지운다 (C15, ADR-0107)."""
    token = consumer(center)
    lost = post(center, field, idempotency=slot("Task_Lost")).json()["task_id"]
    fetch(center, token)
    center.post(
        f"/api/v1/consumers/tasks/{lost}/fail",
        json={"code": "unreachable", "message": "답이 없다", "outcome_unknown": True},
        headers=bearer(token),
    )
    seen = center.get(f"/api/v1/external-tasks/{lost}", headers=bearer(field)).json()
    assert seen["error"]["outcome_unknown"] is True and seen["error"]["retryable"] is False

    both = post(center, field, idempotency=slot("Task_Both")).json()["task_id"]
    fetch(center, token)
    center.post(
        f"/api/v1/consumers/tasks/{both}/fail",
        json={"code": "dependency_down", "message": "죽었다", "retryable": True, "outcome_unknown": True},
        headers=bearer(token),
    )
    seen = center.get(f"/api/v1/external-tasks/{both}", headers=bearer(field)).json()
    assert seen["error"]["retryable"] is True and seen["error"].get("outcome_unknown", False) is False


def test_a_missing_required_output_is_the_consumers_bug(center: TestClient, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field).json()["task_id"]
    fetch(center, token)
    made = center.post(f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {}}, headers=bearer(token))
    assert made.status_code == 422 and made.json()["code"] == "output_invalid"


def test_a_cancelled_task_tells_the_consumer_to_stop(center: TestClient, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field).json()["task_id"]
    fetch(center, token)
    assert center.post(f"/api/v1/external-tasks/{task_id}/cancel", headers=bearer(field)).json()["state"] == "cancelled"
    made = center.post(
        f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "x"}}, headers=bearer(token)
    )
    assert made.status_code == 409 and made.json()["code"] == "cancelled"


def test_unclaimed_values_are_purged_after_seven_days(center: TestClient, store: Store, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field).json()["task_id"]
    fetch(center, token)
    center.post(f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "R"}}, headers=bearer(token))
    api.sweep(store, now=later(8 * 86400))
    row = store.row("SELECT output_json, state FROM external_tasks WHERE task_id = ?", (task_id,))
    assert row is not None and row["output_json"] is None and row["state"] == "completed"


def test_a_result_nobody_waits_for_keeps_no_values(center: TestClient, store: Store, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field, want_result=False).json()["task_id"]
    fetch(center, token)
    center.post(f"/api/v1/consumers/tasks/{task_id}/complete", json={"output": {"receipt": "R"}}, headers=bearer(token))
    row = store.row("SELECT output_json, acked_at FROM external_tasks WHERE task_id = ?", (task_id,))
    assert row is not None and row["output_json"] is None and row["acked_at"]


# ─────────────────────────── 롱폴링 ───────────────────────────


def test_a_waiting_fetch_wakes_when_a_task_arrives(center: TestClient, field: str) -> None:
    token = consumer(center)
    app = center.app

    async def scenario() -> tuple[dict[str, Any], float]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://center") as client:
            started = asyncio.get_running_loop().time()
            waiting = asyncio.create_task(
                client.post("/api/v1/consumers/fetch", json={"topics": [TOPIC], "wait_s": 10}, headers=bearer(token))
            )
            await asyncio.sleep(0.2)
            made = await client.post("/api/v1/external-tasks", json=task_body(), headers=bearer(field))
            assert made.status_code == 201, made.text
            got = await waiting
            return got.json(), asyncio.get_running_loop().time() - started

    body, took = asyncio.run(scenario())
    assert len(body["tasks"]) == 1
    assert took < 3  # 종이 깨웠다 — 10초를 다 기다리지 않았다


def test_too_many_waiters_is_refused() -> None:
    waiters = api.Waiters(limit=1)
    waiters.enter()
    with pytest.raises(ApiError) as caught:
        waiters.enter()
    assert caught.value.status == 503 and caught.value.code == "too_many_waiters"
    waiters.leave()
    waiters.enter()


# ─────────────────────────── 콘솔이 보는 일감 (CON-01 「외부 작업」) ───────────────────────────


def test_the_console_sees_where_a_runs_tasks_stand(center: TestClient, store: Store, field: str) -> None:
    """그 실행의 일감이 **어디서 멈췄는지** — 기다림·쥔 일꾼·다시 나감 — 가 보이고 값은 없다 (C15)."""
    first = consumer(center, seed="a")
    second = consumer(center, seed="b")
    waiting = post(center, field, idempotency={**task_body()["idempotency"], "node_id": "Task_wait"}).json()
    task_id = post(center, field).json()["task_id"]
    other = post(center, field, idempotency={**task_body()["idempotency"], "run_id": "run_20261030_000000_other0"})
    assert other.status_code in (200, 201), other.text
    fetch(center, first, lock_s=1, max_tasks=1)  # 먼저 올린 `Task_wait`을 쥔다
    api.take(store, consumer_row(store, second), FetchRequest(topics=[TOPIC]), now=later(5))

    listed = center.get(f"/api/v1/external-tasks?run_id={RUN}", headers=ADMIN)
    assert listed.status_code == 200, listed.text
    rows = {one["task_id"]: one for one in listed.json()}
    assert set(rows) == {waiting["task_id"], task_id}, "다른 실행의 일감은 보이지 않는다"
    taken = rows[waiting["task_id"]]
    assert taken["node_id"] == "Task_wait" and taken["state"] == "locked"
    assert taken["deliveries"] == 2 and taken["consumers"] == ["일꾼 b"]  # 잠금이 지나 다시 나갔다
    assert all("input" not in one and "output" not in one for one in rows.values()), "업무 값은 없다"


def test_a_failed_task_shows_its_code_but_not_its_words(center: TestClient, field: str) -> None:
    token = consumer(center)
    task_id = post(center, field).json()["task_id"]
    fetch(center, token)
    center.post(
        f"/api/v1/consumers/tasks/{task_id}/fail",
        json={"code": "upstream_error", "message": "거래처 PO-101이 없다", "outcome_unknown": True},
        headers=bearer(token),
    )
    (row,) = center.get(f"/api/v1/external-tasks?run_id={RUN}", headers=ADMIN).json()
    assert row["state"] == "failed" and row["error_code"] == "upstream_error" and row["outcome_unknown"]
    assert "PO-101" not in str(row)


def test_only_the_console_lists_a_runs_tasks(center: TestClient, field: str) -> None:
    assert center.get(f"/api/v1/external-tasks?run_id={RUN}", headers=bearer(field)).status_code == 403
    assert center.get("/api/v1/external-tasks", headers=ADMIN).status_code == 422

"""Center의 서버 실행기 API — 실제로 띄워 부르는 시험 (C12, M7 조각 2).

계약 모델·검사의 시험은 `test_contracts_server_runner.py`에 있다. 이 파일은 그 계약을 지키는
**앱**을 TestClient로 두드린다.

걸려 있는 줄:

1. 「서버 실행기용」 Center API 키로 등록 → 하트비트 (C12, CON-11)
2. **키 묶기는 C4와 같다** — 양방향으로 하나씩이고, 규칙은 `center.host_keys` 한 자리다
3. 운영 API (CON-12 목록·일시 중지·유실 처리)
4. **빈자리만큼만 작업을 내려 준다** (C12 §Center가 작업을 나누는 규칙)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center import create_app
from chaeksas.center.api import jobs as jobs_api
from chaeksas.center.api import server_runner as runner_api
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.server_runner import DEFAULT_PER_BOT_CONCURRENCY

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}
RUNNER = "/api/v1/server-runner"


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def client(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg")
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def issue(client: TestClient, *, name: str = "서버 1", key_type: str = "server_runner") -> str:
    response = client.post(
        "/api/v1/center-keys", json={"name": name, "type": key_type}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


def auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def machine(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def must(store: Store, sql: str, args: tuple[Any, ...]) -> Any:
    """있어야 하는 한 줄 — 없으면 시험이 거기서 끝난다 (`None`을 들고 가지 않는다)."""
    found = store.row(sql, args)
    assert found is not None, sql
    return found


def register_body(*, machine_seed: str = "srv1", name: str = "서버 1", **extra: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "machine_id": machine(machine_seed),
        "name": name,
        "os": "ubuntu-24.04",
        "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
        **extra,
    }


def heartbeat_body(**extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": 1,
        "status": "running",
        "capacity": {"max": 10, "running": 0},
    }
    body.update(extra)
    return body


def register(client: TestClient, key: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"{RUNNER}/register", json=register_body(**extra), headers=auth(key))
    assert response.status_code == 200, response.text
    return dict(response.json())


def beat(client: TestClient, key: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"{RUNNER}/heartbeat", json=heartbeat_body(**extra), headers=auth(key))
    assert response.status_code == 200, response.text
    return dict(response.json())


# ─────────────────────────── 등록 ───────────────────────────


def test_register_then_heartbeat(client: TestClient) -> None:
    key = issue(client)
    body = register(client, key)
    assert body["server_runner_id"].startswith("srv_")
    # 주기는 **C12의 10초**다 (PC의 30초가 아니다).
    assert body["heartbeat_interval_s"] == 10

    answer = beat(client, key)
    assert answer["paused"] is False
    assert answer["jobs"] == [] and answer["deployments"] == []
    # 메시지 길은 아직 없다 (다음 조각) — 칸은 있고 비어 있다.
    assert answer["messages"] == []


def test_register_is_idempotent(client: TestClient) -> None:
    key = issue(client)
    first = register(client, key)
    again = register(client, key, name="서버 1 (이름만 바꿈)")
    assert first["server_runner_id"] == again["server_runner_id"]


def test_only_a_server_runner_key_is_accepted(client: TestClient) -> None:
    """다른 종류의 키는 403 `wrong_key_type` (C12)."""
    for other in ("bot_ui", "studio", "integration"):
        key = issue(client, name=f"{other} 키", key_type=other)
        response = client.post(f"{RUNNER}/register", json=register_body(), headers=auth(key))
        assert response.status_code == 403, other
        assert response.json()["code"] == "wrong_key_type"


def test_heartbeat_before_register_is_refused(client: TestClient) -> None:
    key = issue(client)
    response = client.post(f"{RUNNER}/heartbeat", json=heartbeat_body(), headers=auth(key))
    assert response.status_code == 409 and response.json()["code"] == "not_registered"


def test_max_concurrency_comes_from_the_runner(client: TestClient) -> None:
    key = issue(client)
    register(client, key, max_concurrency=3)
    listed = client.get("/api/v1/server-runners", headers=READ).json()
    # 하트비트 전에는 **등록할 때 말한 상한**을 보인다 (보고된 상태가 없다).
    assert listed[0]["capacity"] == {"max": 3, "running": 0}
    assert listed[0]["status"] == "offline" and listed[0]["online"] is False


# ─────────────────────────── 키 묶기 (C4와 같다) ───────────────────────────


def test_a_key_is_bound_to_one_machine(client: TestClient) -> None:
    key = issue(client)
    register(client, key, machine_seed="srv1")
    response = client.post(
        f"{RUNNER}/register", json=register_body(machine_seed="srv2"), headers=auth(key)
    )
    assert response.status_code == 409 and response.json()["code"] == "machine_mismatch"
    # 메시지는 **「서버」**라고 말한다 — 「PC」라고 하면 운영자가 PC를 찾아 헤맨다.
    assert "서버" in response.json()["message"]


def test_a_machine_is_registered_by_one_key(client: TestClient) -> None:
    first, second = issue(client, name="키1"), issue(client, name="키2")
    register(client, first, machine_seed="srv1")
    response = client.post(
        f"{RUNNER}/register", json=register_body(machine_seed="srv1"), headers=auth(second)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "machine_already_registered"


def test_a_new_key_takes_over_an_unbound_seat(client: TestClient) -> None:
    """묶음을 풀면 **새 키가 그 자리를 이어받는다** (C4와 같다 — 배포·기록이 산다)."""
    first = issue(client, name="키1")
    runner_id = register(client, first, machine_seed="srv1")["server_runner_id"]
    key_id = client.get("/api/v1/center-keys", headers=READ).json()[0]["key_id"]
    assert client.post(f"/api/v1/center-keys/{key_id}/unbind", headers=ADMIN).status_code == 200

    second = issue(client, name="키2")
    again = register(client, second, machine_seed="srv1")
    assert again["server_runner_id"] == runner_id


def test_a_refused_register_does_not_bind_the_key(client: TestClient) -> None:
    """막힌 등록이 키를 묶으면 운영자가 그 묶음까지 풀어야 한다 (C4와 같다)."""
    first, second = issue(client, name="키1"), issue(client, name="키2")
    register(client, first, machine_seed="srv1")
    client.post(f"{RUNNER}/register", json=register_body(machine_seed="srv1"), headers=auth(second))

    listed = {k["name"]: k for k in client.get("/api/v1/center-keys", headers=READ).json()}
    assert listed["키2"].get("bound_to") is None


# ─────────────────────────── 하트비트가 담는 것 ───────────────────────────


def test_heartbeat_reports_capacity_and_waiting(client: TestClient) -> None:
    key = issue(client)
    register(client, key)
    at = now_iso()
    beat(
        client,
        key,
        capacity={"max": 10, "running": 1},
        running=[
            {
                "run_id": "run_20261013_090000_aa11bb",
                "bpm_process_id": "finance.invoice-issue",
                "version": "1.0.0",
                "started_at": at,
            }
        ],
        waiting=[
            {
                "run_id": "run_20261013_080000_cc22dd",
                "bpm_process_id": "finance.invoice-issue",
                "version": "1.0.0",
                "waiting_for": "approval",
                "request_id": "apr_x",
                "since": at,
            }
        ],
    )
    listed = client.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["capacity"] == {"max": 10, "running": 1}
    assert [r["run_id"] for r in listed["running"]] == ["run_20261013_090000_aa11bb"]
    assert [w["run_id"] for w in listed["waiting"]] == ["run_20261013_080000_cc22dd"]
    assert listed["online"] is True and listed["status"] == "running"


def test_a_self_contradicting_heartbeat_is_refused(client: TestClient) -> None:
    """자리 셈이 어긋난 하트비트는 422 — 받아 두면 **빈자리를 틀리게 센다** (C12)."""
    key = issue(client)
    register(client, key)
    response = client.post(
        f"{RUNNER}/heartbeat",
        json=heartbeat_body(capacity={"max": 10, "running": 3}),  # running[]은 비었다
        headers=auth(key),
    )
    assert response.status_code == 422 and response.json()["code"] == "input_invalid"
    assert "running[] 길이" in response.json()["detail"]["problems"][0]


def test_extensions_are_kept_until_they_change(client: TestClient, store: Store) -> None:
    """**바뀌었을 때만 올라온다** (C12) — 빈 목록은 「안 바뀜」이라 덮어쓰지 않는다."""
    key = issue(client)
    register(client, key, extensions=[{"id": "ui-automation", "version": "0.1.0"}])
    beat(client, key)  # extensions 없이
    runner_id = client.get("/api/v1/server-runners", headers=READ).json()[0]["server_runner_id"]
    assert [e.id for e in runner_api.extensions_of(store, runner_id)] == ["ui-automation"]


def test_readiness_is_reported_as_is(client: TestClient, store: Store) -> None:
    key = issue(client)
    register(client, key)
    beat(
        client,
        key,
        readiness=[
            {
                "bpm_process_id": "finance.invoice-issue",
                "version": "1.0.0",
                "ready": False,
                "missing_key_refs": ["erp"],
            }
        ],
    )
    runner_id = client.get("/api/v1/server-runners", headers=READ).json()[0]["server_runner_id"]
    found = runner_api.readiness_of(store, runner_id)
    assert [r.missing_key_refs for r in found] == [["erp"]]


def test_key_expiry_is_sent_every_cycle(client: TestClient) -> None:
    """**주기마다 싣는다** — 「생략 = 그대로」면 늘려 준 기간을 현장이 모른다 (C4·C12)."""
    later = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    raw = client.post(
        "/api/v1/center-keys",
        json={"name": "서버 키", "type": "server_runner", "expires_at": later},
        headers=ADMIN,
    ).json()["key"]
    assert register(client, raw)["key_expires_at"] == later
    assert beat(client, raw)["key_expires_at"] == later


# ─────────────────────────── 운영 API (CON-12) ───────────────────────────


def test_the_listing_carries_the_key_prefix_and_expiry(client: TestClient) -> None:
    """CON-12 「Center API 키」는 **앞자리와 만료**를 함께 보인다 (C12).

    만료만 주면 운영자가 CON-11의 어느 줄인지 못 찾는다 — 키가 여럿이면 만료일이 겹친다.
    **원문·해시는 주지 않는다** (앞자리까지다).
    """
    later = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    raw = client.post(
        "/api/v1/center-keys",
        json={"name": "서버 키", "type": "server_runner", "expires_at": later},
        headers=ADMIN,
    ).json()["key"]
    register(client, raw)

    row = client.get("/api/v1/server-runners", headers=READ).json()[0]
    assert row["key_expires_at"] == later
    assert row["key_prefix"] and raw.startswith(row["key_prefix"])
    # 원문이 새어 나가지 않는다.
    assert raw not in json.dumps(row, ensure_ascii=False)


def test_pause_is_told_in_the_next_heartbeat(client: TestClient) -> None:
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    assert (
        client.post(f"/api/v1/server-runners/{runner_id}/pause", headers=ADMIN).status_code == 200
    )
    assert beat(client, key)["paused"] is True
    client.post(f"/api/v1/server-runners/{runner_id}/resume", headers=ADMIN)
    assert beat(client, key)["paused"] is False


def test_pause_needs_the_admin_token(client: TestClient) -> None:
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    response = client.post(f"/api/v1/server-runners/{runner_id}/pause", headers=READ)
    assert response.status_code == 403 and response.json()["code"] == "admin_only"


def test_pausing_an_unknown_runner_is_404(client: TestClient) -> None:
    response = client.post("/api/v1/server-runners/srv_deadbeef/pause", headers=ADMIN)
    assert response.status_code == 404


def test_an_online_runner_cannot_be_marked_lost(client: TestClient) -> None:
    """온라인이면 409 `runner_online` — 도는 실행기의 실행을 닫으면 **현장이 옳은데** 부정한다."""
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    beat(client, key)
    response = client.post(f"/api/v1/server-runners/{runner_id}/mark-lost", headers=ADMIN)
    assert response.status_code == 409 and response.json()["code"] == "runner_online"


def test_mark_lost_closes_jobs_and_reclaims_approvals(client: TestClient, store: Store) -> None:
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]  # 하트비트를 보내지 않았다 = 오프라인

    _insert_job(store, job_id="job_a", target_id=runner_id, state=jobs_api.ACCEPTED)
    _insert_job(store, job_id="job_b", target_id=runner_id, state=jobs_api.PENDING)
    response = client.post(f"/api/v1/server-runners/{runner_id}/mark-lost", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["jobs_closed"] == 1

    closed = must(store, "SELECT * FROM jobs WHERE job_id = ?", ("job_a",))
    assert closed["state"] == jobs_api.REJECTED and closed["state_reason"] == "runner_lost"
    # **시작하지 않은 것은 놓아 준다** — 다른 실행기가 받으면 된다.
    waiting_job = must(store, "SELECT * FROM jobs WHERE job_id = ?", ("job_b",))
    assert waiting_job["state"] == jobs_api.PENDING and waiting_job["target_id"] == ""


def test_a_returning_runner_clears_the_lost_mark(client: TestClient, store: Store) -> None:
    """닫아 둔 실행기가 돌아오면 **오프라인·유실로 보이게 두지 않는다** (CON-12)."""
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    client.post(f"/api/v1/server-runners/{runner_id}/mark-lost", headers=ADMIN)
    beat(client, key)
    row = must(store, "SELECT lost_at FROM server_runners WHERE server_runner_id = ?", (runner_id,))
    assert row["lost_at"] is None


# ─────────────────────────── 작업 나누기 (C12 §3) ───────────────────────────


def _insert_job(
    store: Store,
    *,
    job_id: str,
    target_id: str,
    state: str = jobs_api.PENDING,
    bot: str = "finance.invoice-issue",
    at: str | None = None,
) -> None:
    """작업 한 줄을 바로 넣는다 — `POST /jobs`는 아직 서버 대상을 막는다 (ADR-0016의 스위치)."""
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id,"
            " inputs_json, requested_by, requested_at, state, owner, body_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                bot,
                "1.0.0",
                "server_runner",
                target_id,
                "{}",
                "운영자",
                at or now_iso(),
                state,
                "admin",
                "h",
            ),
        )


def test_unassigned_jobs_go_to_the_runner_with_room(client: TestClient, store: Store) -> None:
    """`id`를 비운 작업은 **Center가 고른다** (C5 `JobTarget`) — 고르면 그 실행기에 묶인다."""
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    _insert_job(store, job_id="job_a", target_id="")

    answer = beat(client, key, capacity={"max": 10, "running": 0})
    assert [j["job_id"] for j in answer["jobs"]] == ["job_a"]
    # **한 실행은 시작한 실행기에 끝까지 머문다** (ADR-0054).
    assert must(store, "SELECT target_id FROM jobs WHERE job_id = ?", ("job_a",))["target_id"] == runner_id


def test_only_as_many_as_there_are_free_slots(client: TestClient, store: Store) -> None:
    key = issue(client)
    register(client, key)
    for n in range(5):
        _insert_job(store, job_id=f"job_{n}", target_id="", bot=f"bot.{n}")

    answer = beat(client, key, capacity={"max": 2, "running": 0})
    assert len(answer["jobs"]) == 2, "빈자리만큼만 내려 준다 (C12)"


def test_a_paused_runner_gets_no_jobs(client: TestClient, store: Store) -> None:
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    _insert_job(store, job_id="job_a", target_id="")
    client.post(f"/api/v1/server-runners/{runner_id}/pause", headers=ADMIN)
    assert beat(client, key)["jobs"] == []


def test_the_per_bot_limit_is_skipped_not_blocking(client: TestClient, store: Store) -> None:
    """상한에 걸린 BPM 프로세스 하나가 **대기열 전체를 멈추지 않는다** (C12 §3)."""
    key = issue(client)
    register(client, key)
    for n in range(DEFAULT_PER_BOT_CONCURRENCY):
        _insert_job(store, job_id=f"busy_{n}", target_id="srv_other", state=jobs_api.ACCEPTED)
    _insert_job(store, job_id="job_busy", target_id="", at="2026-10-13T00:00:00+00:00")
    _insert_job(store, job_id="job_free", target_id="", bot="hr.onboarding", at="2026-10-13T00:00:01+00:00")

    answer = beat(client, key, capacity={"max": 10, "running": 0})
    assert [j["job_id"] for j in answer["jobs"]] == ["job_free"]
    # 건너뛴 까닭을 적어 둔다 — CON-12 「대기 이유」가 읽는다.
    skipped = must(store, "SELECT state_reason FROM jobs WHERE job_id = ?", ("job_busy",))
    assert skipped["state_reason"] == "per_bot_limit"


def test_a_waiting_run_does_not_look_lost(client: TestClient, store: Store) -> None:
    """**`waiting[]`에는 `job_id`가 없다** (C12) — `run_id`로 되짚지 않으면 멀쩡한 실행을 닫는다."""
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    _insert_job(store, job_id="job_a", target_id=runner_id, state=jobs_api.ACCEPTED)
    with store.tx() as cur:
        cur.execute("UPDATE jobs SET run_id = ? WHERE job_id = ?", ("run_20261013_090000_aa11bb", "job_a"))

    at = now_iso()
    waiting = [
        {
            "run_id": "run_20261013_090000_aa11bb",
            "bpm_process_id": "finance.invoice-issue",
            "version": "1.0.0",
            "waiting_for": "approval",
            "request_id": "apr_x",
            "since": at,
        }
    ]
    for _ in range(3):  # 맞추기 규칙은 두 번 연속 못 보면 닫는다
        beat(client, key, capacity={"max": 10, "running": 0}, waiting=waiting)
    row = must(store, "SELECT state, state_reason FROM jobs WHERE job_id = ?", ("job_a",))
    assert row["state"] == jobs_api.ACCEPTED and row["state_reason"] is None


def test_queued_count_shows_what_center_holds(client: TestClient, store: Store) -> None:
    key = issue(client)
    register(client, key)
    _insert_job(store, job_id="job_a", target_id="")
    _insert_job(store, job_id="job_b", target_id="")
    listed = client.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["queued"] == 2, "대기열은 Center가 가진다 (C12)"


def test_the_listing_needs_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/server-runners").status_code == 401


def test_a_center_api_key_cannot_read_the_listing(client: TestClient) -> None:
    """현황 목록은 **콘솔 토큰만**이다 (C5 권한표에서 키가 「—」인 자리).

    목록에는 다른 기계들의 이름·용량·도는 실행 id가 함께 있다 — 현장 키 하나로 남의 현황을
    읽을 수 있으면 「자기 일만」이 깨진다.
    """
    key = issue(client)
    register(client, key)
    response = client.get("/api/v1/server-runners", headers=auth(key))
    assert response.status_code == 403 and response.json()["code"] == "forbidden"


def test_a_dispatched_job_is_resent_until_acked(client: TestClient, store: Store) -> None:
    """**ack가 올 때까지 매번 다시 싣는다** (C4·C12) — 한 번 보내고 잊으면 작업이 사라진다."""
    key = issue(client)
    register(client, key)
    _insert_job(store, job_id="job_a", target_id="")

    for _ in range(3):
        answer = beat(client, key, capacity={"max": 10, "running": 0})
        assert [j["job_id"] for j in answer["jobs"]] == ["job_a"]

    answer = beat(
        client,
        key,
        capacity={"max": 10, "running": 1},
        running=[
            {
                "run_id": "run_20261013_090000_aa11bb",
                "bpm_process_id": "finance.invoice-issue",
                "version": "1.0.0",
                "started_at": now_iso(),
                "job_id": "job_a",
            }
        ],
        job_acks=[
            {"job_id": "job_a", "result": "started", "run_id": "run_20261013_090000_aa11bb"}
        ],
    )
    assert answer["jobs"] == [], "started를 들었으면 더 싣지 않는다"
    assert must(store, "SELECT state FROM jobs WHERE job_id = ?", ("job_a",))["state"] == jobs_api.ACCEPTED


def test_a_rejected_job_is_not_resent(client: TestClient, store: Store) -> None:
    """거절도 소식이다 — 받고 나면 다시 싣지 않는다 (C4 `JobAck`)."""
    key = issue(client)
    register(client, key)
    _insert_job(store, job_id="job_a", target_id="")
    beat(client, key)
    answer = beat(
        client, key, job_acks=[{"job_id": "job_a", "result": "rejected", "reason": "not_ready"}]
    )
    assert answer["jobs"] == []
    row = must(store, "SELECT state, state_reason FROM jobs WHERE job_id = ?", ("job_a",))
    assert row["state"] == jobs_api.REJECTED and row["state_reason"] == "not_ready"


def test_a_lost_runner_job_says_runner_lost(client: TestClient, store: Store) -> None:
    """맞추기 규칙의 사유는 **호스트마다 다르다** — 서버에 「bot_ui_lost」라고 적지 않는다."""
    key = issue(client)
    runner_id = register(client, key)["server_runner_id"]
    _insert_job(store, job_id="job_a", target_id=runner_id, state=jobs_api.ACCEPTED)

    for _ in range(3):  # 두 번 연속 보이지 않으면 닫는다
        beat(client, key, capacity={"max": 10, "running": 0})
    row = must(store, "SELECT state, state_reason FROM jobs WHERE job_id = ?", ("job_a",))
    assert row["state"] == jobs_api.REJECTED
    assert row["state_reason"] == jobs_api.LOST_RUNNER == "runner_lost"

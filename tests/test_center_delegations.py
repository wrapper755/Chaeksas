"""C12 §PC 위임 — 서버 BPM 프로세스가 **배포된 PC BPM 프로세스**을 Center 작업으로 맡긴다 (ADR-0062).

보는 것은 **Center가 결정하는 자리들**이다.

| 보는 것 | 왜 |
| --- | --- |
| 어느 PC인가를 **Center가 고른다** | 그림에 PC id를 적지 않는다 — 배포가 정하는 자리다 (ADR-0049) |
| **대기열이 짧은 PC**로 간다 | 한 PC에 몰리면 자리 하나가 병목이 된다 (ADR-0014) |
| 배포된 활성 PC가 없으면 **거부** | 기다리면 업무가 설정 잘못을 기다린다 |
| **같은 자리는 한 번만** 작업이 된다 | 되살린 실행이 다시 요청한다 (ADR-0054) |
| 남의 실행 이름으로 **맡길 수 없다** | `requested_by: server_bot:<run_id>`가 거짓이 되면 안 된다 (C3 소유) |
| 결과는 **ack가 올 때까지** 내려오고, ack가 오면 **값이 지워진다** | 원칙 6의 예외는 좁게 쓴다 |
| 위임하는 BPM 프로세스는 그 PC BPM 프로세스가 **승인되어 있어야** 배포된다 | C1 R8처럼 배포 시점에 본다 |
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from center_admin import approve as approve_package
from center_admin import deploy
from fastapi.testclient import TestClient

from chaeksas.center.api import delegations as api
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip

ADMIN = {"Authorization": "Bearer t-admin"}
AT = "2026-10-13T09:00:00+09:00"
VERSION = "1.0.0"
#: 맡길 PC BPM 프로세스와 맡기는 서버 BPM 프로세스.
PC_BOT = "fin.erp-input"
SERVER_BOT = "fin.invoice"
RUN = "run_20261015_090000_aaaaaa"
BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">
  <bpmn:process id="Proc_x" isExecutable="true"><bpmn:startEvent id="S" /></bpmn:process>
</bpmn:definitions>
"""


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg"
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def new_key(center: TestClient, *, name: str, kind: str) -> str:
    made = center.post("/api/v1/center-keys", json={"name": name, "type": kind}, headers=ADMIN)
    assert made.status_code == 201, made.text
    return str(made.json()["key"])


@pytest.fixture
def runner_key(center: TestClient) -> str:
    return new_key(center, name="서버 1", kind="server_runner")


@pytest.fixture
def runner(center: TestClient, runner_key: str) -> str:
    made = center.post(
        "/api/v1/server-runner/register",
        json={
            "schema": 1,
            "machine_id": "a1" * 32,
            "name": "서버 1",
            "os": "Linux",
            "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
            "max_concurrency": 3,
        },
        headers={"Authorization": f"Bearer {runner_key}"},
    )
    assert made.status_code in (200, 201), made.text
    return str(made.json()["server_runner_id"])


#: 등록한 PC의 키 (ack를 올릴 때 쓴다 — 신원은 키다, C4).
PC_KEYS: dict[str, str] = {}


def pc(center: TestClient, *, name: str, machine: str) -> str:
    """등록된 활성 PC 실행기 하나 — 돌려주는 것은 `bot_ui_id`다 (C4)."""
    key = new_key(center, name=name, kind="bot_ui")
    made = center.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": machine,
            "name": name,
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert made.status_code < 400, made.text
    bot_ui_id = str(made.json()["bot_ui_id"])
    PC_KEYS[bot_ui_id] = key
    return bot_ui_id


def package_zip(*, bot: str, where: str, delegations: list[str]) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": bot,
        "version": VERSION,
        "name": bot,
        "run_location": where,
        "entry": "process/main.bpmn",
        "process_id": "Proc_x",
        "requires": {"delegations": delegations},
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


def upload(center: TestClient, *, bot: str, where: str,
           delegations: list[str] | None = None, approve: bool = True) -> dict[str, Any]:
    made = center.post(
        "/api/v1/packages",
        files={
            "file": (
                "p.zip",
                package_zip(bot=bot, where=where, delegations=delegations or []),
                "application/zip",
            )
        },
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    info = dict(made.json())
    if approve:
        approve_package(center, info["id"], info["version"])
    return info


def deploy_to_pc(center: TestClient, info: dict[str, Any], bot_ui_id: str) -> Any:
    return deploy(
        center,
        target={"type": "bot_ui", "id": bot_ui_id},
        bpm_process_id=info["id"],
        version=info["version"],
        expect=None,
    )


def ask(center: TestClient, runner_key: str, **over: Any) -> Any:
    """위임을 맡긴다 (C12 `POST …/delegations`)."""
    body: dict[str, Any] = {
        "schema": 1,
        "run_id": RUN,
        "node_id": "Call_Erp",
        "bpm_process_id": PC_BOT,
        "version": VERSION,
        "inputs": {"전표번호": "EX-1"},
        **over,
    }
    return center.post(
        "/api/v1/server-runner/delegations",
        json=body,
        headers={"Authorization": f"Bearer {runner_key}"},
    )


def beat(center: TestClient, runner_key: str, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": 1,
        "status": "running",
        "capacity": {"max": 3, "running": 0},
        **over,
    }
    made = center.post(
        "/api/v1/server-runner/heartbeat",
        json=body,
        headers={"Authorization": f"Bearer {runner_key}"},
    )
    assert made.status_code == 200, made.text
    return dict(made.json())


@pytest.fixture
def ready(center: TestClient, runner: str) -> str:
    """PC BPM 프로세스가 승인·배포된 PC 하나. 돌려주는 것은 `bot_ui_id`다."""
    info = upload(center, bot=PC_BOT, where="pc")
    one = pc(center, name="현장 1", machine="7" * 64)
    answer = deploy_to_pc(center, info, one)
    assert answer.status_code in (200, 201), answer.text
    return one


# ─────────────────────────── 맡기기 ───────────────────────────


def test_center_picks_the_pc_and_makes_a_job(
    center: TestClient, runner_key: str, ready: str
) -> None:
    """**Center가 고르고 작업이 된다** — 그림에 PC id가 없다 (ADR-0062 §3)."""
    made = ask(center, runner_key)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["bot_ui_id"] == ready
    # **`POST /jobs`와 같은 함수로** 작업이 됐다 — 대상·요청자까지 보인다 (C5).
    job = center.get(f"/api/v1/jobs/{body['job_id']}", headers=ADMIN).json()
    assert job["target"] == {"type": "bot_ui", "id": ready}
    assert job["bpm_process_id"] == PC_BOT
    # **`requested_by`는 Center가 적는다** (C5 예약값) — 본문에서 받지 않는다.
    assert job["requested_by"] == f"server_bot:{RUN}"


def test_the_same_call_site_only_makes_one_job(
    center: TestClient, runner_key: str, ready: str
) -> None:
    """되살린 실행이 다시 맡긴다 (ADR-0054) — **같은 작업이 돌아온다** (200)."""
    first = ask(center, runner_key)
    again = ask(center, runner_key)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["job_id"] == again.json()["job_id"]
    listed = center.get("/api/v1/jobs", headers=ADMIN).json()
    assert len([one for one in listed if one["bpm_process_id"] == PC_BOT]) == 1


def test_another_call_site_in_the_same_run_is_another_job(
    center: TestClient, runner_key: str, ready: str
) -> None:
    """멱등 키는 **자리마다**다 (`run_id`·`node_id`·`node_instance`)."""
    first = ask(center, runner_key)
    other = ask(center, runner_key, node_id="Call_Erp2")
    again = ask(center, runner_key, node_instance=2)
    ids = {first.json()["job_id"], other.json()["job_id"], again.json()["job_id"]}
    assert len(ids) == 3


def test_the_shortest_queue_wins(
    center: TestClient, runner: str, runner_key: str
) -> None:
    """**대기열이 짧은 PC**로 간다 — 한 PC에 몰리면 자리 하나가 병목이다 (ADR-0014)."""
    info = upload(center, bot=PC_BOT, where="pc")
    busy = pc(center, name="현장 1", machine="7" * 64)
    free = pc(center, name="현장 2", machine="8" * 64)
    for one in (busy, free):
        assert deploy_to_pc(center, info, one).status_code in (200, 201)
    # 바쁜 쪽에 작업 하나를 쌓아 둔다.
    queued = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": PC_BOT, "target": {"type": "bot_ui", "id": busy}, "inputs": {}},
        headers=ADMIN,
    )
    assert queued.status_code in (200, 201), queued.text
    assert ask(center, runner_key).json()["bot_ui_id"] == free


def test_a_wanted_pc_is_honoured_and_checked(
    center: TestClient, runner: str, runner_key: str
) -> None:
    """`bot_ui`를 적으면 **그 PC로만** — 배포되지 않았으면 거부다 (담당자 PC 규칙)."""
    info = upload(center, bot=PC_BOT, where="pc")
    mine = pc(center, name="현장 1", machine="7" * 64)
    other = pc(center, name="현장 2", machine="8" * 64)
    assert deploy_to_pc(center, info, mine).status_code in (200, 201)

    assert ask(center, runner_key, bot_ui=mine).json()["bot_ui_id"] == mine
    refused = ask(center, runner_key, node_id="Call_Other", bot_ui=other)
    assert refused.status_code == 404 and refused.json()["code"] == "no_deployment"


def test_no_deployed_pc_is_refused_not_queued(
    center: TestClient, runner: str, runner_key: str
) -> None:
    """**기다리지 않는다** — 배포되지 않은 것을 기다리는 것은 설정 잘못이다 (ADR-0062 §3)."""
    refused = ask(center, runner_key)
    assert refused.status_code == 404 and refused.json()["code"] == "no_deployment"


def test_another_runners_run_cannot_be_delegated(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """남의 실행 이름으로 맡기면 403 — `server_bot:<run_id>`가 거짓이 되면 안 된다 (C3 소유)."""
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO runs (run_id, owner_key_id, first_seen_at, last_seen_at)"
            " VALUES (?, ?, ?, ?)",
            (RUN, "someone-else", now_iso(), now_iso()),
        )
    refused = ask(center, runner_key)
    assert refused.status_code == 403 and refused.json()["code"] == "run_owner_mismatch"


def test_only_a_server_runner_key_can_delegate(center: TestClient, ready: str) -> None:
    """위임은 **서버 실행기용 키만** 맡긴다 (C5 권한표)."""
    refused = ask(center, new_key(center, name="연동", kind="integration"))
    assert refused.status_code == 403 and refused.json()["code"] == "wrong_key_type"


# ─────────────────────────── 결과가 돌아오는 길 ───────────────────────────


def test_a_result_comes_down_until_it_is_acked(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """**ack가 올 때까지 다시 싣고**, ack가 오면 **값을 지운다** (C12 §PC 위임).

    PC 쪽이 올리는 길(C4 작업 ack에 출력)은 다음 조각이라, 여기서는 그 자리를 함수로 채운다.
    """
    job_id = ask(center, runner_key).json()["job_id"]
    assert api.finish(
        store,
        job_id=job_id,
        state="finished",
        outputs={"결과코드": "OK"},
        pc_run_id="run_20261015_100000_bbbbbb",
    )

    first = beat(center, runner_key)["delegations"]
    assert [one["job_id"] for one in first] == [job_id]
    assert first[0]["outputs"] == {"결과코드": "OK"}
    assert first[0]["run_id"] == RUN and first[0]["state"] == "finished"
    # 아직 ack하지 않았다 — **또 내려온다**.
    assert len(beat(center, runner_key)["delegations"]) == 1

    done = beat(center, runner_key, delegation_acks=[{"job_id": job_id, "accepted": True}])
    assert done["delegations"] == []
    # **값은 지워졌다** — 누가·언제·성패는 남는다 (원칙 6의 예외는 좁게 쓴다).
    row = store.row("SELECT * FROM delegations WHERE job_id = ?", (job_id,))
    assert row is not None and row["outputs_json"] is None and row["state"] == "finished"


def test_a_result_only_goes_to_the_runner_that_asked(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """**그 작업을 낸 실행기에게만** 내려간다 (남의 업무 값을 받지 않는다)."""
    job_id = ask(center, runner_key).json()["job_id"]
    api.finish(store, job_id=job_id, state="finished", outputs={"결과코드": "OK"})

    stranger = new_key(center, name="서버 2", kind="server_runner")
    made = center.post(
        "/api/v1/server-runner/register",
        json={
            "schema": 1,
            "machine_id": "b2" * 32,
            "name": "서버 2",
            "os": "Linux",
            "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert made.status_code in (200, 201), made.text
    assert beat(center, stranger)["delegations"] == []
    # 남의 ack로도 지워지지 않는다.
    beat(center, stranger, delegation_acks=[{"job_id": job_id, "accepted": True}])
    assert len(beat(center, runner_key)["delegations"]) == 1


def test_a_failed_delegation_comes_down_with_its_reason(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """실패·거절도 내려간다 — 실행기가 **오류 경계로** 넘긴다 (C14)."""
    job_id = ask(center, runner_key).json()["job_id"]
    api.finish(store, job_id=job_id, state="rejected", reason="not_ready")
    (one,) = beat(center, runner_key)["delegations"]
    assert (one["state"], one["reason"], one["outputs"]) == ("rejected", "not_ready", {})


def test_a_job_that_is_not_a_delegation_is_left_alone(center: TestClient, store: Store) -> None:
    """위임이 아닌 작업의 결과는 담지 않는다 (평범한 PC 작업이다)."""
    assert api.finish(store, job_id="job_whatever", state="finished") is False


def pc_beat(center: TestClient, bot_ui_id: str, **over: Any) -> dict[str, Any]:
    """PC가 하트비트를 올린다 (C4) — `job_acks[]`로 결과를 싣는 자리다."""
    made = center.post(
        "/api/v1/bot-ui/heartbeat",
        json={
            "schema": 1,
            "status": "idle",
            "current_run": None,
            "queue": {"max": 5, "items": []},
            **over,
        },
        headers={"Authorization": f"Bearer {PC_KEYS[bot_ui_id]}"},
    )
    assert made.status_code == 200, made.text
    return dict(made.json())


def test_the_pc_sends_the_outputs_back_in_its_job_ack(
    center: TestClient, runner_key: str, ready: str
) -> None:
    """**PC가 작업 ack에 값을 실어 올리고** 서버 실행기가 하트비트로 받는다 (C4 + C12).

    길이 한 줄로 이어지는가를 본다 — PC 하트비트 → Center → 서버 실행기 하트비트.
    """
    job_id = ask(center, runner_key).json()["job_id"]
    pc_beat(center, ready, job_acks=[{"job_id": job_id, "result": "started", "run_id": "run_20261015_100000_bbbbbb"}])
    pc_beat(
        center,
        ready,
        job_acks=[
            {
                "job_id": job_id,
                "result": "finished",
                "run_id": "run_20261015_100000_bbbbbb",
                "outputs": {"결과코드": "OK"},
            }
        ],
    )

    (one,) = beat(center, runner_key)["delegations"]
    assert one["job_id"] == job_id and one["state"] == "finished"
    assert one["outputs"] == {"결과코드": "OK"}
    # PC 쪽 실행도 함께 온다 — CON-01에서 오갈 수 있다 (C3 `parent_run_id`의 반대 방향).
    assert one["pc_run_id"] == "run_20261015_100000_bbbbbb"
    # 작업의 성패는 **`run_status`**에만 적힌다 (C5) — 작업 상태는 `accepted`로 남는다.
    job = center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()
    assert (job["state"], job["run_status"]) == ("accepted", "finished")


def test_outputs_on_a_plain_job_go_nowhere(
    center: TestClient, store: Store, runner: str
) -> None:
    """**위임이 아닌 작업의 값은 어디에도 남지 않는다** (원칙 6의 예외는 좁게 쓴다)."""
    info = upload(center, bot=PC_BOT, where="pc")
    one = pc(center, name="현장 1", machine="7" * 64)
    assert deploy_to_pc(center, info, one).status_code in (200, 201)
    made = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": PC_BOT, "target": {"type": "bot_ui", "id": one}, "inputs": {}},
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    job_id = made.json()["job_id"]

    pc_beat(center, one, job_acks=[{"job_id": job_id, "result": "finished", "outputs": {"값": 1}}])
    assert store.row("SELECT * FROM delegations WHERE job_id = ?", (job_id,)) is None


def test_a_started_ack_does_not_carry_a_result_yet(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """`started`에 값을 실어 보내도 **담지 않는다** — 담으면 서버 실행이 빈 값으로 이어 간다."""
    job_id = ask(center, runner_key).json()["job_id"]
    pc_beat(center, ready, job_acks=[{"job_id": job_id, "result": "started", "outputs": {"결과코드": "X"}}])
    assert beat(center, runner_key)["delegations"] == []
    row = store.row("SELECT * FROM delegations WHERE job_id = ?", (job_id,))
    assert row is not None and row["state"] is None


# ─────────────────────────── 기다리는 줄·배포 관문 ───────────────────────────


def test_a_delegation_wait_needs_its_job_id(center: TestClient, runner_key: str, runner: str) -> None:
    """`waiting_for: delegation`의 짝 칸은 **작업 id**다 (C12 — 비우면 422)."""
    row: dict[str, Any] = {
        "run_id": RUN,
        "bpm_process_id": SERVER_BOT,
        "version": VERSION,
        "waiting_for": "delegation",
        "since": now_iso(),
    }
    refused = center.post(
        "/api/v1/server-runner/heartbeat",
        json={"schema": 1, "status": "running", "capacity": {"max": 3, "running": 0},
              "waiting": [row]},
        headers={"Authorization": f"Bearer {runner_key}"},
    )
    assert refused.status_code == 422 and refused.json()["code"] == "input_invalid"
    assert beat(center, runner_key, waiting=[{**row, "job_id": "job_1"}])["delegations"] == []


def test_deploying_a_delegating_bot_needs_the_pc_bot_approved(
    center: TestClient, runner: str
) -> None:
    """위임하는 BPM 프로세스는 그 PC BPM 프로세스가 **승인되어 있어야** 배포된다 (C1 R8처럼 배포 때 본다)."""
    server = upload(center, bot=SERVER_BOT, where="server",
                    delegations=[f"{PC_BOT}@{VERSION}"])
    wanted = {
        "target": {"type": "server_runner", "id": runner},
        "bpm_process_id": server["id"],
        "version": server["version"],
    }
    refused = deploy(center, **wanted, expect=422)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "delegation_not_approved"

    # 올리고 승인하면 통과한다. **PC에 배포됐는가는 묻지 않는다.**
    upload(center, bot=PC_BOT, where="pc")
    deploy(center, **wanted)


# ─────────────────────────── 거두기와 청소 (ADR-0062 §4·§5) ───────────────────────────


def revoke(center: TestClient, runner_key: str, job_id: str) -> Any:
    """맡긴 위임을 거둔다 — **실행기 키로** (C5 취소 경로가 아니다)."""
    return center.post(
        f"/api/v1/server-runner/delegations/{job_id}/cancel",
        headers={"Authorization": f"Bearer {runner_key}"},
    )


def test_cancelling_the_server_run_cancels_the_pc_job(
    center: TestClient, runner_key: str, ready: str
) -> None:
    """서버 실행이 취소되면 **그 위임 작업도 취소한다** (ADR-0062 §5).

    돌아도 결과를 받을 쪽이 없다 — PC가 **받을 쪽 없는 일**을 하게 두지 않는다.
    """
    job_id = ask(center, runner_key).json()["job_id"]
    answer = revoke(center, runner_key, job_id)
    assert answer.status_code == 200, answer.text

    job = center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()
    assert (job["state"], job["cancel_result"]) == ("cancelled", "cancelled")
    # **내려가지 않는다** — 그 PC의 대기열에서도 사라진다.
    assert job_id not in [one["job_id"] for one in center.get("/api/v1/jobs", headers=ADMIN).json()
                          if one["state"] in ("pending", "dispatched")]


def test_a_started_pc_run_is_not_stopped(center: TestClient, runner_key: str, ready: str) -> None:
    """**이미 시작된 PC 실행은 끝까지 간다** (C5 — 「시작된 작업의 취소는 거절」).

    그 결과는 받는 쪽이 없어 버려지고, 누가·언제·성패는 위임 표에 남는다.
    """
    job_id = ask(center, runner_key).json()["job_id"]
    pc_beat(center, ready, job_acks=[{"job_id": job_id, "result": "started", "run_id": "run_20261015_100000_bbbbbb"}])

    answer = revoke(center, runner_key, job_id)
    assert answer.status_code == 409 and answer.json()["code"] == "already_started"


def test_only_the_runner_that_delegated_can_cancel(
    center: TestClient, runner_key: str, ready: str
) -> None:
    """**남의 위임은 거둘 수 없다** — 있다는 것조차 알리지 않는다 (404, 작업 지시와 같은 결).

    권한표를 넓히지 않고 **제 관문**을 여기서 지나는 까닭이다 (실행기 키·등록·그 위임의 임자).
    """
    job_id = ask(center, runner_key).json()["job_id"]
    other = new_key(center, name="서버 2", kind="server_runner")
    made = center.post(
        "/api/v1/server-runner/register",
        json={
            "schema": 1,
            "machine_id": "b2" * 32,
            "name": "서버 2",
            "os": "Linux",
            "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
            "max_concurrency": 1,
        },
        headers={"Authorization": f"Bearer {other}"},
    )
    assert made.status_code in (200, 201), made.text
    assert revoke(center, other, job_id).status_code == 404

    # 다른 종류의 키는 애초에 못 거둔다 (C5 권한표).
    read_only = center.post(
        f"/api/v1/server-runner/delegations/{job_id}/cancel",
        headers={"Authorization": "Bearer t-read"},
    )
    assert read_only.status_code == 403


def test_values_nobody_received_are_purged_after_the_idempotency_window(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """**못 받은 값은 작업 멱등 기간에 지운다** (ADR-0062 §4 — 원칙 6의 예외는 좁게 쓴다).

    ack가 오면 `apply_acks`가 바로 지운다. 여기는 **그 ack가 영영 오지 않는** 경우다.
    누가·언제·성패는 남는다 — 「무엇이 오갔나」만 업무 값이다.
    """
    from datetime import UTC, datetime, timedelta

    from chaeksas.center.api import delegations as api_mod

    job_id = ask(center, runner_key).json()["job_id"]
    pc_beat(center, ready, job_acks=[{"job_id": job_id, "result": "started", "run_id": "run_20261015_100000_bbbbbb"}])
    pc_beat(
        center,
        ready,
        job_acks=[{"job_id": job_id, "result": "finished", "run_id": "run_20261015_100000_bbbbbb",
                   "outputs": {"결과코드": "OK"}}],
    )
    assert beat(center, runner_key)["delegations"][0]["outputs"] == {"결과코드": "OK"}

    # 아직 기간 안이면 그대로 둔다.
    assert api_mod.purge_values(store) == 0

    later = (datetime.now(UTC) + timedelta(days=8)).isoformat()
    assert api_mod.purge_values(store, now=later) == 1
    (row,) = store.rows("SELECT * FROM delegations WHERE job_id = ?", (job_id,))
    assert row["outputs_json"] is None
    # **`acked`는 그대로 0이다** — 받지 못한 것을 받았다고 적지 않는다.
    assert row["acked"] == 0 and row["state"] == "finished"
    # 다시 내려가지만 값은 비어 있다 (성패는 알아야 오류 경계가 받는다).
    (one,) = beat(center, runner_key)["delegations"]
    assert one["outputs"] == {} and one["state"] == "finished"


def test_the_purge_leaves_what_the_runner_has_not_seen_yet(
    center: TestClient, store: Store, runner_key: str, ready: str
) -> None:
    """**기간 안의 것은 건드리지 않는다** — 받아 갈 실행기가 아직 있다."""
    job_id = ask(center, runner_key).json()["job_id"]
    pc_beat(center, ready, job_acks=[{"job_id": job_id, "result": "started", "run_id": "run_20261015_100000_bbbbbb"}])
    pc_beat(
        center,
        ready,
        job_acks=[{"job_id": job_id, "result": "finished", "run_id": "run_20261015_100000_bbbbbb",
                   "outputs": {"결과코드": "OK"}}],
    )
    from chaeksas.center.api import delegations as api_mod

    assert api_mod.purge_values(store) == 0
    assert beat(center, runner_key)["delegations"][0]["outputs"] == {"결과코드": "OK"}


# ─────────── 도는 실행을 멈추는 길 (ADR-0063 — 이 거리의 가지를 켜 주는 자리) ───────────


def test_a_started_pc_job_still_refuses_the_cancel(
    center: TestClient, runner: str, ready: str
) -> None:
    """**PC 실행은 Center에서 멈추지 않는다** (ADR-0063) — 화면을 만지는 중일 수 있다.

    도중에 끊으면 화면이 반쯤 바뀐 채 남는다(기록에 `cancelled`가 남아도 되돌려지지 않는다).
    현장 사람이 BUI-04 「중지」로 멈춘다 — 그 사람은 화면을 보고 있다.
    """
    # 위임이 아니라 **평범한 PC 작업**이다 — 가르는 것은 대상 종류이지 위임인가가 아니다.
    made = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": PC_BOT, "target": {"type": "bot_ui", "id": ready}, "inputs": {}},
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    pc_job = str(made.json()["job_id"])
    pc_beat(center, ready, job_acks=[{"job_id": pc_job, "result": "started", "run_id": "run_20261015_100000_cccccc"}])

    refused = center.delete(f"/api/v1/jobs/{pc_job}", headers=ADMIN)
    assert refused.status_code == 409 and refused.json()["code"] == "already_started"
    assert center.get(f"/api/v1/jobs/{pc_job}", headers=ADMIN).json()["state"] == "accepted"


def test_a_started_server_job_takes_the_cancel_and_waits_for_the_runner(
    center: TestClient, runner: str, runner_key: str
) -> None:
    """**서버 실행은 멈출 수 있다** (ADR-0063) — 202로 받아 두고 하트비트로 내려 준다.

    **Center가 혼자 `cancelled`로 적지 않는다** (`dispatched`와 같은 결) — 정말 멈췄는지는
    현장만 안다. 실행기가 돌아오지 않으면 CON-12 「유실 처리」가 닫는다.
    """
    info = upload(center, bot=SERVER_BOT, where="server")
    deploy(
        center,
        target={"type": "server_runner", "id": runner},
        bpm_process_id=info["id"],
        version=info["version"],
    )
    made = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": SERVER_BOT, "target": {"type": "server_runner"}, "inputs": {}},
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    job_id = str(made.json()["job_id"])
    # 실행기가 받아 가고(`dispatched`) 시작했다고 ack한다 (`accepted`).
    assert beat(center, runner_key)["jobs"][0]["job_id"] == job_id
    beat(center, runner_key, job_acks=[{"job_id": job_id, "result": "started", "run_id": RUN}])

    dropped = center.delete(f"/api/v1/jobs/{job_id}", headers=ADMIN)
    assert dropped.status_code == 202, dropped.text
    assert center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()["state"] == "accepted"

    # 다음 하트비트에 **취소 지시가 내려간다**.
    assert beat(center, runner_key)["cancel_jobs"] == [job_id]
    # 실행기가 닫았다고 ack하면 그때 `cancelled`다.
    beat(center, runner_key, job_acks=[{"job_id": job_id, "result": "cancelled", "run_id": RUN}])
    closed = center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()
    assert (closed["state"], closed["cancel_result"]) == ("cancelled", "cancelled")


# ─────────────── 서버 BPM 프로세스에 맡기기·반복 (일괄 기동, ADR-0082) ───────────────

CHILD_BOT = "ops.intake-item"


def deploy_to_server(center: TestClient, info: dict[str, Any], runner_id: str) -> Any:
    return deploy(
        center,
        target={"type": "server_runner", "id": runner_id},
        bpm_process_id=info["id"],
        version=info["version"],
        expect=None,
    )


@pytest.fixture
def server_child(center: TestClient, runner: str) -> str:
    """서버 BPM 프로세스 하나가 승인·배포되어 있다. 돌려주는 것은 그 실행기 id다."""
    info = upload(center, bot=CHILD_BOT, where="server")
    answer = deploy_to_server(center, info, runner)
    assert answer.status_code in (200, 201), answer.text
    return runner


def test_a_server_bot_is_delegated_to_a_server_runner(
    center: TestClient, runner_key: str, server_child: str
) -> None:
    """**대상 패키지의 실행 위치가 가른다** — 그림은 그대로 `bpm_process_id`만 적는다 (ADR-0082)."""
    made = ask(center, runner_key, bpm_process_id=CHILD_BOT, version=None)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["target_type"] == "server_runner" and body.get("bot_ui_id") is None
    job = center.get(f"/api/v1/jobs/{body['job_id']}", headers=ADMIN).json()
    assert job["target"]["type"] == "server_runner"
    assert job["requested_by"] == f"server_bot:{RUN}"
    # 실행기가 하트비트로 받아 간다 — 같은 실행기여도 된다(부모는 기다리며 자리를 놓는다).
    assert [one["job_id"] for one in beat(center, runner_key)["jobs"]] == [body["job_id"]]


def test_each_loop_turn_is_its_own_job_and_comes_back_the_same(
    center: TestClient, runner_key: str, server_child: str
) -> None:
    """반복 차례마다 작업 하나 — 되살린 실행이 다시 맡겨도 **같은 작업**이다 (ADR-0082)."""
    first = [ask(center, runner_key, bpm_process_id=CHILD_BOT, loop_index=i) for i in range(3)]
    assert [one.status_code for one in first] == [201, 201, 201]
    assert len({one.json()["job_id"] for one in first}) == 3
    again = ask(center, runner_key, bpm_process_id=CHILD_BOT, loop_index=1)
    assert again.status_code == 200 and again.json()["job_id"] == first[1].json()["job_id"]
    assert again.json()["target_type"] == "server_runner"


def test_no_loop_index_keeps_the_old_key(center: TestClient, runner_key: str, ready: str) -> None:
    """반복이 아니면 **옛 키 그대로** — 이미 맡겨 둔 위임이 같은 작업을 받는다."""
    from chaeksas.center.api.delegations import key_prefix  # noqa: PLC0415

    assert key_prefix(RUN, "Call_Erp", 1) == f"dlg_{RUN}_Call_Erp_1"
    assert key_prefix(RUN, "Call_Erp", 1, 0) == f"dlg_{RUN}_Call_Erp_1_0"


def test_a_pc_for_a_server_bot_is_refused(center: TestClient, runner_key: str, server_child: str) -> None:
    made = ask(center, runner_key, bpm_process_id=CHILD_BOT, bot_ui="bui_x")
    assert made.status_code == 422 and made.json()["code"] == "bot_ui_for_server"


def test_a_server_result_goes_back_to_the_runner_that_asked(
    center: TestClient, runner_key: str, server_child: str
) -> None:
    """서버 실행기가 작업 ack에 실은 `outputs`가 맡긴 실행기에게 내려간다 (C12)."""
    job_id = ask(center, runner_key, bpm_process_id=CHILD_BOT).json()["job_id"]
    beat(center, runner_key)  # 받아 간다
    done = beat(center, runner_key, job_acks=[
        {"job_id": job_id, "result": "started", "run_id": "run_20261020_000000_cccccc"},
    ])
    done = beat(center, runner_key, job_acks=[
        {"job_id": job_id, "result": "finished", "run_id": "run_20261020_000000_cccccc",
         "outputs": {"처리결과": "등록"}},
    ])
    [result] = done["delegations"]
    assert (result["job_id"], result["state"], result["outputs"]) == (job_id, "finished", {"처리결과": "등록"})

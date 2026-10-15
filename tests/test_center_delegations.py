"""C12 §PC 위임 — 서버 Bot이 **배포된 PC Bot**을 Center 작업으로 맡긴다 (ADR-0062).

보는 것은 **Center가 결정하는 자리들**이다.

| 보는 것 | 왜 |
| --- | --- |
| 어느 PC인가를 **Center가 고른다** | 그림에 PC id를 적지 않는다 — 배포가 정하는 자리다 (ADR-0049) |
| **대기열이 짧은 PC**로 간다 | 한 PC에 몰리면 자리 하나가 병목이 된다 (ADR-0014) |
| 배포된 활성 PC가 없으면 **거부** | 기다리면 업무가 설정 잘못을 기다린다 |
| **같은 자리는 한 번만** 작업이 된다 | 되살린 실행이 다시 요청한다 (ADR-0054) |
| 남의 실행 이름으로 **맡길 수 없다** | `requested_by: server_bot:<run_id>`가 거짓이 되면 안 된다 (C3 소유) |
| 결과는 **ack가 올 때까지** 내려오고, ack가 오면 **값이 지워진다** | 원칙 6의 예외는 좁게 쓴다 |
| 위임하는 Bot은 그 PC Bot이 **승인되어 있어야** 배포된다 | C1 R8처럼 배포 시점에 본다 |
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
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.center.api import delegations as api
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.signing import sign

ADMIN = {"Authorization": "Bearer t-admin"}
PASS = "열쇠말"
AT = "2026-10-13T09:00:00+09:00"
VERSION = "1.0.0"
#: 맡길 PC Bot과 맡기는 서버 Bot.
PC_BOT = "fin.erp-input"
SERVER_BOT = "fin.invoice"
RUN = "run_20261015_090000_aaaaaa"
BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">
  <bpmn:process id="Proc_x" isExecutable="true"><bpmn:startEvent id="S" /></bpmn:process>
</bpmn:definitions>
"""


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


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


@pytest.fixture
def private(store: Store) -> Any:
    signer = keystore.create(label="첫 키")
    bootstrap_key(store, public_key=signer.public_bytes(), label="첫 키")
    return keystore.load(signer, passphrase=PASS)


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
    """등록된 활성 Bot UI 하나 — 돌려주는 것은 `bot_ui_id`다 (C4)."""
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


def upload(center: TestClient, private: Any, *, bot: str, where: str,
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
        signed = center.put(
            f"/api/v1/packages/{info['id']}/{info['version']}/signature",
            json=sign(
                {
                    "kind": "package",
                    "id": info["id"],
                    "version": info["version"],
                    "content_hash": info["content_hash"],
                },
                private,
                signed_at=AT,
            ).to_json_dict(),
            headers=ADMIN,
        )
        assert signed.status_code == 200, signed.text
    return info


def deploy_to_pc(center: TestClient, private: Any, info: dict[str, Any], bot_ui_id: str,
                 *, deployment_id: str) -> Any:
    return center.post(
        "/api/v1/deployments",
        json=sign(
            {
                "kind": "deployment",
                "deployment_id": deployment_id,
                "target": {"type": "bot_ui", "id": bot_ui_id},
                "bpm_process_id": info["id"],
                "version": info["version"],
                "content_hash": info["content_hash"],
            },
            private,
            signed_at=now_iso(),
        ).to_json_dict(),
        headers=ADMIN,
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
def ready(center: TestClient, private: Any, runner: str) -> str:
    """PC Bot이 승인·배포된 PC 하나. 돌려주는 것은 `bot_ui_id`다."""
    info = upload(center, private, bot=PC_BOT, where="pc")
    one = pc(center, name="현장 1", machine="7" * 64)
    answer = deploy_to_pc(center, private, info, one, deployment_id="dep_pc_1")
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
    center: TestClient, private: Any, runner: str, runner_key: str
) -> None:
    """**대기열이 짧은 PC**로 간다 — 한 PC에 몰리면 자리 하나가 병목이다 (ADR-0014)."""
    info = upload(center, private, bot=PC_BOT, where="pc")
    busy = pc(center, name="현장 1", machine="7" * 64)
    free = pc(center, name="현장 2", machine="8" * 64)
    for i, one in enumerate((busy, free)):
        assert deploy_to_pc(
            center, private, info, one, deployment_id=f"dep_pc_{i}"
        ).status_code in (200, 201)
    # 바쁜 쪽에 작업 하나를 쌓아 둔다.
    queued = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": PC_BOT, "target": {"type": "bot_ui", "id": busy}, "inputs": {}},
        headers=ADMIN,
    )
    assert queued.status_code in (200, 201), queued.text
    assert ask(center, runner_key).json()["bot_ui_id"] == free


def test_a_wanted_pc_is_honoured_and_checked(
    center: TestClient, private: Any, runner: str, runner_key: str
) -> None:
    """`bot_ui`를 적으면 **그 PC로만** — 배포되지 않았으면 거부다 (담당자 PC 규칙)."""
    info = upload(center, private, bot=PC_BOT, where="pc")
    mine = pc(center, name="현장 1", machine="7" * 64)
    other = pc(center, name="현장 2", machine="8" * 64)
    assert deploy_to_pc(center, private, info, mine, deployment_id="dep_pc_1").status_code in (200, 201)

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
            "worker": {"state": "off"},
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
    center: TestClient, store: Store, private: Any, runner: str
) -> None:
    """**위임이 아닌 작업의 값은 어디에도 남지 않는다** (원칙 6의 예외는 좁게 쓴다)."""
    info = upload(center, private, bot=PC_BOT, where="pc")
    one = pc(center, name="현장 1", machine="7" * 64)
    assert deploy_to_pc(center, private, info, one, deployment_id="dep_pc_1").status_code in (200, 201)
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
    center: TestClient, private: Any, runner: str
) -> None:
    """위임하는 Bot은 그 PC Bot이 **승인되어 있어야** 배포된다 (C1 R8처럼 배포 때 본다)."""
    server = upload(center, private, bot=SERVER_BOT, where="server",
                    delegations=[f"{PC_BOT}@{VERSION}"])
    envelope = {
        "kind": "deployment",
        "deployment_id": "dep_srv_1",
        "target": {"type": "server_runner", "id": runner},
        "bpm_process_id": server["id"],
        "version": server["version"],
        "content_hash": server["content_hash"],
    }
    refused = center.post(
        "/api/v1/deployments",
        json=sign(envelope, private, signed_at=now_iso()).to_json_dict(),
        headers=ADMIN,
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "delegation_not_approved"

    # 올리고 승인하면 통과한다. **PC에 배포됐는가는 묻지 않는다.**
    upload(center, private, bot=PC_BOT, where="pc")
    ok = center.post(
        "/api/v1/deployments",
        json=sign(envelope, private, signed_at=now_iso()).to_json_dict(),
        headers=ADMIN,
    )
    assert ok.status_code in (200, 201), ok.text

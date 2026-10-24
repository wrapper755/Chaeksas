"""메시지 — 「이 일이 일어났다」가 기다리는 실행이나 새 작업으로 간다 (C12 §메시지).

여기서는 **Center만** 본다 (실행기 쪽은 `tests/test_server_runner_messages.py`). 하트비트는
손으로 올려 `waiting[]`을 만든다 — 실행기가 보고한 것을 Center가 그대로 쓰는 자리라서
진짜 실행이 없어도 고르는 규칙을 다 볼 수 있다.

| 보는 것 | 왜 |
| --- | --- |
| 기다리는 실행으로 간다 | C12 §메시지 (`delivered_to: "run"`) |
| **상관 키가 없으면 찾지 않는다** | 아무 주문이나 깨우면 안 된다 |
| 메시지 시작은 **작업으로** 간다 | 배포 검사·상한이 작업 쪽 한 자리에 남는다 |
| 둘 이상이면 **고르지 않는다** | 422 `receiver_ambiguous` |
| **ack가 올 때까지 다시 싣는다** | ADR-0007 (작업과 같다) |
| 거절은 **다시 싣지 않는다** | 영원히 도는 메시지를 만들지 않는다 |
| 「유실 처리」가 메시지도 닫는다 | 받을 실행이 닫혔다 (C6 `host_lost`와 같은 자리) |
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import center_admin
import pytest
from fastapi.testclient import TestClient

from chaeksas.center.api import messages as messages_api
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}
AT = "2026-10-13T09:00:00+09:00"

#: 업무 예제 BX-11 — 실행 위치 `server`, 메시지 `bid_quote`를 상관 키 `입찰번호`로 기다린다.
BID = Path("docs/08-business-examples/bpmn/bx11_bid_collection.bpmn")
BID_BOT = "scm.bid-collection"
#: 업무 예제 BX-13 — **메시지 시작**(`return_request`)으로 도는 서버 Bot이다.
RETURN = Path("docs/08-business-examples/bpmn/bx13_return_processing.bpmn")
RETURN_BOT = "scm.return-processing"
VERSION = "1.0.0"

RUN = "run_20261013_090000_aa11bb"


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


def _new_key(center: TestClient, *, name: str, kind: str) -> str:
    response = center.post(
        "/api/v1/center-keys", json={"name": name, "type": kind}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


@pytest.fixture
def runner_key(center: TestClient) -> str:
    return _new_key(center, name="서버 1", kind="server_runner")


@pytest.fixture
def integration_key(center: TestClient) -> str:
    """연동용 키 — 외부 시스템이 메시지를 넣는 자리다 (C5 권한표)."""
    return _new_key(center, name="쇼핑몰", kind="integration")


@pytest.fixture
def runner(center: TestClient, runner_key: str) -> str:
    """등록된 서버 실행기 하나. 돌려주는 것은 `server_runner_id`다."""
    response = center.post(
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
    assert response.status_code in (200, 201), response.text
    return str(response.json()["server_runner_id"])


# ─────────────────────────── 거리 ───────────────────────────


def package_zip(*, bot: str, path: Path, process_id: str, triggers: list[dict[str, Any]]) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": bot,
        "version": VERSION,
        "name": bot,
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": process_id,
        "triggers": triggers,
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    files = {"process/main.bpmn": path.read_text(encoding="utf-8")}

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def deploy(
    center: TestClient,
    *,
    runner_id: str,
    bot: str,
    path: Path,
    process_id: str,
    triggers: list[dict[str, Any]],
) -> None:
    """올리고 승인하고 그 실행기에 배포한다 (C2 — 봉투는 Center가 짓는다, ADR-0090)."""

    uploaded = center.post(
        "/api/v1/packages",
        files={
            "file": (
                "p.zip",
                package_zip(bot=bot, path=path, process_id=process_id, triggers=triggers),
                "application/zip",
            )
        },
        headers=ADMIN,
    )
    assert uploaded.status_code in (200, 201), uploaded.text
    info = dict(uploaded.json())
    center_admin.approve(center, info["id"], info["version"])
    center_admin.deploy(
        center,
        target={"type": "server_runner", "id": runner_id},
        bpm_process_id=info["id"],
        version=info["version"],
    )


def heartbeat(
    center: TestClient,
    runner_key: str,
    *,
    waiting: list[dict[str, Any]] | None = None,
    message_acks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """하트비트 하나를 손으로 올린다 — `waiting[]`을 만드는 자리다."""
    body: dict[str, Any] = {
        "schema": 1,
        "status": "running",
        "capacity": {"max": 3, "running": 0},
        "running": [],
        "waiting": waiting or [],
    }
    if message_acks is not None:
        body["message_acks"] = message_acks
    response = center.post(
        "/api/v1/server-runner/heartbeat",
        json=body,
        headers={"Authorization": f"Bearer {runner_key}"},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def go_offline(store: Store, runner_id: str) -> None:
    """마지막 하트비트를 3분 뒤로 돌린다 — **유실 처리는 오프라인인 실행기만** 된다 (C12)."""
    from datetime import datetime, timedelta

    then = (datetime.fromisoformat(now_iso()) - timedelta(seconds=600)).isoformat()
    with store.tx() as cur:
        cur.execute(
            "UPDATE server_runners SET last_seen_at = ? WHERE server_runner_id = ?",
            (then, runner_id),
        )


def waiting_row(*, run_id: str = RUN, correlation: Any = "BID-2026-001", since: str = AT) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "bpm_process_id": BID_BOT,
        "version": VERSION,
        "waiting_for": "message",
        "message_name": "bid_quote",
        "correlation": correlation,
        "since": since,
    }


def put_message(
    center: TestClient, key: str | None = None, **body: Any
) -> Any:
    headers = ADMIN if key is None else {"Authorization": f"Bearer {key}"}
    payload = {"schema": 1, **body}
    return center.post("/api/v1/messages", json=payload, headers=headers)


# ─────────────────────────── 기다리는 실행으로 ───────────────────────────


def test_a_message_goes_to_the_waiting_run(
    center: TestClient, runner_key: str, runner: str, integration_key: str
) -> None:
    """상관 키가 맞는 기다리는 실행이 있으면 **그 실행으로** 간다 (C12 §메시지)."""
    heartbeat(center, runner_key, waiting=[waiting_row()])

    response = put_message(
        center,
        integration_key,
        name="bid_quote",
        correlation="BID-2026-001",
        payload={"견적": {"금액": 1_200_000}},
    )
    assert response.status_code == 201, response.text
    found = response.json()
    assert found["delivered_to"] == "run"
    assert found["run_id"] == RUN
    assert found["message_id"].startswith("msg_")
    assert "job_id" not in found or found["job_id"] is None


def test_the_message_rides_the_heartbeat_until_acked(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """**ack가 올 때까지 매번 다시 싣는다** (ADR-0007 — 작업과 같다)."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    put_message(center, name="bid_quote", correlation="BID-2026-001", payload={"견적": 1})

    first = heartbeat(center, runner_key, waiting=[waiting_row()])
    assert [one["name"] for one in first["messages"]] == ["bid_quote"]
    message_id = first["messages"][0]["message_id"]
    assert first["messages"][0]["payload"] == {"견적": 1}

    # ack하지 않았다 — 다시 온다 (실행기가 자리가 없어 못 넣은 경우다).
    again = heartbeat(center, runner_key, waiting=[waiting_row()])
    assert [one["message_id"] for one in again["messages"]] == [message_id]

    # 받아들였다고 말하면 끝이다.
    after = heartbeat(
        center,
        runner_key,
        waiting=[waiting_row()],
        message_acks=[{"message_id": message_id, "accepted": True, "run_id": RUN}],
    )
    assert after["messages"] == []


def test_a_refused_message_is_not_sent_again(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """`accepted: false`는 **다시 싣지 않는다** — 영원히 도는 메시지를 만들지 않는다."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    first = heartbeat(center, runner_key, waiting=[waiting_row()])
    message_id = first["messages"][0]["message_id"]

    after = heartbeat(
        center,
        runner_key,
        message_acks=[
            {"message_id": message_id, "accepted": False, "reason": "no_receiver"}
        ],
    )
    assert after["messages"] == []
    assert heartbeat(center, runner_key)["messages"] == []


def test_the_longest_waiting_run_gets_it(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """여럿이 맞으면 **가장 오래 기다린 것**에 준다. 한 메시지는 한 실행에만 간다."""
    old = waiting_row(run_id="run_20261013_080000_old111", since="2026-10-13T08:00:00+09:00")
    new = waiting_row(run_id="run_20261013_093000_new222", since="2026-10-13T09:30:00+09:00")
    heartbeat(center, runner_key, waiting=[new, old])

    response = put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    assert response.json()["run_id"] == "run_20261013_080000_old111"


def test_a_run_waiting_without_a_correlation_takes_any(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """기다리는 쪽에 상관 키가 없으면 **이름만 맞아도** 받는다 (엔진과 같은 규칙)."""
    heartbeat(center, runner_key, waiting=[waiting_row(correlation=None)])
    response = put_message(center, name="bid_quote", correlation="BID-아무거나", payload={})
    assert response.status_code == 201, response.text
    assert response.json()["delivered_to"] == "run"


def test_a_message_without_a_correlation_does_not_pick_a_run(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """**상관 키가 없으면 기다리는 실행을 찾지 않는다** (C12 §메시지).

    고를 열쇠가 없는데 고르면 같은 이름을 기다리는 실행 중 **엉뚱한 것**이 깨어난다. 메시지
    시작도 아니므로 `no_receiver`다.
    """
    heartbeat(center, runner_key, waiting=[waiting_row()])
    response = put_message(center, name="bid_quote", payload={})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "no_receiver"


def test_a_lost_runner_is_not_a_receiver(
    center: TestClient, store: Store, runner_key: str, runner: str
) -> None:
    """「유실 처리」된 실행기의 기다리는 실행은 **받을 곳이 아니다** — 그 실행은 닫혔다."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    go_offline(store, runner)
    assert center.post(f"/api/v1/server-runners/{runner}/mark-lost", headers=ADMIN).status_code == 200

    response = put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    assert response.status_code == 422
    assert response.json()["code"] == "no_receiver"


def test_mark_lost_closes_messages_on_the_way(
    center: TestClient, store: Store, runner_key: str, runner: str
) -> None:
    """내려가지 못한 메시지도 닫는다 — 그냥 두면 **다시 등록하는 날** 내려간다."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    go_offline(store, runner)

    response = center.post(f"/api/v1/server-runners/{runner}/mark-lost", headers=ADMIN)
    assert response.status_code == 200, response.text
    assert response.json()["messages_dropped"] == 1

    row = store.row("SELECT * FROM messages", ())
    assert row is not None
    assert str(row["state"]) == messages_api.REFUSED
    assert str(row["reason"]) == "host_lost"


# ─────────────────────────── 메시지 시작 → 작업 ───────────────────────────


def test_a_message_start_becomes_a_job(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """기다리는 실행이 없고 **메시지 시작 트리거**면 작업이 생긴다 (C12 §메시지).

    작업으로 바꾸는 것이 중요하다 — 배포 검사·빈자리·Bot별 상한이 **작업 쪽 한 자리**에
    남는다. `payload`가 그 작업의 `inputs`가 된다.
    """
    deploy(
        center,
        runner_id=runner,
        bot=RETURN_BOT,
        path=RETURN,
        process_id="Proc_bx13_return_processing",
        triggers=[{"kind": "message", "name": "return_request"}],
    )
    response = put_message(
        center,
        name="return_request",
        correlation="RT-001",
        payload={"반품번호": "RT-001", "주문번호": "ORD-9", "사유": "색이 다르다", "금액": 30_000,
                 "고객메일": "a@example.com"},
    )
    assert response.status_code == 201, response.text
    found = response.json()
    assert found["delivered_to"] == "new_job"
    assert found["job_id"].startswith("job_")

    job = center.get(f"/api/v1/jobs/{found['job_id']}", headers=ADMIN).json()
    assert job["bpm_process_id"] == RETURN_BOT
    assert job["version"] == VERSION  # 비워 보냈고 Center가 배포된 하나로 채웠다 (C5)
    assert job["inputs"]["반품번호"] == "RT-001"  # `payload`가 그 작업의 입력이 됐다


def test_a_message_start_with_two_bots_refuses_to_choose(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """같은 이름으로 시작하는 서버 Bot이 둘이면 **고르지 않는다** (422 `receiver_ambiguous`)."""
    for bot in (RETURN_BOT, f"{RETURN_BOT}-2"):
        deploy(
            center,
                runner_id=runner,
            bot=bot,
            path=RETURN,
            process_id="Proc_bx13_return_processing",
            triggers=[{"kind": "message", "name": "return_request"}],
            )

    response = put_message(center, name="return_request", correlation="RT-002", payload={})
    assert response.status_code == 422, response.text
    found = response.json()
    assert found["code"] == "receiver_ambiguous"
    assert sorted(found["detail"]["bpm_process_ids"]) == sorted([RETURN_BOT, f"{RETURN_BOT}-2"])


def test_an_undeployed_bot_is_not_a_receiver(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """배포되지 않은 Bot은 **메시지로도 돌지 않는다** — 작업과 같은 관문이다 (C5)."""
    response = put_message(center, name="return_request", correlation="RT-003", payload={})
    assert response.status_code == 422
    assert response.json()["code"] == "no_receiver"


# ─────────────────────────── 권한·멱등 (C5와 같다) ───────────────────────────


def test_only_admin_and_integration_keys_may_put_messages(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """현장 키로는 메시지를 넣을 수 없다 — 키 하나로 **남의 Bot을 깨울 수 있으면** 안 된다."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    body: dict[str, Any] = {
        "name": "bid_quote",
        "correlation": "BID-2026-001",
        "payload": {},
    }
    assert put_message(center, runner_key, **body).status_code == 403
    found = center.post(
        "/api/v1/messages", json={"schema": 1, **body}, headers=READ
    )
    assert found.status_code == 403, found.text
    assert put_message(center, **body).status_code == 201  # 관리자 토큰은 된다


def test_the_same_idempotency_key_gives_the_same_message(
    center: TestClient, runner_key: str, runner: str, integration_key: str
) -> None:
    """같은 멱등 키·같은 본문이면 **같은 답**이고 메시지는 하나다 (C5와 같은 규칙)."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    body: dict[str, Any] = {
        "name": "bid_quote",
        "correlation": "BID-2026-001",
        "payload": {"견적": 1},
        "idempotency_key": "shop-7",
    }
    first = put_message(center, integration_key, **body)
    assert first.status_code == 201, first.text
    again = put_message(center, integration_key, **body)
    assert again.status_code == 200, again.text
    assert again.json()["message_id"] == first.json()["message_id"]

    sent = heartbeat(center, runner_key, waiting=[waiting_row()])
    assert len(sent["messages"]) == 1


def test_the_same_key_with_another_body_is_a_conflict(
    center: TestClient, runner_key: str, runner: str, integration_key: str
) -> None:
    heartbeat(center, runner_key, waiting=[waiting_row()])
    first = put_message(
        center,
        integration_key,
        name="bid_quote",
        correlation="BID-2026-001",
        payload={"견적": 1},
        idempotency_key="shop-8",
    )
    assert first.status_code == 201, first.text
    again = put_message(
        center,
        integration_key,
        name="bid_quote",
        correlation="BID-2026-001",
        payload={"견적": 2},
        idempotency_key="shop-8",
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "idempotency_conflict"


def test_another_owners_idempotency_key_is_their_own(
    center: TestClient, runner_key: str, runner: str, integration_key: str
) -> None:
    """멱등 키의 범위는 **부른 쪽**이다 (C5) — 남의 키 이름과 겹쳐도 상관없다."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    other = _new_key(center, name="창고", kind="integration")
    body: dict[str, Any] = {
        "name": "bid_quote",
        "correlation": "BID-2026-001",
        "payload": {"견적": 1},
        "idempotency_key": "같은-이름",
    }
    first = put_message(center, integration_key, **body)
    second = put_message(center, other, **body)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["message_id"] != second.json()["message_id"]


def test_a_bad_body_says_so(center: TestClient, runner: str) -> None:
    response = center.post(
        "/api/v1/messages", json={"schema": 1, "payload": "글자다"}, headers=ADMIN
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "input_invalid"


def test_acks_do_not_touch_another_runners_message(
    center: TestClient, store: Store, runner_key: str, runner: str
) -> None:
    """**남의 메시지는 건드리지 않는다** — ack는 자기에게 내려간 것만 닫는다."""
    heartbeat(center, runner_key, waiting=[waiting_row()])
    put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    sent = heartbeat(center, runner_key, waiting=[waiting_row()])
    message_id = sent["messages"][0]["message_id"]

    second_key = _new_key(center, name="서버 2", kind="server_runner")
    register = center.post(
        "/api/v1/server-runner/register",
        json={
            "schema": 1,
            "machine_id": "b2" * 32,
            "name": "서버 2",
            "os": "Linux",
            "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {second_key}"},
    )
    assert register.status_code in (200, 201), register.text
    heartbeat(
        center,
        second_key,
        message_acks=[{"message_id": message_id, "accepted": True}],
    )

    # 첫 실행기에게는 그대로 다시 내려간다.
    assert [one["message_id"] for one in heartbeat(center, runner_key)["messages"]] == [message_id]


def test_the_oldest_wait_wins_across_runners(
    center: TestClient, runner_key: str, runner: str
) -> None:
    """**실행기가 여럿이어도 가장 오래 기다린 것**이다 (C12).

    실행기마다 고른 뒤 그중에서 다시 고르지 않으면 「오래 기다린 쪽부터」가 **실행기 id
    순서**로 바뀐다 — 그러면 먼저 기다린 입찰이 뒤로 밀린다.
    """
    second_key = _new_key(center, name="서버 2", kind="server_runner")
    register = center.post(
        "/api/v1/server-runner/register",
        json={
            "schema": 1,
            "machine_id": "b2" * 32,
            "name": "서버 2",
            "os": "Linux",
            "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {second_key}"},
    )
    assert register.status_code in (200, 201), register.text

    # 첫 실행기가 **나중에** 기다리기 시작했다.
    heartbeat(
        center,
        runner_key,
        waiting=[waiting_row(run_id="run_20261013_093000_new222", since="2026-10-13T09:30:00+09:00")],
    )
    heartbeat(
        center,
        second_key,
        waiting=[waiting_row(run_id="run_20261013_080000_old111", since="2026-10-13T08:00:00+09:00")],
    )

    response = put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    assert response.json()["run_id"] == "run_20261013_080000_old111"
    # 그 실행기에게만 내려간다.
    assert heartbeat(center, runner_key)["messages"] == []
    assert len(heartbeat(center, second_key)["messages"]) == 1


def test_an_offline_runner_is_still_a_receiver(
    center: TestClient, store: Store, runner_key: str, runner: str
) -> None:
    """**오프라인인 실행기에는 걸어 둔다** — 돌아오면 이어 간다 (C12 §재시작과 유실).

    빼면 그 사이 온 메시지가 `no_receiver`가 되거나 **새 작업으로 새어 나간다** — 같은 입찰이
    두 번 돌게 된다. 「유실 처리」된 것만 받는 곳이 아니다.
    """
    heartbeat(center, runner_key, waiting=[waiting_row()])
    go_offline(store, runner)

    response = put_message(center, name="bid_quote", correlation="BID-2026-001", payload={})
    assert response.status_code == 201, response.text
    assert response.json()["delivered_to"] == "run"
    # 돌아온 실행기가 그것을 받는다.
    assert len(heartbeat(center, runner_key, waiting=[waiting_row()])["messages"]) == 1


def test_a_message_start_carries_on_behalf_of_into_the_job(
    center: TestClient, runner: str, integration_key: str
) -> None:
    """연동용 키가 실은 사람은 작업의 `on_behalf_of`로 **적기만** 한다 (ADR-0081).

    `requested_by`는 키 이름 그대로다 — Bot UI가 그 칸의 `server_bot:`로 위임을 가르므로
    바깥에서 온 글을 그 칸에 넣지 않는다. 그 앞머리로 시작하는 이름은 422다.
    """
    deploy(
        center,
        runner_id=runner,
        bot=RETURN_BOT,
        path=RETURN,
        process_id="Proc_bx13_return_processing",
        triggers=[{"kind": "message", "name": "return_request"}],
    )
    body = {"schema": 1, "name": "return_request", "payload": {"반품번호": "RT-002", "주문번호": "ORD-9",
            "사유": "파손", "금액": 10_000, "고객메일": "a@example.com"}}
    auth = {"Authorization": f"Bearer {integration_key}"}
    spoof = center.post("/api/v1/messages", json=body,
                        headers={**auth, "X-CHK-On-Behalf-Of": "server_bot%3Arun_x"})
    assert spoof.status_code == 422 and spoof.json()["code"] == "on_behalf_invalid"

    made = center.post("/api/v1/messages", json=body, headers={**auth, "X-CHK-On-Behalf-Of": "%EA%B9%80"})
    assert made.status_code == 201, made.text
    job = center.get(f"/api/v1/jobs/{made.json()['job_id']}", headers=ADMIN).json()
    assert job["on_behalf_of"] == "김"
    assert not job["requested_by"].startswith("server_bot:") and job["requested_by"] != "김"

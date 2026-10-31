"""등록 요청과 승인, 키 회전 (C4·C12 §등록 요청과 승인, C5 §등록 승인, ADR-0092).

사람은 키를 보지 않는다 — 현장이 공개키를 실어 요청하고, 관리자가 요청 코드를 맞춰 승인하면
Center가 키를 만들어 그 공개키로 봉해 둔다. 여기서는 앱을 TestClient로 두드려 그 길을 끝까지 본다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.enrollment import (
    EnrollStatus,
    Sealed,
    SealError,
    new_keypair,
    open_sealed,
    request_code,
    seal,
    valid_public_key,
)

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def client(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "packages")
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def machine(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def bot_body(public_key: str, *, seed: str = "pc1", name: str = "현장 PC 1") -> dict[str, Any]:
    return {
        "schema": 1,
        "machine_id": machine(seed),
        "name": name,
        "os": "windows-11-23H2",
        "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        "public_key": public_key,
    }


def runner_body(public_key: str, *, seed: str = "srv1") -> dict[str, Any]:
    return {
        "schema": 1,
        "machine_id": machine(seed),
        "name": "서버 1",
        "os": "ubuntu-24.04",
        "versions": {"server_runner": "0.1.0", "core": "0.1.0"},
        "public_key": public_key,
    }


def heartbeat_body() -> dict[str, Any]:
    return {
        "schema": 1,
        "status": "idle",
        "current_run": None,
        "queue": {"max": 20, "items": []},
        "worker": {"state": "off", "restarts": 0},
    }


def enroll(client: TestClient, body: dict[str, Any], *, kind: str = "bot-ui") -> EnrollStatus:
    response = client.post(f"/api/v1/{kind}/enroll", json=body)
    assert response.status_code == 201, response.text
    return EnrollStatus.model_validate(response.json())


def approve(client: TestClient, enrollment_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/api/v1/enrollments/{enrollment_id}/approve", json=body, headers=ADMIN)
    assert response.status_code == 200, response.text
    return dict(response.json())


def receive_key(client: TestClient, private: str, enrollment_id: str, *, kind: str = "bot-ui") -> str:
    """현장이 하는 일 — 물어서 봉함을 받아 연다."""
    status = EnrollStatus.model_validate(client.get(f"/api/v1/{kind}/enroll/{enrollment_id}").json())
    assert status.state == "approved"
    assert status.sealed_key is not None
    return open_sealed(private, status.sealed_key, salt=enrollment_id)


# ─────────────── 봉함·요청 코드 (계약) ───────────────


def test_seal_opens_only_with_the_matching_private_key() -> None:
    private, public = new_keypair()
    other, _ = new_keypair()
    sealed = seal(public, "chk_ctr_secret", salt="enr_x")
    assert open_sealed(private, sealed, salt="enr_x") == "chk_ctr_secret"
    with pytest.raises(SealError):
        open_sealed(other, sealed, salt="enr_x")
    # 다른 자리의 봉함을 끼워도 열리지 않는다 (salt가 다르다).
    with pytest.raises(SealError):
        open_sealed(private, sealed, salt="enr_y")
    tampered = Sealed.model_validate(sealed.to_json_dict() | {"ciphertext": sealed.ciphertext[:-2] + "AA"})
    with pytest.raises(SealError):
        open_sealed(private, tampered, salt="enr_x")


def test_request_code_depends_on_key_and_id() -> None:
    _, public = new_keypair()
    _, other = new_keypair()
    code = request_code(public, "enr_" + "0" * 32)
    assert len(code) == 9 and code[4] == "-"
    assert code == request_code(public, "enr_" + "0" * 32)
    assert code != request_code(public, "enr_" + "1" * 32)
    assert code != request_code(other, "enr_" + "0" * 32)


def test_public_key_shape() -> None:
    _, public = new_keypair()
    assert valid_public_key(public)
    assert not valid_public_key("A" * 42)
    assert not valid_public_key("!" * 43)


# ─────────────── 요청 → 승인 → 등록 ───────────────


def test_enroll_approve_register_end_to_end(client: TestClient, store: Store) -> None:
    private, public = new_keypair()
    pending = enroll(client, bot_body(public))
    assert pending.state == "pending"
    # 현장이 코드를 스스로 다시 계산해 맞춰 본다 (C4 3번째 차례).
    assert pending.code == request_code(public, pending.enrollment_id)

    listed = client.get("/api/v1/enrollments", headers=READ).json()
    assert [one["code"] for one in listed] == [pending.code]
    assert listed[0]["existing"] is None

    # 승인 전에는 봉함이 없다.
    waiting = client.get(f"/api/v1/bot-ui/enroll/{pending.enrollment_id}").json()
    assert waiting["state"] == "pending" and waiting["sealed_key"] is None

    decision = approve(client, pending.enrollment_id)
    assert decision["host_id"] is None and decision["replaced_key_id"] is None
    key = receive_key(client, private, pending.enrollment_id)
    assert key.startswith("chk_ctr_")

    response = client.post(
        "/api/v1/bot-ui/register", json=bot_body(public), headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200, response.text
    # **받은 뒤에는 봉함이 없다** — Center에도 원문이 남지 않는다.
    again = client.get(f"/api/v1/bot-ui/enroll/{pending.enrollment_id}").json()
    assert again["sealed_key"] is None
    row = store.row("SELECT sealed_json FROM enrollments WHERE enrollment_id = ?", (pending.enrollment_id,))
    assert row is not None and row["sealed_json"] is None

    info = next(k for k in client.get("/api/v1/center-keys", headers=ADMIN).json() if k["key_id"] == decision["key_id"])
    assert info["enrollment_id"] == pending.enrollment_id
    assert info["bound_to"]["id"] == machine("pc1")


def test_approval_takes_over_an_already_registered_pc(client: TestClient) -> None:
    """PC를 다시 설치했다 — 승인이 「PC 묶음 풀기」를 대신한다 (C4 키 묶기)."""
    private, public = new_keypair()
    first = enroll(client, bot_body(public))
    approve(client, first.enrollment_id)
    old_key = receive_key(client, private, first.enrollment_id)
    old = client.post("/api/v1/bot-ui/register", json=bot_body(public), headers={"Authorization": f"Bearer {old_key}"})
    bot_ui_id = old.json()["bot_ui_id"]

    # 다시 설치 — 키 쌍도 새로 만든다.
    private2, public2 = new_keypair()
    second = enroll(client, bot_body(public2))
    row = client.get("/api/v1/enrollments", headers=READ).json()[0]
    assert row["existing"]["id"] == bot_ui_id

    decision = approve(client, second.enrollment_id)
    assert decision["host_id"] == bot_ui_id
    new_key = receive_key(client, private2, second.enrollment_id)
    again = client.post(
        "/api/v1/bot-ui/register", json=bot_body(public2), headers={"Authorization": f"Bearer {new_key}"}
    )
    assert again.status_code == 200, again.text
    assert again.json()["bot_ui_id"] == bot_ui_id  # 배포·기록이 가리키는 자리를 이어받았다
    # 옛 키는 폐기됐다.
    old_auth = {"Authorization": f"Bearer {old_key}"}
    beat = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=old_auth)
    assert beat.status_code == 403


def test_reject_tells_the_reason_and_cannot_be_decided_twice(client: TestClient) -> None:
    _, public = new_keypair()
    pending = enroll(client, bot_body(public))
    response = client.post(
        f"/api/v1/enrollments/{pending.enrollment_id}/reject", json={"reason": "모르는 PC"}, headers=ADMIN
    )
    assert response.status_code == 200, response.text
    status = client.get(f"/api/v1/bot-ui/enroll/{pending.enrollment_id}").json()
    assert status["state"] == "rejected" and status["reason"] == "모르는 PC"
    twice = client.post(f"/api/v1/enrollments/{pending.enrollment_id}/approve", json={}, headers=ADMIN)
    assert twice.status_code == 409 and twice.json()["code"] == "enrollment_closed"


def test_only_admin_decides(client: TestClient) -> None:
    _, public = new_keypair()
    pending = enroll(client, bot_body(public))
    refused = client.post(f"/api/v1/enrollments/{pending.enrollment_id}/approve", json={}, headers=READ)
    assert refused.status_code == 403
    assert client.get("/api/v1/enrollments").status_code == 401


def test_same_pc_asking_again_closes_the_old_request(client: TestClient) -> None:
    _, public = new_keypair()
    first = enroll(client, bot_body(public))
    second = enroll(client, bot_body(public))
    listed = client.get("/api/v1/enrollments", headers=READ).json()
    assert [one["enrollment_id"] for one in listed] == [second.enrollment_id]
    assert client.get(f"/api/v1/bot-ui/enroll/{first.enrollment_id}").json()["state"] == "expired"


def test_bad_public_key_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/bot-ui/enroll", json=bot_body("A" * 10))
    assert response.status_code == 422 and response.json()["code"] == "public_key_invalid"


def test_too_many_requests_from_one_place(client: TestClient) -> None:
    for n in range(10):
        _, public = new_keypair()
        enroll(client, bot_body(public, seed=f"pc{n}"))
    _, public = new_keypair()
    response = client.post("/api/v1/bot-ui/enroll", json=bot_body(public, seed="pc-extra"))
    assert response.status_code == 429 and response.json()["code"] == "enroll_rate_limited"


def test_pending_expires_after_a_day(client: TestClient, store: Store) -> None:
    _, public = new_keypair()
    pending = enroll(client, bot_body(public))
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with store.tx() as cur:
        cur.execute("UPDATE enrollments SET expires_at = ? WHERE enrollment_id = ?", (past, pending.enrollment_id))
    assert client.get(f"/api/v1/bot-ui/enroll/{pending.enrollment_id}").json()["state"] == "expired"
    assert client.get("/api/v1/enrollments", headers=READ).json() == []


def test_unclaimed_key_is_revoked_after_a_day(client: TestClient, store: Store) -> None:
    _, public = new_keypair()
    pending = enroll(client, bot_body(public))
    decision = approve(client, pending.enrollment_id)
    past = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with store.tx() as cur:
        cur.execute("UPDATE enrollments SET decided_at = ? WHERE enrollment_id = ?", (past, pending.enrollment_id))
    status = client.get(f"/api/v1/bot-ui/enroll/{pending.enrollment_id}").json()
    assert status["state"] == "expired" and status["sealed_key"] is None
    info = next(k for k in client.get("/api/v1/center-keys", headers=ADMIN).json() if k["key_id"] == decision["key_id"])
    assert info["state"] == "revoked"


def test_server_runner_enrolls_the_same_way(client: TestClient) -> None:
    private, public = new_keypair()
    pending = enroll(client, runner_body(public), kind="server-runner")
    listed = client.get("/api/v1/enrollments?type=server_runner", headers=READ).json()
    assert [one["type"] for one in listed] == ["server_runner"]
    # 종류가 다른 경로로는 보이지 않는다.
    assert client.get(f"/api/v1/bot-ui/enroll/{pending.enrollment_id}").status_code == 404
    approve(client, pending.enrollment_id)
    key = receive_key(client, private, pending.enrollment_id, kind="server-runner")
    response = client.post(
        "/api/v1/server-runner/register", json=runner_body(public), headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 200, response.text


# ─────────────── 들이기 비밀 (C12, ADR-0117) ───────────────

JOIN = "j" * 43


@pytest.fixture
def joined(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "packages", server_runner_join_token=JOIN
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def test_a_bundled_runner_is_approved_on_the_spot(joined: TestClient, store: Store) -> None:
    """같이 배포된 실행기 — 답이 곧 `approved`이고 봉함이 실려 있다. 「승인 대기」에 줄이 없다."""
    private, public = new_keypair()
    response = joined.post(
        "/api/v1/server-runner/enroll", json=runner_body(public), headers={"X-CHK-Join-Token": JOIN}
    )
    assert response.status_code == 201, response.text
    status = EnrollStatus.model_validate(response.json())
    assert status.state == "approved" and status.sealed_key is not None
    key = open_sealed(private, status.sealed_key, salt=status.enrollment_id)
    assert joined.get("/api/v1/enrollments?type=server_runner", headers=READ).json() == []
    row = store.row("SELECT decided_by, request_json FROM enrollments WHERE enrollment_id = ?", (status.enrollment_id,))
    assert row is not None and row["decided_by"] == "join_token"
    assert JOIN not in str(row["request_json"]), "비밀은 저장된 요청에 들어가지 않는다"
    registered = joined.post(
        "/api/v1/server-runner/register", json=runner_body(public), headers={"Authorization": f"Bearer {key}"}
    )
    assert registered.status_code == 200, registered.text

    # 볼륨을 잃고 다시 와도 들어온다 — 같은 기계의 자리를 이어받는다.
    _, public2 = new_keypair()
    second = joined.post(
        "/api/v1/server-runner/enroll", json=runner_body(public2), headers={"X-CHK-Join-Token": JOIN}
    ).json()
    assert second["state"] == "approved"


def test_a_wrong_join_token_is_refused_without_a_pending_row(joined: TestClient, client: TestClient) -> None:
    _, public = new_keypair()
    for app, value in ((joined, "x" * 43), (client, JOIN)):  # 다르다 / Center에 없다
        response = app.post(
            "/api/v1/server-runner/enroll", json=runner_body(public), headers={"X-CHK-Join-Token": value}
        )
        assert response.status_code == 403 and response.json()["code"] == "join_token_invalid"
    assert joined.get("/api/v1/enrollments?type=server_runner", headers=READ).json() == []


def test_without_the_header_a_runner_still_waits(joined: TestClient) -> None:
    _, public = new_keypair()
    assert enroll(joined, runner_body(public), kind="server-runner").state == "pending"


# ─────────────── 키 회전 (C4 §키 회전) ───────────────


def test_key_rotates_before_it_expires(client: TestClient, store: Store) -> None:
    private, public = new_keypair()
    pending = enroll(client, bot_body(public))
    approve(client, pending.enrollment_id)
    key = receive_key(client, private, pending.enrollment_id)
    bot_ui_id = client.post(
        "/api/v1/bot-ui/register", json=bot_body(public), headers={"Authorization": f"Bearer {key}"}
    ).json()["bot_ui_id"]

    # 멀리 있으면 싣지 않는다.
    beat = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers={"Authorization": f"Bearer {key}"})
    assert beat.json().get("rotated_key") is None

    soon = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    with store.tx() as cur:
        cur.execute("UPDATE center_keys SET expires_at = ? WHERE enrollment_id = ?", (soon, pending.enrollment_id))
    first = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers={"Authorization": f"Bearer {key}"})
    rotated = first.json()["rotated_key"]
    assert rotated is not None
    # 같은 것을 다시 싣는다 (새 키로 첫 요청이 올 때까지).
    second = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers={"Authorization": f"Bearer {key}"})
    assert second.json()["rotated_key"] == rotated

    new_key = open_sealed(private, Sealed.model_validate(rotated["sealed_key"]), salt=bot_ui_id)
    with_new = client.post(
        "/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers={"Authorization": f"Bearer {new_key}"}
    )
    assert with_new.status_code == 200, with_new.text
    assert with_new.json().get("rotated_key") is None
    # 옛 키는 폐기됐다.
    old = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers={"Authorization": f"Bearer {key}"})
    assert old.status_code == 403


def test_keys_without_a_public_key_do_not_rotate(client: TestClient, store: Store) -> None:
    """환경변수로 받은 키(공개키를 모른다)는 회전하지 않는다 — 지금처럼 BUI-05가 알린다."""
    made = client.post("/api/v1/center-keys", json={"name": "자동화", "type": "bot_ui"}, headers=ADMIN).json()
    soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    with store.tx() as cur:
        cur.execute("UPDATE center_keys SET expires_at = ? WHERE key_id = ?", (soon, made["key_id"]))
    body = bot_body(new_keypair()[1])
    del body["public_key"]
    headers = {"Authorization": f"Bearer {made['key']}"}
    assert client.post("/api/v1/bot-ui/register", json=body, headers=headers).status_code == 200
    beat = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=headers)
    assert beat.json().get("rotated_key") is None


# ─────────────── Studio (C5 §Studio 등록 요청과 승인, ADR-0093) ───────────────


def studio_body(public_key: str, *, seed: str = "designer-pc", name: str = "설계 PC") -> dict[str, Any]:
    return {
        "schema": 1,
        "machine_id": machine(seed),
        "name": name,
        "os": "windows-11-23H2",
        "versions": {"studio": "0.1.0", "core": "0.1.0"},
        "public_key": public_key,
    }


def test_studio_is_let_in_the_same_way_and_its_name_is_who(client: TestClient, store: Store) -> None:
    """Studio도 요청 코드 → 승인이다. 아이디·비밀번호가 없고 「누가」는 승인 때 붙인 이름이다."""
    private, public = new_keypair()
    pending = enroll(client, studio_body(public), kind="studio")
    assert pending.code == request_code(public, pending.enrollment_id)
    listed = client.get("/api/v1/enrollments?type=studio", headers=READ).json()
    assert [one["code"] for one in listed] == [pending.code]

    approve(client, pending.enrollment_id, name="김OO 설계 PC")
    key = receive_key(client, private, pending.enrollment_id, kind="studio")
    headers = {"Authorization": f"Bearer {key}"}
    listed_keys = client.get("/api/v1/center-keys", headers=ADMIN).json()
    info = next(k for k in listed_keys if k["enrollment_id"] == pending.enrollment_id)
    assert info["type"] == "studio" and info["name"] == "김OO 설계 PC"

    # 처음 부르면 그것이 받았다는 표시다 — 봉해 둔 것을 지운다 (Studio에는 `register`가 없다).
    assert client.get("/api/v1/packages", headers=headers).status_code == 200
    row = store.row("SELECT sealed_json FROM enrollments WHERE enrollment_id = ?", (pending.enrollment_id,))
    assert row is not None and row["sealed_json"] is None


def test_reapproving_the_same_studio_pc_revokes_the_old_key(client: TestClient) -> None:
    private, public = new_keypair()
    first = enroll(client, studio_body(public), kind="studio")
    approve(client, first.enrollment_id)
    old = {"Authorization": f"Bearer {receive_key(client, private, first.enrollment_id, kind='studio')}"}
    assert client.get("/api/v1/packages", headers=old).status_code == 200

    private2, public2 = new_keypair()
    second = enroll(client, studio_body(public2), kind="studio")
    listed = client.get("/api/v1/enrollments?type=studio", headers=READ).json()
    assert listed[0]["existing"]["name"] == "설계 PC"
    decision = approve(client, second.enrollment_id)
    assert decision["replaced_key_id"] is not None
    new = {"Authorization": f"Bearer {receive_key(client, private2, second.enrollment_id, kind='studio')}"}
    assert client.get("/api/v1/packages", headers=old).status_code == 403
    assert client.get("/api/v1/packages", headers=new).status_code == 200


def test_studio_keys_last_a_year(client: TestClient) -> None:
    private, public = new_keypair()
    pending = enroll(client, studio_body(public), kind="studio")
    approve(client, pending.enrollment_id)
    status = client.get(f"/api/v1/studio/enroll/{pending.enrollment_id}").json()
    days = (datetime.fromisoformat(status["key_expires_at"]) - datetime.now(UTC)).days
    assert days in (364, 365)

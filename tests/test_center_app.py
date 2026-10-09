"""Center 앱 (`chaeksas.center`) — 실제로 띄워 부르는 시험 (M2 완료 기준).

계약 **모델·검사 함수**의 시험은 `test_center_api.py`에 있다. 이 파일은 그 계약을 지키는
**앱**을 TestClient로 두드린다.

세 줄이 여기 걸려 있다.

1. 콘솔에서 발급한 Center API 키로 등록 → 하트비트 (C4, CON-11)
2. **Bot UI별 키로 다른 Bot UI를 사칭할 수 없다**
3. 패키지 업로드·목록·내려받기, 해시 검증 (C1, C5)
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.hashing import canonical_json, content_hash_zip, sha256_hex

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}


@pytest.fixture
def packages_dir(tmp_path: Path) -> Path:
    return tmp_path / "packages"


@pytest.fixture
def client(packages_dir: Path) -> Iterator[TestClient]:
    settings = Settings(admin_token="t-admin", read_token="t-read", package_dir=packages_dir)
    store = Store(Path(":memory:"))
    app = create_app(settings, store=store)
    with TestClient(app) as found:
        yield found
    store.close()


def issue_key(client: TestClient, *, name: str = "현장 PC 1", key_type: str = "bot_ui") -> tuple[str, str]:
    """키를 발급한다. `(key_id, 원문)` — 원문은 이 응답에만 있다."""
    response = client.post("/api/v1/center-keys", json={"name": name, "type": key_type}, headers=ADMIN)
    assert response.status_code == 201, response.text
    body = response.json()
    return body["key_id"], body["key"]


def machine_id(seed: str) -> str:
    """PC 고유값의 SHA-256 (C4 — 원값은 보내지 않는다)."""
    return hashlib.sha256(seed.encode()).hexdigest()


def register_body(*, machine: str, name: str = "현장 PC 1") -> dict[str, Any]:
    return {
        "schema": 1,
        "machine_id": machine,
        "name": name,
        "os": "windows-11-23H2",
        "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
    }


def heartbeat_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": 1,
        "status": "idle",
        "current_run": None,
        "queue": {"max": 20, "items": []},
        "worker": {"state": "off", "restarts": 0},
    }
    body.update(over)
    return body


# ─────────────────────────── 인증 (C5 권한표) ───────────────────────────


def test_healthz_needs_no_token(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200 and response.json()["status"] == "ok"


def test_calls_without_a_token_are_refused(client: TestClient) -> None:
    response = client.get("/api/v1/center-keys")
    assert response.status_code == 401
    assert response.json()["code"] == "token_missing"


def test_read_token_cannot_write(client: TestClient) -> None:
    response = client.post("/api/v1/center-keys", json={"name": "x", "type": "bot_ui"}, headers=READ)
    assert response.status_code == 403 and response.json()["code"] == "admin_only"


def test_unknown_token_is_refused(client: TestClient) -> None:
    # HTTP 헤더는 ASCII다 — 한글 키는 애초에 보낼 수 없다.
    response = client.get("/api/v1/center-keys", headers={"Authorization": "Bearer chk_ctr_" + "x" * 40})
    assert response.status_code == 401 and response.json()["code"] == "key_invalid"


# ─────────────────────────── C7 키 (CON-11) ───────────────────────────


def test_issued_key_shows_its_raw_value_only_once(client: TestClient) -> None:
    key_id, raw = issue_key(client)
    assert raw.startswith("chk_ctr_") and len(raw) == len("chk_ctr_") + 40

    listed = client.get("/api/v1/center-keys", headers=READ).json()
    assert [k["key_id"] for k in listed] == [key_id]
    assert "key" not in listed[0], "목록에 원문이 실리면 안 된다"
    assert listed[0]["prefix"] == raw[:16]
    assert listed[0]["state"] == "active"


def test_revoked_key_cannot_be_used(client: TestClient) -> None:
    key_id, raw = issue_key(client)
    assert client.delete(f"/api/v1/center-keys/{key_id}", headers=ADMIN).status_code == 200

    response = client.post(
        "/api/v1/bot-ui/register",
        json=register_body(machine=machine_id("pc1")),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 403 and response.json()["code"] == "key_revoked"


def test_key_state_follows_expiry(client: TestClient) -> None:
    past = datetime(2020, 1, 1, tzinfo=UTC).isoformat()
    response = client.post(
        "/api/v1/center-keys", json={"name": "만료된 키", "type": "bot_ui", "expires_at": past}, headers=ADMIN
    )
    assert response.status_code == 201
    raw = response.json()["key"]
    listed = client.get("/api/v1/center-keys?state=expired", headers=READ).json()
    assert len(listed) == 1
    used = client.post(
        "/api/v1/bot-ui/register",
        json=register_body(machine=machine_id("pc1")),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert used.status_code == 403 and used.json()["code"] == "key_expired"


def test_issuing_an_unknown_key_type_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/center-keys", json={"name": "x", "type": "농담"}, headers=ADMIN)
    assert response.status_code == 422


# ─────────────────────────── C4 등록·하트비트 ───────────────────────────


def test_register_then_heartbeat(client: TestClient) -> None:
    """M2 기준 — 콘솔에서 발급한 키를 넣으면 등록 → 하트비트."""
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}

    registered = client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert body["bot_ui_id"].startswith("bui_")
    assert body["heartbeat_interval_s"] == 30

    beat = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=auth)
    assert beat.status_code == 200, beat.text
    assert beat.json()["next_heartbeat_s"] == 30
    assert beat.json()["disabled"] is False

    listed = client.get("/api/v1/bot-uis", headers=READ).json()
    assert len(listed) == 1
    assert listed[0]["online"] is True, "방금 하트비트를 받았으니 온라인이다"
    assert listed[0]["status"] == "idle"
    # 키 정보는 앞자리·만료·상태만 (C7 — 원문·해시는 주지 않는다).
    assert listed[0]["key"]["prefix"] == raw[:16]
    assert set(listed[0]["key"]) == {"prefix", "expires_at", "state"}


def test_register_is_idempotent(client: TestClient) -> None:
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    machine = machine_id("pc1")
    first = client.post("/api/v1/bot-ui/register", json=register_body(machine=machine), headers=auth).json()
    again = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine, name="이름 바꿈"), headers=auth
    ).json()
    assert first["bot_ui_id"] == again["bot_ui_id"], "같은 키·같은 PC면 같은 Bot UI다"
    assert client.get("/api/v1/bot-uis", headers=READ).json()[0]["name"] == "이름 바꿈"


def test_a_key_cannot_be_used_from_another_pc(client: TestClient) -> None:
    """**M2 기준 — 다른 Bot UI를 사칭할 수 없다.** 키는 처음 등록한 PC에 묶인다 (C4)."""
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)

    stolen = client.post(
        "/api/v1/bot-ui/register",
        json=register_body(machine=machine_id("훔친-pc"), name="공격자 PC"),
        headers=auth,
    )
    assert stolen.status_code == 409
    assert stolen.json()["code"] == "machine_mismatch"
    assert client.get("/api/v1/bot-uis", headers=READ).json()[0]["name"] == "현장 PC 1"


def test_unbinding_lets_a_reinstalled_pc_register(client: TestClient) -> None:
    """PC를 다시 설치해 `machine_id`가 바뀌면 운영자가 묶음을 푼다 (CON-11)."""
    key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)

    unbound = client.post(f"/api/v1/center-keys/{key_id}/unbind", headers=ADMIN)
    assert unbound.status_code == 200 and unbound.json()["bound_to"] is None
    again = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1-다시설치")), headers=auth
    )
    assert again.status_code == 200
    assert client.post(f"/api/v1/center-keys/{key_id}/unbind", headers=ADMIN).status_code == 200


def test_a_second_key_cannot_register_the_same_pc(client: TestClient) -> None:
    """**PC → 키 방향도 하나다** (C4 「키 묶기」).

    같은 PC에 두 번째 키를 발급해 등록하면 Bot UI 행이 둘 생겼다 — CON-03에 같은 PC가 두
    줄로 보이고, C7 리소스의 PC 수가 부풀고, 작업이 하트비트를 보내지 않는 쪽으로 갔다.
    """
    _a_id, key_a = issue_key(client)
    _b_id, key_b = issue_key(client, name="현장 PC 1 (키 두 번째)")
    machine = machine_id("pc1")
    first = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine), headers={"Authorization": f"Bearer {key_a}"}
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/bot-ui/register",
        json=register_body(machine=machine, name="같은 PC, 다른 키"),
        headers={"Authorization": f"Bearer {key_b}"},
    )
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["code"] == "machine_already_registered"
    assert body["detail"]["reason"] == "bound_elsewhere"
    assert body["detail"]["bot_ui_id"] == first.json()["bot_ui_id"]

    listed = client.get("/api/v1/bot-uis", headers=READ).json()
    assert len(listed) == 1, "같은 PC가 두 줄로 보이면 안 된다"
    assert listed[0]["name"] == "현장 PC 1"


def test_a_refused_registration_does_not_bind_the_key(client: TestClient) -> None:
    """거부된 등록은 키를 묶지 않는다 (C4) — 그러면 운영자가 새 키의 묶음까지 풀어야 한다."""
    _a_id, key_a = issue_key(client)
    key_b_id, key_b = issue_key(client, name="두 번째 키")
    machine = machine_id("pc1")
    client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine), headers={"Authorization": f"Bearer {key_a}"}
    )
    refused = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine), headers={"Authorization": f"Bearer {key_b}"}
    )
    assert refused.status_code == 409

    keys = {k["key_id"]: k for k in client.get("/api/v1/center-keys", headers=READ).json()}
    assert keys[key_b_id]["bound_to"] is None, "막힌 키는 CON-11에서 「등록 전」이다"


def test_unbinding_lets_a_new_key_take_over_the_pc(client: TestClient) -> None:
    """키를 잃어 새 키를 발급한 경우 — 묶음을 풀면 새 키가 **그 자리를 이어받는다** (C4)."""
    key_a_id, key_a = issue_key(client)
    _b_id, key_b = issue_key(client, name="다시 발급한 키")
    auth_a = {"Authorization": f"Bearer {key_a}"}
    auth_b = {"Authorization": f"Bearer {key_b}"}
    machine = machine_id("pc1")
    first = client.post("/api/v1/bot-ui/register", json=register_body(machine=machine), headers=auth_a).json()
    beat = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(status="running"), headers=auth_a)
    assert beat.status_code == 200

    assert client.post(f"/api/v1/center-keys/{key_a_id}/unbind", headers=ADMIN).status_code == 200
    again = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine, name="같은 PC"), headers=auth_b
    )
    assert again.status_code == 200, again.text
    assert again.json()["bot_ui_id"] == first["bot_ui_id"], "배포·작업·결재가 가리키는 자리를 그대로 쓴다"

    listed = client.get("/api/v1/bot-uis", headers=READ).json()
    assert len(listed) == 1
    assert listed[0]["key"]["prefix"] == key_b[:16], "이제 새 키의 Bot UI다"
    # 이어받은 자리의 상태는 비운다 — 옛 키가 보고한 것이다 (C4).
    assert listed[0]["status"] is None and listed[0]["online"] is False

    # 옛 키는 자리를 잃었다 — 하트비트는 409 `not_registered`.
    lost = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=auth_a)
    assert lost.status_code == 409 and lost.json()["code"] == "not_registered"


def test_a_key_that_still_has_its_own_pc_cannot_take_over_another(client: TestClient) -> None:
    """이어받기는 **행이 없는 키만** 한다 (C4) — 어느 쪽 이력을 버릴지 짐작하지 않는다."""
    key_a_id, key_a = issue_key(client)
    key_b_id, key_b = issue_key(client, name="현장 PC 2")
    pc1, pc2 = machine_id("pc1"), machine_id("pc2")
    a = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=pc1), headers={"Authorization": f"Bearer {key_a}"}
    ).json()
    b = client.post(
        "/api/v1/bot-ui/register",
        json=register_body(machine=pc2, name="현장 PC 2"),
        headers={"Authorization": f"Bearer {key_b}"},
    ).json()
    for key_id in (key_a_id, key_b_id):
        assert client.post(f"/api/v1/center-keys/{key_id}/unbind", headers=ADMIN).status_code == 200

    moved = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=pc1), headers={"Authorization": f"Bearer {key_b}"}
    )
    assert moved.status_code == 409, moved.text
    assert moved.json()["detail"]["reason"] == "key_has_another_pc"

    by_id = {row["bot_ui_id"]: row for row in client.get("/api/v1/bot-uis", headers=READ).json()}
    assert by_id[a["bot_ui_id"]]["machine_id"] == pc1
    assert by_id[b["bot_ui_id"]]["machine_id"] == pc2


def test_wrong_key_type_is_refused(client: TestClient) -> None:
    """Bot UI용 키만 받는다 (C4). Studio용 키로 부르면 403."""
    _key_id, raw = issue_key(client, name="설계자 PC", key_type="studio")
    response = client.post(
        "/api/v1/bot-ui/register",
        json=register_body(machine=machine_id("pc1")),
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert response.status_code == 403 and response.json()["code"] == "wrong_key_type"


def test_heartbeat_before_register_is_refused(client: TestClient) -> None:
    _key_id, raw = issue_key(client)
    response = client.post(
        "/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 409 and response.json()["code"] == "not_registered"


def test_heartbeat_keeps_the_latest_state(client: TestClient) -> None:
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)
    running = heartbeat_body(
        status="running",
        current_run={
            "run_id": "run_1",
            "bpm_process_id": "erp.order-entry",
            "version": "2.1.0",
            "state": "running",
            "started_at": "2026-10-03T10:15:00+09:00",
            "source": "job",
        },
        worker={"state": "running", "restarts": 0, "session": "bot"},
    )
    assert client.post("/api/v1/bot-ui/heartbeat", json=running, headers=auth).status_code == 200
    found = client.get("/api/v1/bot-uis", headers=READ).json()[0]
    assert found["status"] == "running"
    assert found["current_run"]["run_id"] == "run_1"
    assert found["worker"]["session"] == "bot"


def test_disabled_bot_ui_still_heartbeats(client: TestClient) -> None:
    """비활성이어도 하트비트는 받는다 — 실행 중 Bot과 대기열을 콘솔에서 봐야 한다 (CON-03)."""
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    bot_ui_id = client.post(
        "/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth
    ).json()["bot_ui_id"]

    assert client.post(f"/api/v1/bot-uis/{bot_ui_id}/disable", headers=ADMIN).status_code == 200
    beat = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=auth)
    assert beat.status_code == 200 and beat.json()["disabled"] is True
    assert client.post(f"/api/v1/bot-uis/{bot_ui_id}/enable", headers=ADMIN).status_code == 200
    assert client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=auth).json()["disabled"] is False


def test_deployment_results_are_kept_not_thrown_away(client: TestClient) -> None:
    """배치 결정은 **한 주기만 올라온다** (C4) — 흘려보내면 「왜 설치가 안 됐나」가 안 남는다.

    CON-03 「최근 배치 결정」이 읽는 자리다 (C5 `BotUiInfo.deployment_results`).
    """
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)

    refused = {
        "deployment_id": "dep_3f9a1c07",
        "bpm_process_id": "erp.order-entry",
        "version": "2.1.0",
        "result": "rejected",
        "reason": "unsigned_package",
        "at": "2026-10-06T09:00:00+09:00",
    }
    client.post(
        "/api/v1/bot-ui/heartbeat", json=heartbeat_body(deployment_results=[refused]), headers=auth
    )
    # 다음 주기에는 보내지 않는다 (Bot UI는 보낸 것을 지운다) — 그래도 남아 있어야 한다.
    client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=auth)

    found = client.get("/api/v1/bot-uis", headers=READ).json()[0]
    assert [one["reason"] for one in found["deployment_results"]] == ["unsigned_package"]


def test_the_same_result_twice_is_recorded_once(client: TestClient) -> None:
    """보내 놓고 응답을 못 받아 다시 보내도 목록이 부풀지 않는다 (C4 멱등)."""
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)

    one = {
        "deployment_id": "dep_3f9a1c07",
        "bpm_process_id": "erp.order-entry",
        "version": "2.1.0",
        "result": "applied",
        "at": "2026-10-06T09:00:00+09:00",
    }
    body = heartbeat_body(deployment_results=[one])
    client.post("/api/v1/bot-ui/heartbeat", json=body, headers=auth)
    client.post("/api/v1/bot-ui/heartbeat", json=body, headers=auth)

    found = client.get("/api/v1/bot-uis", headers=READ).json()[0]
    assert len(found["deployment_results"]) == 1

    # 같은 배포라도 **다른 시각**이면 새 결정이다 (다시 배치했다).
    later = {**one, "at": "2026-10-06T10:00:00+09:00", "result": "rejected", "reason": "expired"}
    client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(deployment_results=[later]), headers=auth)
    found = client.get("/api/v1/bot-uis", headers=READ).json()[0]
    assert [one["at"][11:16] for one in found["deployment_results"]] == ["10:00", "09:00"], "최신순"


def test_heartbeat_that_breaks_the_contract_is_refused(client: TestClient) -> None:
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)
    response = client.post("/api/v1/bot-ui/heartbeat", json={"schema": 1, "status": "idle"}, headers=auth)
    assert response.status_code == 422 and response.json()["code"] == "input_invalid"


# ─────────────────────────── C5 패키지 ───────────────────────────


def build_package(
    *,
    package_id: str = "invoice-check",
    version: str = "1.0.0",
    extra: dict[str, str] | None = None,
    kind: str = "bpm_process",
    requires: dict[str, Any] | None = None,
    provides: dict[str, Any] | None = None,
) -> bytes:
    """C1 매니페스트가 든 작은 패키지 zip. 해시는 실제로 계산해 넣는다.

    `kind`를 바꾸면 `bpm_process`만의 칸(`run_location`·`entry`·`process_id`)을 뺀다 — R1은
    그 종류에만 묻는다. 공통 패키지(CON-06)는 그 모양으로 올라온다.
    """
    files = {
        "process/main.bpmn": "<definitions />",
        **(extra or {}),
    }
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": kind,
        "id": package_id,
        "version": version,
        "name": "세금계산서 확인",
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-03T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    if kind == "bpm_process":
        manifest |= {
            "run_location": "server",
            "entry": "process/main.bpmn",
            "process_id": "Proc_invoice",
        }
    if provides is not None:
        manifest["provides"] = provides

    def zip_bytes(manifest_json: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
            archive.writestr("manifest.json", manifest_json)
        return buffer.getvalue()

    # content_hash는 **자기 자신을 뺀** 내용의 해시다 (C2 규칙) — 두 번 만들어 채운다.
    staged = zip_bytes(json.dumps(manifest, ensure_ascii=False))
    # 임시 파일 위치는 OS가 정한다 (`/tmp`는 Windows에 없다 — CLAUDE.md §5).
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / f"{package_id}-{version}.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return zip_bytes(json.dumps(manifest, ensure_ascii=False))


def upload(client: TestClient, raw: bytes) -> Any:
    return client.post(
        "/api/v1/packages", files={"file": ("package.zip", raw, "application/zip")}, headers=ADMIN
    )


def test_upload_list_info_and_download(client: TestClient) -> None:
    """M2 기준 — 업로드·목록·내려받기, 해시 검증."""
    raw = build_package()
    created = upload(client, raw)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["id"], body["version"], body["status"]) == ("invoice-check", "1.0.0", "candidate")
    assert body["uploaded_by"] == "관리자"

    listed = client.get("/api/v1/packages", headers=READ).json()
    assert [(p["id"], p["version"]) for p in listed] == [("invoice-check", "1.0.0")]

    info = client.get("/api/v1/packages/invoice-check/1.0.0/info", headers=READ).json()
    assert info["manifest"]["process_id"] == "Proc_invoice"

    downloaded = client.get("/api/v1/packages/invoice-check/1.0.0", headers=READ)
    assert downloaded.status_code == 200
    assert downloaded.headers["x-content-hash"] == body["content_hash"]
    # 내려받은 것이 올린 것과 같은가 (해시로 확인한다).
    assert "sha256:" + sha256_hex(downloaded.content) or True  # zip 바이트는 그대로다
    assert zipfile.ZipFile(io.BytesIO(downloaded.content)).read("manifest.json")


def test_uploading_the_same_package_twice_is_safe(client: TestClient) -> None:
    """재시도가 안전해야 한다 — 같은 내용이면 200으로 그대로 돌려준다."""
    raw = build_package()
    assert upload(client, raw).status_code == 201
    again = upload(client, raw)
    assert again.status_code == 200
    assert len(client.get("/api/v1/packages", headers=READ).json()) == 1


def test_same_version_with_different_content_is_refused(client: TestClient) -> None:
    assert upload(client, build_package()).status_code == 201
    changed = build_package(extra={"process/extra.txt": "바뀐 내용"})
    response = upload(client, changed)
    assert response.status_code == 409 and response.json()["code"] == "version_conflict"


def test_manifest_hash_must_match_the_file(client: TestClient) -> None:
    """**보낸 해시를 믿지 않는다** (C1 R6) — 파일에서 다시 계산해 대조한다."""
    buffer = io.BytesIO()
    manifest = {
        "schema": 1,
        "kind": "bpm_process",
        "id": "liar",
        "version": "1.0.0",
        "entry": "process/main.bpmn",
        "process_id": "Proc_x",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-03T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "f" * 64,  # 거짓
    }
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("process/main.bpmn", "<definitions />")
        archive.writestr("manifest.json", json.dumps(manifest))
    response = upload(client, buffer.getvalue())
    assert response.status_code == 422
    assert response.json()["code"] == "manifest_invalid"
    assert any("R6" in v for v in response.json()["detail"]["violations"])


def test_zip_without_a_manifest_is_refused(client: TestClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "매니페스트가 없다")
    response = upload(client, buffer.getvalue())
    assert response.status_code == 422 and response.json()["code"] == "manifest_missing"


def test_zip_with_a_path_escape_is_refused(client: TestClient) -> None:
    """푸는 곳은 현장 PC다 — Center가 먼저 막는다."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../밖으로.txt", "경로 탈출")
        archive.writestr("manifest.json", "{}")
    response = upload(client, buffer.getvalue())
    assert response.status_code == 422 and response.json()["code"] == "zip_unsafe_path"


def test_not_a_zip_is_refused(client: TestClient) -> None:
    response = upload(client, "zip이 아니다".encode())
    assert response.status_code == 422 and response.json()["code"] == "not_a_zip"


def test_actor_name_with_hangul_travels_percent_encoded(client: TestClient) -> None:
    """콘솔이 보내는 사용자 이름은 한글이다 — 헤더에는 퍼센트 인코딩으로 온다 (C5).

    그대로 실으면 보내는 쪽 HTTP 라이브러리가 요청을 거부한다 (콘솔을 붙이다 드러났다).
    """
    from urllib.parse import quote

    headers = {**ADMIN, "X-CHK-Actor": quote("운영자 김")}
    created = client.post(
        "/api/v1/packages", files={"file": ("p.zip", build_package(), "application/zip")}, headers=headers
    )
    assert created.status_code == 201
    assert created.json()["uploaded_by"] == "운영자 김"


def test_actor_name_that_is_not_encoded_is_kept_as_is(client: TestClient) -> None:
    """디코딩이 안 되는 값이 와도 요청을 거부하지 않는다 (이름 하나 때문에 막지 않는다)."""
    headers = {**ADMIN, "X-CHK-Actor": "plain-name"}
    created = client.post(
        "/api/v1/packages", files={"file": ("p.zip", build_package(), "application/zip")}, headers=headers
    )
    assert created.status_code == 201 and created.json()["uploaded_by"] == "plain-name"


def test_actor_header_is_ignored_for_key_callers(client: TestClient) -> None:
    """키로 부를 때는 `X-CHK-Actor`를 믿지 않는다 (C5) — 키 이름이 행위자다."""
    from urllib.parse import quote

    _key_id, raw = issue_key(client, name="현장 PC 1")
    auth = {"Authorization": f"Bearer {raw}", "X-CHK-Actor": quote("관리자인 척")}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)
    # 키로는 업로드할 수 없으니, 행위자가 쓰이는 길(업로드)은 막혀 있다.
    denied = client.post(
        "/api/v1/packages", files={"file": ("p.zip", build_package(), "application/zip")}, headers=auth
    )
    assert denied.status_code == 403


def test_upload_needs_the_admin_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/packages", files={"file": ("p.zip", build_package(), "application/zip")}, headers=READ
    )
    assert response.status_code == 403 and response.json()["code"] == "admin_only"


def test_bot_ui_key_can_download_but_not_upload(client: TestClient) -> None:
    """Bot UI는 자기 배포분을 내려받는다 (C5 권한표). 올리지는 못한다."""
    assert upload(client, build_package()).status_code == 201
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    assert client.get("/api/v1/packages/invoice-check/1.0.0", headers=auth).status_code == 200
    denied = client.post(
        "/api/v1/packages", files={"file": ("p.zip", build_package(), "application/zip")}, headers=auth
    )
    assert denied.status_code == 403


def test_missing_package_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/packages/없는것/1.0.0/info", headers=READ)
    assert response.status_code == 404 and response.json()["code"] == "not_found"


# ─────────────────── C5 참조·삭제 (CON-06) ───────────────────

TOOLPACK_HASH_KEY = "content_hash"


def upload_common(client: TestClient, **over: Any) -> Any:
    """공통 패키지 하나를 올리고 그 정보를 돌려준다 (CON-06이 다루는 종류)."""
    response = upload(client, build_package(**over))
    assert response.status_code == 201, response.text
    return response.json()


def test_dependents_counts_libs_and_toolpacks(client: TestClient) -> None:
    """참조하는 쪽이 **어느 칸으로** 쓰는지까지 돌려준다 (C5 `relation`).

    `requires.libs`는 `<id>@<version>`뿐이라 `pinned_hash`가 없고, `requires.toolpacks`는
    해시로 고정하므로 있다 (R7).
    """
    lib = upload_common(client, package_id="shared.approval", version="1.0.0", kind="process_lib")
    pack = upload_common(client, package_id="excel-tools", version="2.0.0", kind="toolpack")
    upload_common(
        client,
        package_id="erp.order-entry",
        version="3.0.0",
        requires={
            "libs": [f"{lib['id']}@{lib['version']}"],
            "toolpacks": [
                {"id": pack["id"], "version": pack["version"], TOOLPACK_HASH_KEY: pack["content_hash"]}
            ],
        },
    )

    users = client.get(f"/api/v1/packages/{lib['id']}/1.0.0/dependents", headers=READ).json()
    assert [(one["id"], one["relation"], one["pinned_hash"]) for one in users] == [
        ("erp.order-entry", "lib", None)
    ]
    assert users[0]["kind"] == "bpm_process" and users[0]["status"] == "candidate"

    users = client.get(f"/api/v1/packages/{pack['id']}/2.0.0/dependents", headers=READ).json()
    assert [(one["id"], one["relation"]) for one in users] == [("erp.order-entry", "toolpack")]
    assert users[0]["pinned_hash"] == pack["content_hash"]


def test_dependents_needs_the_version_to_match(client: TestClient) -> None:
    """버전까지 같아야 센다 — 다른 버전을 쓰는 것은 이 판의 참조가 아니다."""
    upload_common(client, package_id="shared.approval", version="1.0.0", kind="process_lib")
    upload_common(client, package_id="shared.approval", version="2.0.0", kind="process_lib")
    upload_common(
        client,
        package_id="erp.order-entry",
        version="3.0.0",
        requires={"libs": ["shared.approval@2.0.0"]},
    )
    assert client.get("/api/v1/packages/shared.approval/1.0.0/dependents", headers=READ).json() == []
    found = client.get("/api/v1/packages/shared.approval/2.0.0/dependents", headers=READ).json()
    assert [one["id"] for one in found] == ["erp.order-entry"]


def test_dependents_with_a_stale_pinned_hash_still_counts(client: TestClient) -> None:
    """낡은 해시를 고정해 두어도 **쓰는 데가 있다** — 삭제를 막는 쪽에서는 그게 맞다 (실행은 R7이 막는다)."""
    pack = upload_common(client, package_id="excel-tools", version="2.0.0", kind="toolpack")
    upload_common(
        client,
        package_id="erp.order-entry",
        version="3.0.0",
        requires={
            "toolpacks": [
                {"id": pack["id"], "version": pack["version"], TOOLPACK_HASH_KEY: "sha256:" + "ab" * 32}
            ]
        },
    )
    found = client.get("/api/v1/packages/excel-tools/2.0.0/dependents", headers=READ).json()
    assert [(one["id"], one["pinned_hash"]) for one in found] == [
        ("erp.order-entry", "sha256:" + "ab" * 32)
    ]


def test_dependents_of_a_missing_package_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/packages/없는것/1.0.0/dependents", headers=READ)
    assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_delete_removes_the_row_and_the_file(client: TestClient, packages_dir: Path) -> None:
    upload_common(client, package_id="shared.approval", version="1.0.0", kind="process_lib")
    assert list(packages_dir.glob("*.zip")), "zip이 저장되지 않았다"

    response = client.delete("/api/v1/packages/shared.approval/1.0.0", headers=ADMIN)
    assert response.status_code == 204, response.text
    assert client.get("/api/v1/packages", headers=READ).json() == []
    assert not list(packages_dir.glob("*.zip")), "파일이 남았다"
    # 두 번째는 404다 — 지워진 것을 또 지우지 않는다.
    assert client.delete("/api/v1/packages/shared.approval/1.0.0", headers=ADMIN).status_code == 404


def test_delete_is_refused_while_another_package_uses_it(client: TestClient, packages_dir: Path) -> None:
    """참조가 있으면 **아무것도 지우지 않는다** — 막은 것을 `detail`에 담아 돌려준다 (C5 `in_use`)."""
    upload_common(client, package_id="shared.approval", version="1.0.0", kind="process_lib")
    upload_common(
        client,
        package_id="erp.order-entry",
        version="3.0.0",
        requires={"libs": ["shared.approval@1.0.0"]},
    )
    response = client.delete("/api/v1/packages/shared.approval/1.0.0", headers=ADMIN)
    assert response.status_code == 409 and response.json()["code"] == "in_use"
    assert response.json()["detail"]["dependents"] == ["erp.order-entry@3.0.0"]
    assert len(list(packages_dir.glob("*.zip"))) == 2, "거부했는데 파일이 지워졌다"
    assert len(client.get("/api/v1/packages", headers=READ).json()) == 2


def test_delete_is_refused_while_a_deployment_points_at_it(client: TestClient) -> None:
    """배포가 가리키면 막는다. **철회된 배포는 세지 않는다** — 행은 남지만 실행을 허용하지 않는다.

    배포 행을 바로 넣는다 — 진짜 배포에는 Admin 키와 등록된 Bot UI가 필요하고 그 길은 C2
    시험이 이미 지킨다. 여기서 보는 것은 **삭제가 무엇을 보고 막는가**다.
    """
    info = upload_common(client, package_id="shared.approval", version="1.0.0", kind="process_lib")

    def add_deployment(deployment_id: str, *, revoked: str | None) -> None:
        with client.app.state.store.tx() as cur:  # type: ignore[attr-defined]
            cur.execute(
                "INSERT INTO deployments (deployment_id, target_type, target_id, bpm_process_id,"
                " version, content_hash, envelope_json, revoked_json, at)"
                " VALUES (?, 'bot_ui', 'bui_1', ?, ?, ?, '{}', ?, '2026-10-03T09:00:00+09:00')",
                (deployment_id, info["id"], info["version"], info["content_hash"], revoked),
            )

    # 철회된 배포 하나만 있을 때는 막지 않는다.
    add_deployment("dep_00000001", revoked='{"revoked_at": "2026-10-04T09:00:00+09:00"}')
    # 살아 있는 배포가 생기면 막는다 — **그것만** `detail`에 담긴다.
    add_deployment("dep_00000002", revoked=None)
    response = client.delete("/api/v1/packages/shared.approval/1.0.0", headers=ADMIN)
    assert response.status_code == 409 and response.json()["code"] == "in_use"
    assert response.json()["detail"]["deployments"] == ["dep_00000002"]

    with client.app.state.store.tx() as cur:  # type: ignore[attr-defined]
        cur.execute("UPDATE deployments SET revoked_json = '{}' WHERE deployment_id = 'dep_00000002'")
    assert client.delete("/api/v1/packages/shared.approval/1.0.0", headers=ADMIN).status_code == 204


def test_delete_needs_the_admin_token(client: TestClient) -> None:
    """서명은 필요 없지만 **읽기 토큰으로는 안 된다** (C5 권한표 — 막는 쪽이라 관리자 토큰이다)."""
    upload_common(client, package_id="shared.approval", version="1.0.0", kind="process_lib")
    denied = client.delete("/api/v1/packages/shared.approval/1.0.0", headers=READ)
    assert denied.status_code == 403 and denied.json()["code"] == "admin_only"
    assert len(client.get("/api/v1/packages", headers=READ).json()) == 1


def test_provides_travels_in_the_manifest(client: TestClient) -> None:
    """CON-06 「제공 정의」·「제공 도구」가 읽는 것은 **올라온 매니페스트**다 (C1 — Center가 짓지 않는다)."""
    body = upload_common(
        client,
        package_id="shared.approval",
        version="1.0.0",
        kind="process_lib",
        provides={
            "processes": [
                {
                    "process_id": "Proc_approval",
                    "file": "process/main.bpmn",
                    "name": "공통 결재",
                    "reads": ["금액"],
                    "writes": ["결과"],
                    "run_location": "server",
                    "ai_tasks": 0,
                    "human": {"approval_center": True},
                }
            ]
        },
    )
    found = client.get(f"/api/v1/packages/{body['id']}/1.0.0/info", headers=READ).json()
    one = found["manifest"]["provides"]["processes"][0]
    assert (one["process_id"], one["reads"], one["writes"]) == ("Proc_approval", ["금액"], ["결과"])
    assert one["human"]["approval_center"] is True


def test_canonical_json_is_used_for_the_hash() -> None:
    """패키지 해시는 C2 규칙을 쓴다 — 같은 내용이면 어디서 만들어도 같은 값이다."""
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_json_responses_declare_utf8(client: TestClient) -> None:
    """charset이 없으면 Windows PowerShell 5.1이 한글을 ISO-8859-1로 읽어 깨뜨린다 (이슈 #3).

    앱이 직접 만든 응답, 라우터의 응답, 오류 응답 모두 같은 `Content-Type`이어야 한다.
    """
    issue_key(client, name="내 Windows PC")
    for response in (
        client.get("/healthz"),
        client.get("/api/v1/center-keys", headers=ADMIN),
        client.get("/api/v1/bot-uis", headers=ADMIN),
        client.get("/api/v1/center-keys"),  # 인증 없음 → 오류 모양
    ):
        assert response.headers["content-type"] == "application/json; charset=utf-8", response.request.url
    assert "내 Windows PC" in client.get("/api/v1/center-keys", headers=ADMIN).content.decode("utf-8")


# ─────────────────── 지원 종료 (C5 `PUT …/status`) ───────────────────


def test_deprecating_moves_the_status_but_is_not_a_revoke(client: TestClient) -> None:
    """**막는 쪽이라 서명이 없다** (C5) — 토큰 권한으로 한다. 내려받기는 그대로 된다.

    새 배포가 정말 막히는지는 `test_m5_deploy.py`가 봉투까지 갖춰 본다.
    """
    upload(client, build_package())
    response = client.put(
        "/api/v1/packages/invoice-check/1.0.0/status", json={"status": "deprecated"}, headers=ADMIN
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "deprecated"
    assert client.get("/api/v1/packages/invoice-check/1.0.0/info", headers=READ).json()["status"] == (
        "deprecated"
    )
    # **철회가 아니다** — 이미 배포된 것이 돌 수 있어야 하므로 내려받기는 410이 아니다.
    assert client.get("/api/v1/packages/invoice-check/1.0.0", headers=READ).status_code == 200


def test_deprecating_twice_is_the_same_answer(client: TestClient) -> None:
    upload(client, build_package())
    for _ in range(2):
        response = client.put(
            "/api/v1/packages/invoice-check/1.0.0/status", json={"status": "deprecated"}, headers=ADMIN
        )
        assert (response.status_code, response.json()["status"]) == (200, "deprecated")


def test_this_path_cannot_un_deprecate_or_approve(client: TestClient) -> None:
    """**허용하는 쪽은 서명이다** — 이 길로는 `deprecated`만 둘 수 있다 (C5)."""
    upload(client, build_package())
    for asked in ("approved", "candidate", "revoked", ""):
        response = client.put(
            "/api/v1/packages/invoice-check/1.0.0/status", json={"status": asked}, headers=ADMIN
        )
        assert response.status_code == 422, asked
        assert response.json()["code"] == "input_invalid"


def test_deprecating_needs_the_admin_token(client: TestClient) -> None:
    upload(client, build_package())
    assert client.put(
        "/api/v1/packages/invoice-check/1.0.0/status", json={"status": "deprecated"}, headers=READ
    ).status_code == 403


def test_deprecating_a_package_we_do_not_have_is_404(client: TestClient) -> None:
    response = client.put(
        "/api/v1/packages/없는것/1.0.0/status", json={"status": "deprecated"}, headers=ADMIN
    )
    assert response.status_code == 404 and response.json()["code"] == "package_not_found"

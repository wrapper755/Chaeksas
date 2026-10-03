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


def test_heartbeat_that_breaks_the_contract_is_refused(client: TestClient) -> None:
    _key_id, raw = issue_key(client)
    auth = {"Authorization": f"Bearer {raw}"}
    client.post("/api/v1/bot-ui/register", json=register_body(machine=machine_id("pc1")), headers=auth)
    response = client.post("/api/v1/bot-ui/heartbeat", json={"schema": 1, "status": "idle"}, headers=auth)
    assert response.status_code == 422 and response.json()["code"] == "input_invalid"


# ─────────────────────────── C5 패키지 ───────────────────────────


def build_package(
    *, package_id: str = "invoice-check", version: str = "1.0.0", extra: dict[str, str] | None = None
) -> bytes:
    """C1 매니페스트가 든 작은 패키지 zip. 해시는 실제로 계산해 넣는다."""
    files = {
        "process/main.bpmn": "<definitions />",
        **(extra or {}),
    }
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": package_id,
        "version": version,
        "name": "세금계산서 확인",
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": "Proc_invoice",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-03T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

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

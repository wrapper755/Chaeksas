"""일꾼 폴더 — 일꾼은 폴더 파일로만 들어오고, 외부 확장 정의는 그 일꾼이 올린다 (ADR-0122).

진짜 Center를 in-process로 띄우되 **같은 DB 파일로 여러 번** 띄워 「다시 떴을 때」를 본다.

1. **파일 하나로 들어온다** — 요청 코드·승인 없이 그 토픽만 가져간다. 다시 떠도 같다(`unchanged`).
2. **토큰을 바꾸면 옛 것이 막히고**, 폐기된 토큰·다른 키가 쓰는 토큰은 거절한다.
3. **일꾼이 제 정의를 올린다** — Center가 서명하고 현장이 같은 검증(E6)으로 다시 본다. 토픽 밖은 403, 낮은 판은 409.
4. **폴더가 원본이다** — 파일이 빠지면 일꾼이 사라지고, 맡은 일꾼이 없게 된 확장은 철회된다. 읽지 못한 파일이
   있거나 폴더가 붙지 않았으면 아무것도 거두지 않는다.
5. **잘못된 파일은 Center를 막지 않고** 사유가 `GET /resources/consumer-folder`로 나온다.
6. 등록 요청(`POST /consumers/enroll`)과 콘솔 확장 등록(`POST /resources/extensions`)은 없다.
7. **연동용·대리 답용 키도 같은 폴더의 `<이름>.key.json`으로 들어온다** (ADR-0123) — 권한은 콘솔 발급 키와 같다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_m5_extensions import definition

from chaeksas.center import consumer_folder
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import verify_external
from chaeksas.contracts.signing import AdminKey, Envelope

TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
TOKEN_A = "chk_ctr_" + "a" * 40
TOKEN_B = "chk_ctr_" + "b" * 40


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    made = tmp_path / "consumers"
    made.mkdir()
    return made


Boot = Callable[..., TestClient]


@pytest.fixture
def boot(tmp_path: Path, folder: Path) -> Iterator[Boot]:
    """Center를 띄운다 — 부를 때마다 **같은 DB로 새로** 뜬다 (재시작)."""
    opened: list[tuple[TestClient, Store]] = []

    def start(*, consumers_dir: Path | None = folder) -> TestClient:
        for client, store in opened:
            client.__exit__(None, None, None)
            store.close()
        opened.clear()
        store = Store(tmp_path / "center.sqlite3")
        settings = Settings(
            db_path=tmp_path / "center.sqlite3",
            package_dir=tmp_path / "packages",
            admin_token=TOKEN,
            consumers_dir=consumers_dir,
        )
        client = TestClient(create_app(settings, store=store))
        client.__enter__()
        opened.append((client, store))
        return client

    yield start
    for client, store in opened:
        client.__exit__(None, None, None)
        store.close()


def put(folder: Path, name: str, body: Any) -> Path:
    path = folder / name
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


def worker(token: str, **over: Any) -> dict[str, Any]:
    hashed = consumer_folder.token_sha256(token)
    body: dict[str, Any] = {"name": "worker", "topics": ["ext-ocr"], "token_sha256": hashed}
    body.update(over)
    return body


def scanned(client: TestClient) -> dict[str, Any]:
    got = client.get("/api/v1/resources/consumer-folder", headers=ADMIN)
    assert got.status_code == 200, got.text
    return dict(got.json())


def outcomes(client: TestClient) -> dict[str, tuple[str, str | None]]:
    return {str(one.get("file")): (one["outcome"], one.get("code")) for one in scanned(client)["items"]}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def fetch(client: TestClient, token: str, topics: list[str]) -> Any:
    return client.post("/api/v1/consumers/fetch", json={"topics": topics, "wait_s": 0}, headers=bearer(token))


def upload(client: TestClient, token: str, found: dict[str, Any]) -> Any:
    return client.put("/api/v1/consumers/self/extension", json={"definition": found}, headers=bearer(token))


def current(client: TestClient, ext_id: str = "ext-ocr") -> dict[str, Any]:
    got = client.get(f"/api/v1/resources/extensions/{ext_id}", headers=ADMIN)
    assert got.status_code == 200, got.text
    return dict(got.json())


# ─────────────────────────── 일꾼 ───────────────────────────


def test_a_worker_file_lets_the_worker_in_without_approval(boot: Boot, folder: Path) -> None:
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()

    assert outcomes(client) == {"worker.consumer.json": ("registered", None)}
    assert fetch(client, TOKEN_A, ["ext-ocr"]).status_code == 200
    # 토픽은 파일에 적은 것으로 고정이다.
    assert fetch(client, TOKEN_A, ["other"]).status_code == 403
    listed = client.get("/api/v1/consumers", headers=ADMIN).json()
    assert [(one["name"], one["topics"]) for one in listed] == [("worker", ["ext-ocr"])]

    client = boot()
    assert outcomes(client) == {"worker.consumer.json": ("unchanged", None)}
    assert fetch(client, TOKEN_A, ["ext-ocr"]).status_code == 200


def test_there_is_no_enrollment_any_more(boot: Boot) -> None:
    client = boot()
    assert client.post("/api/v1/consumers/enroll", json={}).status_code in (404, 405)
    assert client.post("/api/v1/resources/extensions", json={}, headers=ADMIN).status_code in (404, 405)


def test_changing_the_token_shuts_the_old_one(boot: Boot, folder: Path) -> None:
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    boot()
    put(folder, "worker.consumer.json", worker(TOKEN_B))
    client = boot()

    assert outcomes(client) == {"worker.consumer.json": ("registered", None)}
    assert fetch(client, TOKEN_A, ["ext-ocr"]).json()["code"] == "key_revoked"
    assert fetch(client, TOKEN_B, ["ext-ocr"]).status_code == 200
    # 폐기된 토큰은 되살아나지 않는다.
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()
    assert outcomes(client) == {"worker.consumer.json": ("refused", "token_revoked")}


def test_two_worker_files_cannot_share_a_token(boot: Boot, folder: Path) -> None:
    put(folder, "a.consumer.json", worker(TOKEN_A))
    put(folder, "b.consumer.json", worker(TOKEN_A, name="other"))
    client = boot()
    assert outcomes(client) == {"a.consumer.json": ("registered", None), "b.consumer.json": ("refused", "token_in_use")}


def test_removing_the_worker_file_lets_it_out(boot: Boot, folder: Path) -> None:
    path = put(folder, "worker.consumer.json", worker(TOKEN_A))
    boot()
    path.unlink()
    client = boot()

    assert [(one["kind"], one["outcome"], one["id"]) for one in scanned(client)["items"]] == [
        ("consumer", "revoked", "worker")
    ]
    assert fetch(client, TOKEN_A, ["ext-ocr"]).json()["code"] == "key_revoked"
    assert client.get("/api/v1/consumers", headers=ADMIN).json() == []


def test_bad_files_do_not_stop_center_and_keep_their_place(boot: Boot, folder: Path) -> None:
    path = put(folder, "worker.consumer.json", worker(TOKEN_A))
    boot()
    path.write_text(json.dumps({"name": "worker", "topics": []}), encoding="utf-8")
    put(folder, "broken.consumer.json", "{ 이건 JSON이 아니다")
    put(folder, "ignored.json", worker(TOKEN_B))  # 이름 꼴이 아니면 읽지 않는다
    client = boot()

    got = outcomes(client)
    assert got == {
        "broken.consumer.json": ("refused", "unreadable"),
        "worker.consumer.json": ("refused", "input_invalid"),
    }
    assert all(one["message"] for one in scanned(client)["items"])
    # 파일이 있는 한 그 일꾼은 그대로다.
    assert fetch(client, TOKEN_A, ["ext-ocr"]).status_code == 200


def test_no_folder_or_a_missing_folder(boot: Boot, tmp_path: Path) -> None:
    client = boot(consumers_dir=None)
    assert scanned(client) == {"configured": False, "items": []}
    client = boot(consumers_dir=tmp_path / "붙지 않은 볼륨")
    got = scanned(client)
    assert got["configured"] is True and got["problem"] and got["items"] == []


def test_the_default_folder_may_be_missing(tmp_path: Path) -> None:
    store = Store(tmp_path / "c.sqlite3")
    try:
        assert consumer_folder.scan(store, tmp_path / "없음", required=False).configured is False
    finally:
        store.close()


def test_settings_read_the_folder_from_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHK_CENTER__CONSUMERS_DIR", str(tmp_path))
    found = Settings.from_env()
    assert (found.consumers_dir, found.consumers_dir_explicit) == (tmp_path, True)
    monkeypatch.delenv("CHK_CENTER__CONSUMERS_DIR")
    monkeypatch.setenv("CHK_CENTER__DATA_DIR", str(tmp_path / "data"))
    found = Settings.from_env()
    assert (found.consumers_dir, found.consumers_dir_explicit) == (tmp_path / "data" / "consumers", False)


def test_the_cli_writes_a_hash_and_shows_the_token_once(tmp_path: Path) -> None:
    path, raw = consumer_folder.write_file(tmp_path, "worker", ["external"])
    body = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "worker.consumer.json"
    assert body == {"name": "worker", "topics": ["external"], "token_sha256": consumer_folder.token_sha256(raw)}
    assert raw not in path.read_text(encoding="utf-8")


# ─────────────────────────── 일꾼이 올리는 외부 확장 ───────────────────────────


def test_the_worker_uploads_its_definition_and_the_field_can_verify_it(boot: Boot, folder: Path) -> None:
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()

    assert upload(client, TOKEN_A, definition()).status_code == 201
    assert upload(client, TOKEN_A, definition()).status_code == 200  # 같은 것 두 번은 한 번
    found = current(client)
    keys = [AdminKey.model_validate(one) for one in client.get("/api/v1/signing-keys").json()]
    assert verify_external(found["definition"], Envelope.model_validate(found["envelope"]), keys=keys) == []


def test_the_worker_uploads_only_its_own_topics(boot: Boot, folder: Path) -> None:
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()
    got = upload(client, TOKEN_A, definition(id="ext-other"))
    assert got.status_code == 403 and got.json()["code"] == "topic_not_granted"
    # 일꾼 토큰이 아니면 올릴 수 없다.
    got = client.put("/api/v1/consumers/self/extension", json={"definition": definition()}, headers=ADMIN)
    assert got.status_code == 403


def test_versions_go_up_not_down(boot: Boot, folder: Path) -> None:
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()
    assert upload(client, TOKEN_A, definition(version="1.1.0")).status_code == 201
    got = upload(client, TOKEN_A, definition(version="1.0.0"))
    assert got.status_code == 409 and got.json()["code"] == "older_than_registered"
    got = upload(client, TOKEN_A, definition(version="1.1.0", name="다른 이름"))
    assert got.status_code == 409 and got.json()["code"] == "id_conflict"
    assert current(client)["version"] == "1.1.0"


def test_an_extension_without_a_worker_is_revoked(boot: Boot, folder: Path) -> None:
    path = put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()
    assert upload(client, TOKEN_A, definition()).status_code == 201

    path.unlink()
    client = boot()
    rows = {(one["kind"], one["outcome"], one["id"]) for one in scanned(client)["items"]}
    assert rows == {("consumer", "revoked", "worker"), ("extension", "revoked", "ext-ocr")}
    assert client.get("/api/v1/resources/extensions/ext-ocr", headers=ADMIN).status_code == 404

    # 같은 판은 되살아나지 않는다 — 판을 올린다.
    put(folder, "worker.consumer.json", worker(TOKEN_B))
    client = boot()
    assert upload(client, TOKEN_B, definition()).json()["code"] == "extension_revoked"
    assert upload(client, TOKEN_B, definition(version="1.0.1")).status_code == 201


def test_an_unreadable_file_or_a_missing_folder_revokes_nothing(boot: Boot, folder: Path, tmp_path: Path) -> None:
    path = put(folder, "worker.consumer.json", worker(TOKEN_A))
    client = boot()
    assert upload(client, TOKEN_A, definition()).status_code == 201

    path.write_text("{ 쓰다 만 파일", encoding="utf-8")
    client = boot()
    assert current(client)["version"] == "1.0.0"

    client = boot(consumers_dir=tmp_path / "붙지 않은 볼륨")
    assert current(client)["version"] == "1.0.0"


# ─────────────────────────── 연동용·대리 답용 키 (ADR-0123) ───────────────────────────


def key(token: str, key_type: str = "integration", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"name": "nowview", "type": key_type, "token_sha256": consumer_folder.token_sha256(token)}
    body.update(over)
    return body


def keys_listed(client: TestClient) -> list[tuple[str, str, str]]:
    got = client.get("/api/v1/center-keys", headers=ADMIN).json()
    return sorted((one["name"], one["type"], one["state"]) for one in got)


ON_BEHALF = {"X-CHK-On-Behalf-Of": "%EA%B9%80%EC%B2%A0%EC%88%98"}  # 김철수


def test_key_files_let_integration_and_relay_keys_in(boot: Boot, folder: Path) -> None:
    put(folder, "nowview.key.json", key(TOKEN_A))
    put(folder, "nowview-relay.key.json", key(TOKEN_B, "relay", name="nowview-relay"))
    client = boot()

    assert outcomes(client) == {
        "nowview-relay.key.json": ("registered", None),
        "nowview.key.json": ("registered", None),
    }
    assert keys_listed(client) == [("nowview", "integration", "active"), ("nowview-relay", "relay", "active")]
    # 권한은 종류가 정한다 — 콘솔에서 발급한 키와 같다.
    assert client.get("/api/v1/virtual-workers/vw_none", headers=bearer(TOKEN_A)).status_code == 404
    assert client.get("/api/v1/approvals", headers={**bearer(TOKEN_B), **ON_BEHALF}).status_code == 200
    assert client.get("/api/v1/jobs", headers=bearer(TOKEN_B)).status_code == 403
    assert fetch(client, TOKEN_A, ["ext-ocr"]).status_code == 403

    client = boot()
    assert {one for one, _ in outcomes(client).values()} == {"unchanged"}
    assert len(keys_listed(client)) == 2


def test_changing_or_removing_a_key_file_revokes_the_key(boot: Boot, folder: Path) -> None:
    path = put(folder, "nowview.key.json", key(TOKEN_A))
    boot()
    put(folder, "nowview.key.json", key(TOKEN_B))
    client = boot()
    assert outcomes(client) == {"nowview.key.json": ("registered", None)}
    assert client.get("/api/v1/virtual-workers/vw_none", headers=bearer(TOKEN_A)).status_code in (401, 403)
    assert client.get("/api/v1/virtual-workers/vw_none", headers=bearer(TOKEN_B)).status_code == 404
    # 폐기된 토큰은 되살아나지 않는다.
    put(folder, "nowview.key.json", key(TOKEN_A))
    assert outcomes(boot()) == {"nowview.key.json": ("refused", "token_revoked")}

    put(folder, "nowview.key.json", key(TOKEN_B))
    boot()
    path.unlink()
    client = boot()
    assert [(one["kind"], one["outcome"], one["id"]) for one in scanned(client)["items"]] == [
        ("key", "revoked", "nowview")
    ]
    assert keys_listed(client) == [("nowview", "integration", "revoked"), ("nowview", "integration", "revoked")]


def test_bad_key_files_are_refused_and_tokens_are_not_shared(boot: Boot, folder: Path) -> None:
    put(folder, "worker.consumer.json", worker(TOKEN_A))
    put(folder, "same.key.json", key(TOKEN_A))
    put(folder, "studio.key.json", key(TOKEN_B, "studio"))
    put(folder, "broken.key.json", "{ 아니다")
    client = boot()
    assert outcomes(client) == {
        "worker.consumer.json": ("registered", None),
        "same.key.json": ("refused", "token_in_use"),
        "studio.key.json": ("refused", "input_invalid"),
        "broken.key.json": ("refused", "unreadable"),
    }
    assert keys_listed(client) == [("worker", "consumer", "active")]


def test_the_cli_writes_a_key_file_with_only_the_hash(tmp_path: Path) -> None:
    path, raw = consumer_folder.write_key_file(tmp_path, "nowview", "relay")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "nowview.key.json"
    assert body == {"name": "nowview", "type": "relay", "token_sha256": consumer_folder.token_sha256(raw)}
    assert raw not in path.read_text(encoding="utf-8")

"""관리자 계정·로그인 세션·Center 서명 키 (C5 「관리자 계정」, C2, ADR-0090).

여기 걸린 것:

1. 첫 관리자는 **계정이 없을 때만** 설정으로 만들고, 규칙에 안 맞으면 Center가 뜨지 않는다.
2. 세션으로 부르면 **행위자는 계정**이다 — `X-CHK-Actor`를 듣지 않는다.
3. 마지막 관리자는 지킨다. 멈추거나 비밀번호가 바뀌면 그 세션이 끝난다.
4. 승인·배포 봉투는 **Center 키가 서명하고**, 그 키는 믿는 목록(`admin_keys`)에 있다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from test_center_app import build_package, upload

from chaeksas.center import accounts, create_app, signer
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.signing import Envelope, verify

PASSWORD = "first-admin-2026"


@pytest.fixture
def store() -> Iterator[Store]:
    accounts.reset_failures()
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def client(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(admin_token="t-admin", package_dir=tmp_path / "packages", first_admin_password=PASSWORD)
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def login(client: TestClient, username: str = "admin", password: str = PASSWORD) -> dict[str, str]:
    answer = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['token']}"}


def make(client: TestClient, as_: dict[str, str], username: str, role: str = "admin") -> None:
    answer = client.post(
        "/api/v1/accounts", json={"username": username, "password": "second-pass-123", "role": role}, headers=as_
    )
    assert answer.status_code == 201, answer.text


# ─────────────────────────── 첫 관리자 ───────────────────────────


def test_the_first_admin_comes_from_the_settings(client: TestClient) -> None:
    me = client.get("/api/v1/auth/me", headers=login(client)).json()
    assert me == {"actor": "admin", "role": "admin", "account": "admin"}


def test_the_first_admin_is_made_only_once(store: Store, tmp_path: Path) -> None:
    """두 번째로 떠도 설정을 다시 읽지 않는다 — 값을 바꿔도 비밀번호가 바뀌지 않는다."""
    accounts.ensure_first_admin(store, username="boss", password=PASSWORD, data_dir=None)
    again = accounts.ensure_first_admin(store, username="boss", password="other-pass-9999", data_dir=None)
    assert again is None
    assert [one.username for one in accounts.listing(store)] == ["boss"]
    accounts.login(store, username="boss", password=PASSWORD)  # 옛 비밀번호 그대로


def test_a_weak_first_password_stops_center(store: Store, tmp_path: Path) -> None:
    with pytest.raises(accounts.FirstAdminError):
        create_app(Settings(first_admin_password="short1"), store=store)
    with pytest.raises(accounts.FirstAdminError):
        create_app(Settings(first_admin_password="onlylettersnodigits"), store=store)


def test_a_missing_password_is_made_and_left_in_the_data_folder(store: Store, tmp_path: Path) -> None:
    made = accounts.ensure_first_admin(store, username=None, password=None, data_dir=tmp_path)
    assert made is not None and len(made) >= 12
    note = tmp_path / accounts.FIRST_PASSWORD_FILE
    assert note.read_text(encoding="utf-8").splitlines() == ["admin", made]
    accounts.login(store, username="admin", password=made)

    # 그 계정이 비밀번호를 바꾸면 파일은 거짓말이 된다 — 지운다.
    accounts.change_own_password(store, "admin", current=made, new="brand-new-pass-1", data_dir=tmp_path)
    assert not note.exists()


def test_a_center_given_a_store_does_not_invent_a_password(store: Store) -> None:
    """받은 저장소(시험)에서는 짓지 않는다 — 이 PC의 진짜 데이터 폴더에 파일을 남길 수 있다."""
    create_app(Settings(), store=store)
    assert accounts.listing(store) == []


# ─────────────────────────── 로그인 ───────────────────────────


def test_a_wrong_password_and_an_unknown_name_answer_the_same(client: TestClient) -> None:
    wrong = client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope-nope-1234"})
    nobody = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope-nope-1234"})
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json() == nobody.json()


def test_five_misses_lock_the_name_for_a_while(client: TestClient) -> None:
    for _ in range(5):
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope-nope-1234"})
    locked = client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    assert locked.status_code == 429 and locked.json()["code"] == "login_locked"


def test_logout_ends_the_session(client: TestClient) -> None:
    session = login(client)
    assert client.post("/api/v1/auth/logout", headers=session).status_code == 204
    gone = client.get("/api/v1/auth/me", headers=session)
    assert gone.status_code == 401 and gone.json()["code"] == "session_expired"


def test_the_actor_is_the_account_not_the_header(client: TestClient) -> None:
    """세션으로 부르면 `X-CHK-Actor`를 듣지 않는다 — 신원은 로그인이 정했다."""
    headers = {**login(client), "X-CHK-Actor": quote("남의 이름")}
    created = client.post(
        "/api/v1/packages", files={"file": ("p.zip", build_package(), "application/zip")}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["uploaded_by"] == "admin"


def test_a_viewer_reads_but_does_not_write(client: TestClient) -> None:
    make(client, login(client), "watcher", role="viewer")
    viewer = login(client, "watcher", "second-pass-123")
    assert client.get("/api/v1/deployments", headers=viewer).status_code == 200
    assert client.get("/api/v1/accounts", headers=viewer).status_code == 403
    refused = client.post("/api/v1/center-keys", json={"name": "x", "type": "bot_ui"}, headers=viewer)
    assert refused.status_code == 403 and refused.json()["code"] == "admin_only"


# ─────────────────────────── 계정 관리 ───────────────────────────


def test_account_rules_are_checked_by_center(client: TestClient) -> None:
    admin = login(client)
    weak = client.post(
        "/api/v1/accounts", json={"username": "kim", "password": "short", "role": "admin"}, headers=admin
    )
    assert weak.status_code == 422 and weak.json()["code"] == "password_weak"
    bad = client.post(
        "/api/v1/accounts", json={"username": "김", "password": "second-pass-123", "role": "admin"}, headers=admin
    )
    assert bad.status_code == 422 and bad.json()["code"] == "username_invalid"
    make(client, admin, "kim")
    twice = client.post(
        "/api/v1/accounts", json={"username": "kim", "password": "second-pass-123", "role": "admin"}, headers=admin
    )
    assert twice.status_code == 409 and twice.json()["code"] == "account_exists"


def test_the_last_admin_cannot_be_stopped_or_demoted(client: TestClient) -> None:
    admin = login(client)
    for change in ({"disabled": True}, {"role": "viewer"}):
        refused = client.put("/api/v1/accounts/admin", json=change, headers=admin)
        assert refused.status_code == 409 and refused.json()["code"] == "last_admin"

    # 다른 관리자가 있으면 된다 — 그리고 멈춘 계정의 세션은 그 자리에서 끝난다.
    make(client, admin, "kim")
    kim = login(client, "kim", "second-pass-123")
    assert client.put("/api/v1/accounts/admin", json={"disabled": True}, headers=kim).status_code == 200
    assert client.get("/api/v1/auth/me", headers=admin).status_code == 401
    stopped = client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    assert stopped.status_code == 403 and stopped.json()["code"] == "account_disabled"
    # 이제 kim이 마지막이다.
    assert client.put("/api/v1/accounts/kim", json={"disabled": True}, headers=kim).json()["code"] == "last_admin"


def test_resetting_a_password_ends_that_accounts_sessions(client: TestClient) -> None:
    admin = login(client)
    make(client, admin, "kim")
    kim = login(client, "kim", "second-pass-123")
    assert client.put("/api/v1/accounts/kim", json={"password": "third-pass-4567"}, headers=admin).status_code == 200
    assert client.get("/api/v1/auth/me", headers=kim).status_code == 401
    login(client, "kim", "third-pass-4567")


def test_own_password_needs_the_current_one(client: TestClient) -> None:
    admin = login(client)
    wrong = client.put(
        "/api/v1/auth/password",
        json={"current_password": "nope-nope-1234", "new_password": "next-pass-12345"},
        headers=admin,
    )
    assert wrong.status_code == 403 and wrong.json()["code"] == "password_wrong"
    token_only = client.put(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "next-pass-12345"},
        headers={"Authorization": "Bearer t-admin"},
    )
    assert token_only.status_code == 403 and token_only.json()["code"] == "account_only"


# ─────────────────────────── Center 서명 ───────────────────────────


def test_center_signs_with_a_key_it_trusts(client: TestClient, store: Store) -> None:
    keys = client.get("/api/v1/admin-keys", headers=login(client)).json()
    assert [(one["key_id"], one["label"]) for one in keys] == [(signer.current_key_id(store), "Center")]


def test_approval_is_signed_by_center_and_names_the_account(client: TestClient, store: Store) -> None:
    admin = login(client)
    assert upload(client, build_package()).status_code == 201
    answer = client.put("/api/v1/packages/invoice-check/1.0.0/signature", headers=admin)
    assert answer.status_code == 200, answer.text

    info = client.get("/api/v1/packages/invoice-check/1.0.0/info", headers=admin).json()
    assert info["status"] == "approved" and info["approved_by"] == "admin"
    assert info["signed_by"] == signer.current_key_id(store)

    row = store.row("SELECT signature_json FROM packages WHERE id = 'invoice-check'")
    assert row is not None
    envelope = Envelope.model_validate_json(row["signature_json"])
    from chaeksas.center.api.signing import admin_keys

    assert verify(envelope, keys=admin_keys(store), expect_kind="package") == []
    assert envelope.payload["content_hash"] == info["content_hash"]


def test_rotating_keeps_the_old_key_trusted(store: Store) -> None:
    from chaeksas.center.api.signing import admin_keys

    before = signer.current_key_id(store)
    after = signer.rotate(store)
    assert after != before and signer.current_key_id(store) == after
    assert {one.key_id for one in admin_keys(store) if not one.revoked} == {before, after}

    with pytest.raises(ValueError):
        signer.retire(store, after)  # 지금 서명하는 키는 버리지 못한다
    signer.retire(store, before)
    assert [one.key_id for one in admin_keys(store) if one.revoked] == [before]

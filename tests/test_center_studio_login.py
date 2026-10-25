"""계정 권한과 Studio 로그인 (C5 §계정 권한과 Studio 로그인, ADR-0092).

Studio는 콘솔 세션(12시간)을 쓰지 않는다 — 로그인하면 **그 계정에 묶인 Studio용 키**를 받는다.
여기서는 앱을 TestClient로 두드려 그 키가 언제 열리고 언제 닫히는지를 본다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center import accounts, create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.accounts import STUDIO_KEY_DAYS

ADMIN = {"Authorization": "Bearer t-admin"}
PASSWORD = "designer-pass-1234"


@pytest.fixture(autouse=True)
def _fresh_failures() -> Iterator[None]:
    accounts.reset_failures()
    yield
    accounts.reset_failures()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    store = Store(Path(":memory:"))
    settings = Settings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "packages")
    with TestClient(create_app(settings, store=store)) as found:
        yield found
    store.close()


def make_account(client: TestClient, name: str = "kim", *, role: str = "viewer", design: bool = True) -> None:
    body: dict[str, Any] = {"username": name, "password": PASSWORD, "role": role}
    if design:
        body["permissions"] = ["design"]
    response = client.post("/api/v1/accounts", json=body, headers=ADMIN)
    assert response.status_code == 201, response.text


def studio_login(client: TestClient, name: str = "kim", machine: str = "설계 PC", **over: Any) -> Any:
    body = {"username": name, "password": PASSWORD, "machine_name": machine} | over
    return client.post("/api/v1/auth/studio-login", json=body)


def key_of(response: Any) -> dict[str, str]:
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['key']}"}


def can_list_packages(client: TestClient, headers: dict[str, str]) -> int:
    return int(client.get("/api/v1/packages", headers=headers).status_code)


def account(client: TestClient, name: str = "kim") -> dict[str, Any]:
    return next(one for one in client.get("/api/v1/accounts", headers=ADMIN).json() if one["username"] == name)


def test_login_gives_a_studio_key_tied_to_the_account(client: TestClient) -> None:
    make_account(client)
    response = studio_login(client)
    body = response.json()
    assert body["username"] == "kim" and body["key"].startswith("chk_ctr_")
    headers = key_of(response)
    assert can_list_packages(client, headers) == 200

    listed = next(k for k in client.get("/api/v1/center-keys", headers=ADMIN).json() if k["key_id"] == body["key_id"])
    assert listed["type"] == "studio" and listed["account"] == "kim"
    assert listed["name"] == "kim · 설계 PC"
    logins = account(client)["studio_logins"]
    assert [one["machine_name"] for one in logins] == ["설계 PC"]
    assert logins[0]["expires_at"] == body["expires_at"]
    days = (datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)).days
    assert days in (STUDIO_KEY_DAYS - 1, STUDIO_KEY_DAYS)


def test_without_design_permission_it_is_refused_and_not_counted(client: TestClient) -> None:
    make_account(client, design=False)
    for _ in range(6):  # 잠금 횟수(5)를 넘겨도 잠기지 않는다 — 비밀번호는 맞았다
        response = studio_login(client)
        assert response.status_code == 403
        assert response.json()["code"] == "permission_missing"
        assert response.json()["detail"]["permission"] == "design"


def test_admin_has_every_permission(client: TestClient) -> None:
    make_account(client, "boss", role="admin", design=False)
    assert studio_login(client, "boss").status_code == 200


def test_wrong_password_is_the_same_login_failed_and_locks(client: TestClient) -> None:
    make_account(client)
    for _ in range(5):
        assert studio_login(client, password="wrong-password-1").json()["code"] == "login_failed"
    assert studio_login(client).status_code == 429  # 콘솔 로그인과 같은 잠금


def test_same_machine_replaces_the_old_key(client: TestClient) -> None:
    make_account(client)
    first = key_of(studio_login(client))
    second = key_of(studio_login(client))
    other = key_of(studio_login(client, machine="노트북"))
    assert can_list_packages(client, first) == 403  # 폐기됐다
    assert can_list_packages(client, second) == 200
    assert can_list_packages(client, other) == 200
    assert sorted(one["machine_name"] for one in account(client)["studio_logins"]) == ["노트북", "설계 PC"]


def test_logout_revokes_that_key_only(client: TestClient) -> None:
    make_account(client)
    here = key_of(studio_login(client))
    there = key_of(studio_login(client, machine="노트북"))
    assert client.post("/api/v1/auth/studio-logout", headers=here).status_code == 204
    assert can_list_packages(client, here) == 403
    assert can_list_packages(client, there) == 200


@pytest.mark.parametrize(
    "change",
    [
        {"disabled": True},
        {"password": "another-pass-5678"},
        {"role": "admin"},
        {"permissions": []},
    ],
    ids=["disabled", "password", "role", "permission_removed"],
)
def test_account_changes_end_every_studio_login(client: TestClient, change: dict[str, Any]) -> None:
    make_account(client)
    headers = key_of(studio_login(client))
    response = client.put("/api/v1/accounts/kim", json=change, headers=ADMIN)
    assert response.status_code == 200, response.text
    assert can_list_packages(client, headers) in (401, 403)
    assert account(client)["studio_logins"] == []


def test_adding_a_permission_keeps_the_login(client: TestClient) -> None:
    make_account(client)
    headers = key_of(studio_login(client))
    # 같은 것을 다시 적어도(늘거나 같다) 끝나지 않는다.
    assert client.put("/api/v1/accounts/kim", json={"permissions": ["design"]}, headers=ADMIN).status_code == 200
    assert can_list_packages(client, headers) == 200


def test_unknown_permission_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/v1/accounts",
        json={"username": "lee", "password": PASSWORD, "role": "viewer", "permissions": ["superuser"]},
        headers=ADMIN,
    )
    assert response.status_code == 422 and response.json()["code"] == "permission_unknown"


def test_the_actor_is_the_account_not_the_key_name(client: TestClient) -> None:
    """올리기의 「누가」가 계정 아이디다 — 키 이름(「kim · 설계 PC」)이 아니다."""
    from chaeksas.center.auth import caller  # noqa: PLC0415

    make_account(client)
    response = studio_login(client)
    store: Store = client.app.state.store  # type: ignore[attr-defined]

    class Fake:
        headers = {"authorization": f"Bearer {response.json()['key']}"}

    found = caller(Fake(), store, admin_token=None, read_token=None)  # type: ignore[arg-type]
    assert found.actor == "kim"


def test_studio_logout_needs_a_login_key(client: TestClient) -> None:
    made = client.post("/api/v1/center-keys", json={"name": "CI", "type": "studio"}, headers=ADMIN).json()
    response = client.post("/api/v1/auth/studio-logout", headers={"Authorization": f"Bearer {made['key']}"})
    assert response.status_code == 403

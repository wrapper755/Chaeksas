"""C16 — 조직·업무 자리를 Center가 지키는가 (ADR-0125·ADR-0127).

거듭 보는 것.

1. **업무 자리는 매니페스트에서 온다** — Center는 올릴 때 그 회사 안인지 보고, 승인할 때는 본문이 없다.
2. **작업은 만들 때의 주인을 적고**, 서버로 내려갈 때 `place`를 붙인다. 멈춘 주인은 새 작업이 없다.
3. **회사가 정해진 계정은 제 회사 것만** 보고 다룬다 — 남의 것은 같은 404다.
4. 장비는 회사 소유다 — 등록 승인에 회사가 있어야 하고, PC 배포는 그 회사의 PC에만 된다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from center_admin import approve
from fastapi.testclient import TestClient
from test_center_app import build_package

from chaeksas.center import accounts, create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store

ADMIN = {"Authorization": "Bearer t-admin"}
PASSWORD = "first-admin-2026"
API = "/api/v1"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    accounts.reset_failures()
    store = Store(Path(":memory:"))
    settings = Settings(admin_token="t-admin", package_dir=tmp_path / "packages", first_admin_password=PASSWORD)
    with TestClient(create_app(settings, store=store)) as found:
        yield found
    store.close()


def made(answer: Any, code: int = 201) -> Any:
    assert answer.status_code == code, answer.text
    return answer.json()


def organize(client: TestClient) -> None:
    """회사 둘 — 각자 부서 하나와 직원 하나."""
    made(client.post(f"{API}/companies", json={"id": "company2", "name": "회사2"}, headers=ADMIN))
    made(client.post(f"{API}/departments", json={"id": "purchasing", "company": "default", "name": "구매팀"},
                     headers=ADMIN))
    made(client.post(f"{API}/staff", json={"id": "kim", "company": "default", "department": "purchasing",
                                           "name": "김구매"}, headers=ADMIN))
    made(client.post(f"{API}/departments", json={"id": "sales2", "company": "company2", "name": "영업팀"},
                     headers=ADMIN))


def upload(client: TestClient, raw: bytes, *, company: str | None = None) -> Any:
    data = {"company": company} if company else None
    return client.post(f"{API}/packages", files={"file": ("p.zip", raw, "application/zip")}, data=data,
                       headers=ADMIN)


def login_as(client: TestClient, username: str, role: str, company: str | None) -> dict[str, str]:
    admin = client.post(f"{API}/auth/login", json={"username": "admin", "password": PASSWORD}).json()["token"]
    body = {"username": username, "password": "second-pass-123", "role": role, "company": company}
    made(client.post(f"{API}/accounts", json=body, headers={"Authorization": f"Bearer {admin}"}))
    token = client.post(f"{API}/auth/login", json={"username": username, "password": "second-pass-123"}).json()
    return {"Authorization": f"Bearer {token['token']}"}


def test_the_default_company_is_there_and_the_organization_reads_back(client: TestClient) -> None:
    organize(client)
    assert [one["id"] for one in made(client.get(f"{API}/companies", headers=ADMIN), 200)] == ["company2", "default"]
    kim = made(client.get(f"{API}/staff/kim", headers=ADMIN), 200)
    assert (kim["company"], kim["department"], kim["name"]) == ("default", "purchasing", "김구매")
    # 다른 회사의 부서에 직원을 둘 수 없다.
    wrong = client.post(f"{API}/staff", json={"id": "lee", "company": "default", "department": "sales2",
                                              "name": "이"}, headers=ADMIN)
    assert wrong.status_code == 422 and wrong.json()["code"] == "place_outside_company"


def test_the_place_rides_the_manifest_and_must_be_inside_the_company(client: TestClient) -> None:
    organize(client)
    inside = made(upload(client, build_package(place={"scope": "staff", "staff": "kim"}), company="default"))
    assert inside["company"] == "default" and inside["place"] == {"scope": "staff", "staff": "kim"}
    outside = upload(client, build_package(package_id="other", place={"scope": "department",
                                                                       "department": "sales2"}), company="default")
    assert outside.status_code == 422 and outside.json()["code"] == "place_outside_company", outside.text
    # 승인은 본문이 없다 — 자리는 매니페스트 것 그대로다 (ADR-0127).
    approve(client, "invoice-check", "1.0.0")
    assert made(client.get(f"{API}/packages/invoice-check/1.0.0/info", headers=ADMIN), 200)["place"]["staff"] == "kim"


def test_an_id_belongs_to_one_company(client: TestClient) -> None:
    organize(client)
    made(upload(client, build_package(), company="default"))
    taken = upload(client, build_package(version="1.1.0"), company="company2")
    assert taken.status_code == 409 and taken.json()["code"] == "package_id_taken"


def test_a_job_records_its_owner_and_a_stopped_owner_starts_nothing(client: TestClient) -> None:
    organize(client)
    made(upload(client, build_package(place={"scope": "staff", "staff": "kim"}), company="default"))
    approve(client, "invoice-check", "1.0.0")
    made(client.post(f"{API}/deployments", json={"target": {"type": "server_runner", "id": "*"},
                                                 "bpm_process_id": "invoice-check", "version": "1.0.0"},
                     headers=ADMIN), 200)
    body = {"bpm_process_id": "invoice-check", "target": {"type": "server_runner"}, "inputs": {}}
    job = made(client.post(f"{API}/jobs", json=body, headers=ADMIN))
    assert (job["company"], job["department"], job["staff"]) == ("default", "purchasing", "kim")

    made(client.put(f"{API}/staff/kim", json={"company": "default", "department": "purchasing", "name": "김구매",
                                               "state": "stopped"}, headers=ADMIN), 200)
    stopped = client.post(f"{API}/jobs", json=body, headers=ADMIN)
    assert stopped.status_code == 409 and stopped.json()["code"] == "owner_stopped", stopped.text


def test_a_company_admin_sees_and_touches_only_its_company(client: TestClient) -> None:
    organize(client)
    made(upload(client, build_package(), company="default"))
    made(upload(client, build_package(package_id="theirs"), company="company2"))
    mine = login_as(client, "admin2", "company_admin", "company2")

    assert [one["id"] for one in made(client.get(f"{API}/packages", headers=mine), 200)] == ["theirs"]
    assert client.get(f"{API}/packages/invoice-check/1.0.0/info", headers=mine).status_code == 404
    assert client.put(f"{API}/packages/invoice-check/1.0.0/signature", headers=mine).status_code == 404
    assert [one["id"] for one in made(client.get(f"{API}/departments", headers=mine), 200)] == ["sales2"]
    assert client.get(f"{API}/staff/kim", headers=mine).status_code == 404
    # 제 회사 안에서는 관리자다 — 부서를 만들고 승인한다. 남의 회사 이름으로는 못 만든다.
    made(client.post(f"{API}/departments", json={"id": "ops2", "company": "company2", "name": "운영"}, headers=mine))
    assert client.post(f"{API}/departments", json={"id": "x", "company": "default", "name": "x"},
                       headers=mine).status_code == 404
    approve(client, "theirs", "1.0.0", headers=mine)
    # Center 공용인 것은 Center 관리자만 — 회사 만들기·계정.
    assert client.post(f"{API}/companies", json={"id": "c3", "name": "c3"}, headers=mine).status_code == 403
    assert client.get(f"{API}/accounts", headers=mine).status_code == 403


def test_a_company_admin_needs_a_company_and_a_center_admin_has_none(client: TestClient) -> None:
    admin = client.post(f"{API}/auth/login", json={"username": "admin", "password": PASSWORD}).json()["token"]
    as_ = {"Authorization": f"Bearer {admin}"}
    body = {"username": "nobody", "password": "second-pass-123"}
    no_company = client.post(f"{API}/accounts", json={**body, "role": "company_admin"}, headers=as_)
    assert no_company.status_code == 422 and no_company.json()["code"] == "company_required"
    wrong = client.post(f"{API}/accounts", json={**body, "role": "admin", "company": "default"}, headers=as_)
    assert wrong.status_code == 422


def test_a_pc_deployment_stays_inside_the_company(client: TestClient) -> None:
    """PC 배포는 그 회사의 PC에만 — 422 `company_mismatch` (C16, ADR-0125 §2)."""
    organize(client)
    store: Store = client.app.state.store  # type: ignore[attr-defined]
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO bot_uis (bot_ui_id, key_id, machine_id, name, os, versions_json, registered_at, company)"
            " VALUES ('bui_c2', 'ck_c2', ?, '회사2 PC', 'Windows 11', '{}', '2026-11-01T00:00:00+00:00', 'company2')",
            ("m" * 64,),
        )
    raw = build_package(package_id="pc-job", run_location="pc")
    made(upload(client, raw, company="default"))
    approve(client, "pc-job", "1.0.0")
    refused = client.post(f"{API}/deployments", json={"target": {"type": "bot_ui", "id": "bui_c2"},
                                                      "bpm_process_id": "pc-job", "version": "1.0.0"}, headers=ADMIN)
    assert refused.status_code == 422 and refused.json()["code"] == "company_mismatch", refused.text


def test_the_owner_goes_down_with_names(client: TestClient) -> None:
    """작업 행에는 id만 — 이름은 내려줄 때 읽는다 (C12 `JobDispatch.place`)."""
    from chaeksas.center import organization

    organize(client)
    store: Store = client.app.state.store  # type: ignore[attr-defined]
    owner = organization.identity(store, "default", "purchasing", "kim")
    assert owner is not None
    assert (owner.company.name, owner.department and owner.department.name, owner.staff and owner.staff.name) == (
        "기본 회사", "구매팀", "김구매")
    assert organization.identity(store, None, None, None) is None


def test_a_company_admin_approves_devices_into_its_own_company_only(client: TestClient) -> None:
    from chaeksas.contracts.enrollment import new_keypair

    organize(client)
    mine = login_as(client, "admin2", "company_admin", "company2")
    _, public = new_keypair()
    body = {"schema": 1, "machine_id": "ab" * 32, "name": "현장 PC", "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"}, "public_key": public}
    pending = made(client.post(f"{API}/bot-ui/enroll", json=body))
    # 대기 중인 요청은 회사가 없어 보인다 — 제 회사로 승인할 수 있다.
    assert [one["enrollment_id"] for one in made(client.get(f"{API}/enrollments", headers=mine), 200)] == [
        pending["enrollment_id"]]
    other = client.post(f"{API}/enrollments/{pending['enrollment_id']}/approve", json={"company": "default"},
                        headers=mine)
    assert other.status_code == 404
    done = made(client.post(f"{API}/enrollments/{pending['enrollment_id']}/approve", json={}, headers=mine), 200)
    key = [k for k in made(client.get(f"{API}/center-keys", headers=ADMIN), 200) if k["key_id"] == done["key_id"]]
    assert key, "승인한 키가 있다"
    listed = made(client.get(f"{API}/enrollments?state=approved", headers=mine), 200)
    assert [one["company"] for one in listed] == ["company2"]

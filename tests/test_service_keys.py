"""서비스 앱 키는 배포가 데리고 다닌다 (ADR-0094, C11 §Center가 발급하는 키, C4 §서비스 앱 키 전달).

한 바퀴를 끝까지 본다 — **사람은 키를 보지 않는다.**

| 보는 것 | 왜 |
| --- | --- |
| 배포하면 Center가 키를 짓고 **앱에는 해시만** 간다 | 원문은 Center 밖으로 봉함으로만 나간다 |
| 현장은 하트비트로 받아 열고, 그 키로 앱이 부른다 | 붙여 넣는 심부름이 없어진다 |
| ack가 오면 봉한 덩이가 지워진다 | Center DB에 키가 쌓이지 않는다 |
| 판을 올려도 **같은 키**이고 허용 작업만 고친다 | 올릴 때마다 키가 갈리지 않는다 |
| 철회하면 앱에서 폐기되고 현장에서 지워진다 | 철회가 키를 거둔다 |
| 앱은 **Center가 서명한 것만** 받는다 | 남이 지은 봉투로 키를 만들 수 없다 |
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from center_admin import approve as approve_package
from center_admin import deploy_id, revoke_deployment
from fastapi.testclient import TestClient

from chaeksas.center import service_keys
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, dumps, now_iso
from chaeksas.contracts.enrollment import new_keypair
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.service_app import Operation, ServiceAppManifest
from chaeksas.contracts.service_keys import ServiceKeyDelivery
from chaeksas.core.service_keys import ReceivedKeys, run_name
from chaeksas.service_kit import CenterLink, InMemoryKeyStore
from chaeksas.service_kit import create_app as create_service_app

ADMIN = {"Authorization": "Bearer t-admin"}
AT = "2026-10-25T09:00:00+09:00"
BOT = "fin.invoice"
APP = "tax-invoice"
BASE = "http://tax-invoice.test"
BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="D">
  <bpmn:process id="Proc_x" isExecutable="true"><bpmn:startEvent id="S" /></bpmn:process>
</bpmn:definitions>
"""


# ─────────────── 발판 ───────────────


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg")
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def app_manifest() -> ServiceAppManifest:
    return ServiceAppManifest(
        schema=1,
        app_id=APP,
        name="세금계산서",
        version="1.0.0",
        category="business",
        console_url="http://tax-invoice.test:8001",
        operations=[
            Operation(name="issue", description="발행", modes=["deterministic"]),
            Operation(name="cancel", description="취소", modes=["deterministic"]),
        ],
    )


@pytest.fixture
def keys() -> InMemoryKeyStore:
    return InMemoryKeyStore()


@pytest.fixture
def service(center: TestClient, keys: InMemoryKeyStore) -> TestClient:
    """서비스 앱 하나 — **Center 주소만** 받아 Center 공개키를 받아 둔다 (C11, ADR-0094 §1)."""
    link = CenterLink(
        center_url="http://center.test",
        fetch=lambda url: center.get(url.removeprefix("http://center.test")).json(),
    )
    made = create_service_app(
        app_manifest(),
        {"issue": lambda req, mode: {"invoice_no": "1"}, "cancel": lambda req, mode: {"ok": True}},
        keys=keys,
        center_link=link,
    )
    return TestClient(made)


@pytest.fixture
def send(service: TestClient) -> Any:
    """Center → 서비스 앱 (서버망 안의 일). 시험은 HTTP 대신 앱을 그 자리에서 부른다."""

    def go(base_url: str, envelope: dict[str, Any]) -> tuple[int, str | None]:
        assert base_url == BASE
        answer = service.post("/center/v1/keys", json=envelope)
        return answer.status_code, None if answer.status_code < 400 else answer.json().get("code")

    return go


def register_app(store: Store) -> None:
    """CON-07 「서비스 앱 추가」가 하는 일 — 주소와 manifest. 시험은 줄을 바로 넣는다."""
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO service_apps (app_id, base_url, manifest_json, manifest_at, status, registered_at,"
            " registered_by) VALUES (?, ?, ?, ?, 'ok', ?, 'admin')",
            (APP, BASE, dumps(app_manifest().to_json_dict()), now_iso(), now_iso()),
        )


@pytest.fixture
def pc(center: TestClient) -> dict[str, str]:
    """공개키를 아는 PC 하나 (등록 요청으로 들어온 것과 같다 — C4 `RegisterRequest.public_key`)."""
    made = center.post("/api/v1/center-keys", json={"name": "현장 PC 1", "type": "bot_ui"}, headers=ADMIN)
    key = str(made.json()["key"])
    private, public = new_keypair()
    answer = center.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": hashlib.sha256(b"pc1").hexdigest(),
            "name": "현장 PC 1",
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
            "public_key": public,
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert answer.status_code == 200, answer.text
    return {"bot_ui_id": str(answer.json()["bot_ui_id"]), "key": key, "private": private}


def package_zip(version: str, operations: list[str]) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": BOT,
        "version": version,
        "name": BOT,
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_x",
        "requires": {"service_apps": [{"app_id": APP, "operations": operations, "key_ref": "fin-invoice"}]},
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


def deploy_bot(
    center: TestClient, bot_ui_id: str, *, version: str = "1.0.0", operations: list[str] | None = None
) -> str:
    answer = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(version, operations or ["issue"]), "application/zip")},
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    approve_package(center, BOT, version)
    return str(deploy_id(center, target={"type": "bot_ui", "id": bot_ui_id}, bpm_process_id=BOT, version=version))


def heartbeat(center: TestClient, pc: dict[str, str], acks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    answer = center.post(
        "/api/v1/bot-ui/heartbeat",
        json={
            "schema": 1,
            "status": "idle",
            "current_run": None,
            "queue": {"max": 20, "items": []},
            "worker": {"state": "off", "restarts": 0},
            "service_key_acks": acks or [],
        },
        headers={"Authorization": f"Bearer {pc['key']}"},
    )
    assert answer.status_code == 200, answer.text
    return dict(answer.json())


def take(held: ReceivedKeys, body: dict[str, Any], pc: dict[str, str], vault: dict[str, str]) -> None:
    """현장이 하는 일 — 열어서 비밀 저장소에 두고, 다음 하트비트에 ack를 싣는다."""
    held.take(
        [ServiceKeyDelivery.model_validate(one) for one in body.get("service_keys") or []],
        list(body.get("drop_service_keys") or []),
        secret=pc["private"],
        put=vault.__setitem__,
        delete=lambda name: vault.__delitem__(name) if name in vault else None,
    )


def call(service: TestClient, raw: str, operation: str = "issue") -> int:
    answer = service.post(
        f"/v1/ops/{operation}",
        json={
            "schema": 1,
            "mode": "deterministic",
            "run_id": "run_20261025_090000_aaaaaa",
            "node_id": "Task_issue",
            "node_instance": 1,
            "attempt": 1,
            "caller": {"type": "bot_ui", "host": "pc1", "bpm_process_id": BOT, "version": "1.0.0"},
            "input": {},
        },
        headers={"Authorization": f"Bearer {raw}"},
    )
    return int(answer.status_code)


# ─────────────── 한 바퀴 ───────────────


def test_deploying_issues_a_key_the_field_receives_and_the_app_accepts(
    center: TestClient,
    store: Store,
    service: TestClient,
    keys: InMemoryKeyStore,
    send: Any,
    pc: dict[str, str],
    tmp_path: Path,
) -> None:
    register_app(store)
    deployment = deploy_bot(center, pc["bot_ui_id"])

    done = service_keys.reconcile(store, send=send)
    assert done.issued == 1 and not done.errors

    # 앱에는 **해시만** 왔다 — 레코드에 Center가 누구를 위해 지었는지가 남는다.
    [record] = list(keys.all_keys())
    assert record.issued_by == "center" and record.name.startswith("svk_")
    assert record.allowed_operations == ["issue"] and record.allowed_modes == ["deterministic"]
    assert record.issued_for is not None and record.issued_for.deployment_id == deployment
    assert record.issued_for.target is not None and record.issued_for.target.name == "현장 PC 1"

    held = ReceivedKeys.at(tmp_path)
    vault: dict[str, str] = {}
    body = heartbeat(center, pc)
    assert len(body["service_keys"]) == 1
    take(held, body, pc, vault)
    raw = vault[run_name(BOT, "fin-invoice")]
    assert raw.startswith("chk_svc_")
    assert call(service, raw) == 200
    assert call(service, raw, "cancel") == 403  # 매니페스트가 부르지 않는 작업은 허용되지 않는다

    # ack가 가면 봉한 덩이가 지워지고 더 실리지 않는다.
    body = heartbeat(center, pc, acks=[one.to_json_dict() for one in held.pending])
    held.sent(held.pending)
    assert body["service_keys"] == []
    row = store.row("SELECT sealed_json, acked_at FROM service_keys")
    assert row is not None and row["sealed_json"] is None and row["acked_at"]

    # 판을 올린다 — **같은 키**이고 허용 작업만 는다.
    deploy_bot(center, pc["bot_ui_id"], version="1.1.0", operations=["issue", "cancel"])
    done = service_keys.reconcile(store, send=send)
    assert done.issued == 0 and done.updated == 1
    assert call(service, raw, "cancel") == 200
    assert len(list(keys.all_keys())) == 1

    # 철회 — 둘 다 거두면 앱에서 폐기되고 현장은 지우라는 말을 받는다.
    for one in center.get("/api/v1/deployments?active=true", headers=ADMIN).json():
        revoke_deployment(center, one["deployment_id"])
    done = service_keys.reconcile(store, send=send)
    assert done.revoked == 1
    assert call(service, raw) == 403
    body = heartbeat(center, pc)
    assert body["drop_service_keys"]
    take(held, body, pc, vault)
    assert run_name(BOT, "fin-invoice") not in vault
    body = heartbeat(center, pc, acks=[one.to_json_dict() for one in held.pending])
    assert body["drop_service_keys"] == []


def test_the_app_refuses_an_envelope_center_did_not_sign(service: TestClient, center: TestClient) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from chaeksas.contracts.signing import sign

    payload = {
        "kind": "service_key",
        "action": "issue",
        "app_id": APP,
        "center_key_id": "svk_deadbeef",
        "hash": "0" * 64,
        "prefix": "chk_svc_AAAAAAAA",
        "not_after": "2099-01-01T00:00:00+00:00",
    }
    forged = sign(payload, Ed25519PrivateKey.generate(), signed_at=now_iso()).to_json_dict()
    answer = service.post("/center/v1/keys", json=forged)
    assert answer.status_code == 401
    assert answer.json()["code"] == "center_signature_invalid"


def test_another_apps_envelope_is_refused(store: Store, service: TestClient, center: TestClient) -> None:
    from chaeksas.center import signer

    payload = {
        "kind": "service_key",
        "action": "issue",
        "app_id": "someone-else",
        "center_key_id": "svk_deadbeef",
        "hash": "0" * 64,
        "prefix": "chk_svc_AAAAAAAA",
        "not_after": "2099-01-01T00:00:00+00:00",
    }
    answer = service.post("/center/v1/keys", json=signer.seal(store, payload).to_json_dict())
    assert answer.status_code == 422 and answer.json()["code"] == "wrong_app"


def test_an_old_envelope_is_refused(store: Store, service: TestClient) -> None:
    from chaeksas.center import signer

    payload = {
        "kind": "service_key",
        "action": "issue",
        "app_id": APP,
        "center_key_id": "svk_deadbeef",
        "hash": "0" * 64,
        "prefix": "chk_svc_AAAAAAAA",
        "not_after": "2020-01-01T00:00:00+00:00",
    }
    answer = service.post("/center/v1/keys", json=signer.seal(store, payload).to_json_dict())
    assert answer.status_code == 403 and answer.json()["code"] == "envelope_expired"


def test_the_app_without_a_center_address_takes_no_envelopes(keys: InMemoryKeyStore) -> None:
    made = TestClient(
        create_service_app(app_manifest(), {"issue": lambda r, m: {}, "cancel": lambda r, m: {}}, keys=keys)
    )
    answer = made.post("/center/v1/keys", json={})
    assert answer.status_code == 503 and answer.json()["code"] == "center_disabled"
    assert made.get("/center/v1/trust").json()["key_ids"] == []


def test_a_pin_that_does_not_match_means_no_trust(center: TestClient) -> None:
    link = CenterLink(
        center_url="http://center.test",
        pin="0" * 16,
        fetch=lambda url: center.get(url.removeprefix("http://center.test")).json(),
    )
    assert link.refresh(force=True) is False
    assert link.trust().key_ids == [] and link.trust().pinned


def test_names_starting_with_svk_are_reserved_for_center(keys: InMemoryKeyStore) -> None:
    made = TestClient(
        create_service_app(
            app_manifest(), {"issue": lambda r, m: {}, "cancel": lambda r, m: {}}, keys=keys, admin_token="adm"
        )
    )
    answer = made.post("/admin/v1/keys", json={"name": "svk_mine"}, headers={"Authorization": "Bearer adm"})
    assert answer.status_code == 409 and answer.json()["code"] == "name_reserved"


def test_a_pc_without_a_public_key_gets_no_key(center: TestClient, store: Store, send: Any) -> None:
    """환경변수로 Center 키를 받은 PC는 봉할 수 없다 — 짓지 않는다 (그쪽은 환경변수로 받는다)."""
    register_app(store)
    made = center.post("/api/v1/center-keys", json={"name": "개발 PC", "type": "bot_ui"}, headers=ADMIN)
    key = str(made.json()["key"])
    answer = center.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": hashlib.sha256(b"dev").hexdigest(),
            "name": "개발 PC",
            "os": "linux",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    deploy_bot(center, str(answer.json()["bot_ui_id"]))
    assert service_keys.reconcile(store, send=send).issued == 0


def test_an_unreachable_app_is_retried_without_making_a_second_key(
    center: TestClient, store: Store, send: Any, keys: InMemoryKeyStore, pc: dict[str, str]
) -> None:
    register_app(store)
    deploy_bot(center, pc["bot_ui_id"])
    done = service_keys.reconcile(store, send=lambda base, envelope: (0, "unreachable"))
    assert done.issued == 1 and done.errors
    assert heartbeat(center, pc)["service_keys"] == []  # 앱에 맡기기 전에는 현장에 가지 않는다
    done = service_keys.reconcile(store, send=send)
    assert done.issued == 0 and not done.errors
    assert len(list(keys.all_keys())) == 1
    assert len(heartbeat(center, pc)["service_keys"]) == 1

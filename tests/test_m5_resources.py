"""리소스 목록 — 서비스 앱과 네 종류 모으기 (C7·C15, ADR-0102).

**Center는 바깥 기능을 읽으러 가지 않는다.** 서비스 앱은 그 앱 id를 토픽으로 승인받은 **일꾼이 올린
manifest**에서 오고(들일 때·`PUT /consumers/self/manifest`), 상태는 그 일꾼이 **마지막으로 가져간 때**가
말한다. 진짜 Center를 in-process로 띄우고 제품의 들이기(`consumers.enroll`)로 일꾼을 들인다.

| 보는 것 | 왜 |
| --- | --- |
| 일꾼이 없으면 서비스 앱도 없다, 들이면 manifest가 그대로 뜬다 | 「등록은 됐는데 아무것도 모른다」가 없다 |
| 상태는 일꾼이 말한다 — 가져간 적 없음·90초 조용함은 `unreachable`, 가져가면 `ok` | Center가 앱을 두드리지 않는다 |
| manifest는 **승인된 토픽의 것만** 받는다, 틀린 모양은 422 | 일꾼이 남의 앱을 자처하지 못한다 |
| 주소로 등록하는 길(`POST /resources/service-apps`)이 없다 | 주소·키를 Center가 들지 않는다 |
| 같은 토픽을 둘이 맡으면 일꾼 수가 둘, 나중에 승인된 쪽의 manifest | CON-07 「일꾼 수」 |
| 런타임·확장은 따로 등록받지 않는다 — Center가 이미 가진 것에서 모은다 | C7 |
| 서비스 앱 누락은 **경고만**, 일꾼이 붙으면 읽기만 해도 사라진다 | 막는 것은 확장 누락·해시 불일치뿐이다 |
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from consumers import enroll
from fastapi.testclient import TestClient

from chaeksas.center.api import resources
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store

TOKEN = "t-admin"
READ = "t-read"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
READ_AUTH = {"Authorization": f"Bearer {READ}"}
AT = "2026-10-07T09:00:00+09:00"
APP = "demo.directory"

#: 데모 앱을 쓰는 BPM 프로세스의 `requires.service_apps` 한 줄 (C1). 키 참조는 없다 (ADR-0102).
NEEDS_DEMO = {"app_id": APP, "operations": ["lookup"]}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    made = Store(tmp_path / "center.sqlite3")
    yield made
    made.close()


@pytest.fixture
def client(tmp_path: Path, store: Store) -> Iterator[TestClient]:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=TOKEN,
        read_token=READ,
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


# ─────────────────────────── 일꾼 하나 ───────────────────────────


def manifest(**over: Any) -> dict[str, Any]:
    """일꾼이 올리는 C11 manifest — 앱이 자기 id를 정한다."""
    body: dict[str, Any] = {
        "schema": 1,
        "app_id": APP,
        "name": "사원 디렉터리",
        "version": "1.0.0",
        "category": "business",
        "console_url": "http://127.0.0.1:8599/console",
        "operations": [
            {
                "name": "lookup",
                "description": "사번으로 사원을 찾는다",
                "modes": ["deterministic", "autonomous"],
                "server_ok": True,
            }
        ],
    }
    return body | over


def consumer(
    client: TestClient, tmp_path: Path, *, name: str = "c1", topics: list[str] | None = None, **over: Any
) -> dict[str, str]:
    """일꾼 하나를 들인다 (요청 → 관리자 승인 → 봉한 토큰) — 일꾼 토큰 헤더를 돌려준다."""
    tokens = enroll(
        client, topics=topics or [APP], manifests=[manifest(**over)], name=f"일꾼 {name}", folder=tmp_path / name
    )
    return {"Authorization": f"Bearer {tokens.token()}"}


def fetch(client: TestClient, worker: dict[str, str], topic: str = APP) -> None:
    """일꾼이 한 번 가져간다 — 이것이 「살아 있다」는 신호다 (C7 상태)."""
    answer = client.post("/api/v1/consumers/fetch", json={"topics": [topic], "wait_s": 0}, headers=worker)
    assert answer.status_code == 200, answer.text


def service_apps(client: TestClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = client.get("/api/v1/resources?type=service_app", headers=READ_AUTH).json()["items"]
    return found


# ─────────────────────────── 패키지 거리 ───────────────────────────


def package_zip(
    package_id: str = "hr.onboarding",
    version: str = "1.0.0",
    *,
    kind: str = "bpm_process",
    requires: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> bytes:
    import tempfile

    from chaeksas.contracts.hashing import content_hash_zip

    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": kind,
        "id": package_id,
        "version": version,
        "name": "입사 처리",
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    if kind == "bpm_process":
        manifest |= {"run_location": "pc", "entry": "process/main.bpmn", "process_id": "Proc_main"}
    manifest |= extra or {}

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            if kind == "bpm_process":
                archive.writestr("process/main.bpmn", "<definitions />")
            archive.writestr("manifest.json", body)
        return out.getvalue()

    staged = made(json.dumps(manifest, ensure_ascii=False))
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / "p.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return made(json.dumps(manifest, ensure_ascii=False))


def upload(client: TestClient, raw: bytes) -> dict[str, Any]:
    answer = client.post(
        "/api/v1/packages", files={"file": ("p.zip", raw, "application/zip")}, headers=ADMIN
    )
    assert answer.status_code in (200, 201), answer.text
    return dict(answer.json())


def register_bot_ui(client: TestClient, *, name: str = "현장 PC 1", seed: str = "pc1") -> str:
    made = client.post(
        "/api/v1/center-keys", json={"name": f"{name} 키", "type": "bot_ui"}, headers=ADMIN
    )
    raw = made.json()["key"]
    answer = client.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": hashlib.sha256(seed.encode()).hexdigest(),
            "name": name,
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0", "worker": "0.3.0"},
            "runtimes": {
                "browsers": ["chromium-130"],
                "desktop_backend": "uia",
                "extensions": [{"id": "ui-automation", "version": "0.1.0", "enabled": True}],
            },
        },
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert answer.status_code == 200, answer.text
    return str(answer.json()["bot_ui_id"])


# ─────────────────────────── 서비스 앱 = 일꾼이 올린 manifest (C7·C15) ───────────────────────────


def test_no_consumer_means_no_service_app(client: TestClient) -> None:
    assert service_apps(client) == []
    missing = client.get(f"/api/v1/resources/service-apps/{APP}", headers=READ_AUTH)
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_enrolling_a_consumer_brings_its_manifest(client: TestClient, tmp_path: Path) -> None:
    """들일 때 올린 manifest가 그대로 뜬다 — 앱이 자기 id·작업을 정한다 (C11)."""
    consumer(client, tmp_path)
    [found] = service_apps(client)
    assert found["app_id"] == APP
    assert found["name"] == "사원 디렉터리" and found["category"] == "business"
    assert [one["name"] for one in found["operations"]] == ["lookup"]
    assert found["consumers"] == 1 and found["manifest_at"]
    assert "base_url" not in found or not found["base_url"], "Center는 앱의 주소를 모른다"


def test_the_status_is_what_the_consumer_says(client: TestClient, tmp_path: Path, store: Store) -> None:
    """**가져간 때**가 상태다 — 들었지만 가져간 적 없으면 `unreachable`, 가져가면 `ok`, 90초 조용하면 다시."""
    worker = consumer(client, tmp_path)
    [quiet] = service_apps(client)
    assert (quiet["status"], quiet["status_reasons"]) == ("unreachable", ["consumer_quiet"])
    assert quiet.get("checked_at") is None

    fetch(client, worker)
    [alive] = service_apps(client)
    assert alive["status"] == "ok" and alive["status_reasons"] == [] and alive["checked_at"]

    with store.tx() as cur:
        cur.execute("UPDATE consumers SET last_fetch_at = '2026-01-01T00:00:00+00:00'")
    [gone] = service_apps(client)
    assert gone["status"] == "unreachable" and gone["checked_at"] == "2026-01-01T00:00:00+00:00"


def test_the_consumer_replaces_its_manifest(client: TestClient, tmp_path: Path) -> None:
    """판이 바뀌면 일꾼이 다시 올린다 — 주소가 아니라 **manifest가** 바뀌는 단위다."""
    worker = consumer(client, tmp_path)
    answer = client.put("/api/v1/consumers/self/manifest", json=manifest(version="1.1.0"), headers=worker)
    assert answer.status_code == 200, answer.text
    assert answer.json()["apps"] == [f"{APP}@1.1.0"]
    assert [one["version"] for one in service_apps(client)] == ["1.1.0"]


def test_a_manifest_outside_the_granted_topics_is_refused(client: TestClient, tmp_path: Path) -> None:
    """일꾼이 승인받지 않은 앱을 자처하지 못한다."""
    worker = consumer(client, tmp_path)
    other = client.put("/api/v1/consumers/self/manifest", json=manifest(app_id="hr.payroll"), headers=worker)
    assert other.status_code == 403 and other.json()["code"] == "topic_not_granted"
    broken = client.put("/api/v1/consumers/self/manifest", json={"app_id": APP}, headers=worker)
    assert broken.status_code == 422 and broken.json()["code"] == "input_invalid"
    assert [one["app_id"] for one in service_apps(client)] == [APP]


def test_only_a_consumer_token_uploads_a_manifest(client: TestClient) -> None:
    assert client.put("/api/v1/consumers/self/manifest", json=manifest(), headers=ADMIN).status_code == 403


def test_there_is_no_address_registration_anymore(client: TestClient) -> None:
    """주소로 등록하는 길이 없다 (ADR-0102) — Center는 앱의 주소도 키도 들지 않는다."""
    made = client.post("/api/v1/resources/service-apps", json={"base_url": "http://127.0.0.1:9"}, headers=ADMIN)
    assert made.status_code in (404, 405)
    assert client.post("/api/v1/resources/refresh", json={}, headers=ADMIN).status_code in (404, 405)


def test_two_consumers_on_one_topic_are_counted(client: TestClient, tmp_path: Path) -> None:
    """같은 토픽을 둘이 맡을 수 있다 — 일꾼 수가 늘고, manifest는 **나중에 승인된 쪽**이다."""
    consumer(client, tmp_path, name="c1")
    second = consumer(client, tmp_path, name="c2", version="2.0.0")
    fetch(client, second)
    [found] = service_apps(client)
    assert found["consumers"] == 2 and found["version"] == "2.0.0" and found["status"] == "ok"


def test_used_by_shows_the_packages(client: TestClient, tmp_path: Path) -> None:
    consumer(client, tmp_path)
    upload(client, package_zip(requires={"service_apps": [NEEDS_DEMO]}))
    found = client.get(f"/api/v1/resources/service-apps/{APP}", headers=READ_AUTH).json()
    assert found["used_by"] == ["hr.onboarding@1.0.0"]


# ─────────────────────────── 모으는 종류 (C7) ───────────────────────────


def test_runtimes_come_from_bot_ui_reports(client: TestClient) -> None:
    """런타임은 C4가 보고한 그대로다."""
    bot_ui_id = register_bot_ui(client)
    found = client.get("/api/v1/resources?type=runtime", headers=READ_AUTH).json()
    [one] = found["items"]
    assert one["host"] == {"type": "bot_ui", "id": bot_ui_id, "name": "현장 PC 1"}
    assert one["browsers"] == ["chromium-130"] and one["desktop_backend"] == "uia"
    assert one["versions"]["worker"] == "0.3.0"


def test_extensions_merge_reports_and_manifests(client: TestClient, tmp_path: Path) -> None:
    """확장은 **실행하는 쪽의 보고와 일꾼 manifest를 합친** 것이다 (C7)."""
    register_bot_ui(client)
    register_bot_ui(client, name="현장 PC 2", seed="pc2")
    consumer(client, tmp_path)

    found = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()
    one = next(x for x in found["items"] if x["id"] == "ui-automation")
    assert one["installed_on"] == {"hosts": 2, "by_version": {"0.1.0": 2}}, "몇 대에 깔렸나"
    assert one["status"] == "n/a", "서버 부분이 없는 확장이다"


def test_an_extensions_server_part_status_comes_from_its_consumer(client: TestClient, tmp_path: Path) -> None:
    """manifest가 `extension`을 적으면 그 확장의 서버 부분이다 — 상태·연결 방식이 그 일꾼에서 온다."""
    register_bot_ui(client)
    worker = consumer(client, tmp_path, app_id="uia", extension={"id": "ui-automation", "version": "0.1.0"},
                      topics=["uia"])
    fetch(client, worker, topic="uia")
    found = client.get("/api/v1/resources/extensions/ui-automation", headers=READ_AUTH).json()
    assert (found["service_app_id"], found["protocol"], found["status"]) == ("uia", "chk-c11", "ok")
    assert found["installed_on"]["hosts"] == 1


def test_a_pc_is_counted_once_even_if_a_second_key_tries_to_register(client: TestClient) -> None:
    """PC 하나는 한 번만 세어진다 — 같은 `machine_id`를 다른 키가 등록하면 409다 (C4 「키 묶기」).

    PC 하나에 PC 실행기 행이 둘 생기면 「확장이 깔린 PC 수」와 런타임 수가 함께 부푼다.
    """
    register_bot_ui(client)
    made = client.post("/api/v1/center-keys", json={"name": "같은 PC 두 번째 키", "type": "bot_ui"}, headers=ADMIN)
    second = client.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": hashlib.sha256(b"pc1").hexdigest(),
            "name": "현장 PC 1",
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0", "worker": "0.3.0"},
        },
        headers={"Authorization": f"Bearer {made.json()['key']}"},
    )
    assert second.status_code == 409 and second.json()["code"] == "machine_already_registered"

    runtimes = client.get("/api/v1/resources?type=runtime", headers=READ_AUTH).json()
    assert len(runtimes["items"]) == 1, "같은 PC가 런타임 두 줄로 세어지면 안 된다"
    extensions = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()
    one = next(x for x in extensions["items"] if x["id"] == "ui-automation")
    assert one["installed_on"] == {"hosts": 1, "by_version": {"0.1.0": 1}}


def test_an_app_without_an_extension_is_not_an_extension(client: TestClient, tmp_path: Path) -> None:
    """서비스 앱이 `extension`을 적지 않으면 **확장 목록에 끼지 않는다** (C11 manifest).

    확장이 아닌 서비스 앱도 있다 — 모든 앱을 확장으로 세면 「확장 1개」가 거짓이 된다.
    """
    consumer(client, tmp_path)
    found = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()
    assert [one["id"] for one in found["items"]] == []


def test_the_whole_list_has_every_kind(client: TestClient, tmp_path: Path) -> None:
    register_bot_ui(client)
    consumer(client, tmp_path)

    found = client.get("/api/v1/resources", headers=READ_AUTH).json()
    assert found["fetched_at"]
    kinds = {
        "extension" if "installed_on" in one else
        "service_app" if "app_id" in one else
        "runtime" if "host" in one else "contributed"
        for one in found["items"]
    }
    assert kinds == {"extension", "service_app", "runtime"}, "고정 종류가 다 온다"


def test_an_unknown_type_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/resources?type=없는것", headers=READ_AUTH).status_code == 422


def test_contributed_is_empty_until_a_consumer_uploads_a_catalog(client: TestClient) -> None:
    """기여 자원은 일꾼이 카탈로그를 올려야 생긴다 (`test_m5_catalog.py`)."""
    assert client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"] == []


def test_a_bot_ui_key_can_read_resources(client: TestClient) -> None:
    """실행하는 쪽도 리소스를 읽는다 (C7 §전송 — 권한에 PC 실행기 키가 있다)."""
    made = client.post(
        "/api/v1/center-keys", json={"name": "PC 키", "type": "bot_ui"}, headers=ADMIN
    )
    raw = made.json()["key"]
    answer = client.get("/api/v1/resources", headers={"Authorization": f"Bearer {raw}"})
    assert answer.status_code == 200


# ─────────────────────────── 누락 검사 (C7) ───────────────────────────


def test_a_missing_service_app_is_a_warning_on_the_package(client: TestClient) -> None:
    """업로드할 때는 **경고만** 한다 (C7) — 패키지 정보에 실린다."""
    info = upload(
        client,
        package_zip(requires={"service_apps": [{"app_id": "없는앱", "operations": ["lookup"]}]}),
    )
    found = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert [(one["type"], one["reason"]) for one in found["missing_resources"]] == [
        ("service_app", "not_registered")
    ]


def test_a_consumer_clears_the_warning(client: TestClient, tmp_path: Path) -> None:
    """누락은 **읽을 때** 센다 — 일꾼이 붙으면 다시 읽기만 해도 사라진다."""
    info = upload(
        client,
        package_zip(requires={"service_apps": [NEEDS_DEMO]}),
    )
    before = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert before["missing_resources"]

    consumer(client, tmp_path)
    after = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert after["missing_resources"] == []


def test_a_missing_operation_is_noticed(client: TestClient, tmp_path: Path) -> None:
    consumer(client, tmp_path)
    info = upload(
        client,
        package_zip(
            requires={"service_apps": [{"app_id": APP, "operations": ["없는작업"]}]}
        ),
    )
    found = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert [(one["type"], one["id"], one["reason"]) for one in found["missing_resources"]] == [
        ("operation", "demo.directory.없는작업", "not_found")
    ]


def test_a_quiet_consumer_does_not_block_deployment(client: TestClient, tmp_path: Path, store: Store) -> None:
    """서비스 앱이 잠시 조용한 것으로는 막지 않는다 — 막는 것은 확장 누락·해시 불일치와 R8뿐이다 (C7)."""
    from chaeksas.contracts.manifest import Manifest  # noqa: PLC0415
    from chaeksas.contracts.resources import blocking_at_deploy, missing  # noqa: PLC0415

    consumer(client, tmp_path)  # 들었지만 한 번도 가져가지 않았다 — `unreachable`
    info = upload(client, package_zip(requires={"service_apps": [NEEDS_DEMO]}))
    row = store.row("SELECT manifest_json FROM packages WHERE id = ? AND version = ?", (info["id"], info["version"]))
    assert row is not None
    found = missing(Manifest.model_validate(json.loads(row["manifest_json"])), resources.index(store))
    assert blocking_at_deploy(found) == []

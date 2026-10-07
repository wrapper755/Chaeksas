"""리소스 목록 — 서비스 앱 등록과 네 종류 모으기 (C7, M5 조각 8).

진짜 Center를 in-process로 띄우고, **진짜 서비스 앱**(`service_kit`으로 만든 것)을
127.0.0.1에 올려 Center가 그 공개 정보를 읽게 한다.

거듭 보는 것 다섯.

1. **등록은 manifest를 읽어 본 뒤에** 된다 — 읽지 못하면 422다 (「등록은 됐는데 아무것도
   모른다」를 만들지 않는다).
2. **주소는 한 곳에서만 바뀐다** — 다른 앱을 가리키는 주소로 바꾸면 거부한다.
3. **쓰는 Bot이 있으면 해제하지 못한다** (409 `in_use`).
4. **툴팩·런타임·확장은 따로 등록받지 않는다** — Center가 이미 가진 것에서 모은다.
5. **서비스 앱이 꺼져 있다고 배포를 막지 않는다** — 막는 것은 확장 누락·해시 불일치뿐이다.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
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

#: 데모 앱을 쓰는 BPM 프로세스의 `requires.service_apps` 한 줄.
#: `key_ref`는 **필수이고 이름 규칙을 따른다** (C1 R4 — 키 값이 섞여 들어가지 못하게).
NEEDS_DEMO = {"app_id": "demo.directory", "operations": ["lookup"], "key_ref": "demo-key"}


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


# ─────────────────────────── 진짜 서비스 앱 하나 ───────────────────────────


@pytest.fixture
def app_url(monkeypatch: Any) -> Iterator[str]:
    """`service_kit`으로 만든 진짜 앱을 127.0.0.1에 띄운다 — Center가 HTTP로 읽는다."""
    from chaeksas.contracts.service_app import ServiceAppManifest
    from chaeksas.service_kit.app import create_app as create_service_app
    from chaeksas.service_kit.stores import InMemoryKeyStore

    manifest = ServiceAppManifest.model_validate(
        {
            "schema": 1,
            "app_id": "demo.directory",
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
    )
    made = create_service_app(
        manifest, {"lookup": lambda request, caller: {"이름": "홍길동"}}, keys=InMemoryKeyStore()
    )
    config = uvicorn.Config(made, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():  # pragma: no cover — 띄우지 못했다
            raise RuntimeError("서비스 앱을 띄우지 못했다")
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


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


# ─────────────────────────── 서비스 앱 등록 (C7) ───────────────────────────


def test_registering_reads_the_manifest(client: TestClient, app_url: str) -> None:
    """**등록은 manifest를 읽어 본 뒤에** 된다 — 앱이 자기 id를 정한다 (C11)."""
    answer = client.post(
        "/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN
    )
    assert answer.status_code == 201, answer.text
    found = answer.json()
    assert found["app_id"] == "demo.directory"
    assert found["name"] == "사원 디렉터리" and found["category"] == "business"
    assert found["status"] == "ok", "방금 읽었으니 상태를 안다"
    assert [one["name"] for one in found["operations"]] == ["lookup"]
    assert found["base_url"] == app_url


def test_an_unreachable_app_is_not_registered(client: TestClient) -> None:
    """읽지 못하면 등록하지 않는다 — 「등록은 됐는데 아무것도 모른다」를 만들지 않는다."""
    answer = client.post(
        "/api/v1/resources/service-apps",
        json={"base_url": "http://127.0.0.1:9"},  # 아무도 듣지 않는 포트
        headers=ADMIN,
    )
    assert answer.status_code == 422 and answer.json()["code"] == "manifest_unreachable"
    assert client.get("/api/v1/resources?type=service_app", headers=READ_AUTH).json()["items"] == []


def test_only_the_admin_registers(client: TestClient, app_url: str) -> None:
    assert client.post(
        "/api/v1/resources/service-apps", json={"base_url": app_url}, headers=READ_AUTH
    ).status_code == 403


def test_the_address_has_one_source(client: TestClient, app_url: str) -> None:
    """`PUT`이 **주소의 유일한 출처**다 (C7). 다른 앱을 가리키면 거부한다."""
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)

    moved = client.put(
        "/api/v1/resources/service-apps/demo.directory",
        json={"base_url": f"{app_url}/"},
        headers=ADMIN,
    )
    assert moved.status_code == 200

    # 닿지 못하는 주소로는 바꿀 수 있다 (환경을 먼저 바꾸고 앱을 띄울 수 있다).
    later = client.put(
        "/api/v1/resources/service-apps/demo.directory",
        json={"base_url": "http://127.0.0.1:9"},
        headers=ADMIN,
    )
    assert later.status_code == 200
    assert later.json()["status"] == "unreachable"
    assert later.json()["name"] == "사원 디렉터리", "마지막으로 읽은 manifest는 남는다"


def test_an_app_in_use_cannot_be_unregistered(client: TestClient, app_url: str) -> None:
    """**쓰는 Bot이 있으면 해제하지 못한다** (409 `in_use`)."""
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    assert client.delete(
        "/api/v1/resources/service-apps/demo.directory", headers=ADMIN
    ).status_code == 204

    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    upload(
        client,
        package_zip(requires={"service_apps": [NEEDS_DEMO]}),
    )
    blocked = client.delete("/api/v1/resources/service-apps/demo.directory", headers=ADMIN)
    assert blocked.status_code == 409 and blocked.json()["code"] == "in_use"
    assert blocked.json()["detail"]["used_by"] == ["hr.onboarding@1.0.0"]


def test_used_by_shows_the_packages(client: TestClient, app_url: str) -> None:
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    upload(
        client,
        package_zip(requires={"service_apps": [NEEDS_DEMO]}),
    )
    found = client.get("/api/v1/resources/service-apps/demo.directory", headers=READ_AUTH).json()
    assert found["used_by"] == ["hr.onboarding@1.0.0"]


def test_refresh_reads_again_right_away(client: TestClient, app_url: str, store: Store) -> None:
    """「새로 고침」은 간격을 무시한다 (C7)."""
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    with store.tx() as cur:
        cur.execute("UPDATE service_apps SET status = 'unknown', status_reasons = '[]'")

    answer = client.post("/api/v1/resources/refresh", json={}, headers=ADMIN)
    assert answer.status_code == 200
    assert [one["status"] for one in answer.json()["items"]] == ["ok"]


# ─────────────────────────── 모으는 종류 (C7) ───────────────────────────


def test_toolpacks_come_from_uploaded_packages(client: TestClient) -> None:
    """툴팩은 **따로 등록받지 않는다** — 올라온 `kind=toolpack` 패키지에서 모은다."""
    upload(
        client,
        package_zip(
            "ops.excel-tools",
            "2.0.0",
            kind="toolpack",
            extra={"provides": {"tools": [{"name": "xlsx_read", "domain": "doc"}]}},
        ),
    )
    found = client.get("/api/v1/resources?type=toolpack", headers=READ_AUTH).json()
    assert [one["id"] for one in found["items"]] == ["ops.excel-tools"]
    assert found["items"][0]["status"] == "candidate"
    assert [one["name"] for one in found["items"][0]["tools"]] == ["xlsx_read"]


def test_runtimes_come_from_bot_ui_reports(client: TestClient) -> None:
    """런타임은 C4가 보고한 그대로다."""
    bot_ui_id = register_bot_ui(client)
    found = client.get("/api/v1/resources?type=runtime", headers=READ_AUTH).json()
    [one] = found["items"]
    assert one["host"] == {"type": "bot_ui", "id": bot_ui_id, "name": "현장 PC 1"}
    assert one["browsers"] == ["chromium-130"] and one["desktop_backend"] == "uia"
    assert one["versions"]["worker"] == "0.3.0"


def test_extensions_merge_reports_and_manifests(client: TestClient, app_url: str) -> None:
    """확장은 **실행하는 쪽의 보고와 서비스 앱 manifest를 합친** 것이다 (C7)."""
    register_bot_ui(client)
    register_bot_ui(client, name="현장 PC 2", seed="pc2")
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)

    found = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()
    one = next(x for x in found["items"] if x["id"] == "ui-automation")
    assert one["installed_on"] == {"hosts": 2, "by_version": {"0.1.0": 2}}, "몇 대에 깔렸나"
    assert one["status"] == "n/a", "서버 부분이 없는 확장이다"


def test_an_app_without_an_extension_is_not_an_extension(client: TestClient, app_url: str) -> None:
    """서비스 앱이 `extension`을 적지 않으면 **확장 목록에 끼지 않는다** (C11 manifest).

    확장이 아닌 서비스 앱도 있다 — 모든 앱을 확장으로 세면 「확장 1개」가 거짓이 된다.
    """
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    found = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()
    assert [one["id"] for one in found["items"]] == []


def test_the_whole_list_has_every_kind(client: TestClient, app_url: str) -> None:
    register_bot_ui(client)
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    upload(client, package_zip("ops.tools", "1.0.0", kind="toolpack"))

    found = client.get("/api/v1/resources", headers=READ_AUTH).json()
    assert found["fetched_at"]
    kinds = {
        "extension" if "installed_on" in one else
        "service_app" if "app_id" in one else
        "runtime" if "host" in one else "toolpack"
        for one in found["items"]
    }
    assert kinds == {"extension", "service_app", "runtime", "toolpack"}, "네 종류가 다 온다"


def test_an_unknown_type_is_refused(client: TestClient) -> None:
    assert client.get("/api/v1/resources?type=없는것", headers=READ_AUTH).status_code == 422


def test_contributed_is_empty_for_now(client: TestClient) -> None:
    """확장 기여 자원은 아직 모으지 않는다 — **빈 목록이 「없다」는 뜻은 아니다**."""
    assert client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"] == []


def test_a_bot_ui_key_can_read_resources(client: TestClient) -> None:
    """실행하는 쪽도 리소스를 읽는다 (C7 §전송 — 권한에 Bot UI 키가 있다)."""
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
        package_zip(requires={"service_apps": [{"app_id": "없는앱", "operations": ["lookup"], "key_ref": "demo-key"}]}),
    )
    found = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert [(one["type"], one["reason"]) for one in found["missing_resources"]] == [
        ("service_app", "not_registered")
    ]


def test_registering_the_app_clears_the_warning(client: TestClient, app_url: str) -> None:
    """누락은 **읽을 때** 센다 — 앱을 등록하면 다시 읽기만 해도 사라진다."""
    info = upload(
        client,
        package_zip(requires={"service_apps": [NEEDS_DEMO]}),
    )
    before = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert before["missing_resources"]

    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    after = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert after["missing_resources"] == []


def test_a_missing_operation_is_noticed(client: TestClient, app_url: str) -> None:
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    info = upload(
        client,
        package_zip(
            requires={"service_apps": [{"app_id": "demo.directory", "operations": ["없는작업"], "key_ref": "demo-key"}]}
        ),
    )
    found = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert [(one["type"], one["id"], one["reason"]) for one in found["missing_resources"]] == [
        ("operation", "demo.directory.없는작업", "not_found")
    ]


def test_index_does_not_poke_the_apps(client: TestClient, app_url: str, store: Store) -> None:
    """패키지 목록을 읽을 때마다 서비스 앱을 깨우지 않는다 (`probe=False`)."""
    client.post("/api/v1/resources/service-apps", json={"base_url": app_url}, headers=ADMIN)
    with store.tx() as cur:
        cur.execute("UPDATE service_apps SET checked_at = NULL, status = 'unknown'")
    resources.index(store, probe=False)
    row = store.row("SELECT status FROM service_apps")
    assert row is not None
    assert row["status"] == "unknown", "두드리지 않았다"

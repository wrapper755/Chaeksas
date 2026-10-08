"""확장 기여 자원 — 카탈로그를 읽어 쌓는다 (C7·C11·C13 §5, M5 조각 10).

진짜 Center와 **진짜 UI 자동화 앱**을 띄워, Center가 그 앱의 `/v1/catalog`를 읽어 「UI 화면」을
리소스 목록에 싣는 것까지 본다.

거듭 보는 것 다섯.

1. **내장 확장의 카탈로그는 서버 부분이 알린다** (C11 `resources`) — 정의가 Center에 없다.
2. **`revision`이 같으면 다시 쓰지 않는다** — 같은 것을 다시 쓰면 계획 캐시가 공연히 버려진다.
3. **닿지 못하면 들고 있던 것을 지우지 않는다** — 사유만 남긴다.
4. **Center는 `data`를 해석하지 않는다** (C13 §5) — 그대로 넘긴다.
5. **`requires.resources` 누락 검사가 이제 실제로 돈다** — 등록하면 경고가 사라진다.
"""

from __future__ import annotations

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
AT = "2026-10-08T09:00:00+09:00"

#: 그 자원을 쓰는 BPM 프로세스의 `requires.resources` 한 줄 (C1).
NEEDS_PAGE = {"type": "ui_page", "id": "erp.order.form"}


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


# ─────────────────────── 카탈로그를 주는 앱 (손으로 만든 것) ───────────────────────


class Catalogue:
    """카탈로그를 주는 작은 앱. **판과 항목을 시험이 바꿔 가며** Center의 반응을 본다."""

    def __init__(self) -> None:
        self.revision = 1
        self.items: list[dict[str, Any]] = [
            {
                "type": "ui_page",
                "id": "erp.order.form",
                "name": "ERP 주문 입력",
                "summary": "요소 12개 · 사용 중 9",
                "updated_at": AT,
                "data": {"elements": 12, "platform": "web"},
            }
        ]
        self.reads = 0
        self.fail = False


@pytest.fixture
def app_url() -> Iterator[tuple[str, Catalogue]]:
    """`service_kit` 앱 + 카탈로그 경로를 127.0.0.1에 띄운다 (C11 `resources`가 가리킨다)."""
    from fastapi import Response

    from chaeksas.contracts.service_app import ServiceAppManifest
    from chaeksas.service_kit.app import create_app as create_service_app
    from chaeksas.service_kit.stores import InMemoryKeyStore

    state = Catalogue()
    manifest = ServiceAppManifest.model_validate(
        {
            "schema": 1,
            "app_id": "demo.pages",
            "name": "화면 레지스트리",
            "version": "1.0.0",
            "category": "system",
            "console_url": "http://127.0.0.1:8599",
            "operations": [{"name": "noop", "modes": ["deterministic"]}],
            "extension": {"id": "demo-ui", "version": "1.0.0"},
            # **이것이 이번 조각의 요점이다** — 앱이 자기 카탈로그를 알린다 (C11).
            "resources": [{"type": "ui_page", "catalog_url": "/v1/catalog", "label": "UI 화면"}],
        }
    )
    made = create_service_app(
        manifest, {"noop": lambda request, caller: {}}, keys=InMemoryKeyStore()
    )

    @made.get("/v1/catalog")
    def catalog() -> Any:
        state.reads += 1
        if state.fail:
            return Response(status_code=503)
        return {"schema": 1, "revision": state.revision, "items": state.items}

    config = uvicorn.Config(made, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        if not thread.is_alive():  # pragma: no cover
            raise RuntimeError("앱을 띄우지 못했다")
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}", state
    server.should_exit = True
    thread.join(timeout=5)


def register_app(client: TestClient, base_url: str) -> dict[str, Any]:
    answer = client.post(
        "/api/v1/resources/service-apps", json={"base_url": base_url}, headers=ADMIN
    )
    assert answer.status_code in (200, 201), answer.text
    return dict(answer.json())


def package_zip(requires: dict[str, Any] | None = None) -> bytes:
    import tempfile

    from chaeksas.contracts.hashing import content_hash_zip

    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": "erp.order-entry",
        "version": "1.0.0",
        "name": "주문 입력",
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_main",
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
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


# ─────────────────────────── 읽어 쌓기 (C7·C13 §5) ───────────────────────────


def test_the_app_advertises_its_catalog(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    """**내장 확장의 카탈로그는 서버 부분이 알린다** (C11 `resources`) — 정의가 Center에 없다."""
    base, _state = app_url
    register_app(client, base)
    found = client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()
    [one] = found["items"]
    assert one["resource_type"] == "ui_page" and one["id"] == "erp.order.form"
    assert one["name"] == "ERP 주문 입력" and one["summary"] == "요소 12개 · 사용 중 9"
    assert one["extension_id"] == "demo-ui", "어느 확장이 기여했나 (manifest의 `extension`)"
    assert one["revision"] == 1


def test_center_does_not_interpret_the_data(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    """**`data`는 그대로 넘긴다** (C13 §5) — 플랫폼은 확장 고유 내용을 모른다."""
    base, _state = app_url
    register_app(client, base)
    [one] = client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"]
    assert one["data"] == {"elements": 12, "platform": "web"}


def test_the_kinds_become_tabs(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    """CON-07은 **자원 종류마다 탭 하나**다 (C7) — 그 목록이 여기서 온다."""
    base, _state = app_url
    register_app(client, base)
    found = client.get("/api/v1/resources/contributed-kinds", headers=READ_AUTH).json()
    [one] = found["items"]
    assert one["resource_type"] == "ui_page" and one["label"] == "UI 화면"
    assert one["count"] == 1 and one["extensions"] == ["demo-ui"] and one["errors"] == []


def test_one_resource_by_id(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    base, _state = app_url
    register_app(client, base)
    one = client.get(
        "/api/v1/resources/contributed/ui_page/erp.order.form", headers=READ_AUTH
    ).json()
    assert one["name"] == "ERP 주문 입력"
    assert client.get(
        "/api/v1/resources/contributed/ui_page/없는것", headers=READ_AUTH
    ).status_code == 404


def test_the_same_revision_is_not_rewritten(
    client: TestClient, store: Store, app_url: tuple[str, Catalogue]
) -> None:
    """**판이 같으면 항목을 다시 쓰지 않는다** (C7) — 계획 캐시를 공연히 버리지 않게."""
    base, state = app_url
    register_app(client, base)  # 등록이 카탈로그를 한 번 읽는다
    assert resources.refresh_catalogs(store, force=True) == 0, "같은 판이면 갱신 0"

    state.revision = 2
    state.items[0]["name"] = "ERP 주문 입력 (고침)"
    assert resources.refresh_catalogs(store, force=True) == 1

    [one] = client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"]
    assert one["name"] == "ERP 주문 입력 (고침)" and one["revision"] == 2


def test_items_that_disappear_are_dropped(
    client: TestClient, store: Store, app_url: tuple[str, Catalogue]
) -> None:
    """카탈로그가 더 안 주는 항목은 지운다 — **그 출처가 준 것으로 맞춘다**."""
    base, state = app_url
    register_app(client, base)
    state.revision = 2
    state.items = []
    resources.refresh_catalogs(store, force=True)
    assert client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"] == []


def test_an_unreachable_catalog_keeps_what_we_have(
    client: TestClient, store: Store, app_url: tuple[str, Catalogue]
) -> None:
    """**닿지 못하면 지우지 않는다** — 사유만 남긴다 (앱이 잠깐 꺼진 것일 수 있다)."""
    base, state = app_url
    register_app(client, base)
    state.fail = True
    resources.refresh_catalogs(store, force=True)

    assert len(client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"]) == 1
    kinds = client.get("/api/v1/resources/contributed-kinds", headers=READ_AUTH).json()["items"]
    assert kinds[0]["errors"] and "http_503" in kinds[0]["errors"][0]


def test_reading_respects_the_interval(
    client: TestClient, store: Store, app_url: tuple[str, Catalogue]
) -> None:
    """**목록을 읽을 때마다 카탈로그를 두드리지 않는다** (5분 간격, C7)."""
    base, state = app_url
    register_app(client, base)
    after_register = state.reads
    assert after_register == 1, "등록이 한 번 읽는다"

    client.get("/api/v1/resources?type=contributed", headers=READ_AUTH)
    client.get("/api/v1/resources?type=contributed", headers=READ_AUTH)
    assert state.reads == after_register, "간격 안이라 다시 읽지 않았다"

    assert resources.refresh_catalogs(store, force=True) >= 0
    assert state.reads > after_register, "「새로 고침」은 간격을 무시한다"


def test_refresh_reads_catalogs_too(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    base, state = app_url
    register_app(client, base)
    before = state.reads
    assert client.post("/api/v1/resources/refresh", json={}, headers=ADMIN).status_code == 200
    assert state.reads > before


def test_a_catalog_that_sends_another_kind_is_ignored(
    client: TestClient, store: Store, app_url: tuple[str, Catalogue]
) -> None:
    """선언한 종류만 받는다 — 카탈로그가 남의 종류를 담아 보내도 끼워 넣지 않는다."""
    base, state = app_url
    register_app(client, base)
    state.revision = 3
    state.items = [
        {"type": "ui_page", "id": "a", "name": "A"},
        {"type": "toolpack", "id": "b", "name": "B"},
    ]
    resources.refresh_catalogs(store, force=True)
    found = client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"]
    assert [one["id"] for one in found] == ["a"]


def test_filtering_by_resource_type(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    base, _state = app_url
    register_app(client, base)
    assert len(
        client.get("/api/v1/resources?type=contributed&resource_type=ui_page", headers=READ_AUTH)
        .json()["items"]
    ) == 1
    assert client.get(
        "/api/v1/resources?type=contributed&resource_type=없는종류", headers=READ_AUTH
    ).json()["items"] == []


# ─────────────────────────── 누락 검사가 이제 돈다 (C7) ───────────────────────────


def test_a_missing_page_is_warned_then_cleared(
    client: TestClient, app_url: tuple[str, Catalogue]
) -> None:
    """**`requires.resources` 검사가 이제 실제로 돈다** — 등록하면 경고가 사라진다."""
    base, _state = app_url
    info = upload(client, package_zip(requires={"resources": [NEEDS_PAGE]}))

    before = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert [(one["type"], one["reason"]) for one in before["missing_resources"]] == [
        ("resource", "not_found")
    ]

    register_app(client, base)
    after = client.get(
        f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH
    ).json()
    assert after["missing_resources"] == []


def test_a_missing_page_does_not_block_deployment(
    client: TestClient, store: Store, app_url: tuple[str, Catalogue]
) -> None:
    """기여 자원 누락은 **배포를 막지 않는다** (C7 — 막는 것은 확장 누락·해시 불일치와 R8)."""
    from chaeksas.contracts.manifest import Manifest
    from chaeksas.contracts.resources import blocking_at_deploy, missing

    info = upload(client, package_zip(requires={"resources": [NEEDS_PAGE]}))
    row = store.row(
        "SELECT manifest_json FROM packages WHERE id = ? AND version = ?",
        (info["id"], info["version"]),
    )
    assert row is not None
    manifest = Manifest.model_validate(json.loads(row["manifest_json"]))
    found = missing(manifest, resources.index(store, probe=False))
    assert [one.type for one in found] == ["resource"]
    assert blocking_at_deploy(found) == [], "배포는 막지 않는다"


def test_used_by_shows_the_packages(client: TestClient, app_url: tuple[str, Catalogue]) -> None:
    base, _state = app_url
    register_app(client, base)
    upload(client, package_zip(requires={"resources": [NEEDS_PAGE]}))
    one = client.get(
        "/api/v1/resources/contributed/ui_page/erp.order.form", headers=READ_AUTH
    ).json()
    assert one["used_by"] == ["erp.order-entry@1.0.0"]


# ─────────────────── 진짜 UI 자동화 앱으로 (C9 공개 카탈로그) ───────────────────


def test_the_real_ui_automation_app_is_read(client: TestClient, tmp_path: Path) -> None:
    """**진짜 UI 자동화 앱**의 카탈로그를 Center가 읽는다 — 내장 확장의 한 바퀴다.

    등록된 화면이 없으면 항목도 없다. 요점은 **manifest가 가리킨 경로를 Center가 찾아간다**는
    것이다 (C11 `resources` → C13 §5).
    """
    from chaeksas.ext.ui_automation.service.app import CATALOG_PATH, manifest

    found = manifest()
    assert [one.catalog_url for one in found.resources] == [CATALOG_PATH]
    assert [one.type for one in found.resources] == ["ui_page"]
    assert found.extension is not None and found.extension.id == "ui-automation"

"""확장 기여 자원 — 일꾼이 올린 카탈로그를 쌓는다 (C7·C13 §5·C15, ADR-0102).

**Center는 카탈로그를 읽으러 가지 않는다.** 서버 부분의 일꾼이 manifest의 `resources`로 종류를 알리고,
카탈로그는 판(`revision`)이 바뀌면 `PUT /consumers/self/catalogs/{type}`로 올린다 — 진짜 Center와 제품의
들이기·`Consumer.publish`로 본다.

| 보는 것 | 왜 |
| --- | --- |
| 올린 항목이 목록에 뜨고 **어느 확장**의 것인지 manifest의 `extension`이 말한다 | 내장·사내 확장 정의는 Center에 없다 |
| Center는 `data`를 해석하지 않는다 | C13 §5 |
| 종류는 manifest의 `resources`가 정하고 탭이 된다 | CON-07 |
| **`revision`이 같으면 다시 쓰지 않는다**, 판이 바뀌면 없어진 항목은 지운다 | 계획 캐시를 공연히 버리지 않는다 |
| 남의 종류·남의 토픽·틀린 모양은 받지 않는다 | 일꾼이 남의 자원을 자처하지 못한다 |
| `requires.resources` 누락은 경고만, 올리면 사라진다 | 배포를 막는 것은 확장 누락·해시 불일치와 R8뿐이다 |
| `page_id` → 그 앱의 관리 콘솔 주소로 이어진다 | CON-01 「UI 태스크」 링크 |
"""

from __future__ import annotations

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
AT = "2026-10-08T09:00:00+09:00"
APP = "demo.pages"

#: 그 자원을 쓰는 BPM 프로세스의 `requires.resources` 한 줄 (C1).
NEEDS_PAGE = {"type": "ui_page", "id": "erp.order.form"}

MANIFEST: dict[str, Any] = {
    "schema": 1,
    "app_id": APP,
    "name": "화면 레지스트리",
    "version": "1.0.0",
    "category": "system",
    "console_url": "http://127.0.0.1:8599",
    "operations": [{"name": "noop", "modes": ["deterministic"]}],
    "extension": {"id": "demo-ui", "version": "1.0.0"},
    # 앱이 **자기 카탈로그의 종류**를 알린다 (C11) — 탭 이름도 여기서 온다.
    "resources": [{"type": "ui_page", "catalog_url": "/v1/catalog", "label": "UI 화면"}],
}


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


@pytest.fixture
def worker(client: TestClient, tmp_path: Path) -> dict[str, str]:
    """카탈로그를 올릴 일꾼 — `demo.pages` 토픽으로 들었다."""
    tokens = enroll(client, topics=[APP], manifests=[MANIFEST], folder=tmp_path / "consumer")
    return {"Authorization": f"Bearer {tokens.token()}"}


def page(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "ui_page",
        "id": "erp.order.form",
        "name": "ERP 주문 입력",
        "summary": "요소 12개 · 사용 중 9",
        "updated_at": AT,
        "data": {"elements": 12, "platform": "web"},
    }
    return body | over


def put(
    client: TestClient,
    worker: dict[str, str],
    *,
    revision: int | None = 1,
    items: list[dict[str, Any]] | None = None,
    app_id: str = APP,
) -> Any:
    answer = client.put(
        "/api/v1/consumers/self/catalogs/ui_page",
        json={
            "app_id": app_id,
            "catalog": {"schema": 1, "revision": revision, "items": [page()] if items is None else items},
        },
        headers=worker,
    )
    return answer


def contributed(client: TestClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = client.get("/api/v1/resources?type=contributed", headers=READ_AUTH).json()["items"]
    return found


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


# ─────────────────────────── 쌓기 (C7·C13 §5) ───────────────────────────


def test_an_uploaded_catalog_becomes_resources(client: TestClient, worker: dict[str, str]) -> None:
    answer = put(client, worker)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"resource_type": "ui_page", "revision": 1, "stored": True}
    [one] = contributed(client)
    assert one["resource_type"] == "ui_page" and one["id"] == "erp.order.form"
    assert one["name"] == "ERP 주문 입력" and one["summary"] == "요소 12개 · 사용 중 9"
    assert one["extension_id"] == "demo-ui", "어느 확장이 기여했나 (manifest의 `extension`)"
    assert one["revision"] == 1


def test_center_does_not_interpret_the_data(client: TestClient, worker: dict[str, str]) -> None:
    """**`data`는 그대로 넘긴다** (C13 §5) — 플랫폼은 확장 고유 내용을 모른다."""
    put(client, worker)
    [one] = contributed(client)
    assert one["data"] == {"elements": 12, "platform": "web"}


def test_the_kinds_become_tabs(client: TestClient, worker: dict[str, str]) -> None:
    """CON-07은 **자원 종류마다 탭 하나**다 (C7) — 종류는 manifest가, 수는 올린 것이 말한다."""
    found = client.get("/api/v1/resources/contributed-kinds", headers=READ_AUTH).json()["items"]
    assert [(one["resource_type"], one["label"], one["count"]) for one in found] == [("ui_page", "UI 화면", 0)]
    put(client, worker)
    [one] = client.get("/api/v1/resources/contributed-kinds", headers=READ_AUTH).json()["items"]
    assert one["count"] == 1 and one["extensions"] == ["demo-ui"] and one["errors"] == []


def test_one_resource_by_id(client: TestClient, worker: dict[str, str]) -> None:
    put(client, worker)
    one = client.get("/api/v1/resources/contributed/ui_page/erp.order.form", headers=READ_AUTH).json()
    assert one["name"] == "ERP 주문 입력"
    assert client.get("/api/v1/resources/contributed/ui_page/없는것", headers=READ_AUTH).status_code == 404


def test_the_same_revision_is_not_rewritten(client: TestClient, worker: dict[str, str]) -> None:
    """**판이 같으면 항목을 다시 쓰지 않는다** (C7) — 계획 캐시를 공연히 버리지 않게."""
    put(client, worker)
    same = put(client, worker, items=[page(name="몰래 고침")])
    assert same.json()["stored"] is False
    assert contributed(client)[0]["name"] == "ERP 주문 입력"

    put(client, worker, revision=2, items=[page(name="ERP 주문 입력 (고침)")])
    [one] = contributed(client)
    assert one["name"] == "ERP 주문 입력 (고침)" and one["revision"] == 2


def test_a_catalog_without_a_revision_is_always_written(client: TestClient, worker: dict[str, str]) -> None:
    """판이 없으면 같은지 모른다 — 매번 쓴다."""
    put(client, worker, revision=None)
    again = put(client, worker, revision=None, items=[page(name="새 이름")])
    assert again.json()["stored"] is True and contributed(client)[0]["name"] == "새 이름"


def test_items_that_disappear_are_dropped(client: TestClient, worker: dict[str, str]) -> None:
    """카탈로그가 더 안 주는 항목은 지운다 — **그 출처가 준 것으로 맞춘다**."""
    put(client, worker)
    put(client, worker, revision=2, items=[])
    assert contributed(client) == []


def test_a_catalog_that_sends_another_kind_is_ignored(client: TestClient, worker: dict[str, str]) -> None:
    """올린 종류만 받는다 — 카탈로그가 남의 종류를 담아 보내도 끼워 넣지 않는다."""
    put(client, worker, items=[page(id="a", name="A"), {"type": "report", "id": "b", "name": "B"}])
    assert [one["id"] for one in contributed(client)] == ["a"]


def test_a_catalog_for_another_topic_is_refused(client: TestClient, worker: dict[str, str]) -> None:
    refused = put(client, worker, app_id="hr.payroll")
    assert refused.status_code == 403 and refused.json()["code"] == "topic_not_granted"
    broken = client.put(
        "/api/v1/consumers/self/catalogs/ui_page", json={"app_id": APP, "catalog": {"items": "x"}}, headers=worker
    )
    assert broken.status_code == 422 and broken.json()["code"] == "input_invalid"
    assert put(client, ADMIN).status_code == 403, "일꾼 토큰으로만 올린다"
    assert contributed(client) == []


def test_filtering_by_resource_type(client: TestClient, worker: dict[str, str]) -> None:
    put(client, worker)
    picked = client.get("/api/v1/resources?type=contributed&resource_type=ui_page", headers=READ_AUTH)
    assert len(picked.json()["items"]) == 1
    other = client.get("/api/v1/resources?type=contributed&resource_type=없는종류", headers=READ_AUTH)
    assert other.json()["items"] == []


def test_the_consumer_publishes_through_the_same_path(
    client: TestClient, tmp_path: Path, worker: dict[str, str]
) -> None:
    """제품의 `Consumer.publish()`가 같은 길로 올린다 — 시험이 손으로 부른 것과 결과가 같다."""
    from chaeksas.contracts.extension import Catalog  # noqa: PLC0415
    from chaeksas.contracts.service_app import ServiceAppManifest  # noqa: PLC0415
    from chaeksas.service_kit import Consumer, TokenFile  # noqa: PLC0415
    from chaeksas.service_kit import create_app as create_service_app

    service = create_service_app(
        ServiceAppManifest.model_validate(MANIFEST),
        {"noop": lambda _req, _mode: {}},
        catalogs={"ui_page": lambda: Catalog.model_validate({"schema": 1, "revision": 7, "items": [page()]})},
    ).state.ops
    tokens = TokenFile.at(tmp_path / "consumer")
    Consumer([service], center_url="", tokens=tokens, wait_s=0, client=client).publish()
    [one] = contributed(client)
    assert (one["id"], one["revision"], one["extension_id"]) == ("erp.order.form", 7, "demo-ui")


# ─────────────────────────── 누락 검사 (C7) ───────────────────────────


def test_a_missing_page_is_warned_then_cleared(client: TestClient, worker: dict[str, str]) -> None:
    """**`requires.resources` 검사** — 일꾼이 올리면 경고가 사라진다."""
    info = upload(client, package_zip(requires={"resources": [NEEDS_PAGE]}))
    before = client.get(f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH).json()
    assert [(one["type"], one["reason"]) for one in before["missing_resources"]] == [("resource", "not_found")]

    put(client, worker)
    after = client.get(f"/api/v1/packages/{info['id']}/{info['version']}/info", headers=READ_AUTH).json()
    assert after["missing_resources"] == []


def test_a_missing_page_does_not_block_deployment(client: TestClient, store: Store) -> None:
    """기여 자원 누락은 **배포를 막지 않는다** (C7 — 막는 것은 확장 누락·해시 불일치와 R8)."""
    from chaeksas.contracts.manifest import Manifest  # noqa: PLC0415
    from chaeksas.contracts.resources import blocking_at_deploy, missing  # noqa: PLC0415

    info = upload(client, package_zip(requires={"resources": [NEEDS_PAGE]}))
    row = store.row("SELECT manifest_json FROM packages WHERE id = ? AND version = ?", (info["id"], info["version"]))
    assert row is not None
    found = missing(Manifest.model_validate(json.loads(row["manifest_json"])), resources.index(store, probe=False))
    assert [one.type for one in found] == ["resource"]
    assert blocking_at_deploy(found) == [], "배포는 막지 않는다"


def test_used_by_shows_the_packages(client: TestClient, worker: dict[str, str]) -> None:
    put(client, worker)
    upload(client, package_zip(requires={"resources": [NEEDS_PAGE]}))
    one = client.get("/api/v1/resources/contributed/ui_page/erp.order.form", headers=READ_AUTH).json()
    assert one["used_by"] == ["erp.order-entry@1.0.0"]


# ─────────────────── 진짜 UI 자동화 앱으로 (C9 공개 카탈로그) ───────────────────


def test_the_real_ui_automation_app_publishes_its_kind(client: TestClient, tmp_path: Path) -> None:
    """**진짜 UI 자동화 앱**의 일꾼이 올린다 — 내장 확장의 한 바퀴다.

    등록된 화면이 없으면 항목도 없다. 요점은 **manifest가 알린 종류가 탭이 되고**, 카탈로그 함수가
    일꾼의 `publish`로 Center에 닿는다는 것이다 (C11 `resources` → C13 §5 → C15).
    """
    from chaeksas.ext.ui_automation.service.app import CATALOG_PATH, create  # noqa: PLC0415
    from chaeksas.service_kit import Consumer  # noqa: PLC0415

    app = create(db_path=tmp_path / "uia.sqlite3")
    ops = app.state.ops
    assert [one.catalog_url for one in ops.manifest.resources] == [CATALOG_PATH]
    assert ops.manifest.extension is not None and ops.manifest.extension.id == "ui-automation"
    assert set(ops.catalogs) == {"ui_page"}

    tokens = enroll(client, topics=[ops.app_id], manifests=[ops.manifest.to_json_dict()], folder=tmp_path / "uia")
    Consumer([ops], center_url="", tokens=tokens, wait_s=0, client=client).publish()
    [kind] = client.get("/api/v1/resources/contributed-kinds", headers=READ_AUTH).json()["items"]
    assert (kind["resource_type"], kind["label"], kind["extensions"], kind["count"]) == (
        "ui_page", "UI 화면", ["ui-automation"], 0
    )


# ──────── CON-01 「UI 태스크」 → 관리 콘솔 링크 (C3 ↔ C7, `06-screens/center-console.md`) ────────


def console_of(client: TestClient) -> dict[str, str]:
    """콘솔의 `consoleOf`와 **같은 조인** — `page_id` → 그 앱의 관리 콘솔 주소 (두 걸음).

    콘솔이 읽는 것과 같은 두 경로를 읽는다. 이것이 비면 화면에 링크가 없다.
    """
    pages = client.get(
        "/api/v1/resources?type=contributed&resource_type=ui_page", headers=READ_AUTH
    ).json()["items"]
    apps = client.get("/api/v1/resources?type=service_app", headers=READ_AUTH).json()["items"]
    url_of = {one["extension_id"]: one["console_url"] for one in apps if one["extension_id"]}
    return {
        one["id"]: url_of[one["extension_id"]] for one in pages if one["extension_id"] in url_of
    }


def test_a_page_id_leads_to_the_console_url(client: TestClient, worker: dict[str, str]) -> None:
    """**`page_id`에서 관리 콘솔 주소까지 이어진다** (CON-01 「UI 태스크」의 UIA-03 링크).

    실행 기록에는 앱이 없다 — C3 `ui_session`은 `page_id`만 가진다. 이을 수 있는 것은 C7의
    **두 모양이 같은 `extension_id`를 들고 있어서**다. 콘솔이 그 조인을 하므로, 여기서는
    **재료가 정말 오는지**를 본다 (오지 않으면 콘솔은 링크를 못 만든다).
    """
    put(client, worker)
    # C3 `ui_session.page_id`가 가리키는 그 화면이다.
    assert console_of(client)["erp.order.form"] == "http://127.0.0.1:8599"


def test_an_unregistered_page_simply_has_no_link(client: TestClient, worker: dict[str, str]) -> None:
    """**못 이으면 링크만 없다** (U3) — 줄은 그대로 보인다.

    실행은 남았는데 그 화면이 레지스트리에서 지워졌거나(옛 실행) 아직 등록되지 않은 경우다.
    조인이 **조용히 비는** 것이 중요하다 — 터지면 실행 상세에 볼 것이 아무것도 없다.
    """
    put(client, worker)
    assert "erp.order.form" in console_of(client)

    put(client, worker, revision=2, items=[])
    assert console_of(client) == {}, "그 화면이 없어지면 링크도 없다 (줄은 실행 기록이 들고 있다)"


def test_the_console_links_to_the_app_not_to_one_of_its_pages() -> None:
    """**확장 화면 경로를 플랫폼이 적지 않는다** (ADR-0042) — 콘솔 주소 그대로 보낸다.

    집계·그리기는 TypeScript라 파이썬이 돌려 보지 못한다 (`web`에 단위 시험 판이 없다 — §4-9).
    그래서 **글로** 본다: 조인이 있는가, 새 탭으로 여는가, 그리고 UI 자동화의 화면 경로가
    **들어오지 않았는가**.
    """
    page = (
        Path(__file__).resolve().parent.parent
        / "web" / "apps" / "center-console" / "app" / "runs" / "[runId]" / "page.tsx"
    ).read_text(encoding="utf-8")

    assert "consoleOf" in page, "`page_id` → 콘솔 주소 조인"
    assert 'center.contributed("ui_page")' in page
    assert 'rel="noreferrer noopener"' in page and 'target="_blank"' in page
    # 확장 고유 경로·이름이 플랫폼 화면에 들어오면 안 된다 (ADR-0042 — `console.pages`의 일이다).
    assert "monitoring" not in page
    assert "ui-automation" not in page

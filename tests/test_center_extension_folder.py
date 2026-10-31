"""확장 폴더 — Center가 뜰 때 외부 확장 정의를 콘솔 등록과 같은 관문으로 들인다 (ADR-0121).

진짜 Center를 in-process로 띄우되 **같은 DB 파일로 여러 번** 띄워 「다시 떴을 때」를 본다.

1. **뜰 때 등록된다** — Center가 서명하고 현장이 같은 검증(E6)으로 다시 본다. 출처는 `folder`다.
2. **같은 파일 두 번이면 한 번 등록이다** (`unchanged`).
3. **판이 오르면 새 판이 지금 판이다** — 옛 판을 다시 두어도 내려가지 않는다 (`older_than_registered`).
4. **잘못된 파일은 Center를 막지 않고** 사유가 `GET /resources/extension-folder`로 나온다.
5. **폴더에서 지워도 등록은 남는다.** 콘솔로 먼저 올린 같은 것은 콘솔 등록으로 남는다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from center_admin import register_extension, revoke_extension
from fastapi.testclient import TestClient
from test_m5_extensions import definition

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import verify_external
from chaeksas.contracts.signing import AdminKey, Envelope

TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    made = tmp_path / "extensions"
    made.mkdir()
    return made


Boot = Callable[..., TestClient]


@pytest.fixture
def boot(tmp_path: Path, folder: Path) -> Iterator[Boot]:
    """Center를 띄운다 — 부를 때마다 **같은 DB로 새로** 뜬다 (재시작)."""
    opened: list[tuple[TestClient, Store]] = []

    def start(*, extensions_dir: Path | None = folder) -> TestClient:
        for client, store in opened:
            client.__exit__(None, None, None)
            store.close()
        opened.clear()
        store = Store(tmp_path / "center.sqlite3")
        settings = Settings(
            db_path=tmp_path / "center.sqlite3",
            package_dir=tmp_path / "packages",
            admin_token=TOKEN,
            extensions_dir=extensions_dir,
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


def scanned(client: TestClient) -> dict[str, Any]:
    got = client.get("/api/v1/resources/extension-folder", headers=ADMIN)
    assert got.status_code == 200, got.text
    return dict(got.json())


def outcomes(client: TestClient) -> dict[str, tuple[str, str | None]]:
    return {one["file"]: (one["outcome"], one.get("code")) for one in scanned(client)["items"]}


def current(client: TestClient, ext_id: str = "ext-ocr") -> dict[str, Any]:
    got = client.get(f"/api/v1/resources/extensions/{ext_id}", headers=ADMIN)
    assert got.status_code == 200, got.text
    return dict(got.json())


def keys_of(client: TestClient) -> list[AdminKey]:
    return [AdminKey.model_validate(one) for one in client.get("/api/v1/signing-keys").json()]


def test_registers_on_startup_and_the_field_can_verify_it(boot: Boot, folder: Path) -> None:
    put(folder, "ocr.extension.json", definition())
    client = boot()

    assert outcomes(client) == {"ocr.extension.json": ("registered", None)}
    found = current(client)
    assert found["version"] == "1.0.0"
    assert found["source"] == "folder"
    # 서명은 Center가 했다 — 현장이 하는 검증 그대로 통과한다 (E6).
    assert verify_external(found["definition"], Envelope.model_validate(found["envelope"]), keys=keys_of(client)) == []


def test_the_same_file_twice_registers_once(boot: Boot, folder: Path) -> None:
    put(folder, "ocr.extension.json", definition())
    first = current(boot())
    client = boot()

    assert outcomes(client) == {"ocr.extension.json": ("unchanged", None)}
    again = current(client)
    # 봉투를 다시 짓지 않았다 — 같은 줄이다.
    assert again["envelope"] == first["envelope"]


def test_a_higher_version_becomes_current_and_an_old_file_does_not_bring_it_down(boot: Boot, folder: Path) -> None:
    put(folder, "ocr.extension.json", definition())
    boot()
    put(folder, "ocr.extension.json", definition(version="1.1.0"))
    client = boot()
    assert outcomes(client) == {"ocr.extension.json": ("registered", None)}
    assert current(client)["version"] == "1.1.0"

    # 옛 파일을 다시 복사해도 지금 판은 그대로다.
    put(folder, "ocr.extension.json", definition())
    client = boot()
    assert outcomes(client) == {"ocr.extension.json": ("skipped", "older_than_registered")}
    assert current(client)["version"] == "1.1.0"


def test_two_versions_in_one_folder_end_on_the_higher(boot: Boot, folder: Path) -> None:
    # 파일 이름 순서가 판 순서와 반대여도 높은 판이 지금 판이다.
    put(folder, "a.extension.json", definition(version="2.0.0"))
    put(folder, "b.extension.json", definition(version="1.0.0"))
    client = boot()

    assert outcomes(client) == {"a.extension.json": ("registered", None), "b.extension.json": ("registered", None)}
    assert current(client)["version"] == "2.0.0"


def test_bad_files_do_not_stop_center_and_say_why(boot: Boot, folder: Path) -> None:
    put(folder, "good.extension.json", definition())
    put(folder, "broken.extension.json", "{ 이건 JSON이 아니다")
    put(folder, "array.extension.json", [1, 2])
    put(folder, "builtin.extension.json", definition(id="ext-builtin", tier="builtin"))  # E2
    put(folder, "plain-http.extension.json", definition(id="ext-http", service={
        **definition()["service"], "base_url": "http://ocr.example.com",
    }))  # E3
    put(folder, "ignored.json", definition(id="ext-other"))  # 이름 꼴이 아니면 읽지 않는다
    client = boot()

    got = outcomes(client)
    assert got["good.extension.json"] == ("registered", None)
    assert got["broken.extension.json"] == ("refused", "unreadable")
    assert got["array.extension.json"] == ("refused", "unreadable")
    assert got["builtin.extension.json"][0] == "refused"
    assert got["plain-http.extension.json"][0] == "refused"
    assert "ignored.json" not in got
    # 사유는 사람이 읽을 글로 온다.
    assert all(one["message"] for one in scanned(client)["items"] if one["outcome"] == "refused")
    assert current(client)["version"] == "1.0.0"


def test_same_version_with_other_content_is_refused(boot: Boot, folder: Path) -> None:
    put(folder, "ocr.extension.json", definition())
    boot()
    put(folder, "ocr.extension.json", definition(name="다른 이름"))
    client = boot()

    outcome, code = outcomes(client)["ocr.extension.json"]
    assert outcome == "refused"
    assert code == "id_conflict"  # 콘솔 등록과 같은 코드
    assert current(client)["name"] == "외부 OCR"


def test_a_revoked_version_does_not_come_back(boot: Boot, folder: Path) -> None:
    put(folder, "ocr.extension.json", definition())
    client = boot()
    revoke_extension(client, "ext-ocr", "1.0.0", reason="시험")
    client = boot()

    assert outcomes(client)["ocr.extension.json"] == ("refused", "extension_revoked")
    assert client.get("/api/v1/resources/extensions/ext-ocr", headers=ADMIN).status_code == 404


def test_removing_the_file_keeps_the_registration(boot: Boot, folder: Path) -> None:
    path = put(folder, "ocr.extension.json", definition())
    boot()
    path.unlink()
    client = boot()

    assert scanned(client)["items"] == []
    assert current(client)["source"] == "folder"


def test_a_console_registration_stays_a_console_registration(boot: Boot, folder: Path) -> None:
    client = boot(extensions_dir=None)
    register_extension(client, definition())
    assert current(client)["source"] == "console"

    put(folder, "ocr.extension.json", definition())
    client = boot()
    assert outcomes(client) == {"ocr.extension.json": ("unchanged", None)}
    assert current(client)["source"] == "console"


def test_no_folder_configured_or_missing_folder(boot: Boot, tmp_path: Path) -> None:
    client = boot(extensions_dir=None)
    assert scanned(client) == {"configured": False, "items": []}

    client = boot(extensions_dir=tmp_path / "없는 폴더")
    got = scanned(client)
    assert got["configured"] is True
    assert got["problem"]
    assert got["items"] == []


def test_settings_read_the_folder_from_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHK_CENTER__EXTENSIONS_DIR", str(tmp_path))
    assert Settings.from_env().extensions_dir == tmp_path
    monkeypatch.delenv("CHK_CENTER__EXTENSIONS_DIR")
    assert Settings.from_env().extensions_dir is None

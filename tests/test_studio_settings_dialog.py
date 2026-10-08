"""STU-10 설정 — 「LLM」·「Center」·「Worker」·「서비스 앱 키」 (M4 조각 26, Center는 M5).

보는 것:

1. **키는 설정 파일에 들어가지 않는다** — 이름·주소는 파일에, 값은 OS 비밀 저장소에 (ADR-0013).
2. **「저장」을 누를 때까지 아무것도 바뀌지 않는다**, 비밀 저장소가 없으면 **창을 닫지 않는다**.
3. 「연결 테스트」는 진짜 모양으로 묻는다 — 키 상태는 **진짜 UI 자동화 앱**(`/v1/keys/self`), Center는
   **진짜 Center**의 리소스 목록(C7 `GET /resources?type=service_app`)에 대고.
4. 시험 실행이 같은 비밀 창고를 쓴다 (`StudioSecrets`·모델 키).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fastapi.testclient import TestClient  # noqa: E402

from chaeksas.contracts.service_app import ServiceAppKey  # noqa: E402
from chaeksas.ext.ui_automation.service.app import create  # noqa: E402
from chaeksas.ext.ui_automation.service.store import Database, SqliteKeyStore  # noqa: E402
from chaeksas.service_kit import hash_key  # noqa: E402
from chaeksas.studio.checks import (  # noqa: E402
    WorkerPlace,
    center_status,
    key_status,
    llm_status,
    refs_in,
    worker_status,
)
from chaeksas.studio.credentials import (  # noqa: E402
    CENTER_KEY_NAME,
    ENV_CENTER_API_KEY,
    StudioCredentials,
)
from chaeksas.studio.extensions import Extensions, StudioSecrets  # noqa: E402
from chaeksas.studio.settings import ServiceKeyRef, Settings  # noqa: E402
from chaeksas.studio.settings_dialog import CATEGORIES, LATER, StudioSettingsDialog  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
GOOD = "chk_svc_" + "a" * 40
REVOKED = "chk_svc_" + "r" * 40


class Vault:
    """OS 비밀 저장소인 척 (`keyring`과 같은 세 함수)."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str) -> str | None:
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.values[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.values.pop((service, name), None)


class Credentials(StudioCredentials):
    def __init__(self, vault: Vault | None) -> None:
        super().__init__()
        self.vault = vault

    def _keyring(self) -> Any | None:
        return self.vault


@pytest.fixture(scope="module")
def qt() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "studio")


@pytest.fixture(scope="module")
def extensions() -> Extensions:
    return Extensions.load()


def dialog(settings: Settings, extensions: Extensions, vault: Vault | None, **kw: Any) -> StudioSettingsDialog:
    return StudioSettingsDialog(settings, extensions, credentials=Credentials(vault), **kw)


def type_key(found: StudioSettingsDialog, at: int, value: str) -> None:
    """사람이 「키 값」 칸에 붙여 넣는 것."""
    from PySide6.QtWidgets import QLineEdit  # noqa: PLC0415

    cell = found.keys.cellWidget(at, 2)
    assert isinstance(cell, QLineEdit)
    cell.setText(value)


# ─────────────────────────── 창 ───────────────────────────


def test_every_category_is_listed_and_the_unbuilt_ones_say_why(
    qt: Any, settings: Settings, extensions: Extensions
) -> None:
    found = dialog(settings, extensions, Vault())
    labels = [found.categories.item(i).text() for i in range(found.categories.count())]
    assert len(labels) == len(CATEGORIES) == 8
    assert sum(label.endswith("(아직)") for label in labels) == len(LATER) == 4
    assert "Center" in labels, "M5 조각 14 — Center가 켜졌다 (「(아직)」이 붙지 않는다)"
    assert found.categories.currentItem().text() == "LLM", "처음에는 받쳐 주는 첫 분류를 연다"


def test_the_llm_key_goes_to_the_vault_not_the_file(qt: Any, settings: Settings, extensions: Extensions) -> None:
    vault = Vault()
    found = dialog(settings, extensions, vault)
    found.llm_url.setText("http://127.0.0.1:11434")
    found.llm_model.setText("qwen2.5:7b")
    found.llm_key.setText("sk-개발용-1234")
    found.save()
    assert found.saved is not None and found.saved.llm_model == "qwen2.5:7b"
    assert vault.values[("chaeksas-studio", "llm")] == "sk-개발용-1234"
    raw = settings.path.read_text(encoding="utf-8")
    assert "sk-개발용-1234" not in raw and "qwen2.5:7b" in raw
    assert dialog(settings, extensions, vault).llm_key.placeholderText().startswith("저장됨"), "값은 보이지 않는다"


@pytest.mark.parametrize("field", ["llm_key", "center_key"])
def test_without_a_vault_saving_fails_and_the_window_stays(
    qt: Any, settings: Settings, extensions: Extensions, field: str
) -> None:
    found = dialog(settings, extensions, None)
    getattr(found, field).setText("sk-1")
    found.save()
    assert found.saved is None and "저장하지 못했습니다" in found.error.text()
    assert not settings.path.exists(), "평문으로 흘리지 않는다 — 아무것도 쓰지 않았다"


def test_the_center_key_goes_to_the_vault_and_the_address_to_the_file(
    qt: Any, settings: Settings, extensions: Extensions
) -> None:
    vault = Vault()
    found = dialog(settings, extensions, vault)
    found.center_url.setText("http://center.example.com:8800")
    found.center_key.setText("chk_ctr_개발용")
    found.save()
    assert found.saved is not None and found.saved.center_url == "http://center.example.com:8800"
    assert vault.values[("chaeksas-studio", CENTER_KEY_NAME)] == "chk_ctr_개발용"
    raw = settings.path.read_text(encoding="utf-8")
    assert "chk_ctr_개발용" not in raw, "키는 설정 파일에 들어가지 않는다"
    assert "http://center.example.com:8800" in raw
    assert Settings.load(settings.path).center_url == "http://center.example.com:8800"
    again = dialog(settings, extensions, vault)
    assert again.center_key.text() == "" and again.center_key.placeholderText().startswith("저장됨")


def test_an_empty_center_address_blocks_saving(qt: Any, settings: Settings, extensions: Extensions) -> None:
    found = dialog(settings, extensions, Vault())
    found.center_url.setText("   ")
    found.save()
    assert found.saved is None and "Center 주소가 비었습니다" in found.error.text()
    assert not settings.path.exists()


def test_the_center_key_env_var_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    vault = Vault()
    vault.set_password("chaeksas-studio", CENTER_KEY_NAME, "chk_ctr_stored")
    monkeypatch.delenv(ENV_CENTER_API_KEY, raising=False)
    assert Credentials(vault).center_api_key() == "chk_ctr_stored"
    monkeypatch.setenv(ENV_CENTER_API_KEY, "chk_ctr_env")
    assert Credentials(vault).center_api_key() == "chk_ctr_env"
    assert Credentials(vault).stored_center_api_key() == "chk_ctr_stored", "자리 글은 저장된 것만 본다"


def test_the_center_test_asks_the_real_center(
    qt: Any, settings: Settings, extensions: Extensions, tmp_path: Path
) -> None:
    """Center 상태는 **진짜 Center**의 리소스 목록에 묻는다 (C7 — Studio용 키가 읽는다)."""
    from chaeksas.center.app import create_app  # noqa: PLC0415
    from chaeksas.center.settings import Settings as CenterSettings  # noqa: PLC0415
    from chaeksas.center.storage import Store  # noqa: PLC0415

    store = Store(tmp_path / "center.sqlite3")
    center = create_app(
        CenterSettings(
            db_path=tmp_path / "center.sqlite3",
            package_dir=tmp_path / "packages",
            admin_token="t-admin",
        ),
        store=store,
    )
    try:
        with TestClient(center) as client:
            made = client.post(
                "/api/v1/center-keys",
                json={"name": "설계자 PC", "type": "studio"},
                headers={"Authorization": "Bearer t-admin"},
            )
            assert made.status_code == 201, made.text
            key = made.json()["key"]
            found = dialog(settings, extensions, Vault(), client=client)
            found.center_url.setText("http://center.test")

            found.center_key.setText(key)
            found.test_center()
            assert found.center_result.text() == "연결됨 — 서비스 앱 0개를 읽었습니다"

            found.center_key.setText("chk_ctr_" + "x" * 40)
            found.test_center()
            assert found.center_result.text() == "키가 거부되었습니다 (401)"
            assert "x" * 40 not in found.center_result.text()

            found.center_key.setText("")
            found.test_center()
            assert found.center_result.text() == "Center API 키가 없습니다."
    finally:
        store.close()


def test_service_keys_names_in_the_file_values_in_the_vault(
    qt: Any, settings: Settings, extensions: Extensions
) -> None:
    vault = Vault()
    vault.set_password("chaeksas-studio", "svc:old-ref", "chk_svc_old")
    start = Settings(data_dir=settings.data_dir, service_keys=(ServiceKeyRef("old-ref", "ui-automation"),))
    found = dialog(start, extensions, vault, refs=[("test-ui", "ui-automation"), ("old-ref", "ui-automation")])
    found.fill_from_process()
    assert [ref for ref, _, _ in found.key_rows()] == ["old-ref", "test-ui"], "표에 없는 것만 더한다"
    type_key(found, 1, GOOD)
    found.keys.selectRow(0)
    found.drop_selected_key()
    found.save()
    assert found.saved is not None
    assert found.saved.service_keys == (ServiceKeyRef("test-ui", "ui-automation"),)
    assert vault.values == {("chaeksas-studio", "svc:test-ui"): GOOD}, "지운 줄은 비밀 저장소에서도 지운다"
    assert GOOD not in settings.path.read_text(encoding="utf-8")
    assert Settings.load(settings.path).service_keys == (ServiceKeyRef("test-ui", "ui-automation"),)


@pytest.mark.parametrize(("rows", "why"), [([("", "x")], "빈 줄"), ([("a", "x"), ("a", "y")], "두 줄")])
def test_bad_key_rows_block_saving(
    qt: Any, settings: Settings, extensions: Extensions, rows: list[tuple[str, str]], why: str
) -> None:
    found = dialog(settings, extensions, Vault())
    for ref, app in rows:
        found._add_key_row(ref, app)
    found.save()
    assert found.saved is None and why in found.error.text()


def test_the_key_test_asks_the_real_app(qt: Any, settings: Settings, extensions: Extensions, tmp_path: Path) -> None:
    """키 상태는 **진짜 UI 자동화 앱**의 `/v1/keys/self`에 묻는다 (C11). 주소는 확장의 `service.base_url`."""
    path = tmp_path / "uia.sqlite3"
    app = create(db_path=path, admin_token="t")
    store = SqliteKeyStore(db=Database(path=path))
    for raw, name, revoked in ((GOOD, "개발", None), (REVOKED, "옛 키", "2026-10-01T00:00:00+09:00")):
        store.add(ServiceAppKey(name=name, hash=hash_key(raw), prefix=raw[:16], allowed_operations=["*"],
                                allowed_modes=["deterministic", "autonomous"], created_at="2026-10-05T09:00:00+09:00",
                                revoked_at=revoked))
    found = dialog(settings, extensions, Vault(), client=TestClient(app))
    for ref, app_id, value in (("good", "ui-automation", GOOD), ("gone", "ui-automation", REVOKED),
                               ("wrong", "ui-automation", "chk_svc_" + "x" * 40), ("empty", "ui-automation", ""),
                               ("elsewhere", "crm", GOOD)):
        at = found._add_key_row(ref, app_id)
        type_key(found, at, value)
    found.test_keys()
    states = [found._cell(at, 3) for at in range(found.keys.rowCount())]
    assert states[0] == "정상 — 허용: 결정·자율"
    assert states[1:] == ["폐기됨", "키가 틀림", "없음", "주소를 모름"]


# ─────────────────────────── 확인들 ───────────────────────────


def mock(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_llm_status_says_what_happened() -> None:
    models = mock(lambda r: httpx.Response(200, json={"data": [{"id": "qwen2.5:7b"}]}))
    assert llm_status("http://m", None, client=models) == "연결됨 — 모델 1개 (qwen2.5:7b)"
    denied = mock(lambda r: httpx.Response(401, json={}))
    assert llm_status("http://m", "k", client=denied).startswith("키가 거부")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("거부", request=request)

    assert llm_status("http://m", None, client=mock(refuse)).startswith("닿지 못함")
    assert llm_status("", None) == "서버 주소가 없습니다."


def test_the_key_header_carries_the_key_and_the_result_never_does() -> None:
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"data": []})

    shown = llm_status("http://m", "sk-123", client=mock(answer))
    assert seen == ["Bearer sk-123"] and "sk-123" not in shown


def test_center_status_says_what_happened() -> None:
    listing = mock(lambda r: httpx.Response(200, json={"items": [{"id": "a"}, {"id": "b"}]}))
    assert center_status("http://c/", "k", client=listing) == "연결됨 — 서비스 앱 2개를 읽었습니다"
    assert center_status("", "k") == "Center 주소가 없습니다."
    assert center_status("http://c", None) == "Center API 키가 없습니다.", "키 없이는 묻지 않는다"
    assert center_status("http://c", "k", client=mock(lambda r: httpx.Response(403))) == (
        "키가 거부되었습니다 (403)"
    )
    assert center_status("http://c", "k", client=mock(lambda r: httpx.Response(500))) == (
        "Center가 500로 답했습니다"
    )

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("거부", request=request)

    assert center_status("http://c", "k", client=mock(refuse)).startswith("닿지 못함")


def test_the_center_probe_carries_the_key_and_asks_only_for_service_apps() -> None:
    """키는 헤더로만 가고 결과 글에는 **들어가지 않는다**. 앱을 깨우지 않는 자리를 본다 (C7)."""
    seen: list[tuple[str, str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization", "")))
        return httpx.Response(200, json={"items": []})

    shown = center_status("http://c", "chk_ctr_123", client=mock(answer))
    assert seen == [("http://c/api/v1/resources?type=service_app", "Bearer chk_ctr_123")]
    assert "chk_ctr_123" not in shown


def test_worker_status() -> None:
    alive = mock(lambda r: httpx.Response(200, json={"status": "ok", "version": "0.1.0"}))
    assert worker_status(WorkerPlace(port=8899, token_dir=None), client=alive) == "실행 중 — Worker 0.1.0"

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("거부", request=request)

    assert "꺼져 있거나" in worker_status(WorkerPlace(port=8899, token_dir=None), client=mock(refuse))
    assert worker_status(WorkerPlace(port=None, token_dir=None)).startswith("Worker를 기여한 확장이 없")


def test_the_worker_page_shows_the_place_the_runs_use(qt: Any, settings: Settings, extensions: Extensions) -> None:
    """시험 실행이 쓰는 자리와 **같은 것**을 보인다 (Bot UI가 남긴 `runtime.json`, 없으면 기본 포트)."""
    from chaeksas.studio.extensions import bot_ui_data_dir  # noqa: PLC0415

    folder = bot_ui_data_dir() / "runtimes" / "worker"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "runtime.json").write_text(json.dumps({"port": 9777}), encoding="utf-8")
    found = dialog(settings, extensions, Vault())
    assert found.worker_port.text() == "9777"
    assert Path(found.worker_tokens.text()) == folder


def test_key_status_without_key_or_address() -> None:
    assert key_status("http://a", None) == "없음"
    assert key_status(None, GOOD) == "주소를 모름"


def test_refs_come_from_the_drawing(tmp_path: Path) -> None:
    made = Workspace(tmp_path / "ws").ensure().import_example(EXAMPLES, "bx17_erp_po_entry")
    assert ("purchase-erp-ui", "ui-automation") in refs_in(made.definitions)


# ─────────────────────────── 시험 실행이 같은 창고를 쓴다 ───────────────────────────


def test_runs_read_the_same_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    vault = Vault()
    vault.set_password("chaeksas-studio", "svc:test-ui", GOOD)
    assert StudioSecrets(credentials=Credentials(vault)).resolve("test-ui") == GOOD
    monkeypatch.setenv("CHK_STUDIO__SVC__TEST_UI", "chk_svc_from_env")
    assert StudioSecrets(credentials=Credentials(vault)).resolve("test-ui") == "chk_svc_from_env", "환경변수가 먼저"


def test_the_model_key_for_runs_comes_from_the_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    from chaeksas.studio import runner  # noqa: PLC0415

    vault = Vault()
    vault.set_password("chaeksas-studio", "llm", "sk-stored")
    monkeypatch.delenv("CHK_STUDIO__LLM__API_KEY", raising=False)
    monkeypatch.setattr("chaeksas.studio.credentials.StudioCredentials._keyring", lambda self: vault)
    assert runner._llm_key() == "sk-stored"
    monkeypatch.setenv("CHK_STUDIO__LLM__API_KEY", "sk-env")
    assert runner._llm_key() == "sk-env"

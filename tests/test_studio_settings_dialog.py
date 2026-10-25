"""STU-10 설정 — 「외형」·「LLM」·「Center」·「확장별 설정」·「Worker」·「서비스 앱 키」 (ADR-0073).

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
from chaeksas.studio.settings_dialog import (  # noqa: E402
    CATEGORIES,
    NO_EXTENSION_FIELDS,
    THEMES,
    StudioSettingsDialog,
)
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


def test_only_the_categories_something_reads_are_listed(
    qt: Any, settings: Settings, extensions: Extensions
) -> None:
    """ADR-0073 — 메일·비밀은 읽는 곳이 없어 없고, 남은 분류에 「(아직)」이 없다."""
    found = dialog(settings, extensions, Vault())
    labels = [found.categories.item(i).text() for i in range(found.categories.count())]
    assert labels == list(CATEGORIES) == ["외형", "LLM", "Center", "확장별 설정", "Worker", "서비스 앱 키"]
    assert found.categories.currentItem().text() == "LLM", "처음에는 모델 칸을 연다"


def test_the_theme_goes_to_the_file(qt: Any, settings: Settings, extensions: Extensions) -> None:
    found = dialog(settings, extensions, Vault())
    assert found.theme.currentData() == "system", "기본은 시스템 따름"
    assert [found.theme.itemText(i) for i in range(found.theme.count())] == [label for _, label in THEMES]
    found.theme.setCurrentIndex(found.theme.findData("dark"))
    found.save()
    assert found.saved is not None and found.saved.theme == "dark"
    assert Settings.load(settings.path).theme == "dark"
    assert dialog(Settings.load(settings.path), extensions, Vault()).theme.currentData() == "dark"


# ─────────────────────────── 확장별 설정 (C13 scope studio) ───────────────────────────

DEMO: dict[str, Any] = {
    "schema": 2,
    "id": "demo-ext",
    "version": "1.0.0",
    "name": "데모 확장",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=1,<2",
    "contributes": {
        "configuration": [
            {"key": "region", "label": "지역", "scope": "studio", "schema": {"type": "string"}},
            {"key": "token", "label": "개발용 토큰", "scope": "studio", "secret": True},
            {"key": "elsewhere", "label": "현장 칸", "scope": "bot_ui"},
        ]
    },
}


def demo_extensions(**kw: Any) -> Extensions:
    from chaeksas.core.extensions import ExtensionHost  # noqa: PLC0415

    host = ExtensionHost()
    assert host.add_installed(json.dumps(DEMO).encode("utf-8"), origin="test", root="demo_ext") is not None
    return Extensions(host=host, **kw)


def test_extension_fields_come_from_the_contribution(qt: Any, settings: Settings) -> None:
    """창은 어느 확장인지 모른다 — `scope: studio` 칸만 그 확장의 이름 아래 짓는다."""
    found = dialog(settings, demo_extensions(), Vault())
    assert set(found.extension_fields) == {("demo-ext", "region"), ("demo-ext", "token")}, "bot_ui 칸은 없다"
    _, secret = found.extension_fields[("demo-ext", "token")]
    from PySide6.QtWidgets import QLineEdit  # noqa: PLC0415

    assert secret.echoMode() == QLineEdit.EchoMode.Password


def test_without_contributed_fields_the_page_says_so(qt: Any, settings: Settings) -> None:
    from PySide6.QtWidgets import QLabel  # noqa: PLC0415

    found = dialog(settings, Extensions(), Vault())
    assert found.extension_fields == {}
    page = found.pages.widget(CATEGORIES.index("확장별 설정"))
    assert page is not None
    assert NO_EXTENSION_FIELDS in [one.text() for one in page.findChildren(QLabel)]


def test_extension_values_go_to_the_file_and_secrets_to_the_vault(qt: Any, settings: Settings) -> None:
    vault = Vault()
    found = dialog(settings, demo_extensions(), vault)
    found.extension_fields[("demo-ext", "region")][1].setText("서울")
    found.extension_fields[("demo-ext", "token")][1].setText("tok-비밀-1")
    found.save()
    assert found.saved is not None and found.saved.extensions == {"demo-ext": {"region": "서울"}}
    assert vault.values[("chaeksas-studio", "ext:demo-ext:token")] == "tok-비밀-1"
    raw = settings.path.read_text(encoding="utf-8")
    assert "tok-비밀-1" not in raw and "서울" in raw, "비밀은 설정 파일에 들어가지 않는다"
    again = dialog(Settings.load(settings.path), demo_extensions(), vault)
    assert again.extension_fields[("demo-ext", "region")][1].text() == "서울"
    token = again.extension_fields[("demo-ext", "token")][1]
    assert token.text() == "" and token.placeholderText().startswith("저장됨")

    again.extension_fields[("demo-ext", "region")][1].setText("")
    again.save()
    assert again.saved is not None and again.saved.extensions == {"demo-ext": {}}, "비운 칸은 지운다"


def test_runs_see_what_was_put_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """시험 실행·사전 점검이 쓰는 `context()`가 그 값을 본다 — 비밀은 `secrets`로만 (Bot UI와 같다)."""
    vault = Vault()
    vault.set_password("chaeksas-studio", "ext:demo-ext:token", "tok-stored")
    monkeypatch.setattr("chaeksas.studio.credentials.StudioCredentials._keyring", lambda self: vault)
    monkeypatch.delenv("CHK_STUDIO__EXT__DEMO_EXT__TOKEN", raising=False)
    found = demo_extensions(configured={"demo-ext": {"region": "부산"}})
    values = dict(getattr(found.settings_for("demo-ext"), "values", {}))
    assert values["region"] == "부산" and "token" not in values and "elsewhere" not in values
    assert demo_extensions().settings_for("demo-ext").get("region") is None, "넣지 않은 칸은 None"
    secrets = StudioSecrets(credentials=Credentials(vault), extension_id="demo-ext")
    assert secrets.resolve("token") == "tok-stored"
    monkeypatch.setenv("CHK_STUDIO__EXT__DEMO_EXT__TOKEN", "tok-env")
    assert secrets.resolve("token") == "tok-env", "환경변수가 이긴다"
    assert StudioSecrets(credentials=Credentials(vault)).resolve("token") is None, "확장을 모르면 키 참조만"


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


@pytest.mark.parametrize("field", ["llm_key"])
def test_without_a_vault_saving_fails_and_the_window_stays(
    qt: Any, settings: Settings, extensions: Extensions, field: str
) -> None:
    found = dialog(settings, extensions, None)
    getattr(found, field).setText("sk-1")
    found.save()
    assert found.saved is None and "저장하지 못했습니다" in found.error.text()
    assert not settings.path.exists(), "평문으로 흘리지 않는다 — 아무것도 쓰지 않았다"


@pytest.fixture
def center(tmp_path: Path) -> Any:
    """진짜 Center (TestClient) — 설계 권한이 있는 계정 `kim`, 없는 계정 `lee`."""
    from chaeksas.center import accounts  # noqa: PLC0415
    from chaeksas.center.app import create_app  # noqa: PLC0415
    from chaeksas.center.settings import Settings as CenterSettings  # noqa: PLC0415
    from chaeksas.center.storage import Store  # noqa: PLC0415

    accounts.reset_failures()
    store = Store(tmp_path / "center.sqlite3")
    app = create_app(
        CenterSettings(db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token="t-admin"),
        store=store,
    )
    admin = {"Authorization": "Bearer t-admin"}
    with TestClient(app) as client:
        for name, permissions in (("kim", ["design"]), ("lee", [])):
            made = client.post(
                "/api/v1/accounts",
                json={"username": name, "password": "designer-pass-1234", "role": "viewer", "permissions": permissions},
                headers=admin,
            )
            assert made.status_code == 201, made.text
        yield client
    store.close()


def test_login_puts_the_key_in_the_vault_and_who_in_the_file(
    qt: Any, settings: Settings, extensions: Extensions, center: Any
) -> None:
    """STU-10 「Center」 — 키 칸은 없고, 로그인이 키를 받아 비밀 저장소에 둔다 (ADR-0092)."""
    vault = Vault()
    found = dialog(settings, extensions, vault, client=center)
    assert not hasattr(found, "center_key"), "Center API 키 칸은 없다"
    found.center_url.setText("http://center.test")
    found.center_user.setText("kim")
    found.center_password.setText("designer-pass-1234")
    found.login_center()

    key = vault.values[("chaeksas-studio", CENTER_KEY_NAME)]
    assert key.startswith("chk_ctr_")
    assert found.center_password.text() == "", "비밀번호는 남기지 않는다"
    assert found.center_who.text().startswith("kim로 로그인됨")
    assert found.saved is None, "「저장」을 기다리지 않는다 — 그래도 창은 닫히지 않았다"
    assert found.login_changed is not None and found.login_changed.center_account == "kim"
    raw = settings.path.read_text(encoding="utf-8")
    assert key not in raw and "designer-pass-1234" not in raw
    assert Settings.load(settings.path).center_url == "http://center.test"

    found.test_center()
    assert found.center_result.text() == "연결됨 — 서비스 앱 0개를 읽었습니다"

    found.logout_center()
    assert ("chaeksas-studio", CENTER_KEY_NAME) not in vault.values
    assert found.center_who.text() == "로그인하지 않았습니다."
    after = center.get("/api/v1/packages", headers={"Authorization": f"Bearer {key}"})
    assert after.status_code == 403, "Center에서도 그 키가 폐기됐다"


@pytest.mark.parametrize(
    ("user", "password", "said"),
    [
        ("kim", "wrong-password-1", "아이디나 비밀번호가 맞지 않습니다"),
        ("lee", "designer-pass-1234", "이 계정에는 「설계」 권한이 없습니다"),
    ],
)
def test_login_failures_say_why_and_change_nothing(
    qt: Any, settings: Settings, extensions: Extensions, center: Any, user: str, password: str, said: str
) -> None:
    vault = Vault()
    found = dialog(settings, extensions, vault, client=center)
    found.center_url.setText("http://center.test")
    found.center_user.setText(user)
    found.center_password.setText(password)
    found.login_center()
    assert found.center_result.text().startswith(said)
    assert vault.values == {} and found.login_changed is None
    assert found.center_password.text() == ""


def test_an_env_key_turns_the_login_off(
    qt: Any, settings: Settings, extensions: Extensions, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_CENTER_API_KEY, "chk_ctr_env")
    found = dialog(settings, extensions, Vault())
    assert "환경변수의 키를 씁니다" in found.center_who.text()
    assert not found.center_login.isEnabled()


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


def test_the_center_test_without_a_login_says_so(qt: Any, settings: Settings, extensions: Extensions) -> None:
    found = dialog(settings, extensions, Vault())
    found.test_center()
    assert found.center_result.text() == "Center에 로그인하지 않았습니다."


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


def test_the_key_test_finds_addresses_where_the_test_run_does(
    qt: Any, settings: Settings, extensions: Extensions, tmp_path: Path
) -> None:
    """설치된 확장이 모르는 앱은 **Center 리소스 목록**에서 주소를 찾고(시험 실행과 같은 곳),
    외부 확장은 묻지 않는다 — `/v1/keys/self`는 C11의 길이다."""
    from types import SimpleNamespace

    from chaeksas.studio.checks import EXTERNAL_NOT_CHECKED

    path = tmp_path / "uia.sqlite3"
    app = create(db_path=path, admin_token="t")
    SqliteKeyStore(db=Database(path=path)).add(
        ServiceAppKey(name="개발", hash=hash_key(GOOD), prefix=GOOD[:16], allowed_operations=["*"],
                      allowed_modes=["deterministic", "autonomous"], created_at="2026-10-05T09:00:00+09:00")
    )
    asked: list[str] = []

    class Reader:
        def service_apps(self) -> list[Any]:
            asked.append("service_apps")
            return [SimpleNamespace(app_id="crm", base_url="http://testserver")]

        def extensions(self) -> list[Any]:
            return [SimpleNamespace(id="nowview-sc01", tier="external")]

    found = dialog(settings, extensions, Vault(), client=TestClient(app))
    found._center_reader = Reader  # type: ignore[method-assign]
    for ref, app_id in (("crm", "crm"), ("nv", "nowview-sc01"), ("ui", "ui-automation")):
        type_key(found, found._add_key_row(ref, app_id), GOOD)
    found.test_keys()
    assert [found._cell(at, 3) for at in range(3)] == ["정상 — 허용: 결정·자율", EXTERNAL_NOT_CHECKED,
                                                       "정상 — 허용: 결정·자율"]
    assert asked == ["service_apps"], "Center는 한 번만 묻는다"


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
    assert center_status("http://c", None) == "Center에 로그인하지 않았습니다.", "키 없이는 묻지 않는다"
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

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
from dataclasses import replace
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
from chaeksas.studio.settings import Settings  # noqa: E402
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


#: 이 시험이 만든 창 — 끝날 때 Qt가 지우게 한다 (`_close_dialogs`).
_MADE: list[StudioSettingsDialog] = []


@pytest.fixture(autouse=True)
def _close_dialogs(qt: Any) -> Any:
    """만든 창을 **시험마다** Qt에게 지우게 한다 — 부모 없는 창을 인터프리터가 끝날 때까지 두면
    `QApplication`보다 늦게 사라지며 프로세스가 죽는다 (시험은 모두 통과하고 끝에서 139로 나간다)."""
    yield
    while _MADE:
        _MADE.pop().deleteLater()
    qt.processEvents()


def dialog(settings: Settings, extensions: Extensions, vault: Vault | None, **kw: Any) -> StudioSettingsDialog:
    made = StudioSettingsDialog(settings, extensions, credentials=Credentials(vault), **kw)
    _MADE.append(made)
    return made


def center_hands_out(monkeypatch: pytest.MonkeyPatch, raw: str) -> list[str]:
    """Center 대신 — Studio가 청한 개발 키를 **그 요청의 공개키로** 봉해 준다 (C5 §Studio 개발 키)."""
    from chaeksas.contracts.enrollment import seal  # noqa: PLC0415
    from chaeksas.contracts.service_keys import StudioServiceKey  # noqa: PLC0415
    from chaeksas.studio import dev_keys  # noqa: PLC0415

    asked: list[str] = []

    def made(base_url: str, api_key: str) -> Any:
        def fetch(app_id: str, public_key: str) -> StudioServiceKey:
            asked.append(app_id)
            return StudioServiceKey(
                app_id=app_id,
                service_key_id="svk_00000001",
                sealed_key=seal(public_key, raw, salt="svk_00000001"),
                expires_at="2099-01-01T00:00:00+00:00",
            )

        return fetch

    monkeypatch.setattr(dev_keys, "http_fetch", made)
    return asked


def approved(vault: Vault) -> Vault:
    """승인된 Studio 키가 있다 (ADR-0093)."""
    vault.set_password("chaeksas-studio", "center", "chk_ctr_studio")
    return vault


# ─────────────────────────── 창 ───────────────────────────


def test_only_the_categories_something_reads_are_listed(
    qt: Any, settings: Settings, extensions: Extensions
) -> None:
    """ADR-0073 — 메일·비밀은 읽는 곳이 없어 없고, 남은 분류에 「(아직)」이 없다."""
    found = dialog(settings, extensions, Vault())
    labels = [found.categories.item(i).text() for i in range(found.categories.count())]
    assert labels == list(CATEGORIES) == ["외형", "LLM", "Center", "확장별 설정", "Worker", "서비스 앱"]
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
    """진짜 Center (TestClient). 관리자 토큰으로 승인한다 (콘솔이 하는 일)."""
    from chaeksas.center.app import create_app  # noqa: PLC0415
    from chaeksas.center.settings import Settings as CenterSettings  # noqa: PLC0415
    from chaeksas.center.storage import Store  # noqa: PLC0415

    store = Store(tmp_path / "center.sqlite3")
    app = create_app(
        CenterSettings(db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token="t-admin"),
        store=store,
    )
    with TestClient(app) as client:
        yield client
    store.close()


def approve_studio(center: Any, name: str = "김OO 설계 PC") -> None:
    admin = {"Authorization": "Bearer t-admin"}
    pending = center.get("/api/v1/enrollments?type=studio", headers=admin).json()
    assert len(pending) == 1
    done = center.post(f"/api/v1/enrollments/{pending[0]['enrollment_id']}/approve", json={"name": name}, headers=admin)
    assert done.status_code == 200, done.text


def connect_window(settings: Settings, vault: Vault, center: Any, **over: Any) -> Any:
    from chaeksas.studio.connect_dialog import CenterConnectDialog  # noqa: PLC0415

    return CenterConnectDialog(settings, credentials=Credentials(vault), client=center, **over)


def test_stu16_lets_studio_in_by_approval(qt: Any, settings: Settings, center: Any) -> None:
    """STU-16 — 주소를 넣고 「보내기」, 관리자가 승인하면 키를 받는다. 아이디·비밀번호는 없다 (ADR-0093)."""
    vault = Vault()
    found = connect_window(replace(settings, center_url="http://center.test"), vault, center)
    assert not found.send.isHidden() and found.code.isHidden(), "요청이 없으면 「보내기」만"

    found.send_request()
    code = found.code.text()
    assert code and code in found.status.text()
    assert found.send.isHidden() and not found.copy.isHidden()
    assert found.timer.isActive(), "기다리는 동안 10초마다 묻는다"
    assert found.again.isHidden(), "기다리는 중에는 「다시 요청」이 없다"

    approve_studio(center)
    found.poll()
    assert found.connected and not found.timer.isActive()
    assert found.status.text().startswith("연결됨 — 「김OO 설계 PC」으로 들어와 있습니다")
    key = vault.values[("chaeksas-studio", CENTER_KEY_NAME)]
    raw = settings.path.read_text(encoding="utf-8")
    assert key not in raw and "김OO 설계 PC" in raw and "http://center.test" in raw, "「저장」 없이 그 자리에서 적는다"


def test_stu16_later_keeps_the_request_for_next_time(qt: Any, settings: Settings, center: Any) -> None:
    vault = Vault()
    first = connect_window(replace(settings, center_url="http://center.test"), vault, center)
    first.send_request()
    code = first.code.text()
    first.reject()  # 「나중에」
    assert not first.timer.isActive(), "닫힌 동안은 묻지 않는다"
    again = connect_window(replace(Settings.load(settings.path), data_dir=settings.data_dir), vault, center)
    assert again.code.text() == code, "다음에 뜨면 같은 코드다"


def test_stu16_refused_key_offers_asking_again(qt: Any, settings: Settings, center: Any) -> None:
    vault = Vault()
    vault.set_password("chaeksas-studio", CENTER_KEY_NAME, "chk_ctr_" + "x" * 40)
    found = connect_window(replace(settings, center_url="http://center.test"), vault, center, refused=True)
    assert "키가 거부되었습니다" in found.status.text() and not found.again.isHidden()
    found.ask_again()
    assert ("chaeksas-studio", CENTER_KEY_NAME) not in vault.values
    assert found.code.text() in found.status.text() and found.again.isHidden()


def test_need_at_start(center: Any) -> None:
    """STU-16 「언제 뜨나」 — 키가 없거나 거부됐을 때만 창, 닿지 못함·만료 임박은 한 줄."""
    from chaeksas.studio import center_enroll as ce  # noqa: PLC0415

    base: dict[str, Any] = {"base_url": "http://center.test", "key": None, "from_env": False, "key_expires": ""}

    def ask(**over: Any) -> Any:
        return ce.need_at_start(**(base | {"client": center} | over))

    assert ask().kind == ce.NEED_CONNECT
    assert ask(from_env=True).kind == ce.NEED_NONE
    assert ask(key="chk_ctr_" + "x" * 40).kind == ce.NEED_REFUSED
    assert ask(key="chk_ctr_" + "x" * 40, base_url="http://127.0.0.1:9", client=None).kind == ce.NEED_UNREACHABLE


def test_center_tab_hides_ask_again_while_connected(
    qt: Any, settings: Settings, extensions: Extensions, center: Any
) -> None:
    """STU-10 — 연결이 멀쩡하면 「다시 요청」이 없다 (누르면 쓰던 키를 버린다)."""
    vault = Vault()
    found = connect_window(replace(settings, center_url="http://center.test"), vault, center)
    found.send_request()
    approve_studio(center)
    found.poll()
    tab = dialog(replace(Settings.load(settings.path), data_dir=settings.data_dir), extensions, vault, client=center)
    assert tab.center_result.text().startswith("연결됨")
    assert tab.center_again.isHidden()
    tab.test_center()
    assert tab.center_result.text() == "연결됨 — 서비스 앱 0개를 읽었습니다" and tab.center_again.isHidden()

    vault.set_password("chaeksas-studio", CENTER_KEY_NAME, "chk_ctr_" + "x" * 40)  # 폐기된 키라 치자
    tab.test_center()
    assert tab.center_result.text() == "키가 거부되었습니다 — 「다시 요청」으로 새로 승인받으세요"
    assert not tab.center_again.isHidden()


def test_an_env_key_skips_the_request(
    qt: Any, settings: Settings, extensions: Extensions, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_CENTER_API_KEY, "chk_ctr_env")
    found = dialog(settings, extensions, Vault())
    assert "환경변수의 키를 씁니다" in found.center_result.text()
    assert found.center_again.isHidden()


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


def test_the_apps_table_is_read_only_and_starts_from_the_open_process(
    qt: Any, settings: Settings, extensions: Extensions
) -> None:
    """「서비스 앱」 (ADR-0094 §5) — 값·참조 칸이 없다. 앱마다 개발 키를 **받았나**만 보인다."""
    vault = Vault()
    held = '{"key": "chk_svc_x", "expires_at": "2026-11-01T00:00:00+00:00"}'
    vault.set_password("chaeksas-studio", "dev:ui-automation", held)
    found = dialog(settings, extensions, vault, refs=[("test-ui", "ui-automation"), ("fin", "crm")])
    assert found.app_rows() == [("crm", "아직 받지 않음", ""), ("ui-automation", "받음 — 2026-11-01까지", "")]
    assert not hasattr(found, "keys") and not hasattr(found, "add_key")
    found.save()
    assert found.saved is not None, "고칠 칸이 없으니 저장을 막을 것도 없다"


def test_the_key_test_asks_center_for_a_dev_key_and_the_app_accepts_it(
    qt: Any, settings: Settings, extensions: Extensions, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """「연결 테스트」 — 키가 없으면 Center에 청하고, 받은 키로 **진짜 UI 자동화 앱**의 `/v1/keys/self`에 묻는다."""
    path = tmp_path / "uia.sqlite3"
    app = create(db_path=path, admin_token="t")
    SqliteKeyStore(db=Database(path=path)).add(
        ServiceAppKey(name="svk_00000001", hash=hash_key(GOOD), prefix=GOOD[:16], allowed_operations=["*"],
                      allowed_modes=["deterministic", "autonomous"], created_at="2026-10-05T09:00:00+09:00")
    )
    asked = center_hands_out(monkeypatch, GOOD)
    vault = approved(Vault())
    start = replace(settings, center_url="http://center.test")
    found = dialog(start, extensions, vault, refs=[("test-ui", "ui-automation")], client=TestClient(app))
    found._center_reader = lambda: None  # type: ignore[method-assign]
    found.test_keys()
    assert asked == ["ui-automation"]
    assert found.app_rows() == [("ui-automation", "정상 — 허용: 결정·자율", "자율·결정")]
    assert ("chaeksas-studio", "dev:ui-automation") in vault.values, "받은 키는 비밀 저장소에 둔다"
    assert GOOD not in settings.path.read_text(encoding="utf-8") if settings.path.exists() else True


def test_without_a_studio_key_the_table_says_why(
    qt: Any, settings: Settings, extensions: Extensions, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENV_CENTER_API_KEY, raising=False)
    found = dialog(settings, extensions, Vault(), refs=[("test-ui", "ui-automation")])
    found._center_reader = lambda: None  # type: ignore[method-assign]
    found.test_keys()
    [(app, said, _)] = found.app_rows()
    assert app == "ui-automation" and said.startswith("받지 못함") and "Center" in said


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

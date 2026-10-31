"""STU-10 설정 — 「외형」·「LLM」·「Center」·「확장별 설정」 (ADR-0073 — 「서비스 앱」은 없다, ADR-0102).

보는 것:

1. **키는 설정 파일에 들어가지 않는다** — 이름·주소는 파일에, 값은 OS 비밀 저장소에 (ADR-0013).
2. **「저장」을 누를 때까지 아무것도 바뀌지 않는다**, 비밀 저장소가 없으면 **창을 닫지 않는다**.
3. 「연결 테스트」는 진짜 모양으로 묻는다 — Center는 **진짜 Center**의 리소스 목록
   (C7 `GET /resources?type=service_app`)에 대고.
4. 시험 실행이 같은 비밀 창고를 쓴다 (`StudioSecrets`·모델 키), 호출 토큰은 Studio가 제 키로 청한다 (C15).
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

from chaeksas.studio.checks import center_status, llm_status  # noqa: E402
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

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


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
    assert labels == list(CATEGORIES) == ["외형", "LLM", "Center", "확장별 설정"]
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
    "api": ">=2,<3",
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
    """시험 실행·사전 점검이 쓰는 `context()`가 그 값을 본다 — 비밀은 `secrets`로만 (PC 실행기와 같다)."""
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


# ─────────────────────────── 시험 실행이 같은 창고를 쓴다 ───────────────────────────


def test_runs_resolve_the_call_token_and_extension_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """`call_token`은 Studio가 청한 호출 토큰이고(C15), 나머지는 그 확장의 비밀 칸이다."""
    vault = Vault()
    vault.set_password("chaeksas-studio", "ext:crm:note", "비밀")
    found = StudioSecrets(credentials=Credentials(vault), extension_id="crm", call_tokens=lambda: "chk_ctr_x")
    assert found.resolve("call_token") == "chk_ctr_x"
    assert found.resolve("note") == "비밀"
    assert StudioSecrets(credentials=Credentials(vault)).resolve("call_token") is None, "청하는 쪽이 없으면 없다"


def test_studio_asks_center_for_a_call_token_and_keeps_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Studio 키로 `POST /call-tokens` — 받은 것은 만료 2시간 전까지 다시 청하지 않는다 (C15)."""
    from chaeksas.studio.call_token import PATH, CallTokens  # noqa: PLC0415

    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(f"{request.method} {request.url.path} {request.headers.get('authorization')}")
        return httpx.Response(201, json={"token": "chk_ctr_" + "t" * 40, "expires_at": "2099-01-01T00:00:00+00:00"})

    tokens = CallTokens(base_url="http://c", api_key="chk_ctr_studio", client=mock(answer))
    assert tokens() == "chk_ctr_" + "t" * 40
    assert tokens() == "chk_ctr_" + "t" * 40
    assert asked == [f"POST {PATH} Bearer chk_ctr_studio"], "한 번만 청한다"


def test_the_model_key_for_runs_comes_from_the_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    from chaeksas.studio import runner  # noqa: PLC0415

    vault = Vault()
    vault.set_password("chaeksas-studio", "llm", "sk-stored")
    monkeypatch.delenv("CHK_STUDIO__LLM__API_KEY", raising=False)
    monkeypatch.setattr("chaeksas.studio.credentials.StudioCredentials._keyring", lambda self: vault)
    assert runner._llm_key() == "sk-stored"
    monkeypatch.setenv("CHK_STUDIO__LLM__API_KEY", "sk-env")
    assert runner._llm_key() == "sk-env"


def test_an_old_files_service_keys_are_not_read_and_drop_out_on_save(tmp_path: Path) -> None:
    """옛 STU-10 「서비스 앱」 칸(`service_keys`)은 읽지 않는다 (ADR-0102). 다음 저장에서 빠진다."""
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "dark", "service_keys": [{"ref": "fin", "app_id": "erp"}]}', encoding="utf-8")
    found = Settings.load(path)
    assert found.theme == "dark", "옛 칸 하나로 나머지를 버리지 않는다"
    found.save(path)
    assert "service_keys" not in path.read_text(encoding="utf-8")

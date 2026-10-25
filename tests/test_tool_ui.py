"""Tool UI — 확장의 도구를 띄우는 창 (ADR-0077, TOL-01·02).

보는 것:

- **Bot UI 자리를 빌려 읽는다** — 데이터 위치 규칙이 Bot UI와 같고(앱끼리 import하지 않아 베꼈다),
  런타임 포트·끈 확장·앱 주소 명부를 거기서 읽되 **쓰지 않는다**.
- **런타임을 띄우지 않는다** — 답하지 않으면 도구를 열지 않고 까닭과 길을 말한다.
- 도구의 바깥 세상은 `tool_ui` 호스트이고, 등록 담당자 키는 **도구의 비밀 칸**이다.
- 묶은 앱에서 Tool UI로 가는 깃발은 **네 자리**(Bot UI 바로가기·Tool UI·묶기 진입·설치 파일)가 같은 글이다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts import SERVICE_URL_SETTING, STORAGE_DIR_SETTING  # noqa: E402
from chaeksas.core.extensions import ExtensionHost  # noqa: E402
from chaeksas.tool_ui import places  # noqa: E402
from chaeksas.tool_ui.credentials import SecretsUnavailable, ToolCredentials, extension_secret_env  # noqa: E402
from chaeksas.tool_ui.host import RUNTIME_DOWN, ToolHost, parse_spec  # noqa: E402
from chaeksas.tool_ui.settings import ToolSettings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUILTIN = "ui-automation"
TOOL = "selector-registration"


def tool_host(tmp_path: Path, *, up: bool = True, off: tuple[str, ...] = ()) -> ToolHost:
    host = ExtensionHost(off=off)
    host.load_entry_points()
    return ToolHost(
        host=host,
        bot_ui_root=tmp_path / "bot-ui",
        root=tmp_path / "tool-ui",
        probe=lambda _port, _path: up,
    )


# ─────────────────────────── 자리 (빌려 읽기) ───────────────────────────


def test_tool_ui_and_bot_ui_agree_on_where_the_bot_ui_lives(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tool UI는 Bot UI를 import하지 않는다 — 같은 규칙을 따로 쓰므로 어긋나면 여기서 잡는다."""
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    monkeypatch.delenv("CHK_BOT_UI__DATA_DIR", raising=False)
    assert places.bot_ui_data_dir() == data_dir()
    monkeypatch.setenv("CHK_BOT_UI__DATA_DIR", str(tmp_path))
    assert places.bot_ui_data_dir() == data_dir() == tmp_path
    assert places.data_dir() != places.bot_ui_data_dir(), "제 자리와 빌려 읽는 자리는 다르다"


def test_the_runtime_port_is_read_from_what_bot_ui_left(tmp_path: Path) -> None:
    assert places.runtime_port("worker", root=tmp_path) is None
    folder = places.runtime_folder("worker", root=tmp_path)
    folder.mkdir(parents=True)
    (folder / places.RUNTIME_FILE).write_text(json.dumps({"runtime": "worker", "port": 9555}), encoding="utf-8")
    assert places.runtime_port("worker", root=tmp_path) == 9555
    (folder / places.RUNTIME_FILE).write_text("{깨짐", encoding="utf-8")
    assert places.runtime_port("worker", root=tmp_path) is None, "깨졌으면 다음 출처로 간다"


def test_turned_off_extensions_come_from_bot_ui_settings(tmp_path: Path) -> None:
    """이 PC에서 확장을 켜고 끄는 자리는 BUI-11 하나다 (ADR-0043·0077)."""
    from chaeksas.bot_ui.settings import Settings  # noqa: PLC0415

    assert places.bot_ui_turned_off(root=tmp_path) == ()
    Settings(disabled_extensions=(BUILTIN,)).save(tmp_path / places.BOT_UI_SETTINGS_FILE)
    assert places.bot_ui_turned_off(root=tmp_path) == (BUILTIN,)
    (tmp_path / places.BOT_UI_SETTINGS_FILE).write_text("[]", encoding="utf-8")
    assert places.bot_ui_turned_off(root=tmp_path) == ()


def test_a_turned_off_extension_has_no_tools(tmp_path: Path) -> None:
    from chaeksas.bot_ui.settings import Settings  # noqa: PLC0415

    root = tmp_path / "bot-ui"
    Settings(disabled_extensions=(BUILTIN,)).save(root / places.BOT_UI_SETTINGS_FILE)
    found = ToolHost.load(settings=ToolSettings(), bot_ui_root=root, root=tmp_path / "tool-ui")
    assert found.tools() == []
    assert [c.value.id for c in ToolHost.load(settings=ToolSettings(), bot_ui_root=tmp_path / "x").tools()] == [TOOL]


# ─────────────────────────── 런타임 (띄우지 않는다) ───────────────────────────


def test_a_tool_whose_runtime_does_not_answer_says_why_and_how(tmp_path: Path) -> None:
    down = tool_host(tmp_path, up=False)
    found = down.find(BUILTIN, TOOL)
    assert found is not None and found.value.needs_runtime == "worker"
    problem = down.runtime_problem("worker")
    assert problem is not None
    assert problem == RUNTIME_DOWN.format(label="Worker 프로세스", port=8899)
    assert "Bot UI" in problem, "길을 말한다 — Bot UI 「도구」에서 열면 Bot UI가 띄운다"
    assert tool_host(tmp_path, up=True).runtime_problem("worker") is None
    assert down.runtime_problem(None) is None, "런타임이 필요 없는 도구는 그대로 열린다"
    assert "기여한 확장이 없습니다" in (down.runtime_problem("nope") or "")


def test_the_tool_gets_the_runtime_bot_ui_started_and_its_own_storage(tmp_path: Path) -> None:
    found = tool_host(tmp_path)
    folder = places.runtime_folder("worker", root=found.bot_ui_root)
    folder.mkdir(parents=True)
    (folder / places.RUNTIME_FILE).write_text(json.dumps({"port": 9555}), encoding="utf-8")

    values = found.values(BUILTIN, runtime_ids=("worker",))
    assert values["runtime.worker.port"] == 9555
    assert Path(values["runtime.worker.token_dir"]) == folder, "토큰은 Bot UI가 띄운 Worker의 것이다"
    assert values["runtime.worker.state"] == "running"
    # 제 파일은 **제 자리**에 — Bot UI 데이터 폴더에 쓰지 않는다.
    assert Path(values[STORAGE_DIR_SETTING]) == tmp_path / "tool-ui" / "extensions" / BUILTIN
    assert values[SERVICE_URL_SETTING], "주소는 명부 > 정의 — 명부가 비면 정의의 값"
    assert "registrar_key" not in values, "비밀 칸은 설정으로 가지 않는다"
    assert not (found.bot_ui_root / "extensions").exists()


def test_the_service_address_comes_from_what_bot_ui_fetched(tmp_path: Path) -> None:
    """Tool UI는 Center를 부르지 않는다 — Bot UI가 받아 둔 명부가 정의보다 이긴다 (C13)."""
    from chaeksas.core.app_directory import DirectoryCache  # noqa: PLC0415

    found = tool_host(tmp_path)
    cache = DirectoryCache(data_dir=found.bot_ui_root)
    registered = "http://ui-automation.internal:8810"
    cache.cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache.cache_path.write_text(
        json.dumps({"apps": {BUILTIN: {"extension_id": BUILTIN, "base_url": registered}}, "extensions": []}),
        encoding="utf-8",
    )
    assert found.service_url(BUILTIN) == registered


def test_the_context_says_tool_ui_and_resolves_the_tools_own_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(extension_secret_env(BUILTIN, "registrar_key"), "uia_test_key")
    ctx = tool_host(tmp_path).context(BUILTIN, runtime_ids=("worker",))
    assert ctx.host == "tool_ui"
    assert ctx.secret("registrar_key") == "uia_test_key"
    assert ctx.setting("runtime.worker.port") == 8899


def test_the_registry_client_reports_the_host_as_caller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C11 `caller.type`은 도구를 띄운 호스트다 — Tool UI면 `tool_ui` (ADR-0077)."""
    from chaeksas.contracts.service_app import KNOWN_CALLER_TYPES  # noqa: PLC0415
    from chaeksas.ext.ui_automation.client.registration_window import registry_client  # noqa: PLC0415

    monkeypatch.setenv(extension_secret_env(BUILTIN, "registrar_key"), "uia_test_key")
    client = registry_client(tool_host(tmp_path).context(BUILTIN))
    assert client is not None
    assert client.request("registry_get_page", {"page_id": "p"}, run_id="reg_00000000").caller.type == "tool_ui"
    assert "tool_ui" in KNOWN_CALLER_TYPES


def test_parse_spec() -> None:
    assert parse_spec("ui-automation:selector-registration") == (BUILTIN, TOOL)
    assert parse_spec("nope") is None
    assert parse_spec(":x") is None
    assert parse_spec(None) is None


# ─────────────────────────── 창 (TOL-01) ───────────────────────────


@pytest.fixture
def app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    return QApplication.instance() or QApplication([])


class FakeTool:
    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken
        self.closed_count = 0
        self.context: Any = None

    def widget(self, ctx: Any) -> object:
        from PySide6.QtWidgets import QLabel  # noqa: PLC0415

        if self.broken:
            raise RuntimeError("화면을 그리다 넘어졌다")
        self.context = ctx
        return QLabel("도구")

    def closed(self) -> None:
        self.closed_count += 1


def test_the_window_does_not_open_a_tool_without_its_runtime(app: Any, tmp_path: Path) -> None:
    from chaeksas.tool_ui.window import ToolWindow  # noqa: PLC0415

    window = ToolWindow(tool_host(tmp_path, up=False))
    assert window.open_tool(BUILTIN, TOOL) is False
    assert window.tabs.count() == 0
    assert "Bot UI" in window.problem.text(), "까닭을 그 자리에 쓴다 (U3)"
    window.close()


def test_the_window_opens_a_tool_once_and_closing_the_tab_releases_it(
    app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaeksas.tool_ui.window import ToolWindow  # noqa: PLC0415

    tools = tool_host(tmp_path)
    made: list[FakeTool] = []

    def make(*_: Any) -> FakeTool:
        made.append(FakeTool())
        return made[-1]

    monkeypatch.setattr(tools, "make", make)
    window = ToolWindow(tools)
    assert window.open_tool(BUILTIN, TOOL) is True
    assert window.open_tool(BUILTIN, TOOL) is True
    assert window.tabs.count() == 1 and len(made) == 1, "같은 도구는 그 탭으로 간다"
    assert made[0].context.host == "tool_ui"
    window.close_tab(0)
    assert made[0].closed_count == 1, "탭을 닫으면 자리를 놓는다 (UI 세션은 한 번에 하나)"
    assert window.tabs.count() == 0
    window.close()


def test_a_broken_tool_only_breaks_its_tab(app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chaeksas.tool_ui.window import TOOL_BROKEN, ToolWindow  # noqa: PLC0415

    tools = tool_host(tmp_path)
    monkeypatch.setattr(tools, "make", lambda *_: FakeTool(broken=True))
    window = ToolWindow(tools)
    assert window.open_tool(BUILTIN, TOOL) is True
    from PySide6.QtWidgets import QLabel  # noqa: PLC0415

    shown = window.tabs.widget(0)
    assert isinstance(shown, QLabel) and TOOL_BROKEN in shown.text()
    window.close()


def test_closing_the_window_releases_every_tool(app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chaeksas.tool_ui.window import ToolWindow  # noqa: PLC0415

    tools = tool_host(tmp_path)
    one = FakeTool()
    monkeypatch.setattr(tools, "make", lambda *_: one)
    window = ToolWindow(tools)
    window.open_tool(BUILTIN, TOOL)
    window.close()
    assert one.closed_count == 1


# ─────────────────────────── 설정 (TOL-02) ───────────────────────────


class FakeCredentials(ToolCredentials):
    def __init__(self, *, works: bool = True) -> None:
        super().__init__()
        self.works = works
        self.saved: dict[str, str] = {}

    def stored(self, name: str) -> str | None:
        return self.saved.get(name)

    def set(self, name: str, value: str) -> None:
        if not self.works:
            raise SecretsUnavailable("저장소가 없다")
        self.saved[name] = value


def test_settings_have_no_registrar_key_field(app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """등록 담당자 키 칸은 없다 — Center가 이 PC Bot UI에 내려 준다 (TOL-02, ADR-0094 §6)."""
    from chaeksas.tool_ui.settings_dialog import NO_FIELDS, ToolSettingsDialog  # noqa: PLC0415

    monkeypatch.setenv("CHK_TOOL_UI__DATA_DIR", str(tmp_path))
    tools = tool_host(tmp_path)
    dialog = ToolSettingsDialog(tools.host, ToolSettings(), FakeCredentials())
    assert dialog.tabs.count() == 0
    assert not dialog.fields
    assert NO_FIELDS


def test_the_utility_key_is_what_bot_ui_received(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """도구용 키는 Bot UI 비밀 저장소의 `util:<앱>`을 **읽기만** 한다 — Bot UI와 같은 이름 규칙이다."""
    from chaeksas.core.service_keys import utility_name  # noqa: PLC0415
    from chaeksas.tool_ui import credentials as tool_credentials  # noqa: PLC0415

    assert tool_credentials.BOT_UI_UTILITY_PREFIX + BUILTIN == utility_name(BUILTIN)
    from chaeksas.bot_ui.credentials import SERVICE as BOT_UI_SERVICE  # noqa: PLC0415

    assert tool_credentials.BOT_UI_SERVICE == BOT_UI_SERVICE
    asked: list[tuple[str, str]] = []

    def stored(self: Any, name: str) -> str | None:
        asked.append((self.service, name))
        return "chk_svc_utility" if self.service == BOT_UI_SERVICE else None

    monkeypatch.delenv(extension_secret_env(BUILTIN, "utility"), raising=False)
    monkeypatch.setattr(tool_credentials.ToolCredentials, "stored", stored)
    ctx = tool_host(tmp_path).context(BUILTIN)
    assert ctx.secret("utility") == "chk_svc_utility"
    assert (BOT_UI_SERVICE, utility_name(BUILTIN)) in asked


# ─────────────────────────── 띄우는 길 (ADR-0077 §3·§6) ───────────────────────────


def _botui_main() -> Any:
    spec = importlib.util.spec_from_file_location("botui_main", ROOT / "packaging" / "botui_main.py")
    assert spec is not None and spec.loader is not None
    made = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(made)
    return made


def test_the_tool_ui_flag_is_the_same_text_in_all_four_places() -> None:
    """Bot UI 바로가기·Tool UI·묶기 진입·설치 파일 — 하나라도 다르면 묶은 앱에서야 Bot UI가 뜬다."""
    from chaeksas.bot_ui import tool_launch  # noqa: PLC0415
    from chaeksas.tool_ui import app as tool_app  # noqa: PLC0415

    flag = tool_launch.TOOL_UI_FLAG
    assert flag == tool_app.TOOL_UI_FLAG == _botui_main().TOOL_UI_FLAG
    assert tool_launch.OPEN_FLAG == tool_app.OPEN_FLAG
    iss = (ROOT / "packaging" / "installer" / "chaeksas.iss").read_text(encoding="utf-8-sig")
    assert f'Parameters: "{flag}"' in iss


def test_bot_ui_launches_tool_ui_by_module_from_source_and_by_itself_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from chaeksas.bot_ui.tool_launch import tool_ui_command  # noqa: PLC0415

    monkeypatch.delattr(sys, "frozen", raising=False)
    assert tool_ui_command(BUILTIN, TOOL) == [
        sys.executable, "-m", "chaeksas.tool_ui", "--open", f"{BUILTIN}:{TOOL}",
    ]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert tool_ui_command(BUILTIN, TOOL) == [sys.executable, "--tool-ui", "--open", f"{BUILTIN}:{TOOL}"]


def test_the_packaged_entry_sends_tool_ui_flag_to_tool_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    import chaeksas.bot_ui.app as bot_app  # noqa: PLC0415
    import chaeksas.tool_ui.app as tool_app  # noqa: PLC0415

    went: list[str] = []

    def which(name: str) -> Any:
        def main(argv: list[str]) -> int:
            went.append(name)
            return 0

        return main

    monkeypatch.setattr(tool_app, "main", which("tool"))
    monkeypatch.setattr(bot_app, "main", which("bot"))
    entry = _botui_main()
    entry.run(["exe", "--tool-ui", "--open", "a:b"])
    entry.run(["exe"])
    assert went == ["tool", "bot"]


def test_tool_ui_reads_only_the_open_flag() -> None:
    from chaeksas.tool_ui.app import parse_args  # noqa: PLC0415

    assert parse_args(["--tool-ui", "--open", "a:b", "-platform", "offscreen"]) == "a:b"
    assert parse_args(["--tool-ui"]) is None


def test_only_bot_ui_gets_the_tool_ui_shortcut() -> None:
    """Tool UI는 Bot UI 설치에 함께 든다 (ADR-0077 §6) — Studio 설치에는 없다."""
    spec = importlib.util.spec_from_file_location("installer_tests", ROOT / "tests" / "test_installer.py")
    assert spec is not None and spec.loader is not None
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    apps = {app["key"]: app for app in installer._peek()["apps"]}
    assert "/DToolUiName=Chaeksas Tool UI" in apps["bot-ui"]["defines"]
    assert not any(one.startswith("/DToolUiName=") for one in apps["studio"]["defines"])

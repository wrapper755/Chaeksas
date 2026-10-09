"""로컬 런타임과 확장 유틸리티 — Bot UI가 확장이 기여한 것을 띄우고 연다 (C13, BUI-09).

**Bot UI는 UI 자동화를 모른다.** 기여 목록을 읽어 명령줄을 만들고, 띄우고, 답할 때까지
기다릴 뿐이다. 그래서 여기 시험도 가짜 확장 하나로 돈다 — 진짜 Worker를 띄우지 않는다.

거듭 보는 것 다섯.

1. **명령줄은 Bot UI가 만든다** (C13) — 확장은 진입점만 준다. 토큰은 **폴더로만** 간다.
2. **답할 때까지 기다린다** — 떴다고 바로 쓰지 않는다 (「없는데 된 척」하지 않는다).
3. 못 띄우면 **유틸리티를 열지 않는다** — 빈 창을 띄워 놓고 「안 되네」 하게 두지 않는다.
4. 호스트가 **예약 설정 키**로 런타임 자리를 알려 준다 (`runtime.<id>.*`).
5. 확장이 그 이름을 가로채지 못한다 (E7).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui import runtimes as runtimes_module  # noqa: E402
from chaeksas.bot_ui.runtimes import (  # noqa: E402
    RUNTIME_FLAG,
    HostSettings,
    Runtimes,
    RuntimeUnavailable,
    runtime_args,
    serve,
    token_dir_for,
)
from chaeksas.bot_ui.settings import RuntimeSettings, Settings  # noqa: E402
from chaeksas.contracts import ExtensionManifest, Violation, validate_extension  # noqa: E402
from chaeksas.core.extensions import ExtensionHost  # noqa: E402
from chaeksas.core.processes import Supervisor  # noqa: E402

DEFINITION: dict[str, Any] = {
    "schema": 2,
    "id": "demo",
    "version": "1.0.0",
    "name": "데모",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=1,<2",
    "contributes": {
        "bot_ui.utilities": [
            {"id": "pick-things", "label": "요소 담기", "menu": "tools",
             "entry": "demo.client:Thing", "needs_runtime": "helper"}
        ],
        "bot_ui.local_runtimes": [
            {"id": "helper", "label": "도우미", "entry": "demo.runtime:serve",
             "default_port": 9911, "health": "/v1/health", "token_dir": True}
        ],
    },
}


class FakeChild:
    """자식 프로세스인 척. **진짜로 띄우지 않는다.**"""

    def __init__(self, *, dies: bool = False) -> None:
        self.started = 0
        self.stopped = 0
        self.dies = dies
        self.pid = 4242

    @property
    def alive(self) -> bool:
        return self.started > self.stopped and not self.dies

    @property
    def uptime_s(self) -> float:
        return 3.0

    def start(self) -> None:
        self.started += 1

    def stop(self, *, timeout_s: float = 0) -> None:
        self.stopped += 1

    def poll(self) -> int | None:
        return None if self.alive else 1


def host_with_demo() -> ExtensionHost:
    host = ExtensionHost()
    host.add_installed(_json(DEFINITION), origin="test", root="demo")
    return host


def _json(value: dict[str, Any]) -> bytes:
    import json

    return json.dumps(value).encode("utf-8")


def make(*, dies: bool = False, healthy: bool = True, monkeypatch: Any = None) -> Runtimes:
    child = FakeChild(dies=dies)
    found = Runtimes(
        host=host_with_demo(),
        settings=Settings(runtimes=(RuntimeSettings(runtime_id="helper", port=9911),)),
        supervisor_factory=lambda *_: Supervisor(child=child),  # type: ignore[arg-type]
        sleep=lambda _: None,
    )
    if monkeypatch is not None:
        monkeypatch.setattr(
            runtimes_module, "healthy", lambda *_a, **_k: {"status": "ok"} if healthy else None
        )
    return found


# ─────────────────────────── 명령줄 (C13) ───────────────────────────


def test_the_host_builds_the_command_line() -> None:
    """확장은 진입점만 준다 — **명령줄은 Bot UI가 만든다** (ADR-0024)."""
    args = runtime_args("demo:helper", port=9911, token_dir=Path("/tmp/t"))
    assert args[0] == sys.executable
    assert RUNTIME_FLAG in args
    assert args[args.index(RUNTIME_FLAG) + 1] == "demo:helper"
    assert "--port" in args and "9911" in args


def test_no_secret_rides_on_the_command_line() -> None:
    """토큰은 **파일로만** 간다 (C10) — 명령줄은 프로세스 목록에 뜬다."""
    args = runtime_args("demo:helper", port=9911, token_dir=Path("/tmp/t"))
    assert all("token" not in one or one in ("--token-dir", "/tmp/t") for one in args)


def test_the_token_dir_is_per_runtime(tmp_path: Path) -> None:
    assert token_dir_for("helper", root=tmp_path).name == "helper"


# ─────────────────────────── 띄우기 (BUI-09) ───────────────────────────


def test_it_waits_until_the_runtime_answers(monkeypatch: Any) -> None:
    """떴다고 바로 쓰지 않는다 — `health`가 답해야 돌려준다."""
    found = make(monkeypatch=monkeypatch)
    supervisor = found.ensure("helper")
    assert supervisor.state == "running"


def test_a_runtime_that_never_answers_is_not_pretended(monkeypatch: Any) -> None:
    """**「없는데 된 척」하지 않는다** — 답하지 않으면 끄고 왜인지 말한다."""
    found = make(healthy=False, monkeypatch=monkeypatch)
    found.clock = iter([0.0, 0.0, 99.0]).__next__  # 기다리는 시간을 건너뛴다
    with pytest.raises(RuntimeUnavailable, match="제때 답하지"):
        found.ensure("helper")
    assert found.supervisors["helper"].state == "off", "끄고 둔다 (좀비를 남기지 않는다)"


def test_an_unknown_runtime_says_so() -> None:
    found = make()
    with pytest.raises(RuntimeUnavailable, match="기여된 로컬 런타임이 아닙니다"):
        found.ensure("없는것")


def test_health_of_an_unknown_runtime_is_none() -> None:
    """묻는 쪽(화면)을 막지 않는다 — 확장이 없는 PC에서도 BUI-09가 그려진다."""
    assert Runtimes(host=ExtensionHost(), settings=Settings()).health_of("worker") is None


# ─────────────────────────── 예약 설정 키 (C13) ───────────────────────────


def test_the_host_tells_the_extension_where_the_runtime_is(monkeypatch: Any) -> None:
    """확장이 포트를 다시 계산하거나 토큰 자리를 추측하지 않게 한다."""
    found = make(monkeypatch=monkeypatch)
    found.ensure("helper")
    values = found.host_settings(("helper",))
    assert values["runtime.helper.port"] == 9911
    assert values["runtime.helper.state"] == "running"
    assert str(values["runtime.helper.token_dir"]).endswith("helper")

    settings = HostSettings(values=values)
    assert settings.get("runtime.helper.port") == 9911
    assert settings.get("없는키", "기본") == "기본"


def test_an_unknown_runtime_is_skipped_in_settings() -> None:
    assert make().host_settings(("없는것",)) == {}


def test_an_extension_cannot_take_the_reserved_name() -> None:
    """E7 — 확장이 `runtime.*`를 선언하면 거부한다 (호스트가 쓰는 이름이다)."""
    bad = dict(DEFINITION)
    bad["contributes"] = dict(DEFINITION["contributes"])
    bad["contributes"]["configuration"] = [
        {"key": "runtime.helper.port", "label": "포트", "scope": "bot_ui", "schema": {"type": "integer"}}
    ]
    found: list[Violation] = validate_extension(ExtensionManifest.model_validate(bad))
    assert [one.rule for one in found] == ["E7"]
    assert found[0].code == "reserved_config_key"


# ─────────────────────────── 자식으로 뜬 쪽 ───────────────────────────


def test_the_child_resolves_the_entry() -> None:
    """`--local-runtime <확장>:<런타임>`으로 뜬 쪽이 확장의 진입점을 푼다 (ADR-0024)."""
    calls: list[tuple[int, Path | None]] = []

    class Host:
        def local_runtime(self, extension_id: str, runtime_id: str) -> Any:
            assert (extension_id, runtime_id) == ("demo", "helper")

            def entry(*, port: int, token_dir: Path | None = None) -> int:
                calls.append((port, token_dir))
                return 0

            return entry

    assert serve("demo:helper", port=9911, token_dir=None, host=Host()) == 0  # type: ignore[arg-type]
    assert calls == [(9911, None)]


def test_a_malformed_spec_is_refused() -> None:
    assert serve("demo", port=1, token_dir=None, host=object()) == 2  # type: ignore[arg-type]


# ─────────────────────────── 유틸리티 열기 (BUI-02 「도구」) ───────────────────────────


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


@pytest.fixture
def window(app: Any, tmp_path: Path, monkeypatch: Any) -> Any:
    from conftest import FakeCredentials  # noqa: PLC0415

    from chaeksas.bot_ui.agent import Agent  # noqa: PLC0415
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415
    from chaeksas.bot_ui.store import Store  # noqa: PLC0415

    host = host_with_demo()
    agent = Agent(
        settings=Settings(runtimes=(RuntimeSettings(runtime_id="helper", port=9911),)),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
        host=host,
        extensions=host.states(),
    )
    agent._runtimes = make(monkeypatch=monkeypatch)  # noqa: SLF001 — 자식을 띄우지 않으려고
    made = MainWindow(agent)
    yield made
    made.close()


def menu_texts(window: Any) -> list[str]:
    from PySide6.QtWidgets import QMenu  # noqa: PLC0415

    tools = next(one for one in window.menuBar().findChildren(QMenu) if one.title() == "도구")
    return [action.text() for action in tools.actions()]


def test_the_tools_menu_comes_from_the_extensions(window: Any) -> None:
    """Bot UI는 어느 확장인지 모른다 — 기여 목록을 그대로 그린다 (ADR-0018)."""
    assert "요소 담기..." in menu_texts(window)


def test_the_tray_tools_menu_opens_the_same_utilities(app: Any, window: Any) -> None:
    """BUI-01 — **트레이가 주 진입점**이다 (창을 닫아도 트레이에 남는다). docs/09-gaps.md §4-3.

    붙이기 전까지 트레이 항목은 전부 `setEnabled(False)`였고 이름도 확장 id였다 — 같은 메뉴가
    메인 창에서는 돌고 있었다. 창은 **메인 창이 쥔다** (같은 것을 두 번 열지 않는 자리다).
    """
    from PySide6.QtWidgets import QMenu, QSystemTrayIcon  # noqa: PLC0415

    from chaeksas.bot_ui.tray import Tray  # noqa: PLC0415

    if not QSystemTrayIcon.isSystemTrayAvailable():
        pytest.skip("이 환경에는 시스템 트레이가 없다")
    tray = Tray(window._agent, parent=app)  # noqa: SLF001
    asked: list[tuple[str, str]] = []
    tray.open_utility.connect(lambda e, u: asked.append((e, u)))
    tray.refresh()
    tools = next(one for one in tray.contextMenu().findChildren(QMenu) if one.title() == "도구")
    actions = [one for one in tools.actions() if one.text() == "요소 담기..."]
    assert actions and actions[0].isEnabled(), "이름은 기여의 label이고, 눌릴 수 있어야 한다"
    actions[0].trigger()
    assert asked == [("demo", "pick-things")]
    tray.hide()
    tray.setParent(None)


def test_a_utility_that_cannot_start_its_runtime_does_not_open(
    window: Any, monkeypatch: Any, modal_boxes: list[tuple[str, str]]
) -> None:
    """못 띄우면 **창을 열지 않고** 왜 못 열었는지 말한다."""

    def refuse(*_a: Any, **_k: Any) -> None:
        raise RuntimeUnavailable("포트 9911이 이미 쓰이고 있습니다")

    monkeypatch.setattr(window._agent.runtimes(), "ensure", refuse)  # noqa: SLF001
    window.open_utility("demo", "pick-things")
    assert window._utilities == {}  # noqa: SLF001
    assert any("9911" in text for _, text in modal_boxes)


@pytest.fixture(autouse=True)
def modal_boxes(monkeypatch: Any) -> list[tuple[str, str]]:
    """**어떤 시험도 모달 창에서 멈추지 않게** (이슈 #3)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    shown: list[tuple[str, str]] = []

    def warning(_parent: Any, title: str, text: str, *_args: Any, **_kwargs: Any) -> Any:
        shown.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", warning)
    monkeypatch.setattr(QMessageBox, "question", warning)
    return shown


def test_the_runtime_leaves_its_port_for_studio(monkeypatch: Any) -> None:
    """같은 PC의 Studio가 Bot UI가 띄운 런타임을 찾는다 (STU-10 「Worker」) — 포트를 런타임 폴더에 남긴다."""
    import json  # noqa: PLC0415

    from chaeksas.bot_ui.runtimes import RUNTIME_FILE, token_dir_for  # noqa: PLC0415

    found = make(monkeypatch=monkeypatch)
    found.supervisor("helper")
    left = json.loads((token_dir_for("helper") / RUNTIME_FILE).read_text(encoding="utf-8"))
    assert left == {"runtime": "demo:helper", "port": 9911}

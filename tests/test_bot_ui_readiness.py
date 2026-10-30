"""PC 실행기의 사전 점검 — 준비되지 않은 BPM 프로세스는 **띄우지 않고** 그 까닭을 Center에 올린다 (ADR-0013, C4).

서비스 앱 키는 없어졌다 (ADR-0102 — 바깥 기능은 C15로 Center를 거쳐 부르고 「불러도 되나」는 배포가
가린다). 그래서 막는 까닭으로는 **사람이 끈 확장**을 쓴다 — BX-36이 UI 태스크를 쓰니 `ui-automation`을
끄면 막힌다 (ADR-0043).

| 보는 것 | 왜 |
| --- | --- |
| 하트비트 `readiness`가 막힘 코드를 싣는다 | 올리지 않으면 CON-03이 「왜 안 돌았나」를 모른다 |
| 준비되지 않은 BPM 프로세스는 자리를 쥐지 않고 대기열에서 빠진다 | 대기열에 남기면 영원히 막힌다 |
| Center 작업이면 `rejected`·`not_ready`로 ack한다 | 사람이 Center에서 까닭을 본다 |
| 고치면(확장을 켜면) **다음 주기에** 돈다 | 점검 캐시가 그것을 막으면 안 된다 |
| 「준비」 표기는 `status_map`에 있는 말만 | CLAUDE.md §5 |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import FakeCredentials

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.main_window import EXTENSION_OFF, READY, readiness_label
from chaeksas.bot_ui.settings import Settings, data_dir
from chaeksas.bot_ui.store import Store
from chaeksas.core.extensions import load_host
from chaeksas.core.packages import InstalledBot, install

EXAMPLE = "bx36_legacy_migration"
EXAMPLES = Path("docs/08-business-examples/bpmn")
OFF = "ui-automation"


def install_example(tmp_path: Path) -> InstalledBot:
    """Studio처럼 내보내고 PC 실행기에 설치한다 (배포 길은 `test_m5_pc_rerun.py`가 본다)."""
    from chaeksas.studio.packaging import export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, EXAMPLE)
    return install(data_dir(), export(made, tmp_path / "bot.zip"))


def make_agent(tmp_path: Path, *, off: tuple[str, ...] = (OFF,)) -> Agent:
    return Agent(
        settings=Settings(center_url="http://127.0.0.1:1"),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials(),
        host=load_host(off=off),
    )


def test_the_heartbeat_reports_the_readiness_so_con_03_can_show_it(tmp_path: Path) -> None:
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)
    [found] = agent.heartbeat_request().readiness
    assert (found.bpm_process_id, found.ready) == (bot.id, False)
    assert "extension_turned_off" in found.blocked, "막힘 코드는 C4의 열린 문자열이다"
    assert readiness_label(agent.preflight(bot))[0] == EXTENSION_OFF


def test_a_bot_that_is_not_ready_is_refused_instead_of_started(tmp_path: Path) -> None:
    """띄우면 그 태스크에서 죽는다 — **띄우기 전에** 거절한다."""
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)
    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.inputs[item.queue_id] = {}

    agent._start_next()

    assert agent.current_run is None, "실행 자리를 쥐지 않았다"
    assert agent.queue == [], "대기열에 남겨 두면 영원히 막힌다"


def test_a_center_job_is_acked_as_not_ready(tmp_path: Path) -> None:
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)
    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.queue = [item.model_copy(update={"source": "job", "job_id": "job_1"})]

    agent._start_next()

    acks = [(one.job_id, one.result, one.reason) for one in agent.store.state.pending_acks]
    assert acks == [("job_1", "rejected", "not_ready")]


def test_a_ready_bot_starts(tmp_path: Path) -> None:
    """확장이 켜져 있으면 막을 것이 없다 — 키를 묻지 않는다 (ADR-0102)."""
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path, off=())
    agent.runner().make_child = _FakeChild
    assert readiness_label(agent.preflight(bot))[0] == READY

    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.inputs[item.queue_id] = {}
    agent._start_next()

    assert agent.current_run is not None, "준비됐으면 시작한다"


class _FakeChild:
    """실행 프로세스 대신 — **띄웠나**까지만 본다 (실제 실행은 M4·M5 인수 시험이 본다)."""

    def __init__(self, **_: Any) -> None:
        self.started = 0

    def start(self) -> None:
        self.started += 1

    @property
    def alive(self) -> bool:
        return True

    def poll(self) -> int | None:
        return None

    def stop(self, **_: Any) -> None:
        return None


def test_the_readiness_label_only_uses_words_from_the_status_map() -> None:
    """CLAUDE.md §5 — 상태 표기는 `status_map`에 있는 것만 쓴다 (색이 붙지 않는다)."""
    from chaeksas.core.preflight import (  # noqa: PLC0415
        EXTENSION_TURNED_OFF,
        EXTENSIONS_UNUSABLE,
        MISSING_ENVIRONMENT,
        SETTINGS_MISSING,
        TASK_TYPES_UNSUPPORTED,
        Preflight,
    )
    from chaeksas.extension_api import SEVERITY_BLOCK, Finding  # noqa: PLC0415
    from chaeksas.qt import theme  # noqa: PLC0415

    cases = [Preflight()] + [
        Preflight((Finding(id=code, severity=SEVERITY_BLOCK, message=""),))
        for code in (
            EXTENSION_TURNED_OFF,
            TASK_TYPES_UNSUPPORTED,
            EXTENSIONS_UNUSABLE,
            MISSING_ENVIRONMENT,
            SETTINGS_MISSING,
            "pages",
        )
    ]
    for one in cases:
        token, _shown, _tip = readiness_label(one)
        assert theme.status_color("BPM 프로세스 준비", token) is not None, f"표에 없는 표기: {token}"

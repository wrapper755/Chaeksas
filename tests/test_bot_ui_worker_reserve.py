"""Bot UI가 Bot 실행 동안 Worker를 그 실행에 묶는다 — C13 `reserve`, C10 §4, ADR-0014 §4 (M4 조각 27).

1. **진짜 Worker(HTTP)** 에 확장 정의의 선언대로 예약·풀기 — Bot UI는 C10을 모른다.
2. 다른 쪽(셀렉터 등록·Studio 시험)이 세션을 쥐고 있으면 409 → **Bot은 시작하지 않고 기다린다**
   (강제로 닫지 않는다). 풀리면 다음 주기에 시작하고, 끝나면 예약을 푼다.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.runtimes import BUSY, RESERVED, SKIPPED, Runtimes, token_dir_for  # noqa: E402
from chaeksas.bot_ui.settings import RuntimeSettings, Settings  # noqa: E402
from chaeksas.contracts import validate_extension  # noqa: E402
from chaeksas.contracts.extension import ExtensionManifest  # noqa: E402
from chaeksas.core.extensions import load_host  # noqa: E402
from chaeksas.ext.ui_automation.contracts.worker_local import Caller, SessionRequest  # noqa: E402
from chaeksas.ext.ui_automation.worker.app import Worker, create_app, write_tokens  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


def free_port() -> int:
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return int(one.getsockname()[1])


class Backend:
    """화면 없는 백엔드 — 예약은 세션만 본다."""

    def open(self, request: Any, plan: Any = None) -> str:
        return "about:blank"

    def finder(self, business_key: str) -> Any:
        return None

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


@pytest.fixture
def worker() -> Iterator[tuple[Worker, int]]:
    """진짜 Worker 앱을 진짜 HTTP로 — 토큰은 Bot UI가 읽는 그 자리(`runtimes/worker`)에 쓴다."""
    import uvicorn  # noqa: PLC0415

    token, admin = write_tokens(token_dir_for("worker"))
    made = Worker(token=token, admin_token=admin, backend=Backend())
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(made), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    until = time.monotonic() + 10
    while not server.started and time.monotonic() < until:
        time.sleep(0.05)
    yield made, port
    server.should_exit = True
    thread.join(timeout=5)


def runtimes(port: int) -> Runtimes:
    return Runtimes(host=load_host(), settings=Settings(runtimes=(RuntimeSettings(runtime_id="worker", port=port),)))


# ─────────────────────────── 계약 ───────────────────────────


def test_the_builtin_declares_how_to_reserve_its_worker() -> None:
    found = load_host().get("ui-automation")
    assert found is not None
    worker = next(r for r in found.manifest.contributes.bot_ui_local_runtimes if r.id == "worker")
    assert worker.reserve is not None and worker.reserve.path == "/v1/admin/reserve"


def test_a_reserve_needs_a_token_dir_and_an_absolute_path() -> None:
    definition = {
        "schema": 2, "id": "demo", "version": "1.0.0", "name": "데모", "publisher": "사내", "tier": "internal",
        "api": ">=1,<2",
        "contributes": {"bot_ui.local_runtimes": [{
            "id": "helper", "label": "도우미", "entry": "demo.runtime:serve",
            "reserve": {"path": "v1/reserve", "header": "X-Admin", "token_file": "admin.token"},
        }]},
    }
    codes = [v.code for v in validate_extension(ExtensionManifest.model_validate(definition))]
    assert "reserve_invalid" in codes


# ─────────────────────────── 진짜 Worker ───────────────────────────


def test_reserving_and_releasing_a_real_worker(worker: tuple[Worker, int]) -> None:
    made, port = worker
    found = runtimes(port)
    assert found.reserve("worker", "run_20261006_090000_aaaaaa") == RESERVED
    assert made.reserved_for == "run_20261006_090000_aaaaaa"
    found.release("worker")
    assert made.reserved_for is None


def test_a_held_session_makes_the_bot_wait_not_close_it(worker: tuple[Worker, int]) -> None:
    """셀렉터 등록 중이면 Bot이 기다린다 (ADR-0014 §4) — 그 세션을 강제로 닫지 않는다."""
    made, port = worker
    made.open(SessionRequest(schema=1, caller=Caller(type="selector_registration"), mode="autonomous",
                             business_key="reg_1a2b3c4d"))
    assert runtimes(port).reserve("worker", "run_20261006_090000_aaaaaa") == BUSY
    assert made.session is not None, "등록 세션은 그대로다"


def test_an_unreachable_worker_does_not_block_the_run() -> None:
    assert runtimes(free_port()).reserve("worker", "run_20261006_090000_aaaaaa") == SKIPPED


# ─────────────────────────── 대기열 ───────────────────────────


class FakeChild:
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
        pass


def test_the_queue_waits_while_the_worker_is_busy_and_releases_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chaeksas.bot_ui.agent import TRAY_WORKER_BUSY, Agent  # noqa: PLC0415
    from chaeksas.bot_ui.bots import install  # noqa: PLC0415
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415
    from chaeksas.bot_ui.store import Store  # noqa: PLC0415
    from chaeksas.studio.packaging import default_name, export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, "fx05_desktop_autonomous")
    bot = install(data_dir(), export(made, tmp_path / default_name(made)))
    answers = [BUSY, RESERVED]
    asked: list[str] = []
    released: list[str] = []
    monkeypatch.setattr(Runtimes, "ensure", lambda self, runtime_id, **_: None)
    def reserve(self: Runtimes, runtime_id: str, run_id: str) -> str:
        asked.append(run_id)
        return answers.pop(0)

    monkeypatch.setattr(Runtimes, "reserve", reserve)
    monkeypatch.setattr(Runtimes, "release", lambda self, runtime_id: released.append(runtime_id))
    monkeypatch.setattr("chaeksas.bot_ui.agent.Agent.registered", property(lambda self: True))
    monkeypatch.setattr("chaeksas.bot_ui.credentials.Credentials.center_api_key", lambda self: "chk_x")

    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1"), store=Store.load(tmp_path / "s.json"),
                  host=load_host())
    agent.runner().make_child = FakeChild
    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.inputs[item.queue_id] = {"식": "1+1"}

    agent._start_next()
    assert agent.current_run is None and agent.queue == [item], "기다린다 — 대기열 맨 앞 그대로"
    assert agent.tray_status() == TRAY_WORKER_BUSY

    agent._start_next()
    assert agent.current_run is not None, "풀리면 다음 주기에 시작한다"
    assert agent.current_run.run_id == asked[-1], "예약한 그 run_id로 돈다"
    assert agent.tray_status() != TRAY_WORKER_BUSY

    agent._finished(SimpleNamespace(bot=bot, job_id=None, finished="success", run_id=agent.current_run.run_id))
    assert released == ["worker"] and agent.current_run is None, "끝나면 예약을 푼다"

"""Bot UI가 런타임의 **상태를 묻고 곱게 끈다** — C13 `status`·`shutdown`, C10 §4, §1·§4-2·§3-4·§3-8.

붙이기 전까지 Worker의 `GET /v1/status`는 **부르는 쪽이 Worker 자신뿐**이었다 — `reserved_for`·
`unsent_reports`를 아무도 읽지 않아 BUI-09의 칸과 C4 하트비트의 `worker.reserved_for`가 늘
비어 있었다. 끄기도 그랬다: Bot UI가 프로세스를 그냥 죽여 **열린 세션의 보고를 저장할 틈이
없었다**.

Bot UI는 C10을 모른다 — **확장 정의의 선언대로만** 부른다 (ADR-0018). 그래서 여기서 지키는 것은
둘이다: 선언이 맞나(계약), 그리고 **진짜 Worker**에 그 선언대로 부르면 되나.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.runtimes import Runtimes, token_dir_for  # noqa: E402
from chaeksas.bot_ui.settings import RuntimeSettings, Settings  # noqa: E402
from chaeksas.contracts import validate_extension  # noqa: E402
from chaeksas.contracts.extension import ExtensionManifest  # noqa: E402
from chaeksas.core.extensions import load_host  # noqa: E402
from chaeksas.ext.ui_automation.contracts.worker_local import Caller, SessionRequest  # noqa: E402
from chaeksas.ext.ui_automation.worker.app import Worker, create_app, write_tokens  # noqa: E402


def free_port() -> int:
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return int(one.getsockname()[1])


class Backend:
    """화면 없는 백엔드 — 상태는 세션만 본다."""

    def open(self, request: Any, plan: Any = None) -> str:
        return "about:blank"

    def finder(self, business_key: str) -> Any:
        return None

    def goto(self, session_id: str, url: str) -> str:
        return url

    def close(self, session_id: str) -> None:
        pass


@pytest.fixture
def worker() -> Iterator[tuple[Worker, int, list[bool]]]:
    """진짜 Worker 앱을 진짜 HTTP로 — 토큰은 Bot UI가 읽는 그 자리에 쓴다."""
    import uvicorn  # noqa: PLC0415

    token, admin = write_tokens(token_dir_for("worker"))
    stopped: list[bool] = []
    made = Worker(token=token, admin_token=admin, backend=Backend(),
                  unsent=lambda: 3, stopper=lambda: stopped.append(True))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(made), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    until = time.monotonic() + 10
    while not server.started and time.monotonic() < until:
        time.sleep(0.05)
    yield made, port, stopped
    server.should_exit = True
    thread.join(timeout=5)


def runtimes(port: int) -> Runtimes:
    return Runtimes(host=load_host(), settings=Settings(runtimes=(RuntimeSettings(runtime_id="worker", port=port),)))


# ─────────────────────────── 계약 ───────────────────────────


def test_the_builtin_declares_how_to_ask_status_and_how_to_shut_down() -> None:
    found = load_host().get("ui-automation")
    assert found is not None
    worker = next(r for r in found.manifest.contributes.bot_ui_local_runtimes if r.id == "worker")
    assert worker.status is not None and worker.status.path == "/v1/status"
    assert worker.status.token_file == "worker.token", "상태는 **사용 토큰**이다 (C10)"
    assert worker.shutdown is not None and worker.shutdown.path == "/v1/admin/shutdown"
    assert worker.shutdown.token_file == "worker.admin.token", "끄기는 **관리 토큰**이다"


@pytest.mark.parametrize(("which", "code"), [("status", "status_invalid"), ("shutdown", "shutdown_invalid")])
def test_a_management_call_needs_a_token_dir_and_an_absolute_path(which: str, code: str) -> None:
    """관리 호출 셋은 같은 규칙이다 — 상대 경로·토큰 폴더 없음은 검사에서 걸린다 (C13)."""
    definition = {
        "schema": 2, "id": "demo", "version": "1.0.0", "name": "데모", "publisher": "사내", "tier": "internal",
        "api": ">=1,<2",
        "contributes": {"bot_ui.local_runtimes": [{
            "id": "helper", "label": "도우미", "entry": "demo.runtime:serve",
            which: {"path": "v1/status", "header": "X-Token", "token_file": "t.token"},
        }]},
    }
    codes = [v.code for v in validate_extension(ExtensionManifest.model_validate(definition))]
    assert code in codes


# ─────────────────────────── 상태 묻기 (§4-2) ───────────────────────────


def test_asking_a_real_worker_for_its_status(worker: tuple[Worker, int, list[bool]]) -> None:
    made, port, _ = worker
    made.reserve("run_20261009_010203_aaaaaa")
    found = runtimes(port).status_of("worker")
    assert found is not None
    assert found["reserved_for"] == "run_20261009_010203_aaaaaa"
    assert found["unsent_reports"] == 3, "밀린 보고는 큐를 센 것이다 (C10)"


def test_an_unreachable_runtime_gives_nothing_instead_of_pretending() -> None:
    assert runtimes(free_port()).status_of("worker") is None


def test_a_runtime_with_no_status_declaration_gives_nothing() -> None:
    """선언이 없으면 묻지 않는다 — 경로를 **추측하지 않는다**."""
    found = runtimes(free_port())
    _, runtime = found.find("worker")
    before = runtime.status
    object.__setattr__(runtime, "status", None)
    try:
        assert found.status_of("worker") is None
    finally:
        # 정의는 **호스트가 들고 있는 것**이라 되돌려 놓는다 (다음 시험이 같은 것을 본다).
        object.__setattr__(runtime, "status", before)


# ─────────────────────────── 하트비트에 싣기 (§3-4) ───────────────────────────


def test_the_heartbeat_carries_what_the_runtime_says_it_is_reserved_for(
    worker: tuple[Worker, int, list[bool]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from chaeksas.bot_ui.agent import Agent  # noqa: PLC0415
    from chaeksas.bot_ui.store import Store  # noqa: PLC0415

    made, port, _ = worker
    made.reserve("run_20261009_010203_bbbbbb")
    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1",
                                    runtimes=(RuntimeSettings(runtime_id="worker", port=port),)),
                  store=Store.load(tmp_path / "s.json"), host=load_host())
    agent.supervisors["worker"] = cast("Any", _Alive())
    assert agent.worker_state().reserved_for == "run_20261009_010203_bbbbbb"

    made.unreserve()
    assert agent.worker_state().reserved_for is None, "풀리면 비운다 (CON-03이 낡은 값을 보이지 않는다)"


def test_a_silent_runtime_leaves_the_reservation_empty(tmp_path: Path) -> None:
    """모르는 것을 적지 않는다 — 우리가 예약을 걸어 두었더라도 런타임의 말이 원본이다."""
    from chaeksas.bot_ui.agent import Agent  # noqa: PLC0415
    from chaeksas.bot_ui.store import Store  # noqa: PLC0415

    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1",
                                    runtimes=(RuntimeSettings(runtime_id="worker", port=free_port()),)),
                  store=Store.load(tmp_path / "s.json"), host=load_host())
    agent.supervisors["worker"] = cast("Any", _Alive())
    assert agent.worker_state().reserved_for is None


class _Alive:
    """감시자 자리 — 「실행 중」이라고만 말한다."""

    state = "running"
    restarts = 0
    last_error = ""


# ─────────────────────────── 곱게 끄기 (§3-8) ───────────────────────────


def test_shutting_down_closes_the_open_session_and_then_stops(
    worker: tuple[Worker, int, list[bool]]
) -> None:
    made, port, stopped = worker
    made.open(SessionRequest(schema=1, caller=Caller(type="selector_registration"), mode="autonomous",
                             business_key="reg_1a2b3c4d"))
    assert runtimes(port).shutdown("worker") is True
    assert made.session is None, "열린 세션을 닫는다 (그래야 보고가 큐에 저장된다)"
    assert stopped == [True], "닫은 **뒤에** 멈춘다"


def test_shutdown_needs_the_admin_token(worker: tuple[Worker, int, list[bool]]) -> None:
    """사용 토큰으로는 끌 수 없다 (C10 403 `admin_only`) — 실행 중 Bot이 Worker를 끄지 못한다."""
    import httpx  # noqa: PLC0415

    made, port, stopped = worker
    answer = httpx.post(f"http://127.0.0.1:{port}/v1/admin/shutdown",
                        headers={"X-CHK-Local-Token": made.token}, timeout=5)
    assert answer.status_code == 403
    assert stopped == []


def test_an_unreachable_runtime_is_not_a_failure_to_shut_down() -> None:
    """닿지 못해도 **기다리지 않는다** — 끄는 길은 `core.processes`가 쥐고 있다 (ADR-0023)."""
    assert runtimes(free_port()).shutdown("worker") is False


def test_stopping_everything_asks_the_runtime_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUI-01 종료 순서 — 곱게 끄기를 **먼저** 부르고 트리째 끈다."""
    order: list[str] = []
    found = runtimes(free_port())

    class Supervisor:
        state = "running"

        def stop(self) -> None:
            order.append("stop")

    found.supervisors["worker"] = cast("Any", Supervisor())

    def shutdown(self: Runtimes, runtime_id: str) -> bool:
        order.append("shutdown")
        return True

    monkeypatch.setattr(Runtimes, "shutdown", shutdown)
    found.stop_all()
    assert order == ["shutdown", "stop"]

"""실제 Studio·Bot UI 실행기가 확장을 엔진에 꽂는다 (`HostTasks`, ADR-0018·ADR-0037).

지금까지 인수 시험은 Worker를 HTTP 없이 불렀다. 여기서는 **실제 길**을 본다.

1. 규칙 — 없는 태스크 종류는 `None`, 예약 키로 Worker 자리를 알려 준다, 키 참조를 푼다.
2. **Bot UI 한 바퀴 (Windows):** Bot UI가 그 Bot이 쓰는 확장의 Worker를 **자식으로 띄우고**, 실행기
   (자식)가 진짜 HTTP로 그 Worker에 붙어 FX-05(계산기)를 끝까지 돈다.
3. **Studio 한 바퀴 (Windows):** Bot UI가 띄운 Worker를 Studio가 `runtime.json`·토큰 파일로 찾아 쓴다.
"""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.runner import runner_args  # noqa: E402
from chaeksas.bot_ui.runner_main import RunnerSecrets, extension_tasks  # noqa: E402
from chaeksas.core.extensions import HostTasks, load_host  # noqa: E402
from chaeksas.ext.ui_automation.contracts.plan import WindowSpec  # noqa: E402
from chaeksas.ext.ui_automation.worker import desktop  # noqa: E402
from chaeksas.studio.extensions import Extensions, StudioSecrets, bot_ui_data_dir  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
FAKE_APPS = Path(__file__).resolve().parent / "fake_desktop_apps.py"
FX05 = "fx05_desktop_autonomous"

needs_desktop = pytest.mark.skipif(
    not desktop.available(), reason="Windows UIA가 없다 (데스크톱 연결 한 바퀴는 Windows 전용)"
)


# ─────────────────────────── 규칙 ───────────────────────────


def test_host_tasks_say_none_for_an_unknown_task_type() -> None:
    tasks = HostTasks(host=load_host(), make_context=lambda _: None)  # type: ignore[arg-type,return-value]
    assert tasks.executor("ui_task") is not None
    assert tasks.executor("없는_태스크") is None, "엔진이 그림·설치 오류로 올린다 (LookupError가 아니다)"
    assert tasks.environment("desktop") is not None and tasks.environment_owner("desktop") == "ui-automation"


def test_the_runner_hands_the_worker_place_to_the_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    tasks = extension_tasks(
        {"ui-automation": {"runtime.worker.port": 9123, "runtime.worker.token_dir": "C:/somewhere"}}
    )
    context = tasks.context("ui-automation")
    assert context.setting("runtime.worker.port") == 9123
    assert context.host == "bot_ui"
    monkeypatch.setattr(
        "chaeksas.bot_ui.credentials.Credentials.service_app_key", lambda self, ref: f"값-{ref}"
    )
    assert context.secret("purchase-erp-ui") == "값-purchase-erp-ui", "키 참조는 BUI-10의 서비스 앱 키로 푼다"


def test_runner_secrets_fall_back_to_the_extension_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from chaeksas.bot_ui.credentials import Credentials  # noqa: PLC0415

    monkeypatch.setattr(Credentials, "service_app_key", lambda self, ref: None)
    monkeypatch.setattr(Credentials, "extension_secret", lambda self, ext, ref: f"{ext}/{ref}")
    assert RunnerSecrets(Credentials(), "ui-automation").resolve("registrar_key") == "ui-automation/registrar_key"


def test_the_extension_settings_ride_in_a_file_not_on_the_command_line(tmp_path: Path) -> None:
    args = runner_args(
        package=tmp_path / "pkg", run_id="run_20261005_120000_abcdef", data_dir=tmp_path,
        inputs_path=None, mode="deterministic", source="manual", job_id=None,
        extensions_path=tmp_path / "run.extensions.json",
    )
    assert args[args.index("--extensions") + 1].endswith("run.extensions.json")


def test_studio_finds_the_worker_the_bot_ui_started(tmp_path: Path) -> None:
    """포트는 Bot UI가 런타임 폴더에 남긴 `runtime.json` — 없으면 기여의 기본 포트."""
    found = Extensions.load()
    values = found.runtime_settings("ui-automation", root=tmp_path)
    assert values["runtime.worker.port"] == 8899, "없으면 기본 포트"
    assert Path(values["runtime.worker.token_dir"]) == tmp_path / "runtimes" / "worker"
    (tmp_path / "runtimes" / "worker").mkdir(parents=True)
    (tmp_path / "runtimes" / "worker" / "runtime.json").write_text(json.dumps({"port": 9555}), encoding="utf-8")
    assert found.runtime_settings("ui-automation", root=tmp_path)["runtime.worker.port"] == 9555


def test_studio_and_bot_ui_agree_on_where_the_bot_ui_lives(monkeypatch: pytest.MonkeyPatch) -> None:
    """Studio는 Bot UI를 import하지 않는다 — 같은 규칙을 따로 쓰므로 어긋나면 여기서 잡는다."""
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    assert bot_ui_data_dir() == data_dir()
    monkeypatch.delenv("CHK_BOT_UI__DATA_DIR", raising=False)
    assert bot_ui_data_dir() == data_dir()


def test_studio_resolves_key_references_from_the_environment_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHK_STUDIO__SVC__TEST_UI", "chk_svc_dev")
    assert StudioSecrets().resolve("test-ui") == "chk_svc_dev"


def test_studio_runs_get_the_extension_tasks() -> None:
    tasks = Extensions.load().tasks()
    assert tasks.executor("ui_task") is not None and tasks.environment("desktop") is not None
    assert tasks.context("ui-automation").host == "studio"


# ─────────────────────────── 한 바퀴 (Windows, 진짜 자식 프로세스·HTTP) ───────────────────────────


def free_port() -> int:
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        return int(one.getsockname()[1])


class CalcModel:
    """OpenAI 호환 스텁 — 계산기 단추를 차례로 누르고 표시 칸을 읽는다 (FX-05의 운전사)."""

    AID = "QApplication.calculator."
    KEYS = {**{str(n): f"key{n}" for n in range(10)}, "*": "times", "+": "plus", "-": "minus", "/": "divide"}

    def __init__(self) -> None:
        self.seen: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")
                raw = json.dumps(outer.reply(body)).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def reply(self, body: dict[str, Any]) -> dict[str, Any]:
        messages = body.get("messages") or []
        done = [m for m in messages if m.get("role") == "tool"]
        self.seen = [str(m.get("content") or "") for m in done]
        asked = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "user")
        expression = re.search(r'"식":\s*"([0-9+\-*/]+)"', asked)
        assert expression, "모델에게 `식`이 가지 않았다"
        press = [{"target": {"type": "automation_id", "value": self.AID + self.KEYS[ch]}, "action": "click"}
                 for ch in expression.group(1)]
        plan: list[tuple[str, dict[str, Any]]] = [("desktop_look", {})]
        plan += [("desktop_act", one) for one in press]
        for name, action in (("equals", "click"), ("display", "read")):
            target = {"type": "automation_id", "value": self.AID + name}
            plan.append(("desktop_act", {"target": target, "action": action}))
        usage = {"prompt_tokens": 10, "completion_tokens": 10}
        if len(done) < len(plan):
            name, arguments = plan[len(done)]
            call = {"id": f"c{len(done)}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}
            message = {"role": "assistant", "content": "", "tool_calls": [call]}
            return {"choices": [{"message": message}], "usage": usage}
        answer = json.dumps({"결과": int(self.seen[-1])}, ensure_ascii=False)
        return {"choices": [{"message": {"role": "assistant", "content": answer}}], "usage": usage}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def calculator_settings(token_dir: Path, tag: str) -> WindowSpec:
    """그 PC의 앱 설정 — Worker 데이터 폴더(토큰 폴더)의 `desktop-apps.json` (C10)."""
    title = "^" + re.escape("계산기" + tag) + "$"
    token_dir.mkdir(parents=True, exist_ok=True)
    (token_dir / "desktop-apps.json").write_text(
        json.dumps(
            {"Calculator": {"command": [sys.executable, str(FAKE_APPS), "calc", tag], "window": {"title": title}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return WindowSpec(title=title)


def close_windows(spec: WindowSpec) -> None:
    import subprocess  # noqa: PLC0415

    for window in desktop.find_windows(spec):
        subprocess.run(["taskkill", "/PID", str(int(window.ProcessId)), "/F"], capture_output=True, check=False)


@pytest.fixture
def model() -> Iterator[CalcModel]:
    made = CalcModel()
    yield made
    made.close()


@needs_desktop
def test_the_bot_ui_starts_the_worker_and_the_runner_uses_it(tmp_path: Path, model: CalcModel) -> None:
    """Bot UI → (자식) Worker, Bot UI → (자식) 실행기 → HTTP → Worker → 진짜 창. **가짜가 없다** (모델 빼고)."""
    from chaeksas.bot_ui.agent import Agent  # noqa: PLC0415
    from chaeksas.bot_ui.bots import install  # noqa: PLC0415
    from chaeksas.bot_ui.runtimes import token_dir_for  # noqa: PLC0415
    from chaeksas.bot_ui.settings import RuntimeSettings, Settings, data_dir  # noqa: PLC0415
    from chaeksas.bot_ui.store import Store  # noqa: PLC0415
    from chaeksas.core.run_log import RunLog, log_path  # noqa: PLC0415
    from chaeksas.studio.packaging import default_name, export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    tag = f" #{os.getpid()}b"
    spec = calculator_settings(token_dir_for("worker"), tag)
    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, FX05)
    bot = install(data_dir(), export(made, tmp_path / default_name(made)))
    settings = Settings(
        center_url="http://127.0.0.1:1",
        runtimes=(RuntimeSettings(runtime_id="worker", port=free_port()),),
        llm_base_url=model.base_url,
        llm_model="stub",
    )
    agent = Agent(settings=settings, store=Store.load(tmp_path / "s.json"), host=load_host())
    try:
        item = agent.enqueue_manual(bot.id, version=bot.version)
        # 입력은 Center 작업이 실어 오는 자리에 둔다 (수동 실행 화면은 입력을 받지 않는다).
        agent.store.state.inputs[item.queue_id] = {"식": "12*34"}
        agent.pump()
        assert agent.current_run is not None, "실행이 올라가야 한다"
        run_id = agent.current_run.run_id
        until = time.monotonic() + 90
        while agent.current_run is not None and time.monotonic() < until:
            agent.pump()
            time.sleep(0.3)
        runner_log = log_path(data_dir(), run_id).with_suffix(".runner.log")
        said = runner_log.read_text(encoding="utf-8", errors="replace")[-3000:] if runner_log.is_file() else "(없음)"
        assert log_path(data_dir(), run_id).is_file(), f"실행 기록이 없다 — 실행기 로그:\n{said}"
        events = list(RunLog.read(log_path(data_dir(), run_id)))
        finished = events[-1]
        assert finished.kind == "run_finished", f"{[e.kind for e in events][-5:]}\n{said}"
        assert finished.data["status"] == "success", finished.data
        assert model.seen[-1] == "408", "Worker가 진짜 창의 표시 칸을 읽었다"
    finally:
        agent.runtimes().stop_all()
        close_windows(spec)


@needs_desktop
def test_a_studio_run_uses_the_worker_the_bot_ui_started(tmp_path: Path, model: CalcModel) -> None:
    """Studio는 Worker를 띄우지 않는다 — Bot UI가 띄운 것을 `runtime.json`·토큰 파일로 찾는다 (STU-10)."""
    from chaeksas.bot_ui.runtimes import Runtimes, token_dir_for  # noqa: PLC0415
    from chaeksas.bot_ui.settings import RuntimeSettings, Settings  # noqa: PLC0415
    from chaeksas.contracts.bpmn_ext import read_process  # noqa: PLC0415
    from chaeksas.core.engine import Engine, RunEnv, State  # noqa: PLC0415
    from chaeksas.core.llm import OpenAiCompatibleLlm  # noqa: PLC0415
    from chaeksas.core.run_log import RunLog  # noqa: PLC0415

    tag = f" #{os.getpid()}s"
    spec = calculator_settings(token_dir_for("worker"), tag)
    settings = Settings(runtimes=(RuntimeSettings(runtime_id="worker", port=free_port()),))
    bot_ui = Runtimes(host=load_host(), settings=settings)
    try:
        bot_ui.ensure("worker")
        process = read_process((EXAMPLES / f"{FX05}.bpmn").read_text(encoding="utf-8"))
        env = RunEnv(
            llm=OpenAiCompatibleLlm(base_url=model.base_url, api_key="", model="stub"),
            extensions=Extensions.load().tasks(),
        )
        engine = Engine()
        run = engine.start(
            process, run_id="test_20261005_120000_abcdef", log=RunLog(run_id="test_20261005_120000_abcdef"),
            now=datetime.now(UTC), env=env, inputs={"식": "12*34"}, mode="autonomous",
        )
        assert engine.run_until_blocked(run) is State.DONE, run.error
        assert run.variables["결과"] == 408
    finally:
        bot_ui.stop_all()
        close_windows(spec)


def test_an_unreachable_worker_is_a_retryable_business_failure(tmp_path: Path) -> None:
    """Bot UI가 Worker를 못 띄웠거나 꺼져 있으면 — 실행기가 죽지 않고 오류 경계가 받는다."""
    from chaeksas.ext.ui_automation.client.agent_env import DesktopEnvironment  # noqa: PLC0415
    from chaeksas.ext.ui_automation.client.task import WorkerClient  # noqa: PLC0415
    from chaeksas.extension_api import TaskContext, TaskFailed  # noqa: PLC0415

    nowhere = WorkerClient(token_dir=tmp_path, port=free_port())
    ctx = TaskContext(extension=None, run_id="run_20261005_120000_abcdef", node_id="Task_Calc",  # type: ignore[arg-type]
                      properties={"desktop": {"app": "Calculator"}})
    with pytest.raises(TaskFailed) as caught:
        DesktopEnvironment(client=nowhere).open(ctx)
    assert caught.value.code == "worker_unreachable" and caught.value.retryable


def test_the_bot_ui_starts_the_runtime_of_the_environment_a_domain_needs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FX-05는 그림에 확장을 적지 않았다 — `requires.domains`의 `desktop`으로 그 환경의 확장을 찾는다."""
    from chaeksas.bot_ui.agent import Agent  # noqa: PLC0415
    from chaeksas.bot_ui.bots import install  # noqa: PLC0415
    from chaeksas.bot_ui.runtimes import Runtimes  # noqa: PLC0415
    from chaeksas.bot_ui.settings import Settings, data_dir  # noqa: PLC0415
    from chaeksas.bot_ui.store import Store  # noqa: PLC0415
    from chaeksas.studio.packaging import default_name, export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, FX05)
    bot = install(data_dir(), export(made, tmp_path / default_name(made)))
    assert not bot.manifest.requires.extensions and "desktop" in bot.manifest.requires.domains
    started: list[str] = []
    monkeypatch.setattr(Runtimes, "ensure", lambda self, runtime_id, **_: started.append(runtime_id))
    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1"), store=Store.load(tmp_path / "s.json"),
                  host=load_host())
    table = agent.run_extensions(bot)
    assert started == ["worker"]
    assert table["ui-automation"]["runtime.worker.port"] == 8899
    assert "secret" not in json.dumps(table, default=str).lower(), "비밀은 파일로 넘기지 않는다"

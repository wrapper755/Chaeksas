"""Bot UI가 Bot을 실행한다 (M3 조각 4a) — 설치 → 실행기(자식 프로세스) → 결재 → 끝.

**진짜 자식 프로세스를 띄운다.** 여기가 ADR-0023·ADR-0031이 맞는지 보는 자리다 — 가짜로
바꾸면 「띄우고, 기록으로 보고, 파일로 답한다」가 정말 되는지 모른다.

거듭 보는 것 다섯.

1. **패키지는 Studio가 만든 그대로**다 — 시험이 따로 zip을 짜지 않는다 (C1).
2. **올라오는 길은 실행 기록 하나**다 (C3) — Bot UI는 파일을 읽어 지금 노드와 결재 요청을 안다.
3. **내려가는 길은 제어 파일**이다 (ADR-0031) — 답과 중지.
4. **값은 기록에 없다** (원칙 6) — 결재 답은 제어 파일에만 있고, 끝나면 지운다.
5. **PC 한 대에 Bot 하나** (ADR-0014).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.bot_ui.bots import InstallError, find, install, installed  # noqa: E402
from chaeksas.bot_ui.runner import Launcher, new_run_id, runner_args  # noqa: E402
from chaeksas.core import control  # noqa: E402
from chaeksas.core.run_log import RunLog, log_path  # noqa: E402
from chaeksas.studio.packaging import default_name, export  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

#: 사람이 한 번 확인하고 끝나는 가장 작은 예제 (폼 없는 확인 — C6 `decision`).
MANUAL = "fx19_manual_task_pc"
#: 사람 없이 끝까지 가는 예제 (DMN 한 번).
RULE = "fx02_business_rule"


def packaged(tmp_path: Path, example: str) -> Path:
    """Studio가 하는 일 그대로 — 예제를 가져와 C1 패키지로 내보낸다."""
    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, example)
    return export(made, tmp_path / default_name(made))


def wait_for(check: Any, *, timeout_s: float = 30.0, every_s: float = 0.1) -> bool:
    """자식 프로세스를 기다린다 — 조건이 참이 되면 바로 돌아온다."""
    until = time.monotonic() + timeout_s
    while time.monotonic() < until:
        if check():
            return True
        time.sleep(every_s)
    return False


# ─────────────────────────── 설치 (BUI-04) ───────────────────────────


def test_a_package_can_be_installed_and_listed(tmp_path: Path) -> None:
    data_dir = tmp_path / "botui"
    bot = install(data_dir, packaged(tmp_path, RULE))

    assert bot.entry_path.is_file(), "진입 정의가 풀려 있어야 한다"
    assert bot.signature == "서명 없음", "서명 확인은 M5다 — 모르는 것을 「확인됨」이라 하지 않는다"
    assert [one.id for one in installed(data_dir)] == [bot.id]
    assert find(data_dir, bot.id) is not None


def test_installing_the_same_version_again_replaces_it(tmp_path: Path) -> None:
    data_dir = tmp_path / "botui"
    package = packaged(tmp_path, RULE)
    bot = install(data_dir, package)
    (bot.folder / "남은파일.txt").write_text("지워져야 한다", encoding="utf-8")

    again = install(data_dir, package)
    assert not (again.folder / "남은파일.txt").exists()
    assert len(installed(data_dir)) == 1


def test_a_broken_package_says_why(tmp_path: Path) -> None:
    broken = tmp_path / "가짜.zip"
    broken.write_text("이건 zip이 아니다", encoding="utf-8")
    with pytest.raises(InstallError, match="zip"):
        install(tmp_path / "botui", broken)


def test_a_tampered_package_is_refused(tmp_path: Path) -> None:
    """**보낸 사람이 적은 해시를 믿지 않는다** — 파일에서 다시 계산한다 (C1 R6)."""
    import zipfile

    package = packaged(tmp_path, RULE)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("process/끼워넣은것.txt", "원래 없던 파일")

    with pytest.raises(InstallError, match="해시"):
        install(tmp_path / "botui", package)


# ─────────────────────────── 명령줄 ───────────────────────────


def test_the_command_line_carries_no_business_values(tmp_path: Path) -> None:
    """입력은 **파일로** 준다 — 명령줄은 프로세스 목록에 뜬다 (원칙 6)."""
    args = runner_args(
        package=tmp_path / "pkg",
        run_id="run_20261005_120000_abcdef",
        data_dir=tmp_path,
        inputs_path=tmp_path / "inputs.json",
        mode="deterministic",
        source="manual",
        job_id=None,
    )
    joined = " ".join(args)
    assert "--inputs" in joined and "inputs.json" in joined
    assert "금액" not in joined


# ─────────────────────────── 실행 (진짜 자식 프로세스) ───────────────────────────


def test_a_bot_runs_to_the_end_in_a_child_process(tmp_path: Path) -> None:
    data_dir = tmp_path / "botui"
    bot = install(data_dir, packaged(tmp_path, RULE))
    launcher = Launcher(data_dir=data_dir)

    running = launcher.start(bot, inputs={"등급": "A", "금액": 1000})
    assert launcher.busy

    assert wait_for(lambda: not running.alive), "실행기가 끝나지 않았다"
    done = wait_for(lambda: launcher.tick() is not None)
    assert done and launcher.running is None
    assert running.finished == "success", running.finished

    # 올라오는 길은 **실행 기록 하나**다 (C3).
    events = list(RunLog.read(log_path(data_dir, running.run_id)))
    assert events[0].kind == "run_started"
    assert events[0].data["executor"] == "bot_ui"
    assert events[0].data["mode"] == "deterministic", "운영 실행은 결정 수행이다 (ADR-0010)"
    assert events[-1].kind == "run_finished" and events[-1].data["status"] == "success"


def test_an_approval_is_asked_through_the_log_and_answered_through_the_control_file(
    tmp_path: Path,
) -> None:
    """ADR-0031의 한 바퀴 — 요청은 기록으로 올라오고 답은 제어 파일로 내려간다."""
    data_dir = tmp_path / "botui"
    bot = install(data_dir, packaged(tmp_path, MANUAL))
    launcher = Launcher(data_dir=data_dir)
    running = launcher.start(bot)

    assert wait_for(lambda: bool(_read(running))), "결재 요청이 기록에 올라오지 않았다"
    (asked,) = running.pendings
    assert asked.layer == "confirmation", "`manualTask`는 확인이다 (C6)"

    running.answer(asked.request_id, {"decision": "approve"}, answered_by="김책사")

    assert wait_for(lambda: not running.alive), "답을 줬는데 끝나지 않았다"
    launcher.tick()
    assert running.finished == "success"

    # **값은 기록에 없다** (원칙 6) — `human_answered`에는 답이 담기지 않는다.
    events = list(RunLog.read(log_path(data_dir, running.run_id)))
    answered = next(e for e in events if e.kind == "human_answered")
    assert "decision" not in json.dumps(answered.data, ensure_ascii=False)
    assert answered.data["answered_by"] == "김책사"
    # 제어 파일은 끝나면 **지운다** (답에는 업무 값이 들어 있다).
    assert not running.control_path.exists()


def _read(running: Any) -> list[Any]:
    running.read()
    return list(running.pendings)


def test_stopping_a_waiting_bot_ends_it_as_cancelled(tmp_path: Path) -> None:
    """「중지」는 실패가 아니다 — 무엇을 하다 멈췄는지가 기록에 남는다 (BUI-04)."""
    data_dir = tmp_path / "botui"
    bot = install(data_dir, packaged(tmp_path, MANUAL))
    launcher = Launcher(data_dir=data_dir)
    running = launcher.start(bot)

    assert wait_for(lambda: bool(_read(running))), "결재 요청을 기다렸다"
    launcher.stop()

    assert launcher.running is None
    events = list(RunLog.read(log_path(data_dir, running.run_id)))
    assert events[-1].kind == "run_finished"
    assert events[-1].data["status"] == "cancelled"


def test_only_one_bot_runs_at_a_time(tmp_path: Path) -> None:
    """PC 한 대에 Bot 하나 (ADR-0014) — 나머지는 대기열이 본다."""
    data_dir = tmp_path / "botui"
    bot = install(data_dir, packaged(tmp_path, MANUAL))
    launcher = Launcher(data_dir=data_dir)
    launcher.start(bot)
    try:
        with pytest.raises(RuntimeError, match="이미 실행 중"):
            launcher.start(bot)
    finally:
        launcher.stop()


def test_a_run_id_looks_like_the_contract_says() -> None:
    made = new_run_id()
    assert made.startswith("run_") and len(made.split("_")) == 4


# ─────────────────────────── 제어 파일 (ADR-0031) ───────────────────────────


def test_a_command_is_read_once(tmp_path: Path) -> None:
    """두 번 읽으면 같은 결재에 두 번 답한다."""
    path = tmp_path / "runs" / "run_1.control.jsonl"
    control.answer(path, "req-1", {"decision": "approve"}, answered_by="사람")
    assert [one.request_id for one in control.take(path)] == ["req-1"]
    assert control.take(path) == []

    control.stop(path)
    assert [one.kind for one in control.take(path)] == ["stop"]


def test_a_half_written_line_is_skipped_until_it_is_whole(tmp_path: Path) -> None:
    """덧붙이는 중에 읽을 수 있다 — 깨진 줄에서 멈추지 않는다."""
    path = tmp_path / "runs" / "run_1.control.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"kind": "sto', encoding="utf-8")
    assert control.take(path) == []


def test_clearing_removes_the_values(tmp_path: Path) -> None:
    path = tmp_path / "runs" / "run_1.control.jsonl"
    control.answer(path, "req-1", {"사유": "업무상 사용"}, answered_by="사람")
    control.take(path)
    control.clear(path)
    assert not path.exists()
    assert not path.with_suffix(path.suffix + control.READ_SUFFIX).exists()


# ─────────────────────────── 대기열 → 실행 (C4) ───────────────────────────


def test_the_queue_starts_the_next_bot_and_frees_the_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pump()` 한 바퀴 — 대기열에서 올리고, 끝나면 자리를 비운다 (ADR-0014)."""
    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.settings import Settings
    from chaeksas.bot_ui.store import Store

    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    bot = install(data_dir, packaged(tmp_path, RULE))

    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1"), store=Store.load(tmp_path / "s.json"))
    agent.enqueue_manual(bot.id, version=bot.version)
    agent.pump()

    assert agent.current_run is not None, "자리를 차지해야 한다"
    assert agent.current_run.bpm_process_id == bot.id
    assert not agent.queue, "대기열에서 빠져야 한다"

    def swept() -> bool:
        agent.pump()
        return agent.current_run is None

    assert wait_for(swept, timeout_s=30)
    assert agent.runner().running is None


def test_a_bot_that_is_not_installed_is_rejected_not_stuck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조용히 두면 대기열이 **영원히 막힌다** — 빼고 이유를 남긴다."""
    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.settings import Settings
    from chaeksas.bot_ui.store import Store

    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: tmp_path / "botui")
    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1"), store=Store.load(tmp_path / "s.json"))
    agent.enqueue_manual("없는.bot")
    agent.pump()

    assert not agent.queue and agent.current_run is None


# ─────────────────────────── BUI-04 화면 ───────────────────────────


def test_the_bot_tab_shows_what_is_installed_and_runs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUI-04 — 목록·「지금 실행...」·「중지」·「결재 창 열기」가 Agent와 맞물린다."""
    from PySide6.QtWidgets import QApplication

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.main_window import MainWindow
    from chaeksas.bot_ui.settings import Settings
    from chaeksas.bot_ui.store import Store

    app = QApplication.instance() or QApplication([])
    assert app is not None

    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    bot = install(data_dir, packaged(tmp_path, MANUAL))

    agent = Agent(settings=Settings(center_url="http://127.0.0.1:1"), store=Store.load(tmp_path / "s.json"))
    window = MainWindow(agent)
    window.refresh()

    assert window.bots_table.rowCount() == 1
    assert _cell(window, 0, 0) == bot.name
    assert _cell(window, 0, 3) == "서명 없음"
    assert not window.run_button.isEnabled(), "고른 Bot이 없으면 꺼져 있다"
    assert not window.stop_button.isEnabled()

    window.bots_table.selectRow(0)
    assert window.run_button.isEnabled()
    window.run_selected()

    assert agent.current_run is not None, "자리를 차지해야 한다"
    try:
        # 결재를 기다리면 「결재 창 열기」가 켜진다 (BUI-04 [R]).
        def asked() -> bool:
            agent.pump()
            window.refresh()
            return window.approve_button.isEnabled()

        assert wait_for(asked, timeout_s=30), "결재 요청이 올라오지 않았다"
        assert "결재를 기다리는 중" in window.running_label.text()
    finally:
        agent.runner().stop()
        agent.release_slot()


def _cell(window: Any, row: int, column: int) -> str:
    item = window.bots_table.item(row, column)
    return item.text() if item is not None else ""


def test_installing_a_broken_package_does_not_crash_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """설치가 실패해도 창은 산다 — 사람이 읽을 한 줄을 보인다."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.main_window import MainWindow
    from chaeksas.bot_ui.settings import Settings
    from chaeksas.bot_ui.store import Store

    app = QApplication.instance() or QApplication([])
    assert app is not None

    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: tmp_path / "botui")
    broken = tmp_path / "가짜.zip"
    broken.write_text("zip이 아니다", encoding="utf-8")

    said: list[str] = []
    monkeypatch.setattr(
        "chaeksas.bot_ui.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(broken), "")),
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: said.append(a[2])))

    window = MainWindow(Agent(settings=Settings(), store=Store.load(tmp_path / "s.json")))
    window.install_package()
    assert said and "zip" in said[0]


def test_the_settings_reach_the_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """BUI-03이 정한 것이 실행기까지 간다 — **키는 환경변수로**, 주소는 명령줄로 (조각 4c)."""
    from dataclasses import replace as _replace

    from chaeksas.bot_ui.agent import Agent
    from chaeksas.bot_ui.credentials import ENV_LLM_API_KEY
    from chaeksas.bot_ui.settings import Settings
    from chaeksas.bot_ui.store import Store

    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    monkeypatch.setenv(ENV_LLM_API_KEY, "sk-시험")

    shared = tmp_path / "공유"
    shared.mkdir()
    settings = _replace(
        Settings(),
        llm_base_url="http://127.0.0.1:11434",
        llm_model="qwen2.5:7b",
        readable_dirs=(shared,),
    )
    agent = Agent(settings=settings, store=Store.load(tmp_path / "s.json"))

    seen: dict[str, Any] = {}

    class FakeChild:
        alive = False

        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        def start(self) -> None:
            pass

        def poll(self) -> int | None:
            return 0

    launcher = agent.runner()
    launcher.make_child = FakeChild
    bot = install(data_dir, packaged(tmp_path, RULE))
    launcher.start(bot)

    joined = " ".join(seen["args"])
    assert "--llm-url http://127.0.0.1:11434" in joined
    assert "--readable" in joined and str(shared) in joined
    # **키는 명령줄에 없다** (프로세스 목록에 뜬다) — 환경변수로 간다.
    assert "sk-시험" not in joined
    assert seen["env"][ENV_LLM_API_KEY] == "sk-시험"
    assert "PATH" in seen["env"], "환경을 통째로 물려준다 — 키만 주면 PATH도 없는 자식이 된다"


def test_the_runner_is_told_how_long_the_item_waited() -> None:
    """C3 `run_started.queued_s` — **Bot UI만 안다** (요청 시각과 띄우는 시각 사이)."""
    args = runner_args(
        package=Path("/tmp/pkg"),
        run_id="run_20261009_101500_abcdef",
        data_dir=Path("/tmp/data"),
        inputs_path=None,
        mode="deterministic",
        source="job",
        job_id="job_1",
        queued_s=42.4567,
    )
    assert "--queued-s" in args
    assert args[args.index("--queued-s") + 1] == "42.457", "소수 셋째 자리까지"


def test_a_runner_that_does_not_know_the_wait_says_nothing() -> None:
    """**모르면 넣지 않는다** — 0을 넣으면 「기다리지 않았다」가 된다."""
    args = runner_args(
        package=Path("/tmp/pkg"),
        run_id="run_20261009_101500_abcdef",
        data_dir=Path("/tmp/data"),
        inputs_path=None,
        mode="deterministic",
        source="manual",
        job_id=None,
    )
    assert "--queued-s" not in args

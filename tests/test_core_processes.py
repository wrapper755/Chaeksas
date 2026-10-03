"""자식 프로세스 관리 (ADR-0023). **Windows CI에서도 이 시험이 돈다** — 거기가 주 환경이다.

진짜 자식을 띄운다 (`sys.executable -c ...`). 그래서 Windows에서는 Job Object 길, 그 밖에서는
프로세스 그룹 길이 실제로 실행된다.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from chaeksas.core.processes import (
    MAX_RESTARTS,
    ChildProcess,
    ProcessError,
    Supervisor,
)

#: 가만히 오래 사는 자식.
SLEEPER = "import time; time.sleep(120)"
#: 바로 죽는 자식 (감시자가 다시 띄우는 길을 보려고).
QUITTER = "raise SystemExit(3)"
#: 손자를 띄우고 자기는 기다리는 자식 — 트리째 죽는지 본다.
PARENT_OF_CHILD = (
    "import subprocess, sys, time;"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
    "print(p.pid, flush=True);"
    "time.sleep(120)"
)


def python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def waits_until(check, *, timeout_s: float = 10.0) -> bool:  # type: ignore[no-untyped-def]
    """조건이 참이 될 때까지 짧게 기다린다 (고정 `sleep`을 쓰지 않으려고)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


# ─────────────────────────── 띄우고 멈추기 ───────────────────────────


def test_start_and_stop() -> None:
    child = ChildProcess(args=python(SLEEPER), name="sleeper")
    child.start()
    assert child.alive and child.pid
    code = child.stop(timeout_s=10)
    assert not child.alive
    assert code is not None


def test_starting_twice_is_harmless() -> None:
    child = ChildProcess(args=python(SLEEPER))
    child.start()
    first = child.pid
    child.start()
    assert child.pid == first
    child.stop(timeout_s=10)


def test_stopping_something_that_never_started() -> None:
    assert ChildProcess(args=python(SLEEPER)).stop() is None


def test_an_empty_command_is_refused() -> None:
    with pytest.raises(ProcessError, match="비어 있다"):
        ChildProcess(args=[]).start()


def test_a_missing_program_says_so() -> None:
    with pytest.raises(ProcessError, match="띄우지 못했다"):
        ChildProcess(args=["이런-프로그램은-없다"], name="worker").start()


def test_output_goes_to_the_log_file(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "worker.log"
    child = ChildProcess(args=python("print('안녕')"), log_path=log, name="worker")
    child.start()
    assert waits_until(lambda: child.poll() is not None)
    child.stop()
    # 폴더를 만들고 붙여 쓴다. 자식이 찍은 한글이 그대로 들어 있다.
    assert "안녕" in log.read_text(encoding="utf-8")


def test_the_whole_tree_dies(tmp_path: Path) -> None:
    """**손자까지** 죽는다 — Windows는 Job Object, 그 밖에서는 프로세스 그룹 (ADR-0023)."""
    log = tmp_path / "tree.log"
    child = ChildProcess(args=python(PARENT_OF_CHILD), log_path=log, name="parent")
    child.start()

    # 자식이 찍은 손자 pid를 읽는다.
    assert waits_until(lambda: log.exists() and log.read_text(encoding="utf-8").strip().isdigit())
    grandchild = int(log.read_text(encoding="utf-8").strip())

    child.stop(timeout_s=10)
    assert not child.alive
    assert waits_until(lambda: not _alive(grandchild)), f"손자 {grandchild}가 남았다"


def _alive(pid: int) -> bool:
    """그 pid가 살아 있나. OS별로 방법이 다르다."""
    if sys.platform == "win32":
        found = subprocess.run(  # noqa: S603 — 인자 리스트
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, check=False
        )
        return str(pid) in found.stdout
    import os  # noqa: PLC0415

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - 남의 프로세스
        return True
    return True


# ─────────────────────────── 감시 ───────────────────────────


class Clock:
    """시험용 시계 — 백오프를 기다리지 않는다."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def supervisor(code: str, *, clock: Clock | None = None, **kwargs: object) -> Supervisor:
    found = Supervisor(child=ChildProcess(args=python(code), name="worker"), **kwargs)  # type: ignore[arg-type]
    if clock is not None:
        found._monotonic = clock  # noqa: SLF001 — 시험에서 시계를 바꿔 끼운다
    return found


def test_a_supervisor_starts_and_reports_running() -> None:
    found = supervisor(SLEEPER)
    assert found.state == "off", "시작 전에는 「꺼 둠」이다 (필요할 때 시작, C4)"
    found.start()
    assert found.state == "running"
    found.tick()
    assert found.state == "running"
    found.stop(timeout_s=10)
    assert found.state == "off"


def test_a_dead_child_is_restarted_after_the_backoff() -> None:
    clock = Clock()
    found = supervisor(QUITTER, clock=clock)
    found.start()
    assert waits_until(lambda: not found.child.alive)

    found.tick()  # 죽은 것을 보고 백오프를 잡는다
    assert (found.state, found.restarts) == ("restarting", 1)
    assert "멈췄다" in (found.last_error or "")

    found.tick()  # 아직 기다리는 중이다
    assert found.state == "restarting"

    clock.tick(60)
    found.tick()  # 이제 다시 띄운다
    assert found.state == "running"
    found.stop(timeout_s=10)


def test_it_gives_up_after_too_many_restarts() -> None:
    """계속 죽으면 그만둔다 (`stopped`) — 사람이 설정을 봐야 한다."""
    clock = Clock()
    found = supervisor(QUITTER, clock=clock)
    found.start()
    for _ in range(MAX_RESTARTS + 2):
        assert waits_until(lambda: not found.child.alive)
        found.tick()
        clock.tick(60)
        found.tick()
    assert found.state == "stopped"
    assert found.restarts > MAX_RESTARTS


def test_a_stopped_supervisor_stays_stopped() -> None:
    found = supervisor(QUITTER)
    found.state = "stopped"
    found.tick()
    assert found.state == "stopped" and not found.child.alive


def test_long_uptime_forgets_the_restart_count() -> None:
    """몇 달 뒤의 한 번이 한도를 채우지 않게 — 오래 잘 돌면 연속 실패를 잊는다."""
    found = supervisor(SLEEPER, healthy_after_s=0.0)
    found.start()
    found.restarts = 3
    found.tick()
    assert found.restarts == 0
    found.stop(timeout_s=10)


def test_a_broken_command_lands_in_stopped() -> None:
    found = Supervisor(child=ChildProcess(args=["이런-프로그램은-없다"], name="worker"))
    found.start()
    assert found.state == "stopped"
    assert "띄우지 못했다" in (found.last_error or "")

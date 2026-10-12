"""자식을 기다리는 한 자리 (`tests/waiting.py`) — 시험을 돕는 코드도 시험한다.

**한도를 늘린 대신 「죽었으면 바로 끝낸다」가 붙었다.** 그 둘이 함께 돌아야 한다 — 늘리기만
하면 진짜 고장이 2분을 태우고, 바로 끝내기만 하면 느린 Windows에서 멀쩡한 시험이 깨진다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from waiting import DEFAULT_TIMEOUT_S, wait_for


@dataclass
class FakeChild:
    """`ChildProcess`의 두 칸만 흉내 낸다 (`alive`·`log_path`)."""

    alive: bool = True
    log_path: Path | None = None


def test_a_true_condition_comes_back_at_once() -> None:
    started = time.monotonic()
    assert wait_for(lambda: True) is True
    assert time.monotonic() - started < 1.0


def test_a_dead_child_ends_the_wait_instead_of_burning_the_budget() -> None:
    """**진짜 고장은 더 빨리 드러난다** — 조건을 만들 쪽이 사라졌으면 기다리지 않는다."""
    started = time.monotonic()
    assert wait_for(lambda: False, timeout_s=30.0, child=FakeChild(alive=False)) is False
    assert time.monotonic() - started < 2.0, "한도를 태우지 않는다"


def test_a_child_that_wrote_and_then_died_still_counts(tmp_path: Path) -> None:
    """실행기는 **쓰고 바로 끝난다** — 죽음을 먼저 보면 그것을 놓친다 (순서가 규칙이다)."""
    made = tmp_path / "요청.jsonl"
    made.write_text("{}\n", encoding="utf-8")
    assert wait_for(made.is_file, timeout_s=5.0, child=FakeChild(alive=False)) is True


def test_giving_up_prints_the_child_log_tail(tmp_path: Path, capsys: object) -> None:
    """포기한 까닭과 자식 로그를 찍는다 — CI 로그만 보고도 무엇이 멈췄는지 알게."""
    log = tmp_path / "runner.log"
    log.write_text("첫 줄\n마지막 줄: 설정을 읽지 못했다\n", encoding="utf-8")
    assert wait_for(lambda: False, timeout_s=0.3, child=FakeChild(log_path=log)) is False
    found = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "포기" in found and "마지막 줄: 설정을 읽지 못했다" in found


def test_the_default_budget_is_bigger_on_windows() -> None:
    """자식은 파이썬을 새로 띄워 우리 패키지를 전부 import한다 — 거기서 수십 초가 갈린다."""
    import sys

    assert DEFAULT_TIMEOUT_S == (120.0 if sys.platform == "win32" else 30.0)

"""자식 프로세스를 기다리는 한 자리. **제품 코드가 아니다.**

진짜 실행기를 띄우는 시험(결재 통로·실행 프로세스·PC 예제 재통과)은 모두 「자식이 파일에
쓸 때까지」를 기다린다. 그 기다림을 파일마다 베껴 두었더니 **셋이 서로 다른 한도**를 들고
있었고, 느린 Windows 러너에서 30초를 넘겨 **CI가 빨갛게 됐다** (실행 38279716454 —
`test_approval_channel.py`, 그 묶음이 Linux의 4배 느렸다. 다시 돌리니 통과했다).

그래서 셋을 하나로 모으고 둘을 더했다.

- **Windows에는 더 준다.** 자식은 파이썬을 새로 띄워 우리 패키지를 전부 import한다 — 거기서
  갈리는 것이 수십 초다 (CI Windows 잡은 8~10분, Linux는 2~3분).
- **죽었으면 바로 끝낸다.** 자식이 이미 끝났는데 조건이 거짓이면 더 기다릴 이유가 없다 —
  한도를 늘린 대신 **진짜 고장은 더 빨리** 드러나야 한다. 포기할 때는 자식이 남긴 로그
  꼬리를 찍는다(pytest가 실패한 시험의 stdout을 보여 준다) — 다음 사람이 CI 로그만 보고도
  무엇이 멈췄는지 알게.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

#: 조건을 다시 재는 간격.
EVERY_S = 0.1

#: 기본 한도 — Windows는 자식이 뜨는 데만 수십 초가 걸린다.
DEFAULT_TIMEOUT_S = 120.0 if sys.platform == "win32" else 30.0

#: 포기할 때 찍는 자식 로그 줄 수.
LOG_TAIL = 20


class Child(Protocol):
    """`core.processes.ChildProcess`가 주는 것 중 여기서 쓰는 둘."""

    @property
    def alive(self) -> bool: ...

    log_path: Path | None


def wait_for(
    check: Callable[[], Any],
    *,
    timeout_s: float | None = None,
    every_s: float = EVERY_S,
    child: Child | None = None,
) -> bool:
    """`check()`가 참이 될 때까지 기다린다. 참이면 바로 `True`.

    `child`를 주면 **그 자식이 죽은 순간 포기한다** — 조건을 만들 쪽이 사라졌으니 남은
    한도를 태울 이유가 없다. 포기한 까닭과 자식 로그 꼬리를 찍는다.
    """
    budget = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
    started = time.monotonic()
    until = started + budget
    while True:
        if check():
            return True
        # **죽었는지 보기 전에 조건을 한 번 더 본다** — 자식이 쓰고 바로 끝나는 길이 있다
        # (끝낸 실행기가 요청 파일을 남기고 죽는다). 순서를 뒤집으면 그것을 놓친다.
        if child is not None and not child.alive and not check():
            _say(f"자식이 먼저 끝났다 ({time.monotonic() - started:.1f}초)", child)
            return False
        if time.monotonic() >= until:
            alive = child.alive if child is not None else None
            _say(f"{budget:.0f}초를 기다렸다 (자식 살아 있음: {alive if child is not None else '모름'})", child)
            return False
        time.sleep(every_s)


def _say(why: str, child: Child | None) -> None:
    """포기한 까닭 + 자식 로그 꼬리 (pytest가 실패한 시험의 stdout을 보여 준다)."""
    print(f"[wait_for] 포기: {why}")
    path = getattr(child, "log_path", None)
    if path is None or not Path(path).is_file():
        return
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"[wait_for] {path} 끝 {LOG_TAIL}줄:")
    for line in lines[-LOG_TAIL:]:
        print(f"  | {line}")


__all__ = ["DEFAULT_TIMEOUT_S", "EVERY_S", "LOG_TAIL", "Child", "wait_for"]

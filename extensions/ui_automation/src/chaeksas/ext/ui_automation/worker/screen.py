"""화면을 만지는 일은 **스레드 하나**에서 한다 — Worker의 HTTP 창구와 화면 백엔드 사이.

둘이 같은 까닭을 다르게 요구한다.

- **Playwright 동기 API는 asyncio 루프 안에서 돌지 않는다** («Sync API inside the asyncio loop»).
  Worker의 창구는 uvicorn 루프에서 돌므로 거기서 브라우저를 부르면 세션이 열리지 않는다. 그리고
  한 번 띄운 브라우저는 **띄운 스레드에서만** 만질 수 있다 — 스레드 풀에 흩으면 다음 스텝이 깨진다.
- **UIA(COM)는 스레드마다 초기화한다** — `uiautomation`은 import한 스레드만 저절로 준비한다.

그래서 Worker의 일(세션 열기·스텝·보기·등록·닫기·유휴 정리)은 전부 이 스레드 하나로 보낸다.
세션은 한 번에 하나(ADR-0014)라 줄을 세워도 잃는 것이 없다. **`health`는 기다리지 않는다** —
긴 스텝 동안에도 PC 실행기의 살아 있나 확인에 답해야 한다(못 하면 멀쩡한 Worker를 다시 띄운다).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import sys
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

#: 스레드 이름 — 로그·덤프에서 알아보게.
THREAD_NAME = "chk-screen"


def _prepare_thread() -> None:
    """이 스레드에서 UIA를 쓸 수 있게 한다 (Windows). 없으면 조용히 지나간다 — 웹만 쓰는 PC다."""
    if sys.platform == "win32":
        try:
            import uiautomation  # noqa: PLC0415 — Windows에서만 깔린다

            uiautomation.InitializeUIAutomationInCurrentThread()
        except Exception as e:  # noqa: BLE001 — 데스크톱이 없어도 웹 세션은 돌아야 한다
            log.info("이 스레드에서 UIA를 준비하지 못했다 (데스크톱 세션만 막힌다): %s", e)


class ScreenThread:
    """Worker의 일을 차례로 받는 스레드 하나."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=THREAD_NAME, initializer=_prepare_thread
        )

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """그 스레드에서 돌리고 **루프를 막지 않고** 기다린다. 예외는 그대로 올라온다."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, functools.partial(fn, *args, **kwargs))

    def nudge(self, fn: Callable[[], Any]) -> Future[Any]:
        """기다리지 않고 맡긴다 — 유휴 정리처럼 답에 필요 없는 일."""
        made = self._pool.submit(fn)
        made.add_done_callback(_log_failure)
        return made

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _log_failure(done: Future[Any]) -> None:
    if done.cancelled():
        return
    problem = done.exception()
    if problem is not None:
        log.warning("맡긴 일이 실패했다: %s", problem)


__all__ = ["THREAD_NAME", "ScreenThread"]

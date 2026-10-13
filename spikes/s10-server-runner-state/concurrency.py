"""s10 ③ — 동시 실행의 모양: 프로세스 N개 ↔ 한 프로세스 안 N건.

엔진은 **스레드를 만들지 않고** 부르는 쪽이 `step()`을 민다. 그래서 한 프로세스가 N건을
번갈아 미는 「협력 루프」가 가능하다 — **CPU만 쓰는 걸음이면** 그렇다. 업무는 대개 HTTP를
기다리므로(서비스 앱·모델·웹훅) **막히는 걸음 하나가 루프 전체를 세우는가**를 재 본다.

세 모양을 같은 일로 견준다 (BX-03의 「소액 자동승인」 길 — 멈추지 않고 웹훅 하나를 보낸다).

| 모양 | 어떻게 |
| --- | --- |
| 협력 | 한 프로세스·한 스레드. `step()`을 번갈아 민다 |
| 스레드 | 한 프로세스. 실행마다 스레드 하나 |
| 프로세스 | 실행마다 OS 프로세스 하나 |

`python concurrency.py`로 돌린다.
"""

from __future__ import annotations

import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.core.engine import Engine, Run, State
from chaeksas.core.run_log import RunLog
from chaeksas.core.senders import EmailMessage, SendResult, WebhookRequest
from common import INPUTS, Clock, env, load, new_run_id_for

#: 보내기 한 번이 막혀 있는 시간 — 서비스 앱·모델 왕복을 대신한다.
BLOCK_S = 0.2
#: 몇 건을 함께 돌리나 (C12의 실행기 상한 기본은 10이다).
RUNS = 8

#: 멈추지 않고 끝까지 가는 입력 (금액 ≤ 자동승인한도).
SMALL = {**INPUTS, "금액": 30000}


@dataclass
class SlowSender:
    """보내기가 `BLOCK_S`만큼 막힌다 (HTTP 왕복을 흉내 낸다)."""

    webhooks: list[WebhookRequest] = field(default_factory=list)

    def send_email(self, message: EmailMessage) -> SendResult:
        time.sleep(BLOCK_S)
        return SendResult(ok=True, id="slow")

    def send_webhook(self, request: WebhookRequest) -> SendResult:
        time.sleep(BLOCK_S)
        self.webhooks.append(request)
        return SendResult(ok=True, status=200, text="")


def make(engine: Engine, clock: Clock, out: Path, *, blocking: bool) -> Run:
    run_id = new_run_id_for(clock)
    return engine.start(
        load(),
        run_id=run_id,
        log=RunLog(run_id=run_id),
        inputs=SMALL,
        mode="deterministic",
        executor="server_runner",
        version="1.0.0",
        now=clock(),
        env=env(clock, SlowSender() if blocking else None, out),
    )


# ─────────────────────────── 세 모양 ───────────────────────────


def cooperative(n: int, out: Path, *, blocking: bool) -> tuple[float, int]:
    """한 프로세스·한 스레드. **엔진의 본래 모양** — 토큰 하나씩 번갈아 민다."""
    engine = Engine()
    clock = Clock()
    runs = [make(engine, clock, out, blocking=blocking) for _ in range(n)]
    at = time.perf_counter()
    while any(not r.finished for r in runs):
        for run in runs:
            if not run.finished and not engine.blocked(run):
                engine.step(run)  # **한 걸음만** — 그래서 번갈아 나아간다
            elif not run.finished and engine.blocked(run):
                engine.run_until_blocked(run)
    return time.perf_counter() - at, sum(r.state is State.DONE for r in runs)


def threaded(n: int, out: Path, *, blocking: bool) -> tuple[float, int]:
    """한 프로세스·스레드 N개. 막히는 걸음은 GIL을 놓으므로 겹친다."""
    engine = Engine()
    clock = Clock()
    runs = [make(engine, clock, out, blocking=blocking) for _ in range(n)]
    at = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(lambda r: engine.run_until_blocked(r), runs))
    return time.perf_counter() - at, sum(r.state is State.DONE for r in runs)


def _one(args: tuple[bool, str]) -> str:
    """프로세스 하나가 실행 하나를 돈다 (`ProcessPoolExecutor`가 부른다).

    인자를 **값으로** 넘긴다 — Windows는 `spawn`이라 전역을 물려받지 못한다.
    """
    blocking, out = args
    engine = Engine()
    clock = Clock()
    run = make(engine, clock, Path(out), blocking=blocking)
    engine.run_until_blocked(run)
    return run.state.value


def processes(n: int, out: Path, *, blocking: bool) -> tuple[float, int]:
    at = time.perf_counter()
    with ProcessPoolExecutor(max_workers=n) as pool:
        states = list(pool.map(_one, [(blocking, str(out))] * n))
    return time.perf_counter() - at, states.count("done")


# ─────────────────────────── 자리 셈 (C12 §Center가 작업을 나누는 규칙) ───────────────────────────


def slots(out: Path) -> dict[str, Any]:
    """**기다리는 실행은 자리를 쥐지 않는다** (C12 — PC의 ADR-0014와 거꾸로다).

    상한 3에 세 건을 돌리고, 하나가 결재를 기다리면 빈자리가 하나 생기는지 본다.
    """
    cap = 3
    engine = Engine()
    clock = Clock()

    # 결재를 기다리는 세 건 (금액이 커서 결재로 간다 — `location: center`다).
    held: list[Run] = []
    for _ in range(cap):
        run_id = new_run_id_for(clock)
        run = engine.start(
            load(), run_id=run_id, log=RunLog(run_id=run_id), inputs=INPUTS,
            mode="deterministic", executor="server_runner", version="1.0.0",
            now=clock(), env=env(clock, None, out),
        )
        engine.run_until_blocked(run)
        held.append(run)

    # C12 `capacity.running`은 **기다리는 것을 뺀 수**다.
    running = sum(1 for r in held if not r.finished and r.state is not State.WAITING)
    stalled = sum(1 for r in held if r.state is State.WAITING)
    return {
        "상한 (capacity.max)": cap,
        "들고 있는 실행": len(held),
        "capacity.running (자리를 쥔다)": running,
        "waiting[] (자리를 놓았다)": stalled,
        "빈자리 = max - running": cap - running,
        "그래서": f"상한 {cap}인데 기다리는 {stalled}건을 들고도 새 작업 {cap - running}건을 더 받는다",
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run_all(Path(tmp))


def run_all(out: Path) -> None:
    print(f"③ 같은 일 {RUNS}건 — 셋을 견준다 (막히는 보내기 {BLOCK_S}초)\n")
    print("  막히지 않을 때 (CPU만)")
    for name, fn in (("협력", cooperative), ("스레드", threaded), ("프로세스", processes)):
        took, done = fn(RUNS, out, blocking=False)
        print(f"    {name:5} {took * 1000:7.0f}ms  끝난 것 {done}/{RUNS}")

    print(f"\n  막힐 때 (보내기 {BLOCK_S}초 × {RUNS}건 = 차례로 돌면 {BLOCK_S * RUNS:.1f}초)")
    for name, fn in (("협력", cooperative), ("스레드", threaded), ("프로세스", processes)):
        took, done = fn(RUNS, out, blocking=True)
        print(f"    {name:5} {took * 1000:7.0f}ms  끝난 것 {done}/{RUNS}")

    print("\n④ 자리 셈 — 기다리는 실행이 자리를 쥐나")
    for key, value in slots(out).items():
        print(f"    {key}: {value}")


if __name__ == "__main__":
    main()

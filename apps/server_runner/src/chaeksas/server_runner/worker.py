"""실행 하나를 돌리는 일꾼 — **스레드 하나** (C12, ADR-0054 §5
— `docs/decisions/0054-server-run-state-and-concurrency.md`).

PC와 **모양이 다르다**: Bot UI는 Bot 하나마다 **자식 프로세스**를 띄우고(ADR-0023) 제어
파일로 말을 건넨다. 서버는 한 프로세스 안에서 **실행마다 스레드 하나**다 — 협력 루프는
막히는 걸음 하나가 루프 전체를 세워 상한 10이 사실상 1이 되는 것을 스파이크가 재 보았다
(`spikes/s10-server-runner-state/`).

**`Run` 하나는 그 스레드만 만진다.** 그러므로 바깥에서 묻는 쪽(하트비트)은 `Run`을 **아예
건드리지 않는다** — 도는 스레드가 걸음마다 `Snapshot`을 **찍어 두고**, 묻는 쪽은 찍힌 것을
받는다.

처음에는 `snapshot()`이 `Run`을 그 자리에서 읽게 짰는데, 그것은 **경쟁이다**: 엔진이 토큰을
지우는 사이에 `run.tokens[0]`을 읽으면 `IndexError`이고, `pendings`·`waits`를 훑는 동안
엔진이 그 사전을 고치면 「크기가 바뀌었다」로 터진다. 드물게 나고 **도는 실행을 들여다보다
실행기가 죽는다** — 그래서 찍어 두는 쪽으로 바꿨다.

**아직 사람을 기다리는 실행을 이어 가지 못한다** (M7 조각 4-②) — 멈추면 `waiting[]`으로
보고하고 **자리를 놓지만**, 답을 받아 이어 가는 길과 재시작을 넘기는 저장소는 다음 조각이다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.contracts.server_runner import RunningRun, WaitingRun
from chaeksas.core.engine import Engine, EngineError, Run, RunEnv, State
from chaeksas.core.packages import InstalledBot, UnusablePackage
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.core.run_state import WAIT_MESSAGE, new_run_id

log = logging.getLogger(__name__)

#: 한 번 깨어날 때 밟는 노드 수 — 중지 신호를 자주 본다 (PC 실행기와 같은 수).
STEPS_PER_TICK = 50
#: 멈춘 뒤 타이머를 보는 간격 (초).
TICK_S = 0.2

#: C12 `waiting[].waiting_for` — 무엇을 기다리나.
WAITING_APPROVAL = "approval"
WAITING_MESSAGE = "message"
WAITING_TIMER = "timer"

#: 아무것도 돌지 않은 실행의 셈 (C3 `run_finished`의 필수 칸). **빠뜨리면 그 줄이 거부된다.**
EMPTY_COUNTS: dict[str, Any] = {
    "ai_tasks": 0,
    "replayed_tasks": 0,
    "ui_tasks": 0,
    "service_calls": 0,
    "human_requests": 0,
}

#: 작업 ack 결과 (C4 — 실행의 성패는 `run_status`로 간다, C5).
ACK_STARTED = "started"
ACK_FINISHED = "finished"
ACK_FAILED = "failed"
ACK_CANCELLED = "cancelled"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Snapshot:
    """바깥에서 본 지금 모습 — **베낀 것**이다 (하트비트가 이것으로 본문을 짓는다)."""

    run_id: str
    bpm_process_id: str
    version: str
    started_at: str
    job_id: str | None
    node_id: str | None
    state: str
    #: 기다리는 중이면 C12 `waiting[]` 한 줄, 아니면 `None`.
    waiting: WaitingRun | None = None
    #: 끝났으면 C3 `run_finished.status` (`success`·`failed`·`cancelled`), 아니면 `None`.
    finished: str | None = None
    failure: str = ""

    @property
    def done(self) -> bool:
        return self.finished is not None

    @property
    def holds_a_slot(self) -> bool:
        """자리를 쥐고 있나 — **기다리는 실행은 놓는다** (C12, PC와 거꾸로다)."""
        return not self.done and self.waiting is None

    def running_row(self) -> RunningRun:
        return RunningRun(
            run_id=self.run_id,
            bpm_process_id=self.bpm_process_id,
            version=self.version,
            node_id=self.node_id,
            started_at=self.started_at,
            job_id=self.job_id,
        )


@dataclass
class Worker:
    """실행 하나. `start()`로 스레드를 띄우고 `snapshot()`으로 들여다본다."""

    bot: InstalledBot
    data_dir: Path
    env: RunEnv
    run_id: str = ""
    job_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    mode: str = "deterministic"
    source: str = "job"
    #: 대기열에서 기다린 초 (C3 `run_started.queued_s`). **모르면 `None`** — 0과 다르다.
    queued_s: float | None = None

    engine: Engine = field(default_factory=Engine)
    run: Run | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stopping: bool = False
    _failure: str = ""
    #: 도는 스레드가 찍어 둔 지금 모습. 묻는 쪽은 이것만 본다 (`Run`을 건드리지 않는다).
    _shot: Snapshot | None = None

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = new_run_id()

    # ── 띄우기·거두기 ──

    def start(self) -> None:
        """스레드를 띄운다. **엔진을 여기서 시작하지 않는다** — 그 스레드가 한다.

        `run_started`까지 스레드 안에서 남기므로, 시작하다 터져도 그 사유가 **기록에** 남는다
        (Center가 받는 유일한 길이다 — C3).
        """
        self._thread = threading.Thread(target=self._body, name=f"run-{self.run_id}", daemon=True)
        self._thread.start()

    def stop(self, *, reason: str = "운영자가 중지했습니다") -> None:
        """중지를 **부탁한다** — 스레드가 다음 걸음에서 본다 (강제로 끊지 않는다)."""
        with self._lock:
            self._stopping = True
            self._stop_reason = reason

    def join(self, timeout_s: float | None = None) -> bool:
        if self._thread is None:
            return True
        self._thread.join(timeout_s)
        return not self._thread.is_alive()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 스레드가 도는 자리 ──

    def _body(self) -> None:
        found = RunLog(run_id=self.run_id, path=log_path(self.data_dir, self.run_id))
        try:
            run = self.engine.start(
                self.bot.entry(),
                run_id=self.run_id,
                log=found,
                env=self.env,
                inputs=self.inputs,
                mode=self.mode,
                executor="server_runner",
                source=self.source,
                version=self.bot.version,
                job_id=self.job_id,
                queued_s=self.queued_s,
            )
        except (EngineError, UnusablePackage, OSError, ValueError) as e:
            # 시작조차 못 했다 — **기록에 남겨야** Center가 안다 (C3). `run_started`는 없고
            # 사유를 로그 줄로 남긴 뒤 실패로 닫는다.
            #
            # **셈 칸을 빠뜨리면 그 줄이 거부된다** — C3가 `run_finished`에 요구하는 키가
            # 있고(`REQUIRED_DATA_KEYS`), 빠지면 Center가 그 줄만 버려서 「실패한 실행이
            # 끝나지 않은 것처럼」 남는다. 아무것도 돌지 않았으니 전부 0이다.
            self._failure = str(e)
            found.emit("log", level="error", message=f"실행을 시작하지 못했다: {e}")
            found.emit("run_finished", status="failed", duration_s=0.0, error_message=str(e), **EMPTY_COUNTS)
            log.error("실행 %s를 시작하지 못했다: %s", self.run_id, e)
            return

        with self._lock:
            self.run = run
        self._publish(run)
        self._drive(run)
        self._publish(run)

    def _drive(self, run: Run) -> None:
        """끝날 때까지 민다. **중지를 자주 본다** — 그래야 `cancelled`가 기록에 남는다."""
        while not run.finished:
            if self._take_stop(run):
                break
            if self.engine.blocked(run):
                if not self._tick(run):
                    # 사람·메시지를 기다린다 — 이 조각에서는 **이어 갈 길이 없다** (4-②).
                    # 스레드는 끝내고 자리를 놓는다 (`waiting[]`로 보고된다).
                    self._publish(run)
                    return
                continue
            for _ in range(STEPS_PER_TICK):
                if run.finished or self.engine.blocked(run):
                    break
                self.engine.step(run)
            # 한 묶음마다 찍는다 — 하트비트가 **지금 어느 노드인지**를 보려면 이것이 있어야 한다.
            self._publish(run)
        if run.state is State.FAILED and run.error is not None:
            self._failure = str(run.error)

    def _take_stop(self, run: Run) -> bool:
        with self._lock:
            if not self._stopping:
                return False
            reason = getattr(self, "_stop_reason", "중지했습니다")
        self.engine.cancel(run, reason=reason)
        return True

    def _tick(self, run: Run) -> bool:
        """시간이 된 타이머를 울린다. 민 것이 있으면 참.

        **잠들지 않는다** — 기다리는 것이 타이머뿐이어도 그 시각까지 스레드를 붙잡아 두면
        자리를 놓은 것이 아니다. 울릴 것이 없으면 거짓을 돌려주고 스레드를 끝낸다.
        """
        due = run.due(run.env.clock())
        if not due:
            return False
        self.engine.tick(run)
        return True

    # ── 바깥에서 묻는 것 ──

    def _publish(self, run: Run) -> None:
        """**도는 스레드가** 지금 모습을 찍어 둔다 — 묻는 쪽은 `Run`을 건드리지 않는다."""
        found = self._measure(run)
        with self._lock:
            self._shot = found

    def snapshot(self) -> Snapshot:
        """찍혀 있는 지금 모습. 아직 찍기 전이면 **시작 전**을 말한다."""
        with self._lock:
            found, failure = self._shot, self._failure
        if found is not None:
            # 실패 사유는 찍은 뒤에 정해질 수 있다 (끝낸 직후) — 있으면 얹어 준다.
            return found if found.failure or not failure else replace(found, failure=failure)
        return Snapshot(
            run_id=self.run_id,
            bpm_process_id=self.bot.id,
            version=self.bot.version,
            started_at=now_iso(),
            job_id=self.job_id,
            node_id=None,
            state=State.FAILED.value if failure else State.READY.value,
            finished="failed" if failure else None,
            failure=failure,
        )

    def _measure(self, run: Run) -> Snapshot:
        """`Run`을 읽어 모습 하나를 만든다. **도는 스레드에서만 부른다.**"""
        return Snapshot(
            run_id=self.run_id,
            bpm_process_id=run.process.id,
            version=run.version,
            started_at=run.started.isoformat(),
            job_id=self.job_id,
            node_id=self._node_id(run),
            state=run.state.value,
            waiting=self._waiting_row(run),
            finished=self._finished(run),
            failure=self._failure,
        )

    def _node_id(self, run: Run) -> str | None:
        """지금 밟고 있는 노드 (C12 `running[].node_id`). 토큰이 여럿이면 **첫 자리**다."""
        return run.tokens[0].node_id if run.tokens else None

    def _finished(self, run: Run) -> str | None:
        """끝났으면 C3 `run_finished.status`. **취소는 실패가 아니다** (C3)."""
        if not run.finished:
            return None
        if run.state is State.DONE:
            # 취소도 `DONE`으로 앉으므로 기록에서 읽는다 — `cancelled`와 `success`를 가른다.
            for event in reversed(run.log.events):
                if event.kind == "run_finished":
                    return str(event.data.get("status") or "success")
            return "success"
        return "failed"

    def _waiting_row(self, run: Run) -> WaitingRun | None:
        """기다리는 중이면 C12 `waiting[]` 한 줄. **짝이 되는 칸을 반드시 채운다**.

        결재는 `request_id`, 메시지는 `message_name`, 타이머는 `until`이다 — 비우면 Center가
        422로 거부한다 (`validate_heartbeat`).
        """
        if run.finished or not self.engine.blocked(run):
            return None
        common = {
            "run_id": self.run_id,
            "bpm_process_id": run.process.id,
            "version": run.version,
            "since": now_iso(),
        }
        pending = next(iter(run.pendings.values()), None)
        if pending is not None:
            return WaitingRun(
                **common, waiting_for=WAITING_APPROVAL, request_id=pending.request_id
            )
        for found in run.waits.values():
            if found.kind == WAIT_MESSAGE:
                return WaitingRun(
                    **common,
                    waiting_for=WAITING_MESSAGE,
                    message_name=found.name,
                    correlation=found.correlation,
                )
        due = run.next_due()
        if due is not None:
            return WaitingRun(**common, waiting_for=WAITING_TIMER, until=due.isoformat())
        # 멈췄는데 무엇을 기다리는지 모른다 — **거짓을 올리지 않는다** (자리를 쥔 것으로 둔다).
        log.warning("실행 %s가 멈췄는데 기다리는 것을 모른다", self.run_id)
        return None

    def ack_result(self) -> str | None:
        """끝난 실행의 작업 ack 결과 (C4). 아직 안 끝났으면 `None`.

        **실행의 성패는 작업 상태가 아니다** (C5) — Center는 이것을 `run_status`에만 적는다.
        """
        found = self.snapshot().finished
        if found is None:
            return None
        return {
            "success": ACK_FINISHED, "cancelled": ACK_CANCELLED, "failed": ACK_FAILED
        }.get(found, ACK_FAILED)


__all__ = [
    "ACK_CANCELLED",
    "EMPTY_COUNTS",
    "ACK_FAILED",
    "ACK_FINISHED",
    "ACK_STARTED",
    "STEPS_PER_TICK",
    "TICK_S",
    "WAITING_APPROVAL",
    "WAITING_MESSAGE",
    "WAITING_TIMER",
    "Snapshot",
    "Worker",
    "now_iso",
]

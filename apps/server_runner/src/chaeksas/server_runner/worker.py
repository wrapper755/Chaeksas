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

**멈추면 상태를 담고 스레드를 놓는다** (ADR-0054 §3) — 그러면 그 실행은 `waiting[]`로 보고되고
**자리를 쥐지 않는다**. 답(결재)·메시지·타이머가 오면 부르는 쪽이 `resume()`으로 되살려 다시
민다. 재시작을 넘기는 것도 같은 저장소다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.contracts.server_runner import RunningRun, WaitingRun
from chaeksas.core.engine import Engine, EngineError, Run, RunEnv, State
from chaeksas.core.packages import InstalledBot, UnusablePackage
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.core.run_shipping import read_sent
from chaeksas.core.run_snapshot import SnapshotMismatch, dump, restore
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


def reopen_log(run_id: str, path: Path) -> RunLog:
    """**파일이 원본이다** (C3) — 되살릴 때 jsonl을 다시 읽어 `seq`를 잇는다.

    보낸 자리도 파일에서 읽는다 (`runs/<run_id>.sent`) — 메모리의 `sent_through`는 다시 뜨면
    0이라, 읽지 않으면 보낸 줄을 또 보낸다.
    """
    found = RunLog(run_id=run_id, path=path)
    found.events = list(RunLog.read(path)) if path.exists() else []
    found.sent_through = read_sent(path)
    return found


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
    #: 멈출 때 상태를 담아 둘 곳 (ADR-0054 §3). 없으면 담지 않는다 (시험·한 번 돌리기).
    store: Any | None = None

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

    def resume(self, snapshot: dict[str, Any]) -> None:
        """담아 둔 것을 되살려 **다시 민다** (ADR-0054 §2).

        그림·기록·바깥 세계는 **밖에서 꽂는다** — 그림은 설치된 패키지에서 다시 읽고(`bot`),
        기록은 파일에서 줄과 보낸 자리를 함께 읽는다. 빈 기록으로 되살리면 `seq`가 1부터
        다시 시작해 C3 멱등이 겹치고 **Center가 이어 돈 줄을 버린다** (스파이크 장면 E).
        """
        self._thread = threading.Thread(
            target=self._resumed_body, args=(snapshot,), name=f"run-{self.run_id}", daemon=True
        )
        self._thread.start()

    def _resumed_body(self, snapshot: dict[str, Any]) -> None:
        try:
            run = restore(
                snapshot,
                process=self.bot.entry(),
                log=reopen_log(self.run_id, log_path(self.data_dir, self.run_id)),
                env=self.env,
            )
        except (SnapshotMismatch, EngineError, UnusablePackage, OSError, ValueError) as e:
            # 되살리지 못했다 — **그 실행을 실패로 닫는다** (사유는 기록에 남는다).
            self._failure = str(e)
            log.error("실행 %s를 되살리지 못했다: %s", self.run_id, e)
            found = reopen_log(self.run_id, log_path(self.data_dir, self.run_id))
            found.emit("log", level="error", message=f"되살리지 못했다: {e}")
            found.emit("run_finished", status="failed", duration_s=0.0, error_message=str(e), **EMPTY_COUNTS)
            if self.store is not None:
                self.store.forget(self.run_id)
            return

        with self._lock:
            self.run = run
        self._publish(run)
        self._drive(run)
        self._publish(run)
        self._settle(run)

    def answer(self, request_id: str, found: Mapping[str, Any], *, answered_by: str) -> None:
        """결재·확인의 답을 넣는다 (C6). **되살린 실행이 이 자리에서 이어 간다.**

        답을 넣고 **다시 민다** — 넣기만 하면 그 실행은 멈춘 채 남는다. 미는 것은 새 스레드다
        (`Run` 하나는 한 스레드만 만진다).
        """
        run = self.run
        if run is None:  # pragma: no cover - 부르는 쪽이 먼저 되살린다
            raise RuntimeError("되살리지 않은 실행에 답할 수 없다")
        self.engine.answer(run, request_id, found, answered_by=answered_by)
        self._continue(run)

    def deliver(self, name: str, *, correlation: Any = None, payload: Mapping[str, Any]) -> bool:
        """메시지를 넣는다 (C12 §메시지). **넣었으면 참** — 받을 곳이 없으면 거짓이다.

        받을 곳이 있는지 **먼저 묻는다** (`Engine.message_target`) — 엔진의 `deliver`는 받을 곳이
        없어도 조용히 넘어가므로, 그것만 부르면 실행기가 Center에 「받았다」고 거짓 ack를 보낸다.
        """
        run = self.run
        if run is None:  # pragma: no cover - 부르는 쪽이 먼저 되살린다
            return False
        if self.engine.message_target(run, name, correlation=correlation) is None:
            return False
        self.engine.deliver(run, name, correlation=correlation, payload=payload)
        self._continue(run)
        return True

    def waits_for_message(self, name: str, *, correlation: Any = None) -> bool:
        """그 메시지를 기다리고 있나 — **넣어 보지 않고** 묻는다 (빈자리를 먼저 세려고)."""
        run = self.run
        if run is None:
            return False
        return self.engine.message_target(run, name, correlation=correlation) is not None

    def withdraw(self, request_id: str, *, reason: str) -> None:
        """Center 결재가 **답 없이 끝났다** (회수·만료, C6·ADR-0038).

        답이 아니다 — 오류 경계가 받거나 실행이 실패한다 (`APPROVAL_WITHDRAWN`·`_EXPIRED`).
        """
        run = self.run
        if run is None:  # pragma: no cover
            raise RuntimeError("되살리지 않은 실행의 결재를 거둘 수 없다")
        self.engine.withdraw(run, request_id, reason=reason)
        self._continue(run)

    def _continue(self, run: Run) -> None:
        """멈춰 있던 실행을 **다시 민다** — 새 스레드가 이어서 돈다."""
        self._publish(run)
        self._thread = threading.Thread(
            target=self._continued_body, args=(run,), name=f"run-{self.run_id}", daemon=True
        )
        self._thread.start()

    def _continued_body(self, run: Run) -> None:
        self._drive(run)
        self._publish(run)
        self._settle(run)

    # ── 스레드가 도는 자리 ──

    def _body(self) -> None:
        found = reopen_log(self.run_id, log_path(self.data_dir, self.run_id))
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
        if self.store is not None:
            # **시작했다는 것부터 적는다** — 이것이 없으면 다시 뜬 실행기가 죽은 실행을 모른다.
            self.store.mark_running(
                self.run_id,
                # **패키지 id다** (C1 — Bot의 신원). 그림의 `process.id`가 아니다 — 되살릴 때
                # `find()`가, Center의 Bot별 상한이 이 이름으로 찾는다.
                bpm_process_id=self.bot.id,
                version=run.version,
                job_id=self.job_id,
                started_at=run.started.isoformat(),
            )
        self._drive(run)
        self._publish(run)
        self._settle(run)

    def _settle(self, run: Run) -> None:
        """스레드가 끝나며 저장소를 맞춘다 — 끝났으면 지우고, 멈췄으면 **담는다**."""
        if self.store is None:
            return
        if run.finished:
            self.store.forget(self.run_id)
            return
        size = self.store.save_waiting(self.run_id, dump(run))
        log.info("실행 %s를 담았다 (%d바이트) — 자리를 놓는다", self.run_id, size)

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
        """`Run`을 읽어 모습 하나를 만든다. **도는 스레드에서만 부른다.**

        `bpm_process_id`는 **패키지 id**다 (C1 — Bot의 신원). 그림의 `process.id`를 올리면
        배포·작업·Bot별 상한이 쓰는 이름과 갈라져 CON-12가 다른 이름을 보인다.
        """
        return Snapshot(
            run_id=self.run_id,
            bpm_process_id=self.bot.id,
            version=self.bot.version,
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
            # **패키지 id다** (`_measure`와 같다) — 그림의 `process.id`를 올리면 Center의 Bot별
            # 상한·메시지 찾기가 쓰는 이름과 갈라진다 (C1 — Bot의 신원은 패키지 id다).
            "bpm_process_id": self.bot.id,
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
    "reopen_log",
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

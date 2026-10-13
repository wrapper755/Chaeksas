"""s10 — 함께 쓰는 거리: 예제 읽기, 바깥 세계 꽂기, 밀어 보기.

실험 코드다 (`spikes/README.md`) — 제품 코드가 import하지 않는다.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from chaeksas.contracts.bpmn_ext import BpmnProcess, read_process
from chaeksas.core.engine import Engine, Run, RunEnv, State, Workspace, new_run_id
from chaeksas.core.run_log import RunLog
from chaeksas.core.senders import RecordingSender

ROOT = Path(__file__).resolve().parents[2]
BPMN = ROOT / "docs" / "08-business-examples" / "bpmn"

#: 실험에 쓰는 예제 — **실행 위치가 `server`**이고 결재를 기다리며 경계 타이머가 둘 붙어 있다.
EXAMPLE = "bx03_expense_approval.bpmn"

INPUTS: dict[str, Any] = {
    "신청번호": "EX-2609-014",
    "신청자": "김하나",
    "항목": "출장 숙박",
    "금액": 480000,
    "영수증": True,
    "회신주소": "http://127.0.0.1:1/spike",  # RecordingSender가 받으니 나가지 않는다
}


class Clock:
    """밀 수 있는 시계 — `RunEnv.clock`에 꽂는다 (엔진은 스레드를 만들지 않는다)."""

    def __init__(self, at: datetime | None = None) -> None:
        self.at = at or datetime(2026, 10, 13, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kw: float) -> datetime:
        self.at += timedelta(**kw)
        return self.at


def new_run_id_for(clock: Clock) -> str:
    """C3 모양의 `run_id` (`run_<날짜>_<시각>_<hex6>`)."""
    return new_run_id(now=clock())


def load(name: str = EXAMPLE) -> BpmnProcess:
    return read_process((BPMN / name).read_bytes())


def env(
    clock: Clock, sender: RecordingSender | None = None, output_dir: Path | None = None
) -> RunEnv:
    """바깥 세계 — **되살릴 때 이것을 통째로 다시 꽂는다** (저장소에 담을 수 없다).

    `output_dir`도 그중 하나다. 서버 실행기에서는 실행마다 폴더를 주므로, 되살릴 때
    **같은 폴더**를 다시 줘야 앞서 쓴 파일이 이어진다.
    """
    return RunEnv(
        sender=sender or RecordingSender(),
        clock=clock,
        workspace=Workspace(output_dir=output_dir) if output_dir else Workspace(),
    )


def start(
    process: BpmnProcess,
    *,
    run_id: str,
    clock: Clock,
    log: RunLog | None = None,
    sender: RecordingSender | None = None,
    engine: Engine | None = None,
    output_dir: Path | None = None,
) -> tuple[Engine, Run]:
    engine = engine or Engine()
    run = engine.start(
        process,
        run_id=run_id,
        log=log or RunLog(run_id=run_id),
        inputs=INPUTS,
        mode="deterministic",
        executor="server_runner",
        version="1.0.0",
        now=clock(),
        env=env(clock, sender, output_dir),
    )
    engine.run_until_blocked(run)
    return engine, run


def describe(run: Run) -> str:
    waits = ", ".join(sorted(run.waits)) or "없음"
    pendings = ", ".join(sorted(run.pendings)) or "없음"
    tokens = ", ".join(f"{t.id}@{t.node_id}{'(대기)' if t.waiting else ''}" for t in run.tokens)
    return f"{run.state.value} | 토큰 [{tokens}] | 기다림 [{waits}] | 사람 [{pendings}]"


def answerable(run: Run) -> str:
    """지금 답할 수 있는 결재 `request_id` 하나."""
    return next(iter(run.pendings))


def outcome(run: Run) -> dict[str, Any]:
    """비교할 거리 — 결과 변수와 상태. 업무 값까지 본다 (실험이라 볼 수 있다)."""
    return {
        "state": run.state.value,
        "결과": run.variables.get("결과"),
        # `run_id`·`지금`·`오늘`은 실행마다 다르다 — 견주는 거리에서 뺀다.
        "변수": {
            k: v for k, v in sorted(run.variables.items())
            if k not in ("지금", "오늘", "run_id", "회신결과", "리마인드발송", "실행기록")
        },
        "노드": [e.node_id for e in run.log.events if e.kind == "node_state"],
    }


__all__ = [
    "BPMN",
    "EXAMPLE",
    "INPUTS",
    "Clock",
    "Engine",
    "Run",
    "RunLog",
    "State",
    "answerable",
    "describe",
    "env",
    "load",
    "new_run_id_for",
    "outcome",
    "start",
]

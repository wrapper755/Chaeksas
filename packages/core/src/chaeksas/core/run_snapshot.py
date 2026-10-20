"""기다리는 실행을 **글로 담고 되살린다** (ADR-0054 §1~§2).

서버 실행기가 결재·메시지·타이머를 기다리는 실행의 상태를 자기 저장소에 둔다 (C12 §재시작과
유실). 담는 길은 **`core`에 둔다** — `Run`을 아는 것은 엔진 쪽이고, 그 칸이 늘면 담는 길도
같이 고쳐야 한다 (아래 시험이 그것을 묻는다).

`Run`의 칸을 **셋으로 가른다** (스파이크 `spikes/s10-server-runner-state/`가 하나하나 확인했다).

| 갈래 | 뜻 | 무엇 |
| --- | --- | --- |
| 담는다 | 저장소에 글로 간다 | 변수·토큰·기다림·사람 요청·합류 도착·안쪽 실행·배운 것 |
| 다시 꽂는다 | 담을 수 없어 되살릴 때 밖에서 준다 | `process`·`log`·`env`·`helpers` |
| 버린다 | 되살린 실행에 뜻이 없다 | `error` (실패한 실행은 되살리지 않는다) |

**모양을 바꾸는 것이 셋**이고 되살릴 때 **파이썬 타입으로 되돌린다**.

| 칸 | 담을 때 | 안 되돌리면 |
| --- | --- | --- |
| `waits[].due_at` | 시각 → ISO 글 | 타이머가 안 울린다 |
| `arrivals`의 값 | **집합** → 목록 | 합류가 **도착한 토큰을 두 번 센다** |
| `pendings[].form` | 계약 모델 → `model_dump` | 답 검증이 폼을 못 읽는다 |

**날짜 도우미는 실행 시작 시각에 묶는다** (`bind(now=run.started)`) — 「지금」으로 묶으면
`오늘()`·`지난달()`이 다른 답을 낸다.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from chaeksas.contracts.approvals import Form
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.contracts.replay import ReplaySpec
from chaeksas.core.helpers import bind
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_state import LoopState, Pending, Run, RunEnv, State, Token, Waiting

#: 저장소에 글로 가는 칸.
STORED = (
    "variables", "state", "tokens", "last_token_id", "pendings", "arrivals", "expected",
    "waits", "children", "nested", "mode", "executor", "version", "bpm_process_id", "started",
    "instances", "call_seqs", "learned",
)
#: 되살릴 때 **밖에서 다시 꽂는** 칸.
REPLUGGED = ("process", "log", "env", "helpers")
#: 되살린 실행에 뜻이 없어 버리는 칸.
DROPPED = ("error",)


class SnapshotMismatch(RuntimeError):
    """담아 둔 것과 지금 그림이 다르다 — **되살리지 않는다** (없는 노드를 밟는다)."""


def audit_fields() -> list[str]:
    """`Run`의 칸이 셋 중 하나에 다 들어갔나 — **칸이 늘면 여기서 드러난다**.

    시험이 이것을 부른다 (`tests/test_core_run_snapshot.py`). 엔진에 칸을 더하고 여기 적지
    않으면 되살린 실행이 **다른 답을 낸다** — 조용히 빠지는 것을 막는 그물이다.
    """
    known = {"run_id", *STORED, *REPLUGGED, *DROPPED}
    actual = {f.name for f in dataclasses.fields(Run)}
    problems = []
    for missing in sorted(actual - known):
        problems.append(f"갈래가 없는 칸: {missing}")
    for stale in sorted(known - actual - {"run_id"}):
        problems.append(f"`Run`에 없는 칸: {stale}")
    return problems


# ─────────────────────────── 담기 ───────────────────────────


def dump_token(token: Token) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": token.id, "node_id": token.node_id, "scope": list(token.scope),
        "waiting_for": token.waiting_for,
    }
    if token.loop is not None:
        out["loop"] = dataclasses.asdict(token.loop)
    return out


def load_token(data: dict[str, Any]) -> Token:
    loop = data.get("loop")
    return Token(
        id=data["id"], node_id=data["node_id"], scope=tuple(data["scope"]),
        waiting_for=data["waiting_for"], loop=LoopState(**loop) if loop else None,
    )


def dump_wait(w: Waiting) -> dict[str, Any]:
    out = dataclasses.asdict(w)
    out["due_at"] = w.due_at.isoformat() if w.due_at else None
    return out


def load_wait(data: dict[str, Any]) -> Waiting:
    at = data.pop("due_at")
    return Waiting(due_at=datetime.fromisoformat(at) if at else None, **data)


def dump_pending(p: Pending) -> dict[str, Any]:
    out = dataclasses.asdict(p)
    out["form"] = p.form.model_dump(mode="json") if p.form else None
    return out


def load_pending(data: dict[str, Any]) -> Pending:
    form = data.pop("form")
    return Pending(form=Form.model_validate(form) if form else None, **data)


def dump(run: Run) -> dict[str, Any]:
    """`Run` 하나를 글로. **자식 실행도 함께** (호출이 띄운 안쪽 실행, 같은 `run_id`)."""
    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "variables": run.variables,
        "tokens": [dump_token(t) for t in run.tokens],
        "last_token_id": run.last_token_id,
        "pendings": {k: dump_pending(v) for k, v in run.pendings.items()},
        "arrivals": {k: sorted(v) for k, v in run.arrivals.items()},  # set → 목록
        "expected": dict(run.expected),
        "waits": {k: dump_wait(v) for k, v in run.waits.items()},
        "children": {k: dump(v) for k, v in run.children.items()},
        "nested": run.nested,
        "mode": run.mode,
        "executor": run.executor,
        "version": run.version,
        "bpm_process_id": run.bpm_process_id,
        "started": run.started.isoformat(),
        "instances": dict(run.instances),
        "call_seqs": dict(run.call_seqs),
        "learned": [s.model_dump(mode="json") for s in run.learned],
        # 되살릴 때 **그 그림이 맞나** 보는 거리 (판이 다른 패키지로 이어 가지 않는다).
        "process_id": run.process.id,
    }


def restore(data: dict[str, Any], *, process: BpmnProcess, log: RunLog, env: RunEnv) -> Run:
    """글에서 `Run`을 되살린다 — 그림·기록·바깥 세계는 **밖에서 꽂는다**.

    그림이 다르면 `SnapshotMismatch`다. **판이 맞나는 부르는 쪽이 먼저 본다**
    (`contracts.server_runner.restorable`) — 여기서는 마지막 그물로 그림 id만 본다.
    """
    if data["process_id"] != process.id:
        raise SnapshotMismatch(f"그림이 다르다: 저장된 {data['process_id']} ≠ 준 {process.id}")
    started = datetime.fromisoformat(data["started"])
    run = Run(
        run_id=data["run_id"],
        process=process,
        log=log,
        env=env,
        variables=dict(data["variables"]),
        state=State(data["state"]),
        tokens=[load_token(t) for t in data["tokens"]],
        last_token_id=data["last_token_id"],
        pendings={k: load_pending(dict(v)) for k, v in data["pendings"].items()},
        arrivals={k: set(v) for k, v in data["arrivals"].items()},
        expected=dict(data["expected"]),
        waits={k: load_wait(dict(v)) for k, v in data["waits"].items()},
        children={
            k: restore(v, process=process, log=log, env=env) for k, v in data["children"].items()
        },
        nested=data["nested"],
        mode=data["mode"],
        executor=data["executor"],
        version=data["version"],
        # ADR-0086 전에 담은 스냅샷에는 없다 — 그러면 그림 id로 말한다(`Run.identity`).
        bpm_process_id=str(data.get("bpm_process_id") or ""),
        started=started,
        instances=dict(data["instances"]),
        call_seqs=dict(data["call_seqs"]),
        learned=[ReplaySpec.model_validate(s) for s in data["learned"]],
        # **날짜 도우미는 실행 시작 시각에 묶인다** — 되살릴 때 「지금」으로 묶으면
        # `오늘()`·`지난달()`이 다른 답을 낸다 (`core.helpers.bind`).
        helpers=bind(now=started),
    )
    return run


__all__ = [
    "DROPPED",
    "REPLUGGED",
    "STORED",
    "SnapshotMismatch",
    "audit_fields",
    "dump",
    "dump_pending",
    "dump_token",
    "dump_wait",
    "load_pending",
    "load_token",
    "load_wait",
    "restore",
]

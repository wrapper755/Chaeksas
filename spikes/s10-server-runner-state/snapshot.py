"""s10 ① — `Run`을 저장하고 되살릴 수 있는가.

**무엇이 담겨야 하고 무엇을 담을 수 없는가**를 코드로 확인한다. `Run`의 칸을 하나하나
세 갈래로 가른다.

| 갈래 | 뜻 | 보기 |
| --- | --- | --- |
| 담는다 | 저장소에 글로 간다 | `variables`·`tokens`·`waits`·`pendings`·`arrivals`·`children` |
| 다시 꽂는다 | 저장할 수 없어 되살릴 때 밖에서 준다 | `process`·`log`·`env`·`helpers` |
| 버린다 | 되살린 실행에 뜻이 없다 | `error` (실패한 실행은 되살리지 않는다) |

`python snapshot.py`로 돌린다.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import Any

from chaeksas.contracts.approvals import Form
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.contracts.replay import ReplaySpec
from chaeksas.core.engine import Run, RunEnv, State
from chaeksas.core.helpers import bind
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_state import LoopState, Pending, Token, Waiting
from common import Clock, answerable, describe, load, new_run_id_for, start

#: 저장소에 글로 가는 칸.
STORED = (
    "variables", "state", "tokens", "last_token_id", "pendings", "arrivals", "expected",
    "waits", "children", "nested", "mode", "executor", "version", "started",
    "instances", "call_seqs", "learned",
)
#: 되살릴 때 **밖에서 다시 꽂는** 칸.
REPLUGGED = ("process", "log", "env", "helpers")
#: 되살린 실행에 뜻이 없어 버리는 칸.
DROPPED = ("error",)


def audit_fields() -> list[str]:
    """`Run`의 칸이 셋 중 하나에 다 들어갔나 — **칸이 늘면 여기서 드러난다**."""
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
        "started": run.started.isoformat(),
        "instances": dict(run.instances),
        "call_seqs": dict(run.call_seqs),
        "learned": [s.model_dump(mode="json") for s in run.learned],
        # 되살릴 때 **그 그림이 맞나** 보는 거리 (판이 다른 패키지로 이어 가지 않는다).
        "process_id": run.process.id,
    }


def restore(data: dict[str, Any], *, process: BpmnProcess, log: RunLog, env: RunEnv) -> Run:
    """글에서 `Run`을 되살린다 — 그림·기록·바깥 세계는 **밖에서 꽂는다**."""
    if data["process_id"] != process.id:
        raise ValueError(f"그림이 다르다: 저장된 {data['process_id']} ≠ 준 {process.id}")
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
        started=started,
        instances=dict(data["instances"]),
        call_seqs=dict(data["call_seqs"]),
        learned=[ReplaySpec.model_validate(s) for s in data["learned"]],
        # **날짜 도우미는 실행 시작 시각에 묶인다** — 되살릴 때 「지금」으로 묶으면
        # `오늘()`·`지난달()`이 다른 답을 낸다 (`core.helpers.bind`).
        helpers=bind(now=started),
    )
    return run


def main() -> None:
    print("① `Run`의 칸이 셋 중 하나에 다 들어갔나")
    problems = audit_fields()
    print("  " + ("\n  ".join(problems) if problems else "모두 갈래가 있다"))

    clock = Clock()
    engine, run = start(load(), run_id=new_run_id_for(clock), clock=clock)
    print(f"\n② 결재 앞에서 멈췄다: {describe(run)}")

    data = dump(run)
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    print(f"\n③ 글로 담았다: {len(text)}바이트, 최상위 칸 {len(data)}개")
    print(f"   담긴 기다림: {sorted(data['waits'])}")
    print(f"   담긴 사람 요청: {sorted(data['pendings'])}")
    print(f"   타이머 시각: {[w['due_at'] for w in data['waits'].values()]}")

    back = restore(
        json.loads(text), process=run.process, log=RunLog(run_id=run.run_id), env=run.env
    )
    print(f"\n④ 되살렸다: {describe(back)}")
    same = dump(back) == data
    print(f"   담은 것 ↔ 되살려 다시 담은 것: {'같다' if same else '다르다'}")
    print(f"   도우미: {len(back.helpers)}개 (`bind(now=started)`로 다시 꽂았다)")
    print(f"   기록: 되살린 `RunLog`의 줄 수 {len(back.log.events)} (파일이 원본이다 — C3)")

    print("\n⑤ 담을 수 없는 것")
    for name in REPLUGGED:
        value = getattr(run, name)
        print(f"   {name}: {type(value).__name__} — 다시 꽂는다")
    print(f"   error: {type(run.error).__name__} (예외 객체) — 실패한 실행은 되살리지 않는다")
    print(f"   {answerable(run)} 가 답을 기다린다")


if __name__ == "__main__":
    main()

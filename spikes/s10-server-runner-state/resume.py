"""s10 ② — 되살린 실행이 같은 답을 내는가.

같은 예제(BX-03, 실행 위치 `server`)를 세 번 돌려 **끝 값을 견준다**.

| | 무엇 |
| --- | --- |
| A | 쭉 돈다 — 결재 앞에서 멈췄다가 바로 답한다 |
| B | 결재 앞에서 **상태를 저장하고 모든 객체를 버린다**. 새 엔진·새로 읽은 그림·새 기록으로 되살려 답한다 |
| C | B처럼 되살린 뒤 **시계를 밀어** 경계 타이머를 울린다 (리마인드 P3D → 마감 P7D) |
| D | **실행기가 꺼져 있는 동안** 기한이 지났다 — 되살려 한 번 `tick()`한다 |

저장소는 C12가 적은 대로 **SQLite 한 파일**이다. `python resume.py`로 돌린다.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from chaeksas.core.engine import Engine, Run, State
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_shipping import read_sent
from chaeksas.core.senders import RecordingSender
from common import Clock, answerable, describe, env, load, new_run_id_for, outcome, start
from snapshot import dump, restore

ANSWER = {"승인여부": True, "결재의견": "출장 숙박 승인합니다"}

#: `run_finished`에서 견주는 셈 (C3 — Center는 줄을 다시 읽어 세지 않는다).
COUNTED = ("nodes", "ai_tasks", "service_calls", "human_requests", "confirmations")


def finish_counts(run: Run) -> dict[str, Any]:
    finished = next((e for e in run.log.events if e.kind == "run_finished"), None)
    return {k: v for k, v in (finished.data if finished else {}).items() if k in COUNTED}


# ─────────────────────────── 저장소 (SQLite 한 파일) ───────────────────────────


class Store:
    """기다리는 실행을 담아 두는 곳. C12 §재시작과 유실의 「SQLite로 시작」."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runs ("
            " run_id TEXT PRIMARY KEY, bpm_process_id TEXT NOT NULL, version TEXT NOT NULL,"
            " state TEXT NOT NULL, snapshot TEXT NOT NULL, saved_at TEXT NOT NULL)"
        )

    def save(self, run: Run, *, at: str) -> int:
        body = json.dumps(dump(run), ensure_ascii=False, sort_keys=True)
        self.db.execute(
            "INSERT INTO runs (run_id, bpm_process_id, version, state, snapshot, saved_at)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET"
            " state=excluded.state, snapshot=excluded.snapshot, saved_at=excluded.saved_at",
            (run.run_id, run.process.id, run.version, run.state.value, body, at),
        )
        self.db.commit()
        return len(body)

    def waiting(self) -> list[tuple[str, dict[str, Any]]]:
        """되살릴 것 — **기다리는 것만**. 끝난·실패한 실행은 되살리지 않는다."""
        rows = self.db.execute(
            "SELECT run_id, snapshot FROM runs WHERE state = ? ORDER BY saved_at", ("waiting",)
        ).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def forget(self, run_id: str) -> None:
        self.db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        self.db.commit()


def reopen_log(run_id: str, path: Path) -> RunLog:
    """**파일이 원본이다** (C3) — 되살릴 때 jsonl을 다시 읽어 `seq`를 이어 간다.

    빈 `RunLog`로 되살리면 `seq`가 1부터 다시 시작해 `(run_id, seq)`가 겹친다 — Center는
    멱등이라 **새 줄을 지나간 것으로 보고 버린다** (scene E가 그것을 보인다).

    **보낸 자리도 파일에서 읽는다** (`runs/<run_id>.sent`, `core.run_shipping.read_sent`) —
    메모리의 `sent_through`는 다시 뜨면 0이라, 읽지 않으면 보낸 줄을 또 보낸다.
    """
    log = RunLog(run_id=run_id, path=path)
    log.events = list(RunLog.read(path)) if path.exists() else []
    log.sent_through = read_sent(path)
    return log


def resume(run_id: str, data: dict[str, Any], *, clock: Clock, runs: Path, out: Path) -> Run:
    """**실행기가 다시 떴다** — 그림·기록·바깥 세계를 새로 꽂아 되살린다."""
    return restore(
        data,
        process=load(),  # 설치된 패키지에서 **다시 읽는다** (그림은 저장소에 담지 않는다)
        log=reopen_log(run_id, runs / f"{run_id}.jsonl"),
        env=env(clock, RecordingSender(), out),
    )


# ─────────────────────────── 장면 ───────────────────────────


def scene_a(runs: Path, out: Path) -> dict[str, Any]:
    clock = Clock()
    run_id = new_run_id_for(clock)
    engine, run = start(
        load(), run_id=run_id, clock=clock, log=RunLog(run_id=run_id, path=runs / f"{run_id}.jsonl"), output_dir=out
    )
    engine.answer(run, answerable(run), ANSWER, answered_by="박결재")
    engine.run_until_blocked(run)
    return outcome(run)


def scene_b(
    runs: Path, out: Path, store: Store
) -> tuple[dict[str, Any], int, int, int, dict[str, Any]]:
    clock = Clock()
    run_id = new_run_id_for(clock)
    engine, run = start(
        load(), run_id=run_id, clock=clock, log=RunLog(run_id=run_id, path=runs / f"{run_id}.jsonl"), output_dir=out
    )
    size = store.save(run, at=clock().isoformat())
    before = run.log.seq
    del engine, run  # **일꾼을 놓았다** — 메모리에 아무것도 남지 않는다

    engine = Engine()  # 다시 뜬 실행기
    run_id2, data = store.waiting()[0]
    back = resume(run_id2, data, clock=clock, runs=runs, out=out)
    engine.answer(back, answerable(back), ANSWER, answered_by="박결재")
    engine.run_until_blocked(back)
    store.forget(run_id2)
    return outcome(back), size, before, back.log.seq, finish_counts(back)


def scene_c(runs: Path, out: Path, store: Store) -> dict[str, Any]:
    clock = Clock()
    run_id = new_run_id_for(clock)
    engine, run = start(
        load(), run_id=run_id, clock=clock, log=RunLog(run_id=run_id, path=runs / f"{run_id}.jsonl"), output_dir=out
    )
    store.save(run, at=clock().isoformat())
    del engine, run

    engine = Engine()
    back = resume(run_id, store.waiting()[-1][1], clock=clock, runs=runs, out=out)
    sender: RecordingSender = back.env.sender  # type: ignore[assignment]

    clock.advance(days=4)  # 리마인드 기한(P3D)을 지났다 — 비중단 경계
    engine.tick(back)
    print(f"   P3D 뒤: {describe(back)}")
    print(f"   리마인드 웹훅: {len(sender.webhooks)}건")

    clock.advance(days=4)  # 마감 기한(P7D)을 지났다 — 중단 경계
    engine.tick(back)
    store.forget(run_id)
    return outcome(back)


def scene_d(runs: Path, out: Path, store: Store) -> dict[str, Any]:
    clock = Clock()
    run_id = new_run_id_for(clock)
    engine, run = start(
        load(), run_id=run_id, clock=clock, log=RunLog(run_id=run_id, path=runs / f"{run_id}.jsonl"), output_dir=out
    )
    store.save(run, at=clock().isoformat())
    del engine, run

    clock.advance(days=10)  # 실행기가 열흘 꺼져 있었다 — 그 사이 두 기한이 다 지났다
    engine = Engine()
    back = resume(run_id, store.waiting()[-1][1], clock=clock, runs=runs, out=out)
    print(f"   되살린 직후: {describe(back)}")
    engine.tick(back)  # 한 번에 둘 다 울린다
    store.forget(run_id)
    return outcome(back)


def scene_e(runs: Path, out: Path, store: Store) -> dict[str, Any]:
    """**빈 `RunLog`로 되살리면** 무엇이 깨지나 — 틀린 길을 한 번 밟아 본다."""
    clock = Clock()
    run_id = new_run_id_for(clock)
    engine, run = start(
        load(), run_id=run_id, clock=clock,
        log=RunLog(run_id=run_id, path=runs / f"{run_id}.jsonl"), output_dir=out,
    )
    store.save(run, at=clock().isoformat())
    del engine, run

    engine = Engine()
    back = restore(
        store.waiting()[-1][1],
        process=load(),
        log=RunLog(run_id=run_id, path=runs / f"{run_id}.jsonl"),  # 파일을 **읽지 않았다**
        env=env(clock, RecordingSender(), out),
    )
    engine.answer(back, answerable(back), ANSWER, answered_by="박결재")
    engine.run_until_blocked(back)
    store.forget(run_id)
    seqs = [e.seq for e in RunLog.read(runs / f"{run_id}.jsonl")]
    return {
        "첫 줄의 seq": back.log.events[0].seq,
        "겹친 seq": sorted({s for s in seqs if seqs.count(s) > 1}),
        "run_finished의 셈": finish_counts(back),
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs = root / "runs"
        out = root / "out"
        out.mkdir()
        store = Store(root / "state.sqlite3")

        print("A 쭉 돈다")
        a = scene_a(runs, out)
        print(f"   결과={a['결과']} state={a['state']}")

        print("\nB 저장하고 모두 버린 뒤 되살려 답한다")
        b, size, before, after, counts = scene_b(runs, out, store)
        print(f"   결과={b['결과']} state={b['state']}")
        print(f"   스냅샷 {size}바이트 | 기록 줄 수 저장 때 {before} → 끝 {after}")
        print(f"   run_finished의 셈: {counts}")

        print(f"\nA ↔ B: {'같다' if a == b else '다르다'}")
        if a != b:
            for key in sorted(set(a) | set(b)):
                if a.get(key) != b.get(key):
                    print(f"   {key}: A={a.get(key)!r} B={b.get(key)!r}")

        print("\nC 되살린 뒤 시계를 밀어 경계 타이머를 울린다")
        c = scene_c(runs, out, store)
        print(f"   결과={c['결과']} state={c['state']}")

        print("\nD 실행기가 꺼져 있는 동안 두 기한이 지났다")
        d = scene_d(runs, out, store)
        print(f"   결과={d['결과']} state={d['state']}")

        print("\nE 틀린 길 — 빈 `RunLog`로 되살린다 (파일을 다시 읽지 않는다)")
        for key, value in scene_e(runs, out, store).items():
            print(f"   {key}: {value}")

        print(f"\n저장소에 남은 기다리는 실행: {len(store.waiting())}건")
        assert a["state"] == State.DONE.value
        assert a == b, "되살린 실행이 다른 답을 냈다"


if __name__ == "__main__":
    main()

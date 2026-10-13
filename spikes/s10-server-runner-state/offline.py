"""s10 ④ — Center가 꺼져 있으면 실행기는 무엇을 들고 버티나 (ADR-0007).

**부르는 쪽이 다시 온다** — Center는 실행기를 부르지 않는다. 그래서 Center가 꺼져 있는 동안
실행기가 쥐고 있어야 하는 것이 무엇인지, 그리고 **무엇이 그사이에 저절로 일어나는지**를 본다.

| 물음 | 어디서 |
| --- | --- |
| 기다리는 실행이 남아 있나 | 저장소 (SQLite) — Center를 보지 않는다 |
| 실행 기록이 쌓이나 | `runs/<run_id>.jsonl` — 파일이 원본이다 (C3) |
| 올리지 못한 결재 요청이 쌓이나 | `runs/<run_id>.requests.jsonl` (ADR-0038) |
| **기한은 그사이에도 가나** | 간다 — 경계 타이머는 **로컬 시계**로 잰다 |

마지막 줄이 이 실험의 값이다. `python offline.py`로 돌린다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from chaeksas.core.engine import Engine
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_shipping import write_sent
from chaeksas.core.senders import RecordingSender
from common import Clock, answerable, describe, env, load, new_run_id_for, outcome, start
from resume import Store, reopen_log
from snapshot import dump, restore


class Center:
    """꺼졌다 켜지는 Center. 켜져 있을 때만 줄을 받고 결재를 내려 준다."""

    def __init__(self) -> None:
        self.up = True
        self.received: list[dict[str, Any]] = []
        self.answers: dict[str, dict[str, Any]] = {}

    def ship(self, log: RunLog) -> bool:
        """하트비트 뒤에 묶어 보낸다 (실행 중에 보내지 않는다 — C3)."""
        if not self.up:
            return False
        batch = log.unsent()
        if not batch:
            return True
        self.received.extend(e.to_json_dict() for e in batch)
        log.mark_sent(batch[-1].seq)
        # **보낸 자리를 파일에 적는다** (`core.run_shipping.write_sent`) — 다시 뜰 때 읽는다.
        if log.path is not None:
            write_sent(log.path, batch[-1].seq)
        return True


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs, out = root / "runs", root / "out"
        out.mkdir()
        store = Store(root / "state.sqlite3")
        center = Center()
        clock = Clock()

        run_id = new_run_id_for(clock)
        path = runs / f"{run_id}.jsonl"
        engine, run = start(
            load(), run_id=run_id, clock=clock,
            log=RunLog(run_id=run_id, path=path), output_dir=out,
        )
        request_id = answerable(run)
        store.save(run, at=clock().isoformat())
        center.ship(run.log)
        print(f"① Center가 켜져 있다 — 올린 줄 {len(center.received)}개, 올리지 못한 줄 {run.log.unsent_count}개")
        print(f"   결재 요청 {request_id} 를 Center에 올렸다 (location: center)")

        center.up = False
        del engine, run
        print("\n② Center가 꺼졌다. 실행기도 다시 떴다 (둘이 함께 났다)")

        engine = Engine()
        back = restore(
            store.waiting()[-1][1], process=load(), log=reopen_log(run_id, path),
            env=env(clock, RecordingSender(), out),
        )
        print(f"   저장소에서 되살렸다: {describe(back)}")
        print(f"   Center에 알릴 `restored[]`: ['{run_id}'] — 다음 하트비트까지 **들고 있는다**")
        print(f"   올리지 못한 줄: {back.log.unsent_count}개 (`unsent_events`)")
        print(f"   보내 보기: {'성공' if center.ship(back.log) else '실패 — 그대로 둔다'}")

        clock.advance(days=4)
        engine.tick(back)
        print(f"\n③ Center는 여태 꺼져 있다. 나흘 지났다 (리마인드 기한 P3D)")
        print(f"   {describe(back)}")
        print(f"   → 경계 타이머는 **로컬 시계**로 울렸다. Center가 없어도 간다")

        clock.advance(days=4)
        engine.tick(back)
        print(f"\n④ 여드레째 (마감 기한 P7D). Center는 아직 꺼져 있다")
        result = outcome(back)
        print(f"   {describe(back)}")
        print(f"   결과={result['결과']}")
        print(f"   → **결재가 Center에서 답을 기다리는 동안 실행기가 혼자 기한초과로 닫았다**")

        center.up = True
        center.ship(back.log)
        print(f"\n⑤ Center가 돌아왔다 — 밀린 줄 {len(center.received)}개를 올렸다")
        print(f"   올리지 못한 줄: {back.log.unsent_count}개")
        kinds = [e["kind"] for e in center.received]
        print(f"   올린 줄의 종류: {json.dumps(kinds, ensure_ascii=False)}")
        print("   → Center의 결재함에는 그 결재가 아직 `open`으로 남아 있다 (C6)")
        print("     답해도 갈 곳이 없다 — `run_ended`로 회수되어야 한다")

        store.forget(run_id)
        print(f"\n저장소에 남은 기다리는 실행: {len(store.waiting())}건 (끝난 것은 지운다)")
        assert dump(back)["state"] == "done"


if __name__ == "__main__":
    main()

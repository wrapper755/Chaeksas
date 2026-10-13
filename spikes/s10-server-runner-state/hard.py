"""s10 ⑥ — 쓸기가 닿지 않은 칸을 **손으로 세워** 담고 되살린다.

`sweep.py`가 예제 42개에서 「비어 있지 않은 것을 못 본」 칸 넷이 있다 — 반복(`tokens[].loop`)·
합류 도착(`arrivals`, 값이 **집합**이다)·안쪽 실행(`children`, **재귀**다)·배운 것(`learned`,
계약 모델이다). 담는 길이 서는지 증명하지 못한 자리이므로 여기서 세워 본다.

`python hard.py`로 돌린다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from chaeksas.contracts.replay import ReplaySpec, ReplayStep
from chaeksas.core.engine import Engine, Run, State
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_state import LoopState, Token
from common import Clock, env, load, new_run_id_for, start
from snapshot import dump, restore


def rig(run: Run, clock: Clock) -> Run:
    """기다리는 실행에 **네 칸을 손으로 채운다** (엔진이 만드는 것과 같은 모양)."""
    token = run.tokens[0]
    token.loop = LoopState(
        items=[{"거래처": "가나상사", "금액": 1_200_000}, {"거래처": "다라물산", "금액": 98_000}],
        item_name="청구건",
        result_name="처리결과",
        collect_into="처리결과목록",
        index=1,
        results=[{"ok": True, "번호": "INV-1"}],
        sequential=True,
    )
    # 합류 도착 — **값이 집합이다** (JSON에 집합은 없다).
    run.arrivals = {":Gw_Join": {"t_aaa111", "t_bbb222"}, "Sub_Review:Gw_Inner": {"t_ccc333"}}
    run.expected = {":Gw_Join": 2}
    # 안쪽 실행 — 호출(`callActivity`)이 띄운 것. **같은 `run_id`를 쓰고** 재귀로 담긴다.
    inner_log = RunLog(run_id=run.run_id)
    inner = Engine().start(
        load(), run_id=run.run_id, log=inner_log,
        inputs={
            "신청번호": "EX-2609-099", "신청자": "이둘", "항목": "회식",
            "금액": 70_000, "영수증": True, "회신주소": "http://127.0.0.1:1/inner",
        },
        mode="deterministic", executor="server_runner", version="1.0.0",
        now=clock(), env=run.env, nested=True,
    )
    inner.tokens.append(Token(id="t_inner2", node_id="Task_Result", scope=("Sub_Review",)))
    run.children = {"sub:Call_Inner": inner}
    run.tokens.append(Token(id="t_host", node_id="Approve_Expense", waiting_for="sub:Call_Inner"))
    # 배운 것 (ADR-0028) — 계약 모델이다.
    run.learned = [
        ReplaySpec(
            bpm_process_id=run.process.id, node_id="Task_Parse", version="1.0.0",
            steps=[ReplayStep(tool="pdf_text_tool", args={"path": "{청구서}"})],
            answer='{"금액": 1200000}', model="stub",
        )
    ]
    return run


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        clock = Clock()
        engine, run = start(load(), run_id=new_run_id_for(clock), clock=clock, output_dir=out)
        rig(run, clock)

        first = dump(run)
        text = json.dumps(first, ensure_ascii=False, sort_keys=True)
        back = restore(
            json.loads(text), process=run.process, log=RunLog(run_id=run.run_id), env=run.env
        )
        again = dump(back)

        print("⑥ 쓸기가 닿지 않은 칸 넷을 세워 담고 되살린다\n")
        rows: list[tuple[str, Any, Any]] = [
            ("tokens[].loop", first["tokens"][0].get("loop"), again["tokens"][0].get("loop")),
            ("arrivals (집합 → 목록)", first["arrivals"], again["arrivals"]),
            ("expected", first["expected"], again["expected"]),
            ("children (재귀)", sorted(first["children"]), sorted(again["children"])),
            ("learned", first["learned"], again["learned"]),
        ]
        for name, a, b in rows:
            print(f"  {'o' if a == b else 'X'} {name}")
        print(f"\n  글 길이: {len(text)}바이트")

        # 되살린 쪽의 **파이썬 타입**도 본다 — 목록으로 돌아오면 합류가 틀린 수를 센다.
        print(f"  arrivals 값의 타입: {type(next(iter(back.arrivals.values()))).__name__}")
        print(f"  children 값의 타입: {type(next(iter(back.children.values()))).__name__}")
        print(f"  children의 토큰: {[t.id for t in next(iter(back.children.values())).tokens]}")
        print(f"  children의 run_id: 바깥과 {'같다' if next(iter(back.children.values())).run_id == back.run_id else '다르다'}")
        print(f"  learned[0]: {type(back.learned[0]).__name__} {back.learned[0].key}")
        print(f"  loop.results: {back.tokens[0].loop.results if back.tokens[0].loop else None}")

        assert again == first, "담은 것과 되살려 다시 담은 것이 다르다"
        assert isinstance(next(iter(back.arrivals.values())), set), "arrivals가 집합으로 안 돌아왔다"
        assert back.children["sub:Call_Inner"].nested is True, "안쪽 실행의 `nested`가 빠졌다"
        assert back.state is State.WAITING
        print("\n  넷 모두 선다.")


if __name__ == "__main__":
    main()

"""s10 ⑤ — 예제 **전부**를 저장하고 되살려 본다.

하나로 되는 것은 운일 수 있다. 실행 위치가 `server`인 업무·기능 예제를 **모두** 돌려
멈춘 자리에서 담고 되살려, **담은 것 ↔ 되살려 다시 담은 것**이 같은지 본다.

여기서 걸리는 것이 「무엇을 담을 수 없는가」의 실제 목록이다 — 업무 값에 JSON으로 적을 수
없는 것(날짜 객체·십진수·집합)이 들어 있으면 여기서 드러난다.

`python sweep.py`로 돌린다.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any

from chaeksas.contracts.bpmn_ext import duration_hours, read_process
from chaeksas.core.engine import Engine, State
from chaeksas.core.run_log import RunLog
from chaeksas.core.senders import RecordingSender
from chaeksas.core.services import RecordingServiceCaller
from common import BPMN, Clock, env
from snapshot import dump, restore

CASES = BPMN.parent / "cases"


def fill(value: Any, *, clock: Clock) -> Any:
    """케이스의 특별한 값 (`$now_plus`·`$test_receiver`)을 메운다 (STU-07)."""
    if isinstance(value, dict) and len(value) == 1:
        key, raw = next(iter(value.items()))
        if key == "$now_plus":
            hours = duration_hours(str(raw))
            return (clock() + timedelta(hours=hours or 0.0)).isoformat()
        if key == "$test_receiver":
            return f"http://127.0.0.1:1/{raw}"
    if isinstance(value, dict):
        return {k: fill(v, clock=clock) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, clock=clock) for v in value]
    return value


def server_examples() -> list[Path]:
    found = []
    for path in sorted(BPMN.glob("*.bpmn")):
        process = read_process(path.read_bytes())
        if (process.info.run_location or "pc") == "server":
            found.append(path)
    return found


def inputs_for(path: Path, *, clock: Clock) -> dict[str, Any] | None:
    case_file = CASES / f"{path.stem}.cases.json"
    if not case_file.exists():
        return None
    cases = json.loads(case_file.read_text(encoding="utf-8")).get("cases") or []
    if not cases:
        return None
    return {k: fill(v, clock=clock) for k, v in (cases[0].get("inputs") or {}).items()}


#: 담는 칸 중 **비어 있지 않은 것을 한 번이라도 봤나** — 안 본 칸은 이 쓸기가 증명하지 못했다.
SEEN: dict[str, int] = {}


def note_coverage(data: dict[str, Any]) -> None:
    for key in ("tokens", "pendings", "arrivals", "expected", "waits", "children", "learned"):
        if data.get(key):
            SEEN[key] = SEEN.get(key, 0) + 1
    if any(t.get("loop") for t in data.get("tokens") or []):
        SEEN["tokens[].loop"] = SEEN.get("tokens[].loop", 0) + 1
    for key, value in (data.get("children") or {}).items():
        note_coverage(value)
        _ = key


def check(path: Path, out: Path) -> tuple[str, str]:
    clock = Clock()
    given = inputs_for(path, clock=clock)
    if given is None:
        return "건너뜀", "케이스가 없다"
    process = read_process(path.read_bytes())
    engine = Engine()
    run_id = f"run_20261013_090000_{abs(hash(path.stem)) % 0x1000000:06x}"
    try:
        run = engine.start(
            process, run_id=run_id, log=RunLog(run_id=run_id), inputs=given,
            mode="deterministic", executor="server_runner", version="1.0.0",
            now=clock(),
            # 서비스 앱은 **담아 두는 어댑터**로 바꿔 끼워 더 멀리 가게 한다 (모델은 그대로 둔다 —
            # 예제마다 짜 둔 답이 있어야 한다).
            env=dataclasses.replace(
                env(clock, RecordingSender(), out), services=RecordingServiceCaller()
            ),
        )
        engine.run_until_blocked(run)
    except Exception as e:  # noqa: BLE001 — 실험이다. 왜 못 돌았는지만 적는다
        return "건너뜀", f"돌지 못했다: {type(e).__name__}: {e}".splitlines()[0][:90]

    where = {
        State.DONE: "끝까지 갔다", State.FAILED: "실패로 끝났다", State.WAITING: "기다린다",
    }.get(run.state, run.state.value)
    try:
        first = dump(run)
        note_coverage(first)
        text = json.dumps(first, ensure_ascii=False, sort_keys=True)
        back = restore(
            json.loads(text), process=process, log=RunLog(run_id=run_id), env=run.env
        )
        same = dump(back) == first
    except Exception:  # noqa: BLE001
        line = traceback.format_exc().strip().splitlines()[-1]
        return "깨졌다", f"{where} — {line[:90]}"
    return ("같다" if same else "다르다"), f"{where}, {len(text)}바이트"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        examples = server_examples()
        print(f"⑤ 실행 위치가 `server`인 예제 {len(examples)}개를 담고 되살린다\n")
        tally: dict[str, int] = {}
        for path in examples:
            verdict, detail = check(path, out)
            tally[verdict] = tally.get(verdict, 0) + 1
            mark = {"같다": "o", "건너뜀": "-"}.get(verdict, "X")
            print(f"  {mark} {path.stem:34} {verdict:5} {detail}")
        print(f"\n  셈: {tally}")
        print("\n  담는 칸 가운데 **비어 있지 않은 것을 본** 횟수")
        for key in ("tokens", "tokens[].loop", "pendings", "waits", "arrivals", "expected",
                    "children", "learned"):
            count = SEEN.get(key, 0)
            print(f"    {key:16} {count:2}건" + ("" if count else "  ← 이 쓸기가 증명하지 못했다"))
        if tally.get("깨졌다") or tally.get("다르다"):
            sys.exit(1)


if __name__ == "__main__":
    main()

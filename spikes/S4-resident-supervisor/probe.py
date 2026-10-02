"""S4 자동 시험: 자식 프로세스 격리·강제 종료·재시작·대기열·실행기→Worker REST (표준 라이브러리만).

    uv run python spikes/S4-resident-supervisor/probe.py

결과는 outputs/result.json, 요약은 화면에. 시험 포트는 기본값(8899)과 겹치지 않게 18890번대를 쓴다.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from supervisor import BotRequest, Supervisor  # noqa: E402
from winjob import pid_alive  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "outputs"
R: dict[str, object] = {}


def t_orphans(mode: str, port: int) -> dict:
    """Bot UI가 강제로 죽었을 때 자식·손자가 남는가."""
    p = subprocess.Popen([sys.executable, str(HERE / "fake_botui.py"), mode, str(port), str(OUT / f"tok-{mode}")],
                         stdout=subprocess.PIPE)
    pids = json.loads(p.stdout.readline())  # type: ignore[union-attr]
    p.kill()  # TerminateProcess — 정리할 기회 없음
    p.wait()
    time.sleep(1.0)
    alive = {k: pid_alive(v) for k, v in pids.items() if v}
    # 시험이 남긴 고아는 여기서 치운다 (모두 이 시험이 띄운 프로세스)
    for k, v in pids.items():
        if alive.get(k):
            subprocess.run(["taskkill", "/F", "/PID", str(v)], capture_output=True, check=False)
    return {"alive_after_botui_killed": alive}


def t_queue(port: int) -> dict:
    sv = Supervisor(port, OUT / "tok-queue")
    assert sv.start_worker()
    sv.queue.extend([
        BotRequest("A-보통", "normal", 0.5),
        BotRequest("B-협조중지", "normal", 30, timeout_s=1.0),   # 시간 초과 → stop 받고 스스로 끝냄
        BotRequest("C-멈춤", "hang", timeout_s=1.0),             # stop을 안 읽음 → 나무째 강제 종료
        BotRequest("D-손자남김", "spawn", timeout_s=1.0),         # 손자까지 강제 종료되는가
        BotRequest("E-비정상종료", "crash"),
        BotRequest("F-보통", "normal", 0.5),
    ])
    t = time.perf_counter()
    res = sv.drain()
    total = round(time.perf_counter() - t, 2)
    gc = next((x.get("grandchild") for r in res if r["mode"] == "spawn" for x in r["lines"] if "grandchild" in x), None)
    sv.shutdown()
    return {"total_s": total, "order": [r["bot"] for r in res],
            "results": [{k: r[k] for k in ("bot", "how", "code", "s", "left_in_job_after")} for r in res],
            "spawn_grandchild_alive_after": pid_alive(gc) if gc else None,
            "first_lines": {r["bot"]: r["lines"][:1] for r in res}}


def t_restart(port: int) -> dict:
    """Worker를 죽이고 다시 뜨기까지, 그 사이 실행기가 본 끊김."""
    sv = Supervisor(port, OUT / "tok-restart")
    assert sv.start_worker()
    threading.Thread(target=sv.watch_worker, daemon=True).start()
    sv.queue.append(BotRequest("P-폴링", "poll", 6.0, timeout_s=10))
    out: dict = {}
    th = threading.Thread(target=lambda: out.setdefault("poll", sv.drain()), daemon=True)
    th.start()
    time.sleep(1.5)
    admin = (sv.token_dir / "worker.admin.token").read_text(encoding="utf-8")
    old_token = (sv.token_dir / "worker.token").read_text(encoding="utf-8")
    req = urllib.request.Request(sv.url + "/v1/admin/crash", method="POST", headers={"X-CHK-Local-Admin": admin})
    t = time.perf_counter()
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except OSError:
        pass
    while not sv.health() and time.perf_counter() - t < 10:
        time.sleep(0.02)
    down_ms = round((time.perf_counter() - t) * 1000)
    th.join(15)
    poll = out["poll"][0]
    sv.shutdown()
    return {"downtime_ms": down_ms, "token_changed": old_token != (sv.token_dir / "worker.token").read_text(
        encoding="utf-8"), "runner_saw": poll["lines"][-1], "events": sv.events}


def t_give_up(port: int) -> dict:
    sv = Supervisor(port, OUT / "tok-giveup", worker_flags=["--die-at-start"])
    first = sv.start_worker()
    th = threading.Thread(target=sv.watch_worker, daemon=True)
    th.start()
    th.join(15)
    sv.shutdown()
    return {"first_start": first, "gave_up": sv.gave_up, "restarts": sv.restarts,
            "events": [e["event"] for e in sv.events]}


def t_port_conflict(port: int) -> dict:
    """다른 프로그램이 포트를 쥐고 있을 때. Windows에서 SO_REUSEADDR는 남의 포트에도 bind를 허락한다."""
    res = {}
    for label, opt in (("plain", None), ("exclusive", getattr(socket, "SO_EXCLUSIVEADDRUSE", None))):
        blocker = socket.socket()
        if opt is not None:
            blocker.setsockopt(socket.SOL_SOCKET, opt, 1)
        blocker.bind(("127.0.0.1", port))
        blocker.listen()
        sv = Supervisor(port, OUT / "tok-conflict")
        ok = sv.start_worker()
        res[label] = {"worker_started": ok, "events": sv.events}
        sv.shutdown()
        blocker.close()
        time.sleep(0.3)
    return res


def main() -> None:
    OUT.mkdir(exist_ok=True)
    R["python"] = sys.executable
    R["orphans_nojob"] = t_orphans("nojob", 18891)
    R["orphans_job"] = t_orphans("job", 18892)
    R["queue"] = t_queue(18893)
    R["restart"] = t_restart(18894)
    R["give_up"] = t_give_up(18895)
    R["port_conflict"] = t_port_conflict(18896)
    (OUT / "result.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in R.items():
        if isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if kk not in ("events", "first_lines")}
        print(f"{k}: {json.dumps(v, ensure_ascii=False)[:600]}")


if __name__ == "__main__":
    main()

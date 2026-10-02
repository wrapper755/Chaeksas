"""가짜 실행기 프로세스: Bot(BPM 프로세스) 하나를 돌리는 흉내 (표준 라이브러리만).

    python fake_runner.py <normal|hang|ignore-stop|spawn|crash|poll> [초]

- Worker 주소는 환경변수 CHK_WORKER__URL, 사용 토큰은 CHK_WORKER__TOKEN_FILE(파일 경로)로 받는다 (C10: 토큰은 파일로만).
- stdin에 `stop` 한 줄이 오면 정리하고 끝낸다 (협조적 중지). `hang`·`ignore-stop`은 이를 읽지 않는다.
- stdout에 JSON 한 줄씩 진행을 쓴다.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def say(**kw: object) -> None:
    print(json.dumps({"t": round(time.time(), 3), "pid": os.getpid(), **kw}), flush=True)


def call(path: str) -> dict:
    url = os.environ["CHK_WORKER__URL"] + path
    token = Path(os.environ["CHK_WORKER__TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    req = urllib.request.Request(url, headers={"X-CHK-Local-Token": token})
    with urllib.request.urlopen(req, timeout=2) as r:
        return json.loads(r.read())


def main() -> None:
    mode = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    stop = threading.Event()
    if mode not in ("hang", "ignore-stop"):
        def watch_stdin() -> None:
            for line in sys.stdin:
                if line.strip() == "stop":
                    stop.set()
                    return
        threading.Thread(target=watch_stdin, daemon=True).start()

    if mode == "spawn":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        say(event="spawned", grandchild=child.pid)
    if mode == "crash":
        say(event="crashing")
        os._exit(7)
    if mode in ("hang", "spawn", "ignore-stop"):
        say(event="hanging")
        while True:
            time.sleep(0.2)
    if mode == "poll":
        # Worker가 재시작되는 동안에도 계속 부른다 — 끊김 구간을 잰다
        end = time.time() + seconds
        ok = fail = 0
        while time.time() < end and not stop.is_set():
            try:
                call("/v1/echo?x=poll")
                ok += 1
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                fail += 1
                say(event="worker-unreachable", error=type(e).__name__)
            time.sleep(0.1)
        say(event="done", ok=ok, fail=fail)
        return
    # normal
    say(event="start", health=call("/v1/health")["ok"], echo=bool(call("/v1/echo?x=1")))
    if stop.wait(seconds):
        say(event="stopped-cooperatively")
        return
    say(event="done")


if __name__ == "__main__":
    main()

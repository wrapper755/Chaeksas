"""가짜 Bot UI: Worker(손자 포함)와 실행기(손자 포함)를 띄우고 pid를 알린 뒤 가만히 있는다.

    python fake_botui.py <job|nojob> <port> <token-dir>

probe.py가 이 프로세스를 **강제 종료**(TerminateProcess)해서, 자식·손자가 함께 죽는지(Job) 남는지(Job 없음) 본다.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from winjob import JobProcess

HERE = Path(__file__).parent


def main() -> None:
    use_job = sys.argv[1] == "job"
    port, token_dir = sys.argv[2], Path(sys.argv[3])
    token_dir.mkdir(parents=True, exist_ok=True)
    for name in ("worker.token", "worker.admin.token"):
        (token_dir / name).write_text("t", encoding="utf-8")
    worker = JobProcess([sys.executable, str(HERE / "fake_worker.py"), "--port", port, "--token-dir", str(token_dir),
                         "--spawn-child"], use_job=use_job, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = {**os.environ, "CHK_WORKER__URL": f"http://127.0.0.1:{port}",
           "CHK_WORKER__TOKEN_FILE": str(token_dir / "worker.token")}
    runner = JobProcess([sys.executable, str(HERE / "fake_runner.py"), "spawn"], use_job=use_job,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    first = json.loads(runner.proc.stdout.readline())  # type: ignore[union-attr]
    import urllib.request  # noqa: PLC0415

    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=1) as r:
                h = json.loads(r.read())
                break
        except OSError:
            time.sleep(0.1)
    print(json.dumps({
        "botui": os.getpid(),
        # 런처(Popen pid)와 진짜 인터프리터(자식이 스스로 알린 pid)를 모두 적는다
        "worker_launcher": worker.pid, "worker": h["pid"], "worker_grandchild": h["child"],
        "runner_launcher": runner.pid, "runner": first["pid"], "runner_grandchild": first["grandchild"],
    }), flush=True)
    time.sleep(600)


if __name__ == "__main__":
    main()

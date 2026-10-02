"""Bot UI의 핵심만 떼어 낸 감독자: Worker 프로세스 감시·재시작, 실행기 하나로 대기열 처리 (표준 라이브러리만).

- 자식은 모두 winjob.JobProcess (자식마다 Job, KILL_ON_JOB_CLOSE).
- Worker: 토큰 파일 두 개 → 기동 → /v1/health 200까지 대기 → 죽으면 다시 띄움 (연속 3회까지, C10).
  건강하게 RESET_AFTER_S 넘게 살아 있었으면 연속 횟수를 0으로 되돌린다.
- 실행기: 대기열(FIFO)에서 하나씩. 시간 초과면 stdin으로 `stop` → GRACE_S 기다림 → Job 나무째 강제 종료 → 다음.
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from winjob import JobProcess

HERE = Path(__file__).parent
PY = sys.executable
MAX_CONSECUTIVE_RESTARTS = 3
RESET_AFTER_S = 5.0
HEALTH_TIMEOUT_S = 30.0
GRACE_S = 2.0


@dataclass
class BotRequest:
    name: str
    mode: str
    seconds: float = 1.0
    timeout_s: float = 5.0


@dataclass
class Supervisor:
    port: int
    token_dir: Path
    worker_flags: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    queue: deque[BotRequest] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.worker: JobProcess | None = None
        self.restarts = 0
        self.gave_up = False
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.t0 = time.perf_counter()

    def log(self, event: str, **kw: Any) -> None:
        self.events.append({"t": round(time.perf_counter() - self.t0, 3), "event": event, **kw})

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    # ---- Worker ---------------------------------------------------------------

    def _write_tokens(self) -> None:
        self.token_dir.mkdir(parents=True, exist_ok=True)
        for name in ("worker.token", "worker.admin.token"):  # Worker를 다시 띄울 때마다 바뀐다 (C10)
            (self.token_dir / name).write_text(secrets.token_urlsafe(32), encoding="utf-8")

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/v1/health", timeout=1) as r:
                return r.status == 200
        except OSError:
            return False

    def start_worker(self) -> bool:
        self._write_tokens()
        t = time.perf_counter()
        self.worker = JobProcess([PY, str(HERE / "fake_worker.py"), "--port", str(self.port),
                                  "--token-dir", str(self.token_dir), *self.worker_flags],
                                 stderr=subprocess.PIPE, stdout=subprocess.DEVNULL)
        while time.perf_counter() - t < HEALTH_TIMEOUT_S:
            if self.health():
                self.log("worker-healthy", pid=self.worker.pid, ms=round((time.perf_counter() - t) * 1000))
                return True
            if self.worker.proc.poll() is not None:
                err = self.worker.proc.stderr.read().decode("utf-8", "replace").strip()  # type: ignore[union-attr]
                self.log("worker-exited-at-start", code=self.worker.proc.returncode, stderr=err[:120])
                return False
            time.sleep(0.05)
        self.log("worker-health-timeout")
        return False

    def watch_worker(self) -> None:
        """Worker 감시 스레드. 죽으면 연속 3회까지 다시 띄운다."""
        healthy_since = time.perf_counter()
        while not self._stop.is_set():
            w = self.worker
            if w and w.proc.poll() is not None:
                self.log("worker-died", code=w.proc.returncode)
                w.close()
                if time.perf_counter() - healthy_since > RESET_AFTER_S:
                    self.restarts = 0
                while self.restarts < MAX_CONSECUTIVE_RESTARTS and not self._stop.is_set():
                    self.restarts += 1
                    time.sleep(0.25 * 2 ** (self.restarts - 1))  # 0.25, 0.5, 1초
                    self.log("worker-restart", attempt=self.restarts)
                    if self.start_worker():
                        healthy_since = time.perf_counter()
                        break
                    self.worker.close()  # type: ignore[union-attr]
                else:
                    if not self._stop.is_set():
                        self.gave_up = True
                        self.log("worker-gave-up", restarts=self.restarts)  # BUI-09: 사용자에게 알림
                        return
            time.sleep(0.05)

    # ---- 실행기·대기열 ------------------------------------------------------------

    def run_one(self, req: BotRequest) -> dict[str, Any]:
        env = {**os.environ, "CHK_WORKER__URL": self.url,
               "CHK_WORKER__TOKEN_FILE": str(self.token_dir / "worker.token")}
        t = time.perf_counter()
        r = JobProcess([PY, str(HERE / "fake_runner.py"), req.mode, str(req.seconds)],
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        out: list[str] = []
        reader = threading.Thread(target=lambda: out.extend(
            line.decode("utf-8", "replace").strip() for line in r.proc.stdout), daemon=True)  # type: ignore[union-attr]
        reader.start()
        how = "exited"
        try:
            r.proc.wait(req.timeout_s)
        except Exception:  # 시간 초과
            how = "stopped"
            try:
                r.proc.stdin.write(b"stop\n")  # type: ignore[union-attr]
                r.proc.stdin.flush()  # type: ignore[union-attr]
            except OSError:
                pass
            try:
                r.proc.wait(GRACE_S)
            except Exception:
                how = "killed"
                tk = time.perf_counter()
                r.terminate_tree()
                r.proc.wait(5)
                self.log("runner-killed", bot=req.name, kill_ms=round((time.perf_counter() - tk) * 1000))
        reader.join(2)
        left = r.active_processes()
        r.close()
        res = {"bot": req.name, "mode": req.mode, "how": how, "code": r.proc.returncode,
               "s": round(time.perf_counter() - t, 2), "left_in_job_after": left,
               "lines": [json.loads(x) for x in out if x.startswith("{")]}
        self.log("bot-finished", bot=req.name, how=how, code=r.proc.returncode)
        return res

    def drain(self) -> list[dict[str, Any]]:
        results = []
        while self.queue:
            results.append(self.run_one(self.queue.popleft()))
        return results

    def shutdown(self) -> None:
        self._stop.set()
        if self.worker:
            self.worker.terminate_tree()
            self.worker.close()


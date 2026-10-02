"""가짜 Worker 프로세스: 127.0.0.1 REST 서버 (C10 기동 절차 흉내, 표준 라이브러리만).

    python fake_worker.py --port <p> --token-dir <폴더> [--die-at-start] [--spawn-child]

- GET  /v1/health            → 200 (토큰 불필요)
- GET  /v1/echo?x=..         → X-CHK-Local-Token 필요
- POST /v1/admin/crash       → X-CHK-Local-Admin 필요, 프로세스가 바로 죽는다 (감시·재시작 시험)
- 포트를 못 열면 stderr에 한 줄 쓰고 종료 코드 2.
- --spawn-child: 손자 프로세스(브라우저 흉내)를 하나 띄운다 → 나무 단위 종료 시험.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--token-dir", type=Path, required=True)
    ap.add_argument("--die-at-start", action="store_true")
    ap.add_argument("--spawn-child", action="store_true")
    a = ap.parse_args()
    if a.die_at_start:
        print("die-at-start", file=sys.stderr, flush=True)
        sys.exit(3)
    token = (a.token_dir / "worker.token").read_text(encoding="utf-8").strip()
    admin = (a.token_dir / "worker.admin.token").read_text(encoding="utf-8").strip()
    child = None
    if a.spawn_child:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/health":
                self._send(200, {"ok": True, "pid": os.getpid(), "child": child.pid if child else None})
            elif self.path.startswith("/v1/echo"):
                if self.headers.get("X-CHK-Local-Token") != token:
                    self._send(401, {"error": "token"})
                else:
                    self._send(200, {"echo": self.path, "t": time.time()})
            else:
                self._send(404, {})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/v1/admin/crash" and self.headers.get("X-CHK-Local-Admin") == admin:
                self._send(200, {"crashing": True})
                self.wfile.flush()
                os._exit(9)
            self._send(403, {})

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    except OSError as e:
        print(f"bind-failed port={a.port} {e}", file=sys.stderr, flush=True)
        sys.exit(2)
    srv.serve_forever()


if __name__ == "__main__":
    main()

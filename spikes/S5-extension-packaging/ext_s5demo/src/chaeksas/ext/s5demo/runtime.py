"""확장의 로컬 런타임 (Worker 프로세스 흉내). 호스트가 `--local-runtime s5demo:worker --port <p>`로 띄운다."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def awareness() -> str:
    import ctypes  # noqa: PLC0415

    u = ctypes.windll.user32
    u.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    u.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    return {0: "unaware", 1: "system", 2: "per-monitor"}.get(
        u.GetAwarenessFromDpiAwarenessContext(u.GetThreadDpiAwarenessContext()), "?")


def main(port: int) -> None:
    class H(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps({"ok": True, "pid": os.getpid(), "frozen": getattr(sys, "frozen", False), "dpi": awareness(),
                               "exe": sys.executable}).encode("utf-8")
            self.send_response(200 if self.path == "/v1/health" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()

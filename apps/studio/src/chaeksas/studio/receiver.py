"""Studio 시험 수신기 — 케이스의 `$test_receiver`가 가리키는 곳 (C14 시험 케이스 형식).

웹훅 회신을 받아 **무엇이 왔는지** 실행 기록에 남긴다. 127.0.0.1에만 열고, 받은 것을 메모리에
쌓기만 한다 (디스크에 쓰지 않는다 — 업무 값이 섞여 있다).

**배포된 Bot에서는 쓸 수 없다** (C14) — 이것은 Studio 시험 실행 전용이다.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
#: 한 번에 받을 본문 한도 (업무 값이 통째로 쌓이지 않게).
MAX_BODY = 256 * 1024


@dataclass
class Delivered:
    """받은 것 하나."""

    name: str
    path: str
    body: Any

    @property
    def summary(self) -> str:
        """로그 한 줄 — **값은 담지 않는다** (계약 원칙 6)."""
        size = len(self.body) if isinstance(self.body, dict | list) else 1
        return f"시험 수신기 「{self.name}」가 {self.path}로 {size}개 칸을 받았습니다"


class _Handler(BaseHTTPRequestHandler):
    receiver: Receiver

    def do_POST(self) -> None:  # noqa: N802 — http.server 이름 그대로
        length = min(int(self.headers.get("Content-Length", "0") or 0), MAX_BODY)
        raw = self.rfile.read(length) if length else b""
        try:
            body: Any = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {"(텍스트)": len(raw)}
        name = self.path.strip("/").split("/")[0] or "reply"
        self.receiver.add(Delivered(name=name, path=self.path, body=body))
        payload = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass  # 콘솔을 더럽히지 않는다 (로그는 Studio의 「로그」 탭이다)


@dataclass
class Receiver:
    """켜고 끄는 작은 수신기. 포트 0을 주면 빈 포트를 고른다 (시험)."""

    port: int = 0
    got: list[Delivered] = field(default_factory=list)
    _server: HTTPServer | None = None
    _thread: threading.Thread | None = None

    def add(self, one: Delivered) -> None:
        self.got.append(one)

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("시험 수신기가 꺼져 있다")
        return f"http://{HOST}:{self._server.server_port}"

    def url_for(self, name: str) -> str:
        """케이스의 `{"$test_receiver": "reply"}`가 되는 주소."""
        return f"{self.base_url}/{name}"

    def start(self) -> Receiver:
        if self._server is not None:
            return self
        handler = type("_Bound", (_Handler,), {"receiver": self})
        self._server = HTTPServer((HOST, self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        log.info("시험 수신기: %s", self.base_url)
        return self

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None


__all__ = ["HOST", "MAX_BODY", "Delivered", "Receiver"]

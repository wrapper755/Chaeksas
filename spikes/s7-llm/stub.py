"""OpenAI 호환 `/v1/chat/completions`를 흉내 내는 최소 서버 (표준 라이브러리만).

진짜 모델을 부르지 않고도 **도구 루프가 도는지**를 잴 수 있다. 대본(`SCRIPT`)대로 차례로
답한다: 먼저 도구를 부르라고 하고, 도구 결과를 받으면 최종 JSON을 낸다.

쓰기: `python stub.py` → http://127.0.0.1:8777
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8777

#: 몇 번째 요청에 무엇을 답할지. OpenAI 호환 응답 모양 그대로.
SCRIPT: list[dict] = [
    # 1) 도구를 부르라고 한다
    {
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "pdf_text_tool", "arguments": '{"path": "a.pdf"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 18},
        "model": "stub-1",
    },
    # 2) 도구 결과를 받고 최종 답 (결과 필드 JSON)
    {
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": '{"공급사": "한빛상사", "금액": 1250000, "항목": [{"품명": "A4", "수량": 10}]}',
                },
            }
        ],
        "usage": {"prompt_tokens": 260, "completion_tokens": 42},
        "model": "stub-1",
    },
]


class Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []
    turn = 0

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        Handler.seen.append(body)
        answer = SCRIPT[min(Handler.turn, len(SCRIPT) - 1)]
        Handler.turn += 1
        payload = json.dumps(answer).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


def serve() -> tuple[HTTPServer, threading.Thread]:
    Handler.seen, Handler.turn = [], 0
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    server, _ = serve()
    print(f"stub on http://127.0.0.1:{PORT}")
    server.serve_forever()

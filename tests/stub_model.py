"""시험용 모델 — 127.0.0.1에 뜨는 작은 OpenAI 호환 서버. **이것은 제품 코드가 아니다.**

인수 시험이 쓰는 모델이다. **바깥에 나가지 않고**, 도구를 부르지 않고, 최종 JSON만 답한다.

**답은 모델이 아니라 시험이 정한다** — 시험하는 것은 모델의 똑똑함이 아니라 **엔진·케이스·
기대값이 한 줄로 맞물리는가**다. 그래서 묶음마다 자기 `canned`를 주고, 짜 둔 답이 없는
자리는 `results`의 타입에 맞는 아무 값으로 때운다 (`answer_for`).

M3·M5 인수 시험이 이 파일을 함께 쓴다 (`tests/fake_desktop_apps.py`와 같은 자리다).
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: 묶음이 주는 답 짜기 — `(받을 필드, 함께 온 값)` → 답 또는 `None`(짜 둔 것이 없다).
Canned = Callable[[dict[str, str], dict[str, Any]], "dict[str, Any] | None"]


def answer_for(wanted: Mapping[str, str]) -> dict[str, Any]:
    """`results: {이름: 타입}`에 맞는 **아무 값** — 짜 둔 답이 없는 자리에서 쓴다."""
    by_type: dict[str, Any] = {
        "string": "스텁 답",
        "number": 1,
        "int": 1,
        "bool": True,
        "date": "2026-09-30",
        "list": [],
        "dict": {},
    }
    return {name: by_type.get(kind, "스텁 답") for name, kind in wanted.items()}


def wanted_fields(asked: str) -> dict[str, str]:
    """물음에서 **받을 필드**를 읽는다 (`core.agent`가 적는 「JSON 객체 하나: 이름(타입), …」)."""
    line = re.search(r"JSON 객체 하나: (.+)", asked)
    out: dict[str, str] = {}
    for part in (line.group(1) if line else "").split(", "):
        found = re.match(r"(.+?)\((.+?)\)$", part.strip())
        if found:
            out[found.group(1)] = found.group(2)
    return out


def given_values(asked: str) -> dict[str, Any]:
    """물음에 함께 온 값 (C14 §「AI 태스크가 보는 값」 — 목표가 이름으로 가리킨 것뿐이다)."""
    line = re.search(r"## 파라미터\n(.+)", asked)
    try:
        found = json.loads(line.group(1)) if line else {}
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


class StubModel:
    """OpenAI 호환 `/v1/chat/completions` 하나. **도구는 부르지 않고** 최종 JSON만 답한다."""

    def __init__(self, canned: Canned) -> None:
        self.canned = canned
        self.asked = 0
        #: 물어본 것들 (시험이 「정말 물었나」를 볼 때).
        self.prompts: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — http.server가 정한 이름
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.asked += 1
                raw = json.dumps({
                    "choices": [{"message": {"role": "assistant", "content": outer.reply(body)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def reply(self, body: dict[str, Any]) -> str:
        """물음에서 **받을 필드**와 **함께 온 값**을 읽어 답을 만든다."""
        asked = "\n".join(m.get("content") or "" for m in body.get("messages", []))
        self.prompts.append(asked)
        wanted = wanted_fields(asked)
        made = self.canned(wanted, given_values(asked))
        return json.dumps(made if made is not None else answer_for(wanted), ensure_ascii=False)

    def __enter__(self) -> StubModel:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        # `/v1/chat/completions`는 어댑터가 붙인다 (ADR-0027) — 여기는 주소 뿌리만.
        return f"http://127.0.0.1:{self.server.server_address[1]}"


__all__ = ["Canned", "StubModel", "answer_for", "given_values", "wanted_fields"]

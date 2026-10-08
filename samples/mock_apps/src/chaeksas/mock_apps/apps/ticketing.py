"""모의 티켓 시스템 — 사내 확장 `ticketing`의 서버 부분. BX-31(요청 접수·분배)이 부른다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario

#: 큐 이름 → 담당 (BX-31의 `종류`가 그대로 큐다).
QUEUES = {"장비": "IT지원팀", "권한": "IT보안팀", "시설": "총무팀", "기타": "IT지원팀"}


def create_ticket(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """티켓 번호는 **입력의 해시**로 만든다.

    같은 요청을 다시 보내면 같은 번호가 나온다 (멱등이 뜻을 갖는다). 번호에 업무 글이
    그대로 들어가지 않는 것도 해시를 쓰는 이유다 (원칙 6).
    """
    payload = json.dumps(dict(req.input), sort_keys=True, ensure_ascii=False, default=str)
    short = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    queue = str(req.input.get("queue") or "기타")
    return {"id": f"TK-{short}", "queue": queue, "assignee": QUEUES.get(queue, QUEUES["기타"])}


APP = MockApp(
    app_id="ticketing",
    name="모의 티켓 시스템",
    extension="ticketing",
    used_by=("BX-31",),
    doc="티켓 생성",
    ops=(Op("create_ticket", "티켓 만들기", create_ticket),),
)

__all__ = ["APP", "QUEUES"]

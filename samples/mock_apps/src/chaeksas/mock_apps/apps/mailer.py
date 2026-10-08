"""모의 대량 메일 발송 — 사내 확장 `mailer`의 서버 부분. BX-23이 부른다.

`chk:send`(엔진의 보내기)와 다른 자리다 — 이쪽은 **업무 시스템이 가진 발송 기능**을
서비스 앱 태스크로 부르는 예다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario


def send_bulk(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """**메일 내용·받는 사람을 돌려주지 않는다** (업무 값이다, 원칙 6). 건수만."""
    mails = req.input.get("mails") or []
    return {"result": {"보낸건수": len(mails), "실패": []}}


APP = MockApp(
    app_id="mailer",
    name="모의 대량 메일",
    extension="mailer",
    used_by=("BX-23",),
    doc="메일 일괄 발송",
    ops=(Op("send_bulk", "메일 일괄 발송", send_bulk),),
)

__all__ = ["APP"]

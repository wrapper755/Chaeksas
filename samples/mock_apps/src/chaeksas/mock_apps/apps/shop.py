"""모의 쇼핑몰 — 환불. 사내 확장 `shop`의 서버 부분. BX-13(반품 처리)이 부른다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario


def refund(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """환불. 환불번호는 주문번호에서 만든다 — 다시 불러도 같은 번호여야 멱등이 뜻을 갖는다."""
    order_id = str(req.input.get("order_id") or "")
    return {
        "result": {
            "상태": "완료",
            "환불번호": f"RF-{order_id}",
            "금액": req.input.get("amount"),
        }
    }


APP = MockApp(
    app_id="shop",
    name="모의 쇼핑몰",
    extension="shop",
    used_by=("BX-13",),
    doc="주문 환불",
    ops=(Op("refund", "주문 환불", refund),),
)

__all__ = ["APP"]

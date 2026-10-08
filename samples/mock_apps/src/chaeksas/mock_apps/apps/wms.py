"""모의 창고 관리 — 재고. 사내 확장 `wms`의 서버 부분. BX-16(발주 제안)이 부른다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario

#: 재고. BX-16 「부족 2품목」이 제안수 2를 기대하므로 **`qty < safety`인 것이 정확히 둘**이다
#: (BPM 프로세스의 식이 `[x for x in 재고 if x.qty < x.safety]`다).
STOCK = (
    {"code": "S-100", "name": "포장 필름", "qty": 40, "safety": 30},
    {"code": "S-200", "name": "라벨 용지", "qty": 12, "safety": 25},
    {"code": "S-300", "name": "완충재", "qty": 5, "safety": 20},
    {"code": "S-400", "name": "테이프", "qty": 90, "safety": 60},
)


def list_stock(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    return {"items": [dict(one) for one in STOCK]}


APP = MockApp(
    app_id="wms",
    name="모의 창고 관리",
    extension="wms",
    used_by=("BX-16",),
    doc="재고·안전재고 목록",
    ops=(Op("list_stock", "재고 목록", list_stock),),
)

__all__ = ["APP", "STOCK"]

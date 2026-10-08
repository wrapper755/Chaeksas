"""모의 제재 대상 조회 — 사내 확장 `compliance`의 서버 부분. BX-10이 부른다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario

#: 거짓 제재 목록. **BX-10 「해외 대액」의 Acme Trading은 여기 없다** — 그 케이스의 「반려」는
#: 통장 사본이 없어서다 (케이스 설명). 제재로도 반려가 되게 해 두면 무엇이 반려를 만들었는지
#: 시험이 구별하지 못한다.
SANCTIONED = (
    {"name": "Blocked Trading Co.", "list": "OFAC SDN", "since": "2024-03-11"},
    {"name": "제재상사", "list": "국내 제재", "since": "2025-07-02"},
)


def screen_sanctions(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """이름이 제재 목록에 있으면 그 줄을, 없으면 **빈 목록**을 돌려준다."""
    name = str(req.input.get("name") or "").strip().casefold()
    hits = [one for one in SANCTIONED if one["name"].casefold() == name]
    return {"hits": hits}


APP = MockApp(
    app_id="compliance",
    name="모의 제재 조회",
    extension="compliance",
    used_by=("BX-10",),
    doc="거래처 이름으로 제재 목록 조회",
    ops=(Op("screen_sanctions", "제재 대상 조회", screen_sanctions),),
)

__all__ = ["APP", "SANCTIONED"]

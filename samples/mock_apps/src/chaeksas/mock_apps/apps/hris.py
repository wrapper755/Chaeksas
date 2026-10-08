"""모의 인사 시스템 — 휴가 원장. 사내 확장 `hris`의 서버 부분.

BX-24(잔여 휴가 조회)가 원장을 읽고, BX-21(휴가 신청)이 등록한다. BX-21은 잔여를
BX-24를 **불러서**(`chk:call`) 얻으므로 두 예제의 기대값이 같은 원장에 걸려 있다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario

#: 휴가 원장. `잔여 = 발생 - 사용 - 예정`이고 BX-24의 기대값이 그 결과다
#: (E001 → 11.5, E002 → 3). E002의 잔여 3이 BX-21 「잔여 부족」(20일 신청)을 막는다.
LEDGERS: dict[str, dict[str, float]] = {
    "E001": {"발생": 15, "사용": 2.5, "예정": 1},
    "E002": {"발생": 15, "사용": 11, "예정": 1},
    "E008": {"발생": 15, "사용": 4, "예정": 0},
    "E009": {"발생": 15, "사용": 7.5, "예정": 0},
}


def get_leave_ledger(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """없는 사번은 `KeyError`로 올린다 — 뼈대가 422 `input_invalid`로 바꾼다."""
    emp_id = str(req.input.get("emp_id") or "")
    return {"ledger": dict(LEDGERS[emp_id])}


def register_leave(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    emp_id = str(req.input.get("emp_id") or "")
    days = req.input.get("days")
    return {
        "result": {
            "등록됨": True,
            # 등록번호는 입력에서 만든다 — 같은 신청을 다시 보내면 같은 번호가 나온다.
            "등록번호": f"LV-{emp_id}-{req.input.get('start')}",
            "일수": days,
        }
    }


APP = MockApp(
    app_id="hris",
    name="모의 인사 시스템",
    extension="hris",
    used_by=("BX-21", "BX-24"),
    doc="휴가 원장 조회·등록",
    ops=(
        Op("get_leave_ledger", "휴가 원장 (발생·사용·예정)", get_leave_ledger),
        Op("register_leave", "휴가 등록", register_leave),
    ),
)

__all__ = ["APP", "LEDGERS"]

"""모의 사내 디렉터리 — 계정·권한. 사내 확장 `directory`의 서버 부분.

BX-20(온보딩)·BX-22(퇴사자 계정 회수)·BX-33(권한 신청)이 부른다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario
from chaeksas.mock_apps.fixtures import day

#: 회사 메일 도메인.
DOMAIN = "example.com"

#: BX-33의 결재 「허용 기간(일)」을 비워 두면 쓰는 값 (그 칸의 기본값과 같다).
DEFAULT_REVOKE_DAYS = 90


def _local_part(emp_id: str) -> str:
    """메일 주소의 앞부분은 **사번에서** 만든다.

    이름으로 만들지 않는다 — 한글 이름을 음역하면 아무도 못 읽는 주소가 된다
    (CLAUDE.md §5, C10 §5의 시맨틱 키와 같은 이유).
    """
    return "".join(c for c in emp_id.lower() if c.isalnum() or c in "-.") or "unknown"


def create_mail_account(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    emp_id = str(req.input.get("emp_id") or "")
    return {"email": f"{_local_part(emp_id)}@{DOMAIN}"}


def create_chat_account(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    emp_id = str(req.input.get("emp_id") or "")
    return {"account": f"@{_local_part(emp_id)}"}


def assign_department(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    return {"result": {"배정됨": True, "부서": req.input.get("dept")}}


def disable_mail(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    return {"result": {"회수됨": True, "사번": req.input.get("emp_id")}}


def disable_vpn(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    return {"result": {"회수됨": True, "사번": req.input.get("emp_id")}}


def grant(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    return {
        "result": {
            "부여됨": True,
            "시스템": req.input.get("system"),
            "권한": req.input.get("role"),
        }
    }


def schedule_revoke(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """회수 예약. 기간을 비워 보내면 기본값을 쓴다 — 결재에서 안 적을 수 있는 칸이다."""
    raw = req.input.get("after_days")
    days = int(raw) if raw is not None else DEFAULT_REVOKE_DAYS
    return {"result": {"예약됨": True, "회수일": day(days), "기간": days}}


APP = MockApp(
    app_id="directory",
    name="모의 사내 디렉터리",
    extension="directory",
    used_by=("BX-20", "BX-22", "BX-33"),
    doc="메일·메신저 계정, 부서 배정, 권한 부여·회수",
    ops=(
        Op("create_mail_account", "회사 메일 계정 만들기", create_mail_account),
        Op("create_chat_account", "메신저 계정 만들기", create_chat_account),
        Op("assign_department", "부서 배정", assign_department),
        Op("disable_mail", "메일 계정 회수", disable_mail),
        Op("disable_vpn", "VPN 계정 회수", disable_vpn),
        Op("grant", "권한 부여", grant),
        Op("schedule_revoke", "권한 회수 예약", schedule_revoke),
    ),
)

__all__ = ["APP", "DEFAULT_REVOKE_DAYS", "DOMAIN"]

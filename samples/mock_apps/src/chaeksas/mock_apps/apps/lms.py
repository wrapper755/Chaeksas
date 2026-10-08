"""모의 교육 시스템 — 미이수자. 사내 확장 `lms`의 서버 부분. BX-23(교육 독려)이 부른다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario
from chaeksas.mock_apps.fixtures import EMPLOYEES, day

#: 미이수자. BX-23 「3명」이 메일 세 통을 기대하므로 **세 명**이고, `남은일수`가 DMN
#: `training_nudge`의 세 갈래를 한 번에 지난다 (< 0 인사팀보고 / 0~7 팀장참조 / > 7 본인안내).
#: `마감일`은 `남은일수`에서 만든다 — 둘이 어긋나면 AI 태스크가 서로 다른 말을 쓴다.
INCOMPLETE: tuple[tuple[str, str, int], ...] = (
    ("E001", "개인정보 보호 2026", -2),
    ("E002", "개인정보 보호 2026", 3),
    ("E008", "정보보안 기본", 14),
)

#: 이수 링크의 앞부분 (거짓 주소 — 아무 곳도 부르지 않는다).
COURSE_URL = "https://lms.example.com/course"


def list_incomplete(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    items = []
    for emp_id, course, left in INCOMPLETE:
        who = EMPLOYEES[emp_id]
        items.append(
            {
                "사번": who.emp_id,
                "이름": who.name,
                "메일": who.mail,
                "팀장메일": who.lead_mail,
                "교육명": course,
                "남은일수": left,
                "마감일": day(left),
                "링크": f"{COURSE_URL}/{who.emp_id}",
            }
        )
    return {"items": items}


APP = MockApp(
    app_id="lms",
    name="모의 교육 시스템",
    extension="lms",
    used_by=("BX-23",),
    doc="필수 교육 미이수자 목록",
    ops=(Op("list_incomplete", "미이수자 목록", list_incomplete),),
)

__all__ = ["APP", "COURSE_URL", "INCOMPLETE"]

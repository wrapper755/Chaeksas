"""모의 CRM — 고객·문서 첨부. 사내 확장 `crm`의 서버 부분.

BX-15(견적서 첨부)가 부른다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario


def attach_document(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """문서 첨부.

    **받은 파일 경로를 돌려주지 않는다** — 파일 이름에 거래처 이름이 들어간다 (원칙 6,
    ADR-0026과 같은 이유로 실행 기록에도 경로를 남기지 않는다).
    """
    return {"result": {"첨부됨": True, "요청번호": req.input.get("request_id")}}


APP = MockApp(
    app_id="crm",
    name="모의 CRM",
    extension="crm",
    used_by=("BX-15",),
    doc="문서 첨부",
    ops=(
        Op("attach_document", "요청에 문서 첨부", attach_document),
    ),
)

__all__ = ["APP"]

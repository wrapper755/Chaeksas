"""모의 ERP — 사내 확장 `erp`의 서버 부분.

BX-08(연체 독촉)·BX-10(거래처 등록)·BX-15(견적)·BX-22(퇴사자 계정 회수)가 부른다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import DEFAULT_SCENARIO, MockApp, Op, Scenario
from chaeksas.service_kit import OpError

#: BX-08 「이관 1건」 — 케이스 설명이 「모의 서버에 95일 연체 1건 추가」라고 적어 두었다.
WITH_TRANSFER = "이관1건"

#: 연체 채권 (BX-08 「평소」: 10·40·20일 → 1차·2차·1차, 이관검토 없음 → 이관건수 0).
#: 금액은 모두 1억 미만이다 — DMN `dunning_stage`는 1억 이상이면 일수와 무관하게 이관검토다.
OVERDUE = (
    {"거래처코드": "V-1234567890", "거래처명": "가나상사", "금액": 4_300_000, "연체일수": 10},
    {"거래처코드": "V-2345678901", "거래처명": "다라물산", "금액": 12_800_000, "연체일수": 40},
    {"거래처코드": "V-3456789012", "거래처명": "마바테크", "금액": 2_100_000, "연체일수": 20},
)

#: 「이관 1건」에서 더해지는 한 건 — 90일 이상이라 DMN이 이관검토로 보낸다.
OVERDUE_EXTRA = {"거래처코드": "V-4567890123", "거래처명": "사아산업", "금액": 31_500_000, "연체일수": 95}

#: 품목 단가표 (BX-15). P-100의 무게 1.2kg × 10개 = 12kg이라 「할인 없음」 케이스의 배송비가
#: DMN `shipping_fee`의 기본 3000이 된다 (20kg를 넘기면 6000이 되어 기대값이 깨진다).
PRICES = {
    "P-100": {"코드": "P-100", "이름": "표준 상자", "단가": 12_000, "무게": 1.2},
    "P-200": {"코드": "P-200", "이름": "대형 상자", "단가": 23_500, "무게": 4.5},
    "P-300": {"코드": "P-300", "이름": "소형 상자", "단가": 4_800, "무게": 0.3},
}

#: BX-22 「ERP 실패」 — 이 사번만 계속 503이다. 재시도 2번 뒤 TASK_FAILED로 오류 경계가 받는다.
BROKEN_EMP_ID = "E009"


def _codes(raw: Any) -> list[str]:
    """`codes`는 품목 목록(`{코드, 수량}`)으로 올 수도, 코드 문자열 목록으로 올 수도 있다."""
    found: list[str] = []
    for one in raw or []:
        found.append(str(one["코드"]) if isinstance(one, Mapping) else str(one))
    return found


def list_overdue_receivables(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """연체 채권 — `기준일`은 받아 두지만 거짓 데이터는 시나리오가 정한다."""
    items = list(OVERDUE)
    if scenario.is_(WITH_TRANSFER):
        items.append(OVERDUE_EXTRA)
    return {"items": items, "기준일": req.input.get("기준일")}


def send_customer_mail(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """독촉 메일 발송 — **내용은 돌려주지 않는다** (업무 값이다, 원칙 6). 건수만."""
    mails = req.input.get("메일") or []
    return {"result": {"보낸건수": len(mails), "실패": []}}


def mark_legal_transfer(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    targets = req.input.get("대상") or []
    return {"result": {"등록건수": len(targets), "접수번호": f"LT-{len(targets):03d}"}}


def create_vendor(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """거래처 코드는 사업자번호에서 만든다 — 같은 입력에 같은 코드가 나와야 멱등이 뜻을 갖는다."""
    biz_no = str(req.input.get("biz_no") or "")
    return {"vendor_code": "V-" + "".join(c for c in biz_no if c.isdigit())}


def get_prices(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    codes = _codes(req.input.get("codes"))
    return {"prices": [PRICES[code] for code in codes]}


def disable_user(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    emp_id = str(req.input.get("emp_id") or "")
    if emp_id == BROKEN_EMP_ID:
        # 503이라 BPM 프로세스가 재시도하고(`retry.on`), 다 떨어지면 오류 경계로 간다.
        raise OpError("dependency_down", "사용자 저장소에 닿지 못했다", status=503)
    return {"result": {"회수됨": True, "사번": emp_id}}


APP = MockApp(
    app_id="erp",
    name="모의 ERP",
    extension="erp",
    scenarios=(DEFAULT_SCENARIO, WITH_TRANSFER),
    used_by=("BX-08", "BX-10", "BX-15", "BX-22"),
    doc="연체 채권·거래처 등록·단가·사용자 회수",
    ops=(
        Op("list_overdue_receivables", "연체 채권 목록", list_overdue_receivables),
        Op("send_customer_mail", "거래처 메일 발송", send_customer_mail),
        Op("mark_legal_transfer", "법무 이관 등록", mark_legal_transfer),
        Op("create_vendor", "거래처 등록", create_vendor),
        Op("get_prices", "품목 단가·무게", get_prices),
        Op("disable_user", "사용자 계정 회수", disable_user),
    ),
)

__all__ = ["APP", "BROKEN_EMP_ID", "OVERDUE", "OVERDUE_EXTRA", "PRICES", "WITH_TRANSFER"]

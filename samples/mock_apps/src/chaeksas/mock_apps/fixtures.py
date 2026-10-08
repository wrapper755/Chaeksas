"""여러 앱이 함께 쓰는 거짓 데이터 — 사람·거래처처럼 앱 경계를 넘는 것만 여기 둔다.

**값은 예제 케이스가 정한다.** `docs/08-business-examples/cases/`의 `expected`가 맞으려면
이 숫자여야 한다 — 예제를 비틀지 않고 앱이 예제를 따라간다 (CLAUDE.md §3-6). 그래서 값마다
어느 케이스가 요구하는지 적어 둔다. 숫자를 고치려면 케이스를 먼저 본다.

앱 하나만 쓰는 데이터는 그 앱 모듈에 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


@dataclass(frozen=True)
class Employee:
    emp_id: str
    name: str
    dept: str
    mail: str
    lead_mail: str


#: 사람. 사번은 예제 입력에 나오는 그대로다.
EMPLOYEES: dict[str, Employee] = {
    # BX-24 「E001」: 잔여 11.5 (hris 원장 15 - 2.5 - 1). BX-21 「2일 승인」·「5일 부서장 반려」도 E001이다.
    "E001": Employee("E001", "안도현", "재무팀", "ahn@example.com", "fin-lead@example.com"),
    # BX-24 「E002」: 잔여 3. BX-21 「잔여 부족」이 20일을 신청해 막히는 사람이다.
    "E002": Employee("E002", "서지우", "영업팀", "seo@example.com", "sales-lead@example.com"),
    # BX-22 「정상」
    "E008": Employee("E008", "최서연", "개발팀", "choi@example.com", "dev-lead@example.com"),
    # BX-22 「ERP 실패」 — ERP가 이 사번에만 계속 503을 돌려준다 (erp.py).
    "E009": Employee("E009", "정하준", "개발팀", "jeong@example.com", "dev-lead@example.com"),
}


@dataclass(frozen=True)
class Vendor:
    biz_no: str
    name: str
    #: 신용점수·연체 — 외부 신용 앱(`ext-credit`)이 돌려주는 값. DMN `credit_grade`가 읽는다.
    score: int
    overdue: bool


#: 거래처. 사업자번호는 예제 입력에 나오는 그대로다.
VENDORS: dict[str, Vendor] = {
    # FX-20 「모의 서버」가 `{"score": 780}`을 기대한다. BX-06·BX-10에서도 이 번호가 나온다.
    "123-45-67890": Vendor("123-45-67890", "가나상사", 780, False),
    # BX-06: 600~750이라 「주의」 — 「위험」이 아니다 (위험수 1이어야 한다).
    "234-56-78901": Vendor("234-56-78901", "다라물산", 700, False),
    # BX-06 「소량 3곳」: 이 한 곳만 연체가 있어 위험수 1이 된다.
    "345-67-89012": Vendor("345-67-89012", "마바테크", 640, True),
    # BX-10 「해외 대액」. 제재 목록에는 없다 — 그 케이스의 「반려」는 통장 사본이 없어서다.
    "999-99-99999": Vendor("999-99-99999", "Acme Trading", 720, False),
}


def today() -> date:
    """모의 앱이 보는 「오늘」. 날짜가 섞인 거짓 데이터를 만들 때 쓴다."""
    return datetime.now(UTC).date()


def day(offset: int) -> str:
    """오늘에서 `offset`일 (ISO). 마감일처럼 오늘에 매달린 값에 쓴다."""
    return (today() + timedelta(days=offset)).isoformat()


__all__ = ["EMPLOYEES", "VENDORS", "Employee", "Vendor", "day", "today"]

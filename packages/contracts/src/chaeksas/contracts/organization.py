"""C16 — 조직(회사 > 부서 > 직원)과 업무 자리 (ADR-0125).

Center 안에 회사가 여럿이고 회사 안에 부서(한 단계), 부서 안에 직원이 있다. 직원은 **사람인지
가상인지 가르지 않는다**. BPM 프로세스는 승인할 때 관리자가 고른 **업무 자리**(회사 공통 /
부서 공통 / 개인) 하나에 놓인다 — 자리는 서명하지 않는다(누구의 일인가이지 무엇을 실행해도
되는가가 아니다).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from ._base import ContractModel, Timestamp, Violation

#: 조직 id — 회사·부서·직원이 같은 규칙이다. 종류마다 Center 전체에서 하나다.
ORG_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"
OrgId = Annotated[str, Field(pattern=ORG_ID_PATTERN)]

#: 회사·부서·직원의 상태 (열린 문자열). 멈추면 그 자리 업무는 새 작업을 만들지 않는다.
STATE_ACTIVE = "active"
STATE_STOPPED = "stopped"
KNOWN_ORG_STATES = frozenset({STATE_ACTIVE, STATE_STOPPED})

#: 업무 자리의 범위 (열린 문자열 — 모르는 값으로는 자리를 바꾸지 않는다).
SCOPE_COMPANY = "company"
SCOPE_DEPARTMENT = "department"
SCOPE_STAFF = "staff"
KNOWN_PLACE_SCOPES = frozenset({SCOPE_COMPANY, SCOPE_DEPARTMENT, SCOPE_STAFF})

#: 직원의 주체 이름 앞머리 — `staff:<id>`. 바깥에서 온 사람 이름은 이것으로 시작할 수 없다 (ADR-0081).
STAFF_PREFIX = "staff:"

#: 옮기기(ADR-0125 §7)가 만드는 회사 — 지금의 장비·패키지가 간다.
DEFAULT_COMPANY_ID = "default"
DEFAULT_COMPANY_NAME = "기본 회사"

#: 상세가 주는 최근 실행 수.
RECENT_RUNS = 20

#: C16 오류 코드 (C16 §오류).
CODE_PLACE_OUTSIDE_COMPANY = "place_outside_company"
CODE_PLACE_NOT_FOR_LIB = "place_not_for_lib"
CODE_COMPANY_MISMATCH = "company_mismatch"
CODE_OWNER_STOPPED = "owner_stopped"


def staff_principal(staff_id: str) -> str:
    """직원의 주체 이름 — `staff:<id>` (사람 이름·키 이름과 겹치지 않는다)."""
    return f"{STAFF_PREFIX}{staff_id}"


# ─────────────────────────── 조직 ───────────────────────────


class CompanyRequest(ContractModel):
    """`POST /companies`·`PUT /companies/{id}` — Center 관리자만."""

    id: OrgId
    name: str = Field(min_length=1, max_length=100)
    state: str = STATE_ACTIVE  # 열린 문자열 (KNOWN_ORG_STATES)


class DepartmentRequest(ContractModel):
    """`POST /departments`·`PUT /departments/{id}` — **한 단계**다(부서 안의 부서는 없다)."""

    id: OrgId
    company: OrgId
    name: str = Field(min_length=1, max_length=100)
    state: str = STATE_ACTIVE


class WorkItem(ContractModel):
    """그 자리에 놓인 업무 하나 — 상세가 읽을 때 모은다."""

    bpm_process_id: str
    #: 살아 있는 배포의 판 (없으면 빈 목록 — 「배포 없음」).
    versions: list[str] = Field(default_factory=list)
    #: 그 판 매니페스트의 C1 `triggers`를 옮긴 것 (`{kind, schedule?, message?}`).
    triggers: list[dict[str, str]] = Field(default_factory=list)


class RecentRun(ContractModel):
    run_id: str
    bpm_process_id: str | None = None
    status: str | None = None  # C3 `RunInfo.status`와 같은 값
    started_at: Timestamp | None = None
    requested_by: str | None = None


class CompanyInfo(CompanyRequest):
    """`GET /companies…` — 셈은 읽을 때 센다."""

    created_at: Timestamp
    updated_at: Timestamp
    departments: int = 0
    staff: int = 0
    processes: int = 0
    bot_uis: int = 0
    studios: int = 0
    #: 하나를 읽을 때만 찬다 — **회사 공통** 자리의 업무와 그 최근 실행 (부서·직원 자리는 그쪽 상세에).
    work: list[WorkItem] = Field(default_factory=list)
    recent_runs: list[RecentRun] = Field(default_factory=list)


class DepartmentInfo(DepartmentRequest):
    created_at: Timestamp
    updated_at: Timestamp
    staff: int = 0
    processes: int = 0
    #: 하나를 읽을 때만 찬다.
    work: list[WorkItem] = Field(default_factory=list)
    recent_runs: list[RecentRun] = Field(default_factory=list)


class StaffRequest(ContractModel):
    """`POST /staff`·`PUT /staff/{id}` — 업무의 주체. 사람인지 가상인지 가르지 않는다."""

    id: OrgId
    company: OrgId
    #: 그 회사의 부서. 비우면 회사에 바로 속한다.
    department: OrgId | None = None
    name: str = Field(min_length=1, max_length=100)
    state: str = STATE_ACTIVE


class StaffInfo(StaffRequest):
    created_at: Timestamp
    updated_at: Timestamp
    #: 하나를 읽을 때만 찬다.
    work: list[WorkItem] = Field(default_factory=list)
    recent_runs: list[RecentRun] = Field(default_factory=list)


# ─────────────────────────── 업무 자리 ───────────────────────────


class Place(ContractModel):
    """업무 자리 — BPM 프로세스(패키지 id)마다 하나. **회사는 적지 않는다** — 패키지의 회사다."""

    scope: str  # 열린 문자열 (KNOWN_PLACE_SCOPES)
    department: OrgId | None = None
    staff: OrgId | None = None

    @model_validator(mode="after")
    def _fields_match_scope(self) -> Place:
        need_department = self.scope == SCOPE_DEPARTMENT
        need_staff = self.scope == SCOPE_STAFF
        if need_department != (self.department is not None):
            raise ValueError("부서 자리에만 department를 적는다")
        if need_staff != (self.staff is not None):
            raise ValueError("직원 자리에만 staff를 적는다")
        return self


class OrgRef(ContractModel):
    """조직 하나를 가리키는 id와 이름 — 실행하는 쪽이 값 출처로 푼다."""

    id: str
    name: str


class PlaceIdentity(ContractModel):
    """**작업의 주인** — Center가 서버 작업을 내려줄 때 붙인다 (C12 `JobDispatch.place`). 저장하지 않는다.

    실행하는 쪽이 출처가 `company.*`·`department.*`·`staff.*`인 입력의 값으로 푼다
    (`core.engine.sourced_inputs`). 그 자리에 없는 것(회사 자리 업무의 직원)은 비어 있다.
    """

    company: OrgRef
    department: OrgRef | None = None
    staff: OrgRef | None = None


def place_values(identity: PlaceIdentity) -> dict[str, str]:
    """주인 → 값 출처별 값 (`company.id` → …). 없는 칸은 넣지 않는다 (`None`은 쓰는 쪽이 준다)."""
    out = {"company.id": identity.company.id, "company.name": identity.company.name}
    if identity.department is not None:
        out["department.id"] = identity.department.id
        out["department.name"] = identity.department.name
    if identity.staff is not None:
        out["staff.id"] = identity.staff.id
        out["staff.name"] = identity.staff.name
    return out


def place_violation(
    place: Place,
    *,
    company: str,
    departments: dict[str, str],
    staff: dict[str, str],
    kind: str = "bpm_process",
) -> Violation | None:
    """자리를 받아도 되나 — 판정만 하고 읽기는 부르는 쪽이 한다.

    `departments`·`staff`는 **id → 회사 id**다(Center가 저장소에서 읽어 넘긴다). 없는 id는 그 회사
    밖과 같은 코드다 — 남의 회사 것이 있다는 것을 알리지 않는다.
    """
    if kind != "bpm_process":
        return Violation(rule="C16", code=CODE_PLACE_NOT_FOR_LIB, message="공유 BPM 프로세스에는 업무 자리가 없습니다.")
    if place.scope not in KNOWN_PLACE_SCOPES:
        return Violation(rule="C16", code="input_invalid", message=f"모르는 자리 범위입니다: {place.scope}")
    if place.department is not None and departments.get(place.department) != company:
        return _outside(f"그 회사의 부서가 아닙니다: {place.department}")
    if place.staff is not None and staff.get(place.staff) != company:
        return _outside(f"그 회사의 직원이 아닙니다: {place.staff}")
    return None


def _outside(message: str) -> Violation:
    return Violation(rule="C16", code=CODE_PLACE_OUTSIDE_COMPANY, message=message)

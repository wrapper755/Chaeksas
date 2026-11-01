"""C16 — 조직·업무 자리 (ADR-0125). 모양과 판정만 본다 — Center는 다음 조각이다."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaeksas.contracts import (
    INPUT_SOURCE_TYPES,
    OrgRef,
    Place,
    PlaceIdentity,
    place_values,
    place_violation,
    staff_principal,
)
from chaeksas.contracts.accounts import KNOWN_ROLES, ROLE_COMPANY_ADMIN
from chaeksas.contracts.bot_ui import JobDispatch
from chaeksas.contracts.bpmn_ext import InputDecl, ProcessInfo
from chaeksas.contracts.organization import (
    CODE_PLACE_NOT_FOR_LIB,
    CODE_PLACE_OUTSIDE_COMPANY,
    StaffRequest,
)
from chaeksas.core.engine import sourced_inputs

DEPARTMENTS = {"sales": "company1", "other-sales": "company2"}
STAFF = {"kim": "company1", "lee": "company2"}


def test_a_place_carries_only_what_its_scope_needs() -> None:
    assert Place(scope="company").department is None
    assert Place(scope="department", department="sales").department == "sales"
    assert Place(scope="staff", staff="kim").staff == "kim"
    for bad in ({"scope": "department"}, {"scope": "staff"}, {"scope": "company", "staff": "kim"},
                {"scope": "staff", "staff": "kim", "department": "sales"}):
        with pytest.raises(ValidationError):
            Place.model_validate(bad)


def test_a_place_must_be_inside_the_package_company() -> None:
    def check(place: Place, kind: str = "bpm_process") -> str | None:
        found = place_violation(place, company="company1", departments=DEPARTMENTS, staff=STAFF, kind=kind)
        return found.code if found else None

    assert check(Place(scope="company")) is None
    assert check(Place(scope="department", department="sales")) is None
    assert check(Place(scope="staff", staff="kim")) is None
    # 남의 회사 것과 없는 것은 같은 코드다 — 있다는 것을 알리지 않는다.
    assert check(Place(scope="department", department="other-sales")) == CODE_PLACE_OUTSIDE_COMPANY
    assert check(Place(scope="staff", staff="lee")) == CODE_PLACE_OUTSIDE_COMPANY
    assert check(Place(scope="staff", staff="nobody")) == CODE_PLACE_OUTSIDE_COMPANY
    assert check(Place(scope="company"), kind="process_lib") == CODE_PLACE_NOT_FOR_LIB


def test_staff_may_sit_directly_under_the_company() -> None:
    assert StaffRequest(id="ceo", company="company1", name="대표").department is None
    with pytest.raises(ValidationError):
        StaffRequest(id="Bad Id", company="company1", name="x")
    assert staff_principal("kim") == "staff:kim"


def test_company_admin_is_a_known_role() -> None:
    assert ROLE_COMPANY_ADMIN in KNOWN_ROLES


def test_the_owner_becomes_inputs_whose_source_is_the_organization() -> None:
    sources = ["company.id", "company.name", "department.id", "department.name", "staff.id", "staff.name"]
    assert all(INPUT_SOURCE_TYPES[one] == "string" for one in sources)
    info = ProcessInfo(inputs=[InputDecl(name=f"v{i}", type="string", source=one) for i, one in enumerate(sources)])
    owner = PlaceIdentity(company=OrgRef(id="company1", name="회사1"), staff=OrgRef(id="kim", name="김구매"))
    got = sourced_inputs(info, owner)
    # 부서 자리가 없으면 그 출처의 입력은 넣지 않는다 — 기본값·필수·`None`을 따른다.
    assert got == {"v0": "company1", "v1": "회사1", "v4": "kim", "v5": "김구매"}
    assert place_values(owner) == {"company.id": "company1", "company.name": "회사1", "staff.id": "kim",
                                   "staff.name": "김구매"}
    assert sourced_inputs(info, None) == {}


def test_a_dispatched_job_may_carry_its_owner() -> None:
    job = JobDispatch.model_validate({
        "job_id": "job_1a2b3c4d", "bpm_process_id": "buy.request", "requested_by": "timer:0 8 * * *",
        "requested_at": "2026-11-01T08:00:00+09:00",
        "place": {"company": {"id": "company1", "name": "회사1"}},
    })
    assert job.place is not None and job.place.department is None


def _manifest(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema": 1, "kind": "bpm_process", "id": "buy.request", "version": "1.0.0", "entry": "process/main.bpmn",
        "process_id": "buy", "requires": {}, "human": {},
        "built": {"by": "studio", "at": "2026-11-01T09:00:00+09:00", "core": "0.3.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    return {**base, **over}


def test_r14_the_place_rides_the_manifest_of_a_bpm_process_only() -> None:
    """업무 자리는 Studio가 고르고 매니페스트에 실린다 (C1 R14, ADR-0127)."""
    from chaeksas.contracts.manifest import Manifest, validate

    def rules(**over: object) -> set[str]:
        return {one.rule for one in validate(Manifest.model_validate(_manifest(**over)))}

    assert "R14" not in rules()
    assert "R14" not in rules(place={"scope": "department", "department": "purchasing"})
    assert "R14" in rules(place={"scope": "team"})
    lib = {"kind": "process_lib", "run_location": None, "entry": None, "process_id": None}
    assert "R14" in rules(**lib, place={"scope": "company"})

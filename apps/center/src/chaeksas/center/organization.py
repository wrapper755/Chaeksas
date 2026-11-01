"""조직 — 회사 > 부서 > 직원과 작업의 주인 (C16, ADR-0125·ADR-0127).

업무 자리는 **매니페스트의 `place`**다(ADR-0127) — 여기에는 자리 표가 없다. 여기가 하는 일은 셋이다.

1. 회사·부서·직원을 저장하고 읽는다 (셈·그 자리 업무·최근 실행은 **읽을 때** 센다).
2. 올릴 때 자리가 그 회사 안인지 판정할 재료를 준다 (`place_maps` → `organization.place_violation`).
3. 작업의 주인을 푼다 — 패키지의 회사 + 매니페스트의 자리 → `(회사, 부서, 직원)`·`PlaceIdentity`.

**지우지 않고 멈춘다** — 실행·작업·패키지가 가리키던 것이 사라지지 않게. `DELETE`는 가리키는 것이
없을 때만 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, loads, now_iso
from chaeksas.contracts.organization import (
    CODE_OWNER_STOPPED,
    RECENT_RUNS,
    SCOPE_COMPANY,
    SCOPE_DEPARTMENT,
    SCOPE_STAFF,
    STATE_STOPPED,
    CompanyInfo,
    CompanyRequest,
    DepartmentInfo,
    DepartmentRequest,
    OrgRef,
    Place,
    PlaceIdentity,
    RecentRun,
    StaffInfo,
    StaffRequest,
    WorkItem,
)

#: 종류 → (표, 화면 이름).
TABLES = {"company": ("companies", "회사"), "department": ("departments", "부서"), "staff": ("staff", "직원")}


def _model(model: Any, body: Any) -> Any:
    try:
        return model.model_validate(body)
    except ValidationError as e:
        raise ApiError(422, "input_invalid", "요청이 계약과 맞지 않는다", {"errors": e.errors()}) from e


def _hidden(kind: str, item_id: str) -> ApiError:
    """없거나 남의 회사 것 — **같은 404**다 (있다는 것조차 알리지 않는다, C16)."""
    return ApiError(404, "not_found", f"그 {TABLES[kind][1]}이 없습니다: {item_id}")


def _row(store: Store, kind: str, item_id: str, *, company: str | None = None) -> Any:
    table = TABLES[kind][0]
    found = store.row(f"SELECT * FROM {table} WHERE id = ?", (item_id,))  # noqa: S608 — 표 이름은 위 표에서만
    if found is None:
        raise _hidden(kind, item_id)
    owner = found["id"] if kind == "company" else found["company"]
    if company is not None and owner != company:
        raise _hidden(kind, item_id)
    return found


def company_exists(store: Store, company_id: str) -> bool:
    return store.row("SELECT 1 FROM companies WHERE id = ?", (company_id,)) is not None


def only_company(store: Store) -> str | None:
    """회사가 **하나뿐이면** 그 id — 자동화 토큰이 회사를 적지 않았을 때만 쓴다."""
    rows = store.rows("SELECT id FROM companies")
    return str(rows[0]["id"]) if len(rows) == 1 else None


# ─────────────────────────── 회사 ───────────────────────────


def _company(store: Store, row: Any, *, detail: bool = False) -> CompanyInfo:
    cid = row["id"]

    def count(sql: str) -> int:
        found = store.row(sql, (cid,))
        return int(found["n"]) if found is not None else 0

    return CompanyInfo(
        id=cid,
        name=row["name"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        departments=count("SELECT COUNT(*) AS n FROM departments WHERE company = ?"),
        staff=count("SELECT COUNT(*) AS n FROM staff WHERE company = ?"),
        processes=count(
            "SELECT COUNT(DISTINCT id) AS n FROM packages WHERE company = ? AND kind = 'bpm_process'"
        ),
        bot_uis=count("SELECT COUNT(*) AS n FROM bot_uis WHERE company = ?"),
        studios=count(
            "SELECT COUNT(*) AS n FROM center_keys WHERE company = ? AND type = 'studio' AND revoked_at IS NULL"
        ),
        work=work_at(store, company=cid, scope=SCOPE_COMPANY) if detail else [],
        recent_runs=recent_runs(store, company=cid) if detail else [],
    )


def companies(store: Store, *, company: str | None = None) -> list[CompanyInfo]:
    rows = store.rows("SELECT * FROM companies ORDER BY id")
    return [_company(store, row) for row in rows if company is None or row["id"] == company]


def get_company(store: Store, company_id: str, *, company: str | None = None) -> CompanyInfo:
    return _company(store, _row(store, "company", company_id, company=company), detail=True)


def put_company(store: Store, body: Any, *, company_id: str | None = None) -> tuple[CompanyInfo, bool]:
    """만들기(`company_id` 없음)·바꾸기. Center 관리자만 — 관문은 부르는 쪽이 본다."""
    wanted: CompanyRequest = _model(CompanyRequest, {**(body or {}), **({"id": company_id} if company_id else {})})
    now = now_iso()
    found = store.row("SELECT 1 FROM companies WHERE id = ?", (wanted.id,))
    if company_id is None and found is not None:
        raise ApiError(409, "exists", f"이미 있는 회사입니다: {wanted.id}")
    if company_id is not None and found is None:
        raise _hidden("company", wanted.id)
    with store.tx() as cur:
        if found is None:
            cur.execute(
                "INSERT INTO companies (id, name, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (wanted.id, wanted.name, wanted.state, now, now),
            )
        else:
            cur.execute(
                "UPDATE companies SET name = ?, state = ?, updated_at = ? WHERE id = ?",
                (wanted.name, wanted.state, now, wanted.id),
            )
    return get_company(store, wanted.id), found is None


# ─────────────────────────── 부서·직원 ───────────────────────────


def _department(store: Store, row: Any, *, detail: bool) -> DepartmentInfo:
    did = row["id"]
    staff = store.row("SELECT COUNT(*) AS n FROM staff WHERE department = ?", (did,))
    work = work_at(store, company=row["company"], scope=SCOPE_DEPARTMENT, target=did)
    return DepartmentInfo(
        id=did,
        company=row["company"],
        name=row["name"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        staff=int(staff["n"]) if staff is not None else 0,
        processes=len(work),
        work=work if detail else [],
        recent_runs=recent_runs(store, department=did) if detail else [],
    )


def _staff(store: Store, row: Any, *, detail: bool) -> StaffInfo:
    sid = row["id"]
    return StaffInfo(
        id=sid,
        company=row["company"],
        department=row["department"],
        name=row["name"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        work=work_at(store, company=row["company"], scope=SCOPE_STAFF, target=sid) if detail else [],
        recent_runs=recent_runs(store, staff=sid) if detail else [],
    )


def departments(store: Store, *, company: str | None = None) -> list[DepartmentInfo]:
    rows = store.rows("SELECT * FROM departments ORDER BY company, id")
    return [_department(store, row, detail=False) for row in rows if company is None or row["company"] == company]


def staff_listing(store: Store, *, company: str | None = None, department: str | None = None) -> list[StaffInfo]:
    rows = store.rows("SELECT * FROM staff ORDER BY company, id")
    return [
        _staff(store, row, detail=False)
        for row in rows
        if (company is None or row["company"] == company) and (department is None or row["department"] == department)
    ]


def get_department(store: Store, item_id: str, *, company: str | None = None) -> DepartmentInfo:
    return _department(store, _row(store, "department", item_id, company=company), detail=True)


def get_staff(store: Store, item_id: str, *, company: str | None = None) -> StaffInfo:
    return _staff(store, _row(store, "staff", item_id, company=company), detail=True)


def _own_company(store: Store, wanted_company: str, *, company: str | None) -> None:
    """적은 회사가 있고, 회사가 정해진 계정이면 **제 회사**여야 한다 (아니면 같은 404)."""
    if (company is not None and wanted_company != company) or not company_exists(store, wanted_company):
        raise _hidden("company", wanted_company)


def put_department(
    store: Store, body: Any, *, item_id: str | None = None, company: str | None = None
) -> tuple[DepartmentInfo, bool]:
    wanted: DepartmentRequest = _model(DepartmentRequest, {**(body or {}), **({"id": item_id} if item_id else {})})
    _own_company(store, wanted.company, company=company)
    found = store.row("SELECT * FROM departments WHERE id = ?", (wanted.id,))
    if item_id is None and found is not None:
        raise ApiError(409, "exists", f"이미 있는 부서입니다: {wanted.id}")
    if item_id is not None:
        found = _row(store, "department", wanted.id, company=company)
        if found["company"] != wanted.company:
            raise ApiError(422, "input_invalid", "부서의 회사는 바꿀 수 없습니다")
    now = now_iso()
    with store.tx() as cur:
        if found is None:
            cur.execute(
                "INSERT INTO departments (id, company, name, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (wanted.id, wanted.company, wanted.name, wanted.state, now, now),
            )
        else:
            cur.execute(
                "UPDATE departments SET name = ?, state = ?, updated_at = ? WHERE id = ?",
                (wanted.name, wanted.state, now, wanted.id),
            )
    return get_department(store, wanted.id), found is None


def put_staff(
    store: Store, body: Any, *, item_id: str | None = None, company: str | None = None
) -> tuple[StaffInfo, bool]:
    wanted: StaffRequest = _model(StaffRequest, {**(body or {}), **({"id": item_id} if item_id else {})})
    _own_company(store, wanted.company, company=company)
    if wanted.department is not None:
        dept = store.row("SELECT company FROM departments WHERE id = ?", (wanted.department,))
        if dept is None or dept["company"] != wanted.company:
            raise ApiError(422, "place_outside_company", f"그 회사의 부서가 아닙니다: {wanted.department}")
    found = store.row("SELECT * FROM staff WHERE id = ?", (wanted.id,))
    if item_id is None and found is not None:
        raise ApiError(409, "exists", f"이미 있는 직원입니다: {wanted.id}")
    if item_id is not None:
        found = _row(store, "staff", wanted.id, company=company)
        if found["company"] != wanted.company:
            raise ApiError(422, "input_invalid", "직원의 회사는 바꿀 수 없습니다")
    now = now_iso()
    with store.tx() as cur:
        if found is None:
            cur.execute(
                "INSERT INTO staff (id, company, department, name, state, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (wanted.id, wanted.company, wanted.department, wanted.name, wanted.state, now, now),
            )
        else:
            cur.execute(
                "UPDATE staff SET department = ?, name = ?, state = ?, updated_at = ? WHERE id = ?",
                (wanted.department, wanted.name, wanted.state, now, wanted.id),
            )
    return get_staff(store, wanted.id), found is None


def remove(store: Store, kind: str, item_id: str, *, company: str | None = None) -> None:
    """등록 해제 — **가리키는 것이 없을 때만** (C16 409 `in_use`). 있으면 멈춘다."""
    _row(store, kind, item_id, company=company)
    column = "department" if kind == "department" else "staff"
    users = []
    if kind == "department" and store.row("SELECT 1 FROM staff WHERE department = ?", (item_id,)) is not None:
        users.append("직원")
    if store.row(f"SELECT 1 FROM jobs WHERE {column} = ?", (item_id,)) is not None:  # noqa: S608
        users.append("작업")
    if work_at(store, company=None, scope=kind, target=item_id, live_only=False):
        users.append("업무")
    if users:
        raise ApiError(409, "in_use", f"가리키는 {'·'.join(users)}이 있어 지울 수 없습니다 — 멈추세요", {"by": users})
    with store.tx() as cur:
        cur.execute(f"DELETE FROM {TABLES[kind][0]} WHERE id = ?", (item_id,))  # noqa: S608


# ─────────────────────────── 업무 자리 (매니페스트에서 읽는다) ───────────────────────────


def place_of(manifest: dict[str, Any] | None) -> Place | None:
    raw = (manifest or {}).get("place")
    if not raw:
        return None
    try:
        return Place.model_validate(raw)
    except ValidationError:
        return None  # R14가 올릴 때 막는다 — 여기 올 일이 없다


def place_maps(store: Store) -> tuple[dict[str, str], dict[str, str]]:
    """부서 id → 회사, 직원 id → 회사 — `organization.place_violation`의 재료."""
    departments_of = {str(r["id"]): str(r["company"]) for r in store.rows("SELECT id, company FROM departments")}
    staff_of = {str(r["id"]): str(r["company"]) for r in store.rows("SELECT id, company FROM staff")}
    return departments_of, staff_of


def work_at(
    store: Store, *, company: str | None, scope: str, target: str | None = None, live_only: bool = True
) -> list[WorkItem]:
    """그 자리에 놓인 업무 — 판마다 매니페스트를 읽는다(자리는 판마다다, ADR-0127).

    한 BPM 프로세스의 **판들 중 하나라도** 그 자리이면 그 업무다. `versions`는 그중 살아 있는 배포의 판이다.
    """
    rows = store.rows(
        "SELECT id, version, company, manifest_json FROM packages WHERE kind = 'bpm_process' ORDER BY id, version"
    )
    from chaeksas.center.api.deployments import live_sql  # noqa: PLC0415 — 순환 import를 피한다

    where, args = live_sql()
    live = {
        (str(r["bpm_process_id"]), str(r["version"]))
        for r in store.rows(
            "SELECT DISTINCT d.bpm_process_id, d.version FROM deployments d JOIN packages p"  # noqa: S608
            f" ON p.id = d.bpm_process_id AND p.version = d.version WHERE {where}",
            args,
        )
    }
    found: dict[str, WorkItem] = {}
    for row in rows:
        if company is not None and row["company"] != company:
            continue
        manifest = loads(row["manifest_json"], {}) or {}
        place = place_of(manifest)
        here = place.scope if place is not None else "company"
        aim = None
        if place is not None:
            aim = place.department if here == SCOPE_DEPARTMENT else place.staff if here == SCOPE_STAFF else None
        if here != scope or (target is not None and aim != target):
            continue
        item = found.setdefault(str(row["id"]), WorkItem(bpm_process_id=str(row["id"])))
        if (str(row["id"]), str(row["version"])) in live:
            item.versions.append(str(row["version"]))
            item.triggers = [
                {k: str(v) for k, v in one.items() if v is not None} for one in manifest.get("triggers") or []
            ]
    return [one for one in found.values() if one.versions or not live_only]


def recent_runs(
    store: Store, *, company: str | None = None, department: str | None = None, staff: str | None = None
) -> list[RecentRun]:
    """그 자리 작업의 최근 실행 — 작업 행에 적힌 **만들 때의 자리**로 모은다.

    회사는 **회사 공통** 자리만이다(부서·직원 칸이 빈 작업) — 부서·직원 자리 실행은 그쪽 상세가 보인다.
    """
    value: str | None
    if company is not None:
        where, value = "j.company = ? AND j.department IS NULL AND j.staff IS NULL", company
    elif department is not None:
        where, value = "j.department = ?", department
    else:
        where, value = "j.staff = ?", staff
    rows = store.rows(
        f"SELECT j.run_id, j.bpm_process_id, j.requested_by, r.summary_json FROM jobs j"  # noqa: S608
        f" JOIN runs r ON r.run_id = j.run_id WHERE {where} ORDER BY r.first_seen_at DESC LIMIT ?",
        (value, RECENT_RUNS),
    )
    out = []
    for row in rows:
        summary = loads(row["summary_json"], {}) or {}
        out.append(
            RecentRun(
                run_id=str(row["run_id"]),
                bpm_process_id=row["bpm_process_id"],
                status=summary.get("status"),
                started_at=summary.get("started_at"),
                requested_by=row["requested_by"],
            )
        )
    return out


# ─────────────────────────── 작업의 주인 ───────────────────────────


@dataclass(frozen=True)
class Owner:
    """작업의 주인 — 작업 행에 적는 세 칸 (C16 `JobInfo`)."""

    company: str | None
    department: str | None = None
    staff: str | None = None


def owner_of(store: Store, package: Any) -> Owner:
    """패키지 행(회사·매니페스트) → 주인. 직원 자리면 그 직원의 부서도 적는다."""
    company = package["company"] if package is not None else None
    place = place_of(loads(package["manifest_json"], {}) if package is not None else None)
    if place is None or company is None:
        return Owner(company=company)
    if place.scope == SCOPE_DEPARTMENT:
        return Owner(company=company, department=place.department)
    if place.scope == SCOPE_STAFF:
        found = store.row("SELECT department FROM staff WHERE id = ?", (place.staff,))
        return Owner(company=company, department=found["department"] if found else None, staff=place.staff)
    return Owner(company=company)


def refuse_stopped(store: Store, owner: Owner) -> None:
    """멈춘 회사·부서·직원의 업무는 새 작업을 만들지 않는다 — 409 `owner_stopped` (C16)."""
    for kind, item_id in (("company", owner.company), ("department", owner.department), ("staff", owner.staff)):
        if item_id is None:
            continue
        row = store.row(f"SELECT state FROM {TABLES[kind][0]} WHERE id = ?", (item_id,))  # noqa: S608
        if row is not None and row["state"] == STATE_STOPPED:
            said = f"{TABLES[kind][1]} {item_id}이 멈춰 있어 새 작업을 만들지 않습니다"
            raise ApiError(409, CODE_OWNER_STOPPED, said)


def stopped(store: Store, owner: Owner) -> bool:
    try:
        refuse_stopped(store, owner)
    except ApiError:
        return True
    return False


def identity(store: Store, company: str | None, department: str | None, staff: str | None) -> PlaceIdentity | None:
    """작업 행의 세 칸 → `JobDispatch.place` (이름은 **내려줄 때** 읽는다 — 저장하지 않는다)."""
    if company is None:
        return None
    found = store.row("SELECT name FROM companies WHERE id = ?", (company,))
    if found is None:
        return None

    def ref(table: str, item_id: str | None) -> OrgRef | None:
        if item_id is None:
            return None
        row = store.row(f"SELECT name FROM {table} WHERE id = ?", (item_id,))  # noqa: S608
        return OrgRef(id=item_id, name=row["name"]) if row is not None else None

    return PlaceIdentity(
        company=OrgRef(id=company, name=found["name"]),
        department=ref("departments", department),
        staff=ref("staff", staff),
    )

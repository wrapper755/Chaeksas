"""조직의 경로 (C16, ADR-0125·ADR-0127).

| 경로 | 인증 |
| --- | --- |
| `GET /companies…` | 읽기 (회사가 정해진 쪽은 제 회사만) |
| `POST/PUT /companies…` | Center 관리자 |
| `GET /departments…`·`/staff…` | 읽기·**Studio 키**(제 회사만 — 올리기 창의 고를 거리) |
| `POST/PUT/DELETE /departments…`·`/staff…` | 관리자 (회사 관리자는 제 회사만) |

판단은 `center.organization`에 있고 여기는 길만 잇는다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from chaeksas.center import organization
from chaeksas.center.api.bot_ui import _json
from chaeksas.center.auth import (
    PACKAGE_KEY_TYPE,
    Caller,
    company_scope,
    require_admin,
    require_center_admin,
    require_read,
)
from chaeksas.center.responses import Utf8JSONResponse
from chaeksas.center.storage import Store

router = APIRouter(prefix="/api/v1", tags=["organization"])


def _store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def _reader(request: Request) -> Caller:
    """읽기 — 콘솔·자동화 토큰·Center API 키, 그리고 Studio 키(제 회사만)."""
    found: Caller = request.app.state.authenticate(request)
    if found.key is not None and found.key.type == PACKAGE_KEY_TYPE:
        return found
    return require_read(found)


def _made(info: Any, created: bool) -> Any:
    return Utf8JSONResponse(status_code=201 if created else 200, content=info.to_json_dict())


# ─────────────────────────── 회사 ───────────────────────────


@router.get("/companies")
def list_companies(request: Request) -> Any:
    return organization.companies(_store(request), company=company_scope(_reader(request)))


@router.get("/companies/{company_id}")
def get_company(request: Request, company_id: str) -> Any:
    return organization.get_company(_store(request), company_id, company=company_scope(_reader(request)))


@router.post("/companies")
async def create_company(request: Request) -> Any:
    require_center_admin(request.app.state.authenticate(request))
    return _made(*organization.put_company(_store(request), await _json(request)))


@router.put("/companies/{company_id}")
async def update_company(request: Request, company_id: str) -> Any:
    require_center_admin(request.app.state.authenticate(request))
    return organization.put_company(_store(request), await _json(request), company_id=company_id)[0]


# ─────────────────────────── 부서 ───────────────────────────


@router.get("/departments")
def list_departments(request: Request, company: str | None = None) -> Any:
    scope = company_scope(_reader(request))
    found = organization.departments(_store(request), company=scope or company)
    return [one for one in found if company is None or one.company == company]


@router.get("/departments/{item_id}")
def get_department(request: Request, item_id: str) -> Any:
    return organization.get_department(_store(request), item_id, company=company_scope(_reader(request)))


@router.post("/departments")
async def create_department(request: Request) -> Any:
    found = require_admin(request.app.state.authenticate(request))
    return _made(*organization.put_department(_store(request), await _json(request), company=found.company))


@router.put("/departments/{item_id}")
async def update_department(request: Request, item_id: str) -> Any:
    found = require_admin(request.app.state.authenticate(request))
    return organization.put_department(_store(request), await _json(request), item_id=item_id, company=found.company)[0]


@router.delete("/departments/{item_id}")
def delete_department(request: Request, item_id: str) -> Any:
    found = require_admin(request.app.state.authenticate(request))
    organization.remove(_store(request), "department", item_id, company=found.company)
    return Response(status_code=204)


# ─────────────────────────── 직원 ───────────────────────────


@router.get("/staff")
def list_staff(request: Request, company: str | None = None, department: str | None = None) -> Any:
    scope = company_scope(_reader(request))
    found = organization.staff_listing(_store(request), company=scope or company, department=department)
    return [one for one in found if company is None or one.company == company]


@router.get("/staff/{item_id}")
def get_staff(request: Request, item_id: str) -> Any:
    return organization.get_staff(_store(request), item_id, company=company_scope(_reader(request)))


@router.post("/staff")
async def create_staff(request: Request) -> Any:
    found = require_admin(request.app.state.authenticate(request))
    return _made(*organization.put_staff(_store(request), await _json(request), company=found.company))


@router.put("/staff/{item_id}")
async def update_staff(request: Request, item_id: str) -> Any:
    found = require_admin(request.app.state.authenticate(request))
    return organization.put_staff(_store(request), await _json(request), item_id=item_id, company=found.company)[0]


@router.delete("/staff/{item_id}")
def delete_staff(request: Request, item_id: str) -> Any:
    found = require_admin(request.app.state.authenticate(request))
    organization.remove(_store(request), "staff", item_id, company=found.company)
    return Response(status_code=204)

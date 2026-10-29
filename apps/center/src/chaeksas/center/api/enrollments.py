"""등록 요청과 승인의 경로 (C4·C12 §등록 요청과 승인, C5 §등록 승인, ADR-0092).

| 경로 | 인증 |
| --- | --- |
| `POST /bot-ui/enroll`, `GET /bot-ui/enroll/{id}` | 없음 — 내려 주는 키는 요청의 공개키로 봉해 있다 |
| `POST /server-runner/enroll`, `GET /server-runner/enroll/{id}` | 위와 같다 |
| `POST /studio/enroll`, `GET /studio/enroll/{id}` | 위와 같다 (ADR-0093) |
| `GET /enrollments` | 읽기·관리자 |
| `POST /enrollments/{id}/approve·reject` | 관리자 |

판단은 `center.enrollments`에 있고 여기는 길만 잇는다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from chaeksas.center import enrollments
from chaeksas.center.api.bot_ui import _json
from chaeksas.center.auth import Caller, require_admin, require_read
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store
from chaeksas.contracts.enrollment import EnrollmentApproveRequest, EnrollmentRejectRequest

router = APIRouter(prefix="/api/v1", tags=["enrollments"])


def _store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def _remote(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


@router.post("/bot-ui/enroll", status_code=201)
async def post_bot_ui_enroll(request: Request) -> Any:
    return enrollments.request(_store(request), kind="bot_ui", body=await _json(request), remote_addr=_remote(request))


@router.get("/bot-ui/enroll/{enrollment_id}")
def get_bot_ui_enroll(request: Request, enrollment_id: str) -> Any:
    return enrollments.status(_store(request), enrollment_id, kind="bot_ui")


@router.post("/server-runner/enroll", status_code=201)
async def post_runner_enroll(request: Request) -> Any:
    return enrollments.request(
        _store(request), kind="server_runner", body=await _json(request), remote_addr=_remote(request)
    )


@router.get("/server-runner/enroll/{enrollment_id}")
def get_runner_enroll(request: Request, enrollment_id: str) -> Any:
    return enrollments.status(_store(request), enrollment_id, kind="server_runner")


@router.post("/studio/enroll", status_code=201)
async def post_studio_enroll(request: Request) -> Any:
    """Studio의 등록 요청 (C5 §Studio 등록 요청과 승인, ADR-0093) — Bot UI와 같은 길이다."""
    return enrollments.request(_store(request), kind="studio", body=await _json(request), remote_addr=_remote(request))


@router.get("/studio/enroll/{enrollment_id}")
def get_studio_enroll(request: Request, enrollment_id: str) -> Any:
    return enrollments.status(_store(request), enrollment_id, kind="studio")


@router.get("/enrollments")
def list_enrollments(request: Request, type: str | None = None, state: str | None = None) -> Any:
    found: Caller = request.app.state.authenticate(request)
    require_read(found)
    states = [one.strip() for one in state.split(",") if one.strip()] if state else None
    return enrollments.listing(_store(request), kind=type, states=states)


@router.post("/enrollments/{enrollment_id}/approve")
async def approve_enrollment(request: Request, enrollment_id: str) -> Any:
    found: Caller = require_admin(request.app.state.authenticate(request))
    try:
        body = EnrollmentApproveRequest.model_validate(await _json(request))
    except ValueError as e:
        raise ApiError(422, "input_invalid", "승인 요청이 계약과 맞지 않는다") from e
    return enrollments.approve(
        _store(request), enrollment_id, name=body.name, actor=found.actor, topics=body.topics
    )


@router.post("/enrollments/{enrollment_id}/reject")
async def reject_enrollment(request: Request, enrollment_id: str) -> Any:
    found: Caller = require_admin(request.app.state.authenticate(request))
    try:
        body = EnrollmentRejectRequest.model_validate(await _json(request))
    except ValueError as e:
        raise ApiError(422, "input_invalid", "거절 사유는 200자까지다") from e
    return enrollments.reject(_store(request), enrollment_id, reason=body.reason, actor=found.actor)

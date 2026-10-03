"""오류 — 모든 응답이 같은 모양이다 (`{code, message, detail}`, C5·C11).

Center는 **코드로 말한다.** 부르는 쪽의 재시도 판단이 그 값에 걸려 있다 (C11 오류 표).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from chaeksas.center.responses import Utf8JSONResponse
from chaeksas.contracts.center_api import ErrorBody


class ApiError(Exception):
    """계약이 정한 코드로 실패를 알린다.

        raise ApiError(409, "machine_mismatch", "이 키는 다른 PC에 묶여 있다")
    """

    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}

    def response(self) -> JSONResponse:
        body = ErrorBody(code=self.code, message=self.message, detail=self.detail)
        return Utf8JSONResponse(status_code=self.status, content=body.to_json_dict())


async def handle(_request: Request, exc: Exception) -> JSONResponse:
    """`ApiError`를 계약 모양으로 바꾼다 (FastAPI 예외 처리기)."""
    assert isinstance(exc, ApiError)
    return exc.response()

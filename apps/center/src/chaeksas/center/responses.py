"""Center의 JSON 응답 — `Content-Type`에 `charset=utf-8`을 붙인다.

JSON은 원래 UTF-8이지만, charset이 없으면 Windows PowerShell 5.1의 `Invoke-RestMethod`가 본문을
ISO-8859-1로 읽어 한글 이름이 깨져 보인다 (이슈 #3 — 운영자가 키·Bot UI 목록을 PowerShell로 본다).
"""

from __future__ import annotations

from fastapi.responses import JSONResponse


class Utf8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


__all__ = ["Utf8JSONResponse"]

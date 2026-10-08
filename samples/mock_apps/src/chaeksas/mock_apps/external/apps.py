"""모의 외부 앱 둘 — `ext-credit`(신용 조회)·`ext-helpdesk`(헬프데스크).

**여기만 `service_kit`을 쓰지 않는다.** 외부 앱은 우리 계약을 모르는 남의 HTTP API이고,
그래서 C13 §4의 **HTTP 어댑터**로 붙는다 (`core.http_adapter`). 모의 앱이 C11로 답하면
어댑터가 하는 일(템플릿 채우기·제한 JSONPath로 읽기·`error_when`)을 하나도 시험하지 못한다.

그래서 일부러 남의 API처럼 생겼다 — 낙타 표기 필드(`bizNo`), 자기만의 봉투(`status`·`ok`),
자기만의 경로(`/v1/credit/lookup`). 어댑터 정의가 그것을 우리 말로 옮긴다
(`definitions.py`).

**토큰은 받아서 확인만 한다.** 값은 어디에도 남기지 않는다 (원칙 6).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

#: 모의 외부 앱의 토큰 환경변수. 주지 않으면 **아무 Bearer나** 받는다 (개발 편의).
#: 비어 있는 Authorization은 그래도 거절한다 — 어댑터가 키를 싣는지 시험해야 한다.
TOKEN_ENV = {"ext-credit": "CHK_MOCK_EXT_CREDIT__TOKEN", "ext-helpdesk": "CHK_MOCK_EXT_HELPDESK__TOKEN"}

#: BX-35 「소량 120건」 — `나누기(VOC, 50)`이 3묶음이 되려면 101~150건이어야 한다.
TICKET_COUNT = 120

#: 거짓 문의 본문 밑감 (돌려 쓴다). 업무 값이 아니라 지어낸 글이다.
TICKET_SEEDS = (
    ("배송", "주문한 상품이 아직 안 왔어요. 언제쯤 받을 수 있나요?"),
    ("배송", "배송 조회를 눌렀는데 운송장 번호가 안 보입니다."),
    ("환불", "단순 변심으로 반품하려는데 배송비가 얼마인가요?"),
    ("환불", "환불 신청한 지 일주일인데 아직 입금이 안 됐습니다."),
    ("품질", "받은 제품에 흠집이 있습니다. 교환 가능한가요?"),
    ("품질", "포장이 찌그러진 채로 왔어요."),
    ("가입", "비밀번호를 잊었는데 재설정 메일이 안 옵니다."),
    ("칭찬", "상담원이 친절하게 알려 주셨습니다. 감사합니다."),
)

CHANNELS = ("웹", "앱", "전화", "메일")


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"error": "missing_or_bad_token"})


def _token_ok(app_id: str, request: Request) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return False
    wanted = os.environ.get(TOKEN_ENV[app_id], "").strip()
    return not wanted or value.strip() == wanted


def credit_app() -> FastAPI:
    """`ext-credit` — 신용 조회. 모르는 사업자번호는 `status: "not_found"`로 답한다.

    오류를 **HTTP 상태가 아니라 본문으로** 알리는 API다 (흔한 모양이다). 어댑터 정의의
    `error_when`이 그것을 업무 실패로 바꾼다 (C13 §4-4).
    """
    from chaeksas.mock_apps.fixtures import VENDORS  # noqa: PLC0415 — 순환 import 피하기

    app = FastAPI(title="모의 외부 신용 조회", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "up"}

    @app.post("/v1/credit/lookup")
    async def lookup(request: Request) -> Any:
        if not _token_ok("ext-credit", request):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"status": "bad_request"})
        found = VENDORS.get(str(body.get("bizNo") or ""))
        if found is None:
            return {"status": "not_found", "result": None}
        return {"status": "ok", "result": {"score": found.score, "overdue": found.overdue}}

    return app


def helpdesk_app() -> FastAPI:
    """`ext-helpdesk` — 문의 내려받기·답변 등록."""
    app = FastAPI(title="모의 외부 헬프데스크", version="1.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "up"}

    @app.post("/api/tickets/export")
    async def export_tickets(request: Request) -> Any:
        if not _token_ok("ext-helpdesk", request):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"ok": False})
        return {"ok": True, "since": body.get("since"), "tickets": tickets()}

    @app.post("/api/tickets/{ticket_id}/replies")
    async def post_reply(ticket_id: str, request: Request) -> Any:
        if not _token_ok("ext-helpdesk", request):
            return _unauthorized()
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(status_code=400, content={"ok": False})
        message = str(body.get("message") or "")
        if not message:
            return JSONResponse(status_code=422, content={"ok": False, "error": "empty_message"})
        # 답변 id는 문의 번호에서 만든다 — 같은 것을 다시 보내도 같은 id다.
        # **답변 글을 되돌려주지 않는다** (업무 값이다).
        short = hashlib.sha256(ticket_id.encode("utf-8")).hexdigest()[:8]
        return {"ok": True, "replyId": f"RP-{short}", "ticketId": ticket_id}

    return app


def tickets() -> list[dict[str, Any]]:
    """거짓 문의 `TICKET_COUNT`건. 밑감을 돌려 쓰므로 **부를 때마다 같다**."""
    found = []
    for i in range(TICKET_COUNT):
        channel_name, body = TICKET_SEEDS[i % len(TICKET_SEEDS)]
        found.append(
            {
                "id": f"HD-{i + 1:04d}",
                "subject": f"[{channel_name}] 문의 {i + 1}",
                "body": body,
                "channel": CHANNELS[i % len(CHANNELS)],
                "createdAt": f"2026-10-{(i % 7) + 1:02d}T09:00:00Z",
            }
        )
    return found


#: app_id → 앱을 만드는 함수.
BUILDERS = {"ext-credit": credit_app, "ext-helpdesk": helpdesk_app}

__all__ = ["BUILDERS", "CHANNELS", "TICKET_COUNT", "TICKET_SEEDS", "TOKEN_ENV", "credit_app", "helpdesk_app", "tickets"]

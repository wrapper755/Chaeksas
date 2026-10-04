"""메일·웹훅을 **실제로 보내는 자리** — C14 §보내기.

엔진은 받는 사람·제목·본문을 만들어 넘기기만 하고, 보내는 일은 **실행하는 쪽이 끼우는 어댑터**가
한다. 그래야 Studio 시험 실행이 진짜 메일을 보내지 않고, Bot UI가 SMTP·허용 호스트 설정(M5)을
자기 쪽에 둘 수 있다.

**어댑터를 주지 않으면 보내지 않고 실패한다** (`SendError` → `TaskFailed(SEND_FAILED)`).
조용히 삼키면 「보냈겠거니」 하고 업무가 흘러가 버린다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

#: 웹훅 응답 본문을 변수에 담을 때의 한도 (업무 값이 통째로 들어오지 않게).
MAX_RESPONSE_TEXT = 2000


class SendError(RuntimeError):
    """보내지 못했다. 엔진이 `TaskFailed(SEND_FAILED)`로 바꿔 오류 경계에 넘긴다."""


@dataclass(frozen=True)
class EmailMessage:
    """보낼 메일 하나. 템플릿은 이미 채워져 있고, 첨부는 **푼 경로**다."""

    to: tuple[str, ...]
    cc: tuple[str, ...] = ()
    subject: str = ""
    body: str = ""
    attachments: tuple[Path, ...] = ()


@dataclass(frozen=True)
class WebhookRequest:
    """보낼 웹훅 하나. `body`는 JSON으로 실린다 (`template:`이면 글자 그대로)."""

    url: str
    method: str = "POST"
    body: Mapping[str, Any] | str = ""
    timeout_s: float | None = None


@dataclass(frozen=True)
class SendResult:
    """보낸 결과. `store_as`에 들어갈 **요약**을 만든다 (C14 §보내기)."""

    ok: bool = True
    id: str | None = None
    status: int | None = None
    text: str | None = None

    def email_summary(self, *, recipients: int) -> dict[str, Any]:
        return {"ok": self.ok, "to": recipients, "id": self.id}

    def webhook_summary(self) -> dict[str, Any]:
        body = self.text or ""
        return {"ok": self.ok, "status": self.status, "body": body[:MAX_RESPONSE_TEXT]}


class Sender(Protocol):
    """보내기 어댑터. 실패는 `SendError`로 올린다."""

    def send_email(self, message: EmailMessage) -> SendResult: ...

    def send_webhook(self, request: WebhookRequest) -> SendResult: ...


class NoSender:
    """기본 — **보내지 않고 실패한다.** 실행하는 쪽이 어댑터를 끼워야 보낼 수 있다."""

    def send_email(self, message: EmailMessage) -> SendResult:
        raise SendError("메일 보내기 어댑터가 없다 (실행하는 쪽이 끼워야 한다)")

    def send_webhook(self, request: WebhookRequest) -> SendResult:
        raise SendError("웹훅 보내기 어댑터가 없다 (실행하는 쪽이 끼워야 한다)")


@dataclass
class RecordingSender:
    """시험용 — 보내지 않고 **무엇을 보내려 했는지 담아 둔다.**

    Studio 시험 실행과 단위 시험이 이것을 끼운다. 진짜로 보내는 어댑터는 Bot UI·서버 실행기가
    준다 (M5).
    """

    emails: list[EmailMessage] = field(default_factory=list)
    webhooks: list[WebhookRequest] = field(default_factory=list)
    status: int = 200
    response_text: str = ""
    #: 참이면 보내려 할 때마다 실패한다 (오류 경계 시험).
    fails: bool = False

    def send_email(self, message: EmailMessage) -> SendResult:
        if self.fails:
            raise SendError("시험용 어댑터가 실패하도록 되어 있다")
        self.emails.append(message)
        return SendResult(ok=True, id=f"rec_{len(self.emails)}")

    def send_webhook(self, request: WebhookRequest) -> SendResult:
        if self.fails:
            raise SendError("시험용 어댑터가 실패하도록 되어 있다")
        self.webhooks.append(request)
        return SendResult(ok=True, status=self.status, text=self.response_text)


__all__ = [
    "MAX_RESPONSE_TEXT",
    "EmailMessage",
    "NoSender",
    "RecordingSender",
    "SendError",
    "SendResult",
    "Sender",
    "WebhookRequest",
]

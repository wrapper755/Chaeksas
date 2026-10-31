"""메일·웹훅을 **실제로 보내는 자리** — C14 §보내기.

엔진은 받는 사람·제목·본문을 만들어 넘기기만 하고, 보내는 일은 **실행하는 쪽이 끼우는 어댑터**가
한다. 그래야 Studio 시험 실행이 진짜 메일을 보내지 않고, PC 실행기·서버 실행기가 SMTP·허용 호스트
설정을 자기 쪽에 둘 수 있다 ([ADR-0059](../../../../docs/decisions/0059-sending-mail-and-webhooks.md)).

**어댑터를 주지 않으면 보내지 않고 실패한다** (`SendError` → `TaskFailed(SEND_FAILED)`).
조용히 삼키면 「보냈겠거니」 하고 업무가 흘러가 버린다.

제품용 어댑터는 `PlatformSender` 하나이고 **PC와 서버가 같은 것을 쓴다** — 다른 것은 설정을
어디서 받는지(BUI-03 / 환경변수)뿐이다. 메일은 `SmtpSender`, 웹훅은 `HttpWebhookSender`다.

**재시도하지 않는다** (ADR-0059 §5) — 보내기는 멱등이 아니라서 두 번 보내면 사람이 메일을 두 통
받는다. 실패는 오류 경계로 올리고, 다시 보낼지는 그림이 정한다.
"""

from __future__ import annotations

import mimetypes
import smtplib
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage as MailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from chaeksas.contracts.extension import HostRefused, resolve_host

#: 웹훅 응답 본문을 변수에 담을 때의 한도 (업무 값이 통째로 들어오지 않게).
MAX_RESPONSE_TEXT = 2000

#: SMTP 보안 (ADR-0059 §1). **기본은 `starttls`다** — 느슨한 쪽을 기본으로 두지 않는다.
SECURITY_STARTTLS = "starttls"
SECURITY_SSL = "ssl"
SECURITY_NONE = "none"
KNOWN_SECURITY = (SECURITY_STARTTLS, SECURITY_SSL, SECURITY_NONE)
#: 보안마다의 기본 포트 — 사람이 포트를 비우면 이것을 쓴다.
DEFAULT_PORTS = {SECURITY_STARTTLS: 587, SECURITY_SSL: 465, SECURITY_NONE: 25}

DEFAULT_SMTP_TIMEOUT_S = 20.0
#: 첨부 합계 상한 (MB). 넘으면 **보내기 전에** 실패한다 (서버가 거절하는 것보다 낫다).
DEFAULT_ATTACHMENT_MB = 10.0

DEFAULT_WEBHOOK_TIMEOUT_S = 10.0
DEFAULT_WEBHOOK_RESPONSE_KB = 64


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

    Studio 시험 실행과 단위 시험이 이것을 끼운다. 진짜로 보내는 어댑터는 PC 실행기·서버 실행기가
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


# ─────────────────────── 제품용 어댑터 (ADR-0059) ───────────────────────


@dataclass(frozen=True)
class SmtpConfig:
    """메일을 보낼 서버 (ADR-0059 §1). **비밀번호는 여기 없다** — 부르는 쪽이 따로 준다."""

    host: str = ""
    #: 0이면 `security`에 맞는 기본 포트 (587·465·25).
    port: int = 0
    security: str = SECURITY_STARTTLS
    username: str = ""
    #: 보내는 주소 (`From`). **없으면 보내지 않는다** — 받는 쪽이 누가 보냈는지 못 본다.
    sender: str = ""
    timeout_s: float = DEFAULT_SMTP_TIMEOUT_S
    max_attachment_mb: float = DEFAULT_ATTACHMENT_MB

    @property
    def configured(self) -> bool:
        """보낼 수 있는 설정인가 — 사전 점검(C1 `requires.settings`의 `smtp`)이 이것을 본다."""
        return not self.problems()

    @property
    def real_port(self) -> int:
        return self.port or DEFAULT_PORTS.get(self.security, 587)

    def problems(self) -> list[str]:
        """모자란 것들 (사람이 읽을 한 줄씩). 화면과 사전 점검이 같은 글을 쓴다."""
        out = []
        host = self.host.strip()
        if not host:
            out.append("SMTP 주소가 비어 있습니다")
        elif ":" in host and not host.startswith("["):
            # `localhost:2525`처럼 적으면 포트 칸(0 → 기본 포트)이 이겨 엉뚱한 곳으로 간다.
            out.append("SMTP 주소에 포트를 붙이지 마세요 — 포트는 「포트」 칸에 적습니다")
        if not self.sender.strip():
            out.append("보내는 주소(From)가 비어 있습니다")
        if self.security not in KNOWN_SECURITY:
            out.append(f"모르는 보안 방식입니다: {self.security} (쓸 수 있는 것: {', '.join(KNOWN_SECURITY)})")
        return out


@dataclass(frozen=True)
class WebhookConfig:
    """웹훅을 보낼 수 있는 곳 (ADR-0059 §2).

    **허용 호스트는 운영자가 적는다** — 어댑터는 서명된 정의가 들고 오지만(C13 E3) `bpm:webhook`의
    URL은 BPM 프로세스의 템플릿이라, 승인·배포만으로 임의의 주소에 업무 값을 보낼 수 없어야 한다.
    **비면 아무 데도 보내지 않는다** (ADR-0032와 같은 결 — 열어야 열린다).
    """

    allowed_hosts: tuple[str, ...] = ()
    timeout_s: float = DEFAULT_WEBHOOK_TIMEOUT_S
    max_response_kb: int = DEFAULT_WEBHOOK_RESPONSE_KB
    #: 사설·루프백을 여는가. **설정에 이 스위치를 두지 않는다** (ADR-0059 §2) — 시험과
    #: Studio 시험 수신기만 켠다. 켜 두면 사내 아무 주소로나 업무 값이 나간다.
    allow_private_network: bool = False


@dataclass
class SmtpSender:
    """메일 하나를 SMTP로 보낸다. **표준 라이브러리만** 쓴다 (설치 파일이 커지지 않는다)."""

    config: SmtpConfig = field(default_factory=SmtpConfig)
    #: 비밀번호 — 설정 파일·실행 기록에 넣지 않는다 (CLAUDE.md §5). 비우면 로그인하지 않는다.
    password: str = ""
    #: `(host, port, timeout) -> smtplib.SMTP 같은 것`. 시험이 끼운다.
    connect: Any = None

    def send_email(self, message: EmailMessage) -> SendResult:
        problems = self.config.problems()
        if problems:
            raise SendError(f"SMTP 설정이 모자랍니다 — {'; '.join(problems)}")
        if not message.to:
            raise SendError("받는 사람이 없습니다")
        built = self._build(message)
        try:
            with self._open() as smtp:
                if self.config.security == SECURITY_STARTTLS:
                    smtp.starttls(context=ssl.create_default_context())
                if self.config.username:
                    smtp.login(self.config.username, self.password)
                smtp.send_message(built)
        except (OSError, smtplib.SMTPException) as e:
            # **예외의 글을 싣지 않는다** — `SMTPRecipientsRefused`는 거부된 **주소**를 담고
            # 있고 그것은 업무 값이다 (원칙 6). 종류 이름만 남긴다.
            raise SendError(f"메일을 보내지 못했습니다 ({type(e).__name__})") from e
        return SendResult(ok=True, id=str(built["Message-ID"] or "") or None)

    # ── 속 ──

    def _open(self) -> Any:
        if self.connect is not None:
            return self.connect(self.config.host, self.config.real_port, self.config.timeout_s)
        if self.config.security == SECURITY_SSL:
            return smtplib.SMTP_SSL(
                self.config.host,
                self.config.real_port,
                timeout=self.config.timeout_s,
                context=ssl.create_default_context(),
            )
        return smtplib.SMTP(self.config.host, self.config.real_port, timeout=self.config.timeout_s)

    def _build(self, message: EmailMessage) -> MailMessage:
        """C14가 만든 메일 하나를 RFC 메시지로.

        **한글을 막지 않는다** — CLAUDE.md §5의 「헤더에 한글을 넣지 않는다」는 **HTTP** 이야기다
        (ASCII만 허용해 보내는 쪽이 요청을 거부한다). 메일 헤더에는 인코딩 규칙이 있고
        `email.message`가 제목·파일 이름을 알아서 인코딩한다.
        """
        built = MailMessage()
        built["From"] = self.config.sender
        built["To"] = ", ".join(message.to)
        if message.cc:
            built["Cc"] = ", ".join(message.cc)
        built["Subject"] = message.subject
        built["Message-ID"] = make_msgid()
        built.set_content(message.body)
        self._attach(built, message.attachments)
        return built

    def _attach(self, built: MailMessage, paths: Sequence[Path]) -> None:
        """첨부를 싣는다 — **경로는 엔진이 이미 걸렀다** (`Workspace.for_read`).

        여기서 더 보는 것은 **합계 상한** 하나다. 관문을 두 벌 만들지 않는다.
        """
        limit = int(self.config.max_attachment_mb * 1024 * 1024)
        total = 0
        for path in paths:
            try:
                total += path.stat().st_size
            except OSError as e:
                raise SendError(f"첨부를 읽지 못했습니다 ({type(e).__name__})") from e
            if total > limit:
                raise SendError(
                    f"첨부 합계가 상한을 넘었습니다 ({self.config.max_attachment_mb:g} MB)"
                )
            kind, _ = mimetypes.guess_type(path.name)
            major, _, minor = (kind or "application/octet-stream").partition("/")
            built.add_attachment(
                path.read_bytes(), maintype=major, subtype=minor or "octet-stream", filename=path.name
            )


@dataclass
class HttpWebhookSender:
    """웹훅 하나를 보낸다. **관문은 어댑터와 같은 함수**다 (`resolve_host`, C13 §4-3).

    베끼지 않는다 — 두 벌이면 한쪽만 고쳐진다. 다른 것은 **허용 호스트를 운영자가 적는 것**뿐이다.
    """

    config: WebhookConfig = field(default_factory=WebhookConfig)
    #: `httpx.Client` (시험이 끼운다).
    client: Any = None
    #: 호스트 → IP 목록 (시험이 끼운다).
    resolver: Any = None

    def send_webhook(self, request: WebhookRequest) -> SendResult:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        from chaeksas.core.http_adapter import getaddrinfo  # noqa: PLC0415 — 순환 피함

        if not self.config.allowed_hosts:
            raise SendError(
                "웹훅 허용 호스트가 비어 있습니다 — 보낼 곳을 설정에 적어야 보냅니다 (BUI-03 「보내기」)"
            )
        try:
            checked = resolve_host(
                request.url,
                allowed_hosts=self.config.allowed_hosts,
                allow_private_network=self.config.allow_private_network,
                lookup=self.resolver or getaddrinfo,
            )
        except HostRefused as e:
            raise SendError(f"그 주소로는 보내지 않습니다 — {e}") from e

        parts = urlsplit(request.url)
        # **IP로 접속하고 `Host`는 원래 이름**이다 (DNS 고정 — 어댑터와 같다).
        url = urlunsplit((checked.scheme, checked.netloc, parts.path, parts.query, ""))
        timeout = float(request.timeout_s or self.config.timeout_s)
        own = self.client is None
        client = self.client or httpx.Client(timeout=timeout, follow_redirects=False)
        try:
            status, text = self._send(client, url, request, host=checked.host, timeout=timeout)
        except httpx.HTTPError as e:
            raise SendError(f"웹훅을 보내지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()

        if status >= 400:
            # **전달되지 않았다** — 조용히 `ok: false`로 흘려보내지 않는다 (C14 §보내기의 태도).
            raise SendError(f"웹훅이 {status}를 돌려줬습니다")
        return SendResult(ok=True, status=status, text=text)

    def _send(
        self, client: Any, url: str, request: WebhookRequest, *, host: str, timeout: float
    ) -> tuple[int, str]:
        """한 번 왕복한다. **리다이렉트를 따라가지 않고** 크기 상한을 **읽는 동안** 본다."""
        limit = max(1, int(self.config.max_response_kb)) * 1024
        body = request.body
        text = isinstance(body, str)
        with client.stream(
            request.method.upper(),
            url,
            headers={"Host": host, "Content-Type": "text/plain" if text else "application/json"},
            content=str(body) if text else None,
            json=None if text else dict(body or {}),  # type: ignore[arg-type]
            extensions={"sni_hostname": host},
            follow_redirects=False,
            timeout=timeout,
        ) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise SendError(f"웹훅 응답이 {self.config.max_response_kb} KB를 넘었습니다")
                chunks.append(chunk)
            body = b"".join(chunks).decode("utf-8", "replace")
            return int(response.status_code), body[:MAX_RESPONSE_TEXT]


@dataclass
class PlatformSender:
    """제품용 보내기 어댑터 하나 — **PC와 서버가 같은 것을 쓴다** (ADR-0059).

    엔진이 보는 `Sender`는 이것이고, 안에서 메일·웹훅을 각자에게 넘긴다.
    """

    mail: SmtpSender = field(default_factory=SmtpSender)
    webhook: HttpWebhookSender = field(default_factory=HttpWebhookSender)

    def send_email(self, message: EmailMessage) -> SendResult:
        return self.mail.send_email(message)

    def send_webhook(self, request: WebhookRequest) -> SendResult:
        return self.webhook.send_webhook(request)


def make_sender(
    *,
    smtp: SmtpConfig | None = None,
    webhook: WebhookConfig | None = None,
    password: str = "",
) -> PlatformSender:
    """설정 한 벌로 보내기 어댑터를 짓는다 — **실행하는 쪽 둘이 같은 함수를 쓴다**.

    주지 않은 쪽은 **빈 설정**이라 그 태스크가 분명히 실패한다 (조용히 넘어가지 않는다).
    """
    return PlatformSender(
        mail=SmtpSender(config=smtp or SmtpConfig(), password=password),
        webhook=HttpWebhookSender(config=webhook or WebhookConfig()),
    )


__all__ = [
    "DEFAULT_ATTACHMENT_MB",
    "DEFAULT_PORTS",
    "DEFAULT_SMTP_TIMEOUT_S",
    "DEFAULT_WEBHOOK_RESPONSE_KB",
    "DEFAULT_WEBHOOK_TIMEOUT_S",
    "KNOWN_SECURITY",
    "MAX_RESPONSE_TEXT",
    "SECURITY_NONE",
    "SECURITY_SSL",
    "SECURITY_STARTTLS",
    "EmailMessage",
    "HttpWebhookSender",
    "NoSender",
    "PlatformSender",
    "RecordingSender",
    "SendError",
    "SendResult",
    "Sender",
    "SmtpConfig",
    "SmtpSender",
    "WebhookConfig",
    "WebhookRequest",
    "make_sender",
]

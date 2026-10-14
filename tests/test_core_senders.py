"""제품용 보내기 어댑터 — SMTP와 웹훅 ([ADR-0059](../docs/decisions/0059-sending-mail-and-webhooks.md)).

**진짜 소켓으로 본다.** 메일은 이 파일이 띄우는 **작은 SMTP 서버**가 받고(`smtplib`가 정말
말을 주고받는다), 웹훅은 127.0.0.1의 진짜 HTTP 서버로 간다 — 어댑터 시험(`test_core_http_adapter`)과
같은 결이다. 가짜로 바꿔 끼우면 「보내는 척」만 시험하게 된다.

여기서 지키는 것 넷.

- **설정이 없으면 보내지 않고 실패한다** (조용히 넘어가지 않는다 — C14 §보내기).
- **첨부 합계 상한**은 보내기 **전에** 걸린다 (서버가 거절하는 것보다 낫다).
- **실패 사유에 받는 사람·제목이 들어가지 않는다** (원칙 6).
- **웹훅 관문은 어댑터와 같은 함수**다 — 허용 호스트 밖·사설망·https 아님은 **나가지 않는다**.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from email import message_from_bytes
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from chaeksas.core.senders import (
    DEFAULT_PORTS,
    SECURITY_NONE,
    SECURITY_SSL,
    SECURITY_STARTTLS,
    EmailMessage,
    HttpWebhookSender,
    PlatformSender,
    SendError,
    SmtpConfig,
    SmtpSender,
    WebhookConfig,
    WebhookRequest,
    make_sender,
)

# ─────────────────────────── 작은 SMTP 서버 ───────────────────────────


class FakeSmtp(threading.Thread):
    """127.0.0.1에 뜨는 **아주 작은 SMTP 서버**. 받은 메시지를 통째로 담아 둔다.

    `aiosmtpd`를 들이지 않는다 — 시험 하나를 위해 의존성을 늘리지 않고, 표준 라이브러리의
    `smtpd`는 3.12에서 빠졌다. 그래서 `EHLO`·`MAIL`·`RCPT`·`DATA`·`QUIT`만 답한다.
    """

    def __init__(self, *, refuse: bool = False) -> None:
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = int(self.sock.getsockname()[1])
        self.received: list[bytes] = []
        self.recipients: list[str] = []
        self.refuse = refuse
        self._stop = False

    def run(self) -> None:  # pragma: no cover - 스레드
        while not self._stop:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            try:
                self._serve(client)
            except OSError:
                pass
            finally:
                client.close()

    def _serve(self, client: socket.socket) -> None:  # pragma: no cover - 스레드
        client.sendall(b"220 fake ESMTP\r\n")
        buffer = b""
        data_mode = False
        body = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                return
            buffer += chunk
            while b"\r\n" in buffer:
                line, buffer = buffer.split(b"\r\n", 1)
                if data_mode:
                    if line == b".":
                        data_mode = False
                        self.received.append(body)
                        body = b""
                        client.sendall(b"250 OK queued\r\n")
                    else:
                        body += line + b"\r\n"
                    continue
                upper = line.upper()
                if upper.startswith(b"EHLO") or upper.startswith(b"HELO"):
                    client.sendall(b"250-fake\r\n250 HELP\r\n")
                elif upper.startswith(b"MAIL"):
                    client.sendall(b"250 OK\r\n")
                elif upper.startswith(b"RCPT"):
                    if self.refuse:
                        # 거부 사유에 **주소가 들어 있다** — 그것이 밖으로 새지 않는지 본다.
                        client.sendall(b"550 no such user\r\n")
                    else:
                        self.recipients.append(line.decode("utf-8", "replace"))
                        client.sendall(b"250 OK\r\n")
                elif upper.startswith(b"DATA"):
                    data_mode = True
                    client.sendall(b"354 go ahead\r\n")
                elif upper.startswith(b"QUIT"):
                    client.sendall(b"221 bye\r\n")
                    return
                else:
                    client.sendall(b"250 OK\r\n")

    def close(self) -> None:
        self._stop = True
        self.sock.close()

    def parsed(self) -> Message:
        assert self.received, "받은 메일이 없다"
        return message_from_bytes(self.received[-1])


@pytest.fixture
def smtp() -> Iterator[FakeSmtp]:
    server = FakeSmtp()
    server.start()
    yield server
    server.close()


def config(server: FakeSmtp, **over: object) -> SmtpConfig:
    """그 서버로 보내는 설정. **암호화 없이** 간다 (시험 서버가 TLS를 모른다)."""
    base = {
        "host": "127.0.0.1",
        "port": server.port,
        "security": SECURITY_NONE,
        "sender": "bot@example.com",
    }
    return SmtpConfig(**{**base, **over})  # type: ignore[arg-type]


# ─────────────────────────── 메일 ───────────────────────────


def test_a_mail_really_goes_out(smtp: FakeSmtp) -> None:
    """받는 사람·제목·본문이 **진짜 SMTP로** 나간다."""
    sender = SmtpSender(config=config(smtp))
    found = sender.send_email(
        EmailMessage(to=("a@example.com", "b@example.com"), subject="보고", body="본문입니다")
    )

    assert found.ok and found.id, "Message-ID를 돌려준다 (C14 요약의 `id`)"
    message = smtp.parsed()
    assert message["To"] == "a@example.com, b@example.com"
    assert message["From"] == "bot@example.com"
    assert len(smtp.recipients) == 2


def test_the_subject_may_be_korean(smtp: FakeSmtp) -> None:
    """**메일 헤더의 한글은 막지 않는다** — CLAUDE.md §5의 그 규칙은 HTTP 이야기다.

    뭉뚱그리면 한국어 제목을 못 보낸다. 나갈 때는 인코딩되고 받는 쪽에서 되돌아온다.
    """
    SmtpSender(config=config(smtp)).send_email(
        EmailMessage(to=("a@example.com",), subject="[시험] 세금계산서 발행", body="안녕하세요")
    )
    from email.header import decode_header, make_header

    assert str(make_header(decode_header(smtp.parsed()["Subject"]))) == "[시험] 세금계산서 발행"


def test_an_attachment_rides_along(smtp: FakeSmtp, tmp_path: Path) -> None:
    """첨부는 **경로**로 온다 (엔진이 `Workspace.for_read`로 이미 걸렀다)."""
    report = tmp_path / "보고.md"
    report.write_text("# 보고\n", encoding="utf-8")
    SmtpSender(config=config(smtp)).send_email(
        EmailMessage(to=("a@example.com",), subject="보고", body="첨부 보냅니다", attachments=(report,))
    )
    names = [part.get_filename() for part in smtp.parsed().walk()]
    assert "보고.md" in names, f"첨부가 없다: {names}"


def test_too_big_an_attachment_fails_before_sending(smtp: FakeSmtp, tmp_path: Path) -> None:
    """합계 상한은 **보내기 전에** 걸린다 — 서버가 거절하는 것보다 낫다."""
    big = tmp_path / "big.bin"
    big.write_bytes(b"0" * 2048)
    sender = SmtpSender(config=config(smtp, max_attachment_mb=0.001))

    with pytest.raises(SendError, match="첨부 합계"):
        sender.send_email(EmailMessage(to=("a@example.com",), subject="큰 것", attachments=(big,)))
    assert smtp.received == [], "보내지 않았다"


def test_a_refusal_does_not_leak_the_address() -> None:
    """**실패 사유에 받는 사람이 들어가지 않는다** (원칙 6).

    `smtplib`의 `SMTPRecipientsRefused`는 거부된 **주소**를 담고 있다 — 그대로 실으면 실행
    기록·화면에 업무 값이 샌다. 종류 이름만 남긴다.
    """
    server = FakeSmtp(refuse=True)
    server.start()
    try:
        sender = SmtpSender(config=config(server))
        with pytest.raises(SendError) as caught:
            sender.send_email(EmailMessage(to=("secret@example.com",), subject="기밀 제목"))
    finally:
        server.close()
    said = str(caught.value)
    assert "SMTPRecipientsRefused" in said
    assert "secret@example.com" not in said and "기밀 제목" not in said


def test_no_config_means_it_says_so() -> None:
    """**설정이 없으면 보내지 않고 실패한다** — 조용히 넘어가지 않는다 (C14 §보내기)."""
    with pytest.raises(SendError, match="SMTP 주소가 비어"):
        SmtpSender().send_email(EmailMessage(to=("a@example.com",)))

    with pytest.raises(SendError, match="보내는 주소"):
        SmtpSender(config=SmtpConfig(host="smtp.example.com")).send_email(
            EmailMessage(to=("a@example.com",))
        )


def test_no_recipient_means_it_says_so(smtp: FakeSmtp) -> None:
    with pytest.raises(SendError, match="받는 사람이 없습니다"):
        SmtpSender(config=config(smtp)).send_email(EmailMessage(to=()))


def test_the_default_port_follows_the_security() -> None:
    """포트를 비우면 **보안에 맞는 기본**이다 — 화면이 「기본」이라고 보인다."""
    assert SmtpConfig(security=SECURITY_STARTTLS).real_port == DEFAULT_PORTS[SECURITY_STARTTLS]
    assert SmtpConfig(security=SECURITY_SSL).real_port == DEFAULT_PORTS[SECURITY_SSL]
    assert SmtpConfig(security=SECURITY_NONE).real_port == DEFAULT_PORTS[SECURITY_NONE]
    assert SmtpConfig(security=SECURITY_SSL, port=2525).real_port == 2525


def test_the_default_security_is_not_the_loose_one() -> None:
    """**기본을 느슨하게 두지 않는다** (ADR-0059 §1) — `none`은 사람이 골라야 한다."""
    assert SmtpConfig().security == SECURITY_STARTTLS


def test_an_unknown_security_is_refused() -> None:
    found = SmtpConfig(host="smtp.example.com", sender="a@example.com", security="아무거나")
    assert not found.configured
    assert any("모르는 보안" in one for one in found.problems())


def test_a_korean_recipient_address_fails_clearly(smtp: FakeSmtp) -> None:
    """**받는 사람 주소에 한글이 들어가면** 서버가 `SMTPUTF8`을 알려야 보낼 수 있다.

    시험 서버는 그것을 알리지 않으므로 `smtplib`가 **보내기 전에** 거절한다 — 그래도
    **사유에 주소가 들어가지 않는다**. (제목·본문의 한글은 늘 된다 — 위 시험이 본다.)
    """
    with pytest.raises(SendError) as caught:
        SmtpSender(config=config(smtp)).send_email(
            EmailMessage(to=("받는사람@example.com",), subject="x")
        )
    assert "받는사람@example.com" not in str(caught.value)
    assert smtp.received == [], "보내지 않았다"


class Recording:
    """`smtplib.SMTP` 자리에 끼우는 가짜 — **무엇을 불렀는지**만 담는다."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, host: str, port: int, timeout: float) -> Recording:
        self.calls.append(f"connect {host}:{port}")
        return self

    def __enter__(self) -> Recording:
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append("close")

    def starttls(self, context: object = None) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login {user}")

    def send_message(self, message: object) -> None:
        self.calls.append("send")


def test_it_logs_in_only_when_there_is_a_user() -> None:
    """사용자가 없으면 **로그인하지 않는다** — 비밀번호 없는 사내 중계기가 흔하다."""
    watching = Recording()
    SmtpSender(
        config=SmtpConfig(host="smtp.example.com", sender="bot@example.com", security=SECURITY_NONE),
        connect=watching,
    ).send_email(EmailMessage(to=("a@example.com",)))
    assert "send" in watching.calls
    assert not any(one.startswith("login") for one in watching.calls)


def test_starttls_is_called_when_the_security_says_so() -> None:
    """`starttls`를 고르면 **정말 건다** — 기본이 그것이다 (ADR-0059 §1)."""
    watching = Recording()
    SmtpSender(
        config=SmtpConfig(host="smtp.example.com", sender="bot@example.com", username="bot"),
        password="비밀",
        connect=watching,
    ).send_email(EmailMessage(to=("a@example.com",)))
    assert watching.calls[:3] == ["connect smtp.example.com:587", "starttls", "login bot"]


# ─────────────────────────── 웹훅 ───────────────────────────


class Receiver(BaseHTTPRequestHandler):
    """받은 웹훅을 담아 두는 작은 서버."""

    bodies: list[bytes] = []
    status = 200
    reply = b'{"ok": true}'

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 규약
        length = int(self.headers.get("Content-Length") or 0)
        Receiver.bodies.append(self.rfile.read(length))
        self.send_response(Receiver.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(Receiver.reply)))
        self.end_headers()
        self.wfile.write(Receiver.reply)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def receiver() -> Iterator[int]:
    Receiver.bodies = []
    Receiver.status = 200
    Receiver.reply = b'{"ok": true}'
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield int(server.server_address[1])
    server.shutdown()
    server.server_close()


def open_webhook(port: int, **over: object) -> HttpWebhookSender:
    """127.0.0.1로 보내는 어댑터.

    **`allow_private_network`는 설정에 없다** (ADR-0059 §2) — 시험만 켠다. 사설 주소를 막는
    규칙 자체는 아래 `test_a_private_address_is_refused`가 본다 (어댑터 시험과 같은 결).
    """
    base = {"allowed_hosts": ("127.0.0.1",), "allow_private_network": True}
    return HttpWebhookSender(config=WebhookConfig(**{**base, **over}))  # type: ignore[arg-type]


def test_a_webhook_really_goes_out(receiver: int) -> None:
    found = open_webhook(receiver).send_webhook(
        WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook", body={"주문": "PO-1"})
    )
    assert (found.ok, found.status) == (True, 200)
    assert b"PO-1" in Receiver.bodies[-1]


def test_an_empty_allow_list_sends_nowhere(receiver: int) -> None:
    """**기본은 닫힘이다** (ADR-0032와 같은 결) — 비면 아무 데도 보내지 않는다."""
    sender = HttpWebhookSender()
    with pytest.raises(SendError, match="허용 호스트가 비어"):
        sender.send_webhook(WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook"))
    assert Receiver.bodies == []


def test_a_host_outside_the_list_is_refused(receiver: int) -> None:
    sender = open_webhook(receiver, allowed_hosts=("hooks.example.com",))
    with pytest.raises(SendError, match="허용 호스트 밖"):
        sender.send_webhook(WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook"))
    assert Receiver.bodies == []


def test_a_private_address_is_refused(receiver: int) -> None:
    """**사설·루프백은 적어도 열리지 않는다** — 설정에 스위치가 없기 때문이다 (ADR-0059 §2)."""
    sender = HttpWebhookSender(config=WebhookConfig(allowed_hosts=("127.0.0.1",)))
    with pytest.raises(SendError, match="사설·루프백"):
        sender.send_webhook(WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook"))
    assert Receiver.bodies == []


def test_plain_http_outside_the_private_network_is_refused() -> None:
    """**https만 쓴다** — 관문은 어댑터와 같은 함수다 (C13 §4-3)."""
    sender = HttpWebhookSender(
        config=WebhookConfig(allowed_hosts=("example.com",)),
    )
    sender.resolver = lambda host: ["93.184.216.34"]  # 공개 IP로 푼 척
    with pytest.raises(SendError, match="https만"):
        sender.send_webhook(WebhookRequest(url="http://example.com/hook"))


def test_an_error_status_is_a_failure(receiver: int) -> None:
    """**4xx·5xx는 `SEND_FAILED`다** — 500을 돌려준 웹훅은 전달되지 않았다."""
    Receiver.status = 500
    with pytest.raises(SendError, match="500"):
        open_webhook(receiver).send_webhook(WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook"))


def test_a_huge_reply_is_cut_while_reading(receiver: int) -> None:
    """응답 크기는 **읽는 동안** 끊는다 (어댑터와 같다)."""
    Receiver.reply = b"x" * 4096
    sender = open_webhook(receiver, max_response_kb=1)
    with pytest.raises(SendError, match="KB를 넘었습니다"):
        sender.send_webhook(WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook"))


def test_a_text_body_goes_as_text(receiver: int) -> None:
    """`template:`은 **글자 그대로** 간다 (C14 §보내기)."""
    open_webhook(receiver).send_webhook(
        WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook", body="안녕하세요")
    )
    assert Receiver.bodies[-1].decode("utf-8") == "안녕하세요"


# ─────────────────────────── 한 벌 ───────────────────────────


def test_the_platform_sender_does_both(smtp: FakeSmtp, receiver: int) -> None:
    """엔진이 보는 `Sender` 하나가 메일·웹훅을 **각자에게** 넘긴다."""
    made = PlatformSender(
        mail=SmtpSender(config=config(smtp)),
        webhook=open_webhook(receiver),
    )
    made.send_email(EmailMessage(to=("a@example.com",), subject="x"))
    made.send_webhook(WebhookRequest(url=f"http://127.0.0.1:{receiver}/hook", body={"a": 1}))
    assert smtp.received and Receiver.bodies


def test_make_sender_without_settings_fails_clearly() -> None:
    """**주지 않으면 분명히 실패한다** — 조용히 넘어가지 않는다."""
    made = make_sender()
    with pytest.raises(SendError):
        made.send_email(EmailMessage(to=("a@example.com",)))
    with pytest.raises(SendError):
        made.send_webhook(WebhookRequest(url="https://hooks.example.com/x"))

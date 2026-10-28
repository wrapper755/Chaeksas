"""등록 요청과 승인 — 키는 Center가 만들어 봉해 내려 준다 (C4·C12 §등록 요청과 승인, C5 §등록 승인).

단일 원본: `docs/03-contracts/C4-bot-ui-center.md` 「등록 요청과 승인」,
[ADR-0092](../../../../../docs/decisions/0092-keys-are-issued-and-delivered-by-center.md).

설치하는 사람은 Center 주소만 넣는다. 현장이 키 쌍을 만들어 요청하고, 관리자가 **요청 코드**를
맞춰 보고 승인하면 Center가 키를 만들어 **요청의 공개키로 봉해** 둔다. 사람은 키를 보지 않는다.

이 모듈이 쥐는 것:

- **요청 코드** (`request_code`) — 공개키와 Center가 준 요청 id 둘로 정해진다. Center가 짓고
  현장이 **다시 계산해** 맞을 때만 띄운다 (가운데서 응답을 바꿔치면 어긋난다).
- **봉함** (`seal`·`open_sealed`) — X25519 + HKDF-SHA256 + ChaCha20-Poly1305. 승인으로 받는 키와
  키 회전이 같은 것을 쓴다.
- 오가는 모양 (요청 상태·콘솔이 보는 한 줄·결정).

Bot UI·서버 실행기의 요청 본문은 각자의 `RegisterRequest`에 `public_key`를 더한 것이라 그쪽
모듈(`bot_ui`·`server_runner`)에 있다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Annotated, Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp

#: 봉함 방식 — 지금은 이것 하나다 (C4 §봉함).
SEAL_ALG = "x25519-hkdf-sha256-chacha20poly1305"
HKDF_INFO = b"chaeksas-seal-v1"

#: 승인 대기 시간, 승인된 키를 `register`로 쓸 때까지의 시간 (C4).
PENDING_HOURS = 24
DELIVERY_HOURS = 24
#: 다음에 물을 때까지 (C4 `poll_after_s` 기본값).
POLL_AFTER_S = 10
#: 막는 것 (C4) — 같은 원격 주소에서 10분에 10건, 대기 중인 요청은 Center 전체에 200건.
RATE_WINDOW_S = 600
RATE_MAX = 10
QUEUE_MAX = 200
#: 키 회전 (C4 §키 회전) — 만료 14일 전부터 새 키를 싣는다. 회전을 받는 PC는 7일 전까지 새 키가
#: 오지 않았을 때만 BUI-05로 알린다.
ROTATE_BEFORE_DAYS = 14
ROTATE_NOTICE_DAYS = 7
#: 거절 사유 길이 (C5).
REASON_MAX = 200

#: 요청할 수 있는 종류 — 만드는 키 종류와 같다 (C7). Studio도 같은 길이다 (ADR-0093).
ENROLLMENT_TYPES = frozenset({"bot_ui", "server_runner", "studio", "consumer"})  # consumer = C15 일꾼
#: 알려진 상태 (열린 문자열).
KNOWN_ENROLLMENT_STATES = frozenset({"pending", "approved", "rejected", "expired"})

EnrollmentId = Annotated[str, Field(pattern=r"^enr_[0-9a-f]{32}$")]
#: X25519 공개키 — 32바이트를 덧붙임 없는 base64url로 (43자).
PublicKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]
RequestCode = Annotated[str, Field(pattern=r"^[A-Z2-7]{4}-[A-Z2-7]{4}$")]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SealError(ValueError):
    """봉함을 열 수 없다 — 다른 키로 봉했거나 손을 탔다."""


def new_keypair() -> tuple[str, str]:
    """현장이 만드는 키 쌍 — `(비밀 반쪽, 공개 반쪽)`, 둘 다 base64url.

    **비밀 반쪽은 OS 비밀 저장소에만** 둔다 (CLAUDE.md §5).
    """
    private = X25519PrivateKey.generate()
    raw = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return _b64(raw), public_of(_b64(raw))


def public_of(private_key: str) -> str:
    """비밀 반쪽 → 공개 반쪽."""
    private = X25519PrivateKey.from_private_bytes(_unb64(private_key))
    return _b64(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def valid_public_key(text: str) -> bool:
    """X25519 공개키로 읽히나 (C4 422 `public_key_invalid`)."""
    try:
        raw = _unb64(text)
    except (binascii.Error, ValueError):
        return False
    if len(raw) != 32 or _b64(raw) != text:
        return False
    try:
        X25519PublicKey.from_public_bytes(raw)
    except ValueError:
        return False
    return True


def request_code(public_key: str, enrollment_id: str) -> str:
    """요청 코드 `XXXX-XXXX` (C4).

    `SHA-256(공개키 32바이트 ‖ enrollment_id)`를 base32(RFC 4648, 대문자, 덧붙임 없음)로 적은
    앞 8자다. **사람이 지어 맞출 수 없다** — 공개키와 Center가 준 id가 함께 정한다.
    """
    digest = hashlib.sha256(_unb64(public_key) + enrollment_id.encode("ascii")).digest()
    text = base64.b32encode(digest).decode("ascii").rstrip("=")[:8]
    return f"{text[:4]}-{text[4:]}"


class Sealed(ContractModel):
    """받는 쪽 공개키로만 열리는 한 덩이 (C4 §봉함)."""

    alg: str = SEAL_ALG
    epk: str
    nonce: str
    ciphertext: str


def _derive(shared: bytes, salt: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt.encode("ascii"), info=HKDF_INFO).derive(shared)


def seal(public_key: str, plaintext: str, *, salt: str) -> Sealed:
    """`public_key`의 주인만 열 수 있게 봉한다. 봉할 때마다 X25519 키를 새로 만든다.

    `salt`는 승인이면 `enrollment_id`, 회전이면 그 기계의 id다 (C4) — 다른 자리의 봉함을
    가져와 끼워도 열리지 않는다.
    """
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(_unb64(public_key)))
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(_derive(shared, salt)).encrypt(nonce, plaintext.encode("utf-8"), None)
    epk = ephemeral.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return Sealed(epk=_b64(epk), nonce=_b64(nonce), ciphertext=_b64(ciphertext))


def open_sealed(private_key: str, sealed: Sealed, *, salt: str) -> str:
    """봉함을 연다. 열 수 없으면 `SealError` — **받은 것을 그대로 쓰지 않는다.**"""
    if sealed.alg != SEAL_ALG:
        raise SealError(f"모르는 봉함 방식이다: {sealed.alg}")
    try:
        private = X25519PrivateKey.from_private_bytes(_unb64(private_key))
        shared = private.exchange(X25519PublicKey.from_public_bytes(_unb64(sealed.epk)))
        plain = ChaCha20Poly1305(_derive(shared, salt)).decrypt(
            _unb64(sealed.nonce), _unb64(sealed.ciphertext), None
        )
    except Exception as e:  # noqa: BLE001 — 깨진 칸·틀린 키·손 탄 본문이 모두 「못 연다」다
        raise SealError("봉함을 열 수 없다 — 이 PC의 키로 봉한 것이 아니거나 손을 탔다") from e
    return plain.decode("utf-8")


class StudioVersions(ContractModel):
    """Studio의 판 (C5 §Studio 등록 요청과 승인)."""

    studio: str
    core: str


class StudioEnrollRequest(SchemaVersioned):
    """`POST /api/v1/studio/enroll` — Studio의 등록 요청 (C5 §Studio 등록 요청과 승인, ADR-0093).

    Bot UI의 `EnrollRequest`와 같은 결이다 — 등록(`register`)이 없는 Studio라 그 칸만 따로 둔다.
    """

    machine_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    name: str
    os: str
    versions: StudioVersions
    public_key: PublicKey


class EnrollStatus(ContractModel):
    """`POST …/enroll`의 응답이자 `GET …/enroll/{id}`의 응답 (C4 `EnrollResponse`·`EnrollStatus`)."""

    enrollment_id: EnrollmentId
    state: str  # 열린 문자열 (KNOWN_ENROLLMENT_STATES)
    code: RequestCode
    poll_after_s: int = POLL_AFTER_S
    expires_at: Timestamp
    #: `approved`일 때만 — 봉한 Center API 키.
    sealed_key: Sealed | None = None
    key_expires_at: Timestamp | None = None
    #: `approved`일 때만. 승인할 때 붙인 키 이름 — Studio는 이것이 「누가」라 보여 준다 (ADR-0093).
    key_name: str | None = None
    #: `rejected`일 때 관리자가 적은 사유.
    reason: str | None = None


class RotatedKey(ContractModel):
    """하트비트 답의 새 키 (C4 §키 회전). 새 키로 첫 요청이 올 때까지 주기마다 실린다."""

    sealed_key: Sealed
    expires_at: Timestamp | None = None


class ExistingHost(ContractModel):
    """그 기계가 이미 등록돼 있으면 — 승인하면 이 자리를 이어받고 그 키는 폐기된다 (C5)."""

    id: str
    name: str
    key_prefix: str | None = None
    last_seen: Timestamp | None = None


class EnrollmentInfo(ContractModel):
    """`GET /enrollments`의 한 줄 (C5 §등록 승인, CON-03·CON-12 「승인 대기」)."""

    enrollment_id: EnrollmentId
    type: str
    code: RequestCode
    name: str
    os: str
    versions: dict[str, Any] = Field(default_factory=dict)
    machine_id_prefix: str
    remote_addr: str | None = None
    requested_at: Timestamp
    expires_at: Timestamp
    state: str  # 열린 문자열 (KNOWN_ENROLLMENT_STATES)
    existing: ExistingHost | None = None
    decided_by: str | None = None
    decided_at: Timestamp | None = None
    reason: str | None = None
    key_id: str | None = None


class EnrollmentApproveRequest(ContractModel):
    """`POST /enrollments/{id}/approve` — `name`을 비우면 요청의 이름을 쓴다."""

    name: str | None = None
    #: 일꾼(C15)만 — 승인할 토픽. 비우면 요청한 그대로, 적으면 **요청한 것 안에서만** 줄인다.
    topics: list[str] | None = None


class EnrollmentRejectRequest(ContractModel):
    """`POST /enrollments/{id}/reject` — 사유는 요청한 쪽에 그대로 보인다."""

    reason: str | None = Field(default=None, max_length=REASON_MAX)


class EnrollmentDecision(ContractModel):
    """승인 응답 (C5). `host_id`는 이어받았으면 그 id, 새 자리면 첫 `register`가 만들 때까지 `None`."""

    key_id: str
    host_id: str | None = None
    replaced_key_id: str | None = None


__all__ = [
    "DELIVERY_HOURS",
    "ENROLLMENT_TYPES",
    "KNOWN_ENROLLMENT_STATES",
    "PENDING_HOURS",
    "POLL_AFTER_S",
    "QUEUE_MAX",
    "RATE_MAX",
    "RATE_WINDOW_S",
    "REASON_MAX",
    "ROTATE_BEFORE_DAYS",
    "ROTATE_NOTICE_DAYS",
    "SEAL_ALG",
    "EnrollStatus",
    "EnrollmentApproveRequest",
    "EnrollmentDecision",
    "EnrollmentId",
    "EnrollmentInfo",
    "EnrollmentRejectRequest",
    "ExistingHost",
    "PublicKey",
    "RequestCode",
    "RotatedKey",
    "SealError",
    "StudioEnrollRequest",
    "StudioVersions",
    "Sealed",
    "new_keypair",
    "open_sealed",
    "public_of",
    "request_code",
    "seal",
    "valid_public_key",
]

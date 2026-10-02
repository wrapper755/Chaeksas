"""C2. 서명 봉투 — Admin 개인키 서명으로만 할 수 있는 일.

단일 원본: `docs/03-contracts/C2-signing-envelope.md`.

관리자 토큰이나 Center API 키가 새도 **배포를 만들거나 서명 키를 바꿔치기할 수 없게** 하는
마지막 관문이다. Center와 실행하는 쪽은 공개키만 가진다.

`payload`는 **받은 그대로의 `dict`로 둔다.** 모델로 바꿔 다시 직렬화하면 모르는 필드나 표기가
흔들려 서명이 깨질 수 있다 (C2 "바이트 보존"). 타입이 필요하면 `parse_claim()`으로 따로 읽는다.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Sha256, Timestamp, Violation
from chaeksas.contracts.hashing import FloatInPayloadError, canonical_json, sha256_hex

#: 서버 배포에서 "Center가 관리하는 모든 서버 실행기".
TARGET_ANY = "*"

#: 서버 배포의 기본 동시 실행 상한 (C2 `deployment` 필드 규칙).
DEFAULT_MAX_CONCURRENCY = 5

KeyId = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
"""Admin 공개키 raw 32바이트의 SHA-256 앞 16 hex."""

KNOWN_CLAIM_KINDS = frozenset(
    {
        "package",
        "package_revoke",
        "deployment",
        "revoke",
        "extension",
        "extension_revoke",
        "admin_key",
        "admin_key_revoke",
    }
)


class AdminKey(ContractModel):
    """Admin 공개키 하나. 철회된 키도 `revoked_at`과 함께 내려온다 (C4로 배포된다)."""

    key_id: KeyId
    public_key: str  # raw 32바이트 base64
    label: str | None = None
    revoked_at: Timestamp | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def raw(self) -> bytes:
        return base64.b64decode(self.public_key, validate=True)


def key_id_for(public_key: bytes) -> str:
    """공개키 raw 32바이트 → `key_id` (SHA-256 앞 16 hex)."""
    if len(public_key) != 32:
        raise ValueError(f"Ed25519 공개키는 raw 32바이트다: {len(public_key)}바이트")
    return sha256_hex(public_key)[:16]


class DeploymentTarget(ContractModel):
    """`{type: "bot_ui" | "server_runner", id}`. 서버 배포는 `id`에 `"*"`를 쓸 수 있다."""

    type: str  # 열린 문자열 (알려진 값: bot_ui, server_runner)
    id: str

    def matches(self, *, kind: str, id: str) -> bool:
        if self.type != kind:
            return False
        return self.id == id or (self.type == "server_runner" and self.id == TARGET_ANY)


class DeploymentClaim(ContractModel):
    """`kind: "deployment"` — 배포."""

    kind: Literal["deployment"]
    deployment_id: str
    target: DeploymentTarget
    bpm_process_id: str
    version: str
    content_hash: Sha256
    not_before: Timestamp | None = None
    expires_at: Timestamp | None = None
    max_concurrency: int | None = None  # 서버 배포에만. 없으면 DEFAULT_MAX_CONCURRENCY


class PackageClaim(ContractModel):
    """`kind: "package"` — 패키지 승인."""

    kind: Literal["package"]
    id: str
    version: str
    content_hash: Sha256


class ExtensionClaim(ContractModel):
    """`kind: "extension"` — 외부 확장 정의 승인 (C13).

    정의가 서비스 앱 키를 어느 주소로 보낼지 정하므로 배포와 같은 관문을 둔다.
    `definition_hash`는 `canonical_json(정의)`의 해시다 (`contracts.extension.definition_hash`).
    """

    kind: Literal["extension"]
    id: str
    version: str
    definition_hash: Sha256


class AdminKeyClaim(ContractModel):
    """`kind: "admin_key"` — Admin 공개키 추가."""

    kind: Literal["admin_key"]
    key_id: KeyId
    public_key: str
    label: str | None = None


class RevokeClaim(ContractModel):
    """철회 claim들(`revoke`·`package_revoke`·`extension_revoke`·`admin_key_revoke`)의 공통 모양."""

    kind: str
    reason: str
    revoked_at: Timestamp


class Envelope(SchemaVersioned):
    """서명 봉투. `payload`는 **받은 그대로** 둔다."""

    payload: dict[str, Any]
    key_id: KeyId
    alg: Literal["ed25519"]
    sig: str  # base64
    signed_at: Timestamp

    @property
    def kind(self) -> str:
        """`payload.kind` (없으면 빈 문자열)."""
        kind = self.payload.get("kind", "")
        return kind if isinstance(kind, str) else ""

    def signing_input(self) -> bytes:
        """서명 대상 — `sha256(canonical_json(payload))`의 **바이트 32개**."""
        return bytes.fromhex(sha256_hex(canonical_json(self.payload)))


def parse_claim(envelope: Envelope) -> DeploymentClaim | PackageClaim | ExtensionClaim | AdminKeyClaim | RevokeClaim:
    """`payload`를 종류에 맞는 모델로 읽는다 (검증과 별개로, 값을 쓰려고).

    모르는 종류면 `ValueError`. 검증은 `verify()`가 한다.
    """
    kind = envelope.kind
    if kind == "deployment":
        return DeploymentClaim.model_validate(envelope.payload)
    if kind == "package":
        return PackageClaim.model_validate(envelope.payload)
    if kind == "extension":
        return ExtensionClaim.model_validate(envelope.payload)
    if kind == "admin_key":
        return AdminKeyClaim.model_validate(envelope.payload)
    if kind.endswith("_revoke") or kind == "revoke":
        return RevokeClaim.model_validate(envelope.payload)
    raise ValueError(f"모르는 claim 종류: {kind!r}")


def sign(payload: dict[str, Any], private_key: Ed25519PrivateKey, *, signed_at: str) -> Envelope:
    """Admin이 봉투를 만든다 (`sig = base64(Ed25519(sha256(canonical_json(payload))))`).

    `payload`에 실수가 있으면 `FloatInPayloadError` — 서명 전에 막는다.
    """
    digest = bytes.fromhex(sha256_hex(canonical_json(payload)))
    public = private_key.public_key().public_bytes_raw()
    return Envelope(
        schema=Envelope.SCHEMA,
        payload=payload,
        key_id=key_id_for(public),
        alg="ed25519",
        sig=base64.b64encode(private_key.sign(digest)).decode("ascii"),
        signed_at=signed_at,
    )


def _find_key(key_id: str, keys: Sequence[AdminKey]) -> AdminKey | None:
    return next((k for k in keys if k.key_id == key_id), None)


def verify(
    envelope: Envelope,
    *,
    keys: Sequence[AdminKey],
    expect_kind: str | None = None,
) -> list[Violation]:
    """V1~V4 — **모두가** 하는 검증. 위반 목록을 돌려준다 (비어 있으면 통과).

    - V1 `alg`가 `ed25519`다 (`unsupported_alg`)
    - V2 `key_id`가 알려져 있고 철회되지 않았다 (`unknown_key` / `revoked_key`)
    - V3 서명이 `canonical_json(payload)`와 맞는다 (`bad_signature`)
    - V4 기대한 `kind`다 (`wrong_kind`)

    시간·대상·해시 검증(V5~V8)은 역할에 따라 다르므로 아래 함수들이 한다.
    """
    out: list[Violation] = []

    # V1 — 모델이 Literal로 막지만, 다른 경로로 들어온 값도 코드로 잡는다.
    if envelope.alg != "ed25519":
        return [Violation(rule="V1", code="unsupported_alg", message=f"서명 알고리즘 {envelope.alg}")]

    # V4 — 기대한 종류인가.
    if expect_kind is not None and envelope.kind != expect_kind:
        out.append(
            Violation(rule="V4", code="wrong_kind", message=f"{expect_kind}를 기대했는데 {envelope.kind or '없음'}")
        )

    # V2 — 아는 키이고 철회되지 않았나.
    key = _find_key(envelope.key_id, keys)
    if key is None:
        out.append(Violation(rule="V2", code="unknown_key", message=f"모르는 서명 키 {envelope.key_id}"))
        return out  # 키가 없으면 서명을 확인할 수 없다
    if key.revoked:
        out.append(Violation(rule="V2", code="revoked_key", message=f"철회된 서명 키 {envelope.key_id}"))

    # V3 — 서명이 맞나.
    try:
        digest = envelope.signing_input()
    except FloatInPayloadError as e:
        return [*out, Violation(rule="V3", code="float_in_payload", message=str(e))]
    try:
        Ed25519PublicKey.from_public_bytes(key.raw()).verify(base64.b64decode(envelope.sig, validate=True), digest)
    except (InvalidSignature, ValueError, binascii.Error):
        out.append(Violation(rule="V3", code="bad_signature", message="서명이 payload와 맞지 않는다"))
    return out


def verify_time(envelope: Envelope, *, now: str, check_not_before: bool) -> list[Violation]:
    """V5 — 배포 봉투의 시간 창.

    - V5a `expires_at`이 지나지 않았다 (`expired`) — **모두** 검사한다.
    - V5b 지금이 `not_before` 이후다 (`not_yet`) — **실행하는 쪽만**, 적용할 때.
      Center는 예약 배포를 받아 두므로 `check_not_before=False`로 부른다.
    """
    from datetime import datetime

    if envelope.kind != "deployment":
        return []
    out = []
    at = datetime.fromisoformat(now)
    expires = envelope.payload.get("expires_at")
    if isinstance(expires, str) and datetime.fromisoformat(expires) < at:
        out.append(Violation(rule="V5a", code="expired", message=f"배포가 {expires}에 만료되었다"))
    not_before = envelope.payload.get("not_before")
    if check_not_before and isinstance(not_before, str) and at < datetime.fromisoformat(not_before):
        out.append(Violation(rule="V5b", code="not_yet", message=f"{not_before} 이후에 적용한다"))
    return out


def verify_target(envelope: Envelope, *, runner_kind: str, runner_id: str) -> list[Violation]:
    """V6 — 이 배포가 나에게 온 것인가 (실행하는 쪽만).

    `runner_kind`는 `bot_ui` 또는 `server_runner`, `runner_id`는 자기 id.
    서버 실행기 대상의 `"*"`는 모든 서버 실행기와 맞는다.
    """
    if envelope.kind != "deployment":
        return []
    target = DeploymentTarget.model_validate(envelope.payload.get("target", {}))
    if target.matches(kind=runner_kind, id=runner_id):
        return []
    return [
        Violation(
            rule="V6",
            code="wrong_target",
            message=f"{target.type}/{target.id}에게 온 배포다 (나는 {runner_kind}/{runner_id})",
        )
    ]


def verify_package(
    envelope: Envelope,
    *,
    package_hash: str,
    package_signature: Envelope | None,
    keys: Sequence[AdminKey],
) -> list[Violation]:
    """V7 — 받은 패키지가 봉투와 같고, 승인 서명도 통과하나 (실행하는 쪽만).

    - 실제 `content_hash`가 배포 봉투의 것과 같다 (`hash_mismatch`)
    - 패키지 `SIGNATURE`(package claim)가 V1~V3을 통과한다 (`unsigned_package`)
    """
    out = []
    expected = envelope.payload.get("content_hash")
    if expected != package_hash:
        out.append(
            Violation(
                rule="V7",
                code="hash_mismatch",
                message=f"패키지 해시가 다르다 (봉투 {expected}, 실제 {package_hash})",
            )
        )
    if package_signature is None:
        out.append(Violation(rule="V7", code="unsigned_package", message="패키지에 승인 서명(SIGNATURE)이 없다"))
        return out
    inner = verify(package_signature, keys=keys, expect_kind="package")
    if inner:
        out.append(
            Violation(
                rule="V7",
                code="unsigned_package",
                message="패키지 승인 서명이 검증을 통과하지 못했다",
                items=[str(v) for v in inner],
            )
        )
    return out


def verify_admin_key_addition(envelope: Envelope, *, keys: Sequence[AdminKey]) -> list[Violation]:
    """V8 — Admin 키 추가는 **다른** 키가 서명해야 한다 (Center).

    자기 자신으로 서명한 키를 받으면 아무 키나 스스로를 등록할 수 있게 된다.
    """
    out = verify(envelope, keys=keys, expect_kind="admin_key")
    added = envelope.payload.get("key_id")
    if isinstance(added, str) and added == envelope.key_id:
        out.append(
            Violation(rule="V8", code="self_signed_key", message="추가하려는 키가 자기 자신으로 서명되었다")
        )
    return out

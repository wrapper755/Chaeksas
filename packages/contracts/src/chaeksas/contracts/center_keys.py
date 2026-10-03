"""C7. Center API 키 관리 (CON-11).

단일 원본: `docs/03-contracts/C7-resources-center-keys.md` 「Center API 키 관리」.

키 **원문은 발급 응답에 한 번만** 실린다. Center는 해시만 저장하고, 그 뒤로는 앞자리
(`prefix`)만 보인다. 키가 그 Bot UI의 신원이므로(ADR-0013) 다른 PC에서 쓰면 409다 (C4).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated

from pydantic import Field

from chaeksas.contracts._base import ContractModel, Timestamp, Violation

#: 키 원문 — `chk_ctr_` + 무작위 40자. 화면에는 앞자리 16자만 보인다.
KEY_PREFIX = "chk_ctr_"
KEY_RANDOM_LEN = 40
PREFIX_LEN = 16

#: 기본 만료는 1년. 만료 14일 전부터 CON-11과 그 Bot UI 알림(BUI-05)에 보인다.
DEFAULT_EXPIRY_DAYS = 365
EXPIRY_WARNING_DAYS = 14

#: `type`은 열린 문자열이지만 Center는 이 넷만 발급한다.
ISSUABLE_KEY_TYPES = frozenset({"bot_ui", "studio", "server_runner", "integration"})
KNOWN_KEY_STATES = frozenset({"active", "expired", "revoked"})

KeyId = Annotated[str, Field(pattern=r"^ck_[0-9a-f]{8}$")]
KeyRaw = Annotated[str, Field(pattern=rf"^{KEY_PREFIX}[A-Za-z0-9_-]{{{KEY_RANDOM_LEN}}}$")]


def prefix_of(key: str) -> str:
    """키 원문 → 화면에 보이는 앞자리 (`chk_ctr_` + 무작위 8자)."""
    return key[:PREFIX_LEN]


#: 키 원문의 모양. `KeyRaw`와 같은 패턴이다 (두 곳에 적지 않는다).
KEY_RE = re.compile(rf"^{KEY_PREFIX}[A-Za-z0-9_-]{{{KEY_RANDOM_LEN}}}$")


def looks_like_key(raw: str) -> bool:
    """붙여 넣은 값이 Center API 키 모양인가.

    **키를 확인하는 것이 아니다** — 받는 쪽만 진짜를 안다. 다른 것을 붙여 넣었을 때(명령 한 줄,
    따옴표가 붙은 값) 등록이 401로만 실패해 이유를 알 수 없는 일을 막으려는 것이다 (이슈 #3).
    """
    return bool(KEY_RE.fullmatch(raw.strip()))


def key_state(*, now: str, expires_at: str | None = None, revoked_at: str | None = None) -> str:
    """지금 이 키의 상태. 폐기가 만료보다 앞선다."""
    if revoked_at is not None:
        return "revoked"
    if expires_at is not None and datetime.fromisoformat(expires_at) <= datetime.fromisoformat(now):
        return "expired"
    return "active"


def expires_soon(*, now: str, expires_at: str | None, within_days: int = EXPIRY_WARNING_DAYS) -> bool:
    """만료가 가까웠나 (이미 만료된 것은 `False` — 그건 만료 상태로 보인다)."""
    if expires_at is None:
        return False
    at = datetime.fromisoformat(now)
    until = datetime.fromisoformat(expires_at)
    return at < until <= at + timedelta(days=within_days)


class BoundTo(ContractModel):
    """키가 묶인 곳. Bot UI용·서버 실행기용 키는 처음 등록한 PC에 묶인다 (C4)."""

    type: str
    id: str
    name: str | None = None
    machine_name: str | None = None
    first_seen: Timestamp | None = None


class CenterKeyCreateRequest(ContractModel):
    """`POST /center-keys` — 관리자 토큰으로만."""

    name: str
    type: str  # ISSUABLE_KEY_TYPES
    expires_at: Timestamp | None = None  # 없으면 Center가 DEFAULT_EXPIRY_DAYS 뒤로 정한다


class CenterKeyInfo(ContractModel):
    """`GET /center-keys`의 한 줄. **원문은 들어가지 않는다.**"""

    key_id: KeyId
    name: str
    type: str
    prefix: str
    state: str  # KNOWN_KEY_STATES
    created_at: Timestamp
    bound_to: BoundTo | None = None
    expires_at: Timestamp | None = None
    last_used_at: Timestamp | None = None
    revoked_at: Timestamp | None = None


class CenterKeyCreated(CenterKeyInfo):
    """발급 응답 — 여기에만 원문 `key`가 실린다. 다시 볼 수 없다.

    받는 쪽(운영자)은 이 값을 Bot UI·Studio 설정이나 OS 비밀 저장소에 넣는다.
    **기록·로그에 남기지 않는다.**
    """

    key: KeyRaw


def validate_create(req: CenterKeyCreateRequest) -> list[Violation]:
    """발급 요청에서 거부할 것. 알려진 종류가 아니면 422 `key_type_unknown`."""
    if req.type not in ISSUABLE_KEY_TYPES:
        return [
            Violation(
                rule="C7",
                code="key_type_unknown",
                message=f"발급할 수 있는 키 종류가 아니다: {req.type}",
                items=sorted(ISSUABLE_KEY_TYPES),
            )
        ]
    return []

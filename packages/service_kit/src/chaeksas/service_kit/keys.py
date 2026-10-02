"""서비스 앱 API 키 발급·검증 (C11).

**키는 앱이 스스로 발급하고 스스로 검증한다** (ADR-0013). Center는 서비스 앱 키를 모른다.
원문은 발급할 때 한 번만 돌려주고, 앱은 **해시만** 저장한다.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable, Sequence

from chaeksas.contracts.service_app import (
    KEY_PREFIX,
    KEY_RANDOM_LEN,
    MODE_DETERMINISTIC,
    ServiceAppKey,
    key_state,
    prefix_of,
)

#: `secrets.token_urlsafe`는 길이를 정확히 맞추기 어려워 알파벳에서 직접 고른다.
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"


def generate_key() -> str:
    """새 키 원문 (`chk_svc_` + 무작위 40자). **이 값은 다시 볼 수 없다.**"""
    return KEY_PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(KEY_RANDOM_LEN))


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue(
    name: str,
    *,
    allowed_operations: Sequence[str] = ("*",),
    allowed_modes: Sequence[str] = (MODE_DETERMINISTIC,),
    extra_scopes: Sequence[str] = (),
    created_at: str | None = None,
    expires_at: str | None = None,
) -> tuple[str, ServiceAppKey]:
    """키를 발급한다. `(원문, 저장할 레코드)`.

    원문은 호출한 쪽이 한 번 보여 주고 버린다. 기록·로그에는 `prefix`만 남긴다.
    기본 권한은 **결정 수행만**이다 — 운영 키가 자율 수행을 하지 못하게 (CLAUDE.md §5).
    """
    raw = generate_key()
    record = ServiceAppKey(
        name=name,
        hash=hash_key(raw),
        prefix=prefix_of(raw),
        allowed_operations=list(allowed_operations),
        allowed_modes=list(allowed_modes),
        extra_scopes=list(extra_scopes),
        created_at=created_at,
        expires_at=expires_at,
    )
    return raw, record


def find_key(raw: str, keys: Iterable[ServiceAppKey]) -> ServiceAppKey | None:
    """원문에 맞는 레코드. 해시를 상수 시간으로 비교한다.

    폐기·만료된 키도 **찾아서 돌려준다** — 「모르는 키(401)」와 「폐기된 키(403)」를
    구분해 알려야 하기 때문이다 (C11 오류 표).
    """
    digest = hash_key(raw)
    for key in keys:
        if secrets.compare_digest(key.hash, digest):
            return key
    return None


__all__ = ["find_key", "generate_key", "hash_key", "issue", "key_state", "prefix_of"]

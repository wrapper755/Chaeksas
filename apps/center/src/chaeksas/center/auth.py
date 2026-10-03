"""인증 — 누가 부르는가 (C5 「권한표」).

| 부르는 쪽 | 토큰 | 할 수 있는 것 |
| --- | --- | --- |
| 콘솔 「보기 전용」 | 읽기 토큰 | **GET만** |
| 콘솔 「관리자」·Admin | 관리자 토큰 | 쓰기 전부 (서명이 필요한 것은 봉투도 함께) |
| Bot UI·Studio·서버 실행기 | Center API 키 (종류별) | 자기 일만 |

**행위자 이름은 본문에서 받지 않는다** (C5). 키로 부르면 키 이름, 콘솔에서 부르면 BFF가 실어
보내는 `X-CHK-Actor` 헤더를 쓴다 — 그 헤더는 **관리자·읽기 토큰으로 부를 때만** 믿는다.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Request

from chaeksas.center import keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso

ACTOR_HEADER = "X-CHK-Actor"


@dataclass(frozen=True)
class Caller:
    """부르는 쪽. `kind`는 `admin`·`read`·`key` 중 하나다."""

    kind: str
    actor: str
    key: keys.KeyRecord | None = None

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def _console_actor(request: Request, *, fallback: str) -> str:
    """콘솔이 보낸 사용자 이름. 없으면 토큰 이름을 쓴다."""
    return request.headers.get(ACTOR_HEADER, "").strip() or fallback


def caller(request: Request, store: Store, *, admin_token: str | None, read_token: str | None) -> Caller:
    """토큰·키를 보고 부르는 쪽을 정한다. 아무것도 맞지 않으면 401."""
    token = bearer(request)
    if token is None:
        raise ApiError(401, "token_missing", "인증 토큰이 없다")

    # 토큰이 비어 있으면(설정하지 않았으면) 그 권한으로는 부를 수 없다.
    if admin_token and hmac.compare_digest(token, admin_token):
        return Caller(kind="admin", actor=_console_actor(request, fallback="관리자"))
    if read_token and hmac.compare_digest(token, read_token):
        return Caller(kind="read", actor=_console_actor(request, fallback="보기 전용"))

    record = keys.find(store, token)
    if record is None:
        raise ApiError(401, "key_invalid", "모르는 토큰이다")
    state = record.state(now=now_iso())
    if state != "active":
        raise ApiError(403, f"key_{state}", f"키 「{record.name}」은 {state} 상태다")
    keys.touch(store, record.key_id)
    # 키로 부를 때는 X-CHK-Actor를 믿지 않는다 (C5).
    return Caller(kind="key", actor=record.name, key=record)


def require_admin(found: Caller) -> Caller:
    if not found.is_admin:
        raise ApiError(403, "admin_only", "관리자 토큰이 필요하다")
    return found


def require_read(found: Caller) -> Caller:
    """GET에 필요한 권한 — 읽기·관리자 토큰, 또는 Center API 키."""
    if found.kind in ("admin", "read", "key"):
        return found
    raise ApiError(403, "forbidden", "읽을 권한이 없다")  # pragma: no cover - 방어


def require_key_type(found: Caller, wanted: str) -> keys.KeyRecord:
    """그 종류의 Center API 키로 불렀는가 (C4 — Bot UI용 키만 받는다)."""
    if found.key is None:
        raise ApiError(403, "wrong_key_type", f"{wanted} 종류의 Center API 키로 불러야 한다")
    if found.key.type != wanted:
        raise ApiError(
            403, "wrong_key_type", f"키 종류가 {found.key.type}이다 ({wanted} 키가 필요하다)"
        )
    return found.key

"""Center API 키 — 발급·검증·묶기 (C7, ADR-0013).

세 가지를 지킨다.

1. **원문은 저장하지 않는다.** 해시만 두고, 발급 응답에 **한 번만** 원문을 싣는다 (CON-11).
2. **키가 신원이다.** PC 실행기는 `bot_ui_id`를 보내지 않는다 — 키로 누구인지 정한다 (C4).
3. **키는 처음 등록한 PC에 묶인다.** 다른 PC에서 같은 키를 쓰면 409 — 키가 새어도 다른
   PC 실행기를 사칭할 수 없다. 운영자가 CON-11에서 묶음을 풀 수 있다.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.center_keys import (
    KEY_PREFIX,
    KEY_RANDOM_LEN,
    BoundTo,
    CenterKeyInfo,
    key_state,
    prefix_of,
)

#: 키 종류 (C7). Center는 이 넷만 발급한다.
KEY_TYPES = ("bot_ui", "studio", "server_runner", "integration")
#: 키 묶음을 가지는 종류 — PC 하나에 묶인다.
BOUND_TYPES = ("bot_ui", "server_runner")
#: 기본 만료 (C7 — 1년).
DEFAULT_EXPIRY_DAYS = 365

#: 무작위 부분에 쓰는 글자 수. `token_urlsafe`는 길이가 들쭉날쭉하므로 잘라 쓴다.
_RANDOM_BYTES = 48


def new_key() -> str:
    """키 원문 (`chk_ctr_` + 무작위 40자). 돌려준 뒤 **다시 만들 수 없다.**"""
    random = secrets.token_urlsafe(_RANDOM_BYTES).replace("=", "")[:KEY_RANDOM_LEN]
    return f"{KEY_PREFIX}{random}"


def key_hash(raw: str) -> str:
    """저장·비교에 쓰는 해시. 원문은 어디에도 남기지 않는다."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_key_id() -> str:
    return f"ck_{secrets.token_hex(4)}"


@dataclass(frozen=True)
class KeyRecord:
    """저장된 키 하나 (원문 없음)."""

    key_id: str
    name: str
    type: str
    prefix: str
    created_at: str
    expires_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None
    bound_to: BoundTo | None = None
    #: 등록 승인이 만든 키면 그 요청 (C5 §등록 승인, ADR-0092).
    enrollment_id: str | None = None
    #: 그 기계의 X25519 공개키 — 있으면 Center가 키를 회전해 준다 (C4 §키 회전).
    public_key: str | None = None
    #: 회전으로 갈아 줄 새 키 (새 키로 첫 요청이 오면 이 키를 폐기한다).
    successor_id: str | None = None

    def state(self, *, now: str) -> str:
        return key_state(now=now, expires_at=self.expires_at, revoked_at=self.revoked_at)

    def info(self, *, now: str) -> CenterKeyInfo:
        return CenterKeyInfo(
            key_id=self.key_id,
            name=self.name,
            type=self.type,
            prefix=self.prefix,
            bound_to=self.bound_to,
            created_at=self.created_at,
            expires_at=self.expires_at,
            last_used_at=self.last_used_at,
            revoked_at=self.revoked_at,
            state=self.state(now=now),
            enrollment_id=self.enrollment_id,
        )


def _record(row: Any) -> KeyRecord:
    bound = loads(row["bound_json"])
    return KeyRecord(
        key_id=row["key_id"],
        name=row["name"],
        type=row["type"],
        prefix=row["prefix"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
        bound_to=BoundTo.model_validate(bound) if bound else None,
        enrollment_id=row["enrollment_id"],
        public_key=row["public_key"],
        successor_id=row["successor_id"],
    )


def issue(
    store: Store,
    *,
    name: str,
    key_type: str,
    expires_at: str | None,
    bound: BoundTo | None = None,
    enrollment_id: str | None = None,
    public_key: str | None = None,
) -> tuple[KeyRecord, str]:
    """키를 발급한다. `(기록, 원문)` — **원문은 이때만 볼 수 있다.**

    등록 승인·회전은 `bound`를 주어 **그 기계에 미리 묶는다** (C4 §등록 요청과 승인).
    """
    raw = new_key()
    record = KeyRecord(
        key_id=new_key_id(),
        name=name,
        type=key_type,
        prefix=prefix_of(raw),
        created_at=now_iso(),
        expires_at=expires_at,
        bound_to=bound,
        enrollment_id=enrollment_id,
        public_key=public_key,
    )
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO center_keys (key_id, name, type, prefix, key_hash, created_at, expires_at,"
            " bound_json, enrollment_id, public_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.key_id,
                name,
                key_type,
                record.prefix,
                key_hash(raw),
                record.created_at,
                expires_at,
                dumps(bound.to_json_dict()) if bound is not None else None,
                enrollment_id,
                public_key,
            ),
        )
    return record, raw


def set_public_key(store: Store, key_id: str, public_key: str) -> None:
    """그 기계가 등록에 실어 보낸 공개키를 둔다 — 그때부터 Center가 키를 회전해 준다 (C4)."""
    with store.tx() as cur:
        cur.execute("UPDATE center_keys SET public_key = ? WHERE key_id = ?", (public_key, key_id))


def find(store: Store, raw: str) -> KeyRecord | None:
    """원문으로 키를 찾는다. 해시를 **일정 시간 비교**한다 (앞자리로 좁힌 뒤)."""
    wanted = key_hash(raw)
    for row in store.rows("SELECT * FROM center_keys WHERE prefix = ?", (prefix_of(raw),)):
        if hmac.compare_digest(row["key_hash"], wanted):
            return _record(row)
    # 확장 폴더의 일꾼 키는 **해시만** 안다 — 앞자리가 비어 있다 (ADR-0121, C15 §승인 없는 일꾼).
    for row in store.rows("SELECT * FROM center_keys WHERE prefix = '' AND key_hash = ?", (wanted,)):
        if hmac.compare_digest(row["key_hash"], wanted):
            return _record(row)
    return None


def get(store: Store, key_id: str) -> KeyRecord | None:
    row = store.row("SELECT * FROM center_keys WHERE key_id = ?", (key_id,))
    return _record(row) if row else None


def listing(store: Store, *, key_type: str | None = None, state: str | None = None) -> list[KeyRecord]:
    # 호출 토큰(C15)은 실행마다 생기는 짧은 토큰이라 CON-11 목록에 보이지 않는다.
    rows = store.rows("SELECT * FROM center_keys WHERE type != 'call_token' ORDER BY created_at DESC")
    found = [_record(r) for r in rows]
    now = now_iso()
    if key_type:
        found = [k for k in found if k.type == key_type]
    if state:
        found = [k for k in found if k.state(now=now) == state]
    return found


def touch(store: Store, key_id: str) -> None:
    """마지막 사용 시각 (CON-11에서 「언제 마지막으로 썼나」를 본다)."""
    with store.tx() as cur:
        cur.execute("UPDATE center_keys SET last_used_at = ? WHERE key_id = ?", (now_iso(), key_id))


def revoke(store: Store, key_id: str) -> bool:
    with store.tx() as cur:
        cur.execute(
            "UPDATE center_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
            (now_iso(), key_id),
        )
        return cur.rowcount > 0


def purge(store: Store, key_id: str) -> bool:
    """폐기된 키의 행을 지운다 (CON-11 「삭제」, [ADR-0095]). **폐기된 것만** — 아니면 `False`.

    키 행을 가리키는 것(PC 실행기·서버 실행기 행의 `key_id`, 실행 기록·결재의 `owner_key_id`,
    회전의 `successor_id`)은 그대로 둔다 — 모두 키 행이 없을 때를 다룬다. 묶였던 기계 자리는
    「묶음 풀기」처럼 놓인 자리가 된다 (`host_keys._adopt_or_refuse`).
    """
    with store.tx() as cur:
        cur.execute("DELETE FROM center_keys WHERE key_id = ? AND revoked_at IS NOT NULL", (key_id,))
        return cur.rowcount > 0


def bind(store: Store, key_id: str, bound: BoundTo) -> None:
    """키를 그 PC·대상에 묶는다 (처음 등록할 때)."""
    with store.tx() as cur:
        cur.execute("UPDATE center_keys SET bound_json = ? WHERE key_id = ?", (dumps(bound.to_json_dict()), key_id))


def unbind(store: Store, key_id: str) -> bool:
    """PC 묶음 풀기 (CON-11). PC를 다시 설치해 `machine_id`가 바뀐 경우."""
    with store.tx() as cur:
        cur.execute(
            "UPDATE center_keys SET bound_json = NULL WHERE key_id = ? AND bound_json IS NOT NULL", (key_id,)
        )
        return cur.rowcount > 0

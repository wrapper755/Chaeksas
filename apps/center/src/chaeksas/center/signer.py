"""Center 서명 키 — 승인·배포·외부 확장 봉투는 **Center가 대신 서명한다** (ADR-0090 §5).

봉투와 검증(C2 V1~V7)은 그대로다. Bot UI·서버 실행기는 하트비트의 `admin_keys`를 믿는데,
Center 키의 공개키가 그 목록에 「Center」라는 이름으로 들어 있을 뿐이다 — 현장 코드는 모른다.

- 처음 뜰 때 키 하나를 만들어 **DB에** 둔다(`center_signing_keys`). DB와 같이 백업되고, 파일
  권한·경로를 따로 다루지 않으며, 시험의 메모리 DB에서도 그대로 돈다.
- **교체**(`rotate`)는 새 키가 그 뒤의 서명을 맡고 옛 키는 믿는 목록에 남는다 — 이미 나간
  승인·배포가 계속 산다. **버리기**(`retire`)는 그 키가 서명한 것을 모두 무효로 만든다.
"""

from __future__ import annotations

import base64
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.signing import AdminKey, Envelope, key_id_for, sign

#: Admin 키 목록에 보일 Center 키의 이름.
LABEL = "Center"


def _public_of(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes_raw()


def _load(raw: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw, validate=True))


def _trust(store: Store, private: Ed25519PrivateKey) -> AdminKey:
    """공개키를 믿는 목록(`admin_keys`)에 넣는다 — 하트비트가 현장에 그대로 내려 준다."""
    public = _public_of(private)
    made = AdminKey(
        key_id=key_id_for(public),
        public_key=base64.b64encode(public).decode("ascii"),
        label=LABEL,
    )
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO admin_keys (key_id, key_json, envelope_json, at) VALUES (?, ?, NULL, ?)"
            " ON CONFLICT (key_id) DO NOTHING",
            (made.key_id, made.model_dump_json(), now_iso()),
        )
    return made


def _create(store: Store) -> Ed25519PrivateKey:
    private = Ed25519PrivateKey.generate()
    key_id = key_id_for(_public_of(private))
    with store.tx() as cur:
        cur.execute("UPDATE center_signing_keys SET active = 0")
        cur.execute(
            "INSERT INTO center_signing_keys (key_id, private_key, created_at, active) VALUES (?, ?, ?, 1)",
            (key_id, base64.b64encode(private.private_bytes_raw()).decode("ascii"), now_iso()),
        )
    _trust(store, private)
    return private


def active(store: Store) -> Ed25519PrivateKey:
    """지금 서명하는 키. 없으면 **만든다** (처음 뜰 때 한 번)."""
    row = store.row("SELECT private_key FROM center_signing_keys WHERE active = 1")
    if row is None:
        return _create(store)
    private = _load(str(row["private_key"]))
    _trust(store, private)  # 믿는 목록에서 빠져 있으면 되돌려 넣는다 (멱등)
    return private


def seal(store: Store, payload: dict[str, Any]) -> Envelope:
    """`payload`에 서명한 봉투. 실수(`float`)가 들어 있으면 서명 전에 막힌다 (C2)."""
    return sign(payload, active(store), signed_at=now_iso())


def rotate(store: Store) -> str:
    """새 키로 바꾼다. 옛 키는 **믿는 목록에 남는다**. 새 `key_id`를 돌려준다."""
    return key_id_for(_public_of(_create(store)))


def retire(store: Store, key_id: str) -> AdminKey:
    """키를 버린다 — 그 키가 서명한 승인·배포가 **모두 무효**가 된다 (C2 V2 `revoked_key`).

    **지금 서명하는 키는 버리지 않는다**(먼저 `rotate`). 옛 Admin 키(사람이 서명하던 때의 것)도
    같은 길로 버린다.
    """
    current = store.row("SELECT key_id FROM center_signing_keys WHERE active = 1")
    if current is not None and current["key_id"] == key_id:
        raise ValueError("지금 서명하는 키는 버릴 수 없다 — 먼저 `signing-key rotate`로 바꾼다")
    row = store.row("SELECT key_json FROM admin_keys WHERE key_id = ?", (key_id,))
    if row is None:
        raise LookupError(f"믿는 키 목록에 없다: {key_id}")
    found = AdminKey.model_validate_json(row["key_json"])
    if found.revoked:
        return found
    made = found.model_copy(update={"revoked_at": now_iso()})
    with store.tx() as cur:
        cur.execute("UPDATE admin_keys SET key_json = ? WHERE key_id = ?", (made.model_dump_json(), key_id))
        cur.execute("UPDATE center_signing_keys SET active = 0 WHERE key_id = ?", (key_id,))
    return made


def current_key_id(store: Store) -> str:
    return key_id_for(_public_of(active(store)))


__all__ = ["LABEL", "active", "current_key_id", "retire", "rotate", "seal"]

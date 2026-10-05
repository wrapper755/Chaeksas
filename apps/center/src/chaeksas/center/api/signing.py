"""Admin 키와 패키지 승인 — **서명이 유일한 관문**이다 (C2·C5).

관리자 토큰이 새도 배포를 만들거나 서명 키를 바꿔치기할 수 없어야 한다. 그래서 여기서
바뀌는 것은 모두 **Admin 개인키 서명(봉투)**이 있어야 한다. 토큰은 문을 여는 것일 뿐이다.

- Center는 **공개키만** 가진다. 개인키는 Admin의 PC에만 있다.
- **봉투 바이트를 그대로 저장한다** (감사 추적) — 다시 만들어 내지 않는다.
- 같은 봉투를 다시 올리면 **200**이다 (멱등). 같은 자리에 다른 내용이면 409.
- **마지막 Admin 키는 철회할 수 없다** — 잠겨서 아무도 서명할 수 없게 되는 것을 막는다.
"""

from __future__ import annotations

import json
from typing import Any

from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.signing import (
    AdminKey,
    Envelope,
    key_id_for,
    verify,
    verify_admin_key_addition,
)

#: 패키지 상태 (C5 — `KNOWN_PACKAGE_STATUSES`).
STATUS_CANDIDATE = "candidate"
STATUS_APPROVED = "approved"
STATUS_REVOKED = "revoked"


def _envelope(raw: Any) -> Envelope:
    try:
        return Envelope.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", f"봉투가 계약과 맞지 않는다: {e}") from e


def _refuse(problems: list[Any]) -> None:
    """검증 위반을 C2의 사유 코드 그대로 올린다 — **왜 거부했는지**가 보여야 한다."""
    if not problems:
        return
    first = problems[0]
    raise ApiError(
        403,
        first.code or "bad_signature",
        first.message,
        detail={"violations": [{"rule": p.rule, "code": p.code, "message": p.message} for p in problems]},
    )


# ─────────────────────────── Admin 키 ───────────────────────────


def admin_keys(store: Store) -> list[AdminKey]:
    """등록된 Admin 공개키 (철회된 것도 함께 — 왜 거부됐는지 알아야 한다)."""
    rows = store.rows("SELECT key_json FROM admin_keys ORDER BY key_id")
    return [AdminKey.model_validate_json(row["key_json"]) for row in rows]


def active_keys(store: Store) -> list[AdminKey]:
    return [one for one in admin_keys(store) if not one.revoked]


def bootstrap_key(store: Store, *, public_key: bytes, label: str | None = None) -> AdminKey:
    """첫 Admin 키를 넣는다 (C2 §부트스트랩) — **서버 셸에서만**.

    키가 하나라도 있으면 거부한다. 그다음부터는 `admin_key` 봉투로만 더한다.
    """
    if admin_keys(store):
        raise ApiError(
            409,
            "already_bootstrapped",
            "Admin 키가 이미 있다 — 그다음부터는 서명한 봉투(admin_key)로만 더한다",
        )
    import base64

    made = AdminKey(
        key_id=key_id_for(public_key),
        public_key=base64.b64encode(public_key).decode("ascii"),
        label=label,
    )
    _put_key(store, made, envelope=None)
    return made


def add_admin_key(store: Store, raw: Any) -> AdminKey:
    """`admin_key` 봉투로 공개키를 더한다. **다른 Admin 키가 서명해야 한다** (V8)."""
    envelope = _envelope(raw)
    keys = admin_keys(store)
    _refuse(verify(envelope, keys=keys, expect_kind="admin_key"))
    _refuse(verify_admin_key_addition(envelope, keys=keys))

    claim = envelope.payload
    made = AdminKey(
        key_id=str(claim["key_id"]),
        public_key=str(claim["public_key"]),
        label=claim.get("label"),
    )
    found = next((one for one in keys if one.key_id == made.key_id), None)
    if found is not None:
        if found.public_key != made.public_key:
            raise ApiError(409, "key_conflict", f"같은 key_id에 다른 공개키다: {made.key_id}")
        return found  # 멱등 — 같은 것을 다시 올렸다
    _put_key(store, made, envelope=envelope)
    return made


def revoke_admin_key(store: Store, raw: Any) -> AdminKey:
    """`admin_key_revoke` 봉투. **마지막 남은 키는 철회할 수 없다** (409 `last_admin_key`)."""
    envelope = _envelope(raw)
    keys = admin_keys(store)
    _refuse(verify(envelope, keys=keys, expect_kind="admin_key_revoke"))

    key_id = str(envelope.payload["key_id"])
    found = next((one for one in keys if one.key_id == key_id), None)
    if found is None:
        raise ApiError(404, "not_found", f"그 Admin 키가 없다: {key_id}")
    if found.revoked:
        return found  # 멱등
    if len([one for one in keys if not one.revoked]) <= 1:
        raise ApiError(
            409,
            "last_admin_key",
            "마지막 남은 Admin 키는 철회할 수 없다 — 아무도 서명할 수 없게 된다",
        )
    made = found.model_copy(update={"revoked_at": str(envelope.payload.get("revoked_at") or now_iso())})
    _put_key(store, made, envelope=envelope)
    return made


def _put_key(store: Store, key: AdminKey, *, envelope: Envelope | None) -> None:
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO admin_keys (key_id, key_json, envelope_json, at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (key_id) DO UPDATE SET key_json = excluded.key_json, "
            "envelope_json = excluded.envelope_json, at = excluded.at",
            (
                key.key_id,
                key.model_dump_json(),
                # **봉투 바이트를 그대로 둔다** (감사 추적). 부트스트랩은 봉투가 없다.
                json.dumps(envelope.to_json_dict(), ensure_ascii=False) if envelope else None,
                now_iso(),
            ),
        )


# ─────────────────────────── 패키지 승인 ───────────────────────────


def approve_package(store: Store, package_id: str, version: str, raw: Any) -> dict[str, Any]:
    """`package` 봉투로 승인한다 (C5 `PUT …/signature`).

    **해시가 다르면 거부한다** — 승인한 그 바이트가 아니면 승인이 아니다.
    """
    envelope = _envelope(raw)
    _refuse(verify(envelope, keys=admin_keys(store), expect_kind="package"))
    row = _package(store, package_id, version)

    claim = envelope.payload
    if (claim.get("id"), claim.get("version")) != (package_id, version):
        raise ApiError(
            409,
            "wrong_package",
            f"봉투는 {claim.get('id')}@{claim.get('version')}를 가리킨다",
        )
    if claim.get("content_hash") != row["content_hash"]:
        raise ApiError(
            409,
            "hash_mismatch",
            f"해시가 다르다 (봉투 {claim.get('content_hash')}, 실제 {row['content_hash']})",
        )
    if row["status"] == STATUS_REVOKED:
        # **철회된 것은 되살아나지 않는다** (C2 — 배포 철회와 같은 규칙).
        raise ApiError(409, "package_revoked", f"{package_id}@{version}은 승인이 철회됐다")

    with store.tx() as cur:
        cur.execute(
            "UPDATE packages SET status = ?, signature_json = ? WHERE id = ? AND version = ?",
            (STATUS_APPROVED, json.dumps(envelope.to_json_dict(), ensure_ascii=False), package_id, version),
        )
    return {"id": package_id, "version": version, "status": STATUS_APPROVED}


def revoke_package(store: Store, package_id: str, version: str, raw: Any) -> dict[str, Any]:
    """`package_revoke` 봉투. 이 패키지의 배포가 모두 무효가 되고 내려받기는 410이다."""
    envelope = _envelope(raw)
    _refuse(verify(envelope, keys=admin_keys(store), expect_kind="package_revoke"))
    row = _package(store, package_id, version)
    claim = envelope.payload
    if (claim.get("id"), claim.get("version")) != (package_id, version):
        raise ApiError(409, "wrong_package", f"봉투는 {claim.get('id')}@{claim.get('version')}를 가리킨다")
    if row["status"] == STATUS_REVOKED:
        return {"id": package_id, "version": version, "status": STATUS_REVOKED}

    with store.tx() as cur:
        cur.execute(
            "UPDATE packages SET status = ?, revoke_json = ? WHERE id = ? AND version = ?",
            (STATUS_REVOKED, json.dumps(envelope.to_json_dict(), ensure_ascii=False), package_id, version),
        )
    return {"id": package_id, "version": version, "status": STATUS_REVOKED}


def signature_of(store: Store, package_id: str, version: str) -> Envelope | None:
    """내려줄 때 zip에 넣을 승인 봉투 (C2) — 없으면 `None`."""
    row = _package(store, package_id, version)
    raw = row["signature_json"] if "signature_json" in row.keys() else None
    return Envelope.model_validate_json(raw) if raw else None


def _package(store: Store, package_id: str, version: str) -> Any:
    row = store.row(
        "SELECT status, content_hash, signature_json FROM packages WHERE id = ? AND version = ?",
        (package_id, version),
    )
    if row is None:
        raise ApiError(404, "not_found", f"{package_id}@{version}이 없다")
    return row


__all__ = [
    "STATUS_APPROVED",
    "STATUS_REVOKED",
    "STATUS_CANDIDATE",
    "active_keys",
    "add_admin_key",
    "admin_keys",
    "approve_package",
    "bootstrap_key",
    "revoke_admin_key",
    "revoke_package",
    "signature_of",
]

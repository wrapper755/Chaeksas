"""패키지 승인 — **Center가 서버의 키로 대신 서명한다** (C2·C5, ADR-0090).

봉투와 검증은 그대로다. 사람(관리자 계정)이 누르면 Center가 `package`·`package_revoke` 봉투를
지어 `signer`로 서명하고, 받던 때와 **같은 규칙**(해시·철회)을 지나 둔다. 현장(PC 실행기·서버
실행기)은 하트비트의 `admin_keys`에 든 Center 공개키로 다시 검증한다.

- **봉투 바이트를 그대로 저장한다** (감사 추적 — zip의 `SIGNATURE`가 된다).
- **누가 했는지는 계정 이름**으로 남긴다(`approved_by`·`revoked_by`) — 봉투의 `key_id`는 이제
  늘 Center 키라 사람을 말하지 못한다.
- 믿는 키(`admin_keys`)는 Center 키와, 사람이 서명하던 때 들어온 옛 Admin 키다. 옛 키를 버리는
  길은 서버 셸의 `bpm-center signing-key retire`뿐이다.
"""

from __future__ import annotations

import json
from typing import Any

from chaeksas.center import signer
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.signing import AdminKey, Envelope, verify

#: 패키지 상태 (C5 — `KNOWN_PACKAGE_STATUSES`).
STATUS_CANDIDATE = "candidate"
STATUS_APPROVED = "approved"
STATUS_REVOKED = "revoked"
#: 지원 종료 (C5 `PUT …/status`) — **막는 쪽이라 서명이 없다**. 철회(`revoked`)는 서명이 있다.
STATUS_DEPRECATED = "deprecated"

#: **이미 배포된 것이 그대로 도는** 패키지 상태 (C5 §패키지). 지원 종료는 **새 배포만** 막는다 —
#: 돌고 있는 것을 세우는 것은 배포 철회다. 그래서 활성 배포를 고르는 자리는 이 둘을 받는다
#: (`deployments._live_sql`), 새 배포·승인 관문은 `approved` 하나다.
LIVE_STATUSES = (STATUS_APPROVED, STATUS_DEPRECATED)


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


# ─────────────────────────── 믿는 키 ───────────────────────────


def admin_keys(store: Store) -> list[AdminKey]:
    """믿는 공개키 (Center 키 + 옛 Admin 키, 철회된 것도 함께 — 왜 거부됐는지 알아야 한다)."""
    rows = store.rows("SELECT key_json FROM admin_keys ORDER BY key_id")
    return [AdminKey.model_validate_json(row["key_json"]) for row in rows]


def active_keys(store: Store) -> list[AdminKey]:
    return [one for one in admin_keys(store) if not one.revoked]


# ─────────────────────────── 패키지 승인 ───────────────────────────


def approve_package(store: Store, package_id: str, version: str, *, by: str) -> dict[str, Any]:
    """승인한다 (C5 `PUT …/signature`). Center가 `package` 봉투를 지어 서명한다.

    이미 승인됐으면 그대로 돌려준다(멱등). **철회된 것은 되살아나지 않는다** (C2).
    """
    row = _package(store, package_id, version)
    if row["status"] == STATUS_REVOKED:
        raise ApiError(409, "package_revoked", f"{package_id}@{version}은 승인이 철회됐다")
    if row["status"] == STATUS_APPROVED and row["signature_json"]:
        return {"id": package_id, "version": version, "status": STATUS_APPROVED}
    envelope = signer.seal(
        store,
        {"kind": "package", "id": package_id, "version": version, "content_hash": str(row["content_hash"])},
    )
    # 지은 것도 받던 때와 같은 검사를 지난다 — 믿는 키 목록에서 빠진 키로 서명하면 여기서 안다.
    _refuse(verify(envelope, keys=admin_keys(store), expect_kind="package"))
    with store.tx() as cur:
        cur.execute(
            "UPDATE packages SET status = ?, signature_json = ?, approved_by = ? WHERE id = ? AND version = ?",
            (
                STATUS_APPROVED,
                json.dumps(envelope.to_json_dict(), ensure_ascii=False),
                by,
                package_id,
                version,
            ),
        )
    return {"id": package_id, "version": version, "status": STATUS_APPROVED}


def revoke_package(store: Store, package_id: str, version: str, *, reason: str, by: str) -> dict[str, Any]:
    """승인을 철회한다 (`package_revoke`). 이 패키지의 배포가 모두 무효가 되고 내려받기는 410이다."""
    row = _package(store, package_id, version)
    if row["status"] == STATUS_REVOKED:
        return {"id": package_id, "version": version, "status": STATUS_REVOKED}
    envelope = signer.seal(
        store,
        {
            "kind": "package_revoke",
            "id": package_id,
            "version": version,
            "reason": reason,
            "revoked_at": now_iso(),
        },
    )
    with store.tx() as cur:
        cur.execute(
            "UPDATE packages SET status = ?, revoke_json = ?, revoked_by = ? WHERE id = ? AND version = ?",
            (
                STATUS_REVOKED,
                json.dumps(envelope.to_json_dict(), ensure_ascii=False),
                by,
                package_id,
                version,
            ),
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
    "STATUS_DEPRECATED",
    "LIVE_STATUSES",
    "active_keys",
    "admin_keys",
    "approve_package",
    "revoke_package",
    "signature_of",
]

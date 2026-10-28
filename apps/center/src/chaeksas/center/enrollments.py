"""등록 요청과 승인, 키 회전 — **키는 Center가 만들어 봉해 내려 준다** (C4·C12·C5, ADR-0092).

설치하는 사람은 Center 주소만 넣는다. 현장이 공개키를 실어 요청하면 여기서 「승인 대기」로 두고,
관리자가 요청 코드를 맞춰 보고 승인하면 키를 만들어 **그 기계에 미리 묶고** 요청의 공개키로 봉해
둔다. 현장이 그 키로 `register`를 부르면 봉해 둔 것을 지운다(그것이 받았다는 표시다).

지키는 것:

- **사람은 키 원문을 보지 않는다.** 원문은 봉함 안에만 있고, 받은 뒤에는 Center에도 없다(해시만).
- **승인은 키 묶기 규칙을 그대로 따른다** (`host_keys`). 이미 등록된 기계면 옛 키를 폐기하고 묶음을
  풀어 둔다 — 새 키의 첫 `register`가 그 자리를 이어받는다 (「PC 묶음 풀기」가 하던 일).
- **회전도 같은 봉함이다.** 공개키를 아는 키는 만료 14일 전부터 새 키를 하트비트 답에 싣고, 새 키로
  첫 요청이 오면 행을 새 키로 옮기고 옛 키를 폐기한다.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center import host_keys, keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.bot_ui import EnrollRequest
from chaeksas.contracts.center_keys import DEFAULT_EXPIRY_DAYS, BoundTo, expires_soon
from chaeksas.contracts.enrollment import (
    DELIVERY_HOURS,
    PENDING_HOURS,
    QUEUE_MAX,
    RATE_MAX,
    RATE_WINDOW_S,
    ROTATE_BEFORE_DAYS,
    EnrollmentDecision,
    EnrollmentInfo,
    EnrollStatus,
    ExistingHost,
    RotatedKey,
    Sealed,
    StudioEnrollRequest,
    request_code,
    seal,
    valid_public_key,
)
from chaeksas.contracts.external_task import CONSUMER, ConsumerEnrollRequest
from chaeksas.contracts.server_runner import ServerRunnerEnrollRequest

#: 요청 종류 → 키 묶기를 지킬 표 (C4·C12 — 규칙은 `host_keys`에 하나다). **Studio는 표가 없다** —
#: 등록(`register`)이 없어 그 PC는 키 자체에만 묶인다 (C5 §Studio 등록 요청과 승인, ADR-0093).
TABLES = {"bot_ui": host_keys.BOT_UI, "server_runner": host_keys.SERVER_RUNNER}
STUDIO = "studio"
#: 요청 본문 모델 — 각자의 `RegisterRequest` + `public_key` (Studio는 제 모양).
MODELS: dict[str, Any] = {
    "bot_ui": EnrollRequest,
    "server_runner": ServerRunnerEnrollRequest,
    STUDIO: StudioEnrollRequest,
    CONSUMER: ConsumerEnrollRequest,
}


def new_enrollment_id() -> str:
    return f"enr_{secrets.token_hex(16)}"


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _later(now: str, **delta: float) -> str:
    return (_at(now) + timedelta(**delta)).isoformat()


def sweep(store: Store, *, now: str | None = None) -> None:
    """지난 것을 닫는다 — 대기 24시간, 승인된 키를 받을 때까지 24시간 (C4).

    읽을 때마다 부른다 (따로 도는 일꾼이 없다). 받지 않은 키는 **폐기한다** — 봉함이 Center에
    남아 있는 동안 그 키는 쓰이지 않은 채 살아 있는 키다.
    """
    at = now or now_iso()
    with store.tx() as cur:
        cur.execute("UPDATE enrollments SET state = 'expired' WHERE state = 'pending' AND expires_at <= ?", (at,))
    cutoff = _later(at, hours=-DELIVERY_HOURS)
    for row in store.rows(
        "SELECT enrollment_id, key_id FROM enrollments"
        " WHERE state = 'approved' AND sealed_json IS NOT NULL AND decided_at <= ?",
        (cutoff,),
    ):
        if row["key_id"]:
            keys.revoke(store, str(row["key_id"]))
        with store.tx() as cur:
            cur.execute(
                "UPDATE enrollments SET state = 'expired', sealed_json = NULL WHERE enrollment_id = ?",
                (row["enrollment_id"],),
            )


def _with_key_expiry(store: Store, row: Any, found: EnrollStatus) -> EnrollStatus:
    if found.sealed_key is None or not row["key_id"]:
        return found
    record = keys.get(store, str(row["key_id"]))
    return found.model_copy(
        update={"key_expires_at": record.expires_at if record else None, "key_name": record.name if record else None}
    )


def request(store: Store, *, kind: str, body: dict[str, Any], remote_addr: str | None) -> EnrollStatus:
    """`POST …/enroll` (C4·C12). 인증이 없다 — 내려 줄 키는 요청의 공개키로 봉한다."""
    try:
        wanted = MODELS[kind].model_validate(body)
    except ValueError as e:
        message = str(e)
        if "public_key" in message:
            raise ApiError(422, "public_key_invalid", "공개키가 X25519 공개키(base64url 43자)가 아니다") from e
        raise ApiError(
            422, "input_invalid", "등록 요청이 계약과 맞지 않는다", {"error": message.splitlines()[0]}
        ) from e
    if not valid_public_key(wanted.public_key):
        raise ApiError(422, "public_key_invalid", "공개키가 X25519 공개키로 읽히지 않는다")

    now = now_iso()
    sweep(store, now=now)
    if remote_addr:
        recent = store.row(
            "SELECT COUNT(*) AS n FROM enrollments WHERE remote_addr = ? AND requested_at > ?",
            (remote_addr, _later(now, seconds=-RATE_WINDOW_S)),
        )
        if recent is not None and int(recent["n"]) >= RATE_MAX:
            raise ApiError(
                429,
                "enroll_rate_limited",
                f"같은 곳에서 {RATE_WINDOW_S // 60}분에 {RATE_MAX}건까지 요청할 수 있다",
                {"retry_after_s": RATE_WINDOW_S},
            )
    waiting = store.row("SELECT COUNT(*) AS n FROM enrollments WHERE state = 'pending'")
    if waiting is not None and int(waiting["n"]) >= QUEUE_MAX:
        raise ApiError(
            429, "enroll_queue_full", f"승인을 기다리는 요청이 {QUEUE_MAX}건이라 더 받지 않는다", {"retry_after_s": 600}
        )

    enrollment_id = new_enrollment_id()
    code = request_code(wanted.public_key, enrollment_id)
    expires_at = _later(now, hours=PENDING_HOURS)
    with store.tx() as cur:
        # 같은 기계가 대기 중에 다시 요청하면 **옛 요청을 닫는다** — 승인 대기에 두 줄 서지 않는다.
        cur.execute(
            "UPDATE enrollments SET state = 'expired' WHERE type = ? AND machine_id = ? AND state = 'pending'",
            (kind, wanted.machine_id),
        )
        cur.execute(
            "INSERT INTO enrollments (enrollment_id, type, machine_id, name, os, request_json, public_key,"
            " code, remote_addr, requested_at, expires_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                enrollment_id,
                kind,
                wanted.machine_id,
                wanted.name,
                wanted.os,
                dumps(wanted.to_json_dict()),
                wanted.public_key,
                code,
                remote_addr,
                now,
                expires_at,
            ),
        )
    return EnrollStatus(enrollment_id=enrollment_id, state="pending", code=code, expires_at=expires_at)


def status(store: Store, enrollment_id: str, *, kind: str) -> EnrollStatus:
    """`GET …/enroll/{id}` (C4·C12). 없거나 다른 종류의 요청이면 404."""
    sweep(store)
    row = store.row("SELECT * FROM enrollments WHERE enrollment_id = ? AND type = ?", (enrollment_id, kind))
    if row is None:
        raise ApiError(404, "not_found", "그런 등록 요청이 없다")
    sealed = loads(row["sealed_json"])
    found = EnrollStatus(
        enrollment_id=row["enrollment_id"],
        state=row["state"],
        code=row["code"],
        expires_at=row["expires_at"],
        sealed_key=Sealed.model_validate(sealed) if sealed and row["state"] == "approved" else None,
        reason=row["reason"] if row["state"] == "rejected" else None,
    )
    return _with_key_expiry(store, row, found)


def _existing(store: Store, kind: str, machine_id: str) -> Any | None:
    table = TABLES[kind]
    return store.row(f"SELECT * FROM {table.name} WHERE machine_id = ?", (machine_id,))  # noqa: S608 — 표 이름은 상수다


def _studio_keys(store: Store, machine_id: str) -> list[keys.KeyRecord]:
    """그 PC에 묶인 **살아 있는** Studio 키 — 같은 PC를 다시 승인하면 폐기할 것들."""
    now = now_iso()
    rows = store.rows("SELECT key_id FROM center_keys WHERE type = ? AND revoked_at IS NULL", (STUDIO,))
    found = [keys.get(store, str(row["key_id"])) for row in rows]
    return [
        one
        for one in found
        if one is not None
        and one.bound_to is not None
        and one.bound_to.id == machine_id
        and one.state(now=now) == "active"
    ]


def _consumer_of(store: Store, machine_id: str) -> Any | None:
    """그 기계의 일꾼 행 (C15). 일꾼은 `register`가 없어 **승인이 행을 만든다**."""
    return store.row("SELECT * FROM consumers WHERE machine_id = ?", (machine_id,))


def _existing_info(store: Store, kind: str, machine_id: str) -> ExistingHost | None:
    """그 기계가 이미 들어와 있으면 — 승인하면 그 자리를 이어받고 옛 키는 폐기된다."""
    if kind == CONSUMER:
        found = _consumer_of(store, machine_id)
        if found is None:
            return None
        record = keys.get(store, str(found["key_id"]))
        return ExistingHost(
            id=str(found["consumer_id"]),
            name=str(found["name"]),
            key_prefix=record.prefix if record else None,
            last_seen=found["last_fetch_at"],
        )
    if kind == STUDIO:
        held = _studio_keys(store, machine_id)
        if not held:
            return None
        newest = held[-1]
        return ExistingHost(id=newest.key_id, name=newest.name, key_prefix=newest.prefix, last_seen=newest.last_used_at)
    table = TABLES.get(kind)
    other = _existing(store, kind, machine_id) if table is not None else None
    if other is None or table is None:
        return None
    record = keys.get(store, str(other["key_id"]))
    return ExistingHost(
        id=str(other[table.id_column]),
        name=str(other["name"]),
        key_prefix=record.prefix if record else None,
        last_seen=other["last_seen_at"],
    )


def _info(store: Store, row: Any) -> EnrollmentInfo:
    existing = (
        _existing_info(store, str(row["type"]), str(row["machine_id"])) if row["state"] == "pending" else None
    )
    request_body = loads(row["request_json"], {}) or {}
    return EnrollmentInfo(
        enrollment_id=row["enrollment_id"],
        type=row["type"],
        code=row["code"],
        name=row["name"],
        os=row["os"],
        versions=request_body.get("versions") or {},
        machine_id_prefix=str(row["machine_id"])[:12],
        remote_addr=row["remote_addr"],
        requested_at=row["requested_at"],
        expires_at=row["expires_at"],
        state=row["state"],
        existing=existing,
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        reason=row["reason"],
        key_id=row["key_id"],
    )


def listing(store: Store, *, kind: str | None = None, states: list[str] | None = None) -> list[EnrollmentInfo]:
    """`GET /enrollments` (C5). `states`를 비우면 `pending`만."""
    sweep(store)
    wanted = states or ["pending"]
    rows = store.rows("SELECT * FROM enrollments ORDER BY requested_at DESC")
    return [
        _info(store, row)
        for row in rows
        if row["state"] in wanted and (kind is None or row["type"] == kind)
    ]


def _pending(store: Store, enrollment_id: str) -> Any:
    sweep(store)
    row = store.row("SELECT * FROM enrollments WHERE enrollment_id = ?", (enrollment_id,))
    if row is None:
        raise ApiError(404, "not_found", "그런 등록 요청이 없다")
    if row["state"] != "pending":
        raise ApiError(
            409, "enrollment_closed", f"이미 결정됐거나 만료된 요청이다 ({row['state']})", {"state": row["state"]}
        )
    return row


def _granted_topics(row: Any, wanted: list[str] | None) -> list[str]:
    """승인할 토픽 (C15 §일꾼 들이기) — 비우면 요청한 그대로, 적으면 **요청한 것 안에서만** 줄인다."""
    asked = list((loads(row["request_json"], {}) or {}).get("topics") or [])
    if not wanted:
        return asked
    outside = sorted(set(wanted) - set(asked))
    if outside:
        raise ApiError(422, "topic_not_requested", "일꾼이 요청하지 않은 토픽은 줄 수 없다", {"topics": outside})
    return [one for one in asked if one in set(wanted)]


def approve(
    store: Store, enrollment_id: str, *, name: str | None, actor: str, topics: list[str] | None = None
) -> EnrollmentDecision:
    """승인 (C5). 키를 만들어 **그 기계에 미리 묶고** 요청의 공개키로 봉해 둔다."""
    row = _pending(store, enrollment_id)
    kind = str(row["type"])
    machine_id = str(row["machine_id"])
    shown = (name or "").strip() or str(row["name"])
    granted = _granted_topics(row, topics) if kind == CONSUMER else []
    if kind == CONSUMER and not granted:
        raise ApiError(422, "topics_empty", "토픽 없이 일꾼을 들일 수 없다")

    replaced = None
    host_id = None
    if kind == STUDIO:
        # 같은 PC를 다시 승인했다 — 그 PC의 옛 Studio 키를 폐기한다 (Studio에는 이어받을 행이 없다).
        for old in _studio_keys(store, machine_id):
            keys.revoke(store, old.key_id)
            replaced = old.key_id
    old_consumer = _consumer_of(store, machine_id) if kind == CONSUMER else None
    if old_consumer is not None:
        # 같은 기계를 다시 들였다 — 옛 키를 폐기하고 **같은 `consumer_id`**를 잇는다 (토픽은 새로 준 것).
        replaced = str(old_consumer["key_id"])
        host_id = str(old_consumer["consumer_id"])
        keys.revoke(store, replaced)
    other = _existing(store, kind, machine_id) if kind in TABLES else None
    if other is not None:
        table = TABLES[kind]
        # 이미 등록된 기계 — **옛 키를 폐기하고 묶음을 풀어 둔다**. 새 키의 첫 `register`가
        # 그 자리를 이어받는다 (C4 키 묶기 「이어받기」 — 배포·기록이 그 id를 가리킨다).
        host_id = str(other[table.id_column])
        replaced = str(other["key_id"])
        keys.revoke(store, replaced)
        keys.unbind(store, replaced)

    now = now_iso()
    record, raw = keys.issue(
        store,
        name=shown,
        key_type=kind,
        expires_at=_later(now, days=DEFAULT_EXPIRY_DAYS),
        bound=BoundTo(type=kind, id=machine_id, name=shown),
        enrollment_id=enrollment_id,
        public_key=str(row["public_key"]),
    )
    sealed = seal(str(row["public_key"]), raw, salt=enrollment_id)
    del raw  # 원문은 봉함 안에만 남는다
    with store.tx() as cur:
        cur.execute(
            "UPDATE enrollments SET state = 'approved', decided_by = ?, decided_at = ?, key_id = ?,"
            " sealed_json = ?, replaced_key_id = ? WHERE enrollment_id = ?",
            (actor, now, record.key_id, dumps(sealed.to_json_dict()), replaced, enrollment_id),
        )
        if kind == CONSUMER:
            # 일꾼은 `register`가 없다 — **승인이 행을 만든다**. manifest는 들일 때 올린 것이다.
            manifest = (loads(row["request_json"], {}) or {}).get("manifest")
            host_id = host_id or f"csm_{secrets.token_hex(8)}"
            cur.execute(
                "INSERT INTO consumers (consumer_id, key_id, machine_id, name, topics_json, manifest_json,"
                " approved_at, approved_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (consumer_id) DO UPDATE SET key_id = excluded.key_id, name = excluded.name,"
                " topics_json = excluded.topics_json, manifest_json = excluded.manifest_json,"
                " approved_at = excluded.approved_at, approved_by = excluded.approved_by",
                (
                    host_id,
                    record.key_id,
                    machine_id,
                    shown,
                    dumps(granted),
                    dumps(manifest) if manifest else None,
                    now,
                    actor,
                ),
            )
    return EnrollmentDecision(key_id=record.key_id, host_id=host_id, replaced_key_id=replaced)


def reject(store: Store, enrollment_id: str, *, reason: str | None, actor: str) -> EnrollmentInfo:
    """거절 (C5). 사유는 요청한 쪽에 그대로 보인다."""
    _pending(store, enrollment_id)
    with store.tx() as cur:
        cur.execute(
            "UPDATE enrollments SET state = 'rejected', decided_by = ?, decided_at = ?, reason = ?"
            " WHERE enrollment_id = ?",
            (actor, now_iso(), (reason or "").strip() or None, enrollment_id),
        )
    found = store.row("SELECT * FROM enrollments WHERE enrollment_id = ?", (enrollment_id,))
    assert found is not None
    return _info(store, found)


def delivered(store: Store, key: keys.KeyRecord, *, public_key: str | None) -> None:
    """그 키로 `register`가 성공했다 — **봉해 둔 것을 지운다** (C4 7번째 차례).

    등록에 공개키가 실려 왔으면 그것을 둔다 — 그때부터 회전해 준다 (C4 §키 회전).
    """
    if key.enrollment_id:
        with store.tx() as cur:
            cur.execute(
                "UPDATE enrollments SET sealed_json = NULL WHERE key_id = ? AND sealed_json IS NOT NULL",
                (key.key_id,),
            )
    if public_key and public_key != key.public_key and valid_public_key(public_key):
        keys.set_public_key(store, key.key_id, public_key)


# ─────────────────────────── 키 회전 (C4 §키 회전) ───────────────────────────


def rotation_for(store: Store, key: keys.KeyRecord, *, host_id: str) -> RotatedKey | None:
    """하트비트 답에 실을 새 키. 만료 14일 전부터이고 **공개키를 아는 키만**이다.

    새 키는 한 번만 만든다 — 그 행에 봉함을 두고 새 키로 첫 요청이 올 때까지 같은 것을 싣는다.
    """
    if key.public_key is None or key.expires_at is None:
        return None
    now = now_iso()
    if not expires_soon(now=now, expires_at=key.expires_at, within_days=ROTATE_BEFORE_DAYS):
        return None
    if key.successor_id:
        found = store.row(
            "SELECT sealed_json, expires_at, revoked_at FROM center_keys WHERE key_id = ?", (key.successor_id,)
        )
        if found is not None and found["sealed_json"] and found["revoked_at"] is None:
            sealed = Sealed.model_validate(loads(found["sealed_json"]))
            return RotatedKey(sealed_key=sealed, expires_at=found["expires_at"])
    record, raw = keys.issue(
        store,
        name=key.name,
        key_type=key.type,
        expires_at=_later(now, days=DEFAULT_EXPIRY_DAYS),
        bound=key.bound_to,
        enrollment_id=key.enrollment_id,
        public_key=key.public_key,
    )
    sealed = seal(key.public_key, raw, salt=host_id)
    del raw
    with store.tx() as cur:
        cur.execute(
            "UPDATE center_keys SET sealed_json = ? WHERE key_id = ?", (dumps(sealed.to_json_dict()), record.key_id)
        )
        cur.execute("UPDATE center_keys SET successor_id = ? WHERE key_id = ?", (record.key_id, key.key_id))
    return RotatedKey(sealed_key=sealed, expires_at=record.expires_at)


def adopt_successor(store: Store, key: keys.KeyRecord) -> None:
    """새 키로 첫 요청이 왔다 — 행을 새 키로 옮기고 옛 키를 폐기한다 (그것이 받았다는 표시다).

    인증하는 자리(`auth.caller`)가 부른다 — 하트비트가 행을 찾기 **전에** 옮겨야 409
    `not_registered`가 나지 않는다.
    """
    old = store.row(
        "SELECT key_id FROM center_keys WHERE successor_id = ? AND revoked_at IS NULL", (key.key_id,)
    )
    if old is None:
        return
    old_id = str(old["key_id"])
    with store.tx() as cur:
        for table in TABLES.values():
            cur.execute(f"UPDATE {table.name} SET key_id = ? WHERE key_id = ?", (key.key_id, old_id))  # noqa: S608
        cur.execute("UPDATE consumers SET key_id = ? WHERE key_id = ?", (key.key_id, old_id))
        cur.execute("UPDATE center_keys SET sealed_json = NULL WHERE key_id = ?", (key.key_id,))
    keys.revoke(store, old_id)


__all__ = [
    "TABLES",
    "adopt_successor",
    "approve",
    "delivered",
    "listing",
    "reject",
    "request",
    "rotation_for",
    "status",
    "sweep",
]

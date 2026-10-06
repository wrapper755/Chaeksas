"""결재 — 실행하는 쪽이 올리고, 콘솔에서 답하고, 하트비트로 내려간다 (C6).

**Center로 올라오는 것은 결재(`approval`)뿐이다.** 확인(`confirmation`)은 화면 앞 사람만
답할 수 있으므로 올리지 않는다 — 올라오면 422다.

세 가지가 이 모듈의 뼈대다.

1. **답은 올린 키에게만 내려간다** (§소유) — 결재는 올린 키에 묶이고, `run_id`도 C3 소유와
   대조한다. 키가 새도 남의 결재를 가로채지 못한다.
2. **거절은 되돌림이다** — 실행하는 쪽이 답을 받아들이지 못하면(`rejected_by_host`) 곧바로
   `open`으로 돌아가고 사유만 남는다. 결재자가 고쳐서 다시 답한다.
3. **답할 곳이 없어진 결재는 자동으로 회수한다** — 실행이 끝났거나(`run_ended`) Bot UI가
   대기열을 잃으면(`host_lost`). 답은 할 수 있는데 전달될 데가 없는 결재를 남기지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.approvals import (
    AUTO_WITHDRAW_REASONS,
    VALUE_RETENTION_DAYS,
    AnswerRequest,
    ApprovalCreateRequest,
    ApprovalHost,
    ApprovalInfo,
    Form,
    apply_defaults,
    validate_answer,
    validate_create,
)
from chaeksas.contracts.bot_ui import ApprovalAck, ApprovalDispatch

#: 결재 상태 (C6). 열린 문자열이지만 Center가 **짓는** 것은 이것들뿐이다.
OPEN = "open"
ANSWERED = "answered"
EXPIRED = "expired"
WITHDRAWN = "withdrawn"

#: 답이 정해져 내려갈 수 있는 상태 (C4 `approvals[]`).
SETTLED = (ANSWERED, EXPIRED, WITHDRAWN)

#: 결재를 올릴 수 있는 키 종류 (C6 §전송).
HOST_KEY_TYPES = {"bot_ui": "bot_ui", "server_runner": "server_runner"}

#: 올린 쪽이 스스로 회수할 수 있는 사유. 그 밖은 관리자만 (`admin_withdraw`).
HOST_WITHDRAW_REASONS = frozenset({"answered_in_field", "run_ended"})
ADMIN_WITHDRAW = "admin_withdraw"


# ─────────────────────────── 올리기 (POST /approvals) ───────────────────────────


def _host_key(found: Caller) -> Any:
    """결재를 올릴 수 있는 키인가 (C6 — Bot UI·서버 실행기만)."""
    if found.key is None or found.key.type not in HOST_KEY_TYPES:
        raise ApiError(403, "wrong_key_type", "결재는 Bot UI·서버 실행기 키로 올린다")
    return found.key


def _body_hash(request: ApprovalCreateRequest) -> str:
    return hashlib.sha256(
        json.dumps(request.to_json_dict(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def create(store: Store, found: Caller, raw: dict[str, Any]) -> tuple[ApprovalInfo, bool]:
    """`POST /approvals`. 두 번째 값이 `False`면 멱등으로 돌려준 기존 결재다 (200)."""
    key = _host_key(found)
    try:
        request = ApprovalCreateRequest.model_validate(raw)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "결재 요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    problems = validate_create(request)
    if problems:
        raise ApiError(422, problems[0].code or "input_invalid", problems[0].message)

    # **다른 키가 만든 실행의 결재는 받지 않는다** (C6 §소유). 기록이 아직 안 올라왔으면
    # 대조할 것이 없다 — 기록은 하트비트 **뒤에** 가므로 결재가 먼저 도착하는 것이 보통이다.
    from chaeksas.center.api.runs import owner_of  # noqa: PLC0415 — 순환 import를 피한다

    owner = owner_of(store, request.run_id)
    if owner is not None and owner != key.key_id:
        raise ApiError(403, "run_owner_mismatch", "다른 키가 만든 실행의 결재다")

    body_hash = _body_hash(request)
    before = store.row("SELECT * FROM approvals WHERE request_id = ?", (request.request_id,))
    if before is not None:
        if before["owner_key_id"] != key.key_id or before["body_hash"] != body_hash:
            raise ApiError(
                409, "idempotency_conflict", f"{request.request_id}에 다른 키·본문이 왔다"
            )
        return _info(before, store), False

    host = _host_of(store, key)
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO approvals (request_id, owner_key_id, host_type, host_id, run_id, node_id,"
            " node_instance, bpm_process_id, version, title, description, form_json, review_json,"
            " expires_at, body_hash, created_at, state)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.request_id,
                key.key_id,
                host.type,
                host.id,
                request.run_id,
                request.node_id,
                request.node_instance,
                request.bpm_process_id,
                request.version,
                request.title,
                request.description,
                dumps(request.form.to_json_dict()) if request.form else None,
                dumps(request.review) if request.review else None,
                request.expires_at,
                body_hash,
                now_iso(),
                OPEN,
            ),
        )
    return _info(_must(store, request.request_id), store), True


def _host_of(store: Store, key: Any) -> ApprovalHost:
    """올린 쪽 (C6 `host`). Bot UI는 키로 찾는다 — 신원은 키가 정한다 (C4)."""
    if key.type == "bot_ui":
        found = store.row("SELECT bot_ui_id, name FROM bot_uis WHERE key_id = ?", (key.key_id,))
        if found is not None:
            return ApprovalHost(type="bot_ui", id=str(found["bot_ui_id"]), name=str(found["name"]))
    # 등록 전이거나 서버 실행기 — 키 이름으로 적는다 (모르는 것을 지어내지 않는다).
    return ApprovalHost(type=key.type, id=key.key_id, name=key.name)


# ─────────────────────────── 읽기·답하기·회수 ───────────────────────────


def _must(store: Store, request_id: str) -> Any:
    row = store.row("SELECT * FROM approvals WHERE request_id = ?", (request_id,))
    if row is None:
        raise ApiError(404, "not_found", f"결재 {request_id}가 없다")
    return row


def get(store: Store, request_id: str) -> ApprovalInfo:
    return _info(_must(store, request_id), store)


def listing(
    store: Store,
    *,
    state: str | None = None,
    bpm_process_id: str | None = None,
    host: str | None = None,
) -> list[ApprovalInfo]:
    """`GET /approvals` (CON-04 결재함). 최신순."""
    rows = store.rows("SELECT * FROM approvals ORDER BY created_at DESC, request_id DESC")
    return [
        _info(row, store)
        for row in rows
        if (state is None or row["state"] == state)
        and (bpm_process_id is None or row["bpm_process_id"] == bpm_process_id)
        and (host is None or row["host_id"] == host)
    ]


def answer(store: Store, found: Caller, request_id: str, raw: dict[str, Any]) -> ApprovalInfo:
    """`POST /approvals/{id}/answer` — 관리자 토큰만 (C6 권한표).

    **Center가 폼으로 답을 검증한다** — 틀리면 422로 콘솔에 바로 보인다. 실행하는 쪽도 같은
    함수로 한 번 더 본다 (CMN-01과 엔진이 쓰는 `validate_answer` 그대로다).
    """
    if not found.is_admin:
        raise ApiError(403, "admin_only", "결재에 답하려면 관리자 토큰이 필요하다")
    row = _must(store, request_id)
    _refuse_if_not_open(store, row)

    try:
        request = AnswerRequest.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "답이 계약과 맞지 않는다") from e

    form = _form_of(row)
    filled = apply_defaults(form, request.answer)
    problems = validate_answer(form, filled)
    if problems:
        raise ApiError(
            422,
            "answer_invalid",
            problems[0].message,
            {"fields": [v.items[0] for v in problems if v.items]},
        )

    with store.tx() as cur:
        cur.execute(
            "UPDATE approvals SET state = ?, answer_json = ?, answered_by = ?, answered_at = ?,"
            " delivered = 0, delivery_accepted = NULL, delivery_reason = NULL WHERE request_id = ?",
            (ANSWERED, dumps(filled), found.actor, now_iso(), request_id),
        )
    return _info(_must(store, request_id), store)


def withdraw(store: Store, found: Caller, request_id: str, reason: str) -> ApprovalInfo:
    """`DELETE /approvals/{id}` — 올린 쪽은 현장·실행 사유로, 관리자는 `admin_withdraw`로.

    **관리자 회수는 실행에 영향이 있다** (C6) — 실행하는 쪽은 「답 없이 끝남」으로 받고,
    오류 경계가 없으면 실행이 실패로 끝난다. 화면이 그렇게 말한다.
    """
    row = _must(store, request_id)
    if found.is_admin:
        reason = reason or ADMIN_WITHDRAW
    elif found.key is not None:
        if row["owner_key_id"] != found.key.key_id:
            raise ApiError(403, "not_owner", "남이 올린 결재다")
        if reason not in HOST_WITHDRAW_REASONS:
            raise ApiError(
                403, "not_owner", f"올린 쪽이 쓸 수 있는 사유가 아니다: {reason or '(없음)'}"
            )
    else:
        raise ApiError(403, "forbidden", "회수할 권한이 없다")

    if row["state"] != OPEN:
        if row["state"] == ANSWERED:
            raise ApiError(409, "already_answered", "이미 답한 결재다")
        raise ApiError(409, "not_open", f"지금 상태({row['state']})에서는 회수할 수 없다")

    _set_withdrawn(store, request_id, reason)
    return _info(_must(store, request_id), store)


def _set_withdrawn(store: Store, request_id: str, reason: str) -> None:
    with store.tx() as cur:
        cur.execute(
            "UPDATE approvals SET state = ?, withdraw_reason = ?, delivered = 0 WHERE request_id = ?",
            (WITHDRAWN, reason, request_id),
        )


def _refuse_if_not_open(store: Store, row: Any) -> None:
    """답할 수 있는 상태인가. 시한이 지났으면 **그 자리에서 만료로 바꾼다.**"""
    if row["state"] == ANSWERED:
        raise ApiError(409, "already_answered", "이미 답한 결재다")
    if row["state"] != OPEN:
        raise ApiError(409, "not_open", f"지금 상태({row['state']})에서는 답할 수 없다")
    if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.fromisoformat(now_iso()):
        _expire(store, str(row["request_id"]))
        raise ApiError(409, "not_open", "시한이 지난 결재다")


def _expire(store: Store, request_id: str) -> None:
    with store.tx() as cur:
        cur.execute(
            "UPDATE approvals SET state = ?, delivered = 0 WHERE request_id = ?", (EXPIRED, request_id)
        )


# ─────────────────────────── 자동 회수 (C6 §상태 전이) ───────────────────────────


def withdraw_for_run(store: Store, run_id: str, *, event: str) -> int:
    """그 실행의 `open` 결재를 거둔다. `event`는 `run_finished`·`bot_ui_lost`다.

    **답할 수는 있지만 전달될 곳이 없는 결재를 결재함에 남기지 않는다** (C6).
    """
    reason = AUTO_WITHDRAW_REASONS.get(event)
    if reason is None:
        return 0
    rows = store.rows(
        "SELECT request_id FROM approvals WHERE run_id = ? AND state = ?", (run_id, OPEN)
    )
    for row in rows:
        _set_withdrawn(store, str(row["request_id"]), reason)
    return len(rows)


def expire_due(store: Store, *, now: str | None = None) -> int:
    """시한이 지난 `open` 결재를 만료로 바꾼다 — 그래야 실행하는 쪽이 기다림을 멈춘다."""
    edge = datetime.fromisoformat(now or now_iso())
    found = [
        row
        for row in store.rows(
            "SELECT request_id, expires_at FROM approvals WHERE state = ? AND expires_at IS NOT NULL",
            (OPEN,),
        )
        if datetime.fromisoformat(row["expires_at"]) <= edge
    ]
    for row in found:
        _expire(store, str(row["request_id"]))
    return len(found)


def purge_values(store: Store, *, now: str | None = None, days: int = VALUE_RETENTION_DAYS) -> int:
    """끝난 지 오래된 결재의 **값**(`review`·`answer`)을 지운다 (C6).

    누가·언제·결과는 남는다 — 「승인했다」는 사실은 감사에 필요하지만, 거래처 이름과 금액은
    30일 뒤까지 Center에 둘 이유가 없다.
    """
    edge = datetime.fromisoformat(now or now_iso()) - timedelta(days=days)
    found = [
        row
        for row in store.rows(
            "SELECT request_id, created_at, answered_at FROM approvals WHERE state <> ?"
            " AND values_purged_at IS NULL AND (review_json IS NOT NULL OR answer_json IS NOT NULL)",
            (OPEN,),
        )
        # 기준은 **끝난 시각**이다. 답하지 않고 만료·회수된 것은 올라온 시각으로 센다.
        if datetime.fromisoformat(str(row["answered_at"] or row["created_at"])) <= edge
    ]
    for row in found:
        with store.tx() as cur:
            cur.execute(
                "UPDATE approvals SET review_json = NULL, answer_json = NULL, values_purged_at = ?"
                " WHERE request_id = ?",
                (now or now_iso(), row["request_id"]),
            )
    return len(found)


# ─────────────────────────── 하트비트 (C4) ───────────────────────────


def heartbeat(
    store: Store, *, bot_ui_id: str, acks: list[ApprovalAck]
) -> list[ApprovalDispatch]:
    """받은 ack를 반영하고, 내려줄 결재를 고른다.

    **ack를 먼저** 본다 — 방금 받아 간 것을 다시 내려보내지 않게.
    """
    _apply_acks(store, bot_ui_id=bot_ui_id, acks=acks)
    expire_due(store)
    purge_values(store)
    return _to_dispatch(store, bot_ui_id=bot_ui_id)


def _apply_acks(store: Store, *, bot_ui_id: str, acks: list[ApprovalAck]) -> None:
    """`approval_acks` (C4). **거절은 `open`으로 되돌린다** (C6)."""
    for ack in acks:
        row = store.row(
            "SELECT * FROM approvals WHERE request_id = ? AND host_id = ?", (ack.request_id, bot_ui_id)
        )
        if row is None:
            continue  # 모르는 결재이거나 **남의 것**이다
        with store.tx() as cur:
            if ack.accepted:
                cur.execute(
                    "UPDATE approvals SET delivered = 1, delivery_accepted = 1, delivery_reason = NULL"
                    " WHERE request_id = ?",
                    (ack.request_id,),
                )
            else:
                # 받아들이지 못했다 — 사유만 남기고 **다시 답할 수 있게** 연다 (C6).
                cur.execute(
                    "UPDATE approvals SET state = ?, delivered = 0, delivery_accepted = 0,"
                    " delivery_reason = ?, answer_json = NULL, answered_by = NULL, answered_at = NULL"
                    " WHERE request_id = ?",
                    (OPEN, ack.reason, ack.request_id),
                )


def _to_dispatch(store: Store, *, bot_ui_id: str) -> list[ApprovalDispatch]:
    """답이 정해졌고 아직 ack되지 않은 결재 (C4 `approvals[]`)."""
    rows = store.rows(
        "SELECT * FROM approvals WHERE host_id = ? AND delivered = 0 AND state IN (?, ?, ?)"
        " ORDER BY created_at",
        (bot_ui_id, ANSWERED, EXPIRED, WITHDRAWN),
    )
    return [
        ApprovalDispatch(
            request_id=row["request_id"],
            state=row["state"],
            answer=loads(row["answer_json"]),
            answered_by=row["answered_by"],
            answered_at=row["answered_at"],
        )
        for row in rows
    ]


# ─────────────────────────── 응답 모양 ───────────────────────────


def _form_of(row: Any) -> Form | None:
    found = loads(row["form_json"])
    return Form.model_validate(found) if found else None


def _host_name(store: Store, row: Any) -> str | None:
    """실행하는 곳의 **지금** 이름 (CON-04). 이름은 바뀌므로 읽을 때 찾는다."""
    if row["host_type"] != "bot_ui":
        return None
    found = store.row("SELECT name FROM bot_uis WHERE bot_ui_id = ?", (row["host_id"],))
    return str(found["name"]) if found is not None else None


def _info(row: Any, store: Store | None = None) -> ApprovalInfo:
    return ApprovalInfo(
        schema=1,
        request_id=row["request_id"],
        layer="approval",  # Center는 이것만 받는다 (C6)
        run_id=row["run_id"],
        node_id=row["node_id"],
        node_instance=row["node_instance"],
        bpm_process_id=row["bpm_process_id"],
        version=row["version"],
        title=row["title"],
        description=row["description"],
        form=_form_of(row),
        review=loads(row["review_json"], {}) or {},
        expires_at=row["expires_at"],
        host=ApprovalHost(
            type=row["host_type"],
            id=row["host_id"],
            name=_host_name(store, row) if store is not None else None,
        ),
        state=row["state"],
        created_at=row["created_at"],
        answer=loads(row["answer_json"]),
        answered_by=row["answered_by"],
        answered_at=row["answered_at"],
        withdraw_reason=row["withdraw_reason"],
        delivered=bool(row["delivered"]),
        delivery_accepted=None if row["delivery_accepted"] is None else bool(row["delivery_accepted"]),
        delivery_reason=row["delivery_reason"],
    )


__all__ = [
    "ADMIN_WITHDRAW",
    "ANSWERED",
    "EXPIRED",
    "OPEN",
    "WITHDRAWN",
    "answer",
    "create",
    "expire_due",
    "get",
    "heartbeat",
    "listing",
    "purge_values",
    "withdraw",
    "withdraw_for_run",
]

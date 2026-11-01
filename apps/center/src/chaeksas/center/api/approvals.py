"""결재 — 실행하는 쪽이 올리고, 콘솔에서 답하고, 하트비트로 내려간다 (C6).

**Center로 올라오는 것은 결재(`approval`)뿐이다.** 확인(`confirmation`)은 화면 앞 사람만
답할 수 있으므로 올리지 않는다 — 올라오면 422다.

세 가지가 이 모듈의 뼈대다.

1. **답은 올린 키에게만 내려간다** (§소유) — 결재는 올린 키에 묶이고, `run_id`도 C3 소유와
   대조한다. 키가 새도 남의 결재를 가로채지 못한다.
2. **거절은 되돌림이다** — 실행하는 쪽이 답을 받아들이지 못하면(`rejected_by_host`) 곧바로
   `open`으로 돌아가고 사유만 남는다. 결재자가 고쳐서 다시 답한다.
3. **답할 곳이 없어진 결재는 자동으로 회수한다** — 실행이 끝났거나(`run_ended`) PC 실행기가
   대기열을 잃으면(`host_lost`). 답은 할 수 있는데 전달될 데가 없는 결재를 남기지 않는다.
   **끝난 실행의 결재는 다시 열리지 않는다** — 2의 되돌림은 답에만, 실행이 도는 동안에만이다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center.auth import Caller, require_on_behalf
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
    normalize_name,
    review_digest,
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
    """결재를 올릴 수 있는 키인가 (C6 — PC 실행기·서버 실행기만)."""
    if found.key is None or found.key.type not in HOST_KEY_TYPES:
        raise ApiError(403, "wrong_key_type", "결재는 PC 실행기·서버 실행기 키로 올린다")
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
            " expires_at, body_hash, created_at, state, assignees_json, review_digest)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                # 담당자는 업무 값이 아니라 사람 이름이다 — 30일 삭제 대상이 아니다 (ADR-0080).
                dumps(request.assignees) if request.assignees else None,
                # 지문은 **값을 지워도 남는다** (ADR-0083) — 업무 값이 아니라 그 값의 지문이다.
                review_digest(request.review),
            ),
        )
    return _info(_must(store, request.request_id), store), True


def _host_of(store: Store, key: Any) -> ApprovalHost:
    """올린 쪽 (C6 `host`). **신원은 키가 정한다** (C4·C12) — 등록한 쪽에게 묻는다.

    **`host_id`가 맞아야 답이 내려간다** — 하트비트가 `host_id`로 고르므로(`_to_dispatch`)
    여기서 키 이름을 적어 두면 **올린 쪽이 그 답을 영영 못 받는다**. 서버 실행기를 붙이다
    실제로 그랬다.
    """
    from chaeksas.center.api import bot_ui, server_runner  # noqa: PLC0415 — 순환 import를 피한다

    if key.type == "bot_ui":
        found = bot_ui.id_for_key(store, key.key_id)
        if found is not None:
            row = store.row("SELECT name FROM bot_uis WHERE bot_ui_id = ?", (found,))
            return ApprovalHost(
                type="bot_ui", id=found, name=str(row["name"]) if row else key.name
            )
    elif key.type == "server_runner":
        found = server_runner.id_for_key(store, key.key_id)
        if found is not None:
            row = store.row(
                "SELECT name FROM server_runners WHERE server_runner_id = ?", (found,)
            )
            return ApprovalHost(
                type="server_runner", id=found, name=str(row["name"]) if row else key.name
            )
    # 등록 전이다 — 키 이름으로 적는다 (모르는 것을 지어내지 않는다). 그 결재의 답은
    # 등록하기 전까지 내려가지 않는다.
    return ApprovalHost(type=key.type, id=key.key_id, name=key.name)


# ─────────────────────────── 읽기·답하기·회수 ───────────────────────────


def _must(store: Store, request_id: str) -> Any:
    row = store.row("SELECT * FROM approvals WHERE request_id = ?", (request_id,))
    if row is None:
        raise ApiError(404, "not_found", f"결재 {request_id}가 없다")
    return row


def _assignees_of(row: Any) -> list[str]:
    return list(loads(row["assignees_json"], []) or [])


def _company_of(store: Store, row: Any) -> str | None:
    """그 결재가 속한 회사 — 그 실행의 업무 자리에서 (C16). 실행 목록과 **같은 함수**다."""
    from chaeksas.center.api.runs import place_of_run  # noqa: PLC0415 — 순환 import를 피한다

    return place_of_run(store, str(row["run_id"]), row["bpm_process_id"])[0]


def get(
    store: Store, request_id: str, *, on_behalf: str | None = None, company: str | None = None
) -> ApprovalInfo:
    """하나. `on_behalf`가 있으면(대리 답용 키) **그 사람이 담당인 결재만** — 아니면 404 (ADR-0081).

    `company`가 있으면(회사가 정해진 계정) **제 회사 실행의 결재만**이다 (C16)."""
    row = _must(store, request_id)
    if (on_behalf is not None and on_behalf not in _assignees_of(row)) or (
        company is not None and _company_of(store, row) != company
    ):
        raise ApiError(404, "not_found", f"결재 {request_id}가 없다")  # 있다는 것조차 알리지 않는다
    return _info(row, store)


def listing(
    store: Store,
    *,
    state: str | None = None,
    bpm_process_id: str | None = None,
    host: str | None = None,
    assignee: str | None = None,
    on_behalf: str | None = None,
    company: str | None = None,
) -> list[ApprovalInfo]:
    """`GET /approvals` (CON-04 결재함). 최신순.

    `assignee`는 그 이름이 담당자에 있는 것만 (ADR-0080). `on_behalf`(대리 답용 키)가 있으면
    거르기가 **그 이름으로 고정된다** — 다른 이름을 물으면 403 `not_assignee` (ADR-0081).
    """
    wanted = normalize_name(assignee) if assignee else None
    if on_behalf is not None:
        if wanted is not None and wanted != on_behalf:
            raise ApiError(403, "not_assignee", "대리 답용 키는 그 사람의 결재만 본다")
        wanted = on_behalf
    rows = store.rows("SELECT * FROM approvals ORDER BY created_at DESC, request_id DESC")
    return [
        _info(row, store)
        for row in rows
        if (state is None or row["state"] == state)
        and (bpm_process_id is None or row["bpm_process_id"] == bpm_process_id)
        and (host is None or row["host_id"] == host)
        and (wanted is None or wanted in _assignees_of(row))
        and (company is None or _company_of(store, row) == company)
    ]


def answer(store: Store, found: Caller, request_id: str, raw: dict[str, Any]) -> ApprovalInfo:
    """`POST /approvals/{id}/answer` — 관리자 토큰, 또는 **담당자 대신** 대리 답용 키 (C6 권한표).

    **Center가 폼으로 답을 검증한다** — 틀리면 422로 콘솔에 바로 보인다. 실행하는 쪽도 같은
    함수로 한 번 더 본다 (CMN-01과 엔진이 쓰는 `validate_answer` 그대로다).

    **관리자 토큰은 담당자로 막지 않는다** (ADR-0080 — 콘솔의 이름은 자칭이다). 막는 것은
    대리 답 하나다: 그 사람이 담당자여야 하고, 담당자가 없는 결재는 콘솔에서만 답한다 (ADR-0081).
    """
    via: str | None = None
    if found.is_relay:
        answered_by = require_on_behalf(found)
        row = _must(store, request_id)
        if answered_by not in _assignees_of(row):
            raise ApiError(403, "not_assignee", f"「{answered_by}」은 이 결재의 담당자가 아니다")
        assert found.key is not None  # is_relay가 본다
        via = found.key.name
    elif found.is_admin:
        answered_by = found.actor
        row = _must(store, request_id)
        if found.company is not None and _company_of(store, row) != found.company:
            raise ApiError(404, "not_found", f"결재 {request_id}가 없다")
    else:
        raise ApiError(403, "admin_only", "결재에 답하려면 관리자 토큰이나 대리 답용 키가 필요하다")
    _refuse_if_not_open(store, row)
    if _run_ended(store, str(row["run_id"])):
        # 기다리는 이가 없다 — 받아 두면 효과 없이 200이 된다 (C6). 그 자리에서 거둔다.
        _set_withdrawn(store, request_id, AUTO_WITHDRAW_REASONS["run_finished"])
        raise ApiError(409, "not_open", "실행이 끝난 결재다")

    try:
        request = AnswerRequest.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "답이 계약과 맞지 않는다") from e

    if request.if_review_digest is not None and request.if_review_digest != _digest_of(row):
        # **답하는 쪽이 본 것과 다르다** (ADR-0083) — 받지 않는다. 다시 읽어 사람에게 보여야 한다.
        raise ApiError(409, "review_changed", "본 검토 자료가 지금 결재와 다르다")

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
            "UPDATE approvals SET state = ?, answer_json = ?, answered_by = ?, answered_via = ?,"
            " answered_at = ?, delivered = 0, delivery_accepted = NULL, delivery_reason = NULL"
            " WHERE request_id = ?",
            (ANSWERED, dumps(filled), answered_by, via, now_iso(), request_id),
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


def withdraw_ended_runs(store: Store) -> int:
    """**끝난 실행인데 `open`인 결재**를 거둔다 — 하트비트마다 쓴다 (C6 `run_ended`).

    `withdraw_for_run`은 `run_finished`가 닿는 그 자리에서만 돈다. 결재가 그보다 늦게 닿았거나
    (보내기 차례는 정해져 있지 않다) 되돌림 규칙이 고쳐지기 전에 다시 열린 것은 거기서 빠진다.
    """
    rows = store.rows("SELECT request_id, run_id FROM approvals WHERE state = ?", (OPEN,))
    ended = [row for row in rows if _run_ended(store, str(row["run_id"]))]
    for row in ended:
        _set_withdrawn(store, str(row["request_id"]), AUTO_WITHDRAW_REASONS["run_finished"])
    return len(ended)


def _run_ended(store: Store, run_id: str) -> bool:
    """C3 `run_finished`를 받은 실행인가 — 요약에 `finished_at`이 있다 (`runs.ingest`가 거두는 기준과 같다)."""
    found = store.row("SELECT summary_json FROM runs WHERE run_id = ?", (run_id,))
    return found is not None and bool((loads(found["summary_json"], {}) or {}).get("finished_at"))


def reclaim_host(store: Store, *, host_id: str, reason: str) -> int:
    """그 **올린 쪽**이 사라졌다 — 기다리는 결재를 모두 거둔다 (C6 `host_lost`).

    CON-12 「유실 처리」가 부른다 (C12). 실행마다 거두는 `withdraw_for_run`과 달리 **그 호스트가
    올린 것 전부**를 본다 — 유실 처리는 「이 실행기의 실행을 다 닫는다」이고, 작업과 짝이 맞지
    않는 결재(수동 실행·메시지 시작)도 전달될 곳이 없다.
    """
    rows = store.rows(
        "SELECT request_id FROM approvals WHERE host_id = ? AND state = ?", (host_id, OPEN)
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
    store: Store, *, host_id: str, acks: list[ApprovalAck]
) -> list[ApprovalDispatch]:
    """받은 ack를 반영하고, 내려줄 결재를 고른다.

    **ack를 먼저** 본다 — 방금 받아 간 것을 다시 내려보내지 않게.
    """
    _apply_acks(store, host_id=host_id, acks=acks)
    expire_due(store)
    withdraw_ended_runs(store)
    purge_values(store)
    return _to_dispatch(store, host_id=host_id)


def _apply_acks(store: Store, *, host_id: str, acks: list[ApprovalAck]) -> None:
    """`approval_acks` (C4). **답의 거절은 `open`으로 되돌린다** (C6).

    **되돌리는 것은 답뿐이다** — 회수·만료는 실행하는 쪽이 기다리지 않아도 할 일이 없으므로
    거절 ack도 「받아 갔다」로 적는다. 그리고 **끝난 실행의 답은 되돌리지 않고 거둔다** — 다시
    열면 결재함에 「대기」로 보이고 답해도 아무 일이 없다 (서버 실행기가 이미 닫은 실행의 회수에
    `not_waiting`으로 답해 취소된 실행의 결재가 되살아났다).
    """
    for ack in acks:
        row = store.row(
            "SELECT * FROM approvals WHERE request_id = ? AND host_id = ?", (ack.request_id, host_id)
        )
        if row is None:
            continue  # 모르는 결재이거나 **남의 것**이다
        reopen = not ack.accepted and row["state"] == ANSWERED
        if reopen and _run_ended(store, str(row["run_id"])):
            with store.tx() as cur:
                cur.execute(
                    "UPDATE approvals SET state = ?, withdraw_reason = ?, delivered = 0, delivery_accepted = 0,"
                    " delivery_reason = ? WHERE request_id = ?",
                    (WITHDRAWN, AUTO_WITHDRAW_REASONS["run_finished"], ack.reason, ack.request_id),
                )
            continue
        with store.tx() as cur:
            if not reopen:
                cur.execute(
                    "UPDATE approvals SET delivered = 1, delivery_accepted = 1, delivery_reason = NULL"
                    " WHERE request_id = ?",
                    (ack.request_id,),
                )
            else:
                # 받아들이지 못했다 — 사유만 남기고 **다시 답할 수 있게** 연다 (C6).
                cur.execute(
                    "UPDATE approvals SET state = ?, delivered = 0, delivery_accepted = 0,"
                    " delivery_reason = ?, answer_json = NULL, answered_by = NULL, answered_via = NULL,"
                    " answered_at = NULL"
                    " WHERE request_id = ?",
                    (OPEN, ack.reason, ack.request_id),
                )


def _to_dispatch(store: Store, *, host_id: str) -> list[ApprovalDispatch]:
    """답이 정해졌고 아직 ack되지 않은 결재 (C4 `approvals[]`)."""
    rows = store.rows(
        "SELECT * FROM approvals WHERE host_id = ? AND delivered = 0 AND state IN (?, ?, ?)"
        " ORDER BY created_at",
        (host_id, ANSWERED, EXPIRED, WITHDRAWN),
    )
    return [
        ApprovalDispatch(
            request_id=row["request_id"],
            state=row["state"],
            answer=loads(row["answer_json"]),
            answered_by=row["answered_by"],
            answered_at=row["answered_at"],
            answered_via=row["answered_via"],
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


def _digest_of(row: Any) -> str | None:
    """저장된 지문. 이 칸이 생기기 전의 결재는 **남은 값으로** 읽을 때 계산한다 (ADR-0083)."""
    if row["review_digest"]:
        return str(row["review_digest"])
    if row["values_purged_at"]:
        return None  # 값도 지문도 없다 — 맞춰 볼 근거가 없다
    return review_digest(loads(row["review_json"], {}) or {})


def _requested_by(store: Store, run_id: str) -> str | None:
    """그 실행을 시작한 작업의 `requested_by` (ADR-0080). **읽을 때** 붙이고 저장하지 않는다."""
    found = store.row(
        "SELECT requested_by FROM jobs WHERE run_id = ? ORDER BY requested_at LIMIT 1", (run_id,)
    )
    return str(found["requested_by"]) if found is not None else None


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
        assignees=_assignees_of(row),
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
        answered_via=row["answered_via"],
        review_digest=_digest_of(row),
        requested_by=_requested_by(store, row["run_id"]) if store is not None else None,
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
    "withdraw_ended_runs",
    "withdraw_for_run",
]

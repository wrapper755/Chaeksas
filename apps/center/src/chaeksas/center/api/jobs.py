"""작업 지시 — 「언제 돌려라」 (C5 `/jobs`).

**서명이 필요 없다.** 배포는 「무엇을 실행해도 되는가」라서 Admin 서명이 유일한 관문이지만
(C2), 작업은 **이미 배포된 것**을 지금 돌리라는 말일 뿐이다 — 배포되지 않은 Bot은 작업으로도
돌릴 수 없으므로 토큰 권한(C5 권한표: 관리자 토큰·연동용 키)으로 충분하다.

Center는 작업을 **밀지 않는다** (ADR-0007). 하트비트 응답에 실어 두고 ack를 기다린다 —
**ack가 올 때까지 매번 다시 싣는다** (C4). 그래서 「전달했다」와 「받았다」가 따로 있다
(`dispatched` / `queued`·`accepted`).

실행의 성패는 작업 상태가 **아니다** (C5) — C3 `run_finished`가 정하고 `run_status`에 보인다.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center.api import deployments
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.bot_ui import HeartbeatRequest, JobAck, JobDispatch
from chaeksas.contracts.center_api import (
    IDEMPOTENCY_WINDOW_DAYS,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    JobCreateRequest,
    JobInfo,
    JobTarget,
    cancel_outcome,
    validate_job_create,
)

#: 작업 상태 (C5 「작업 상태」). 열린 문자열이지만 Center가 **짓는** 것은 이 넷뿐이다.
PENDING = "pending"
DISPATCHED = "dispatched"
QUEUED = "queued"
ACCEPTED = "accepted"
REJECTED = "rejected"
EXPIRED = "expired"
CANCELLED = "cancelled"

#: 아직 끝나지 않은 작업 — 하트비트가 들여다보는 것들.
LIVE_STATES = (PENDING, DISPATCHED, QUEUED, ACCEPTED)

#: 취소 결과 (C5 `cancel_result`).
CANCEL_DONE = "cancelled"
CANCEL_REFUSED = "refused_already_started"

#: 연동용 키 종류 (C5 권한표 — `POST /jobs`와 **자기 것만** 읽기·취소).
INTEGRATION = "integration"

#: 맞추기 규칙 — 하트비트 **두 번 연속** 보이지 않고 ack도 없으면 잃어버린 것으로 본다 (C4).
LOST_AFTER = 2


def new_job_id() -> str:
    return f"job_{secrets.token_hex(4)}"


# ─────────────────────────── 권한 (C5 권한표) ───────────────────────────


def owner_of(found: Caller) -> str:
    """멱등 키의 범위이자 「자기 것」의 주인 (C5 — 부른 쪽 키, 또는 행위자)."""
    if found.key is not None:
        return f"key:{found.key.key_id}"
    return f"actor:{found.actor}"


def _scope(found: Caller, *, write: bool) -> str | None:
    """볼·바꿀 수 있는 범위. `None`이면 전부, 문자열이면 그 주인의 것만 (C5 권한표).

    - 관리자 토큰: 전부 (쓰기 포함)
    - 읽기 토큰: 전부, **GET만**
    - 연동용 키: 만들기와 **자기 것만** 읽기·취소
    - 그 밖의 Center API 키(Studio·Bot UI·서버 실행기): 작업은 다루지 못한다
    """
    if found.is_admin:
        return None
    if found.kind == "read":
        if write:
            raise ApiError(403, "forbidden", "읽기 토큰으로는 작업을 만들거나 취소할 수 없다")
        return None
    if found.key is not None and found.key.type == INTEGRATION:
        return owner_of(found)
    raise ApiError(403, "forbidden", "작업은 관리자 토큰이나 연동용 키로 다룬다")


# ─────────────────────────── 만들기 (POST /jobs) ───────────────────────────


def _body_hash(request: JobCreateRequest) -> str:
    """멱등 충돌 판정용 — 멱등 키 자신은 빼고 센다 (같은 키에 **다른 본문**이면 409)."""
    payload = {k: v for k, v in request.to_json_dict().items() if k != "idempotency_key"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _remembered(store: Store, *, owner: str, key: str, now: str) -> Any:
    """같은 주인이 같은 멱등 키로 최근 7일 안에 만든 작업 (C5)."""
    edge = datetime.fromisoformat(now) - timedelta(days=IDEMPOTENCY_WINDOW_DAYS)
    for row in store.rows(
        "SELECT * FROM jobs WHERE owner = ? AND idempotency_key = ? ORDER BY requested_at DESC",
        (owner, key),
    ):
        if datetime.fromisoformat(row["requested_at"]) >= edge:
            return row
    return None


def create(store: Store, found: Caller, raw: dict[str, Any]) -> tuple[JobInfo, bool]:
    """`POST /jobs`. 두 번째 값이 `False`면 멱등으로 돌려준 기존 작업이다 (200)."""
    _scope(found, write=True)

    if "inputs" in raw and not isinstance(raw["inputs"], dict):
        # 계약이 코드를 따로 두었다 — 「뭐가 틀렸는지」를 부르는 쪽이 바로 알 수 있게 (C5).
        raise ApiError(422, "inputs_not_object", "`inputs`는 JSON 객체여야 한다")
    try:
        request = JobCreateRequest.model_validate(raw)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "작업 요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    now = now_iso()
    owner = owner_of(found)
    if request.idempotency_key:
        before = _remembered(store, owner=owner, key=request.idempotency_key, now=now)
        if before is not None:
            if before["body_hash"] != _body_hash(request):
                raise ApiError(
                    409,
                    "idempotency_conflict",
                    f"멱등 키 「{request.idempotency_key}」에 다른 본문이 왔다 (기존 {before['job_id']})",
                )
            return info_of(store, before), False

    target = request.target
    version = _resolved_version(store, request)

    job_id = new_job_id()
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id, inputs_json,"
            " expires_at, note, owner, idempotency_key, body_hash, requested_by, requested_at, state)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                request.bpm_process_id,
                version,
                target.type,
                target.id,
                dumps(request.inputs),
                request.expires_at,
                request.note,
                owner,
                request.idempotency_key,
                _body_hash(request),
                # **행위자는 본문에서 받지 않는다** (C5) — 키 이름이나 X-CHK-Actor가 정한다.
                found.actor,
                now,
                PENDING,
            ),
        )
    return info_of(store, _must(store, job_id)), True


def _resolved_version(store: Store, request: JobCreateRequest) -> str:
    """어느 버전을 돌릴지 정한다 — 대상이 있는지, 배포돼 있는지까지 본다 (C5)."""
    target = request.target
    if target.type == "server_runner":
        # 서버 실행은 M7부터다 (ADR-0016) — 배포와 같은 사유로 막는다.
        raise ApiError(422, "server_runner_not_available", "서버 실행은 M7부터다 (ADR-0016)")
    if target.type != "bot_ui":
        raise ApiError(422, "target_mismatch", f"모르는 대상 종류다: {target.type}")

    target_id = str(target.id or "")
    if store.row("SELECT bot_ui_id FROM bot_uis WHERE bot_ui_id = ?", (target_id,)) is None:
        raise ApiError(404, "not_found", f"Bot UI {target_id}가 없다")

    deployed = deployments.versions_for(
        store, target_type="bot_ui", target_id=target_id, bpm_process_id=request.bpm_process_id
    )
    problems = validate_job_create(request, deployed_versions=deployed)
    if problems:
        first = problems[0]
        raise ApiError(422, first.code or "no_deployment", first.message, {"versions": first.items})
    # `version`을 비웠으면 배포된 하나로 **여기서 정한다** — 내려갈 때 다시 고르지 않는다.
    return request.version or deployed[0]


# ─────────────────────────── 읽기·취소 ───────────────────────────


def _must(store: Store, job_id: str) -> Any:
    row = store.row("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    if row is None:
        raise ApiError(404, "not_found", f"작업 {job_id}가 없다")
    return row


def get(store: Store, found: Caller, job_id: str, *, write: bool = False) -> JobInfo:
    scope = _scope(found, write=write)
    row = _must(store, job_id)
    if scope is not None and row["owner"] != scope:
        # **남의 작업은 없는 것과 같다** — 있다는 것조차 알려 주지 않는다 (C5 「자기 것만」).
        raise ApiError(404, "not_found", f"작업 {job_id}가 없다")
    return info_of(store, row)


def listing(
    store: Store,
    found: Caller,
    *,
    state: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    bpm_process_id: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
) -> list[JobInfo]:
    scope = _scope(found, write=False)
    # 상태는 쉼표로 여럿 (C5 — CON-05의 상태 필터가 여러 개를 고른다).
    states = {one.strip() for one in state.split(",") if one.strip()} if state else None
    rows = store.rows("SELECT * FROM jobs ORDER BY requested_at DESC, job_id DESC")
    picked = [
        row
        for row in rows
        if (scope is None or row["owner"] == scope)
        and (not states or row["state"] in states)
        and (target_type is None or row["target_type"] == target_type)
        and (target_id is None or row["target_id"] == target_id)
        and (bpm_process_id is None or row["bpm_process_id"] == bpm_process_id)
    ]
    window = max(0, min(limit, LIST_LIMIT_MAX))
    return [info_of(store, row) for row in picked[offset : offset + window]]


def cancel(store: Store, found: Caller, job_id: str) -> tuple[JobInfo, int]:
    """`DELETE /jobs/{id}` (C5 「취소」 표). 두 번째 값이 응답 코드다 (200 / 202).

    `dispatched`·`queued`는 **Center 혼자 끝낼 수 없다** — 그사이 실행을 시작했을 수 있어서,
    현장에 물어보고(`cancel_jobs`) ack를 기다린다. 시작된 것은 거절이고 작업은 `accepted`로
    남는다 (실행 중인 Bot을 멈추는 것은 schema 1 범위 밖).
    """
    found_job = get(store, found, job_id, write=True)
    status, code = cancel_outcome(found_job.state)
    if code is not None:
        raise ApiError(409, code, f"지금 상태({found_job.state})에서는 취소할 수 없다")

    with store.tx() as cur:
        if status == 200:
            cur.execute(
                "UPDATE jobs SET state = ?, cancel_requested = 1, cancel_result = ?, settled = 1"
                " WHERE job_id = ?",
                (CANCELLED, CANCEL_DONE, job_id),
            )
        else:
            cur.execute("UPDATE jobs SET cancel_requested = 1 WHERE job_id = ?", (job_id,))
    return info_of(store, _must(store, job_id)), status


# ─────────────────────────── 하트비트 (C4) ───────────────────────────


def heartbeat(
    store: Store, *, bot_ui_id: str, request: HeartbeatRequest, disabled: bool
) -> tuple[list[JobDispatch], list[str]]:
    """하트비트 한 번 — 받은 ack를 반영하고, 내려줄 작업과 취소 지시를 고른다.

    **순서가 중요하다.** ack를 먼저 반영해야 맞추기가 방금 온 소식을 못 봤다고 오해하지 않고,
    만료를 그다음에 봐야 이미 끝난 것을 다시 만료시키지 않는다.
    """
    acked = _apply_acks(store, bot_ui_id=bot_ui_id, acks=request.job_acks)
    _expire_due(store, bot_ui_id=bot_ui_id, now=now_iso())

    seen = {item.job_id for item in request.queue.items if item.job_id}
    if request.current_run is not None and request.current_run.job_id:
        seen.add(request.current_run.job_id)
    _reconcile(store, bot_ui_id=bot_ui_id, seen=seen | acked)

    return _to_dispatch(store, bot_ui_id=bot_ui_id, disabled=disabled), _to_cancel(store, bot_ui_id=bot_ui_id)


def _apply_acks(store: Store, *, bot_ui_id: str, acks: list[JobAck]) -> set[str]:
    """받은 ack를 반영한다 (C4 `JobAck.result`). 돌려주는 것은 이번에 소식이 온 작업들이다.

    **같은 ack를 다시 보내도 한 번만 반영한다** (C4 멱등성) — 값을 덮어쓸 뿐이라 저절로 그렇다.
    """
    touched: set[str] = set()
    for ack in acks:
        row = store.row(
            "SELECT * FROM jobs WHERE job_id = ? AND target_id = ?", (ack.job_id, bot_ui_id)
        )
        if row is None:
            # 모르는 작업이거나 **남의 작업**이다 — 다른 PC의 작업을 ack하지 못한다.
            continue
        touched.add(ack.job_id)
        changes = _ack_changes(row, ack)
        if not changes:
            continue
        columns = ", ".join(f"{name} = ?" for name in changes)
        with store.tx() as cur:
            cur.execute(
                f"UPDATE jobs SET {columns} WHERE job_id = ?", (*changes.values(), ack.job_id)
            )
    return touched


#: 작업 상태를 정하는 ack 결과 (C4). 나머지(`finished`·`failed`·모르는 값)는 **실행의**
#: 결과이지 작업의 결과가 아니다 (C5).
STATE_ACKS = frozenset({"queued", "started", "rejected", "expired", "cancelled", "cancel_refused"})


def _ack_changes(row: Any, ack: JobAck) -> dict[str, Any]:
    """ack 하나가 바꾸는 칸들 (C4 작업 상태 흐름)."""
    if ack.result == "started":
        # **시작했다는 말은 언제나 이긴다** — 실제로 돌고 있는 것을 Center가 부정할 수 없다
        # (만료·잃어버림으로 끝내 두었더라도 현장이 옳다).
        return {
            "state": ACCEPTED,
            "run_id": ack.run_id,
            "queue_position": None,
            "settled": 0,
            "misses": 0,
        }
    if ack.result not in STATE_ACKS:
        # **실행의 성패는 작업 상태가 아니다** (C5) — `run_status`에만 적고 맞추기를 멈춘다
        # (끝난 실행을 「잃어버렸다」고 하지 않게).
        return {"run_status": ack.result, "settled": 1, "misses": 0}
    if row["settled"]:
        # 마지막 말은 이미 나왔다 — **밀린 ack가 그것을 지우지 못한다.**
        return {}
    if ack.result == "queued":
        if row["state"] == ACCEPTED:
            return {}  # 되돌리지 않는다
        return {"state": QUEUED, "queue_position": ack.position, "misses": 0}
    if ack.result == "rejected":
        return {"state": REJECTED, "state_reason": ack.reason, "settled": 1, "misses": 0}
    if ack.result == "expired":
        return {"state": EXPIRED, "settled": 1, "misses": 0}
    if ack.result == "cancelled":
        return {"state": CANCELLED, "cancel_result": CANCEL_DONE, "settled": 1, "misses": 0}
    # `cancel_refused` — 작업은 **`accepted` 그대로**다 (C5 「취소」 표).
    return {"cancel_requested": 1, "cancel_result": CANCEL_REFUSED, "misses": 0}


def _expire_due(store: Store, *, bot_ui_id: str, now: str) -> None:
    """`expires_at`까지 시작하지 못한 것은 `expired`다 (C5).

    **실행 중인 것(`accepted`)은 건드리지 않는다** — 이미 시작했으면 만료가 아니다.
    """
    edge = datetime.fromisoformat(now)
    for row in store.rows(
        "SELECT job_id, expires_at FROM jobs WHERE target_id = ? AND settled = 0"
        " AND state IN (?, ?, ?) AND expires_at IS NOT NULL",
        (bot_ui_id, PENDING, DISPATCHED, QUEUED),
    ):
        if datetime.fromisoformat(row["expires_at"]) > edge:
            continue
        with store.tx() as cur:
            cur.execute(
                "UPDATE jobs SET state = ?, settled = 1 WHERE job_id = ?", (EXPIRED, row["job_id"])
            )


def _reconcile(store: Store, *, bot_ui_id: str, seen: set[str]) -> None:
    """맞추기 규칙 (C4) — 넘겨준 작업이 **소리 없이 사라지지 않게** 한다.

    Bot UI가 비정상 종료로 대기열을 잃으면 작업은 영원히 `queued`로 남는다. 두 번 연속
    하트비트에서 대기열·실행 자리에 보이지 않고 ack도 없으면 `rejected` + `bot_ui_lost`다.
    """
    for row in store.rows(
        "SELECT job_id, misses, run_id FROM jobs WHERE target_id = ? AND settled = 0 AND state IN (?, ?)",
        (bot_ui_id, QUEUED, ACCEPTED),
    ):
        if row["job_id"] in seen:
            if row["misses"]:
                with store.tx() as cur:
                    cur.execute("UPDATE jobs SET misses = 0 WHERE job_id = ?", (row["job_id"],))
            continue
        misses = int(row["misses"]) + 1
        with store.tx() as cur:
            if misses >= LOST_AFTER:
                cur.execute(
                    "UPDATE jobs SET state = ?, state_reason = ?, settled = 1, misses = ?"
                    " WHERE job_id = ?",
                    (REJECTED, "bot_ui_lost", misses, row["job_id"]),
                )
            else:
                cur.execute("UPDATE jobs SET misses = ? WHERE job_id = ?", (misses, row["job_id"]))
        if misses >= LOST_AFTER and row["run_id"]:
            # 대기열을 잃었으면 그 실행의 결재도 전달될 곳이 없다 (C6 `host_lost`).
            from chaeksas.center.api import approvals  # noqa: PLC0415 — 순환 import를 피한다

            approvals.withdraw_for_run(store, str(row["run_id"]), event="bot_ui_lost")


def _to_dispatch(store: Store, *, bot_ui_id: str, disabled: bool) -> list[JobDispatch]:
    """내려줄 작업 (C4 `jobs`) — **ack가 올 때까지 매번 실린다**.

    비활성화된 Bot UI에는 **새 작업을 보내지 않는다** (C5 CON-03). 작업은 `pending`으로 남아
    기다린다 — 되살리려고 다시 만들 필요가 없다.
    """
    if disabled:
        return []
    out = []
    for row in store.rows(
        "SELECT * FROM jobs WHERE target_id = ? AND settled = 0 AND cancel_requested = 0"
        " AND state IN (?, ?) ORDER BY requested_at",
        (bot_ui_id, PENDING, DISPATCHED),
    ):
        if row["state"] == PENDING:
            with store.tx() as cur:
                cur.execute(
                    "UPDATE jobs SET state = ?, dispatched_at = ? WHERE job_id = ?",
                    (DISPATCHED, now_iso(), row["job_id"]),
                )
        out.append(
            JobDispatch(
                job_id=row["job_id"],
                bpm_process_id=row["bpm_process_id"],
                version=row["version"],
                inputs=loads(row["inputs_json"], {}) or {},
                requested_by=row["requested_by"],
                requested_at=row["requested_at"],
                expires_at=row["expires_at"],
                note=row["note"],
            )
        )
    return out


def _to_cancel(store: Store, *, bot_ui_id: str) -> list[str]:
    """취소 지시 (C4 `cancel_jobs`) — 아직 답을 듣지 못한 것만.

    **`accepted`도 보낸다.** 취소 요청과 `started` ack는 엇갈리기 마련이고, 그때 「이미
    시작했다」고 말해 줄 수 있는 쪽은 현장뿐이다 (`cancel_refused` → `refused_already_started`).
    답이 오면 `cancel_result`가 차서 더 내려가지 않는다.
    """
    return [
        str(row["job_id"])
        for row in store.rows(
            "SELECT job_id FROM jobs WHERE target_id = ? AND settled = 0 AND cancel_requested = 1"
            " AND cancel_result IS NULL AND state IN (?, ?, ?) ORDER BY requested_at",
            (bot_ui_id, DISPATCHED, QUEUED, ACCEPTED),
        )
    ]


# ─────────────────────────── 응답 모양 ───────────────────────────


def info_of(store: Store, row: Any) -> JobInfo:
    """`JobInfo` 한 줄 (C5). `run_status`는 **C3가 원본**이고 ack는 거들 뿐이다."""
    run_status = row["run_status"]
    if row["run_id"]:
        found = store.row("SELECT summary_json FROM runs WHERE run_id = ?", (row["run_id"],))
        if found is not None:
            run_status = (loads(found["summary_json"], {}) or {}).get("status") or run_status
    return JobInfo(
        job_id=row["job_id"],
        bpm_process_id=row["bpm_process_id"],
        version=row["version"],
        target=JobTarget(type=row["target_type"], id=row["target_id"]),
        inputs=loads(row["inputs_json"], {}) or {},
        expires_at=row["expires_at"],
        note=row["note"],
        idempotency_key=row["idempotency_key"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        state=row["state"],
        state_reason=row["state_reason"],
        cancel_requested=bool(row["cancel_requested"]),
        cancel_result=row["cancel_result"],
        queue_position=row["queue_position"],
        dispatched_at=row["dispatched_at"],
        run_id=row["run_id"],
        run_status=run_status,
    )


__all__ = [
    "ACCEPTED",
    "CANCELLED",
    "CANCEL_DONE",
    "CANCEL_REFUSED",
    "DISPATCHED",
    "EXPIRED",
    "INTEGRATION",
    "LIVE_STATES",
    "LOST_AFTER",
    "PENDING",
    "QUEUED",
    "REJECTED",
    "cancel",
    "create",
    "get",
    "heartbeat",
    "info_of",
    "listing",
    "new_job_id",
    "owner_of",
]

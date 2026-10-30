"""메시지 — 「이 일이 일어났다」 (C12 §메시지, `POST /api/v1/messages`).

**서명이 없다** (작업과 같다, C5 권한표) — 무엇을 실행해도 되는가는 배포가 정했고, 메시지는
이미 배포된 BPM 프로세스를 깨우거나 그 BPM 프로세스의 시작 이벤트를 울리는 말일 뿐이다. 관문은 토큰 권한이다
(관리자 토큰·연동용 키).

**가는 길이 둘이다.**

| | 간 곳 | 어떻게 |
| --- | --- | --- |
| 기다리는 실행이 있다 | `delivered_to: "run"` | 그 실행기의 하트비트 `messages[]`로 내려간다 |
| 메시지 시작 트리거다 | `delivered_to: "new_job"` | **`POST /jobs`와 같은 함수**로 작업을 만든다 |

둘째를 작업으로 바꾸는 것이 중요하다 — 그래야 배포 검사·빈자리·BPM 프로세스별 상한이 **한 자리**에
남는다 (여기서 따로 실행을 띄우면 상한을 모르는 둘째 길이 생긴다).

Center는 메시지를 **밀지 않는다** (ADR-0007) — 하트비트 응답에 실어 두고 **ack가 올 때까지
매번 다시 싣는다** (작업과 같다). 그래서 실행기는 지금 넣을 수 없는 메시지를 **ack하지 않고
그냥 둔다**.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center.api import deployments, jobs
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.center_api import IDEMPOTENCY_WINDOW_DAYS
from chaeksas.contracts.server_runner import (
    MessageAck,
    MessageDispatch,
    MessageRequest,
    MessageResponse,
    WaitingRun,
    pick_message_target,
)

#: 행 상태. `pending`만 내려간다.
PENDING = "pending"
DONE = "done"
REFUSED = "refused"

#: C12 §메시지의 `delivered_to`.
TO_RUN = "run"
TO_JOB = "new_job"


def new_message_id() -> str:
    return f"msg_{secrets.token_hex(4)}"


# ─────────────────────────── 권한 (C5 권한표) ───────────────────────────


def _guard(found: Caller) -> str:
    """부를 수 있는 쪽인가 — 돌려주는 것은 멱등 키의 범위이자 「자기 것」의 주인이다.

    **작업과 같은 권한이다** (C5 권한표) — 관리자 토큰이거나 연동용 키다. 읽기 토큰은 GET만이고,
    현장 키(PC 실행기·서버 실행기·Studio)로는 메시지를 넣을 수 없다 (넣을 수 있으면 현장 키 하나로
    남의 BPM 프로세스를 깨울 수 있다).
    """
    if found.is_admin:
        return jobs.owner_of(found)
    if found.kind == "read":
        raise ApiError(403, "forbidden", "읽기 토큰으로는 메시지를 넣을 수 없다")
    if found.key is not None and found.key.type == jobs.INTEGRATION:
        return jobs.owner_of(found)
    raise ApiError(403, "forbidden", "메시지는 관리자 토큰이나 연동용 키로 넣는다")


def _body_hash(request: MessageRequest) -> str:
    """멱등 충돌 판정용 — 멱등 키 자신은 빼고 센다 (C5와 같다)."""
    payload = {k: v for k, v in request.to_json_dict().items() if k != "idempotency_key"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _remembered(store: Store, *, owner: str, key: str, now: str) -> Any:
    """같은 주인이 같은 멱등 키로 최근 7일 안에 넣은 메시지 (C5와 같은 규칙)."""
    edge = datetime.fromisoformat(now) - timedelta(days=IDEMPOTENCY_WINDOW_DAYS)
    for row in store.rows(
        "SELECT * FROM messages WHERE owner = ? AND idempotency_key = ? ORDER BY received_at DESC",
        (owner, key),
    ):
        if datetime.fromisoformat(str(row["received_at"])) >= edge:
            return row
    return None


# ─────────────────────────── 넣기 (POST /messages) ───────────────────────────


def create(store: Store, caller: Caller, raw: dict[str, Any]) -> tuple[MessageResponse, bool]:
    """`POST /messages`. 두 번째 값이 `False`면 멱등으로 돌려준 기존 메시지다 (200)."""
    owner = _guard(caller)
    try:
        request = MessageRequest.model_validate(raw)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "메시지가 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    now = now_iso()
    if request.idempotency_key:
        before = _remembered(store, owner=owner, key=request.idempotency_key, now=now)
        if before is not None:
            if str(before["body_hash"]) != _body_hash(request):
                raise ApiError(
                    409,
                    "idempotency_conflict",
                    f"멱등 키 「{request.idempotency_key}」에 다른 본문이 왔다"
                    f" (기존 {before['message_id']})",
                )
            return _response(before), False

    found = _receiver(store, request)
    if found is not None:
        return _to_run(store, caller, request, found, owner=owner, now=now), True
    return _to_new_job(store, caller, request, owner=owner, now=now), True


def _receiver(store: Store, request: MessageRequest) -> tuple[str, WaitingRun] | None:
    """그 메시지를 받을 `(실행기, 기다리는 실행)`. 없으면 `None`.

    **상관 키가 없으면 찾지 않는다** (C12 §메시지) — 어느 실행인지 가릴 열쇠가 없으니 메시지
    시작만이다. 판정 자체는 계약의 `pick_message_target()`이 하고(엔진과 같은 규칙), 여기서
    보는 것은 **실행기가 마지막 하트비트에 보고한 `waiting[]`**이다.

    **「유실 처리」된 실행기는 보지 않는다** — 그쪽 실행은 이미 닫혔으니(C12) 메시지를 걸어 두면
    영원히 `pending`으로 남는다. **오프라인인 실행기는 본다** — 기다리는 실행은 그 실행기가
    돌아오면 이어 가므로(실행은 유실로 보지 않고 기다린다, C12 §재시작과 유실), 거기 걸어 두는
    것이 맞다. 빼면 그 사이 온 메시지가 `no_receiver`가 되거나 **새 작업으로 새어 나간다**.
    """
    if request.correlation is None:
        return None
    found: list[tuple[str, WaitingRun]] = []
    for row in store.rows(
        "SELECT server_runner_id AS id, state_json AS body FROM server_runners"
        " WHERE lost_at IS NULL ORDER BY server_runner_id"
    ):
        state = loads(row["body"], {}) or {}
        waiting = [WaitingRun.model_validate(one) for one in state.get("waiting", [])]
        picked = pick_message_target(
            waiting, name=request.name, correlation=request.correlation
        )
        if picked is not None:
            found.append((str(row["id"]), picked))
    if not found:
        return None
    # **실행기가 여럿이면 가장 오래 기다린 것**이다 — 실행기마다 고른 뒤 그중에서 다시 고른다
    # (앞 실행기의 것을 바로 쓰면 「오래 기다린 쪽부터」가 실행기 id 순서로 바뀐다).
    return sorted(found, key=lambda one: (one[1].since, one[1].run_id))[0]


def _to_run(
    store: Store,
    caller: Caller,
    request: MessageRequest,
    found: tuple[str, WaitingRun],
    *,
    owner: str,
    now: str,
) -> MessageResponse:
    runner_id, waiting = found
    message_id = new_message_id()
    _insert(
        store,
        message_id=message_id,
        request=request,
        owner=owner,
        actor=caller.actor,
        now=now,
        delivered_to=TO_RUN,
        run_id=waiting.run_id,
        runner_id=runner_id,
        job_id=None,
        state=PENDING,
    )
    return MessageResponse(message_id=message_id, delivered_to=TO_RUN, run_id=waiting.run_id)


def _to_new_job(
    store: Store, caller: Caller, request: MessageRequest, *, owner: str, now: str
) -> MessageResponse:
    """메시지 시작 — **작업으로 바꾼다** (C12 §메시지).

    배포 검사·버전 고르기·빈자리·BPM 프로세스별 상한을 **작업 쪽 한 자리**에 남긴다. 둘 이상의 서버
    BPM 프로세스가 같은 이름을 받으면 **고르지 않고** 422 `receiver_ambiguous`다 (C5의
    `version_ambiguous`와 같은 결 — 부르는 쪽이 `POST /jobs`로 정하면 된다).
    """
    bots = deployments.server_message_starts(store, name=request.name)
    if not bots:
        raise ApiError(
            422,
            "no_receiver",
            f"메시지 「{request.name}」을 기다리는 실행도, 그 이름으로 시작하는 서버 BPM 프로세스도 없다",
        )
    if len(bots) > 1:
        raise ApiError(
            422,
            "receiver_ambiguous",
            f"메시지 「{request.name}」으로 시작하는 서버 BPM 프로세스가 둘 이상이다",
            {"bpm_process_ids": bots},
        )

    info, _created = jobs.create(
        store,
        caller,
        {
            "schema": 1,
            "bpm_process_id": bots[0],
            # **실행기는 Center가 고른다** (C5 `JobTarget`) — 빈자리가 있는 쪽으로 간다.
            "target": {"type": "server_runner"},
            "inputs": dict(request.payload),
            "note": f"메시지 {request.name}",
            # 어느 가상 직원의 일인가 — `POST /jobs`와 같은 규칙으로 고른다 (ADR-0099).
            "virtual_worker": request.virtual_worker,
        },
    )
    message_id = new_message_id()
    _insert(
        store,
        message_id=message_id,
        request=request,
        owner=owner,
        actor=caller.actor,
        now=now,
        delivered_to=TO_JOB,
        run_id=None,
        runner_id=None,
        job_id=info.job_id,
        # 작업이 생긴 것으로 **이 메시지의 할 일은 끝났다** — 내려갈 것이 없다.
        state=DONE,
    )
    return MessageResponse(message_id=message_id, delivered_to=TO_JOB, job_id=info.job_id)


def _insert(
    store: Store,
    *,
    message_id: str,
    request: MessageRequest,
    owner: str,
    actor: str,
    now: str,
    delivered_to: str,
    run_id: str | None,
    runner_id: str | None,
    job_id: str | None,
    state: str,
) -> None:
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO messages (message_id, name, correlation_json, payload_json, owner,"
            " idempotency_key, body_hash, received_at, received_by, delivered_to, run_id,"
            " runner_id, job_id, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                request.name,
                # **상관 키는 아무 JSON 값**이라 글로 담는다 (없으면 NULL — 「없다」와 `null`을
                # 가르려고 `dumps`를 쓰지 않는다).
                dumps(request.correlation) if request.correlation is not None else None,
                dumps(dict(request.payload)),
                owner,
                request.idempotency_key,
                _body_hash(request),
                now,
                # **행위자는 본문에서 받지 않는다** (C5) — 키 이름이나 X-CHK-Actor가 정한다.
                actor,
                delivered_to,
                run_id,
                runner_id,
                job_id,
                state,
            ),
        )


def _response(row: Any) -> MessageResponse:
    return MessageResponse(
        message_id=str(row["message_id"]),
        delivered_to=str(row["delivered_to"]),
        run_id=row["run_id"],
        job_id=row["job_id"],
    )


# ─────────────────────────── 하트비트 (C12 `messages[]`) ───────────────────────────


def heartbeat(store: Store, *, runner_id: str, acks: list[MessageAck]) -> list[MessageDispatch]:
    """받은 ack를 반영하고, 그 실행기에 내려줄 메시지를 고른다.

    **순서가 작업과 같다** — ack를 먼저 반영해야 방금 받아들인 메시지를 다시 싣지 않는다.
    """
    _apply_acks(store, runner_id=runner_id, acks=acks)
    return _to_dispatch(store, runner_id=runner_id)


def _apply_acks(store: Store, *, runner_id: str, acks: list[MessageAck]) -> None:
    """`accepted`면 끝, 아니면 **사유와 함께 닫는다** — 어느 쪽이든 다시 싣지 않는다 (C12).

    `accepted: false`를 다시 싣기로 하면 **영원히 도는 메시지**가 된다. 넣을 수 없는 메시지는
    실행기가 ack하지 않고 두므로(C12), 여기 온 거절은 「이 실행은 그것을 받을 수 없다」는 말이다.
    """
    now = now_iso()
    for ack in acks:
        row = store.row(
            "SELECT * FROM messages WHERE message_id = ? AND runner_id = ?",
            (ack.message_id, runner_id),
        )
        if row is None or str(row["state"]) != PENDING:
            # 모르는 메시지이거나 이미 끝난 것이다 — **남의 메시지는 건드리지 않는다**.
            continue
        with store.tx() as cur:
            cur.execute(
                "UPDATE messages SET state = ?, reason = ?, acked_at = ?, run_id = ?"
                " WHERE message_id = ?",
                (
                    DONE if ack.accepted else REFUSED,
                    ack.reason,
                    now,
                    # **실행기가 말하는 실행이 원본이다** — Center가 고른 것과 다를 수 있다
                    # (그 사이 다른 실행이 그 메시지를 기다리게 됐을 수 있다).
                    ack.run_id or row["run_id"],
                    ack.message_id,
                ),
            )


def _to_dispatch(store: Store, *, runner_id: str) -> list[MessageDispatch]:
    """내려줄 메시지 (오래된 것부터). **ack가 올 때까지 매번 다시 싣는다** (ADR-0007)."""
    rows = store.rows(
        "SELECT * FROM messages WHERE runner_id = ? AND state = ? ORDER BY received_at, message_id",
        (runner_id, PENDING),
    )
    return [
        MessageDispatch(
            message_id=str(one["message_id"]),
            name=str(one["name"]),
            correlation=loads(one["correlation_json"], None),
            payload=loads(one["payload_json"], {}) or {},
            received_at=str(one["received_at"]),
        )
        for one in rows
    ]


def fail_runner_messages(store: Store, *, runner_id: str) -> int:
    """그 실행기로 가던 메시지를 닫는다 — 「유실 처리」가 부른다 (C12).

    결재를 회수하는 것과 같은 자리다 (C6 `host_lost`) — 받을 실행이 닫혔으니 메시지도 갈 곳이
    없다. 그냥 두면 `pending`으로 남아 그 실행기가 **다시 등록하는 날** 내려간다.
    """
    rows = store.rows(
        "SELECT message_id FROM messages WHERE runner_id = ? AND state = ?", (runner_id, PENDING)
    )
    if not rows:
        return 0
    now = now_iso()
    with store.tx() as cur:
        for one in rows:
            cur.execute(
                "UPDATE messages SET state = ?, reason = ?, acked_at = ? WHERE message_id = ?",
                (REFUSED, "host_lost", now, str(one["message_id"])),
            )
    return len(rows)


__all__ = [
    "DONE",
    "PENDING",
    "REFUSED",
    "TO_JOB",
    "TO_RUN",
    "create",
    "fail_runner_messages",
    "heartbeat",
    "new_message_id",
]

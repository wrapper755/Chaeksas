"""C3. 실행 이벤트 받기와 보여 주기 (CON-01 실행 로그).

받는 쪽의 태도가 계약에 또렷이 적혀 있다 — 그대로 옮긴다.

- **모르는 `kind`는 거부하지 않고 저장만 한다.** 하나를 거부하면 배치 전체가 막히고, `seq`가
  단조라서 그 실행의 기록이 영원히 막힌다 (프로토타입에서 실제로 일어났다).
- **줄 하나가 틀려도 나머지는 받는다** — `200` + `rejected: [{seq, code}]`.
- **같은 줄을 다시 보내면 무시한다** (`(run_id, seq)`가 키) — 보내는 쪽은 실패하면 같은
  배치를 그대로 또 보내면 된다.
- **`run_id`는 처음 보낸 키의 것이다** — 다른 키가 같은 `run_id`에 쓰면 403. 남의 실행 기록을
  덮지 못하게 한다.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request

from chaeksas.center.auth import Caller, require_read
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.events import (
    MAX_BATCH_BYTES,
    MAX_BATCH_LINES,
    EventBatchResponse,
    RejectedLine,
    RunEvent,
    RunEventsResponse,
    RunInfo,
    RunListing,
    missing_data_keys,
)

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

#: 줄 단위 거부 사유 (C3 「오류」 — `rejected[].code`).
CODE_INVALID = "line_invalid"
CODE_MISSING = "data_missing"
CODE_SCHEMA = "schema_too_high"
CODE_RUN_MISMATCH = "run_id_mismatch"

#: 목록 한 번에 돌려주는 실행 수 (CON-01).
DEFAULT_LIMIT = 50
MAX_LIMIT = 500

#: `run_finished`가 세어 보낸 것 — 요약에 그대로 둔다 (CON-01 목록 열, C3 `RunInfo`).
#: **줄을 다시 읽어 세지 않는다** — 보낸 쪽이 센 것이 원본이다.
COUNTS = ("ai_tasks", "replayed_tasks", "ui_tasks", "service_calls", "human_requests")


def owner_of(store: Store, run_id: str) -> str | None:
    found = store.row("SELECT owner_key_id FROM runs WHERE run_id = ?", (run_id,))
    return str(found["owner_key_id"]) if found else None


def _owner_key(caller: Caller) -> str:
    """이 배치를 보낸 쪽의 열쇠 id. 관리자 토큰은 키가 없으니 종류로 적는다."""
    return caller.key.key_id if caller.key is not None else f"token:{caller.kind}"


def accept(store: Store, caller: Caller, run_id: str, lines: list[Any]) -> EventBatchResponse:
    """배치 하나를 받는다 (C3 §전송)."""
    if len(lines) > MAX_BATCH_LINES:
        raise ApiError(413, "batch_too_long", f"한 배치는 {MAX_BATCH_LINES}줄까지다")

    owner = owner_of(store, run_id)
    mine = _owner_key(caller)
    if owner is not None and owner != mine:
        raise ApiError(403, "run_owner_mismatch", "다른 키가 만든 실행 기록이다")

    accepted = 0
    duplicates = 0
    rejected: list[RejectedLine] = []
    rows: list[tuple[Any, ...]] = []
    seen: set[int] = set()
    summary: dict[str, Any] = {}

    for index, raw in enumerate(lines, start=1):
        if not isinstance(raw, dict):
            rejected.append(RejectedLine(seq=index, code=CODE_INVALID))
            continue
        if int(raw.get("schema") or 1) > RunEvent.SCHEMA:
            rejected.append(RejectedLine(seq=int(raw.get("seq") or index), code=CODE_SCHEMA))
            continue
        try:
            event = RunEvent.model_validate(raw)
        except ValueError:
            rejected.append(RejectedLine(seq=int(raw.get("seq") or index), code=CODE_INVALID))
            continue
        if event.run_id != run_id:
            rejected.append(RejectedLine(seq=event.seq, code=CODE_RUN_MISMATCH))
            continue
        missing = missing_data_keys(event)
        if missing:
            rejected.append(RejectedLine(seq=event.seq, code=CODE_MISSING))
            continue
        if event.seq in seen:
            duplicates += 1
            continue
        seen.add(event.seq)
        rows.append((run_id, event.seq, event.ts, event.kind, event.node_id, dumps(event.data)))
        _note(summary, event)

    with store.tx() as cur:
        if owner is None:
            cur.execute(
                "INSERT INTO runs (run_id, owner_key_id, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
                (run_id, mine, now_iso(), now_iso()),
            )
        for row in rows:
            # 같은 줄을 다시 보내면 **무시한다** (멱등 — C3 §전송).
            cur.execute(
                "INSERT INTO run_events (run_id, seq, ts, kind, node_id, data_json) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (run_id, seq) DO NOTHING",
                row,
            )
            if cur.rowcount:
                accepted += 1
            else:
                duplicates += 1
        _update_run(cur, run_id, summary)

    if summary.get("finished_at"):
        # 실행이 끝났으면 그 실행의 `open` 결재를 거둔다 (C6 `run_ended`) — 답할 수는 있는데
        # 전달될 곳이 없는 결재가 결재함에 남지 않게.
        from chaeksas.center.api import approvals  # noqa: PLC0415 — 순환 import를 피한다

        approvals.withdraw_for_run(store, run_id, event="run_finished")

    return EventBatchResponse(
        run_id=run_id, accepted=accepted, duplicates=duplicates, rejected=rejected
    )


def _note(summary: dict[str, Any], event: RunEvent) -> None:
    """목록에 보일 값만 추려 둔다 (CON-01 — 줄마다 다시 읽지 않게)."""
    if event.kind == "run_started":
        summary.update(
            {
                "bpm_process_id": event.data.get("bpm_process_id"),
                "version": event.data.get("version"),
                "run_location": event.data.get("run_location"),
                "executor": event.data.get("executor"),
                "mode": event.data.get("mode"),
                "source": event.data.get("source"),
                "started_at": event.ts,
                "status": "running",
            }
        )
    elif event.kind == "run_finished":
        summary.update(
            {
                "status": event.data.get("status") or "success",
                "finished_at": event.ts,
                "duration_s": event.data.get("duration_s"),
                "error_code": event.data.get("error_code"),
                # 셈은 **보낸 쪽이 센 것**을 그대로 둔다 (C3) — 줄을 다시 읽어 세지 않는다.
                **{name: event.data.get(name) for name in COUNTS},
            }
        )
    elif event.kind == "run_waiting":
        summary["status"] = "waiting"
    elif event.kind == "run_resumed":
        summary.setdefault("status", "running")


def _update_run(cur: Any, run_id: str, summary: dict[str, Any]) -> None:
    """요약을 덮어쓴다. **늦게 온 배치가 끝난 실행을 「도는 중」으로 되돌리지 않게** 한다."""
    cur.execute("UPDATE runs SET last_seen_at = ? WHERE run_id = ?", (now_iso(), run_id))
    if not summary:
        return
    found = cur.execute("SELECT summary_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    before = loads(found["summary_json"] if found else None, {}) or {}
    if before.get("status") in ("success", "failed", "cancelled") and summary.get("status") in (
        "running",
        "waiting",
    ):
        summary = {k: v for k, v in summary.items() if k != "status"}
    cur.execute(
        "UPDATE runs SET summary_json = ? WHERE run_id = ?", (dumps({**before, **summary}), run_id)
    )


def events_of(store: Store, run_id: str) -> list[RunEvent]:
    """그 실행의 이벤트 — **`seq` 차례로** (CON-01 타임라인)."""
    rows = store.rows(
        "SELECT run_id, seq, ts, kind, node_id, data_json FROM run_events "
        "WHERE run_id = ? ORDER BY seq",
        (run_id,),
    )
    return [
        RunEvent(
            schema=1,
            run_id=row["run_id"],
            seq=row["seq"],
            ts=row["ts"],
            kind=row["kind"],
            node_id=row["node_id"],
            data=loads(row["data_json"], {}) or {},
        )
        for row in rows
    ]


def info_of(store: Store, run_id: str) -> RunInfo:
    found = store.row(
        "SELECT run_id, first_seen_at, last_seen_at, summary_json FROM runs WHERE run_id = ?",
        (run_id,),
    )
    if found is None:
        raise ApiError(404, "run_not_found", f"그 실행 기록이 없다: {run_id}")
    return _info(found, store)


def _info(row: Any, store: Store) -> RunInfo:
    summary = loads(row["summary_json"], {}) or {}
    counted = store.row("SELECT COUNT(*) AS n FROM run_events WHERE run_id = ?", (row["run_id"],))
    tallies = {name: summary.get(name) for name in COUNTS}
    return RunInfo(
        run_id=row["run_id"],
        status=summary.get("status") or "running",
        bpm_process_id=summary.get("bpm_process_id"),
        version=summary.get("version"),
        run_location=summary.get("run_location"),
        executor=summary.get("executor"),
        mode=summary.get("mode"),
        source=summary.get("source"),
        started_at=summary.get("started_at") or row["first_seen_at"],
        finished_at=summary.get("finished_at"),
        duration_s=summary.get("duration_s"),
        error_code=summary.get("error_code"),
        **tallies,
        events=int(counted["n"]) if counted else 0,
    )


def listing(
    store: Store,
    *,
    status: str | None = None,
    bpm_process_id: str | None = None,
    run_location: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> RunListing:
    """최근 실행부터 (CON-01 목록). 좁히기는 상태·BPM 프로세스·실행 위치다.

    **「Bot UI」로는 아직 좁히지 못한다** — C3 `RunInfo`에 어느 Bot UI였나가 없다 (Center는
    `run_id`를 보낸 **키**에 묶어 두지만 그것을 실행 요약에 적지 않는다, docs/09-gaps.md §4-11).
    """
    rows = store.rows(
        "SELECT run_id, first_seen_at, last_seen_at, summary_json FROM runs "
        "ORDER BY first_seen_at DESC, run_id DESC"
    )
    found = [_info(row, store) for row in rows]
    if status:
        found = [one for one in found if one.status == status]
    if bpm_process_id:
        found = [one for one in found if one.bpm_process_id == bpm_process_id]
    if run_location:
        found = [one for one in found if one.run_location == run_location]
    return RunListing(runs=found[: max(1, min(limit, MAX_LIMIT))], total=len(found))


# ─────────────────────────── 경로 ───────────────────────────


@router.post("/{run_id}/events")
async def post_events(run_id: str, request: Request) -> Any:
    store: Store = request.app.state.store
    found: Caller = request.app.state.authenticate(request)
    raw = await request.body()
    if len(raw) > MAX_BATCH_BYTES:
        raise ApiError(413, "batch_too_large", f"한 배치는 {MAX_BATCH_BYTES // 1024} KB까지다")
    try:
        body = json.loads(raw or b"[]")
    except ValueError as e:
        raise ApiError(422, "input_invalid", "JSON이 아니다") from e
    if not isinstance(body, list):
        raise ApiError(422, "input_invalid", "본문은 이벤트 배열이다")
    return accept(store, found, run_id, body)


@router.get("")
def get_runs(
    request: Request,
    status: str | None = None,
    bpm_process_id: str | None = None,
    run_location: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> Any:
    require_read(request.app.state.authenticate(request))
    return listing(
        request.app.state.store,
        status=status,
        bpm_process_id=bpm_process_id,
        run_location=run_location,
        limit=limit,
    )


@router.get("/{run_id}")
def get_run(run_id: str, request: Request) -> Any:
    require_read(request.app.state.authenticate(request))
    return info_of(request.app.state.store, run_id)


@router.get("/{run_id}/events")
def get_events(run_id: str, request: Request) -> Any:
    require_read(request.app.state.authenticate(request))
    info_of(request.app.state.store, run_id)  # 없으면 404
    return RunEventsResponse(run_id=run_id, events=events_of(request.app.state.store, run_id))


__all__ = [
    "CODE_INVALID",
    "CODE_MISSING",
    "CODE_RUN_MISMATCH",
    "CODE_SCHEMA",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "accept",
    "events_of",
    "info_of",
    "listing",
    "owner_of",
    "router",
]

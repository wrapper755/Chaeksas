"""C4. Bot UI 등록·하트비트.

**연결은 항상 Bot UI → Center다** (ADR-0007). 지시(배포·작업·결재 답)는 하트비트 **응답**에
실려 내려간다 — Center가 현장 PC로 먼저 연결하지 않는다.

신원은 키로 정한다 (C4): 경로·본문에 `bot_ui_id`를 넣지 않는다. 키는 처음 등록한 PC에 묶이고,
다른 PC에서 쓰면 409 — 키가 새어도 다른 Bot UI를 사칭할 수 없다.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from chaeksas.center import keys
from chaeksas.center.auth import Caller, require_key_type
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import MAX_REQUEST_KB, ONLINE_WITHIN_S
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.bot_ui import (
    BotUiId,
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterRequest,
    RegisterResponse,
)
from chaeksas.contracts.center_keys import BoundTo

router = APIRouter(prefix="/api/v1/bot-ui", tags=["bot-ui"])

#: 키 종류 (C4 — Bot UI용 키만 받는다).
KEY_TYPE = "bot_ui"


def new_bot_ui_id() -> str:
    return f"bui_{secrets.token_hex(4)}"


def _bound_or_bind(store: Store, key: keys.KeyRecord, *, machine_id: str, name: str) -> None:
    """키 묶기 — 처음이면 묶고, 다른 PC면 409 (C4 「키 묶기」)."""
    if key.bound_to is None:
        keys.bind(
            store,
            key.key_id,
            BoundTo(type=KEY_TYPE, id=machine_id, name=name, first_seen=now_iso()),
        )
        return
    if key.bound_to.id != machine_id:
        raise ApiError(
            409,
            "machine_mismatch",
            f"이 키는 다른 PC에 묶여 있다 (「{key.bound_to.name}」). "
            "PC를 다시 설치했다면 콘솔에서 「PC 묶음 풀기」를 하세요",
            {"bound_to": key.bound_to.to_json_dict()},
        )


def register(store: Store, caller: Caller, body: dict[str, Any], *, heartbeat_interval_s: int) -> RegisterResponse:
    """처음 한 번, 그리고 이름·버전이 바뀔 때. **멱등**이다 — 같은 키·PC면 같은 `bot_ui_id`."""
    key = require_key_type(caller, KEY_TYPE)
    try:
        request = RegisterRequest.model_validate(body)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "등록 요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e

    _bound_or_bind(store, key, machine_id=request.machine_id, name=request.name)

    existing = store.row("SELECT * FROM bot_uis WHERE key_id = ?", (key.key_id,))
    if existing is not None and existing["machine_id"] != request.machine_id:
        # 묶음을 풀고 다른 PC에서 다시 등록한 경우 — 그 키의 Bot UI를 새 PC로 옮긴다.
        bot_ui_id = existing["bot_ui_id"]
    elif existing is not None:
        bot_ui_id = existing["bot_ui_id"]
    else:
        bot_ui_id = new_bot_ui_id()

    runtimes = request.runtimes.to_json_dict() if request.runtimes else None
    with store.tx() as cur:
        if existing is None:
            cur.execute(
                "INSERT INTO bot_uis (bot_ui_id, key_id, machine_id, name, os, versions_json,"
                " runtimes_json, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bot_ui_id,
                    key.key_id,
                    request.machine_id,
                    request.name,
                    request.os,
                    dumps(request.versions.to_json_dict()),
                    dumps(runtimes) if runtimes else None,
                    now_iso(),
                ),
            )
        else:
            cur.execute(
                "UPDATE bot_uis SET machine_id = ?, name = ?, os = ?, versions_json = ?,"
                " runtimes_json = ? WHERE bot_ui_id = ?",
                (
                    request.machine_id,
                    request.name,
                    request.os,
                    dumps(request.versions.to_json_dict()),
                    dumps(runtimes) if runtimes else None,
                    bot_ui_id,
                ),
            )

    return RegisterResponse(
        bot_ui_id=BotUiId(bot_ui_id),
        admin_keys=[],  # 배포 서명 검증용 Admin 공개키 — 서명·배포는 M5다
        heartbeat_interval_s=heartbeat_interval_s,
        server_time=now_iso(),
    )


def heartbeat(store: Store, caller: Caller, body: dict[str, Any], *, heartbeat_interval_s: int) -> HeartbeatResponse:
    """30초마다. 상태를 덮어쓰고, 내려줄 지시를 응답에 싣는다.

    지금 내려줄 것은 `disabled`뿐이다 — 배포·작업·결재는 M5다. 그때 이 응답에 실린다.
    """
    key = require_key_type(caller, KEY_TYPE)
    try:
        request = HeartbeatRequest.model_validate(body)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "하트비트가 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    found = store.row("SELECT * FROM bot_uis WHERE key_id = ?", (key.key_id,))
    if found is None:
        raise ApiError(409, "not_registered", "등록되지 않은 키다 — 먼저 register를 부르세요")

    state = {
        "status": request.status,
        "current_run": request.current_run.to_json_dict() if request.current_run else None,
        "queue": request.queue.to_json_dict(),
        "worker": request.worker.to_json_dict(),
        "readiness": [r.to_json_dict() for r in request.readiness],
        "extensions": [e.to_json_dict() for e in request.extensions],
        "unsent_events": request.unsent_events,
    }
    with store.tx() as cur:
        if request.versions is not None:
            cur.execute(
                "UPDATE bot_uis SET versions_json = ? WHERE bot_ui_id = ?",
                (dumps(request.versions.to_json_dict()), found["bot_ui_id"]),
            )
        cur.execute(
            "UPDATE bot_uis SET last_seen_at = ?, state_json = ? WHERE bot_ui_id = ?",
            (now_iso(), dumps(state), found["bot_ui_id"]),
        )

    return HeartbeatResponse(
        server_time=now_iso(),
        next_heartbeat_s=heartbeat_interval_s,
        deployments=[],
        jobs=[],
        cancel_jobs=[],
        approvals=[],
        disabled=bool(found["disabled"]),
    )


def bot_ui_listing(store: Store) -> list[dict[str, Any]]:
    """CON-03 「Bot UI 현황」이 쓰는 목록. 온라인 판정은 마지막 하트비트가 90초 이내인가다."""
    now = datetime.fromisoformat(now_iso())
    out = []
    for row in store.rows("SELECT * FROM bot_uis ORDER BY name"):
        last_seen = row["last_seen_at"]
        online = False
        if last_seen:
            online = (now - datetime.fromisoformat(last_seen)).total_seconds() <= ONLINE_WITHIN_S
        out.append(
            {
                "bot_ui_id": row["bot_ui_id"],
                "name": row["name"],
                "os": row["os"],
                "machine_id": row["machine_id"],
                "versions": loads(row["versions_json"], {}),
                "runtimes": loads(row["runtimes_json"], None),
                "registered_at": row["registered_at"],
                "last_seen_at": last_seen,
                "online": online,
                "disabled": bool(row["disabled"]),
                "state": loads(row["state_json"], None),
            }
        )
    return out


def set_disabled(store: Store, bot_ui_id: str, *, disabled: bool) -> bool:
    """CON-03 「비활성화」. 비활성이어도 **하트비트는 계속 받는다** (실행 중 Bot을 봐야 한다)."""
    with store.tx() as cur:
        cur.execute("UPDATE bot_uis SET disabled = ? WHERE bot_ui_id = ?", (1 if disabled else 0, bot_ui_id))
        return cur.rowcount > 0


@router.post("/register")
async def post_register(request: Request) -> Any:
    store: Store = request.app.state.store
    found: Caller = request.app.state.authenticate(request)
    body = await _json(request)
    return register(store, found, body, heartbeat_interval_s=request.app.state.settings.heartbeat_interval_s)


@router.post("/heartbeat")
async def post_heartbeat(request: Request) -> Any:
    store: Store = request.app.state.store
    found: Caller = request.app.state.authenticate(request)
    body = await _json(request)
    return heartbeat(store, found, body, heartbeat_interval_s=request.app.state.settings.heartbeat_interval_s)


async def _json(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > MAX_REQUEST_KB * 1024:
        raise ApiError(413, "too_large", f"요청이 {MAX_REQUEST_KB} KB를 넘는다")
    try:
        body = json.loads(raw or b"{}")
    except ValueError as e:
        raise ApiError(422, "input_invalid", "본문이 JSON이 아니다") from e
    if not isinstance(body, dict):
        raise ApiError(422, "input_invalid", "본문의 최상위가 객체가 아니다")
    return body

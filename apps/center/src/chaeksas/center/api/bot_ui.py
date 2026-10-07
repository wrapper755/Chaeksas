"""C4. Bot UI 등록·하트비트.

**연결은 항상 Bot UI → Center다** (ADR-0007). 지시(배포·작업·결재 답)는 하트비트 **응답**에
실려 내려간다 — Center가 현장 PC로 먼저 연결하지 않는다.

신원은 키로 정한다 (C4): 경로·본문에 `bot_ui_id`를 넣지 않는다. 키는 처음 등록한 PC에 묶이고,
다른 PC에서 쓰면 409 — 키가 새어도 다른 Bot UI를 사칭할 수 없다. **묶기는 두 방향 모두 하나씩**
이라 같은 PC를 다른 키가 등록하는 것도 409다 (C4 「키 묶기」) — 그러지 않으면 PC 하나에 Bot UI
행이 둘 생겨 CON-03에 두 줄로 보이고, C7 리소스의 PC 수가 부풀고, 작업이 하트비트를 보내지
않는 쪽으로 간다.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from chaeksas.center import keys
from chaeksas.center.api import approvals, deployments, jobs, signing
from chaeksas.center.auth import Caller, require_key_type
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import MAX_REQUEST_KB, ONLINE_WITHIN_S
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.bot_ui import (
    BotUiId,
    CurrentRun,
    ExtensionState,
    HeartbeatRequest,
    HeartbeatResponse,
    Queue,
    Readiness,
    RegisterRequest,
    RegisterResponse,
    Runtimes,
    Versions,
    WorkerState,
)
from chaeksas.contracts.center_api import BotUiInfo, BotUiKey
from chaeksas.contracts.center_keys import BoundTo

router = APIRouter(prefix="/api/v1/bot-ui", tags=["bot-ui"])

#: 키 종류 (C4 — Bot UI용 키만 받는다).
KEY_TYPE = "bot_ui"


def new_bot_ui_id() -> str:
    return f"bui_{secrets.token_hex(4)}"


def _refuse_if_bound_elsewhere(key: keys.KeyRecord, machine_id: str) -> None:
    """키 → PC: 키는 처음 등록한 PC에 묶인다 (C4 「키 묶기」)."""
    if key.bound_to is not None and key.bound_to.id != machine_id:
        raise ApiError(
            409,
            "machine_mismatch",
            f"이 키는 다른 PC에 묶여 있다 (「{key.bound_to.name}」). "
            "PC를 다시 설치했다면 콘솔에서 「PC 묶음 풀기」를 하세요",
            {"bound_to": key.bound_to.to_json_dict()},
        )


def _adopt_or_refuse(store: Store, key: keys.KeyRecord, *, machine_id: str, own: Any | None) -> Any | None:
    """PC → 키: `machine_id` 하나에 Bot UI 행도 하나다 (C4 「키 묶기」).

    돌려주는 것은 **이어받을 자리**다 (그 PC가 비어 있으면 `None`). 묶음이 풀린 키의 자리는
    놓인 자리라 새 키가 이어받는다 — 새 행을 만들면 배포·작업·결재가 가리키는 `bot_ui_id`를
    버리게 되고 CON-03에 유령 한 줄이 남는다.
    """
    other = store.row(
        "SELECT * FROM bot_uis WHERE machine_id = ? AND key_id <> ?", (machine_id, key.key_id)
    )
    if other is None:
        return None
    detail = {"bot_ui_id": str(other["bot_ui_id"]), "name": str(other["name"])}
    owner = keys.get(store, str(other["key_id"]))
    if owner is not None and owner.bound_to is not None:
        # 키 하나가 혼자서 남의 PC 자리를 가져가지 못한다 — 관문은 운영자다.
        raise ApiError(
            409,
            "machine_already_registered",
            f"이 PC는 이미 다른 키로 등록되어 있다 (「{other['name']}」). "
            "키를 바꾸려면 콘솔에서 옛 키의 「PC 묶음 풀기」를 먼저 하세요",
            {**detail, "reason": "bound_elsewhere"},
        )
    if own is not None:
        # 이어받기는 행이 없는 키만 한다 — 어느 쪽 이력을 버릴지 짐작하지 않는다.
        raise ApiError(
            409,
            "machine_already_registered",
            f"이 키는 이미 다른 PC로 등록되어 있어 이 PC(「{other['name']}」)의 자리를 "
            "이어받을 수 없다. 이 PC에는 새 키를 발급하세요",
            {**detail, "reason": "key_has_another_pc"},
        )
    return other


def register(store: Store, caller: Caller, body: dict[str, Any], *, heartbeat_interval_s: int) -> RegisterResponse:
    """처음 한 번, 그리고 이름·버전이 바뀔 때. **멱등**이다 — 같은 키·PC면 같은 `bot_ui_id`."""
    key = require_key_type(caller, KEY_TYPE)
    try:
        request = RegisterRequest.model_validate(body)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "등록 요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e

    existing = store.row("SELECT * FROM bot_uis WHERE key_id = ?", (key.key_id,))
    # **묶기 전에 두 방향을 다 본다** — 막힌 등록이 키를 묶으면 운영자가 그 묶음까지 풀어야 한다 (C4).
    _refuse_if_bound_elsewhere(key, request.machine_id)
    adopted = _adopt_or_refuse(store, key, machine_id=request.machine_id, own=existing)
    if key.bound_to is None:
        keys.bind(
            store,
            key.key_id,
            BoundTo(type=KEY_TYPE, id=request.machine_id, name=request.name, first_seen=now_iso()),
        )

    row = existing if existing is not None else adopted
    bot_ui_id = str(row["bot_ui_id"]) if row is not None else new_bot_ui_id()

    runtimes = request.runtimes.to_json_dict() if request.runtimes else None
    with store.tx() as cur:
        if row is None:
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
        elif adopted is not None:
            # 이어받은 자리의 **상태는 비운다** — 옛 키가 보고한 것이다 (C4). 다음 하트비트가 채운다.
            cur.execute(
                "UPDATE bot_uis SET key_id = ?, machine_id = ?, name = ?, os = ?, versions_json = ?,"
                " runtimes_json = ?, last_seen_at = NULL, state_json = NULL WHERE bot_ui_id = ?",
                (
                    key.key_id,
                    request.machine_id,
                    request.name,
                    request.os,
                    dumps(request.versions.to_json_dict()),
                    dumps(runtimes) if runtimes else None,
                    bot_ui_id,
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

    배포 봉투와 작업이 여기 실려 내려간다. 결재(C6)는 아직이다.
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
    # 배치 결정은 **한 주기만 올라온다** — 흘려보내면 「왜 설치가 안 됐나」가 남지 않는다 (C4).
    deployments.remember_results(
        store, bot_ui_id=str(found["bot_ui_id"]), results=request.deployment_results
    )

    disabled = bool(found["disabled"])
    # 작업은 ack 반영 → 만료 → 맞추기 → 고르기 순이다 (C4·C5, `api/jobs.py`).
    dispatch, cancels = jobs.heartbeat(
        store, bot_ui_id=str(found["bot_ui_id"]), request=request, disabled=disabled
    )
    return HeartbeatResponse(
        server_time=now_iso(),
        next_heartbeat_s=heartbeat_interval_s,
        # **저장된 JSON 그대로** 내려 준다 — 모델로 바꿔 다시 쓰면 서명이 깨진다 (C4).
        deployments=deployments.envelopes_for(
            store, target_type="bot_ui", target_id=str(found["bot_ui_id"])
        ),
        admin_keys=signing.admin_keys(store),
        jobs=dispatch,
        cancel_jobs=cancels,
        # 답이 정해진 결재 (C6). ack가 올 때까지 내려간다 — 거절하면 다시 `open`이 된다.
        approvals=approvals.heartbeat(
            store, bot_ui_id=str(found["bot_ui_id"]), acks=request.approval_acks
        ),
        disabled=disabled,
    )


def bot_ui_listing(store: Store) -> list[BotUiInfo]:
    """CON-03 「Bot UI 현황」 (C5 `BotUiInfo`).

    상태는 **Bot UI가 하트비트로 보고한 그대로** 싣고, Center가 더하는 것은 온라인 판정과
    키 정보뿐이다. 키는 앞자리·만료·상태만 준다 — 원문·해시는 주지 않는다 (C7).
    """
    now = datetime.fromisoformat(now_iso())
    out = []
    for row in store.rows("SELECT * FROM bot_uis ORDER BY name"):
        last_seen = row["last_seen_at"]
        online = bool(
            last_seen and (now - datetime.fromisoformat(last_seen)).total_seconds() <= ONLINE_WITHIN_S
        )
        state = loads(row["state_json"], {}) or {}
        record = keys.get(store, row["key_id"])
        out.append(
            BotUiInfo(
                bot_ui_id=row["bot_ui_id"],
                name=row["name"],
                os=row["os"],
                machine_id=row["machine_id"],
                versions=Versions.model_validate(loads(row["versions_json"], {})),
                runtimes=Runtimes.model_validate(loads(row["runtimes_json"]))
                if loads(row["runtimes_json"])
                else None,
                registered_at=row["registered_at"],
                last_seen_at=last_seen,
                online=online,
                disabled=bool(row["disabled"]),
                status=state.get("status"),
                current_run=CurrentRun.model_validate(state["current_run"]) if state.get("current_run") else None,
                queue=Queue.model_validate(state["queue"]) if state.get("queue") else None,
                worker=WorkerState.model_validate(state["worker"]) if state.get("worker") else None,
                readiness=[Readiness.model_validate(r) for r in state.get("readiness", [])],
                extensions=[ExtensionState.model_validate(e) for e in state.get("extensions", [])],
                # 마지막 하트비트가 아니라 **Center가 쌓아 둔 것**이다 (C5 — CON-03이 읽는다).
                deployment_results=deployments.results_of(store, bot_ui_id=str(row["bot_ui_id"])),
                key=BotUiKey(
                    prefix=record.prefix,
                    expires_at=record.expires_at,
                    state=record.state(now=now_iso()),
                )
                if record
                else None,
            )
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

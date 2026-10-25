"""C12. 서버 실행기 등록·하트비트 + 운영 API (CON-12).

**연결은 늘 실행기 → Center다** (ADR-0007) — C4와 같은 틀이다. 지시(배포·작업·결재 답·메시지)는
하트비트 **응답**에 실려 내려간다.

C4와 **다른 것 셋**이 여기 있다 (C12 표·ADR-0054 —
`docs/decisions/0054-server-run-state-and-concurrency.md`):

| | C4 Bot UI | C12 서버 실행기 |
| --- | --- | --- |
| 실행 자리 | `current_run` 하나 (ADR-0014) | `capacity` + `running[]` — 상한까지 여럿 |
| 기다리는 실행 | 자리를 쥔다 | **`waiting[]`로 빠져 자리를 놓는다** |
| 대기열 | Bot UI가 가진다 | **Center가 가진다** — 실행기는 빈자리만큼만 받는다 |

**같은 것은 같은 코드로 한다** — 키 묶기는 `center.host_keys`, 배포 봉투·배치 결정은
`api.deployments`, 결재는 `api.approvals`가 C4와 **같은 함수**로 다룬다. 베끼면 한쪽만 고쳐져
「PC에서는 되는데 서버에서 안 된다」가 된다.

**내려가는 것은 넷이다** — 배포 봉투·작업·결재 답·**메시지**. 메시지는 `api.messages`가 고르고
(C12 §메시지), 나머지 셋은 C4와 같은 함수들이 고른다. 서버 대상 배포·작업을 막던 스위치
(`SERVER_RUNNER_AVAILABLE`)는 켜져 있다.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from chaeksas.center import enrollments, host_keys
from chaeksas.center.api import approvals, deployments, jobs, messages, signing
from chaeksas.center.auth import Caller, require_key_type
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.bot_ui import ExtensionState, Readiness
from chaeksas.contracts.server_runner import (
    DEFAULT_HEARTBEAT_S,
    OFFLINE_AFTER_S,
    Capacity,
    RunnerVersions,
    RunningRun,
    ServerRunnerHeartbeatRequest,
    ServerRunnerHeartbeatResponse,
    ServerRunnerId,
    ServerRunnerInfo,
    ServerRunnerRegisterRequest,
    ServerRunnerRegisterResponse,
    WaitingRun,
    validate_heartbeat,
)

router = APIRouter(prefix="/api/v1/server-runner", tags=["server-runner"])

#: 키 종류 (C12 — 「서버 실행기용」 키만 받는다. 다른 종류는 403 `wrong_key_type`).
KEY_TYPE = "server_runner"
#: 키 묶기를 지킬 표 (규칙은 `center.host_keys`에 하나다 — C4와 같다).
TABLE = host_keys.SERVER_RUNNER


def new_server_runner_id() -> str:
    return f"srv_{secrets.token_hex(4)}"


def id_for_key(store: Store, key_id: str) -> str | None:
    """그 키로 등록된 실행기의 `server_runner_id`. 등록 전이면 `None` — **키가 신원이다**."""
    return host_keys.id_for_key(store, TABLE, key_id)


def exists(store: Store, server_runner_id: str) -> bool:
    """등록된 서버인가 (C5 배포·작업 지시의 대상 검사, ADR-0049)."""
    return host_keys.exists(store, TABLE, server_runner_id)


# ─────────────────────────── 등록 ───────────────────────────


def register(
    store: Store, caller: Caller, body: dict[str, Any], *, heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
) -> ServerRunnerRegisterResponse:
    """처음 한 번, 그리고 이름·버전·상한이 바뀔 때. **멱등**이다 — 같은 키·서버면 같은 id."""
    key = require_key_type(caller, KEY_TYPE)
    try:
        request = ServerRunnerRegisterRequest.model_validate(body)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "등록 요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    existing, adopted = host_keys.claim(
        store, TABLE, key, machine_id=request.machine_id, name=request.name, key_type=KEY_TYPE
    )
    row = existing if existing is not None else adopted
    runner_id = str(row[TABLE.id_column]) if row is not None else new_server_runner_id()

    versions = dumps(request.versions.to_json_dict())
    extensions = dumps([e.to_json_dict() for e in request.extensions])
    with store.tx() as cur:
        if row is None:
            cur.execute(
                "INSERT INTO server_runners (server_runner_id, key_id, machine_id, name, os,"
                " versions_json, max_concurrency, extensions_json, registered_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    runner_id,
                    key.key_id,
                    request.machine_id,
                    request.name,
                    request.os,
                    versions,
                    request.max_concurrency,
                    extensions,
                    now_iso(),
                ),
            )
        elif adopted is not None:
            # 이어받은 자리의 **상태는 비운다** — 옛 키가 보고한 것이다 (C4와 같은 결).
            # **「유실 처리」도 함께 지운다** — 새 키로 다시 선 서버다.
            cur.execute(
                "UPDATE server_runners SET key_id = ?, machine_id = ?, name = ?, os = ?,"
                " versions_json = ?, max_concurrency = ?, extensions_json = ?, last_seen_at = NULL,"
                " state_json = NULL, lost_at = NULL WHERE server_runner_id = ?",
                (
                    key.key_id,
                    request.machine_id,
                    request.name,
                    request.os,
                    versions,
                    request.max_concurrency,
                    extensions,
                    runner_id,
                ),
            )
        else:
            # **다시 떠도 「유실 처리」를 지운다** — 운영자가 닫아 둔 실행기가 돌아왔다.
            cur.execute(
                "UPDATE server_runners SET machine_id = ?, name = ?, os = ?, versions_json = ?,"
                " max_concurrency = ?, extensions_json = ?, lost_at = NULL WHERE server_runner_id = ?",
                (
                    request.machine_id,
                    request.name,
                    request.os,
                    versions,
                    request.max_concurrency,
                    extensions,
                    runner_id,
                ),
            )

    # 승인으로 받은 키가 처음 쓰였다 — **봉해 둔 것을 지운다** (C12 §등록 요청과 승인).
    enrollments.delivered(store, key, public_key=request.public_key)

    return ServerRunnerRegisterResponse(
        server_runner_id=ServerRunnerId(runner_id),
        # **등록 응답에도 싣는다** (C12 §등록) — 실행기는 공개키를 메모리에만 두고, 다시 뜨면
        # **첫 하트비트보다 먼저** 담아 둔 실행을 되살린다 (ADR-0054). 되살린 실행이 바깥 앱
        # 명부를 지을 때 공개키가 없으면 외부 확장의 봉투를 **한 번도** 검증할 수 없다 (C13 E6).
        # Bot UI는 공개키를 제 저장소에 들고 있어 이 자리가 비어도 괜찮다 (C4).
        admin_keys=signing.admin_keys(store),
        heartbeat_interval_s=heartbeat_interval_s,
        server_time=now_iso(),
        # **만료일은 Center만 안다** (C7) — 없으면 「만료 없음」이고 「모른다」가 아니다.
        key_expires_at=key.expires_at,
    )


# ─────────────────────────── 하트비트 ───────────────────────────


def heartbeat(
    store: Store, caller: Caller, body: dict[str, Any], *, heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
) -> ServerRunnerHeartbeatResponse:
    """기본 10초. 상태를 덮어쓰고, 내려줄 지시를 응답에 싣는다.

    본문이 **스스로 앞뒤가 맞나**를 계약의 `validate_heartbeat()`로 본다 — 보내는 쪽과 받는
    쪽이 같은 함수를 쓴다. 자리 셈이 어긋난 하트비트를 받아 두면 Center가 빈자리를 틀리게
    세어 상한을 넘겨 작업을 보낸다.
    """
    key = require_key_type(caller, KEY_TYPE)
    try:
        request = ServerRunnerHeartbeatRequest.model_validate(body)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "하트비트가 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e
    problems = validate_heartbeat(request)
    if problems:
        raise ApiError(
            422, "input_invalid", f"하트비트가 앞뒤가 맞지 않는다: {problems[0]}", {"problems": problems}
        )

    found = host_keys.row_for_key(store, TABLE, key.key_id)
    if found is None:
        raise ApiError(409, "not_registered", "등록되지 않은 키다 — 먼저 register를 부르세요")
    runner_id = str(found["server_runner_id"])

    state = {
        "status": request.status,
        "capacity": request.capacity.to_json_dict(),
        "running": [r.to_json_dict() for r in request.running],
        "waiting": [w.to_json_dict() for w in request.waiting],
        "readiness": [r.to_json_dict() for r in request.readiness],
        "restored": list(request.restored),
        "unsent_events": request.unsent_events,
    }
    with store.tx() as cur:
        if request.versions is not None:
            cur.execute(
                "UPDATE server_runners SET versions_json = ? WHERE server_runner_id = ?",
                (dumps(request.versions.to_json_dict()), runner_id),
            )
        if request.extensions:
            # **바뀌었을 때만 올라온다** (C12) — 빈 목록은 「안 바뀜」이라 덮어쓰지 않는다.
            cur.execute(
                "UPDATE server_runners SET extensions_json = ? WHERE server_runner_id = ?",
                (dumps([e.to_json_dict() for e in request.extensions]), runner_id),
            )
        cur.execute(
            # **살아 돌아왔으면 「유실 처리」를 지운다** — 닫아 둔 실행이 이미 실패로 남았어도,
            # 지금 도는 실행기를 오프라인·유실로 보이게 두지 않는다 (CON-12).
            "UPDATE server_runners SET last_seen_at = ?, state_json = ?, lost_at = NULL"
            " WHERE server_runner_id = ?",
            (now_iso(), dumps(state), runner_id),
        )

    # 배치 결정은 **한 주기만 올라온다** — 흘려보내면 「왜 설치가 안 됐나」가 남지 않는다 (C4·C12).
    deployments.remember_results(store, host_id=runner_id, results=request.deployment_results)

    paused = bool(found["paused"])
    dispatch, cancels = jobs.server_heartbeat(
        store, runner_id=runner_id, request=request, paused=paused
    )
    return ServerRunnerHeartbeatResponse(
        server_time=now_iso(),
        next_heartbeat_s=heartbeat_interval_s,
        # **저장된 JSON 그대로** 내려 준다 — 모델로 바꿔 다시 쓰면 서명이 깨진다 (C4·C12).
        # `"*"` 배포도 함께 온다 (`_target_sql` — 서버 실행기만 쓰는 전체 대상, ADR-0046).
        deployments=deployments.envelopes_for(
            store, target_type="server_runner", target_id=runner_id
        ),
        admin_keys=signing.admin_keys(store),
        jobs=dispatch,
        cancel_jobs=cancels,
        # 답이 정해진 결재 (C6) — **C4와 같은 함수**다. 결재 창구는 Center만이다 (C12).
        approvals=approvals.heartbeat(store, host_id=runner_id, acks=request.approval_acks),
        # 받을 곳이 이 실행기인 메시지 (C12 §메시지) — **ack가 올 때까지 매번 다시 싣는다**.
        messages=messages.heartbeat(store, runner_id=runner_id, acks=request.message_acks),
        # 끝난 PC 위임의 결과 (C12 §PC 위임, ADR-0062) — 메시지와 같은 결이다: **ack가 올
        # 때까지 다시 싣고**, 받았다는 ack가 오면 **값을 바로 지운다**.
        delegations=_delegations(store, runner_id=runner_id, acks=request.delegation_acks),
        paused=paused,
        rotated_key=enrollments.rotation_for(store, key, host_id=runner_id),
        # **주기마다 싣는다** — 운영자가 기간을 늘려 주면 다음 주기에 바로 안다 (C4·C12).
        key_expires_at=key.expires_at,
    )


def _delegations(store: Store, *, runner_id: str, acks: list[Any]) -> list[Any]:
    """내려줄 위임 결과 — **ack를 먼저 적는다** (그러면 받은 것은 이번에 다시 내려가지 않는다).

    `delegations.py`를 **함수 안에서** 들여온다 — 그 모듈이 이 모듈의 `id_for_key`를 쓰므로
    위에서 import하면 순환이다 (결재·메시지와 같은 짜임).
    """
    from chaeksas.center.api import delegations  # noqa: PLC0415 — 순환 import를 피한다

    delegations.apply_acks(store, runner_id=runner_id, acks=acks)
    # **못 받은 값도 언젠가는 지운다** (ADR-0062 §4) — ack가 영영 오지 않는 것이 있다. C6
    # 결재의 `purge_values`가 하트비트에서 돌듯 여기서 돈다 (따로 도는 청소기를 두지 않는다).
    delegations.purge_values(store)
    return [one.to_json_dict() for one in delegations.pending_for(store, runner_id)]


# ─────────────────────────── 운영 API (CON-12) ───────────────────────────


def _online(last_seen: Any, *, now: datetime) -> bool:
    """하트비트가 3분 안에 왔나 (C12 — PC의 90초보다 길다. 주기가 10초다)."""
    if not last_seen:
        return False
    return (now - datetime.fromisoformat(str(last_seen))).total_seconds() <= OFFLINE_AFTER_S


def runner_listing(store: Store) -> list[ServerRunnerInfo]:
    """`GET /api/v1/server-runners` (CON-12).

    상태는 **실행기가 보고한 그대로** 싣고, Center가 더하는 것은 온라인 판정·일시 중지·
    **대기열 수**다 (서버 쪽 대기열은 Center가 가진다 — C12).
    """
    now = datetime.fromisoformat(now_iso())
    out = []
    for row in store.rows("SELECT * FROM server_runners ORDER BY name"):
        runner_id = str(row["server_runner_id"])
        state = loads(row["state_json"], {}) or {}
        capacity = state.get("capacity") or {"max": int(row["max_concurrency"]), "running": 0}
        out.append(
            ServerRunnerInfo(
                server_runner_id=ServerRunnerId(runner_id),
                name=str(row["name"]),
                os=str(row["os"]),
                # **보고한 상태가 없으면 「모른다」**가 아니라 오프라인이다 (아직 하트비트 전).
                status=str(state.get("status") or "offline"),
                online=_online(row["last_seen_at"], now=now),
                paused=bool(row["paused"]),
                capacity=Capacity.model_validate(capacity),
                running=[RunningRun.model_validate(r) for r in state.get("running", [])],
                waiting=[WaitingRun.model_validate(w) for w in state.get("waiting", [])],
                queued=jobs.queued_count(store, runner_id=runner_id),
                readiness=[Readiness.model_validate(r) for r in state.get("readiness", [])],
                extensions=extensions_of(store, runner_id),
                # 마지막 하트비트가 아니라 **Center가 쌓아 둔 것**이다 (CON-12가 읽는다).
                deployment_results=deployments.results_of(store, host_id=runner_id),
                versions=RunnerVersions.model_validate(loads(row["versions_json"], {})),
                last_heartbeat_at=row["last_seen_at"],
                registered_at=str(row["registered_at"]),
                **_key_of(store, str(row["key_id"])),
                unsent_events=state.get("unsent_events"),
            )
        )
    return out


def _key_of(store: Store, key_id: str) -> dict[str, str | None]:
    """그 실행기가 쓰는 키의 **앞자리와 만료** (C12 — 원문·해시는 주지 않는다).

    둘을 **한 자리에서** 읽는다 — 앞자리만 있고 만료가 없으면 CON-12가 「무기한」을 거짓으로
    말한다 (키 행이 없는 것과 만료가 없는 것은 다르다).
    """
    from chaeksas.center import keys  # noqa: PLC0415 — 순환 import를 피한다

    record = keys.get(store, key_id)
    if record is None:
        return {"key_prefix": None, "key_expires_at": None}
    return {"key_prefix": record.prefix, "key_expires_at": record.expires_at}


def readiness_of(store: Store, runner_id: str) -> list[Readiness]:
    """그 실행기가 보고한 Bot별 준비 상태 (C12 `readiness`, CON-12 「Bot별 상한」)."""
    row = store.row(
        "SELECT state_json FROM server_runners WHERE server_runner_id = ?", (runner_id,)
    )
    state = loads(row["state_json"], {}) if row is not None else {}
    return [Readiness.model_validate(r) for r in (state or {}).get("readiness", [])]


def extensions_of(store: Store, runner_id: str) -> list[ExtensionState]:
    """그 실행기에 깔린 확장 (C12 — 등록·하트비트가 보고한 것, C7이 합쳐 보인다)."""
    row = store.row(
        "SELECT extensions_json FROM server_runners WHERE server_runner_id = ?", (runner_id,)
    )
    found = loads(row["extensions_json"], []) if row is not None else []
    return [ExtensionState.model_validate(e) for e in found or []]


def set_paused(store: Store, runner_id: str, *, paused: bool) -> bool:
    """CON-12 「일시 중지」·「다시 시작」. **다음 하트비트 응답의 `paused`로 전달된다** (C12).

    도는 것은 끝까지 간다 — 멈추는 것은 **새 작업을 받는 일**뿐이다.
    """
    with store.tx() as cur:
        cur.execute(
            "UPDATE server_runners SET paused = ? WHERE server_runner_id = ?",
            (1 if paused else 0, runner_id),
        )
        return cur.rowcount > 0


def mark_lost(store: Store, runner_id: str) -> dict[str, Any]:
    """CON-12 「유실 처리」 — **오프라인인 실행기만** (C12).

    온라인이면 409 `runner_online`이다. 하트비트가 오는 실행기의 실행을 닫으면 **현장이
    옳은데 Center가 부정하는** 것이 된다 (C4의 「`started`는 언제나 이긴다」와 같은 결).

    닫는 것은 그 실행기가 **올린** 결재와 작업이다. 실행 기록(C3)은 손대지 않는다 — 파일이
    원본이고 Center는 그것을 받아 둔 쪽이다.
    """
    row = store.row("SELECT * FROM server_runners WHERE server_runner_id = ?", (runner_id,))
    if row is None:
        raise ApiError(404, "not_found", f"서버 실행기 {runner_id}가 없다")
    if _online(row["last_seen_at"], now=datetime.fromisoformat(now_iso())):
        raise ApiError(
            409,
            "runner_online",
            "이 실행기는 온라인이다 — 유실 처리는 오프라인인 실행기만 할 수 있다",
            {"last_heartbeat_at": row["last_seen_at"]},
        )

    # 기다리는 결재를 회수한다 (C6 `host_lost`) — 답할 수는 있는데 전달될 곳이 없는 결재를
    # 남기지 않는다. 작업은 유실로 닫는다 (`runner_lost`).
    reclaimed = approvals.reclaim_host(store, host_id=runner_id, reason="host_lost")
    closed = jobs.fail_host_jobs(store, target_type="server_runner", target_id=runner_id)
    # 내려가지 못한 메시지도 닫는다 (C12 §메시지) — 그냥 두면 그 실행기가 **다시 등록하는
    # 날** 이미 닫힌 실행에 내려간다.
    dropped = messages.fail_runner_messages(store, runner_id=runner_id)
    with store.tx() as cur:
        cur.execute(
            "UPDATE server_runners SET lost_at = ?, state_json = NULL WHERE server_runner_id = ?",
            (now_iso(), runner_id),
        )
    return {
        "server_runner_id": runner_id,
        "approvals_reclaimed": reclaimed,
        "jobs_closed": closed,
        "messages_dropped": dropped,
    }


# ─────────────────────────── HTTP ───────────────────────────


@router.post("/register")
async def post_register(request: Request) -> Any:
    from chaeksas.center.api.bot_ui import _json  # noqa: PLC0415 — 본문 읽기는 한 자리다

    store: Store = request.app.state.store
    found: Caller = request.app.state.authenticate(request)
    body = await _json(request)
    return register(
        store, found, body, heartbeat_interval_s=request.app.state.settings.runner_heartbeat_s
    )


@router.post("/heartbeat")
async def post_heartbeat(request: Request) -> Any:
    from chaeksas.center.api.bot_ui import _json  # noqa: PLC0415 — 위와 같다

    store: Store = request.app.state.store
    found: Caller = request.app.state.authenticate(request)
    body = await _json(request)
    return heartbeat(
        store, found, body, heartbeat_interval_s=request.app.state.settings.runner_heartbeat_s
    )


__all__ = [
    "KEY_TYPE",
    "TABLE",
    "exists",
    "extensions_of",
    "heartbeat",
    "id_for_key",
    "mark_lost",
    "new_server_runner_id",
    "readiness_of",
    "register",
    "router",
    "runner_listing",
    "set_paused",
]

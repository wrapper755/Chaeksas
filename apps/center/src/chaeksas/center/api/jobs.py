"""작업 지시 — 「언제 돌려라」 (C5 `/jobs`).

**서명이 필요 없다.** 배포는 「무엇을 실행해도 되는가」라서 Admin 서명이 유일한 관문이지만
(C2), 작업은 **이미 배포된 것**을 지금 돌리라는 말일 뿐이다 — 배포되지 않은 BPM 프로세스는 작업으로도
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
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center.api import deployments
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.bot_ui import HeartbeatRequest, JobAck, JobDispatch
from chaeksas.contracts.bpmn_ext import INPUT_SOURCE_CALLER
from chaeksas.contracts.center_api import (
    DELEGATION_REQUESTER_PREFIX,
    IDEMPOTENCY_WINDOW_DAYS,
    LIST_LIMIT_DEFAULT,
    LIST_LIMIT_MAX,
    SERVER_RUNNER_AVAILABLE,
    JobCreateRequest,
    JobInfo,
    JobTarget,
    cancel_outcome,
    validate_job_create,
)
from chaeksas.contracts.server_runner import (
    ServerRunnerHeartbeatRequest,
    free_slots,
    pick_jobs,
)
from chaeksas.contracts.signing import TARGET_ANY

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
    - 그 밖의 Center API 키(Studio·PC 실행기·서버 실행기): 작업은 다루지 못한다
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


def create(
    store: Store, found: Caller, raw: dict[str, Any], *, by_center: bool = False
) -> tuple[JobInfo, bool]:
    """`POST /jobs`. 두 번째 값이 `False`면 멱등으로 돌려준 기존 작업이다 (200).

    **`by_center`는 Center 안에서 부를 때만 참이다** — 지금은 **PC 위임**뿐이다 (C12 §PC 위임,
    ADR-0062). 권한표의 「작업은 관리자 토큰이나 연동용 키로 다룬다」는 **HTTP `POST /jobs`의
    규칙**이고, 위임은 그 길이 아니라 `POST …/server-runner/delegations`로 들어와 **제 관문**을
    이미 지났다(실행기용 키·등록된 실행기·그 실행의 소유). 여기서 또 막으면 위임이 설 수 없다.
    """
    if not by_center:
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
    _refuse_sourced_inputs(store, bot=request.bpm_process_id, version=version, inputs=request.inputs)
    virtual_worker = _virtual_worker_of(store, request, actor=found.actor, by_center=by_center)

    job_id = new_job_id()
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id, inputs_json,"
            " expires_at, note, owner, idempotency_key, body_hash, requested_by, requested_at, state,"
            " on_behalf_of, virtual_worker)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                request.bpm_process_id,
                version,
                target.type,
                # **서버 대상의 `"*"`·빈 값은 빈 글로 둔다** — 고를 때 그 실행기에 묶는다
                # (`_server_dispatch`). PC는 그대로 그 id다.
                "" if target.type == "server_runner" and (target.id or TARGET_ANY) == TARGET_ANY else target.id,
                dumps(request.inputs),
                request.expires_at,
                request.note,
                owner,
                request.idempotency_key,
                _body_hash(request),
                # **행위자는 본문에서 받지 않는다** (C5) — 키 이름이나 X-BPM-Actor가 정한다.
                found.actor,
                now,
                PENDING,
                # 연동용 키가 실은 사람 — **주장**이라 적기만 한다 (ADR-0081). `requested_by`는
                # 그대로 키 이름이다: PC 실행기가 그 칸의 `server_bot:`로 위임을 가른다.
                None if by_center else found.on_behalf,
                virtual_worker,
            ),
        )
    return info_of(store, _must(store, job_id)), True


def _refuse_sourced_inputs(store: Store, *, bot: str, version: str, inputs: dict[str, Any]) -> None:
    """**값 출처가 부르는 쪽이 아닌 입력**은 줄 수 없다 — 422 `input_not_from_caller` (C5, ADR-0099).

    매니페스트의 `inputs[].source`로 본다. 위임도 같은 길을 지난다 — 부모 그림이 자식의 그
    입력에 매핑을 적으면 업무 실패가 된다(넘기는 것이 아니라 Center가 넣는 값이다).
    """
    row = store.row("SELECT manifest_json FROM packages WHERE id = ? AND version = ?", (bot, version))
    declared = (loads(row["manifest_json"], {}) or {}).get("inputs") or [] if row is not None else []
    sourced = sorted(
        str(one.get("name"))
        for one in declared
        if isinstance(one, dict) and one.get("source") not in (None, INPUT_SOURCE_CALLER) and one.get("name") in inputs
    )
    if sourced:
        raise ApiError(
            422,
            "input_not_from_caller",
            f"{bot}@{version}의 입력 {', '.join(sourced)}은 Center가 넣는다 — 부르는 쪽이 줄 수 없다",
            {"inputs": sourced},
        )


def _virtual_worker_of(store: Store, request: JobCreateRequest, *, actor: str, by_center: bool) -> str | None:
    """이 작업의 가상 직원 id (ADR-0099 §2·§3).

    **위임으로 만든 작업은 맡긴 실행의 작업에서 이어받는다** — 일괄이 맡긴 일은 그 가상 직원의
    일이다. 그 밖에는 부른 쪽이 적은 것을 `intake`와 대조하고, 비웠으면 하나뿐일 때만 그것이다.
    """
    from chaeksas.center.api import virtual_workers  # noqa: PLC0415 — 순환 import를 피한다

    if by_center and actor.startswith(DELEGATION_REQUESTER_PREFIX):
        parent = store.row(
            "SELECT virtual_worker FROM jobs WHERE run_id = ?", (actor[len(DELEGATION_REQUESTER_PREFIX):],)
        )
        return str(parent["virtual_worker"]) if parent is not None and parent["virtual_worker"] else None
    return virtual_workers.pick(store, bot=request.bpm_process_id, requested=request.virtual_worker)


def _resolved_version(store: Store, request: JobCreateRequest) -> str:
    """어느 버전을 돌릴지 정한다 — 대상이 있는지, 배포돼 있는지까지 본다 (C5)."""
    target = request.target
    if target.type == "server_runner" and not SERVER_RUNNER_AVAILABLE:
        # **배포와 같은 스위치를 본다** (ADR-0047). 두 자리에 적어 두면 한쪽만 켜져
        # 「작업은 만들어지는데 배포가 없다」가 된다.
        raise ApiError(422, "server_runner_not_available", "서버 실행은 아직 열려 있지 않다 (ADR-0016)")
    if target.type not in ("bot_ui", "server_runner"):
        raise ApiError(422, "target_mismatch", f"모르는 대상 종류다: {target.type}")

    from chaeksas.center.api import bot_ui, server_runner  # noqa: PLC0415 — 순환 import를 피한다

    target_id = str(target.id or "")
    if target.type == "server_runner":
        # **실행기는 Center가 고를 수 있다** (C5 `JobTarget`) — `id`를 비우거나 `"*"`면
        # 빈자리가 있는 쪽에 간다. 그때는 「어느 서버에 배포됐나」가 아니라 **어디든 배포돼
        # 있나**를 묻는다 (`"*"` 배포도 센다 — ADR-0046).
        if target_id in ("", TARGET_ANY):
            deployed = deployments.server_versions(store, bpm_process_id=request.bpm_process_id)
        else:
            if not server_runner.exists(store, target_id):
                raise ApiError(404, "target_not_found", f"등록되지 않은 서버 실행기다: {target_id}")
            deployed = deployments.versions_for(
                store,
                target_type="server_runner",
                target_id=target_id,
                bpm_process_id=request.bpm_process_id,
            )
    else:
        if not bot_ui.exists(store, target_id):
            # **배포와 같은 코드다** (`target_not_found`, ADR-0049) — 같은 조건에 두 이름을 두는
            # 것이 ADR-0047이 고친 흠이다. `not_found`는 이 길에서 「그 작업이 없다」로 쓴다.
            raise ApiError(404, "target_not_found", f"등록되지 않은 PC다: {target_id}")
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
    virtual_worker: str | None = None,
    limit: int = LIST_LIMIT_DEFAULT,
    offset: int = 0,
) -> list[JobInfo]:
    scope = _scope(found, write=False)
    belongs = None
    if virtual_worker:
        from chaeksas.center.api import virtual_workers  # noqa: PLC0415 — 순환 import를 피한다

        # 접수 BPM 프로세스의 작업 + **그 일괄이 맡긴 작업** — 읽을 때 잇는다 (C5 §가상 직원, ADR-0085).
        intake, batches = virtual_workers.runs_of(store, virtual_worker)
        def belongs(row: Any) -> bool:
            return virtual_workers.job_belongs(row, intake=intake, batches=batches)
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
        and (belongs is None or belongs(row))
    ]
    window = max(0, min(limit, LIST_LIMIT_MAX))
    return [info_of(store, row) for row in picked[offset : offset + window]]


def cancel(
    store: Store, found: Caller, job_id: str, *, by_center: bool = False
) -> tuple[JobInfo, int]:
    """`DELETE /jobs/{id}` (C5 「취소」 표). 두 번째 값이 응답 코드다 (200 / 202).

    `dispatched`·`queued`는 **Center 혼자 끝낼 수 없다** — 그사이 실행을 시작했을 수 있어서,
    현장에 물어보고(`cancel_jobs`) ack를 기다린다. 시작된 것은 거절이고 작업은 `accepted`로
    남는다 (실행 중인 BPM 프로세스를 멈추는 것은 schema 1 범위 밖).

    **`by_center`는 Center 안에서 부를 때만 참이다** — `create`와 **같은 결**이다 (지금은
    **PC 위임을 거두는 길**뿐이다, ADR-0062 §5): 그 길은 실행기 키로 들어와 **제 관문**을 이미
    지났다(등록된 실행기·그 위임의 임자). 권한표를 넓히면 실행기 키로 **남의 작업**까지
    취소할 수 있게 된다.
    """
    found_job = (
        info_of(store, _must(store, job_id)) if by_center else get(store, found, job_id, write=True)
    )
    # **대상 종류가 `accepted`의 답을 가른다** (ADR-0063) — 서버 실행은 멈출 수 있고 PC는
    # 그대로 거절이다. 판정은 계약이 쥔다 (문서의 표와 갈라지지 않게).
    status, code = cancel_outcome(found_job.state, found_job.target.type)
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
    acked = _apply_acks(store, host_id=bot_ui_id, acks=request.job_acks)
    _expire_due(store, host_id=bot_ui_id, now=now_iso())

    seen = {item.job_id for item in request.queue.items if item.job_id}
    if request.current_run is not None and request.current_run.job_id:
        seen.add(request.current_run.job_id)
    _reconcile(store, host_id=bot_ui_id, seen=seen | acked)

    return _to_dispatch(store, host_id=bot_ui_id, disabled=disabled), _to_cancel(store, host_id=bot_ui_id)


# ─────────────────────────── 하트비트 (C12 서버 실행기) ───────────────────────────

#: 서버 작업의 **아직 아무 실행기에도 가지 않은** 대상 (C5 — `id`를 비우거나 `"*"`).
UNASSIGNED = ""


def server_heartbeat(
    store: Store, *, runner_id: str, request: ServerRunnerHeartbeatRequest, paused: bool
) -> tuple[list[JobDispatch], list[str]]:
    """하트비트 한 번 (C12). **대기열은 Center가 가지므로** 빈자리만큼만 골라 보낸다.

    C4와 순서는 같다 (ack → 만료 → 맞추기 → 고르기). 다른 것은 **무엇을 「보았다」고 할
    것인가**다 — PC 실행기는 대기열을 올려 주지만 실행기는 `running[]`·`waiting[]`을 올린다.
    """
    acked = _apply_acks(store, host_id=runner_id, acks=request.job_acks)
    _expire_due(store, host_id=runner_id, now=now_iso())
    _expire_due(store, host_id=UNASSIGNED, now=now_iso())  # 아직 아무에게도 안 간 것도 만료된다
    _reconcile(
        store, host_id=runner_id, seen=_server_seen(store, request) | acked, lost_reason=LOST_RUNNER
    )
    return (
        _server_dispatch(store, runner_id=runner_id, request=request, paused=paused),
        _to_cancel(store, host_id=runner_id),
    )


def _server_seen(store: Store, request: ServerRunnerHeartbeatRequest) -> set[str]:
    """이번 하트비트에 **소식이 온** 작업들 (맞추기 규칙이 쓴다).

    **`waiting[]`에는 `job_id`가 없다** (C12) — 결재를 기다리는 실행의 작업을 「사라졌다」고
    보면 멀쩡한 실행을 `runner_lost`로 닫는다. 그래서 `run_id`로 되짚는다.
    """
    seen = {r.job_id for r in request.running if r.job_id}
    run_ids = {r.run_id for r in request.running} | {w.run_id for w in request.waiting}
    for run_id in run_ids:
        row = store.row("SELECT job_id FROM jobs WHERE run_id = ?", (run_id,))
        if row is not None:
            seen.add(str(row["job_id"]))
    return seen


def _per_bot_limits(store: Store, bots: Iterable[str]) -> dict[str, int]:
    """BPM 프로세스별 동시 실행 상한 — **배포 봉투가 정한다** (C2 `max_concurrency`, 기본 5).

    봉투에 없으면 계약의 기본값이다. 상한을 Center가 짓지 않는다 — 서명된 값이다.
    """
    out: dict[str, int] = {}
    for bot in bots:
        found = deployments.max_concurrency_for(store, bpm_process_id=bot)
        if found is not None:
            out[bot] = found
    return out


def _running_per_bot(store: Store) -> dict[str, int]:
    """지금 서버에서 도는 수 (BPM 프로세스별) — **실행기 전부를 합쳐** 센다.

    상한은 「이 서버에서 n건」이 아니라 「이 BPM 프로세스가 한 번에 n건」이다 (C12 §3). 한 실행기만
    보면 실행기를 늘릴 때마다 상한이 같이 늘어난다.
    """
    out: dict[str, int] = {}
    for row in store.rows(
        "SELECT bpm_process_id, COUNT(*) AS n FROM jobs"
        " WHERE target_type = ? AND settled = 0 AND state = ? GROUP BY bpm_process_id",
        ("server_runner", ACCEPTED),
    ):
        out[str(row["bpm_process_id"])] = int(row["n"])
    return out


def _server_candidates(store: Store, *, runner_id: str) -> list[Any]:
    """고를 수 있는 작업 — 이 실행기에 넘긴 것과 **아직 아무에게도 안 간 것**, 들어온 순서.

    `"*"`·빈 `id`로 만든 작업은 Center가 고른다 (C5 `JobTarget`). 이미 넘긴 것(`dispatched`)이
    먼저다 — ack가 올 때까지 매번 다시 실어야 하므로 (C4).
    """
    return list(
        store.rows(
            "SELECT * FROM jobs WHERE target_type = ? AND settled = 0 AND cancel_requested = 0"
            " AND state IN (?, ?) AND (target_id = ? OR target_id = ? OR target_id = ?)"
            " ORDER BY requested_at, job_id",
            ("server_runner", PENDING, DISPATCHED, runner_id, UNASSIGNED, TARGET_ANY),
        )
    )


def _server_dispatch(
    store: Store, *, runner_id: str, request: ServerRunnerHeartbeatRequest, paused: bool
) -> list[JobDispatch]:
    """내려줄 작업 — **빈자리만큼만** (C12 §Center가 작업을 나누는 규칙).

    고르는 것은 계약의 `pick_jobs()`다 — **건너뛰고 다음을 본다**(막아 세우면 상한에 걸린 BPM 프로세스
    하나가 대기열 전체를 멈춘다). 건너뛴 까닭은 `state_reason`에 적어 CON-12가 보인다.

    고른 작업은 **이 실행기에 묶는다** — 한 실행은 시작한 실행기에 끝까지 머문다 (상태가 그
    실행기 저장소에 있다, ADR-0054).
    """
    rows = _server_candidates(store, runner_id=runner_id)
    if not rows:
        return []
    queued = [(str(row["job_id"]), str(row["bpm_process_id"])) for row in rows]
    taken, skipped = pick_jobs(
        queued,
        slots=free_slots(request.capacity, paused=paused),
        running_per_bot=_running_per_bot(store),
        per_bot_limit=_per_bot_limits(store, {bot for _, bot in queued}),
    )

    with store.tx() as cur:
        for job_id, reason in skipped.items():
            cur.execute("UPDATE jobs SET state_reason = ? WHERE job_id = ?", (reason, job_id))
    from chaeksas.center.api import virtual_workers  # noqa: PLC0415 — 순환 import를 피한다

    out = []
    by_id = {str(row["job_id"]): row for row in rows}
    for job_id in taken:
        row = by_id[job_id]
        with store.tx() as cur:
            cur.execute(
                "UPDATE jobs SET state = ?, state_reason = NULL, target_id = ?, dispatched_at = ?"
                " WHERE job_id = ?",
                (DISPATCHED, runner_id, now_iso(), job_id),
            )
        out.append(
            JobDispatch(
                job_id=job_id,
                bpm_process_id=row["bpm_process_id"],
                version=row["version"],
                inputs=loads(row["inputs_json"], {}) or {},
                requested_by=row["requested_by"],
                requested_at=row["requested_at"],
                expires_at=row["expires_at"],
                note=row["note"],
                # **작업의 가상 직원을 붙인다** (C12, ADR-0099) — id만 남겨 두고 값은 내려줄 때
                # 등록에서 읽는다. 감독자를 바꾸면 다음 작업부터 맞는다.
                virtual_worker=virtual_workers.identity_of(store, row["virtual_worker"]),
            )
        )
    return out


def queued_count(store: Store, *, runner_id: str) -> int:
    """CON-12 「대기열」 — 아직 내려가지 않은 서버 작업 수.

    **아직 아무에게도 안 간 것까지 센다** (대기열은 Center가 가진다, C12).
    """
    row = store.row(
        "SELECT COUNT(*) AS n FROM jobs WHERE target_type = ? AND settled = 0 AND state = ?"
        " AND (target_id = ? OR target_id = ? OR target_id = ?)",
        ("server_runner", PENDING, runner_id, UNASSIGNED, TARGET_ANY),
    )
    return int(row["n"]) if row is not None else 0


def fail_host_jobs(store: Store, *, target_type: str, target_id: str) -> int:
    """그 실행기에 넘긴 작업을 **유실로 닫는다** (C12 「유실 처리」 — CON-12).

    아직 시작하지 않은 것(`pending`)은 **놓아 준다** — 다른 실행기가 받으면 된다. 닫는 것은
    이미 넘어가 버린 것(`dispatched`·`queued`·`accepted`)이다.
    """
    rows = store.rows(
        "SELECT job_id FROM jobs WHERE target_type = ? AND target_id = ? AND settled = 0"
        " AND state IN (?, ?, ?)",
        (target_type, target_id, DISPATCHED, QUEUED, ACCEPTED),
    )
    with store.tx() as cur:
        for row in rows:
            cur.execute(
                "UPDATE jobs SET state = ?, state_reason = ?, settled = 1 WHERE job_id = ?",
                (REJECTED, "runner_lost", row["job_id"]),
            )
        cur.execute(
            "UPDATE jobs SET target_id = ? WHERE target_type = ? AND target_id = ?"
            " AND settled = 0 AND state = ?",
            (UNASSIGNED, target_type, target_id, PENDING),
        )
    return len(rows)


def _apply_acks(store: Store, *, host_id: str, acks: list[JobAck]) -> set[str]:
    """받은 ack를 반영한다 (C4 `JobAck.result`). 돌려주는 것은 이번에 소식이 온 작업들이다.

    **같은 ack를 다시 보내도 한 번만 반영한다** (C4 멱등성) — 값을 덮어쓸 뿐이라 저절로 그렇다.
    """
    touched: set[str] = set()
    for ack in acks:
        row = store.row(
            "SELECT * FROM jobs WHERE job_id = ? AND target_id = ?", (ack.job_id, host_id)
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
        _note_delegation(store, row=row, ack=ack)
    return touched


def _note_delegation(store: Store, *, row: Any, ack: JobAck) -> None:
    """끝난 작업이 **PC 위임**이면 결과를 담아 둔다 (C12 §PC 위임, ADR-0062).

    담는 것은 **끝난 ack**뿐이다 — `started`·`queued`는 아직 결과가 아니고, 그때 담으면
    기다리는 서버 실행이 **빈 값으로 이어 간다**.

    `outputs`는 **위임일 때만** 쓴다 — 평범한 PC 작업이 값을 실어 보내도 `finish()`가 거짓을
    돌려주고 그 값은 **어디에도 남지 않는다** (원칙 6의 예외는 좁게 쓴다).
    """
    if ack.result in STATE_ACKS:
        return
    from chaeksas.center.api import delegations  # noqa: PLC0415 — 순환 import를 피한다

    delegations.finish(
        store,
        job_id=ack.job_id,
        state=ack.result,
        outputs=dict(ack.outputs),
        reason=ack.reason,
        pc_run_id=ack.run_id or (row["run_id"] if "run_id" in row.keys() else None),
    )


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


def _expire_due(store: Store, *, host_id: str, now: str) -> None:
    """`expires_at`까지 시작하지 못한 것은 `expired`다 (C5).

    **실행 중인 것(`accepted`)은 건드리지 않는다** — 이미 시작했으면 만료가 아니다.
    """
    edge = datetime.fromisoformat(now)
    for row in store.rows(
        "SELECT job_id, expires_at FROM jobs WHERE target_id = ? AND settled = 0"
        " AND state IN (?, ?, ?) AND expires_at IS NOT NULL",
        (host_id, PENDING, DISPATCHED, QUEUED),
    ):
        if datetime.fromisoformat(row["expires_at"]) > edge:
            continue
        with store.tx() as cur:
            cur.execute(
                "UPDATE jobs SET state = ?, settled = 1 WHERE job_id = ?", (EXPIRED, row["job_id"])
            )


#: 맞추기 규칙이 적는 사유 — **호스트마다 다르다**. PC는 C4의 값, 서버 실행기는 C12의 값이다.
#: 뭉개면 CON-12가 서버 실행기에 「bot_ui_lost」라고 적어 운영자가 PC를 찾아 헤맨다.
LOST_BOT_UI = "bot_ui_lost"
LOST_RUNNER = "runner_lost"


def _reconcile(store: Store, *, host_id: str, seen: set[str], lost_reason: str = LOST_BOT_UI) -> None:
    """맞추기 규칙 (C4·C12) — 넘겨준 작업이 **소리 없이 사라지지 않게** 한다.

    실행하는 쪽이 비정상 종료로 쥔 것을 잃으면 작업은 영원히 `queued`로 남는다. 두 번 연속
    하트비트에서 보이지 않고 ack도 없으면 `rejected` + `lost_reason`이다.

    **무엇을 「보았다」고 할지는 부르는 쪽이 정한다** (`seen`) — PC 실행기는 대기열·실행 자리로,
    서버 실행기는 `running[]`·`waiting[]`으로 말한다 (C12).
    """
    for row in store.rows(
        "SELECT job_id, misses, run_id FROM jobs WHERE target_id = ? AND settled = 0 AND state IN (?, ?)",
        (host_id, QUEUED, ACCEPTED),
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
                    (REJECTED, lost_reason, misses, row["job_id"]),
                )
            else:
                cur.execute("UPDATE jobs SET misses = ? WHERE job_id = ?", (misses, row["job_id"]))
        if misses >= LOST_AFTER and row["run_id"]:
            # 대기열을 잃었으면 그 실행의 결재도 전달될 곳이 없다 (C6 `host_lost`).
            from chaeksas.center.api import approvals  # noqa: PLC0415 — 순환 import를 피한다

            # `event`는 **계약의 열쇠**라 그대로 둔다 (`AUTO_WITHDRAW_REASONS`) — 저장되는
            # 사유는 호스트를 가리지 않는 `host_lost`다 (C6).
            approvals.withdraw_for_run(store, str(row["run_id"]), event=LOST_BOT_UI)


def _to_dispatch(store: Store, *, host_id: str, disabled: bool) -> list[JobDispatch]:
    """내려줄 작업 (C4 `jobs`) — **ack가 올 때까지 매번 실린다**.

    비활성화된 PC 실행기에는 **새 작업을 보내지 않는다** (C5 CON-03). 작업은 `pending`으로 남아
    기다린다 — 되살리려고 다시 만들 필요가 없다.
    """
    if disabled:
        return []
    out = []
    for row in store.rows(
        "SELECT * FROM jobs WHERE target_id = ? AND settled = 0 AND cancel_requested = 0"
        " AND state IN (?, ?) ORDER BY requested_at",
        (host_id, PENDING, DISPATCHED),
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


def _to_cancel(store: Store, *, host_id: str) -> list[str]:
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
            (host_id, DISPATCHED, QUEUED, ACCEPTED),
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
        virtual_worker=row["virtual_worker"],
        requested_by=row["requested_by"],
        on_behalf_of=row["on_behalf_of"],
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

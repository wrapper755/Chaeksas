"""C12 §PC 위임 — 서버 Bot이 **배포된 PC Bot**을 Center 작업으로 부른다 (ADR-0062).

받는 쪽의 태도가 ADR에 또렷이 적혀 있다 — 그대로 옮긴다.

- **어느 PC인가는 Center가 고른다.** 그림에 PC id를 적지 않는다 — 「PC에서 무엇을 돌려도
  되는가」를 정하는 것은 배포다 (ADR-0049). 고르는 곳은 **그 판이 배포된, 활성인, 대기열이
  가장 짧은** PC다.
- **고른 뒤에는 `POST /jobs`와 같은 함수로 작업이 된다** — 배포 검사·대상 검사·대기열이 한
  자리에 남는다 (메시지 시작이 이미 그렇다, C12 §메시지).
- **멱등 키와 `requested_by`는 본문에서 받지 않는다** — `run_id`·`node_id`·`node_instance`로
  Center가 짓는다. 부르는 쪽마다 규칙이 갈라지면 되살린 실행이 **같은 자리에서 작업을 두 번
  만든다** (ADR-0054 「마지막 기다림 이후를 다시 한다」).
- **남의 실행 이름으로 맡길 수 없다** — `run_id`는 보낸 키의 실행이어야 한다 (C3 소유와 같은
  대조). 그래야 `requested_by: server_bot:<run_id>`가 거짓이 되지 않는다.
- **값은 ack가 오면 바로 지운다** (원칙 6의 예외는 좁게 쓴다).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Request

from chaeksas.center.api import jobs as jobs_api
from chaeksas.center.api.server_runner import KEY_TYPE, id_for_key
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.center_api import delegation_requester
from chaeksas.contracts.server_runner import (
    DelegationAck,
    DelegationRequest,
    DelegationResponse,
    DelegationResult,
)

router = APIRouter(prefix="/api/v1/server-runner", tags=["server-runner"])

#: PC 대상 작업·배포의 종류 이름 (C5 `KNOWN_TARGET_TYPES`).
PC = "bot_ui"

#: 대기열에 있다고 보는 작업 상태 (PC를 고를 때 짧은 쪽을 찾는다).
IN_QUEUE = ("pending", "dispatched", "accepted")


def key_prefix(run_id: str, node_id: str, instance: int) -> str:
    """멱등 키 — **Center가 짓는다** (C12 §PC 위임). 결재 `request_id`와 같은 짜임이다."""
    return f"dlg_{run_id}_{node_id}_{instance}"


def _runner_of(store: Store, found: Caller) -> str:
    """부른 실행기. **서버 실행기용 키만** 맡길 수 있다 (C5 권한표)."""
    if found.key is None or found.key.type != KEY_TYPE:
        raise ApiError(403, "wrong_key_type", "서버 실행기용 키만 PC 위임을 맡길 수 있다")
    runner_id = id_for_key(store, found.key.key_id)
    if runner_id is None:
        raise ApiError(409, "not_registered", "등록되지 않은 실행기다")
    return runner_id


def _owns_the_run(store: Store, *, run_id: str, key_id: str) -> bool:
    """그 실행 기록을 보낸 키인가 (C3 소유).

    **기록이 아직 없으면 받아 준다** — 실행 기록은 하트비트 **뒤에** 올라가므로(C3 §전송)
    위임이 첫 배치보다 먼저 닿을 수 있다. 거절하면 멀쩡한 위임이 타이밍으로 실패한다.
    """
    row = store.row("SELECT owner_key_id FROM runs WHERE run_id = ?", (run_id,))
    return row is None or row["owner_key_id"] == key_id


def pick_bot_ui(store: Store, *, bot: str, version: str, wanted: str | None) -> str | None:
    """그 판을 돌릴 PC를 고른다 (C12 §PC 위임). 없으면 `None`.

    **배포가 후보를 정한다** — PC 배포는 대상이 `bot_ui_id` 하나씩이라(ADR-0046) 풀 것이 없다.
    **활성인 PC만** 보고, 그중 **대기열이 가장 짧은 곳**을 고른다 (같으면 id 순서).
    """
    from chaeksas.center.api import deployments  # noqa: PLC0415 — 순환 import를 피한다

    # **배포가 후보를 정하고 그 규칙은 `deployments.py`에 있다** — 여기서 다시 적으면
    # 「배포는 됐는데 위임이 안 간다」의 다섯째 자리가 된다.
    deployed = deployments.targets_for(
        store, bpm_process_id=bot, version=version, target_type=PC
    )
    found = {one for one in deployed if _usable(store, one)}
    if wanted is not None:
        return wanted if wanted in found else None
    if not found:
        return None
    marks = ",".join("?" * len(IN_QUEUE))
    return min(
        sorted(found),
        key=lambda one: int(
            (
                store.row(
                    f"SELECT COUNT(*) AS n FROM jobs WHERE target_type = ? AND target_id = ?"
                    f" AND state IN ({marks})",
                    (PC, one, *IN_QUEUE),
                )
                or {"n": 0}
            )["n"]
        ),
    )


def _usable(store: Store, bot_ui_id: str) -> bool:
    """그 PC에 보낼 수 있나 — **등록되어 있고 운영자가 끄지 않았다** (C4 `disabled`)."""
    row = store.row("SELECT disabled FROM bot_uis WHERE bot_ui_id = ?", (bot_ui_id,))
    return row is not None and not row["disabled"]


def create(store: Store, found: Caller, raw: dict[str, Any]) -> tuple[DelegationResponse, bool]:
    """`POST /api/v1/server-runner/delegations`. 두 번째 값이 거짓이면 **이미 만든 작업**이다."""
    runner_id = _runner_of(store, found)
    try:
        request = DelegationRequest.model_validate(raw)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "위임 요청이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    assert found.key is not None  # `_runner_of`가 먼저 본다
    if not _owns_the_run(store, run_id=request.run_id, key_id=found.key.key_id):
        raise ApiError(403, "run_owner_mismatch", "남의 실행 이름으로 위임을 맡길 수 없다")

    key = key_prefix(request.run_id, request.node_id, request.node_instance)
    before = store.row("SELECT * FROM delegations WHERE job_id IN (SELECT job_id FROM jobs"
                       " WHERE idempotency_key = ? AND owner = ?)", (key, jobs_api.owner_of(found)))
    if before is not None:
        # **작업 표를 그대로 읽는다** — `jobs.get`은 HTTP 길의 권한표(관리자·연동용 키)를 보므로
        # 실행기 키로는 제 위임의 작업도 못 읽는다. 여기 오는 길은 위에서 제 관문을 지났다.
        row = store.row("SELECT * FROM jobs WHERE job_id = ?", (str(before["job_id"]),))
        assert row is not None  # 위임 행이 있으면 그 작업도 있다
        job = jobs_api.info_of(store, row)
        return DelegationResponse(
            job_id=job.job_id, bot_ui_id=str(before["bot_ui_id"]), state=job.state
        ), False

    version = _version_for(store, request)
    bot_ui_id = pick_bot_ui(store, bot=request.bpm_process_id, version=version, wanted=request.bot_ui)
    if bot_ui_id is None:
        # **기다리지 않는다** — 배포되지 않은 것을 기다리는 것은 업무가 아니라 설정 잘못이고,
        # 오류 경계가 받아야 사람이 안다 (ADR-0062 §3).
        raise ApiError(
            404,
            "no_deployment",
            f"{request.bpm_process_id}@{version}이 배포된 활성 PC가 없다",
            {"bot_ui": request.bot_ui} if request.bot_ui else None,
        )

    # **`requested_by`는 본문으로 가지 않는다** (C5 — 키 이름이나 `X-CHK-Actor`가 정한다).
    # 위임은 Center가 **행위자를 바꿔** 부른다: `server_bot:<run_id>`(C5 예약값)이라 부르는
    # 쪽이 지어낼 수 없다.
    job, made = jobs_api.create(
        store,
        replace(found, actor=delegation_requester(request.run_id)),
        {
            "schema": 1,
            "bpm_process_id": request.bpm_process_id,
            "version": version,
            "target": {"type": PC, "id": bot_ui_id},
            "inputs": request.inputs,
            "idempotency_key": key,
        },
        # **Center 안에서 부른다** — 권한표의 「작업은 관리자·연동용 키」는 HTTP `POST /jobs`의
        # 규칙이고, 이 길은 위에서 제 관문을 지났다 (실행기 키·등록·실행 소유).
        by_center=True,
    )
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO delegations (job_id, runner_id, run_id, node_id, node_instance,"
            " bot_ui_id, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job.job_id,
                runner_id,
                request.run_id,
                request.node_id,
                request.node_instance,
                bot_ui_id,
                now_iso(),
            ),
        )
    return DelegationResponse(job_id=job.job_id, bot_ui_id=bot_ui_id, state=job.state), made


def _version_for(store: Store, request: DelegationRequest) -> str:
    """판을 비우면 **배포된 판** — 둘 이상이면 거절한다 (작업 지시와 같은 규칙, C5)."""
    if request.version:
        return request.version
    from chaeksas.center.api import deployments  # noqa: PLC0415 — 순환 import를 피한다

    versions = deployments.versions_deployed_to(
        store, bpm_process_id=request.bpm_process_id, target_type=PC
    )
    if not versions:
        raise ApiError(404, "no_deployment", f"{request.bpm_process_id}이 PC에 배포되지 않았다")
    if len(versions) > 1:
        raise ApiError(
            422, "version_ambiguous", "배포된 판이 둘 이상이다", {"versions": versions}
        )
    return versions[0]


def pending_for(store: Store, runner_id: str) -> list[DelegationResult]:
    """그 실행기에게 내려줄 **끝난 위임**들 (C12). **ack가 올 때까지 다시 싣는다.**"""
    rows = store.rows(
        "SELECT * FROM delegations WHERE runner_id = ? AND state IS NOT NULL AND acked = 0"
        " ORDER BY at",
        (runner_id,),
    )
    return [
        DelegationResult(
            job_id=str(row["job_id"]),
            run_id=str(row["run_id"]),
            state=str(row["state"]),
            outputs=loads(row["outputs_json"], {}) or {},
            reason=row["reason"],
            pc_run_id=row["pc_run_id"],
        )
        for row in rows
    ]


def apply_acks(store: Store, *, runner_id: str, acks: list[DelegationAck]) -> None:
    """받았다는 ack — **값을 바로 지운다** (원칙 6의 예외는 좁게 쓴다).

    누가·언제·성패는 남긴다 (`state`·`reason`). 받지 않았다고 온 것은 **그대로 둔다** (다음
    주기에 다시 내려간다).
    """
    with store.tx() as cur:
        for ack in acks:
            if not ack.accepted:
                continue
            cur.execute(
                "UPDATE delegations SET acked = 1, outputs_json = NULL"
                " WHERE job_id = ? AND runner_id = ?",
                (ack.job_id, runner_id),
            )


def finish(
    store: Store,
    *,
    job_id: str,
    state: str,
    outputs: dict[str, Any] | None = None,
    reason: str | None = None,
    pc_run_id: str | None = None,
) -> bool:
    """PC 쪽이 끝났다 — 결과를 담아 둔다. **위임이 아니면 거짓**이다.

    부르는 쪽은 작업 ack를 받는 자리다 (C4 — 그 조각에서 잇는다). 값은 그 Bot이 **선언한
    `outputs`만** 올라온다 (C1).
    """
    row = store.row("SELECT job_id FROM delegations WHERE job_id = ?", (job_id,))
    if row is None:
        return False
    with store.tx() as cur:
        cur.execute(
            "UPDATE delegations SET state = ?, outputs_json = ?, reason = ?, pc_run_id = ?,"
            " acked = 0 WHERE job_id = ?",
            (state, dumps(outputs or {}), reason, pc_run_id, job_id),
        )
    return True


def delegated_bots(store: Store, run_id: str) -> list[str]:
    """그 서버 실행이 맡긴 작업들 (CON-01이 오갈 때 쓴다 — 지금은 시험이 본다)."""
    rows = store.rows("SELECT job_id FROM delegations WHERE run_id = ? ORDER BY at", (run_id,))
    return [str(row["job_id"]) for row in rows]


@router.post("/delegations")
async def post_delegation(request: Request) -> Any:
    from fastapi.responses import JSONResponse  # noqa: PLC0415

    from chaeksas.center.api.bot_ui import _json  # noqa: PLC0415 — 본문 읽기는 한 자리다

    store: Store = request.app.state.store
    found: Caller = request.app.state.authenticate(request)
    body = await _json(request)
    made, fresh = create(store, found, body)
    return JSONResponse(made.to_json_dict(), status_code=201 if fresh else 200)


__all__ = [
    "IN_QUEUE",
    "apply_acks",
    "create",
    "delegated_bots",
    "finish",
    "key_prefix",
    "pending_for",
    "pick_bot_ui",
    "router",
]

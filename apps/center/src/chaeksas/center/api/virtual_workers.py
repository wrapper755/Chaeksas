"""가상 직원 — 사람이 아닌 업무 주체 (C5 §가상 직원, ADR-0085).

**저장하는 것은 등록뿐이다.** 일괄(접수 Bot 실행)·자식 실행·작업은 **읽을 때** 이어 붙인다
(`dependents`·`bot_ui_of`와 같은 결) — 저장하면 실행이 오갈 때마다 낡는다.

셋이 뼈대다.

1. **관문** — 접수 Bot에 「결재 없는 일괄 기동」(C14 B16)이 없어야 묶이고, 묶인 뒤 새 판도
   그것이 없어야 배포된다. 그림은 **Center가 저장된 zip에서 읽는다** — 내보낸 쪽을 믿지 않는다.
2. **기동 허용 목록은 없다** — 접수 Bot의 서명된 `requires.delegations`가 그것이다 (ADR-0079).
3. **대리 답용 키는 감독하는 것만** 읽는다 — `X-CHK-On-Behalf-Of`의 사람이 감독자일 때 (ADR-0081).
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from chaeksas.center.auth import Caller, require_on_behalf
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.approvals import normalize_assignees, normalize_name
from chaeksas.contracts.bpmn_ext import BpmnReadError, read_process, validate
from chaeksas.contracts.center_api import (
    DELEGATION_REQUESTER_PREFIX,
    VIRTUAL_WORKER_RECENT_BATCHES,
    VirtualWorkerBatch,
    VirtualWorkerInfo,
    VirtualWorkerRequest,
)
from chaeksas.contracts.hashing import MANIFEST_NAME
from chaeksas.contracts.manifest import Manifest

#: 관문이 보는 C14 규칙 (ADR-0082 §4) — 이것만 본다. 다른 검사는 Studio가 이미 보았다.
GATE_RULE = "B16"

#: 승인된 패키지 상태 (C5) — 묶는 관문은 **승인된 판**만 본다.
APPROVED = "approved"


# ─────────────────────────── 관문 ───────────────────────────


def entry_gate(package_dir: Path, file_name: str) -> list[str]:
    """그 판의 진입 그림에 걸린 **B16 메시지들** (없으면 빈 목록).

    그림을 읽지 못하면 그것도 걸린 것으로 본다 — 「못 읽었으니 괜찮다」로 지나가면 관문이 아니다.
    """
    try:
        with zipfile.ZipFile(package_dir / file_name) as archive:
            manifest = Manifest.model_validate_json(archive.read(MANIFEST_NAME))
            if not manifest.entry:
                return ["진입 정의가 없다"]
            process = read_process(archive.read(manifest.entry).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, BpmnReadError) as e:
        return [f"진입 그림을 읽지 못했다: {e}"]
    return [v.message for v in validate(process) if v.rule == GATE_RULE]


def _check_intake(store: Store, package_dir: Path, intake: str) -> None:
    """묶어도 되는가 — 승인된 판이 있고·서버 Bot이고·**승인된 판마다** B16이 없다 (ADR-0085 §2)."""
    rows = store.rows(
        "SELECT version, run_location, file_name FROM packages WHERE id = ? AND status = ?",
        (intake, APPROVED),
    )
    if not rows:
        raise ApiError(422, "intake_unknown", f"{intake}의 승인된 판이 없다")
    if any(row["run_location"] != "server" for row in rows):
        raise ApiError(422, "intake_not_server", f"{intake}는 서버 Bot이 아니다 — 접수 Bot은 서버에서 돈다")
    found = {str(row["version"]): entry_gate(package_dir, str(row["file_name"])) for row in rows}
    bad = {version: messages for version, messages in found.items() if messages}
    if bad:
        raise ApiError(
            422,
            "intake_not_gated",
            f"{intake}에 결재 없는 일괄 기동이 있다 (C14 B16)",
            {"violations": bad},
        )


def deploy_gate(store: Store, package_dir: Path, *, bot: str, version: str) -> None:
    """배포하려는 판이 **활성 가상 직원의 접수 Bot**이면 B16이 없어야 한다 (409, ADR-0085 §2)."""
    if store.row("SELECT id FROM virtual_workers WHERE intake = ? AND state = 'active'", (bot,)) is None:
        return
    row = store.row("SELECT file_name FROM packages WHERE id = ? AND version = ?", (bot, version))
    if row is None:
        return  # 없는 판은 배포 쪽이 이미 404로 말했다
    messages = entry_gate(package_dir, str(row["file_name"]))
    if messages:
        raise ApiError(
            409,
            "intake_not_gated",
            f"{bot}@{version}은 가상 직원의 접수 Bot인데 결재 없는 일괄 기동이 있다 (C14 B16)",
            {"violations": {version: messages}},
        )


# ─────────────────────────── 쓰기 (관리자 토큰) ───────────────────────────


def _parse(raw: Any, *, path_id: str | None = None) -> VirtualWorkerRequest:
    body = dict(raw) if isinstance(raw, dict) else {}
    if path_id is not None:
        body["id"] = path_id  # 경로가 이긴다
    try:
        request = VirtualWorkerRequest.model_validate(body)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "가상 직원이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e
    try:
        supervisors = normalize_assignees(request.supervisors)
    except TypeError as e:
        raise ApiError(422, "input_invalid", str(e)) from e
    return request.model_copy(update={"supervisors": supervisors})


def create(store: Store, package_dir: Path, raw: Any) -> VirtualWorkerInfo:
    """`POST /virtual-workers` — 등록. 같은 `id`가 있으면 409 `id_conflict`."""
    request = _parse(raw)
    if store.row("SELECT id FROM virtual_workers WHERE id = ?", (request.id,)) is not None:
        raise ApiError(409, "id_conflict", f"가상 직원 {request.id}가 이미 있다")
    _check_intake(store, package_dir, request.intake)
    at = now_iso()
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO virtual_workers (id, name, supervisors_json, intake, state, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (request.id, request.name, dumps(request.supervisors), request.intake, request.state, at, at),
        )
    return _info(store, _must(store, request.id), with_batches=False)


def update(store: Store, package_dir: Path, worker_id: str, raw: Any) -> VirtualWorkerInfo:
    """`PUT /virtual-workers/{id}` — 본문 전체로 바꾼다. 접수 Bot이 바뀌면 관문을 다시 본다."""
    before = _must(store, worker_id)
    request = _parse(raw, path_id=worker_id)
    if request.intake != before["intake"]:
        _check_intake(store, package_dir, request.intake)
    with store.tx() as cur:
        cur.execute(
            "UPDATE virtual_workers SET name = ?, supervisors_json = ?, intake = ?, state = ?, updated_at = ?"
            " WHERE id = ?",
            (request.name, dumps(request.supervisors), request.intake, request.state, now_iso(), worker_id),
        )
    return _info(store, _must(store, worker_id), with_batches=False)


def remove(store: Store, worker_id: str) -> None:
    """`DELETE /virtual-workers/{id}` — **등록만** 지운다. 실행·작업은 남는다."""
    _must(store, worker_id)
    with store.tx() as cur:
        cur.execute("DELETE FROM virtual_workers WHERE id = ?", (worker_id,))


# ─────────────────────────── 읽기 ───────────────────────────


def reader(found: Caller) -> str | None:
    """읽을 수 있는 쪽 — 콘솔 토큰이면 `None`(전부), 대리 답용 키면 **그 사람**(감독하는 것만)."""
    if found.kind in ("admin", "read"):
        return None
    if found.is_relay:
        return require_on_behalf(found)
    raise ApiError(403, "forbidden", "가상 직원은 콘솔 토큰이나 대리 답용 키로 읽는다")


def listing(store: Store, *, supervisor: str | None = None, on_behalf: str | None = None) -> list[VirtualWorkerInfo]:
    """`GET /virtual-workers?supervisor=` — 대리 답용 키면 거르기가 그 사람으로 **고정된다**."""
    wanted = normalize_name(supervisor) if supervisor else None
    if on_behalf is not None:
        if wanted is not None and wanted != on_behalf:
            raise ApiError(403, "not_supervisor", "대리 답용 키는 그 사람이 감독하는 것만 본다")
        wanted = on_behalf
    rows = store.rows("SELECT * FROM virtual_workers ORDER BY id")
    return [
        _info(store, row, with_batches=False)
        for row in rows
        if wanted is None or wanted in _supervisors_of(row)
    ]


def get(store: Store, worker_id: str, *, on_behalf: str | None = None) -> VirtualWorkerInfo:
    """`GET /virtual-workers/{id}` — **최근 일괄**까지. 감독하지 않는 것은 404 (있다는 것조차)."""
    row = _must(store, worker_id)
    if on_behalf is not None and on_behalf not in _supervisors_of(row):
        raise ApiError(404, "not_found", f"가상 직원 {worker_id}가 없다")
    return _info(store, row, with_batches=True)


def intake_names(store: Store, intake: str) -> set[str]:
    """실행 기록이 접수 Bot을 부르는 이름들 — 패키지 id와 **그 패키지들의 진입 `process_id`**.

    C3 `run_started.bpm_process_id`에는 엔진이 **그림의 process id**를 적는다(`Proc_…`). 작업·배포는
    패키지 id로 말하므로 둘 다 본다 — 한쪽만 보면 일괄이 하나도 잡히지 않는다.
    """
    names = {intake}
    for row in store.rows("SELECT manifest_json FROM packages WHERE id = ?", (intake,)):
        process_id = (loads(row["manifest_json"], {}) or {}).get("process_id")
        if process_id:
            names.add(str(process_id))
    return names


def runs_of(store: Store, worker_id: str) -> tuple[set[str], set[str]]:
    """그 가상 직원의 **접수 Bot 이름들**과 **일괄(접수 실행) id들** — `?virtual_worker=`가 쓴다."""
    row = _must(store, worker_id)
    names = intake_names(store, str(row["intake"]))
    batches = {
        str(one["run_id"])
        for one in store.rows("SELECT run_id, summary_json FROM runs")
        if (loads(one["summary_json"], {}) or {}).get("bpm_process_id") in names
    }
    return names, batches


def job_belongs(row: Any, *, intake: set[str], batches: set[str]) -> bool:
    """그 작업이 이 가상 직원의 것인가 — 접수 Bot의 작업이거나 **그 일괄이 맡긴 작업**이다."""
    if row["bpm_process_id"] in intake:
        return True
    requested = str(row["requested_by"] or "")
    return requested.startswith(DELEGATION_REQUESTER_PREFIX) and requested[len(DELEGATION_REQUESTER_PREFIX):] in batches


def _must(store: Store, worker_id: str) -> Any:
    row = store.row("SELECT * FROM virtual_workers WHERE id = ?", (worker_id,))
    if row is None:
        raise ApiError(404, "not_found", f"가상 직원 {worker_id}가 없다")
    return row


def _supervisors_of(row: Any) -> list[str]:
    return list(loads(row["supervisors_json"], []) or [])


def _batches(store: Store, intake: str) -> list[VirtualWorkerBatch]:
    """최근 일괄 — 접수 Bot의 실행과 그 자식(`parent_run_id`), 열린 결재를 **읽을 때** 센다."""
    names = intake_names(store, intake)
    summaries = [
        (str(one["run_id"]), loads(one["summary_json"], {}) or {}, str(one["first_seen_at"]))
        for one in store.rows("SELECT run_id, summary_json, first_seen_at FROM runs")
    ]
    mine = sorted(
        ((run_id, summary, seen) for run_id, summary, seen in summaries if summary.get("bpm_process_id") in names),
        key=lambda one: (one[1].get("started_at") or one[2], one[0]),
        reverse=True,
    )[:VIRTUAL_WORKER_RECENT_BATCHES]
    out: list[VirtualWorkerBatch] = []
    for run_id, summary, seen in mine:
        children: dict[str, int] = {}
        for _child, child_summary, _at in summaries:
            if child_summary.get("parent_run_id") == run_id:
                status = str(child_summary.get("status") or "running")
                children[status] = children.get(status, 0) + 1
        open_ones = [
            str(one["request_id"])
            for one in store.rows(
                "SELECT request_id FROM approvals WHERE run_id = ? AND state = 'open' ORDER BY created_at", (run_id,)
            )
        ]
        out.append(
            VirtualWorkerBatch(
                run_id=run_id,
                status=summary.get("status") or "running",
                started_at=summary.get("started_at") or seen,
                children=sum(children.values()),
                children_by_status=children,
                open_approvals=open_ones,
            )
        )
    return out


def _info(store: Store, row: Any, *, with_batches: bool) -> VirtualWorkerInfo:
    return VirtualWorkerInfo(
        id=row["id"],
        name=row["name"],
        supervisors=_supervisors_of(row),
        intake=row["intake"],
        state=row["state"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        batches=_batches(store, str(row["intake"])) if with_batches else [],
    )


__all__ = [
    "create",
    "deploy_gate",
    "entry_gate",
    "get",
    "job_belongs",
    "listing",
    "reader",
    "remove",
    "runs_of",
    "update",
]

"""배포 — **봉투로만** 만들고 철회한다 (C2·C5).

Center는 배포를 **짓지 않는다.** Admin이 서명한 것을 받아 두었다가 하트비트로 그대로 내려
줄 뿐이다 (C4) — 재직렬화하면 서명이 깨지므로 **저장된 JSON 그대로** 다룬다.

- **철회된 `deployment_id`는 영구히 철회 상태**다. 같은 봉투를 다시 올려도 되살아나지 않는다.
- 같은 id에 다른 내용이 오면 409 `deployment_conflict`.
- 승인되지 않은 패키지는 배포할 수 없다 — **승인이 먼저**다.
- `target.type`은 패키지의 `run_location`과 맞아야 한다 (`pc`→`bot_ui`, `server`→`server_runner`).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from chaeksas.center.api.signing import STATUS_APPROVED, admin_keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.bot_ui import DeploymentResult
from chaeksas.contracts.center_api import RECENT_RESULTS, DeploymentInfo
from chaeksas.contracts.signing import Envelope, verify, verify_time

#: `run_location` → 배포 대상 종류 (C2 §배포 대상 규칙).
TARGET_FOR = {"pc": "bot_ui", "server": "server_runner"}


def _envelope(raw: Any) -> Envelope:
    try:
        return Envelope.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", f"봉투가 계약과 맞지 않는다: {e}") from e


def _refuse(problems: list[Any]) -> None:
    if not problems:
        return
    first = problems[0]
    raise ApiError(
        403,
        first.code or "bad_signature",
        first.message,
        detail={"violations": [{"rule": p.rule, "code": p.code, "message": p.message} for p in problems]},
    )


def create(store: Store, raw: Any) -> DeploymentInfo:
    """`deployment` 봉투를 받아 둔다 (C5 `POST /deployments`)."""
    envelope = _envelope(raw)
    keys = admin_keys(store)
    _refuse(verify(envelope, keys=keys, expect_kind="deployment"))
    # **예약 배포는 받아 둔다** — `not_before`는 실행하는 쪽이 적용할 때 본다 (C2 V5b).
    _refuse(verify_time(envelope, now=now_iso(), check_not_before=False))

    claim = envelope.payload
    deployment_id = str(claim.get("deployment_id") or "")
    body = json.dumps(envelope.to_json_dict(), ensure_ascii=False)

    found = store.row("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,))
    if found is not None:
        if found["revoked_json"]:
            # **철회된 것은 되살아나지 않는다** (C2).
            raise ApiError(409, "deployment_revoked", f"{deployment_id}은 철회됐다")
        if found["envelope_json"] != body:
            raise ApiError(409, "deployment_conflict", f"{deployment_id}에 다른 내용이 왔다")
        return _row(store, found)  # 멱등

    package = store.row(
        "SELECT status, content_hash, run_location FROM packages WHERE id = ? AND version = ?",
        (claim.get("bpm_process_id"), claim.get("version")),
    )
    if package is None:
        raise ApiError(404, "not_found", f"{claim.get('bpm_process_id')}@{claim.get('version')}이 없다")
    if package["status"] != STATUS_APPROVED:
        # **승인이 먼저다** — 서명 없는 것을 배포하면 받는 쪽이 어차피 거부한다 (V7).
        raise ApiError(
            409, "not_approved", f"승인되지 않은 패키지다 (지금 {package['status']})"
        )
    if claim.get("content_hash") != package["content_hash"]:
        raise ApiError(
            409,
            "hash_mismatch",
            f"해시가 다르다 (봉투 {claim.get('content_hash')}, 실제 {package['content_hash']})",
        )
    target = claim.get("target") or {}
    wanted = TARGET_FOR.get(str(package["run_location"] or ""))
    if wanted and target.get("type") != wanted:
        raise ApiError(
            409,
            "wrong_target",
            f"실행 위치 {package['run_location']}는 {wanted}에 배포한다 (받은 것 {target.get('type')})",
        )

    with store.tx() as cur:
        cur.execute(
            "INSERT INTO deployments (deployment_id, target_type, target_id, bpm_process_id, "
            "version, content_hash, envelope_json, revoked_json, at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (
                deployment_id,
                str(target.get("type") or ""),
                str(target.get("id") or ""),
                str(claim.get("bpm_process_id") or ""),
                str(claim.get("version") or ""),
                str(claim.get("content_hash") or ""),
                body,
                now_iso(),
            ),
        )
    return _row(store, store.row("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,)))


def revoke(store: Store, raw: Any) -> DeploymentInfo:
    """`revoke` 봉투 (C5 `DELETE /deployments`). **되살릴 수 없다.**"""
    envelope = _envelope(raw)
    _refuse(verify(envelope, keys=admin_keys(store), expect_kind="revoke"))
    deployment_id = str(envelope.payload.get("deployment_id") or "")
    found = store.row("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,))
    if found is None:
        raise ApiError(404, "not_found", f"그 배포가 없다: {deployment_id}")
    if found["revoked_json"]:
        return _row(store, found)  # 멱등
    with store.tx() as cur:
        cur.execute(
            "UPDATE deployments SET revoked_json = ? WHERE deployment_id = ?",
            (json.dumps(envelope.to_json_dict(), ensure_ascii=False), deployment_id),
        )
    return _row(store, store.row("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,)))


def listing(
    store: Store, *, target_id: str | None = None, active_only: bool = False
) -> list[DeploymentInfo]:
    """`GET /deployments` (C5). 철회된 것도 **행이 남으므로** 목록에 보인다."""
    rows = store.rows("SELECT * FROM deployments ORDER BY at DESC")
    out = [_row(store, one) for one in rows]
    if target_id:
        # `*` 배포는 모든 대상에 걸린다 — 그 Bot UI를 물어도 보여야 한다.
        out = [one for one in out if one.target.get("id") in (target_id, "*")]
    if active_only:
        out = [one for one in out if one.revoked_at is None]
    return out


def envelopes_for(store: Store, *, target_type: str, target_id: str) -> list[dict[str, Any]]:
    """그 대상의 **활성 배포 봉투**를 저장된 JSON 그대로 (C4 — 재직렬화하면 서명이 깨진다).

    **승인이 철회된 패키지의 배포는 빼고 준다** — 받는 쪽이 어차피 거부한다 (C2).
    """
    rows = store.rows(
        "SELECT d.envelope_json AS body FROM deployments d "
        "JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version "
        "WHERE d.revoked_json IS NULL AND p.status = ? AND d.target_type = ? "
        "AND (d.target_id = ? OR d.target_id = '*') ORDER BY d.at",
        (STATUS_APPROVED, target_type, target_id),
    )
    return [json.loads(one["body"]) for one in rows]


def versions_for(store: Store, *, target_type: str, target_id: str, bpm_process_id: str) -> list[str]:
    """그 대상에 **활성으로 배포된** 버전들 (C5 작업 만들기가 `version`을 푸는 데 쓴다).

    고르는 기준은 `envelopes_for`와 **같다** — 내려가는 것과 돌릴 수 있는 것이 어긋나면
    「배포는 됐는데 작업이 안 된다」가 된다. `not_before`·`expires_at`은 여기서 보지 않는다
    (C2 V5b — 때를 보는 것은 실행하는 쪽이다).
    """
    rows = store.rows(
        "SELECT d.version AS version FROM deployments d "
        "JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version "
        "WHERE d.revoked_json IS NULL AND p.status = ? AND d.target_type = ? "
        "AND (d.target_id = ? OR d.target_id = '*') AND d.bpm_process_id = ? ORDER BY d.at",
        (STATUS_APPROVED, target_type, target_id, bpm_process_id),
    )
    return [str(one["version"]) for one in rows]


def results_of(store: Store, *, bot_ui_id: str, limit: int = RECENT_RESULTS) -> list[DeploymentResult]:
    """그 Bot UI가 보고한 **최근 배치 결정** (C5 `BotUiInfo.deployment_results`, CON-03)."""
    rows = store.rows(
        "SELECT * FROM deployment_results WHERE bot_ui_id = ? ORDER BY at DESC LIMIT ?",
        (bot_ui_id, limit),
    )
    return [
        DeploymentResult(
            deployment_id=row["deployment_id"],
            bpm_process_id=row["bpm_process_id"],
            version=row["version"],
            result=row["result"],
            reason=row["reason"],
            at=row["at"],
        )
        for row in rows
    ]


def remember_results(store: Store, *, bot_ui_id: str, results: Sequence[DeploymentResult]) -> None:
    """하트비트가 실어 온 배치 결정을 쌓는다 (C4).

    **같은 `(deployment_id, at)`은 한 번만** — Bot UI가 보내 놓고 응답을 못 받아 다시 보내도
    목록이 부풀지 않는다.
    """
    for one in results:
        found = store.row(
            "SELECT 1 FROM deployment_results WHERE bot_ui_id = ? AND deployment_id = ? AND at = ?",
            (bot_ui_id, one.deployment_id, one.at),
        )
        if found is not None:
            continue
        with store.tx() as cur:
            cur.execute(
                "INSERT INTO deployment_results (bot_ui_id, deployment_id, bpm_process_id, version,"
                " result, reason, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    bot_ui_id,
                    one.deployment_id,
                    one.bpm_process_id,
                    one.version,
                    one.result,
                    one.reason,
                    one.at,
                ),
            )


def _last_result(store: Store, deployment_id: str) -> str | None:
    found = store.row(
        "SELECT result FROM deployment_results WHERE deployment_id = ? ORDER BY at DESC LIMIT 1",
        (deployment_id,),
    )
    return str(found["result"]) if found is not None else None


def _row(store: Store, row: Any) -> DeploymentInfo:
    """저장된 봉투에서 C5 `DeploymentInfo`를 짓는다.

    서명자·유효 기간은 **봉투에서 읽는다** — Center가 따로 짓지 않는다 (C5). 철회 시각은
    철회 봉투에서 온다 (행은 지우지 않는다).
    """
    envelope = json.loads(row["envelope_json"])
    claim = envelope.get("payload") or {}
    revoked = json.loads(row["revoked_json"]) if row["revoked_json"] else None
    return DeploymentInfo(
        deployment_id=row["deployment_id"],
        target={"type": row["target_type"], "id": row["target_id"]},
        bpm_process_id=row["bpm_process_id"],
        version=row["version"],
        content_hash=row["content_hash"],
        signed_by=str(envelope.get("key_id") or ""),
        signed_at=str(envelope.get("signed_at") or row["at"]),
        max_concurrency=claim.get("max_concurrency"),
        not_before=claim.get("not_before"),
        expires_at=claim.get("expires_at"),
        revoked_at=(revoked.get("payload") or {}).get("revoked_at") if revoked else None,
        last_result=_last_result(store, str(row["deployment_id"])),
    )


__all__ = [
    "TARGET_FOR",
    "create",
    "envelopes_for",
    "listing",
    "remember_results",
    "results_of",
    "revoke",
    "versions_for",
]

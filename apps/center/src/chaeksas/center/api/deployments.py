"""배포 — 관리자가 요청하면 **Center가 봉투를 지어 서명한다** (C2·C5, ADR-0090).

봉투를 지은 뒤에는 사람이 서명하던 때와 **같은 길**(`_accept`)을 지난다. 받아 둔 봉투는
하트비트로 그대로 내려 줄 뿐이다 (C4) — 재직렬화하면 서명이 깨지므로 **저장된 JSON 그대로**
다룬다. 누가 배포·철회했는지는 계정 이름으로 남긴다(`deployed_by`·`revoked_by`).

**무엇을 받아들이나는 계약이 정한다** (ADR-0047) —
`contracts.center_api.validate_deployment()`가 규칙(서명·승인 상태·해시·대상·M7)을 모두 보고,
상태 코드는 `deployment_refusal()`이 고른다. 여기서 규칙을 다시 적지 않는다 — 두 벌로 두었을
때 대상 어긋남이 한쪽에서 `target_mismatch`(422), 다른 쪽에서 `wrong_target`(409)이었다.

Center만 아는 것(저장소를 봐야 하는 것)이 여기 남는다:

- **철회된 `deployment_id`는 영구히 철회 상태**다. 같은 봉투를 다시 올려도 되살아나지 않는다.
- 같은 id에 다른 내용이 오면 409 `deployment_conflict`.
- 그 패키지가 Center에 있나 (404), 그리고 배포를 막는 리소스 누락(C7·C1 R8).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from chaeksas.center import signer
from chaeksas.center.api.signing import LIVE_STATUSES, admin_keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.bot_ui import DeploymentResult
from chaeksas.contracts.center_api import (
    RECENT_RESULTS,
    DeploymentInfo,
    DeploymentRequest,
    deployment_refusal,
    validate_deployment,
)
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.signing import TARGET_ANY, Envelope, verify, verify_time

#: `id`에 `"*"`로 **모두**를 가리킬 수 있는 대상 종류 (C2 §배포 대상 규칙, ADR-0046).
#:
#: **PC(`bot_ui`)는 들어 있지 않다** — `DeploymentTarget.matches`가 `*`를 서버 실행기에만
#: 주므로(V6) `{bot_ui, "*"}` 봉투는 **모든 PC가 `wrong_target`으로 거부한다**. 그런 것을
#: Center가 풀어 내려 주면 CON-03이 거짓 ⛔로 차고 운영자는 승인·해시·키를 뒤진다.
WILDCARD_TARGETS = frozenset({"server_runner"})


def _target_sql(target_type: str, target_id: str) -> tuple[str, tuple[str, ...]]:
    """`d.target_type`·`d.target_id`를 맞추는 WHERE 조각과 인자.

    **고르는 기준이 네 자리에서 같아야 한다** — `envelopes_for`(내려 주는 것)·
    `versions_for`(돌릴 수 있는 것)·`downloadable_by`(받을 수 있는 것)·`listing`(보이는 것)이
    어긋나면 「배포는 됐는데 설치가 안 된다」·「배포는 됐는데 작업이 안 된다」가 된다. 그래서
    **말로 적어 두지 않고 한 함수로** 짓는다.
    """
    if target_type in WILDCARD_TARGETS:
        return "d.target_type = ? AND (d.target_id = ? OR d.target_id = ?)", (
            target_type,
            target_id,
            TARGET_ANY,
        )
    return "d.target_type = ? AND d.target_id = ?", (target_type, target_id)


def live_sql() -> tuple[str, tuple[str, ...]]:
    """**살아 있는 배포**를 고르는 WHERE 조각과 인자 — 철회되지 않았고 패키지가 `LIVE_STATUSES`.

    `deployments d JOIN packages p`를 전제한다. **지원 종료(`deprecated`)도 받는다** (C5 §패키지 —
    「이미 배포된 것은 그대로 돈다」). 고르는 자리(하트비트 봉투·작업의 판·위임·일정·내려받기·
    메시지 시작)가 이 조건을 따로 적다가 모두 `approved` 하나로 걸러, 지원 종료가 돌던 것을
    세웠다 (09-gaps §3-22). 그래서 `_target_sql`처럼 **한 함수로** 짓는다.
    """
    marks = ", ".join("?" for _ in LIVE_STATUSES)
    return f"d.revoked_json IS NULL AND p.status IN ({marks})", LIVE_STATUSES


def _registered(store: Store, target: Any) -> bool | None:
    """그 대상이 Center에 있나 — **읽는 것은 Center, 판정은 계약이다** (ADR-0049·0047 ②).

    `None`은 **「묻지 않았다」**다. PC(`bot_ui`)만 명부(`bot_uis`)가 있으므로 나머지 종류는
    묻지 않고 넘긴다 — 서버 실행기는 M7이고(그쪽은 `server_runner_not_available`이 막는다)
    `False`를 주면 **없는 규칙으로** 막게 된다.

    **`bot_uis`를 아는 자리는 `api.bot_ui`다** — 키 묶기 규칙이 갈라지지 않게 거기로 묻는다.
    """
    if not isinstance(target, dict) or str(target.get("type") or "") != "bot_ui":
        return None
    from chaeksas.center.api import bot_ui  # noqa: PLC0415 — 순환 import를 피한다

    return bot_ui.exists(store, str(target.get("id") or ""))


def _envelope(raw: Any) -> Envelope:
    try:
        return Envelope.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", f"봉투가 계약과 맞지 않는다: {e}") from e


def _refuse(problems: Sequence[Any]) -> None:
    """위반 하나로 답한다 — **상태는 계약이 고른다** (C5 `deployment_refusal`, ADR-0047)."""
    picked = deployment_refusal(problems)
    if picked is None:
        return
    status, first = picked
    raise ApiError(
        status,
        first.code or "bad_signature",
        first.message,
        detail={"violations": [{"rule": p.rule, "code": p.code, "message": p.message} for p in problems]},
    )


def create(
    store: Store, wanted: DeploymentRequest, *, by: str, package_dir: Path | None = None
) -> DeploymentInfo:
    """배포한다 (C5 `POST /deployments`). Center가 `deployment` 봉투를 지어 서명한다 (ADR-0090).

    `deployment_id`는 새로 짓고 `content_hash`는 그 패키지의 것이다. 없는 패키지면 404다.
    """
    from chaeksas.center.api import packages  # noqa: PLC0415 — 순환 import를 피한다

    package = packages.info_of(store, wanted.bpm_process_id, wanted.version)
    claim: dict[str, Any] = {
        "kind": "deployment",
        "deployment_id": f"dep_{secrets.token_hex(4)}",
        "target": {"type": str(wanted.target.get("type") or ""), "id": str(wanted.target.get("id") or "")},
        "bpm_process_id": wanted.bpm_process_id,
        "version": wanted.version,
        "content_hash": package.content_hash,
    }
    for name in ("not_before", "expires_at", "max_concurrency"):
        value = getattr(wanted, name)
        if value is not None:
            claim[name] = value
    made = _accept(store, signer.seal(store, claim).to_json_dict(), package_dir=package_dir)
    with store.tx() as cur:
        cur.execute("UPDATE deployments SET deployed_by = ? WHERE deployment_id = ?", (by, made.deployment_id))
    return _row(store, store.row("SELECT * FROM deployments WHERE deployment_id = ?", (made.deployment_id,)))


def _accept(store: Store, raw: Any, *, package_dir: Path | None = None) -> DeploymentInfo:
    """서명된 `deployment` 봉투를 받아 둔다 — 사람이 서명하던 때부터 같은 관문이다.

    `package_dir`가 있으면 **가상 직원의 접수 BPM 프로세스 관문**도 본다 (ADR-0085 §2 — 그 판의 그림을 읽는다).
    """
    envelope = _envelope(raw)
    keys = admin_keys(store)
    # **봉투를 먼저 본다** — 패키지를 찾기 전에 막아야 없는 패키지의 404로 봉투의 진위가 새지
    # 않는다. 아래 `validate_deployment`가 같은 검사를 다시 하지만 **같은 계약 함수**라 답이
    # 갈리지 않는다 (순서만 당긴 것이다). **예약 배포는 받아 둔다** (C2 V5b는 실행하는 쪽).
    _refuse([*verify(envelope, keys=keys, expect_kind="deployment"),
             *verify_time(envelope, now=now_iso(), check_not_before=False)])

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

    from chaeksas.center.api import packages  # noqa: PLC0415 — 순환 import를 피한다

    # 없으면 404 (같은 메시지다) — 그다음은 **계약이 본다**: 승인 상태·지원 종료·해시·대상·M7.
    package = packages.info_of(
        store, str(claim.get("bpm_process_id") or ""), str(claim.get("version") or "")
    )
    _refuse(
        validate_deployment(
            envelope,
            package=package,
            keys=keys,
            now=now_iso(),
            target_registered=_registered(store, claim.get("target") or {}),
        )
    )

    _refuse_missing_resources(package.manifest, store)
    _refuse_unapproved_delegations(package.manifest, store)
    if package_dir is not None:
        from chaeksas.center.api import virtual_workers  # noqa: PLC0415 — 순환 import를 피한다

        # 묶인 뒤 **새 판**으로 결재 없는 일괄 기동이 들어오는 길을 막는다 (409 `intake_not_gated`).
        virtual_workers.deploy_gate(
            store, package_dir, bot=str(claim.get("bpm_process_id") or ""), version=str(claim.get("version") or "")
        )
    target = claim.get("target") or {}

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


def targets_for(store: Store, *, bpm_process_id: str, version: str, target_type: str) -> list[str]:
    """그 판이 **살아 있는 배포로 걸린 대상 id**들 (C5). PC 위임이 PC를 고를 때 쓴다.

    **고르는 기준을 다섯째 자리에 적지 않으려고** 여기 둔다 — `envelopes_for`와 같은 조건
    (`live_sql`)이고, 어긋나면 「배포는 됐는데 위임이 안 간다」가 된다
    (`_target_sql`의 각주와 같은 결).
    """
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT DISTINCT d.target_id AS id FROM deployments d"
        " JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version"
        f" WHERE {live} AND d.target_type = ?"
        "   AND d.bpm_process_id = ? AND d.version = ?",
        (*statuses, target_type, bpm_process_id, version),
    )
    return sorted(str(row["id"]) for row in rows)


def versions_deployed_to(store: Store, *, bpm_process_id: str, target_type: str) -> list[str]:
    """그 BPM 프로세스가 그 종류의 대상에 배포된 판들 (C5) — 위임이 판을 비웠을 때 고를 거리다."""
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT DISTINCT d.version AS v FROM deployments d"
        " JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version"
        f" WHERE {live} AND d.target_type = ?"
        "   AND d.bpm_process_id = ?",
        (*statuses, target_type, bpm_process_id),
    )
    return sorted(str(row["v"]) for row in rows)


def _refuse_unapproved_delegations(manifest: Manifest | None, store: Store) -> None:
    """**PC 위임으로 부르는 BPM 프로세스가 승인되어 있어야** 한다 (C12 §PC 위임, ADR-0062).

    C1 R8처럼 **배포 시점에** 본다 — 매니페스트만으로는 알 수 없다. 반대로 **PC에 배포됐는가는
    묻지 않는다**: 서버 BPM 프로세스를 먼저 배포하는 순서를 막으면 안 되고, 실제 관문은 위임을 요청할
    때다 (그때 `no_deployment`로 거절한다).

    판을 비운 위임(`<id>`)은 **승인된 판이 하나라도 있으면** 통과다 — 어느 판으로 돌릴지는
    요청할 때 정한다 (둘 이상이면 그때 `version_ambiguous`다).
    """
    from chaeksas.center.api.signing import STATUS_APPROVED  # noqa: PLC0415 — 순환 import를 피한다

    if manifest is None:  # pragma: no cover — 올릴 때 검증했다
        return
    missing: list[str] = []
    for ref in manifest.requires.delegations:
        bot, _, version = ref.partition("@")
        if version:
            row = store.row(
                "SELECT status FROM packages WHERE id = ? AND version = ?", (bot, version)
            )
            ok = row is not None and row["status"] == STATUS_APPROVED
        else:
            rows = store.rows("SELECT status FROM packages WHERE id = ?", (bot,))
            ok = any(row["status"] == STATUS_APPROVED for row in rows)
        if not ok:
            missing.append(ref)
    if not missing:
        return
    raise ApiError(
        422,
        "delegation_not_approved",
        f"PC 위임으로 부르는 BPM 프로세스가 승인되지 않았다: {missing[0]}",
        {"delegations": missing},
    )


def _refuse_missing_resources(manifest: Manifest | None, store: Store) -> None:
    """배포를 막는 누락만 거부한다 (C7 §누락 검사).

    **서비스 앱이 잠시 응답이 없다고 배포를 막지 않는다** — 막는 것은 확장 누락·해시
    불일치와 C1 R8(서버 BPM 프로세스의 작업)뿐이다. 그래서 여기서는 **두드리지 않는다**
    (`probe=False`) — 배포가 느린 앱을 기다리게 할 이유가 없다.
    """
    from chaeksas.center.api import resources  # noqa: PLC0415 — 순환 import를 피한다
    from chaeksas.contracts.resources import blocking_at_deploy, missing  # noqa: PLC0415

    if manifest is None:  # pragma: no cover — 올릴 때 검증했다
        return
    blocked = blocking_at_deploy(missing(manifest, resources.index(store, probe=False)))
    if not blocked:
        return
    first = blocked[0]
    raise ApiError(
        422,
        f"{first.type}_{first.reason}",
        f"필요한 리소스가 Center에 없다: {first.type} {first.id} ({first.reason})",
        {"missing_resources": [one.to_json_dict() for one in blocked]},
    )


def revoke(store: Store, deployment_id: str, *, reason: str, by: str) -> DeploymentInfo:
    """배포를 철회한다 (C5 `DELETE /deployments`). Center가 `revoke` 봉투를 지어 서명한다. **되살릴 수 없다.**"""
    found = store.row("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,))
    if found is None:
        raise ApiError(404, "not_found", f"그 배포가 없다: {deployment_id}")
    if found["revoked_json"]:
        return _row(store, found)  # 멱등
    envelope = signer.seal(
        store, {"kind": "revoke", "deployment_id": deployment_id, "reason": reason, "revoked_at": now_iso()}
    )
    with store.tx() as cur:
        cur.execute(
            "UPDATE deployments SET revoked_json = ?, revoked_by = ? WHERE deployment_id = ?",
            (json.dumps(envelope.to_json_dict(), ensure_ascii=False), by, deployment_id),
        )
    return _row(store, store.row("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,)))


def listing(
    store: Store,
    *,
    target_id: str | None = None,
    target_type: str = "bot_ui",
    active_only: bool = False,
) -> list[DeploymentInfo]:
    """`GET /deployments` (C5). 철회된 것도 **행이 남으므로** 목록에 보인다.

    좁히는 기준은 `envelopes_for`와 **같다** (ADR-0046) — 보이는 것과 내려가는 것이 어긋나면
    CON-03의 「배포」가 그 PC가 받지 못할 것을 보인다. 묻는 쪽이 종류를 적지 않으면 **PC**다
    (`GET /deployments?target_id=`는 PC 실행기 id를 받는다).
    """
    rows = store.rows("SELECT * FROM deployments ORDER BY at DESC")
    out = [_row(store, one) for one in rows]
    if target_id:
        wanted = {target_id} | ({TARGET_ANY} if target_type in WILDCARD_TARGETS else set())
        out = [one for one in out if one.target.get("id") in wanted]
    if active_only:
        out = [one for one in out if one.revoked_at is None]
    return out


def envelopes_for(store: Store, *, target_type: str, target_id: str) -> list[dict[str, Any]]:
    """그 대상의 **활성 배포 봉투**를 저장된 JSON 그대로 (C4 — 재직렬화하면 서명이 깨진다).

    **승인이 철회된 패키지의 배포는 빼고 준다** — 받는 쪽은 빠진 배포를 비활성으로 돌린다
    (C2 §검증 규칙, ADR-0113). **지원 종료는 빼지 않는다** (`live_sql`).
    """
    where, target = _target_sql(target_type, target_id)
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT d.envelope_json AS body FROM deployments d "
        "JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version "
        f"WHERE {live} AND {where} ORDER BY d.at",
        (*statuses, *target),
    )
    return [json.loads(one["body"]) for one in rows]


def versions_for(store: Store, *, target_type: str, target_id: str, bpm_process_id: str) -> list[str]:
    """그 대상에 **활성으로 배포된** 버전들 (C5 작업 만들기가 `version`을 푸는 데 쓴다).

    고르는 기준은 `envelopes_for`와 **같다** (`_target_sql`) — 내려가는 것과 돌릴 수 있는 것이
    어긋나면 「배포는 됐는데 작업이 안 된다」가 된다. `not_before`·`expires_at`은 여기서 보지
    않는다 (C2 V5b — 때를 보는 것은 실행하는 쪽이다).
    """
    where, target = _target_sql(target_type, target_id)
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT d.version AS version FROM deployments d "
        "JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version "
        f"WHERE {live} AND {where} "
        "AND d.bpm_process_id = ? ORDER BY d.at",
        (*statuses, *target, bpm_process_id),
    )
    return [str(one["version"]) for one in rows]


def server_versions(store: Store, *, bpm_process_id: str) -> list[str]:
    """그 BPM 프로세스가 **어느 서버 실행기에든** 활성으로 배포된 버전들 (C5 작업 만들기).

    `id`를 비운 서버 작업은 Center가 실행기를 고르므로(C5 `JobTarget`) 「어느 서버에
    배포됐나」가 아니라 **어디든 배포돼 있나**를 묻는다. `"*"` 배포도 센다 (ADR-0046).
    고르는 기준은 `envelopes_for`와 같다 (`live_sql`).
    """
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT DISTINCT d.version AS version FROM deployments d "
        "JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version "
        f"WHERE {live} AND d.target_type = ? "
        "AND d.bpm_process_id = ? ORDER BY d.version",
        (*statuses, "server_runner", bpm_process_id),
    )
    return [str(one["version"]) for one in rows]


def server_message_starts(store: Store, *, name: str) -> list[str]:
    """그 이름의 **메시지 시작 트리거**를 가진, 서버에 배포된 BPM 프로세스 id들 (C12 §메시지).

    고르는 기준은 `server_versions`와 같다 (`live_sql` — 살아 있는 서버 배포) — 배포되지
    않은 BPM 프로세스는 메시지로도 돌지 않는다. 트리거는 **매니페스트가 말한다** (C1 `triggers[]`) —
    Center가 그림을 읽지 않는다.

    버전은 돌려주지 않는다. **작업을 만드는 쪽이 고르게** 둔다 (`_resolved_version` — 둘 이상이면
    `version_ambiguous`다). 여기서 또 고르면 두 자리가 다른 답을 낸다.
    """
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT DISTINCT d.bpm_process_id AS id, p.manifest_json AS body FROM deployments d "
        "JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version "
        f"WHERE {live} AND d.target_type = ?",
        (*statuses, "server_runner"),
    )
    out = []
    for one in rows:
        manifest = Manifest.model_validate(json.loads(str(one["body"] or "{}")))
        if any(t.kind == "message" and t.name == name for t in manifest.triggers):
            out.append(str(one["id"]))
    return sorted(set(out))


def downloadable_by(store: Store, *, target_type: str, target_id: str) -> set[tuple[str, str]]:
    """그 대상이 **내려받을 수 있는** 패키지 `{(id, 버전)}` (C5 권한표).

    고르는 기준은 `envelopes_for`와 **같다** (`_target_sql`) — 내려가는 배포와 받을 수 있는
    파일이 어긋나면 「배포는 됐는데 설치가 안 된다」가 된다.

    **따로 받는 것은 없다.** 공유 BPM 프로세스(`requires.libs`)는 패키지 안 `libs/`로
    **복사해 넣은** 것이고(C1 §패키지 구성), 도구는 패키지로 오지 않는다
    ([ADR-0050](../../../../../../docs/decisions/0050-no-toolpack-kind.md)).
    """
    where, target = _target_sql(target_type, target_id)
    live, statuses = live_sql()
    rows = store.rows(
        "SELECT d.bpm_process_id AS id, d.version AS version"
        " FROM deployments d"
        " JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version"
        f" WHERE {live} AND {where}",
        (*statuses, *target),
    )
    return {(str(one["id"]), str(one["version"])) for one in rows}


def max_concurrency_for(store: Store, *, bpm_process_id: str) -> int | None:
    """그 BPM 프로세스의 **동시 실행 상한** — 서명된 배포 봉투가 정한다 (C2 `max_concurrency`, C12 §3).

    Center가 짓지 않는다 — 봉투에 적힌 값이고, 없으면 `None`이라 부르는 쪽이 계약의 기본값
    (5)을 쓴다. 활성 배포가 여럿이면 **가장 작은 값**이다 (가장 조심스러운 쪽을 따른다).
    """
    found: list[int] = []
    for row in store.rows(
        "SELECT envelope_json AS body FROM deployments"
        " WHERE revoked_json IS NULL AND target_type = ? AND bpm_process_id = ?",
        ("server_runner", bpm_process_id),
    ):
        claim = (json.loads(row["body"]) or {}).get("payload") or {}
        value = claim.get("max_concurrency")
        if isinstance(value, int) and value > 0:
            found.append(value)
    return min(found) if found else None


def results_of(store: Store, *, host_id: str, limit: int = RECENT_RESULTS) -> list[DeploymentResult]:
    """그 **보고한 쪽**의 최근 배치 결정 (C5 `BotUiInfo.deployment_results`, CON-03·CON-12).

    `host_id`는 PC(`bui_…`)이거나 서버 실행기(`srv_…`)다 (열 이름은 2판 단계가 고쳤다, ADR-0065).
    """
    rows = store.rows(
        "SELECT * FROM deployment_results WHERE host_id = ? ORDER BY at DESC LIMIT ?",
        (host_id, limit),
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


def remember_results(store: Store, *, host_id: str, results: Sequence[DeploymentResult]) -> None:
    """하트비트가 실어 온 배치 결정을 쌓는다 (C4).

    **같은 `(deployment_id, at)`은 한 번만** — PC 실행기가 보내 놓고 응답을 못 받아 다시 보내도
    목록이 부풀지 않는다.
    """
    for one in results:
        found = store.row(
            "SELECT 1 FROM deployment_results WHERE host_id = ? AND deployment_id = ? AND at = ?",
            (host_id, one.deployment_id, one.at),
        )
        if found is not None:
            continue
        with store.tx() as cur:
            cur.execute(
                "INSERT INTO deployment_results (host_id, deployment_id, bpm_process_id, version,"
                " result, reason, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    host_id,
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
        deployed_by=row["deployed_by"],
        revoked_by=row["revoked_by"],
    )


__all__ = [
    # `run_location` → 대상 종류 표는 **계약에 하나**다 (`TARGET_TYPE_FOR_RUN_LOCATION`, ADR-0047).
    "WILDCARD_TARGETS",
    "server_versions",
    "create",
    "envelopes_for",
    "listing",
    "live_sql",
    "remember_results",
    "results_of",
    "revoke",
    "versions_for",
]

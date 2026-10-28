"""리소스 목록 — Bot이 실행에 필요로 하는 바깥 자원 (C7, CON-07).

네 종류를 모은다. **Center가 이미 가진 것에서 계산한다** — 따로 등록받지 않는다.

| 종류 | 어디서 |
| --- | --- |
| 서비스 앱 | 그 앱 id를 토픽으로 승인받은 **일꾼이 올린 manifest** (C15) |
| 런타임 | `bot_uis`가 등록·하트비트로 보고한 것 (C4) |
| 확장 | 실행하는 쪽의 보고(`bot_uis`·`server_runners` — C4·C12) + 일꾼 manifest의 `extension` |
| | + **외부로 등록된 정의** (C13) |
| 확장 기여 자원 | 일꾼이 올린 카탈로그 (C15 `PUT …/consumers/self/catalogs/{type}`) |

**Center는 바깥 기능을 읽으러 가지 않는다** (ADR-0102) — 주소도 키도 들지 않고, 상태는 그 토픽을
가져가는 일꾼이 말한다(마지막으로 가져간 때).

외부 확장은 **서명 봉투로만** 등록·해제된다 (C2 `extension`·`extension_revoke`, C13 E6).
내장·사내 확장은 설치 파일에 든 것만 쓰고 여기 들어오지 않는다 (E2).

**기여 자원의 `data`는 해석하지 않는다** (C13 §5) — 그래서 플랫폼 코드에 「UI 화면」이라는 말이
없다 (ADR-0018).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import ONLINE_WITHIN_S
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.extension import Catalog
from chaeksas.contracts.resources import (
    ContributedResource,
    ExtensionResource,
    InstalledOn,
    RuntimeHost,
    RuntimeResource,
    ServiceAppResource,
)
from chaeksas.contracts.service_app import ServiceAppManifest

#: 서비스 앱 상태 (C7). 열린 문자열이지만 Center가 짓는 것은 이 넷이다.
OK = "ok"
DEGRADED = "degraded"
UNREACHABLE = "unreachable"
UNKNOWN = "unknown"

#: `GET /resources?type=`로 물을 수 있는 종류.
KNOWN_TYPES = ("extension", "service_app", "contributed", "runtime")


# ─────────────────────────── 토픽 — 일꾼이 말하는 상태 (C7·C15) ───────────────────────────


def _manifests_of(raw: str | None) -> list[ServiceAppManifest]:
    """일꾼 줄의 manifest들 (토픽마다 하나). 깨진 것은 건너뛴다 — 목록을 멈추지 않는다."""
    found = loads(raw)
    items = found if isinstance(found, list) else ([found] if isinstance(found, dict) else [])
    out = []
    for one in items:
        try:
            out.append(ServiceAppManifest.model_validate(one))
        except ValueError:
            continue
    return out


def topic_state(store: Store, topic: str, *, now: str | None = None) -> tuple[str, int, str | None]:
    """`(상태, 일꾼 수, 마지막으로 가져간 때)` — 일꾼이 없으면 `unknown`, 있는데 90초 넘게 조용하면
    `unreachable`, 아니면 `ok` (C7 §리소스 모으는 방식)."""
    at = datetime.fromisoformat(now or now_iso())
    count, last = 0, None
    for row in store.rows("SELECT topics_json, last_fetch_at FROM consumers"):
        if topic not in (loads(row["topics_json"], []) or []):
            continue
        count += 1
        seen = row["last_fetch_at"]
        if seen and (last is None or datetime.fromisoformat(seen) > datetime.fromisoformat(last)):
            last = seen
    if count == 0:
        return UNKNOWN, 0, None
    if last is None or datetime.fromisoformat(last) < at - timedelta(seconds=ONLINE_WITHIN_S):
        return UNREACHABLE, count, last
    return OK, count, last


def app_manifests(store: Store) -> dict[str, tuple[ServiceAppManifest, str]]:
    """app_id → (manifest, 올린 때). 같은 토픽을 둘이 맡으면 **나중에 승인된 쪽**이 이긴다."""
    out: dict[str, tuple[ServiceAppManifest, str]] = {}
    for row in store.rows("SELECT topics_json, manifest_json, approved_at FROM consumers ORDER BY approved_at"):
        granted = set(loads(row["topics_json"], []) or [])
        for one in _manifests_of(row["manifest_json"]):
            if one.app_id in granted:
                out[one.app_id] = (one, str(row["approved_at"]))
    return out


# ─────────────────────────── 서비스 앱 ───────────────────────────


def _approved_manifests(store: Store) -> list[dict[str, Any]]:
    """승인·배포 대상이 되는 패키지의 C1 매니페스트 (「이것을 쓰는 Bot」을 세는 바탕)."""
    rows = store.rows("SELECT id, version, manifest_json FROM packages WHERE kind = 'bpm_process' ORDER BY id, version")
    out = []
    for row in rows:
        found = loads(row["manifest_json"], {}) or {}
        found["__ref"] = f"{row['id']}@{row['version']}"
        out.append(found)
    return out


def _used_by(store: Store, app_id: str) -> list[str]:
    """그 서비스 앱을 `requires`에 적은 BPM 프로세스들 (`id@version`)."""
    out = []
    for manifest in _approved_manifests(store):
        apps = (manifest.get("requires") or {}).get("service_apps") or []
        if any(str((one or {}).get("app_id")) == app_id for one in apps if isinstance(one, dict)):
            out.append(str(manifest["__ref"]))
    return out


def _extension_used_by(store: Store, extension_id: str) -> list[str]:
    out = []
    for manifest in _approved_manifests(store):
        found = (manifest.get("requires") or {}).get("extensions") or []
        if any(str((one or {}).get("id")) == extension_id for one in found if isinstance(one, dict)):
            out.append(str(manifest["__ref"]))
    return out


def service_app(store: Store, app_id: str) -> ServiceAppResource:
    """서비스 앱 하나 (C7 `GET /resources/service-apps/{id}`)."""
    found = next((one for one in service_apps(store) if one.app_id == app_id), None)
    if found is None:
        raise ApiError(404, "not_found", f"서비스 앱 {app_id}가 없다 — 그 토픽을 맡은 일꾼이 없다")
    return found


def service_apps(store: Store, *, probe: bool = True) -> list[ServiceAppResource]:
    """서비스 앱 — 일꾼이 올린 manifest에서 (C7). `probe`는 옛 이름이라 받기만 한다 (두드릴 곳이 없다)."""
    del probe
    out = []
    # 외부 확장 토픽의 manifest(어댑터 일꾼이 정의에서 지어 올린 것)는 **서비스 앱이 아니다** — 그 확장의
    # 줄(`ExtensionResource`)에 이미 있다. 작업·모드 대조(C15)에만 쓴다.
    external = set(_external_rows(store))
    for app_id, (manifest, at) in sorted(app_manifests(store).items()):
        if app_id in external:
            continue
        state, count, last = topic_state(store, app_id)
        out.append(
            ServiceAppResource(
                app_id=app_id,
                name=manifest.name,
                version=manifest.version,
                category=manifest.category,
                extension_id=manifest.extension.id if manifest.extension else None,
                console_url=manifest.console_url,
                operations=list(manifest.operations),
                status=state,
                status_reasons=[] if state == OK else (["no_consumer"] if count == 0 else ["consumer_quiet"]),
                checked_at=last,
                manifest_at=at,
                used_by=_used_by(store, app_id),
                consumers=count,
            )
        )
    return out


def runtimes(store: Store) -> list[RuntimeResource]:
    """런타임 (C4 등록·하트비트가 보고한 그대로). 서버 실행기는 M7이다."""
    out = []
    for row in store.rows("SELECT * FROM bot_uis ORDER BY name"):
        reported = loads(row["runtimes_json"], {}) or {}
        versions = loads(row["versions_json"], {}) or {}
        out.append(
            RuntimeResource(
                host=RuntimeHost(type="bot_ui", id=str(row["bot_ui_id"]), name=str(row["name"])),
                os=str(row["os"]),
                versions={k: str(v) for k, v in versions.items() if v},
                browsers=[str(one) for one in (reported.get("browsers") or [])],
                desktop_backend=reported.get("desktop_backend"),
                extensions=[one for one in (reported.get("extensions") or []) if isinstance(one, dict)],
            )
        )
    return out


def extensions(store: Store, *, probe: bool = True) -> list[ExtensionResource]:
    """확장 — 실행하는 쪽의 보고와 일꾼 manifest와 외부 정의를 **합친** 것 (C7)."""
    found: dict[str, dict[str, Any]] = {}

    # 1) 실행하는 쪽이 보고한 것 — 몇 대에 깔렸는지는 여기서만 안다. **PC와 서버를 함께 센다**.
    reports = [
        (loads(row["state_json"], {}) or {}).get("extensions")
        or (loads(row["runtimes_json"], {}) or {}).get("extensions")
        or []
        for row in store.rows("SELECT runtimes_json, state_json FROM bot_uis")
    ] + [loads(row["extensions_json"], []) or [] for row in store.rows("SELECT extensions_json FROM server_runners")]
    for installed in reports:
        for one in installed:
            if not isinstance(one, dict) or not one.get("id"):
                continue
            key = str(one["id"])
            version = str(one.get("version") or "")
            slot = found.setdefault(key, {"versions": {}, "hosts": 0, "hash": None})
            slot["hosts"] += 1
            slot["versions"][version] = slot["versions"].get(version, 0) + 1
            slot["hash"] = slot["hash"] or one.get("definition_hash")

    # 2) 일꾼 manifest의 `extension` — 서버 부분이 있는 확장은 여기서 이름·버전이 온다.
    apps = {one.extension_id: one for one in service_apps(store, probe=probe) if one.extension_id}
    # 3) Center에 **외부로 등록된** 정의 (C13) — 이름·등급·어댑터는 정의가 원본이다.
    external = _external_rows(store)

    out = []
    for key in sorted(set(found) | set(apps) | set(external)):
        slot = found.get(key, {"versions": {}, "hosts": 0, "hash": None})
        app = apps.get(key)
        registered = external.get(key)
        definition = json.loads(registered["definition_json"]) if registered is not None else None
        versions = slot["versions"]
        # 서버 부분 상태는 **그 토픽의 일꾼**이 말한다 — C11 앱은 앱 id, 외부 확장은 확장 id가 토픽이다.
        if app is not None:
            status, reasons, checked = app.status, list(app.status_reasons), app.checked_at
        elif definition is not None:
            status, count, checked = topic_state(store, key)
            reasons = [] if status == OK else (["no_consumer"] if count == 0 else ["consumer_quiet"])
        else:
            status, reasons, checked = "n/a", [], None
        out.append(
            ExtensionResource(
                id=key,
                version=(
                    str(definition["version"])
                    if definition
                    else (max(versions, key=lambda v: versions[v]) if versions else (app.version or "" if app else ""))
                ),
                name=(definition.get("name") if definition else None) or (app.name if app else None),
                publisher=definition.get("publisher") if definition else None,
                tier=str(definition["tier"]) if definition else "builtin",
                definition_hash=(str(registered["definition_hash"]) if registered is not None else slot["hash"]),
                protocol=_protocol_of(definition, app),
                contributes_summary=_contributes_of(definition),
                service_app_id=app.app_id if app else None,
                installed_on=InstalledOn(hosts=int(slot["hosts"]), by_version=dict(versions)),
                status=status,
                status_reasons=reasons,
                checked_at=checked,
                definition=definition,
                envelope=json.loads(registered["envelope_json"]) if registered is not None else None,
            )
        )
    return out


def _protocol_of(definition: dict[str, Any] | None, app: ServiceAppResource | None) -> str | None:
    """연결 방식 (C7). 정의가 있으면 그것이, 없으면 서버 부분이 있는지가 정한다."""
    if definition:
        found = (definition.get("service") or {}).get("protocol")
        return str(found) if found else None
    return "chk-c11" if app else None


def _contributes_of(definition: dict[str, Any] | None) -> dict[str, list[str]]:
    """기여 지점별 이름 (C7 `contributes_summary`). Center는 뜻을 해석하지 않는다."""
    if not definition:
        return {}
    out: dict[str, list[str]] = {}
    for where, items in (definition.get("contributes") or {}).items():
        if isinstance(items, list):
            names = [str(one.get("id") or one.get("type") or "") for one in items if isinstance(one, dict)]
            out[str(where)] = [one for one in names if one]
    return out


# ─────────────────────────── 확장 기여 자원 (C7·C13 §5) ───────────────────────────


def put_catalog(
    store: Store, *, consumer: Any, resource_type: str, raw: dict[str, Any], now: str | None = None
) -> dict[str, Any]:
    """`PUT /consumers/self/catalogs/{type}` (C15) — 일꾼이 올린 카탈로그를 쌓는다.

    **`revision`이 같으면 항목을 다시 쓰지 않는다** (C7) — 같은 것을 다시 쓰면 Studio·Worker의
    계획 캐시가 공연히 버려진다. 승인된 토픽의 것만 받는다.
    """
    app_id = str(raw.get("app_id") or "")
    if app_id not in set(loads(consumer["topics_json"], []) or []):
        raise ApiError(403, "topic_not_granted", f"승인받지 않은 토픽이다: {app_id or '(없음)'}")
    try:
        catalog = Catalog.model_validate(raw.get("catalog") or {})
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "카탈로그가 C13 §5와 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e
    extension_id = _extension_of(store, app_id)
    source = {
        "source": f"consumer:{app_id}:{resource_type}",
        "resource_type": resource_type,
        "extension_id": extension_id,
    }
    at = now or now_iso()
    before = store.row("SELECT * FROM catalog_reads WHERE source = ?", (source["source"],))
    same = before is not None and before["revision"] is not None and before["revision"] == catalog.revision
    with store.tx() as cur:
        cur.execute("DELETE FROM catalog_reads WHERE source = ?", (source["source"],))
        cur.execute(
            "INSERT INTO catalog_reads (source, resource_type, extension_id, revision, read_at, error)"
            " VALUES (?, ?, ?, ?, ?, NULL)",
            (source["source"], resource_type, extension_id, catalog.revision, at),
        )
    if not same:
        _store_items(store, source, catalog, at=at)
    return {"resource_type": resource_type, "revision": catalog.revision, "stored": not same}


def _extension_of(store: Store, app_id: str) -> str | None:
    """카탈로그를 올린 토픽의 확장 — C11 앱이면 manifest의 `extension`, 외부 확장이면 그 id."""
    found = app_manifests(store).get(app_id)
    if found is not None and found[0].extension is not None:
        return found[0].extension.id
    if app_id in _external_rows(store):
        return app_id
    return None


def _store_items(store: Store, source: dict[str, Any], catalog: Any, *, at: str) -> None:
    """그 종류의 항목을 **이 출처가 준 것으로 맞춘다** (없어진 것은 지운다)."""
    kept = {str(one.id) for one in catalog.items if one.type == source["resource_type"]}
    with store.tx() as cur:
        for row in store.rows(
            "SELECT id FROM contributed_resources WHERE resource_type = ?", (source["resource_type"],)
        ):
            if str(row["id"]) not in kept:
                cur.execute(
                    "DELETE FROM contributed_resources WHERE resource_type = ? AND id = ?",
                    (source["resource_type"], row["id"]),
                )
        for one in catalog.items:
            if one.type != source["resource_type"]:
                continue  # 카탈로그가 남의 종류를 담아 보내도 받지 않는다
            cur.execute(
                "DELETE FROM contributed_resources WHERE resource_type = ? AND id = ?",
                (one.type, one.id),
            )
            cur.execute(
                "INSERT INTO contributed_resources (resource_type, id, extension_id, name, summary,"
                " updated_at, revision, data_json, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    one.type,
                    one.id,
                    source["extension_id"],
                    one.name,
                    one.summary,
                    one.updated_at,
                    catalog.revision,
                    dumps(one.data) if one.data else None,
                    at,
                ),
            )


def contributed(store: Store, *, resource_type: str | None = None, probe: bool = False) -> list[ContributedResource]:
    """확장이 기여한 자원 (C7). **Center는 `data`를 해석하지 않는다** (C13 §5)."""
    del probe
    rows = store.rows(
        "SELECT * FROM contributed_resources ORDER BY resource_type, id"
        if resource_type is None
        else "SELECT * FROM contributed_resources WHERE resource_type = ? ORDER BY id",
        () if resource_type is None else (resource_type,),
    )
    return [
        ContributedResource(
            resource_type=str(row["resource_type"]),
            id=str(row["id"]),
            name=row["name"],
            summary=row["summary"],
            updated_at=row["updated_at"],
            extension_id=row["extension_id"],
            revision=row["revision"],
            data=loads(row["data_json"], {}) or {},
            used_by=_resource_used_by(store, str(row["resource_type"]), str(row["id"])),
        )
        for row in rows
    ]


def _resource_used_by(store: Store, resource_type: str, resource_id: str) -> list[str]:
    """그 자원을 `requires.resources`에 적은 BPM 프로세스들 (C1)."""
    out = []
    for manifest in _approved_manifests(store):
        found = (manifest.get("requires") or {}).get("resources") or []
        if any(
            str((one or {}).get("type")) == resource_type and str((one or {}).get("id")) == resource_id
            for one in found
            if isinstance(one, dict)
        ):
            out.append(str(manifest["__ref"]))
    return out


def catalog_kinds(store: Store) -> list[dict[str, Any]]:
    """지금 알고 있는 기여 자원 종류들 (CON-07 탭 하나씩) — 일꾼 manifest·외부 정의가 선언한 것."""
    out: dict[str, dict[str, Any]] = {}
    for manifest, _ in app_manifests(store).values():
        for one in manifest.resources:
            slot = out.setdefault(
                one.type, {"resource_type": one.type, "label": one.label or one.type, "extensions": [], "errors": []}
            )
            if manifest.extension and manifest.extension.id not in slot["extensions"]:
                slot["extensions"].append(manifest.extension.id)
    for key, row in _external_rows(store).items():
        definition = json.loads(row["definition_json"])
        for declared in (definition.get("contributes") or {}).get("resources") or []:
            if not isinstance(declared, dict) or not declared.get("type"):
                continue
            slot = out.setdefault(
                str(declared["type"]),
                {
                    "resource_type": str(declared["type"]),
                    "label": str(declared.get("label") or declared["type"]),
                    "extensions": [],
                    "errors": [],
                },
            )
            if key not in slot["extensions"]:
                slot["extensions"].append(key)
    for kind in out.values():
        kind["count"] = len(
            store.rows("SELECT id FROM contributed_resources WHERE resource_type = ?", (kind["resource_type"],))
        )
    return sorted(out.values(), key=lambda kind: str(kind["resource_type"]))


# ─────────────────────────── 외부 확장 등록 (C13·C2) ───────────────────────────


def _refuse(problems: list[Any], *, status: int = 422) -> None:
    if not problems:
        return
    first = problems[0]
    raise ApiError(
        status,
        first.code or "input_invalid",
        first.message,
        detail={
            "violations": [
                {"rule": p.rule, "code": p.code, "message": p.message, "items": list(p.items or [])} for p in problems
            ]
        },
    )


def register_extension(store: Store, found: Caller, raw: dict[str, Any]) -> tuple[ExtensionResource, bool]:
    """`POST /resources/extensions` — 정의를 받아 **Center가 `extension` 봉투로 서명한다** (C13 E6, ADR-0090).

    관문은 관리자 계정이다. 검사(E1·E2·E3·E4·E8)를 모두 지난 정의에만 서명한다 — 정의가 Bot의
    키를 어느 주소로 보낼지 정하므로 배포와 같은 관문이다. 봉투는 정의와 함께 그대로 두고
    실행하는 쪽이 다시 검증한다(E6).
    """
    from chaeksas.center import signer  # noqa: PLC0415
    from chaeksas.center.api.signing import admin_keys  # noqa: PLC0415 — 순환 import를 피한다
    from chaeksas.contracts.extension import (  # noqa: PLC0415
        ExtensionManifest,
        check_size,
        definition_hash,
        environment_conflicts,
        task_type_conflicts,
        validate,
        verify_external,
    )

    definition = raw.get("definition")
    if not isinstance(definition, dict):
        raise ApiError(422, "input_invalid", "`definition`에 확장 정의를 보내세요")

    _refuse(check_size(json.dumps(definition, ensure_ascii=False).encode("utf-8")), status=413)
    try:
        manifest = ExtensionManifest.model_validate(definition)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "확장 정의가 C13과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e

    # E1·E2·E3 — 외부 확장에 코드 기여가 없고, 등급이 external이고, 어댑터 선언이 안전한가.
    _refuse(validate(manifest, from_center=True))

    # E4·E8 — 이미 등록된 **다른** 확장들과 겹치지 않는가.
    others = [one for one in _registered_manifests(store) if one.id != manifest.id]
    _refuse(task_type_conflicts([*others, manifest]), status=409)
    _refuse(environment_conflicts([*others, manifest]), status=409)

    computed = definition_hash(definition)
    body = json.dumps(definition, ensure_ascii=False, sort_keys=True)

    before = store.row("SELECT * FROM extensions WHERE id = ? AND version = ?", (manifest.id, manifest.version))
    if before is not None:
        if before["revoked_json"]:
            # **철회된 판은 되살아나지 않는다** (배포·패키지와 같은 규칙, C2).
            raise ApiError(409, "extension_revoked", f"{manifest.id}@{manifest.version}은 철회됐다")
        if before["definition_hash"] != computed:
            raise ApiError(409, "id_conflict", f"{manifest.id}@{manifest.version}에 다른 정의가 왔다")
        return extension(store, manifest.id), False

    envelope = signer.seal(
        store,
        {"kind": "extension", "id": manifest.id, "version": manifest.version, "definition_hash": computed},
    )
    # E6 — 현장이 할 검증을 지금 한 번 — 지은 봉투가 **이 정의**에 맞는가 (해시·id·버전·키).
    _refuse(verify_external(definition, envelope, keys=admin_keys(store)), status=400)
    envelope_body = json.dumps(envelope.to_json_dict(), ensure_ascii=False)
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO extensions (id, version, definition_json, envelope_json, definition_hash,"
            " revoked_json, at, registered_by) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
            (manifest.id, manifest.version, body, envelope_body, computed, now_iso(), found.actor),
        )
    return extension(store, manifest.id), True


def revoke_extension(store: Store, extension_id: str, version: str, *, reason: str, by: str) -> ExtensionResource:
    """`DELETE /resources/extensions` — Center가 `extension_revoke` 봉투를 지어 서명한다 (C13·C2, ADR-0090).

    **쓰는 Bot이 있어도 막지 않는다** (C13) — 확장 해제는 **정의에 문제가 있어 거두는 보안 동작**이라,
    쓰는 쪽이 있을 때 더 거둬야 한다. 몇 개가 실행 불가가 되는지는 화면이 미리 말한다 (CON-07).
    """
    from chaeksas.center import signer  # noqa: PLC0415

    found = store.row("SELECT * FROM extensions WHERE id = ? AND version = ?", (extension_id, version))
    if found is None:
        raise ApiError(404, "not_found", f"등록된 확장이 없다: {extension_id}@{version}")
    if not found["revoked_json"]:
        envelope = signer.seal(
            store,
            {
                "kind": "extension_revoke",
                "id": extension_id,
                "version": version,
                "reason": reason,
                "revoked_at": now_iso(),
            },
        )
        with store.tx() as cur:
            cur.execute(
                "UPDATE extensions SET revoked_json = ?, revoked_by = ? WHERE id = ? AND version = ?",
                (json.dumps(envelope.to_json_dict(), ensure_ascii=False), by, extension_id, version),
            )
    # **철회된 것은 목록에서 빠지므로** `extension()`으로는 찾을 수 없다 — 저장된 줄에서 짓는다.
    return _revoked_info(store, extension_id, version)


def _revoked_info(store: Store, extension_id: str, version: str) -> ExtensionResource:
    """철회된 확장 하나 (철회 응답에만 쓴다 — 목록에는 뜨지 않는다)."""
    row = store.row("SELECT * FROM extensions WHERE id = ? AND version = ?", (extension_id, version))
    if row is None:  # pragma: no cover — 방금 본 줄이다
        raise ApiError(404, "not_found", f"등록된 확장이 없다: {extension_id}@{version}")
    definition = json.loads(row["definition_json"])
    return ExtensionResource(
        id=extension_id,
        version=version,
        name=definition.get("name"),
        publisher=definition.get("publisher"),
        tier=str(definition["tier"]),
        definition_hash=str(row["definition_hash"]),
        protocol=_protocol_of(definition, None),
        contributes_summary=_contributes_of(definition),
        status="n/a",
        definition=definition,
        envelope=json.loads(row["envelope_json"]),
    )


def _registered_manifests(store: Store) -> list[Any]:
    """등록돼 있고 **철회되지 않은** 외부 확장 정의들 (E4·E8 대조에 쓴다)."""
    from chaeksas.contracts.extension import ExtensionManifest  # noqa: PLC0415

    out = []
    for row in store.rows("SELECT definition_json FROM extensions WHERE revoked_json IS NULL ORDER BY id, version"):
        try:
            out.append(ExtensionManifest.model_validate(json.loads(row["definition_json"])))
        except ValueError:  # pragma: no cover — 등록할 때 검증했다
            continue
    return out


def _external_rows(store: Store) -> dict[str, Any]:
    """id → 가장 최근에 등록된(철회되지 않은) 외부 확장 줄."""
    out: dict[str, Any] = {}
    for row in store.rows("SELECT * FROM extensions WHERE revoked_json IS NULL ORDER BY id, at"):
        out[str(row["id"])] = row  # 같은 id는 나중 것이 이긴다
    return out


def index(store: Store, *, probe: bool = False) -> Any:
    """누락 검사에 넘길 리소스 묶음 (C7 `ResourceIndex`)."""
    from chaeksas.contracts.resources import ResourceIndex  # noqa: PLC0415

    return ResourceIndex(
        extensions=extensions(store, probe=probe),
        service_apps=service_apps(store, probe=probe),
        contributed=_cached_contributed(store),
    )


def listing(store: Store, *, type: str | None = None, resource_type: str | None = None) -> dict[str, Any]:
    """`GET /resources?type=[&resource_type=]` (C7 §목록 응답 공통 — `{items, fetched_at}`)."""
    if type is not None and type not in KNOWN_TYPES:
        raise ApiError(422, "input_invalid", f"모르는 리소스 종류다: {type}")
    picked = (type,) if type else KNOWN_TYPES
    items: list[Any] = []
    for one in picked:
        if one == "service_app":
            items += service_apps(store)
        elif one == "runtime":
            items += runtimes(store)
        elif one == "extension":
            items += extensions(store)
        elif one == "contributed":
            items += contributed(store, resource_type=resource_type)
    return {"items": [one.to_json_dict() for one in items], "fetched_at": now_iso()}


def extension(store: Store, extension_id: str) -> ExtensionResource:
    found = next((one for one in extensions(store) if one.id == extension_id), None)
    if found is None:
        raise ApiError(404, "not_found", f"확장 {extension_id}가 없다")
    # 「이 확장을 쓰는 Bot」은 상세에서만 센다 (목록마다 매니페스트를 다 읽지 않게).
    extra = dict(found.to_json_dict())
    extra["used_by"] = _extension_used_by(store, extension_id)
    return ExtensionResource.model_validate(extra)


def _cached_contributed(store: Store) -> list[ContributedResource]:
    """들고 있는 기여 자원 (두드리지 않는다) — 누락 검사·배포가 쓴다."""
    return [
        ContributedResource(
            resource_type=str(row["resource_type"]),
            id=str(row["id"]),
            name=row["name"],
            summary=row["summary"],
            updated_at=row["updated_at"],
            extension_id=row["extension_id"],
            revision=row["revision"],
            data=loads(row["data_json"], {}) or {},
        )
        for row in store.rows("SELECT * FROM contributed_resources ORDER BY resource_type, id")
    ]


def contributed_resource(store: Store, resource_type: str, resource_id: str) -> ContributedResource:
    """`GET /resources/contributed/{type}/{id}` (C7)."""
    found = next(
        (one for one in contributed(store, resource_type=resource_type) if one.id == resource_id),
        None,
    )
    if found is None:
        raise ApiError(404, "not_found", f"기여 자원이 없다: {resource_type}/{resource_id}")
    return found


__all__ = [
    "DEGRADED",
    "KNOWN_TYPES",
    "OK",
    "UNKNOWN",
    "UNREACHABLE",
    "catalog_kinds",
    "contributed",
    "contributed_resource",
    "extension",
    "extensions",
    "index",
    "listing",
    "app_manifests",
    "put_catalog",
    "register_extension",
    "revoke_extension",
    "runtimes",
    "service_app",
    "service_apps",
    "topic_state",
]

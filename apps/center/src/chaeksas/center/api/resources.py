"""리소스 목록 — Bot이 실행에 필요로 하는 바깥 자원 (C7, CON-07).

다섯 종류를 모은다. **넷은 Center가 이미 가진 것에서 계산한다** — 따로 등록받지 않는다.

| 종류 | 어디서 |
| --- | --- |
| 서비스 앱 | 운영자가 등록한 주소 + Center가 읽은 C11 `/manifest`·`/healthz` |
| 툴팩 | `packages` 표의 `kind=toolpack` (C5) |
| 런타임 | `bot_uis`가 등록·하트비트로 보고한 것 (C4) |
| 확장 | 실행하는 쪽의 보고 + 서비스 앱 manifest의 `extension` + **외부로 등록된 정의**(C13) |
| 확장 기여 자원 | 카탈로그를 읽어 쌓은 것 (C13 §5) |

기여 자원의 **출처는 둘이고 모양은 같다** — 내장·사내는 C11 manifest의 `resources`,
외부는 등록된 정의의 `contributes.resources`다.

**Center는 서비스 앱 키를 갖지 않는다** (ADR-0013) — 읽는 것은 인증이 필요 없는 공개
정보뿐이다 (`/healthz`·`/manifest`·카탈로그).

외부 확장은 **서명 봉투로만** 등록·해제된다 (C2 `extension`·`extension_revoke`, C13 E6) —
정의가 Bot의 키를 어느 주소로 보낼지 정하므로 배포와 같은 관문을 둔다. 내장·사내 확장은
설치 파일에 든 것만 쓰고 여기 들어오지 않는다 (E2).

**기여 자원의 `data`는 해석하지 않는다** (C13 §5) — 그 모양은 확장이 정하고 Center는 그대로
넘긴다. 그래서 플랫폼 코드에 「UI 화면」이라는 말이 없다 (ADR-0018).
"""

from __future__ import annotations

import json
from typing import Any

from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import (
    RESOURCE_CATALOG_S,
    RESOURCE_MANIFEST_S,
    RESOURCE_STATUS_S,
    RESOURCE_TIMEOUT_S,
)
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.resources import (
    ContributedResource,
    ExtensionResource,
    InstalledOn,
    RuntimeHost,
    RuntimeResource,
    ServiceAppResource,
    ToolpackResource,
)
from chaeksas.contracts.service_app import ServiceAppManifest

#: 서비스 앱 상태 (C7). 열린 문자열이지만 Center가 짓는 것은 이 넷이다.
OK = "ok"
DEGRADED = "degraded"
UNREACHABLE = "unreachable"
UNKNOWN = "unknown"

#: `GET /resources?type=`로 물을 수 있는 종류.
KNOWN_TYPES = ("extension", "service_app", "contributed", "toolpack", "runtime")

#: 툴팩 패키지의 `kind` (C5).
TOOLPACK = "toolpack"


# ─────────────────────────── 서비스 앱 등록 ───────────────────────────


def _manifest_of(raw: str | None) -> ServiceAppManifest | None:
    found = loads(raw)
    if not found:
        return None
    try:
        return ServiceAppManifest.model_validate(found)
    except ValueError:
        # 저장할 때 검증했으므로 여기 오면 계약이 바뀐 것이다 — 목록을 멈추지는 않는다.
        return None


def read_public(base_url: str, *, timeout_s: float = RESOURCE_TIMEOUT_S) -> dict[str, Any]:
    """서비스 앱의 **공개 정보**를 읽는다 (C11 `/manifest`·`/healthz`, 인증 없음).

    돌려주는 것은 `{manifest?, status, reasons}`다. 닿지 못하면 `status=unreachable`이고
    **예외를 올리지 않는다** — 앱 하나가 꺼져 있다고 리소스 목록이 멈추면 안 된다.
    """
    import httpx  # noqa: PLC0415 — 부를 때만 든다

    out: dict[str, Any] = {"manifest": None, "status": UNREACHABLE, "reasons": []}
    root = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
            health = client.get(f"{root}/healthz")
            if health.status_code >= 400:
                out["reasons"] = [f"healthz_{health.status_code}"]
                return out
            body = health.json() if health.content else {}
            out["status"] = str(body.get("status") or UNKNOWN)
            out["reasons"] = [str(one) for one in (body.get("reasons") or [])]

            manifest = client.get(f"{root}/manifest")
            if manifest.status_code < 400 and manifest.content:
                out["manifest"] = manifest.json()
    except Exception as e:  # noqa: BLE001 — 주소가 틀렸거나 꺼져 있다
        out["status"] = UNREACHABLE
        out["reasons"] = [type(e).__name__]
    return out


def register(store: Store, found: Caller, raw: dict[str, Any]) -> tuple[ServiceAppResource, bool]:
    """`POST /resources/service-apps` — 주소를 받아 **바로 manifest를 읽어 본다** (C7).

    읽지 못하거나 C11과 맞지 않으면 등록하지 않는다 — 「등록은 됐는데 아무것도 모른다」를
    만들지 않는다 (422 `manifest_unreachable`·`manifest_invalid`).
    """
    base_url = str(raw.get("base_url") or "").strip()
    if not base_url:
        raise ApiError(422, "input_invalid", "`base_url`이 필요하다")

    probed = read_public(base_url)
    if probed["manifest"] is None:
        raise ApiError(
            422,
            "manifest_unreachable",
            f"manifest를 읽지 못했다 ({base_url})",
            {"reasons": probed["reasons"]},
        )
    try:
        manifest = ServiceAppManifest.model_validate(probed["manifest"])
    except ValueError as e:
        raise ApiError(
            422, "manifest_invalid", "manifest가 C11과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    app_id = manifest.app_id
    before = store.row("SELECT app_id FROM service_apps WHERE app_id = ?", (app_id,))
    now = now_iso()
    with store.tx() as cur:
        if before is None:
            cur.execute(
                "INSERT INTO service_apps (app_id, base_url, manifest_json, manifest_at, status,"
                " status_reasons, checked_at, registered_at, registered_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    app_id,
                    base_url,
                    dumps(probed["manifest"]),
                    now,
                    probed["status"],
                    dumps(probed["reasons"]),
                    now,
                    now,
                    found.actor,
                ),
            )
        else:
            # 같은 앱을 다시 등록하면 주소를 고친 것으로 본다 (PUT과 같은 결과).
            cur.execute(
                "UPDATE service_apps SET base_url = ?, manifest_json = ?, manifest_at = ?,"
                " status = ?, status_reasons = ?, checked_at = ? WHERE app_id = ?",
                (
                    base_url,
                    dumps(probed["manifest"]),
                    now,
                    probed["status"],
                    dumps(probed["reasons"]),
                    now,
                    app_id,
                ),
            )
    # manifest를 읽은 그 자리에서 **카탈로그도 읽는다** — 등록하자마자 기여 자원이 보여야
    # 「등록했는데 왜 경고가 그대로인가」가 생기지 않는다 (C7 누락 검사).
    refresh_catalogs(store, force=True)
    return service_app(store, app_id), before is None


def set_base_url(store: Store, app_id: str, raw: dict[str, Any]) -> ServiceAppResource:
    """`PUT /resources/service-apps/{id}` — **주소의 유일한 출처**를 고친다 (C7)."""
    _must_app(store, app_id)
    base_url = str(raw.get("base_url") or "").strip()
    if not base_url:
        raise ApiError(422, "input_invalid", "`base_url`이 필요하다")

    probed = read_public(base_url)
    if probed["manifest"] is not None:
        try:
            manifest = ServiceAppManifest.model_validate(probed["manifest"])
        except ValueError as e:
            raise ApiError(422, "manifest_invalid", "manifest가 C11과 맞지 않는다") from e
        if manifest.app_id != app_id:
            # 다른 앱을 가리키는 주소다 — 조용히 바꾸면 그 Bot들이 엉뚱한 앱을 부른다.
            raise ApiError(
                422,
                "manifest_invalid",
                f"그 주소의 앱은 {manifest.app_id}다 ({app_id}가 아니다)",
            )

    now = now_iso()
    with store.tx() as cur:
        cur.execute(
            "UPDATE service_apps SET base_url = ?, status = ?, status_reasons = ?, checked_at = ?"
            " WHERE app_id = ?",
            (base_url, probed["status"], dumps(probed["reasons"]), now, app_id),
        )
        if probed["manifest"] is not None:
            cur.execute(
                "UPDATE service_apps SET manifest_json = ?, manifest_at = ? WHERE app_id = ?",
                (dumps(probed["manifest"]), now, app_id),
            )
    refresh_catalogs(store, force=True)
    return service_app(store, app_id)


def unregister(store: Store, app_id: str) -> None:
    """`DELETE /resources/service-apps/{id}`. **쓰는 Bot이 있으면 409** (C7 `in_use`)."""
    _must_app(store, app_id)
    users = _used_by(store, app_id)
    if users:
        raise ApiError(
            409,
            "in_use",
            f"이 앱을 쓰는 Bot이 {len(users)}개 있다",
            {"used_by": users},
        )
    with store.tx() as cur:
        cur.execute("DELETE FROM service_apps WHERE app_id = ?", (app_id,))


def refresh(store: Store, raw: dict[str, Any]) -> list[ServiceAppResource]:
    """`POST /resources/refresh` — **간격을 무시하고 바로** 다시 읽는다 (C7)."""
    app_id = raw.get("id")
    rows = (
        store.rows("SELECT * FROM service_apps WHERE app_id = ?", (str(app_id),))
        if app_id
        else store.rows("SELECT * FROM service_apps ORDER BY app_id")
    )
    for row in rows:
        _probe_into(store, row, force=True)
    # 카탈로그도 함께 — 「새로 고침」은 **간격을 무시한다** (C7).
    refresh_catalogs(store, force=True)
    return [service_app(store, str(row["app_id"])) for row in rows]


def _probe_into(store: Store, row: Any, *, force: bool = False) -> None:
    """그 앱의 상태·manifest를 **때가 됐으면** 다시 읽는다 (C7 60초 / 10분).

    목록을 읽을 때마다 부르므로, 간격을 지키는 것이 요점이다 — 콘솔을 새로 고칠 때마다
    모든 앱을 두드리면 안 된다.
    """
    now = now_iso()
    if not force and not _due(row["checked_at"], now, RESOURCE_STATUS_S):
        return
    probed = read_public(str(row["base_url"]))
    wants_manifest = force or _due(row["manifest_at"], now, RESOURCE_MANIFEST_S)
    with store.tx() as cur:
        cur.execute(
            "UPDATE service_apps SET status = ?, status_reasons = ?, checked_at = ? WHERE app_id = ?",
            (probed["status"], dumps(probed["reasons"]), now, row["app_id"]),
        )
        if wants_manifest and probed["manifest"] is not None:
            cur.execute(
                "UPDATE service_apps SET manifest_json = ?, manifest_at = ? WHERE app_id = ?",
                (dumps(probed["manifest"]), now, row["app_id"]),
            )


def _due(at: str | None, now: str, seconds: int) -> bool:
    if not at:
        return True
    from datetime import datetime  # noqa: PLC0415

    return (datetime.fromisoformat(now) - datetime.fromisoformat(at)).total_seconds() >= seconds


def _must_app(store: Store, app_id: str) -> Any:
    row = store.row("SELECT * FROM service_apps WHERE app_id = ?", (app_id,))
    if row is None:
        raise ApiError(404, "not_found", f"서비스 앱 {app_id}가 없다")
    return row


# ─────────────────────────── 모아 주기 ───────────────────────────


def _approved_manifests(store: Store) -> list[dict[str, Any]]:
    """승인·배포 대상이 되는 패키지의 C1 매니페스트 (「이것을 쓰는 Bot」을 세는 바탕)."""
    rows = store.rows(
        "SELECT id, version, manifest_json FROM packages WHERE kind = 'bpm_process' ORDER BY id, version"
    )
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
    row = _must_app(store, app_id)
    return _service_app_of(store, row)


def _service_app_of(store: Store, row: Any) -> ServiceAppResource:
    manifest = _manifest_of(row["manifest_json"])
    return ServiceAppResource(
        app_id=str(row["app_id"]),
        name=manifest.name if manifest else None,
        version=manifest.version if manifest else None,
        category=manifest.category if manifest else None,
        extension_id=manifest.extension.id if manifest and manifest.extension else None,
        base_url=str(row["base_url"]),
        console_url=manifest.console_url if manifest else None,
        operations=list(manifest.operations) if manifest else [],
        status=str(row["status"]),
        status_reasons=loads(row["status_reasons"], []) or [],
        checked_at=row["checked_at"],
        manifest_at=row["manifest_at"],
        used_by=_used_by(store, str(row["app_id"])),
    )


def service_apps(store: Store, *, probe: bool = True) -> list[ServiceAppResource]:
    rows = store.rows("SELECT * FROM service_apps ORDER BY app_id")
    if probe:
        for row in rows:
            _probe_into(store, row)
        rows = store.rows("SELECT * FROM service_apps ORDER BY app_id")
    return [_service_app_of(store, row) for row in rows]


def toolpacks(store: Store) -> list[ToolpackResource]:
    """툴팩 (C5 `kind=toolpack` 패키지에서 — 따로 등록받지 않는다)."""
    rows = store.rows(
        "SELECT id, version, status, content_hash, manifest_json FROM packages WHERE kind = ?"
        " ORDER BY id, version",
        (TOOLPACK,),
    )
    out = []
    for row in rows:
        manifest = loads(row["manifest_json"], {}) or {}
        tools = manifest.get("provides", {}).get("tools") or manifest.get("tools") or []
        out.append(
            ToolpackResource(
                id=str(row["id"]),
                version=str(row["version"]),
                status=str(row["status"]),
                content_hash=str(row["content_hash"]),
                tools=[one for one in tools if isinstance(one, dict)],
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
    """확장 — 실행하는 쪽의 보고와 서비스 앱 manifest를 **합친** 것 (C7).

    외부 확장(서명된 정의 등록, C13)은 아직 없다 — 그때 `definition`·`envelope`가 붙는다.
    """
    found: dict[str, dict[str, Any]] = {}

    # 1) 실행하는 쪽이 보고한 것 — 몇 대에 깔렸는지는 여기서만 안다.
    for row in store.rows("SELECT runtimes_json, state_json FROM bot_uis"):
        reported = loads(row["runtimes_json"], {}) or {}
        state = loads(row["state_json"], {}) or {}
        # 하트비트가 더 새것이다 (C13 — 바뀔 때만 올라온다).
        installed = state.get("extensions") or reported.get("extensions") or []
        for one in installed:
            if not isinstance(one, dict) or not one.get("id"):
                continue
            key = str(one["id"])
            version = str(one.get("version") or "")
            slot = found.setdefault(key, {"versions": {}, "hosts": 0, "hash": None})
            slot["hosts"] += 1
            slot["versions"][version] = slot["versions"].get(version, 0) + 1
            slot["hash"] = slot["hash"] or one.get("definition_hash")

    # 2) 서비스 앱 manifest의 `extension` — 서버 부분이 있는 확장은 여기서 이름·버전이 온다.
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
        out.append(
            ExtensionResource(
                id=key,
                # 등록된 정의가 있으면 그것이 원본이다. 없으면 보고된 판 중 **가장 많이
                # 깔린 것**을 적는다 (분포는 `installed_on`에 있다).
                version=(
                    str(definition["version"])
                    if definition
                    else (max(versions, key=lambda v: versions[v]) if versions else (app.version or "" if app else ""))
                ),
                name=(definition.get("name") if definition else None) or (app.name if app else None),
                publisher=definition.get("publisher") if definition else None,
                # 등록된 것은 외부뿐이다 (E2) — 보고만 있는 것은 설치 파일에 든 내장이다.
                tier=str(definition["tier"]) if definition else "builtin",
                definition_hash=(
                    str(registered["definition_hash"]) if registered is not None else slot["hash"]
                ),
                protocol=_protocol_of(definition, app),
                contributes_summary=_contributes_of(definition),
                service_app_id=app.app_id if app else None,
                installed_on=InstalledOn(hosts=int(slot["hosts"]), by_version=dict(versions)),
                status=app.status if app else "n/a",
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


def _catalog_sources(store: Store, *, probe: bool) -> list[dict[str, Any]]:
    """읽을 카탈로그들 — **출처가 둘**이고 모양은 같다 (C7 §리소스 모으는 방식).

    | 출처 | 어디서 |
    | --- | --- |
    | 서비스 앱 manifest의 `resources` (C11) | 내장·사내 확장. **정의가 Center에 없어서** 서버 부분이 알린다 |
    | 등록된 외부 정의의 `contributes.resources` (C13) | 외부 확장. 정의가 Center에 있다 |

    주소는 **Center의 리소스 등록(`base_url`)이 이긴다** — 환경별 주소의 유일한 출처다
    (C13 `service.base_url`). 등록이 없으면 정의의 `base_url`을 쓴다.
    """
    out: list[dict[str, Any]] = []
    apps = {one.app_id: one for one in service_apps(store, probe=probe)}

    for row in store.rows("SELECT app_id, base_url, manifest_json FROM service_apps ORDER BY app_id"):
        found = _manifest_of(row["manifest_json"])
        if found is None:
            continue
        for one in found.resources:
            out.append(
                {
                    "source": f"app:{row['app_id']}:{one.type}",
                    "resource_type": one.type,
                    "label": one.label or one.type,
                    "extension_id": found.extension.id if found.extension else None,
                    "url": f"{str(row['base_url']).rstrip('/')}{one.catalog_url}",
                }
            )

    for row in store.rows(
        "SELECT id, definition_json FROM extensions WHERE revoked_json IS NULL ORDER BY id"
    ):
        definition = json.loads(row["definition_json"])
        service = definition.get("service") or {}
        declared = (definition.get("contributes") or {}).get("resources") or []
        for one in declared:
            if not isinstance(one, dict) or not one.get("catalog_url"):
                continue
            # 등록된 서비스 앱이 있으면 그 주소가 이긴다 (출처는 하나다).
            app = apps.get(str(service.get("app_id") or ""))
            base = (app.base_url if app else None) or str(service.get("base_url") or "")
            if not base:
                continue
            out.append(
                {
                    "source": f"ext:{row['id']}:{one.get('type')}",
                    "resource_type": str(one.get("type") or ""),
                    "label": str(one.get("label") or one.get("type") or ""),
                    "extension_id": str(row["id"]),
                    "url": f"{base.rstrip('/')}{one['catalog_url']}",
                }
            )
    return out


def read_catalog(url: str, *, timeout_s: float = RESOURCE_TIMEOUT_S) -> dict[str, Any]:
    """카탈로그 하나를 읽는다 (C13 §5). 닿지 못하면 `error`를 담아 돌려준다 — 올리지 않는다."""
    import httpx  # noqa: PLC0415

    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
            answer = client.get(url)
        if answer.status_code >= 400:
            return {"error": f"http_{answer.status_code}"}
        return {"body": answer.json() if answer.content else {}}
    except Exception as e:  # noqa: BLE001 — 앱이 꺼져 있을 수 있다
        return {"error": type(e).__name__}


def refresh_catalogs(store: Store, *, force: bool = False, probe: bool = False) -> int:
    """카탈로그들을 **때가 됐으면** 다시 읽는다 (C7 — 5분). 돌려주는 것은 갱신한 수다.

    **`revision`이 같으면 항목을 다시 쓰지 않는다** (C7) — 같은 것을 다시 쓰면 Studio·Worker의
    계획 캐시가 공연히 버려진다. 닿지 못한 것은 **들고 있던 항목을 지우지 않고** 사유만 남긴다.
    """
    from chaeksas.contracts.extension import Catalog  # noqa: PLC0415

    now = now_iso()
    changed = 0
    for source in _catalog_sources(store, probe=probe):
        before = store.row("SELECT * FROM catalog_reads WHERE source = ?", (source["source"],))
        if not force and before is not None and not _due(before["read_at"], now, RESOURCE_CATALOG_S):
            continue

        got = read_catalog(source["url"])
        if "error" in got:
            _note_read(store, source, revision=before["revision"] if before else None, at=now, error=got["error"])
            continue
        try:
            catalog = Catalog.model_validate(got["body"])
        except ValueError as e:
            _note_read(store, source, revision=None, at=now, error=f"invalid:{type(e).__name__}")
            continue

        same = before is not None and before["revision"] is not None and before["revision"] == catalog.revision
        _note_read(store, source, revision=catalog.revision, at=now, error=None)
        if same:
            continue  # 판이 그대로다 — 항목을 다시 쓰지 않는다
        _store_items(store, source, catalog, at=now)
        changed += 1
    return changed


def _note_read(store: Store, source: dict[str, Any], *, revision: Any, at: str, error: str | None) -> None:
    with store.tx() as cur:
        cur.execute("DELETE FROM catalog_reads WHERE source = ?", (source["source"],))
        cur.execute(
            "INSERT INTO catalog_reads (source, resource_type, extension_id, revision, read_at, error)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (source["source"], source["resource_type"], source["extension_id"], revision, at, error),
        )


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
    """확장이 기여한 자원 (C7). **Center는 `data`를 해석하지 않는다** (C13 §5).

    읽는 쪽이 부를 때 **때가 됐으면** 다시 읽는다 (5분) — 콘솔을 새로 고칠 때마다 모든
    카탈로그를 두드리지 않는다.
    """
    refresh_catalogs(store, probe=probe)
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
    """지금 알고 있는 기여 자원 종류들 (CON-07 탭 하나씩). 읽기 실패도 함께 보인다.

    **때가 됐으면 먼저 읽는다** — 아직 한 번도 읽지 않은 종류를 「항목 0개」로 보이면
    「없다」로 읽힌다.
    """
    refresh_catalogs(store)
    out: dict[str, dict[str, Any]] = {}
    for source in _catalog_sources(store, probe=False):
        slot = out.setdefault(
            source["resource_type"],
            {"resource_type": source["resource_type"], "label": source["label"], "extensions": [], "errors": []},
        )
        if source["extension_id"] and source["extension_id"] not in slot["extensions"]:
            slot["extensions"].append(source["extension_id"])
        read = store.row("SELECT error FROM catalog_reads WHERE source = ?", (source["source"],))
        if read is not None and read["error"]:
            slot["errors"].append(f"{source['source']}: {read['error']}")
    for one in out.values():
        one["count"] = len(
            store.rows(
                "SELECT id FROM contributed_resources WHERE resource_type = ?", (one["resource_type"],)
            )
        )
    return sorted(out.values(), key=lambda one: str(one["resource_type"]))


# ─────────────────────────── 외부 확장 등록 (C13·C2) ───────────────────────────


def _envelope_of(raw: Any) -> Any:
    from chaeksas.contracts.signing import Envelope  # noqa: PLC0415

    try:
        return Envelope.model_validate(raw)
    except ValueError as e:
        raise ApiError(400, "bad_envelope", f"봉투가 계약과 맞지 않는다: {e}") from e


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
                {"rule": p.rule, "code": p.code, "message": p.message, "items": list(p.items or [])}
                for p in problems
            ]
        },
    )


def register_extension(store: Store, found: Caller, raw: dict[str, Any]) -> tuple[ExtensionResource, bool]:
    """`POST /resources/extensions` — 정의와 **서명 봉투**를 함께 받는다 (C13 E6).

    **서명이 관문이다** (C2). 관리자 토큰만으로는 등록되지 않는다 — 정의가 Bot의 키를 어느
    주소로 보낼지 정하므로 배포와 같은 관문을 둔다.
    """
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
    envelope = _envelope_of(raw.get("envelope"))

    _refuse(check_size(json.dumps(definition, ensure_ascii=False).encode("utf-8")), status=413)
    try:
        manifest = ExtensionManifest.model_validate(definition)
    except ValueError as e:
        raise ApiError(
            422, "input_invalid", "확장 정의가 C13과 맞지 않는다", {"error": str(e).splitlines()[0]}
        ) from e

    # E1·E2·E3 — 외부 확장에 코드 기여가 없고, 등급이 external이고, 어댑터 선언이 안전한가.
    _refuse(validate(manifest, from_center=True))
    # E6 — 봉투가 **이 정의**에 대한 것인가 (해시·id·버전).
    _refuse(verify_external(definition, envelope, keys=admin_keys(store)), status=400)

    # E4·E8 — 이미 등록된 **다른** 확장들과 겹치지 않는가.
    others = [one for one in _registered_manifests(store) if one.id != manifest.id]
    _refuse(task_type_conflicts([*others, manifest]), status=409)
    _refuse(environment_conflicts([*others, manifest]), status=409)

    computed = definition_hash(definition)
    body = json.dumps(definition, ensure_ascii=False, sort_keys=True)
    envelope_body = json.dumps(envelope.to_json_dict(), ensure_ascii=False)

    before = store.row(
        "SELECT * FROM extensions WHERE id = ? AND version = ?", (manifest.id, manifest.version)
    )
    if before is not None:
        if before["revoked_json"]:
            # **철회된 판은 되살아나지 않는다** (배포·패키지와 같은 규칙, C2).
            raise ApiError(409, "extension_revoked", f"{manifest.id}@{manifest.version}은 철회됐다")
        if before["definition_hash"] != computed:
            raise ApiError(409, "id_conflict", f"{manifest.id}@{manifest.version}에 다른 정의가 왔다")
        return extension(store, manifest.id), False

    with store.tx() as cur:
        cur.execute(
            "INSERT INTO extensions (id, version, definition_json, envelope_json, definition_hash,"
            " revoked_json, at, registered_by) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
            (manifest.id, manifest.version, body, envelope_body, computed, now_iso(), found.actor),
        )
    return extension(store, manifest.id), True


def revoke_extension(store: Store, raw: dict[str, Any]) -> ExtensionResource:
    """`DELETE /resources/extensions` — `extension_revoke` 봉투 (C13·C2). **되살릴 수 없다.**

    **쓰는 Bot이 있어도 막지 않는다** — 정의에 문제가 있어 거두는 일이라, 쓰는 쪽이 있다고
    남겨 두면 그게 더 위험하다. 몇 개가 실행 불가가 되는지는 화면이 미리 말한다 (CON-07).
    """
    from chaeksas.center.api.signing import admin_keys  # noqa: PLC0415
    from chaeksas.contracts.signing import verify  # noqa: PLC0415

    envelope = _envelope_of(raw.get("envelope") if "envelope" in raw else raw)
    _refuse(verify(envelope, keys=admin_keys(store), expect_kind="extension_revoke"), status=403)

    claim = envelope.payload
    found = store.row(
        "SELECT * FROM extensions WHERE id = ? AND version = ?",
        (claim.get("id"), claim.get("version")),
    )
    if found is None:
        raise ApiError(404, "not_found", f"등록된 확장이 없다: {claim.get('id')}@{claim.get('version')}")
    if not found["revoked_json"]:
        with store.tx() as cur:
            cur.execute(
                "UPDATE extensions SET revoked_json = ? WHERE id = ? AND version = ?",
                (
                    json.dumps(envelope.to_json_dict(), ensure_ascii=False),
                    claim.get("id"),
                    claim.get("version"),
                ),
            )
    # **철회된 것은 목록에서 빠지므로** `extension()`으로는 찾을 수 없다 — 저장된 줄에서 짓는다.
    return _revoked_info(store, str(claim.get("id")), str(claim.get("version")))


def _revoked_info(store: Store, extension_id: str, version: str) -> ExtensionResource:
    """철회된 확장 하나 (철회 응답에만 쓴다 — 목록에는 뜨지 않는다)."""
    row = store.row(
        "SELECT * FROM extensions WHERE id = ? AND version = ?", (extension_id, version)
    )
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
    for row in store.rows(
        "SELECT definition_json FROM extensions WHERE revoked_json IS NULL ORDER BY id, version"
    ):
        try:
            out.append(ExtensionManifest.model_validate(json.loads(row["definition_json"])))
        except ValueError:  # pragma: no cover — 등록할 때 검증했다
            continue
    return out


def _external_rows(store: Store) -> dict[str, Any]:
    """id → 가장 최근에 등록된(철회되지 않은) 외부 확장 줄."""
    out: dict[str, Any] = {}
    for row in store.rows(
        "SELECT * FROM extensions WHERE revoked_json IS NULL ORDER BY id, at"
    ):
        out[str(row["id"])] = row  # 같은 id는 나중 것이 이긴다
    return out


def index(store: Store, *, probe: bool = False) -> Any:
    """누락 검사에 넘길 리소스 묶음 (C7 `ResourceIndex`).

    **기본은 두드리지 않는다** — 패키지 목록을 읽을 때마다 서비스 앱을 깨우지 않는다.
    """
    from chaeksas.contracts.resources import ResourceIndex  # noqa: PLC0415

    return ResourceIndex(
        extensions=extensions(store, probe=probe),
        service_apps=service_apps(store, probe=probe),
        # 누락 검사는 **카탈로그를 두드리지 않는다** — 들고 있는 것으로 센다.
        contributed=contributed(store, probe=probe) if probe else _cached_contributed(store),
        toolpacks=toolpacks(store),
    )


def listing(
    store: Store, *, type: str | None = None, resource_type: str | None = None
) -> dict[str, Any]:
    """`GET /resources?type=[&resource_type=]` (C7 §목록 응답 공통 — `{items, fetched_at}`)."""
    if type is not None and type not in KNOWN_TYPES:
        raise ApiError(422, "input_invalid", f"모르는 리소스 종류다: {type}")
    picked = (type,) if type else KNOWN_TYPES
    items: list[Any] = []
    for one in picked:
        if one == "service_app":
            items += service_apps(store)
        elif one == "toolpack":
            items += toolpacks(store)
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
        (
            one
            for one in contributed(store, resource_type=resource_type)
            if one.id == resource_id
        ),
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
    "read_public",
    "refresh",
    "register",
    "register_extension",
    "revoke_extension",
    "runtimes",
    "service_app",
    "service_apps",
    "set_base_url",
    "toolpacks",
    "unregister",
]

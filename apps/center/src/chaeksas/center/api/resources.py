"""리소스 목록 — Bot이 실행에 필요로 하는 바깥 자원 (C7, CON-07).

네 종류를 모은다. **셋은 Center가 이미 가진 것에서 계산한다** — 따로 등록받지 않는다.

| 종류 | 어디서 |
| --- | --- |
| 서비스 앱 | 운영자가 등록한 주소 + Center가 읽은 C11 `/manifest`·`/healthz` |
| 툴팩 | `packages` 표의 `kind=toolpack` (C5) |
| 런타임 | `bot_uis`가 등록·하트비트로 보고한 것 (C4) |
| 확장 | 실행하는 쪽의 보고 + 서비스 앱 manifest의 `extension` |

**Center는 서비스 앱 키를 갖지 않는다** (ADR-0013) — 읽는 것은 인증이 필요 없는 공개
정보뿐이다 (`/healthz`·`/manifest`).

> 확장이 기여한 자원(「UI 화면」)은 아직이다 — `catalog_url`을 읽는 일이 C13 외부 확장
> 등록(서명 봉투)에 딸려 있어서 그것과 함께 한다. 그때까지 `contributed`는 빈 목록이고,
> 누락 검사도 그 종류를 **거부 사유로 쓰지 않는다** (C7 §누락 검사 — 배포를 막는 것은
> 확장 누락·해시 불일치와 R8뿐이다).
"""

from __future__ import annotations

from typing import Any

from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import (
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

    out = []
    for key in sorted(set(found) | set(apps)):
        slot = found.get(key, {"versions": {}, "hosts": 0, "hash": None})
        app = apps.get(key)
        versions = slot["versions"]
        out.append(
            ExtensionResource(
                id=key,
                # 보고된 판이 여럿이면 가장 많이 깔린 것을 적는다 (분포는 `installed_on`에 있다).
                version=max(versions, key=lambda v: versions[v]) if versions else (app.version or "" if app else ""),
                name=app.name if app else None,
                tier="builtin",  # 외부 확장 등록(C13)이 붙으면 거기서 온다
                definition_hash=slot["hash"],
                protocol="chk-c11" if app else None,
                service_app_id=app.app_id if app else None,
                installed_on=InstalledOn(hosts=int(slot["hosts"]), by_version=dict(versions)),
                status=app.status if app else "n/a",
            )
        )
    return out


def contributed(store: Store) -> list[ContributedResource]:
    """확장이 기여한 자원 — **아직 모으지 않는다** (C13 외부 확장 등록과 함께 온다).

    빈 목록을 주는 것이 「없다」는 뜻은 아니다. 그래서 누락 검사에서 이 종류를 거부
    사유로 쓰지 않는다 (C7 §누락 검사).
    """
    return []


def index(store: Store, *, probe: bool = False) -> Any:
    """누락 검사에 넘길 리소스 묶음 (C7 `ResourceIndex`).

    **기본은 두드리지 않는다** — 패키지 목록을 읽을 때마다 서비스 앱을 깨우지 않는다.
    """
    from chaeksas.contracts.resources import ResourceIndex  # noqa: PLC0415

    return ResourceIndex(
        extensions=extensions(store, probe=probe),
        service_apps=service_apps(store, probe=probe),
        contributed=contributed(store),
        toolpacks=toolpacks(store),
    )


def listing(store: Store, *, type: str | None = None) -> dict[str, Any]:
    """`GET /resources?type=` (C7 §목록 응답 공통 — `{items, fetched_at}`)."""
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
            items += contributed(store)
    return {"items": [one.to_json_dict() for one in items], "fetched_at": now_iso()}


def extension(store: Store, extension_id: str) -> ExtensionResource:
    found = next((one for one in extensions(store) if one.id == extension_id), None)
    if found is None:
        raise ApiError(404, "not_found", f"확장 {extension_id}가 없다")
    # 「이 확장을 쓰는 Bot」은 상세에서만 센다 (목록마다 매니페스트를 다 읽지 않게).
    extra = dict(found.to_json_dict())
    extra["used_by"] = _extension_used_by(store, extension_id)
    return ExtensionResource.model_validate(extra)


__all__ = [
    "DEGRADED",
    "KNOWN_TYPES",
    "OK",
    "UNKNOWN",
    "UNREACHABLE",
    "contributed",
    "extension",
    "extensions",
    "index",
    "listing",
    "read_public",
    "refresh",
    "register",
    "runtimes",
    "service_app",
    "service_apps",
    "set_base_url",
    "toolpacks",
    "unregister",
]

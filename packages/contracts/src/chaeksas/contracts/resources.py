"""C7. Center API: 리소스 목록 (+ 누락 검사).

단일 원본: `docs/03-contracts/C7-resources-center-keys.md`. Center API 키 관리는 `center_keys`에.

**플랫폼 계약은 특정 확장을 모른다** (ADR-0018). 확장이 기여한 자원은 C13 §5의 공통 카탈로그
형식으로만 다루고, `data`의 모양은 확장이 정한다 — Center는 해석하지 않고 그대로 넘긴다.

**Center는 서비스 앱 키를 갖지 않는다** (ADR-0013). 서비스 앱에서 읽는 것은 인증이 필요 없는
공개 정보(`/healthz`, `/manifest`, 어댑터 `health`, 공개 카탈로그)뿐이다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import Field, ValidationError

from chaeksas.contracts._base import ContractModel, Timestamp
from chaeksas.contracts._semver import InvalidVersion, satisfies
from chaeksas.contracts.extension import AdapterOperation
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.service_app import Operation

#: 리소스를 다시 읽는 주기 (`CHK_CENTER__RESOURCE__POLL_S`). 「새로 고침」은 즉시.
STATUS_POLL_S = 60
MANIFEST_POLL_S = 600
CATALOG_POLL_S = 300

# 열린 문자열의 알려진 값 (README 원칙 10).
KNOWN_RESOURCE_TYPES = frozenset({"extension", "service_app", "contributed", "runtime"})
KNOWN_SERVICE_APP_STATUSES = frozenset({"ok", "degraded", "unreachable", "unknown"})
KNOWN_EXTENSION_TIERS = frozenset({"builtin", "internal", "external"})  # C13
KNOWN_PROTOCOLS = frozenset({"chk-c11", "http-adapter"})  # 없으면 클라이언트 기여만
# 수행 모드 값은 C11이 소유한다 (`service_app.MODES`).

#: 누락 검사 결과의 `type`·`reason` (C7 「누락 검사」 표).
KNOWN_MISSING_TYPES = frozenset({"extension", "service_app", "operation", "resource"})
KNOWN_MISSING_REASONS = frozenset(
    {"not_found", "not_registered", "version_mismatch", "hash_mismatch",
     "not_deterministic", "not_server_ok", "not_approved"}
)


class MissingResource(ContractModel):
    """패키지가 쓰는데 Center 리소스 목록에 없는(또는 맞지 않는) 것 하나.

    C5 `PackageInfo.missing_resources`에 실린다.
    """

    type: str  # KNOWN_MISSING_TYPES
    id: str
    reason: str  # KNOWN_MISSING_REASONS


class InstalledOn(ContractModel):
    """이 확장을 가진 실행하는 쪽의 수와 버전 분포 (C4·C12 보고. Studio는 세지 않는다)."""

    hosts: int = 0
    by_version: dict[str, int] = Field(default_factory=dict)


class ExtensionResource(ContractModel):
    """확장 하나 (C13 정의에서 모은 것)."""

    id: str
    version: str
    name: str | None = None
    publisher: str | None = None
    tier: str  # KNOWN_EXTENSION_TIERS
    definition_hash: str | None = None
    protocol: str | None = None  # KNOWN_PROTOCOLS, 없으면 클라이언트 기여만
    contributes_summary: dict[str, list[str]] = Field(default_factory=dict)
    service_app_id: str | None = None
    installed_on: InstalledOn = Field(default_factory=InstalledOn)
    # 서버 부분 상태 — 그 토픽을 가져가는 **일꾼**이 말한다 (C7, ADR-0102). 서버 부분이 아예
    # 없으면 `n/a`다.
    status: str = "n/a"  # KNOWN_SERVICE_APP_STATUSES + n/a
    status_reasons: list[str] = Field(default_factory=list)
    checked_at: Timestamp | None = None
    # 외부 확장만 — 실행하는 쪽이 받아 검증한다 (C2 `extension` 봉투).
    definition: dict[str, Any] | None = None
    envelope: dict[str, Any] | None = None


class ServiceAppResource(ContractModel):
    """서비스 앱 하나 (확장의 서버 부분)."""

    app_id: str
    name: str | None = None
    version: str | None = None
    category: str | None = None
    extension_id: str | None = None
    #: **비어 있다** — Center는 서비스 앱의 주소를 모른다 (ADR-0102). 옛 읽는 쪽을 위해 칸만 둔다.
    base_url: str | None = None
    console_url: str | None = None
    operations: list[Operation] = Field(default_factory=list)
    status: str = "unknown"  # KNOWN_SERVICE_APP_STATUSES
    status_reasons: list[str] = Field(default_factory=list)
    checked_at: Timestamp | None = None
    manifest_at: Timestamp | None = None
    used_by: list[str] = Field(default_factory=list)  # `id@version`
    #: 이 토픽을 가져가는 일꾼 수 (C15).
    consumers: int = 0

    def operation(self, name: str) -> Operation | None:
        return next((o for o in self.operations if o.name == name), None)


class ContributedResource(ContractModel):
    """확장이 기여한 자원 하나 (C13 §5 공통 카탈로그 항목)."""

    resource_type: str  # 예: ui_page
    id: str
    name: str | None = None
    summary: str | None = None
    updated_at: Timestamp | None = None
    extension_id: str | None = None
    revision: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)  # Center는 해석하지 않는다
    used_by: list[str] = Field(default_factory=list)


class RuntimeHost(ContractModel):
    type: str  # bot_ui | server_runner
    id: str
    name: str | None = None


class RuntimeResource(ContractModel):
    """실행하는 쪽이 보고한 런타임 (C4 등록·하트비트, C12)."""

    host: RuntimeHost
    os: str | None = None
    versions: dict[str, str] = Field(default_factory=dict)  # {bot_ui?, core}
    browsers: list[str] = Field(default_factory=list)
    desktop_backend: str | None = None
    extensions: list[dict[str, Any]] = Field(default_factory=list)


class ResourceList[T](ContractModel):
    """목록 응답 공통 (`{items, fetched_at}`).

    Studio는 마지막으로 받은 목록을 캐시하고, 오프라인이면 「(오프라인 — 마지막 확인
    `fetched_at`)」을 붙여 보인다 (U8).
    """

    items: list[T] = Field(default_factory=list)
    fetched_at: Timestamp


class ResourceIndex(ContractModel):
    """누락 검사에 쓰는 리소스 묶음 (Center가 자기 목록에서 만들어 넘긴다)."""

    extensions: list[ExtensionResource] = Field(default_factory=list)
    service_apps: list[ServiceAppResource] = Field(default_factory=list)
    contributed: list[ContributedResource] = Field(default_factory=list)

    def extension(self, id: str) -> ExtensionResource | None:
        return next((e for e in self.extensions if e.id == id), None)

    def service_app(self, app_id: str) -> ServiceAppResource | None:
        return next((s for s in self.service_apps if s.app_id == app_id), None)

    def contributed_resource(self, type: str, id: str) -> ContributedResource | None:
        return next((c for c in self.contributed if c.resource_type == type and c.id == id), None)

# ─────────────────────────── 누락 검사 ───────────────────────────


def _check_extensions(m: Manifest, index: ResourceIndex) -> list[MissingResource]:
    out = []
    for need in m.requires.extensions:
        have = index.extension(need.id)
        if have is None:
            out.append(MissingResource(type="extension", id=need.id, reason="not_found"))
            continue
        try:
            ok = satisfies(have.version, need.version)
        except InvalidVersion:
            ok = False
        if not ok:
            out.append(MissingResource(type="extension", id=f"{need.id}@{need.version}", reason="version_mismatch"))
        # 외부 확장은 정의를 해시로 고정한다 (C13).
        if need.definition_hash and have.definition_hash != need.definition_hash:
            out.append(MissingResource(type="extension", id=need.id, reason="hash_mismatch"))
    return out


def _adapter_operations(ext: ExtensionResource | None) -> dict[str, AdapterOperation] | None:
    """외부 확장의 어댑터 작업들 (이름 → 작업). 외부 확장이 아니거나 어댑터가 없으면 `None`."""
    if ext is None or ext.tier != "external" or not ext.definition:
        return None
    adapter = (ext.definition.get("service") or {}).get("adapter")
    if not isinstance(adapter, dict):
        return None
    found: dict[str, AdapterOperation] = {}
    for raw in adapter.get("operations") or []:
        try:
            op = AdapterOperation.model_validate(raw)
        except ValidationError:
            continue  # 등록 때 E3가 이미 걸렀다 — 여기서 하나 때문에 목록을 깨지 않는다
        found[op.name] = op
    return found


def _check_service_apps(m: Manifest, index: ResourceIndex) -> list[MissingResource]:
    out = []
    server = m.run_location == "server"
    for need in m.requires.service_apps:
        app = index.service_app(need.app_id)
        # `chk:serviceCall`은 서비스 앱과 외부 확장을 가리지 않는다 (C13 §4) — 같은 id의 외부
        # 확장이 있으면 그 어댑터 작업으로 본다. 없다고 하면 등록된 앱에 「등록되지 않음」이 뜬다.
        find_op: Callable[[str], Any]
        if app is not None:
            find_op = app.operation
        else:
            adapter = _adapter_operations(index.extension(need.app_id))
            if adapter is None:
                out.append(MissingResource(type="service_app", id=need.app_id, reason="not_registered"))
                continue
            find_op = adapter.get
        for name in need.operations:
            op_id = f"{need.app_id}.{name}"
            op = find_op(name)
            if op is None:
                out.append(MissingResource(type="operation", id=op_id, reason="not_found"))
                continue
            # 실행하는 쪽(PC 실행기·서버 실행기)은 결정 수행으로 부른다.
            if "deterministic" not in op.modes:
                out.append(MissingResource(type="operation", id=op_id, reason="not_deterministic"))
            if server and not op.server_ok:
                out.append(MissingResource(type="operation", id=op_id, reason="not_server_ok"))
    return out


def _check_contributed(m: Manifest, index: ResourceIndex) -> list[MissingResource]:
    return [
        MissingResource(type="resource", id=f"{ref.type}:{ref.id}", reason="not_found")
        for ref in m.requires.resources
        if index.contributed_resource(ref.type, ref.id) is None
    ]


def missing(manifest: Manifest, resources: ResourceIndex) -> list[MissingResource]:
    """C1 `requires`를 리소스 목록과 대조한다. **확장 종류를 가리지 않는 같은 규칙이다.**

    업로드할 때는 결과를 **경고로만** 보이고(CON-02 띠), 배포할 때는
    `blocking_at_deploy()`가 고른 것만 거부한다.
    """
    return [
        *_check_extensions(manifest, resources),
        *_check_service_apps(manifest, resources),
        *_check_contributed(manifest, resources),
    ]


def blocking_at_deploy(items: list[MissingResource]) -> list[MissingResource]:
    """배포를 막는 누락만 고른다.

    C1 R8에 걸리는 것(서버 BPM 프로세스의 작업 — `not_server_ok`·`not_deterministic`),
    확장 누락, 그리고 해시 불일치뿐이다.
    **서비스 앱이 잠시 응답이 없다고 배포를 막지는 않는다.**
    """
    return [
        i
        for i in items
        if i.type == "extension"
        or i.reason == "hash_mismatch"
        or (i.type == "operation" and i.reason in ("not_server_ok", "not_deterministic"))
    ]

"""C13. 확장 정의 (`extension.json`) — 확장 하나가 무엇을 더하는지.

단일 원본: `docs/03-contracts/C13-extension-manifest.md`. 구현하는 인터페이스는
`packages/extension_api/`, 찾아 켜는 쪽은 `chaeksas.core.extensions` (확장 호스트).

**플랫폼은 이 파일만 보고 기여를 끼워 넣는다.** 특정 확장 이름을 플랫폼 코드에 쓰지 않는다
(ADR-0018). 그래서 검사 규칙 E1~E7이 여기 있고, Studio(정의 파일 열기)·Center(등록)·확장
호스트(켜기)가 **같은 함수**를 쓴다.

`contributes`의 열쇠는 문서 그대로 점이 든 이름(`studio.editors`)이다. 파이썬 이름만
`studio_editors`로 두고 별명으로 잇는다 (`_base`의 `schema` ↔ `schema_version`과 같은 방식).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Any, ClassVar
from urllib.parse import urlsplit

from pydantic import Field, ValidationError

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp, Violation
from chaeksas.contracts._semver import InvalidVersion, satisfies
from chaeksas.contracts.hashing import canonical_json, sha256_hex
from chaeksas.contracts.manifest import SemVer
from chaeksas.contracts.service_app import MODE_AUTONOMOUS, MODES, OPERATION_PATTERN
from chaeksas.contracts.signing import AdminKey, Envelope, ExtensionClaim, verify

#: 확장 패키지 안에 두는 정의 파일 이름, 그리고 확장 호스트가 읽는 엔트리 포인트 그룹.
EXTENSION_FILE = "extension.json"
ENTRY_POINT_GROUP = "chaeksas.extensions"

#: 정의 크기 한도 (C13 「전송」).
MAX_DEFINITION_KB = 256
MAX_DEFINITION_BYTES = MAX_DEFINITION_KB * 1024

#: 등급 (ADR-0018 §3). `builtin`·`internal`은 설치 파일에 든 코드, `external`은 선언뿐이다.
TIER_BUILTIN = "builtin"
TIER_INTERNAL = "internal"
TIER_EXTERNAL = "external"
TIERS = frozenset({TIER_BUILTIN, TIER_INTERNAL, TIER_EXTERNAL})
#: 코드를 기여할 수 있는 등급 — 우리가 빌드·서명한 설치 파일에 든 것뿐이다.
CODE_TIERS = frozenset({TIER_BUILTIN, TIER_INTERNAL})

#: 서버 부분의 종류.
PROTOCOL_C11 = "chk-c11"
PROTOCOL_HTTP_ADAPTER = "http-adapter"
KNOWN_PROTOCOLS = frozenset({PROTOCOL_C11, PROTOCOL_HTTP_ADAPTER})

#: `editor.kind` — 확장이 준 편집기, 또는 입력 JSON Schema로 만드는 자동 폼.
EDITOR_BUILTIN = "builtin"
EDITOR_SCHEMA = "schema"

#: 호스트가 소유하는 설정 키의 머리 (C13 — `runtime.<런타임 id>.port` 등). 확장이 쓰지 못한다.
RESERVED_CONFIG_PREFIX = "runtime."

#: `configuration[].scope`, `local_runtimes[].start`, `requires_keys[].purpose`.
CONFIG_SCOPES = frozenset({"bot_ui", "studio", "server_runner"})
START_ON_DEMAND = "on_demand"
START_ALWAYS = "always"
KNOWN_STARTS = frozenset({START_ON_DEMAND, START_ALWAYS})
PURPOSE_RUN = "run"
PURPOSE_UTILITY = "utility"
KNOWN_PURPOSES = frozenset({PURPOSE_RUN, PURPOSE_UTILITY})

#: 실행 위치 (C1과 같은 값).
KNOWN_RUN_LOCATIONS = frozenset({"pc", "server"})

#: HTTP 어댑터 (§4).
ADAPTER_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
#: 템플릿으로 쓸 수 없는 헤더 — 키·주소를 바꿔치기할 수 있다 (§4-2).
FORBIDDEN_HEADERS = frozenset({"authorization", "host", "cookie"})
#: 템플릿에서 쓸 수 있는 변수. 그 밖에는 정의 검사에서 거부한다. **키는 쓸 수 없다.**
TEMPLATE_VARS = frozenset({"run_id", "node_id", "idempotency_key"})
AUTH_BEARER = "bearer"
AUTH_HEADER = "header"
KNOWN_AUTH_TYPES = frozenset({AUTH_BEARER, AUTH_HEADER})
DEFAULT_TIMEOUT_S = 60
DEFAULT_MAX_RESPONSE_KB = 1024

ExtensionId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,49}$")]
OperationName = Annotated[str, Field(pattern=OPERATION_PATTERN)]

_TEMPLATE = re.compile(r"\{\{(.*?)\}\}", re.S)
_INPUT_VAR = re.compile(r"^input\.[A-Za-z_][A-Za-z0-9_]*$")
#: 제한된 JSONPath — `$`, `.이름`, `[숫자]`만 (§4-2). 필터·식·와일드카드는 없다.
_JSONPATH = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\d+\])*$")
#: 호스트 이름 — 와일드카드·포트·스킴 없이 이름만.
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


# ─────────────────────────── 기여 (contributes) ───────────────────────────


class Editor(ContractModel):
    """태스크 편집기. `kind="schema"`면 입력 JSON Schema로 자동 폼을 만든다 (STU-14 방식)."""

    kind: str  # EDITOR_BUILTIN | EDITOR_SCHEMA
    entry: str | None = None  # kind=builtin일 때만


class Executor(ContractModel):
    """`extension_api.TaskExecutor`를 구현한 객체를 가리킨다."""

    entry: str


class TaskTypeContribution(ContractModel):
    """Studio 팔레트·속성 편집기에 더하는 태스크 종류 하나 (실행기가 수행한다)."""

    id: str
    label: str
    icon: str | None = None
    bpmn: str = "serviceTask"
    editor: Editor | None = None
    executor: Executor | None = None
    #: 이 태스크 종류를 쓸 수 있는 실행 위치 (C1 R2 판정에 쓰인다). `ui_task`는 `["pc"]`.
    run_locations: list[str] = Field(default_factory=list)


class StudioEditorContribution(ContractModel):
    """Studio 속성 패널의 태스크 편집기 (태스크 종류와 따로 더할 때)."""

    task_type: str
    entry: str


class ResourceView(ContractModel):
    """Studio 리소스 탐색기(STU-03)의 한 갈래. **선언뿐이라 외부 확장도 쓸 수 있다.**"""

    id: str
    label: str
    resource_type: str
    creates_task_type: str | None = None


class Utility(ContractModel):
    """Bot UI 「도구」 메뉴·탭에 더하는 유틸리티 하나 (BUI-06~08)."""

    id: str
    label: str
    menu: str = "tools"
    entry: str
    needs_runtime: str | None = None  # 열어 둘 때 띄워야 하는 로컬 런타임 id


class LocalRuntime(ContractModel):
    """Bot UI가 띄우고 감시하는 로컬 프로세스 (BUI-09·11).

    **명령줄은 확장이 적지 않는다** (schema 2, ADR-0024). `entry`가 런타임을 실행하는 코드를
    가리키고, Bot UI가 **자기 실행 파일을 자식으로 다시 띄워** 그 `entry`를 부른다 — 설치
    파일로 묶은 앱 안에는 콘솔 스크립트가 없기 때문이다.

    포트를 코드에 적지 않는다 — 설정 이름(`port_setting`)과 기본값만 둔다 (CLAUDE.md §5).
    """

    id: str
    label: str
    #: `"<모듈>:<이름>"` — `extension_api.LocalRuntimeEntry` 모양의 호출 가능한 것.
    entry: str
    port_setting: str | None = None
    default_port: int | None = None
    health: str | None = None  # 상태 확인 경로 (예: /v1/health)
    token_dir: bool = False  # 로컬 토큰 파일을 둘 폴더가 필요한가
    start: str = START_ON_DEMAND


class ConfigurationItem(ContractModel):
    """설정 화면의 칸 하나 (BUI-03 「확장별 설정」, STU-10, 서버 실행기 설정).

    **`secret: true`인 칸은 OS 비밀 저장소에 둔다** (ADR-0013). 설정 파일·로그에 남기지 않는다.
    """

    key: str
    label: str
    scope: str  # CONFIG_SCOPES
    # JSON 열쇠는 `schema`인데 pydantic BaseModel의 속성과 겹치므로 별명으로 잇는다.
    json_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")
    secret: bool = False


class PreflightContribution(ContractModel):
    """사전 점검 하나 (`extension_api.PreflightCheck`)."""

    id: str
    entry: str


class ConsolePage(ContractModel):
    """그 서비스 앱 관리 콘솔의 고유 화면 (웹 모듈, `web/apps/svc-console`이 불러 쓴다)."""

    id: str
    label: str
    module: str


class ResourceContribution(ContractModel):
    """Center 리소스 목록(C7)에 올릴 자원 갈래. 응답은 §5 공통 카탈로그 형식이다."""

    type: str
    label: str
    catalog_url: str  # 상대 경로(서버 부분 기준) 또는 allowed_hosts 안의 주소


class Contributes(ContractModel):
    """기여 지점 (ADR-0018 §2). **모르는 열쇠는 무시한다** (호환 규칙) — `extra="allow"`가 보관한다."""

    task_types: list[TaskTypeContribution] = Field(default_factory=list)
    studio_editors: list[StudioEditorContribution] = Field(default_factory=list, alias="studio.editors")
    studio_resource_views: list[ResourceView] = Field(default_factory=list, alias="studio.resource_views")
    bot_ui_utilities: list[Utility] = Field(default_factory=list, alias="bot_ui.utilities")
    bot_ui_local_runtimes: list[LocalRuntime] = Field(default_factory=list, alias="bot_ui.local_runtimes")
    configuration: list[ConfigurationItem] = Field(default_factory=list)
    preflight: list[PreflightContribution] = Field(default_factory=list)
    console_pages: list[ConsolePage] = Field(default_factory=list, alias="console.pages")
    resources: list[ResourceContribution] = Field(default_factory=list)


# ─────────────────────────── 서버 부분 ───────────────────────────


class AdapterAuth(ContractModel):
    """어느 헤더에 키 참조로 푼 값을 넣나. **쿼리 문자열 인증은 없다** (주소·로그에 키가 남는다)."""

    type: str  # KNOWN_AUTH_TYPES
    name: str | None = None  # type=header일 때 헤더 이름


class AdapterLimits(ContractModel):
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_response_kb: int = DEFAULT_MAX_RESPONSE_KB


class AdapterHealth(ContractModel):
    """없으면 Center는 상태를 「확인 전」으로 둔다."""

    path: str
    expect_status: int = 200


class AdapterRequest(ContractModel):
    """요청 템플릿. 값은 위치별로 인코딩한다 (§4-2)."""

    method: str
    path: str
    query: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any | None = None  # JSON 템플릿 (문자열 이어 붙이기 없음)


class ErrorWhen(ContractModel):
    """응답이 실패를 뜻하는 조건. `equals`·`not_equals`·`exists` 중 하나만 쓴다."""

    path: str
    equals: Any | None = None
    not_equals: Any | None = None
    exists: bool | None = None


class AdapterResponse(ContractModel):
    """어디서 출력 필드를 꺼내나. 값은 제한된 JSONPath다."""

    output: dict[str, str] = Field(default_factory=dict)
    error_when: ErrorWhen | None = None


class AdapterOperation(ContractModel):
    """외부 앱의 작업 하나. 기본값이 보수적이다 — 자율 수행만, 멱등 아님.

    `idempotent: false`인 작업이 결과를 모르는 실패(시간 초과·연결 끊김)를 만나면 자동으로
    다시 부르지 않는다. PC는 확인으로 넘기고, 서버는 실행 실패·오류 경계로 보낸다.
    """

    name: OperationName
    description: str | None = None
    modes: list[str] = Field(default_factory=lambda: [MODE_AUTONOMOUS])
    server_ok: bool = True
    idempotent: bool = False
    retry_on: list[int] = Field(default_factory=list)  # 요청이 처리되지 않았다는 뜻의 상태 코드
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    request: AdapterRequest
    response: AdapterResponse = Field(default_factory=AdapterResponse)


class HttpAdapter(ContractModel):
    """C11을 따르지 않는 외부 앱을 **코드 없이** 붙이는 선언 (§4).

    해석기는 `chaeksas.core`에 하나뿐이고, 안전 규칙(https만·리다이렉트 금지·사설망 차단·
    DNS 고정·크기 상한)을 그 해석기가 지킨다.
    """

    allowed_hosts: list[str] = Field(default_factory=list)
    allow_private_network: bool = False
    auth: AdapterAuth | None = None
    limits: AdapterLimits = Field(default_factory=AdapterLimits)
    health: AdapterHealth | None = None
    operations: list[AdapterOperation] = Field(default_factory=list)

    def operation(self, name: str) -> AdapterOperation | None:
        return next((o for o in self.operations if o.name == name), None)


class Service(ContractModel):
    """서버 부분. **주소의 출처는 하나다** — Center 리소스 등록(C7)의 `base_url`이 있으면
    그것을, 없으면 이 값을 쓴다. 클라이언트 설정에 따로 두지 않는다.
    """

    protocol: str  # KNOWN_PROTOCOLS
    base_url: str | None = None
    adapter: HttpAdapter | None = None  # protocol=http-adapter일 때만


class KeyNeed(ContractModel):
    """이 확장이 쓰는 서비스 앱 키 하나.

    - `run`: BPM 프로세스가 작업을 부를 때. BPM 프로세스의 키 참조로 지정한다.
    - `utility`: Bot UI 유틸리티가 쓸 때. `configuration`의 `secret` 칸으로 받는다.
    """

    purpose: str  # KNOWN_PURPOSES
    extra_scopes: list[str] = Field(default_factory=list)
    config_key: str | None = None  # utility일 때 그 키를 받는 configuration 칸


class ExtensionManifest(SchemaVersioned):
    """확장 정의 (C13 최상위). 파일 하나 = 확장 하나.

    schema 2에서 `bot_ui.local_runtimes`의 `command`(명령 배열)가 `entry`(진입점)로 바뀌었다
    (ADR-0024). 필드의 뜻이 바뀐 것이라 번호를 올렸다 (계약 README 원칙 2).
    """

    SCHEMA: ClassVar[int] = 2

    id: ExtensionId
    version: SemVer
    name: str
    description: str | None = None
    publisher: str
    tier: str  # TIERS
    api: str | None = None  # 내장·사내는 필수 (필요한 extension_api 버전 범위)
    service: Service | None = None
    contributes: Contributes = Field(default_factory=Contributes)
    requires_keys: list[KeyNeed] = Field(default_factory=list)
    docs_url: str | None = None
    console_url: str | None = None

    @property
    def is_external(self) -> bool:
        return self.tier == TIER_EXTERNAL

    @property
    def can_contribute_code(self) -> bool:
        """설치 파일에 든 확장만 클라이언트 코드를 돌린다 (ADR-0018 §3)."""
        return self.tier in CODE_TIERS

    @property
    def adapter(self) -> HttpAdapter | None:
        if self.service is None or self.service.protocol != PROTOCOL_HTTP_ADAPTER:
            return None
        return self.service.adapter

    def task_type(self, id: str) -> TaskTypeContribution | None:
        return next((t for t in self.contributes.task_types if t.id == id), None)

    def contributes_summary(self) -> dict[str, list[str]]:
        """C7 `ExtensionResource.contributes_summary` — 기여 지점별 id 목록."""
        c = self.contributes
        found = {
            "task_types": [t.id for t in c.task_types],
            "studio.editors": [e.task_type for e in c.studio_editors],
            "studio.resource_views": [v.id for v in c.studio_resource_views],
            "bot_ui.utilities": [u.id for u in c.bot_ui_utilities],
            "bot_ui.local_runtimes": [r.id for r in c.bot_ui_local_runtimes],
            "configuration": [i.key for i in c.configuration],
            "preflight": [p.id for p in c.preflight],
            "console.pages": [p.id for p in c.console_pages],
            "resources": [r.type for r in c.resources],
        }
        return {k: v for k, v in found.items() if v}


class CatalogItem(ContractModel):
    """공통 카탈로그 항목 (§5). `data`의 모양은 확장이 정하고, Center는 해석하지 않는다."""

    type: str
    id: str
    name: str | None = None
    summary: str | None = None
    updated_at: Timestamp | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class Catalog(SchemaVersioned):
    """`resources[].catalog_url`의 응답 (§5).

    **비밀·셀렉터·업무 값을 넣지 않는다.** 카탈로그는 서버망 안에서만 연다.
    """

    revision: int | None = None
    items: list[CatalogItem] = Field(default_factory=list)


# ─────────────────────────── 해시 ───────────────────────────


def definition_hash(definition: Mapping[str, Any]) -> str:
    """`sha256:<hex>` of `canonical_json(정의)` (C2 규칙).

    **모델이 아니라 받은 그대로의 dict를 해시한다.** 모르는 필드까지 포함해야 서명이 맞는다.
    """
    return "sha256:" + sha256_hex(canonical_json(dict(definition)))


# ─────────────────────────── 검사 규칙 (E1~E7) ───────────────────────────


def bad_template_vars(text: str) -> list[str]:
    """템플릿에 쓸 수 없는 변수들 (§4-2). 비어 있으면 통과."""
    return [
        var
        for raw in _TEMPLATE.findall(text)
        for var in [raw.strip()]
        if var not in TEMPLATE_VARS and not _INPUT_VAR.match(var)
    ]


def is_restricted_jsonpath(path: str) -> bool:
    """제한된 JSONPath인가 — `$`, `.이름`, `[숫자]`만 (§4-2)."""
    return bool(_JSONPATH.match(path))


def _e3(message: str, where: str) -> Violation:
    return Violation(rule="E3", code="adapter_invalid", message=message, items=[where])


def _template_violations(value: Any, where: str) -> list[Violation]:
    """JSON 템플릿을 훑어 쓸 수 없는 변수를 찾는다 (본문은 중첩될 수 있다)."""
    if isinstance(value, str):
        bad = bad_template_vars(value)
        return [_e3(f"쓸 수 없는 템플릿 변수다: {bad}", where)] if bad else []
    if isinstance(value, Mapping):
        return [v for k, item in value.items() for v in _template_violations(item, f"{where}.{k}")]
    if isinstance(value, (list, tuple)):
        return [v for i, item in enumerate(value) for v in _template_violations(item, f"{where}[{i}]")]
    return []


def host_of(url: str) -> str | None:
    """주소의 호스트 (포트 제외). 상대 경로면 `None`."""
    parts = urlsplit(url)
    return parts.hostname if parts.scheme else None


def _check_url(url: str, adapter: HttpAdapter, where: str) -> list[Violation]:
    """어댑터가 부를 주소 하나 — https인가, `allowed_hosts` 안인가."""
    if url.startswith("/"):
        return []  # 상대 경로는 base_url을 따른다
    parts = urlsplit(url)
    out = []
    if parts.scheme not in ("https", "http"):
        out.append(_e3(f"주소가 http(s)가 아니다: {url}", where))
        return out
    if parts.scheme == "http" and not adapter.allow_private_network:
        out.append(_e3(f"https만 쓴다 (사설망은 allow_private_network가 필요하다): {url}", where))
    if parts.hostname is None:
        out.append(_e3(f"호스트가 없다: {url}", where))
    elif parts.hostname not in adapter.allowed_hosts:
        out.append(_e3(f"allowed_hosts에 없는 호스트다: {parts.hostname}", where))
    return out


def _check_adapter_operation(op: AdapterOperation, adapter: HttpAdapter, where: str) -> list[Violation]:
    out: list[Violation] = []
    if not op.modes:
        out.append(_e3("modes가 비어 있다", f"{where}.modes"))
    unknown_modes = [m for m in op.modes if m not in MODES]
    if unknown_modes:
        out.append(_e3(f"모르는 수행 모드다: {unknown_modes}", f"{where}.modes"))

    req = op.request
    if req.method.upper() not in ADAPTER_METHODS:
        out.append(_e3(f"쓸 수 없는 메서드다: {req.method}", f"{where}.request.method"))
    if not req.path.startswith("/"):
        out.append(_e3(f"경로는 /로 시작한다: {req.path!r}", f"{where}.request.path"))
    out += _template_violations(req.path, f"{where}.request.path")
    out += _template_violations(req.query, f"{where}.request.query")
    if req.body is not None:
        out += _template_violations(req.body, f"{where}.request.body")

    for name, value in req.headers.items():
        at = f"{where}.request.headers.{name}"
        if name.lower() in FORBIDDEN_HEADERS:
            out.append(_e3(f"템플릿으로 쓸 수 없는 헤더다: {name}", at))
        elif not _HEADER_NAME.match(name):
            out.append(_e3(f"헤더 이름 규칙에 맞지 않는다: {name!r}", at))
        if _CONTROL.search(value):
            out.append(_e3("헤더 값에 제어 문자가 있다", at))
        out += _template_violations(value, at)

    for field, path in op.response.output.items():
        if not is_restricted_jsonpath(path):
            out.append(_e3(f"제한된 JSONPath가 아니다: {path!r}", f"{where}.response.output.{field}"))
    when = op.response.error_when
    if when is not None:
        if not is_restricted_jsonpath(when.path):
            out.append(_e3(f"제한된 JSONPath가 아니다: {when.path!r}", f"{where}.response.error_when.path"))
        given = [n for n in ("equals", "not_equals", "exists") if getattr(when, n) is not None]
        if len(given) != 1:
            out.append(_e3(f"equals·not_equals·exists 중 하나만 쓴다 (준 것: {given})", f"{where}.response.error_when"))

    bad_codes = [c for c in op.retry_on if not 400 <= c <= 599]
    if bad_codes:
        out.append(_e3(f"재시도 상태 코드가 4xx·5xx가 아니다: {bad_codes}", f"{where}.retry_on"))
    return out


def _check_e1(m: ExtensionManifest) -> list[Violation]:
    """E1. 외부 확장에는 코드 기여가 없다 (422 `external_code_not_allowed`).

    선언만으로 되는 `studio.resource_views`·`resources`만 쓸 수 있다.
    """
    if not m.is_external:
        return []
    c = m.contributes
    forbidden = {
        "task_types": [t.id for t in c.task_types],
        "studio.editors": [e.task_type for e in c.studio_editors],
        "bot_ui.utilities": [u.id for u in c.bot_ui_utilities],
        "bot_ui.local_runtimes": [r.id for r in c.bot_ui_local_runtimes],
        "configuration": [i.key for i in c.configuration],
        "preflight": [p.id for p in c.preflight],
        "console.pages": [p.id for p in c.console_pages],
    }
    items = [f"{key}:{id}" for key, ids in forbidden.items() for id in ids]
    if not items:
        return []
    return [
        Violation(
            rule="E1",
            code="external_code_not_allowed",
            message="외부 확장은 코드를 기여할 수 없다 (선언만 쓴다)",
            items=items,
        )
    ]


def _check_e3(m: ExtensionManifest) -> list[Violation]:
    """E3. HTTP 어댑터의 선언 규칙 (422 `adapter_invalid`). `detail`에 칸별 사유가 담긴다."""
    svc = m.service
    if svc is None:
        return []
    out: list[Violation] = []
    if svc.protocol == PROTOCOL_HTTP_ADAPTER and svc.adapter is None:
        return [_e3("protocol=http-adapter인데 adapter가 없다", "service.adapter")]
    if svc.adapter is not None and svc.protocol != PROTOCOL_HTTP_ADAPTER:
        return [_e3(f"adapter는 protocol=http-adapter일 때만 쓴다 (지금 {svc.protocol})", "service.protocol")]
    adapter = svc.adapter
    if adapter is None:
        return out

    if not adapter.allowed_hosts:
        out.append(_e3("allowed_hosts가 비어 있다 (부를 수 있는 주소가 없다)", "service.adapter.allowed_hosts"))
    for i, host in enumerate(adapter.allowed_hosts):
        if not _HOSTNAME.match(host):
            out.append(_e3(f"호스트 이름만 적는다 (와일드카드·포트·스킴 없이): {host!r}",
                           f"service.adapter.allowed_hosts[{i}]"))

    if svc.base_url is not None:
        out += _check_url(svc.base_url, adapter, "service.base_url")
    if adapter.health is not None and not adapter.health.path.startswith("/"):
        out.append(_e3(f"경로는 /로 시작한다: {adapter.health.path!r}", "service.adapter.health.path"))

    auth = adapter.auth
    if auth is not None:
        if auth.type not in KNOWN_AUTH_TYPES:
            out.append(_e3(f"모르는 인증 방식이다: {auth.type}", "service.adapter.auth.type"))
        if auth.type == AUTH_HEADER:
            if not auth.name:
                out.append(_e3("type=header는 헤더 이름이 필요하다", "service.adapter.auth.name"))
            elif auth.name.lower() in FORBIDDEN_HEADERS - {"authorization"}:
                out.append(_e3(f"인증에 쓸 수 없는 헤더다: {auth.name}", "service.adapter.auth.name"))

    seen: set[str] = set()
    for i, op in enumerate(adapter.operations):
        where = f"service.adapter.operations[{i}]"
        if op.name in seen:
            out.append(_e3(f"작업 이름이 겹친다: {op.name}", f"{where}.name"))
        seen.add(op.name)
        out += _check_adapter_operation(op, adapter, where)

    for i, res in enumerate(m.contributes.resources):
        out += _check_url(res.catalog_url, adapter, f"contributes.resources[{i}].catalog_url")
    return out


def _check_shape(m: ExtensionManifest) -> list[Violation]:
    """타입만으로는 못 보는 모양 — 아는 값인가, 짝이 맞나.

    열린 문자열이라 거부하지 않는 값(`tier`·`protocol`)도 여기서는 알려 준다. 확장 호스트는
    아는 값만 켜므로(C13 호환 규칙), 정의 파일을 쓰는 사람이 미리 알아야 한다.
    """
    out: list[Violation] = []
    if m.tier not in TIERS:
        out.append(Violation(rule="C13", code="unknown_tier", message=f"모르는 등급이다: {m.tier}",
                             items=sorted(TIERS)))
    if m.service is not None and m.service.protocol not in KNOWN_PROTOCOLS:
        out.append(Violation(rule="C13", code="unknown_protocol",
                             message=f"모르는 서버 부분 종류다: {m.service.protocol}", items=sorted(KNOWN_PROTOCOLS)))

    if m.api is None and m.can_contribute_code:
        out.append(Violation(rule="E5", code="api_missing",
                             message=f"{m.tier} 확장은 필요한 extension_api 버전 범위(api)를 적는다"))

    c = m.contributes
    for t in c.task_types:
        if t.editor is not None and t.editor.kind == EDITOR_BUILTIN and not t.editor.entry:
            out.append(Violation(rule="C13", code="editor_entry_missing",
                                 message=f"태스크 종류 {t.id}의 편집기가 builtin인데 entry가 없다"))
        bad = [loc for loc in t.run_locations if loc not in KNOWN_RUN_LOCATIONS]
        if bad:
            out.append(Violation(rule="C13", code="unknown_run_location",
                                 message=f"태스크 종류 {t.id}의 실행 위치를 모른다", items=bad))
        if not t.run_locations:
            out.append(Violation(rule="C13", code="run_locations_missing",
                                 message=f"태스크 종류 {t.id}에 실행 위치가 없다"))
    for item in c.configuration:
        if item.key.startswith(RESERVED_CONFIG_PREFIX):
            # E7. 호스트가 띄운 로컬 런타임을 이 이름으로 알려 준다 (C13) — 가려지면 안 된다.
            out.append(Violation(rule="E7", code="reserved_config_key",
                                 message=f"설정 칸 {item.key}은 호스트가 쓰는 이름이다 "
                                         f"({RESERVED_CONFIG_PREFIX}*)"))
        if item.scope not in CONFIG_SCOPES:
            out.append(Violation(rule="C13", code="unknown_scope",
                                 message=f"설정 칸 {item.key}의 scope를 모른다: {item.scope}",
                                 items=sorted(CONFIG_SCOPES)))
    for rt in c.bot_ui_local_runtimes:
        if rt.start not in KNOWN_STARTS:
            out.append(Violation(rule="C13", code="unknown_start",
                                 message=f"로컬 런타임 {rt.id}의 start를 모른다: {rt.start}",
                                 items=sorted(KNOWN_STARTS)))
        if not rt.entry:
            out.append(Violation(rule="C13", code="entry_missing",
                                 message=f"로컬 런타임 {rt.id}에 진입점(entry)이 없다"))

    config_keys = {item.key for item in c.configuration}
    for need in m.requires_keys:
        if need.purpose not in KNOWN_PURPOSES:
            out.append(Violation(rule="C13", code="unknown_purpose",
                                 message=f"모르는 키 용도다: {need.purpose}", items=sorted(KNOWN_PURPOSES)))
        if need.purpose != PURPOSE_UTILITY:
            continue
        # 유틸리티 키는 설정의 secret 칸으로 받는다 (ADR-0013).
        if not need.config_key:
            out.append(Violation(rule="C13", code="config_key_missing",
                                 message="purpose=utility인 키는 받을 configuration 칸(config_key)이 필요하다"))
        elif need.config_key not in config_keys:
            out.append(Violation(rule="C13", code="config_key_not_found",
                                 message=f"config_key {need.config_key}가 configuration에 없다",
                                 items=sorted(config_keys)))
        else:
            item = next(i for i in c.configuration if i.key == need.config_key)
            if not item.secret:
                out.append(Violation(rule="C13", code="key_config_not_secret",
                                     message=f"키를 받는 칸 {item.key}은 secret: true여야 한다 (OS 비밀 저장소)"))

    for field in ("docs_url", "console_url"):
        url: str | None = getattr(m, field)
        if url is not None and urlsplit(url).scheme not in ("http", "https"):
            out.append(Violation(rule="C13", code="url_scheme",
                                 message=f"{field}는 http(s)만 쓴다: {url}"))
    return out


def validate(m: ExtensionManifest, *, from_center: bool = False) -> list[Violation]:
    """C13 검사 규칙. 위반 목록을 돌려준다 (비어 있으면 통과).

    - **E1** 외부 확장에 코드 기여가 없다.
    - **E2** `from_center=True`(Center에 외부로 등록된 정의)인데 등급이 `external`이 아니면 거부한다.
      내장·사내 확장은 설치 파일에 든 것만 쓴다 (ADR-0018 §3).
    - **E3** HTTP 어댑터 선언 규칙 (§4).
    - 그 밖에 타입만으로는 못 보는 모양 (아는 `tier`·`scope`·`purpose`인가, 키를 받는 칸이 비밀인가).

    여기서 하지 않는 것:
    - **E4** (태스크 종류가 확장 사이에 겹치지 않는다) — 다른 확장을 알아야 한다. `task_type_conflicts()`.
    - **E5** (`api` 범위가 맞는다) — 호스트의 `extension_api` 버전을 알아야 한다. `check_api()`.
    - **E6** (외부 정의의 봉투) — Admin 공개키가 필요하다. `verify_external()`.
    - 크기 한도 — 파일·본문 바이트를 알아야 한다. `check_size()`.
    - 실행할 때만 알 수 있는 것: Center 리소스 등록(C7)으로 덮어쓴 `base_url`이 `allowed_hosts`
      안인가, 호스트가 **정말** 사설 주소인가. 해석기(`core`)가 부를 때 같은 규칙으로 본다 (§4-3).
    """
    out = [*_check_e1(m), *_check_e3(m), *_check_shape(m)]
    if from_center and not m.is_external:
        out.append(
            Violation(
                rule="E2",
                code="id_conflict",
                message=f"{m.tier} 확장은 설치 파일에 든 것만 쓴다 (Center에 외부로 등록할 수 없다)",
            )
        )
    return out


def task_type_conflicts(manifests: Iterable[ExtensionManifest]) -> list[Violation]:
    """E4. 태스크 종류 id가 확장 사이에 겹치는가 (409 `task_type_conflict`)."""
    owners: dict[str, list[str]] = {}
    for m in manifests:
        for t in m.contributes.task_types:
            owners.setdefault(t.id, []).append(m.id)
    return [
        Violation(
            rule="E4",
            code="task_type_conflict",
            message=f"태스크 종류 {task_type}을 여러 확장이 기여한다",
            items=sorted(ids),
        )
        for task_type, ids in sorted(owners.items())
        if len(ids) > 1
    ]


def check_api(m: ExtensionManifest, *, api_version: str) -> list[Violation]:
    """E5. 이 호스트의 `extension_api` 버전이 확장이 요구하는 범위에 드나.

    맞지 않으면 확장 호스트는 켜지 않고 목록에 「호환 안 됨」으로 보인다.
    """
    if m.api is None:
        return [] if not m.can_contribute_code else [
            Violation(rule="E5", code="api_missing", message=f"{m.tier} 확장은 api 범위를 적는다")
        ]
    try:
        ok = satisfies(api_version, m.api)
    except InvalidVersion as e:
        return [Violation(rule="E5", code="api_invalid", message=f"api 범위를 읽을 수 없다: {m.api!r} ({e})")]
    if ok:
        return []
    return [
        Violation(
            rule="E5",
            code="api_incompatible",
            message=f"확장 {m.id}은 extension_api {m.api}를 요구하는데 이 호스트는 {api_version}이다",
        )
    ]


def check_size(raw: bytes) -> list[Violation]:
    """정의 크기 한도 (256 KB)."""
    if len(raw) <= MAX_DEFINITION_BYTES:
        return []
    return [
        Violation(
            rule="C13",
            code="too_large",
            message=f"정의가 한도를 넘는다 ({len(raw)}바이트 > {MAX_DEFINITION_BYTES})",
        )
    ]


def verify_external(
    definition: Mapping[str, Any],
    envelope: Envelope,
    *,
    keys: Sequence[AdminKey],
) -> list[Violation]:
    """E6. 외부 정의의 봉투(C2 `extension`)가 검증되고 `definition_hash`가 맞는가.

    **실행하는 쪽은 Center에서 받은 정의의 봉투를 다시 검증한다** (C13 「전송」). 관리자 토큰만
    새어도 Bot의 키·업무 값이 다른 주소로 새는 일을 막으려고, 배포와 같은 관문을 둔다.

    `verify()`가 봉투 자체를 보고(V1~V4, `kind`까지), 여기서는 그 봉투가 **이 정의**에 대한
    것인지(해시·id·버전)를 본다. `extension` claim에는 시간 창이 없어 V5는 쓰지 않는다.
    """
    failed = verify(envelope, keys=keys, expect_kind="extension")
    if failed:
        return [Violation(rule="E6", code="bad_envelope", message=str(v)) for v in failed]
    try:
        claim = ExtensionClaim.model_validate(envelope.payload)
    except ValidationError as e:
        return [Violation(rule="E6", code="bad_envelope", message=f"extension claim이 아니다: {e.error_count()}곳")]
    computed = definition_hash(definition)
    if claim.definition_hash != computed:
        return [
            Violation(
                rule="E6",
                code="hash_mismatch",
                message=f"봉투의 definition_hash가 정의와 다르다 (봉투 {claim.definition_hash}, 계산값 {computed})",
            )
        ]
    mismatched = [
        f"{field}: 봉투 {getattr(claim, field)!r} ≠ 정의 {definition.get(field)!r}"
        for field in ("id", "version")
        if getattr(claim, field) != definition.get(field)
    ]
    if mismatched:
        return [Violation(rule="E6", code="bad_envelope", message="봉투와 정의가 다른 확장이다", items=mismatched)]
    return []

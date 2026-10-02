"""C1. 패키지 매니페스트 — 패키지 zip 루트의 `manifest.json`.

단일 원본: `docs/03-contracts/C1-package-manifest.md`. 검사 규칙 R1~R8은 `validate()`에 있고,
Studio(빌드)·Center(업로드)·Bot UI·서버 실행기(설치)가 **같은 함수**를 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Sha256, Timestamp, Violation

PackageKind = Literal["bpm_process", "process_lib", "toolpack"]
RunLocation = Literal["server", "pc"]

KNOWN_TRIGGER_KINDS = frozenset({"none", "message", "timer", "conditional", "signal"})
KNOWN_DOMAINS = frozenset({"llm", "api", "doc", "web", "desktop"})
KNOWN_SETTINGS = frozenset({"llm", "vlm", "smtp"})
KNOWN_BUILT_BY = frozenset({"studio", "cli"})

#: 서버에서 돌 수 없는 AI 태스크 대상 환경 (R2).
PC_ONLY_DOMAINS = frozenset({"web", "desktop"})

#: `key_ref` 이름 규칙 (R4). `_`가 없으므로 키 값(`chk_…`)은 들어갈 수 없다.
KEY_REF_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"

PackageId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")]
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")]


class Trigger(ContractModel):
    """시작 방법. `kind`는 열린 문자열 (알려진 값은 `KNOWN_TRIGGER_KINDS`)."""

    kind: str
    name: str | None = None  # 메시지 이름


class ServiceAppNeed(ContractModel):
    """부르는 서비스 앱과 **키 참조**. 키 값은 절대 들어가지 않는다 (R5)."""

    app_id: str
    operations: list[str]
    # 이름 규칙은 타입이 아니라 R4(`validate()`)가 검사한다 — 위반에 `invalid_key_ref` 코드를 붙이려고.
    key_ref: str
    task_key_refs: list[str] = Field(default_factory=list)


class ResourceRef(ContractModel):
    """확장이 기여한 자원 중 쓰는 것 (예: `{type: "ui_page", id: "erp.order.form"}`)."""

    type: str
    id: str


class ExtensionNeed(ContractModel):
    """쓰는 확장과 버전 범위 (C13). 외부 확장은 `definition_hash`로 정의를 고정한다."""

    id: str
    version: str
    definition_hash: str | None = None


class TaskTypeNeed(ContractModel):
    """확장이 기여한 태스크 종류와, 그 확장 정의에 적힌 실행 위치. R2 판정에 쓴다."""

    id: str
    extension: str
    run_locations: list[str]


class ToolpackRef(ContractModel):
    """쓰는 툴팩. 해시로 고정한다 (R7)."""

    id: str
    version: str
    content_hash: str


class Requires(ContractModel):
    """실행에 필요한 것. 모두 선택이고, 없으면 "제한 없음"이다."""

    core: str | None = None
    tools: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    settings: list[str] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    service_apps: list[ServiceAppNeed] = Field(default_factory=list)
    resources: list[ResourceRef] = Field(default_factory=list)
    extensions: list[ExtensionNeed] = Field(default_factory=list)
    task_types: list[TaskTypeNeed] = Field(default_factory=list)
    libs: list[str] = Field(default_factory=list)
    toolpacks: list[ToolpackRef] = Field(default_factory=list)
    runtimes: list[str] = Field(default_factory=list)
    os: list[str] = Field(default_factory=list)


class HumanNeeds(ContractModel):
    """사람 개입 종류. 서버 실행 가능 여부(R2) 판정에 쓴다."""

    approval_center: bool = False
    approval_field: bool = False
    confirmation: bool = False


class Built(ContractModel):
    """누가 언제 무엇으로 빌드했나."""

    by: str  # 열린 문자열 (KNOWN_BUILT_BY)
    at: Timestamp
    core: str
    spec_version: int


class ProvidedProcess(ContractModel):
    """`process_lib`이 제공하는 공유 BPM 프로세스 하나."""

    process_id: str
    file: str
    name: str | None = None
    description: str | None = None
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    run_location: RunLocation | None = None
    ai_tasks: int | None = None
    human: HumanNeeds | None = None


class ProvidedTool(ContractModel):
    """툴팩이 제공하는 도구 하나. `args`는 JSON Schema."""

    name: str
    domain: str
    description: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)


class Provides(ContractModel):
    processes: list[ProvidedProcess] = Field(default_factory=list)
    tools: list[ProvidedTool] = Field(default_factory=list)


class Manifest(SchemaVersioned):
    """패키지 매니페스트 (C1 최상위).

    `kind="bpm_process"`이고 `run_location`이 없으면 **`server`로 채운다** (서버 우선, 호환 규칙).
    """

    kind: PackageKind
    id: PackageId
    version: SemVer
    name: str | None = None
    description: str | None = None
    run_location: RunLocation | None = None
    entry: str | None = None
    process_id: str | None = None
    triggers: list[Trigger] = Field(default_factory=list)
    requires: Requires
    human: HumanNeeds
    outputs: list[str] = Field(default_factory=list)
    provides: Provides | None = None
    built: Built
    content_hash: Sha256

    @model_validator(mode="after")
    def _default_run_location(self) -> Manifest:
        if self.kind == "bpm_process" and self.run_location is None:
            self.run_location = "server"
        return self


def _check_r1(m: Manifest) -> list[Violation]:
    out = []
    if m.kind == "bpm_process":
        missing = [f for f in ("entry", "process_id") if getattr(m, f) is None]
        if missing:
            out.append(Violation(rule="R1", message="bpm_process에 필수 필드가 없다", items=missing))
    elif m.run_location is not None:
        out.append(Violation(rule="R1", message=f"kind={m.kind}에는 run_location을 두지 않는다"))
    return out


def _check_r2(m: Manifest) -> list[Violation]:
    if m.run_location != "server":
        return []
    items = []
    items += [f"domains:{d}" for d in m.requires.domains if d in PC_ONLY_DOMAINS]
    items += [
        f"task_types:{t.id}" for t in m.requires.task_types if "server" not in t.run_locations
    ]
    if m.human.approval_field:
        items.append("human.approval_field")
    if m.human.confirmation:
        items.append("human.confirmation")
    if not items:
        return []
    return [
        Violation(
            rule="R2",
            code="server_incompatible",
            message="실행 위치가 server인데 서버에서 할 수 없는 것이 있다",
            items=items,
        )
    ]


def _check_r3(m: Manifest, lib_locations: Mapping[str, str]) -> list[Violation]:
    """서버 BPM 프로세스가 PC 공유 BPM 프로세스를 부르면 PC 위임 — schema 1에서는 거부."""
    if m.run_location != "server":
        return []
    pc_libs = [lib for lib in m.requires.libs if lib_locations.get(lib) == "pc"]
    if not pc_libs:
        return []
    return [
        Violation(
            rule="R3",
            code="delegation_not_supported",
            message="서버 BPM 프로세스가 PC 공유 BPM 프로세스를 부른다 (PC 위임은 schema 1 범위 밖)",
            items=pc_libs,
        )
    ]


def _check_r4(m: Manifest) -> list[Violation]:
    import re

    out = []
    for need in m.requires.service_apps:
        bad = [r for r in [need.key_ref, *need.task_key_refs] if not re.fullmatch(KEY_REF_PATTERN, r)]
        if bad:
            out.append(
                Violation(
                    rule="R4",
                    code="invalid_key_ref",
                    message=f"{need.app_id}의 키 참조 이름이 규칙({KEY_REF_PATTERN})에 맞지 않는다",
                    items=bad,
                )
            )
    return out


def _check_r6(m: Manifest, computed_hash: str | None) -> list[Violation]:
    if computed_hash is None or computed_hash == m.content_hash:
        return []
    return [
        Violation(
            rule="R6",
            code="hash_mismatch",
            message=f"content_hash가 실제 내용과 다르다 (매니페스트 {m.content_hash}, 계산값 {computed_hash})",
        )
    ]


def _check_r7(m: Manifest) -> list[Violation]:
    bad = [t.id for t in m.requires.toolpacks if not t.content_hash]
    if not bad:
        return []
    return [
        Violation(
            rule="R7",
            message="툴팩의 content_hash가 비어 있다 (로컬 개발용 툴팩은 업로드 불가)",
            items=bad,
        )
    ]


def validate(
    m: Manifest,
    *,
    lib_locations: Mapping[str, str] | None = None,
    computed_hash: str | None = None,
) -> list[Violation]:
    """C1 검사 규칙. 위반 목록을 돌려준다 (비어 있으면 통과).

    인자를 주지 않으면 **매니페스트 하나만 보고 할 수 있는 검사**만 한다.

    - `lib_locations`: `<id>@<version>` → `"server"`\\|`"pc"`. 없으면 R3을 건너뛴다.
    - `computed_hash`: 패키지 실물에서 계산한 해시. 없으면 R6을 건너뛴다.
      폴더면 `chaeksas.contracts.hashing.content_hash_dir(root)`, zip이면 `content_hash_zip(path)`.

    여기서 하지 않는 것:
    - **R5** (키 값·비밀이 없음) — Studio 빌드가 보장한다. Center는 R4만 본다 (C1 검사 규칙 표).
    - **R8** (서버 배포 때 작업이 `server_ok`·결정 수행인지) — Center가 배포 시점에 C11 manifest·
      리소스 목록(C7)과 대조한다. 매니페스트만으로는 알 수 없다.
    """
    return [
        *_check_r1(m),
        *_check_r2(m),
        *_check_r3(m, lib_locations or {}),
        *_check_r4(m),
        *_check_r6(m, computed_hash),
        *_check_r7(m),
    ]

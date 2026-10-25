"""C1. 패키지 매니페스트 — 패키지 zip 루트의 `manifest.json`.

단일 원본: `docs/03-contracts/C1-package-manifest.md`. 검사 규칙은 `validate()`에 있고,
Studio(빌드)·Center(업로드)·Bot UI·서버 실행기(설치)가 **같은 함수**를 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Sha256, Timestamp, Violation

PackageKind = Literal["bpm_process", "process_lib"]
RunLocation = Literal["server", "pc"]

KNOWN_TRIGGER_KINDS = frozenset({"none", "message", "timer", "conditional", "signal"})
#: 실행하는 쪽이 갖춰야 할 설정 이름 (C1 `requires.settings`).
SETTING_LLM = "llm"
SETTING_VLM = "vlm"
SETTING_SMTP = "smtp"
KNOWN_SETTINGS = frozenset({SETTING_LLM, SETTING_VLM, SETTING_SMTP})
#: `built.by`의 아는 값. **검사하지 않는다** — 남의 도구로 만든 올바른 패키지를 거부하게
#: 되므로 **열린 문자열이 맞다** (`settings`와 다르다: 그쪽은 우리가 아는 것만 점검할 수 있어
#: R11이 막는다). 화면이 「studio로 만듦」처럼 풀어 쓸 때 쓰는 목록이다.
KNOWN_BUILT_BY = frozenset({"studio", "cli"})

#: AI 태스크의 대상 환경 — C14 `chk:aiTask.domain`과 C1 `requires.domains`가 **같은 목록**이다.
#: 거르는 자리는 둘이지만(C14 B8이 그림에서, R2가 매니페스트에서) **정의는 여기 하나**다.
#: 자리가 C1 쪽인 것은 층 때문이다 — `bpmn_ext`가 이 모듈을 import한다 (거꾸로는 순환이다).
KNOWN_DOMAINS = frozenset({"llm", "api", "doc", "web", "desktop"})

#: 서버에서 돌 수 없는 AI 태스크 대상 환경 (R2·C14 B6, `core`의 사전 점검·AI 태스크도 본다).
PC_ONLY_DOMAINS = frozenset({"web", "desktop"})

#: `key_ref` 이름 규칙 (R4). `_`가 없으므로 키 값(`chk_…`)은 들어갈 수 없다.
KEY_REF_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"

PackageId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")]
SemVer = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")]


class Trigger(ContractModel):
    """시작 방법 — 진입 정의의 시작 이벤트 하나를 옮긴 것.

    `kind`는 `KNOWN_TRIGGER_KINDS` 중 하나다. 타입이 아니라 **R9**가 검사한다 — 위반에
    `unknown_trigger_kind` 코드를 붙여 Studio·Center가 같은 문구로 말하려고 (R4와 같은 결).

    **이름과 식은 다른 칸이다** — `name`은 이벤트 이름(C12 메시지 API가 이 이름으로 보낸다),
    `expression`은 타이머 식(`timeCycle`의 cron·ISO)이다. 한 칸에 담으면 읽는 쪽이 타이머
    트리거의 `name`을 메시지 이름으로 읽는다.
    """

    kind: str
    name: str | None = None  # 이벤트 이름 (`message`는 메시지 이름, `signal`은 신호 이름)
    expression: str | None = None  # 타이머 식 (`timer`만)


class ManifestInput(ContractModel):
    """진입 정의가 받는 입력 하나 — `chk:process.inputs`를 옮긴 것 (C1). 작업 지시 화면이 칸을 그린다."""

    name: str
    type: str  # C14 VALUE_TYPES
    required: bool = False
    description: str | None = None
    default: Any = None


class ServiceAppNeed(ContractModel):
    """부르는 서비스 앱과 **키 참조**. 키 값은 절대 들어가지 않는다 (R5)."""

    app_id: str
    operations: list[str]
    # 이름 규칙은 타입이 아니라 R4(`validate()`)가 검사한다 — 위반에 `invalid_key_ref` 코드를 붙이려고.
    # **없으면 키를 받지 않는 앱이다** (C13 `auth`가 없는 외부 앱, ADR-0091) — 받는 쪽은 묻지 않는다.
    key_ref: str | None = None
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
    #: **아는 쪽이 준다 — 모르면 넣지 않는다** (C3 `queued_s`·C4 `key_expires_at`과 같은 결).
    #: 실행 위치는 **확장 정의만** 안다 (C13 `task_types[].run_locations`, ADR-0018). 패키지를
    #: 만드는 PC에 그 확장이 깔려 있지 않거나 꺼져 있으면(ADR-0043) 적을 것이 없다 — 그때 빈
    #: 목록을 적으면 R2가 「서버에서 안 된다」로 읽어 **올바른 패키지를 거부한다**.
    run_locations: list[str] | None = None


class Requires(ContractModel):
    """실행에 필요한 것. 모두 선택이고, 없으면 "제한 없음"이다."""

    core: str | None = None
    tools: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    settings: list[str] = Field(default_factory=list)
    service_apps: list[ServiceAppNeed] = Field(default_factory=list)
    resources: list[ResourceRef] = Field(default_factory=list)
    extensions: list[ExtensionNeed] = Field(default_factory=list)
    task_types: list[TaskTypeNeed] = Field(default_factory=list)
    libs: list[str] = Field(default_factory=list)
    #: **PC 위임**으로 부르는 PC Bot (`<id>@<version>` 또는 `<id>` — 판을 비우면 배포된 판,
    #: [ADR-0062](../decisions/0062-pc-delegation.md)). `libs`와 다르다: 복사해 넣는 것이
    #: 아니라 **따로 올리고 따로 배포한 Bot**이다.
    delegations: list[str] = Field(default_factory=list)
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


class Provides(ContractModel):
    processes: list[ProvidedProcess] = Field(default_factory=list)


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
    inputs: list[ManifestInput] = Field(default_factory=list)
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
    # **선언된 것이 `server`를 빼놓았을 때만** 막는다. 비어 있거나 없는 것은 「모른다」는 뜻이고
    # (`TaskTypeNeed.run_locations`), 모르는 것을 막으면 확장을 깔지 않은 PC에서 만든 올바른
    # 패키지가 거부된다. 그 확장이 **정말 없는** 경우는 배포 때 확장 누락이 막는다 (C7).
    items += [
        f"task_types:{t.id}"
        for t in m.requires.task_types
        if t.run_locations and "server" not in t.run_locations
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
    """서버 BPM 프로세스가 **PC 공유 BPM 프로세스**를 부르면 거부 (C1 R3).

    **PC 위임의 길이 아니다** ([ADR-0062](../decisions/0062-pc-delegation.md)) — 패키지에 복사해
    넣은 정의(`libs/`)는 PC에서 돌릴 길이 없다: 작업은 **배포된 패키지**를 가리키고 공유 BPM
    프로세스에는 **진입이 없다**(R1). 위임은 `requires.delegations`로 적는다.
    """
    if m.run_location != "server":
        return []
    pc_libs = [lib for lib in m.requires.libs if lib_locations.get(lib) == "pc"]
    if not pc_libs:
        return []
    return [
        Violation(
            rule="R3",
            code="delegation_not_supported",
            message="서버 BPM 프로세스가 PC 공유 BPM 프로세스를 부른다 "
                    "(PC 위임은 requires.delegations로 적는다 — 복사해 넣은 정의는 PC에서 돌릴 길이 없다)",
            items=pc_libs,
        )
    ]


def _check_r10(m: Manifest) -> list[Violation]:
    """PC 위임은 **서버 Bot만** 한다 (C1 R10, [ADR-0062](../decisions/0062-pc-delegation.md)).

    PC 실행은 그 PC의 자리를 끝까지 쥐므로(ADR-0014) PC가 다른 PC를 기다리면 둘이 서로를
    기다릴 수 있다. C14 B14가 그림에서 같은 것을 보지만 **매니페스트를 보는 쪽은 그림을 읽지
    않는다** — 둘 다 있어야 올리는 길과 설치하는 길이 함께 막힌다.
    """
    if not m.requires.delegations or m.run_location == "server":
        return []
    return [
        Violation(
            rule="R10",
            code="delegation_not_from_pc",
            message="PC 위임은 실행 위치가 server인 BPM 프로세스만 할 수 있다",
            items=sorted(m.requires.delegations),
        )
    ]


def _check_r12(m: Manifest) -> list[Violation]:
    """**자기 자신에게 위임하지 않는다** (C1 R12, [ADR-0082](../decisions/0082-batch-start.md)).

    끝나지 않는 되부름이다 — 위임은 결과를 기다리므로 한 건이 같은 Bot을 또 기동하고 그것이
    또 기동한다. 그림은 자기 패키지 id를 모르므로 **매니페스트가 본다** (`id`와
    `requires.delegations`가 한 자리에 있다).
    """
    mine = [one for one in m.requires.delegations if one.split("@", 1)[0] == m.id]
    if not mine:
        return []
    return [
        Violation(
            rule="R12",
            code="delegation_to_self",
            message="자기 자신에게 위임할 수 없다 (끝나지 않는 되부름이다)",
            items=sorted(mine),
        )
    ]


def _check_r4(m: Manifest) -> list[Violation]:
    import re

    out = []
    for need in m.requires.service_apps:
        refs = [*([] if need.key_ref is None else [need.key_ref]), *need.task_key_refs]
        bad = [r for r in refs if not re.fullmatch(KEY_REF_PATTERN, r)]
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


def _check_r9(m: Manifest) -> list[Violation]:
    """시작 방법의 `kind`가 계약에 적힌 다섯 중 하나인가 (C1 R9).

    **「모르는 것」으로 보고 넘기지 않는다** — 시작 방법은 사람이 적는 값이 아니라 그림에서
    기계가 옮기는 값이라, 모르는 이름이 들어왔다면 옮기는 쪽의 흠이다. 경고로 두면 읽는 쪽이
    `timer`를 기다리며 아무 말 없이 영영 못 만난다.
    """
    bad = sorted({t.kind for t in m.triggers if t.kind not in KNOWN_TRIGGER_KINDS})
    if not bad:
        return []
    return [
        Violation(
            rule="R9",
            code="unknown_trigger_kind",
            message="triggers[].kind가 계약에 없는 값이다 "
            f"(아는 값: {', '.join(sorted(KNOWN_TRIGGER_KINDS))})",
            items=bad,
        )
    ]


def _check_r11(m: Manifest) -> list[Violation]:
    """`requires.settings`가 계약에 적힌 것 중 하나인가 (C1 R11).

    **R9와 같은 까닭이다** — 갖춰야 할 설정은 사람이 적는 값이 아니라 **그림에서 Studio가
    옮기는 값**이고(`chk:email` → `smtp`), 읽는 쪽은 그 이름으로 「이 호스트가 갖췄나」를 본다
    (`core.preflight`). 모르는 이름이 들어오면 그 점검은 **아무 말 없이 지나가** 준비되지 않은
    Bot이 실행되고 그 태스크에서 죽는다. R9를 만들기 전 `triggers[].kind`가 겪은 그 꼴이다.

    열어 두지 않는 것은 **우리가 아는 설정만 점검할 수 있어서**다 — `built.by`처럼 남이 적을
    수 있는 값이 아니다 (그쪽은 열린 문자열이 맞다).
    """
    bad = sorted({one for one in m.requires.settings if one not in KNOWN_SETTINGS})
    if not bad:
        return []
    return [
        Violation(
            rule="R11",
            code="unknown_setting",
            message="requires.settings가 계약에 없는 값이다 "
            f"(아는 값: {', '.join(sorted(KNOWN_SETTINGS))})",
            items=bad,
        )
    ]


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
        *_check_r9(m),
        *_check_r10(m),
        *_check_r11(m),
        *_check_r12(m),
    ]

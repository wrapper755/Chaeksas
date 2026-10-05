"""C8. 계획·치유·보고 — **UI 자동화 확장이 소유한다** (ADR-0018).

단일 원본: `docs/03-contracts/C8-ui-automation-plan-heal-report.md`.

세 가지가 모델에 그대로 박혀 있다.

- **사다리는 Worker가 로컬에서 돈다.** 폴백 도중에는 네트워크를 타지 않는다 — 계획에 사다리
  **전부**가 실려 내려온다.
- **정책도 계획에 실려 온다** (시간 제한·치유 한도). Worker를 다시 배포하지 않고 서버가
  동작을 바꾼다.
- **업무 값을 보내지 않는다** (원칙 6). 치유 요청의 스냅샷은 구조와 라벨만 남긴다.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned

#: 로케이터 전략 (웹 / 데스크톱). 섞어 쓰지 않는다 — `platform`과 맞아야 한다.
WEB_STRATEGIES = ("role", "test_id", "css", "xpath")
DESKTOP_STRATEGIES = ("automation_id", "class_name", "control_name")

#: 기본 우선순위 — **안정한 것부터**. 데스크톱 순서의 이유는 ADR-0020에 있다
#: (`control_name`은 화면 언어를 탄다).
DEFAULT_PRIORITY: dict[str, int] = {
    "role": 1,
    "test_id": 2,
    "css": 3,
    "xpath": 4,
    "automation_id": 1,
    "class_name": 2,
    "control_name": 3,
}

ACTIVE = "active"
UNVERIFIED = "unverified"
DEPRECATED = "deprecated"

WEB = "web"
DESKTOP = "desktop"

#: 가린 값 (원칙 6 — 치유 요청에 업무 값을 싣지 않는다).
MASK = "•••"


class LocatorSpec(ContractModel):
    """로케이터 하나. `deprecated`는 **시도하지 않는다**."""

    type: str
    value: str
    #: `role`일 때만, 필수 (접근성 이름).
    name: str | None = None
    priority: int | None = None
    status: str = ACTIVE
    exact: bool = False
    #: 데스크톱만 — 그 전략으로 찾은 것을 컨트롤 종류로 좁힌다. **열쇠에는 넣지 않는다.**
    control_type: str | None = None
    timeout_ms: int | None = None
    platform: str = WEB

    @property
    def key(self) -> str:
        """`<type>|<value>|<name 또는 빈 문자열>` — 통계·승격·보고가 이것으로 가리킨다."""
        return f"{self.type}|{self.value}|{self.name or ''}"

    @property
    def rank(self) -> int:
        return self.priority if self.priority is not None else DEFAULT_PRIORITY.get(self.type, 99)

    @property
    def usable(self) -> bool:
        return self.status != DEPRECATED


class Policy(ContractModel):
    """계획에 실려 오는 정책 — Worker를 다시 배포하지 않고 서버가 바꾼다."""

    locator_timeout_ms: int = 2000
    action_timeout_ms: int = 10000
    navigation_timeout_ms: int = 30000
    require_unique_match: bool = True
    max_healing_attempts: int = 3


class PlanStep(ContractModel):
    """확정된 스텝 하나 (동작·값 규칙은 C10과 같다)."""

    semantic_key: str
    action: str
    value: Any = None
    expect_navigation: bool = False


class ElementInfo(ContractModel):
    """치유 프롬프트용 **시맨틱** 정보 (셀렉터가 아니다)."""

    description: str = ""
    role: str = ""


class ExecutionPlan(SchemaVersioned):
    """`POST /v1/ops/plan`의 결과 — **사다리 전부**가 여기 있다."""

    SCHEMA: ClassVar[int] = 1

    plan_id: str
    page_id: str
    platform: str = WEB
    start_url: str | None = None
    #: 레지스트리 판 번호 (C9). Worker 캐시 열쇠에 쓴다.
    revision: int = 1
    steps: list[PlanStep] = Field(default_factory=list)
    locators: dict[str, list[LocatorSpec]] = Field(default_factory=dict)
    elements: dict[str, ElementInfo] = Field(default_factory=dict)
    policy: Policy = Field(default_factory=Policy)

    def ladder(self, semantic_key: str) -> list[LocatorSpec]:
        """그 요소의 사다리 — **안정한 것부터**, `deprecated`는 뺀다."""
        found = [one for one in self.locators.get(semantic_key, []) if one.usable]
        return sorted(found, key=lambda one: one.rank)

    def missing_keys(self) -> list[str]:
        """사다리가 없는 스텝의 시맨틱 키 — 있으면 422 `unknown_semantic_key`."""
        return sorted({step.semantic_key for step in self.steps if not self.ladder(step.semantic_key)})


class Failure(ContractModel):
    """사다리가 모두 실패했다 — 치유 요청에 싣는다."""

    tried: list[str] = Field(default_factory=list)  # locator_key들
    reasons: list[str] = Field(default_factory=list)
    url: str | None = None


class HealRequest(SchemaVersioned):
    """`POST /v1/ops/heal` — **사다리가 모두 실패했을 때만**."""

    SCHEMA: ClassVar[int] = 1

    page_id: str
    semantic_key: str
    description: str = ""
    role: str = ""
    #: 이 요소에 대한 치유 시도 번호 (1부터, 상한은 `policy.max_healing_attempts`).
    heal_attempt: int = 1
    failure: Failure = Field(default_factory=Failure)
    #: 접근성 스냅샷 (최대 32 KB) — **값은 가려서** 보낸다.
    aria_snapshot: str | None = None
    #: 실패 지점 주변 HTML (최대 16 KB) — 마찬가지.
    sub_dom: str | None = None


class HealResponse(ContractModel):
    """제안된 로케이터. **없을 수 있다** — 정상적인 분기다 (횟수는 Worker가 센다)."""

    locator: LocatorSpec | None = None
    reasoning: str = ""


#: 보고의 출처 — **`test`는 승격 통계에 넣지 않는다** (셀렉터 시험, BUI-08).
ORIGIN_RUN = "run"
ORIGIN_TEST = "test"

#: 보고의 결말 (열린 문자열).
STATUS_SUCCEEDED = "succeeded"
STATUS_ESCALATED = "escalated"
STATUS_FAILED = "failed"


class AttemptReport(ContractModel):
    """로케이터 하나를 시도한 결과 — 서버가 이것으로 통계를 갱신한다 (C8 §승격 규칙)."""

    semantic_key: str
    locator_key: str
    succeeded: bool
    elapsed_ms: int = 0
    matched_count: int | None = None
    failure_reason: str | None = None


class HealedReport(ContractModel):
    """치유로 찾아 **로컬 검증을 통과한** 로케이터 (그것만 보낸다)."""

    semantic_key: str
    locator: LocatorSpec
    heal_attempt: int = 1
    #: 이 로케이터가 밀어내는 것들 — 승격될 때 함께 `deprecated`가 된다.
    supersedes: list[str] = Field(default_factory=list)
    reasoning: str = ""


class Escalation(ContractModel):
    """사람에게 넘긴 자리 (UIA-03 「전환」). 서버는 **기록만** 한다."""

    semantic_key: str
    reason: str = ""
    attempts: int = 0
    url: str | None = None


class SessionReport(SchemaVersioned):
    """`POST /v1/ops/report` — UI 세션 하나의 최종 보고.

    **업무 값은 보내지 않는다.** 읽기 결과(`text`·`data`)는 들어가지 않는다 — 모니터링은
    진행·폴백·치유만 보면 된다 (원칙 6).
    """

    SCHEMA: ClassVar[int] = 1

    business_key: str
    page_id: str
    plan_id: str | None = None
    revision: int = 1
    origin: str = ORIGIN_RUN
    status: str = STATUS_SUCCEEDED
    steps_completed: int = 0
    steps_total: int = 0
    attempts: list[AttemptReport] = Field(default_factory=list)
    healed: list[HealedReport] = Field(default_factory=list)
    escalation: Escalation | None = None
    error: dict[str, str] | None = None
    duration_ms: int = 0


def masked(text: str, values: list[str]) -> str:
    """업무 값을 `•••`로 바꾼다 (원칙 6) — 구조와 라벨만 남긴다.

    **보내기 전에** 거친다. 입력칸의 값·입력한 글자·표 셀이 그대로 나가면 안 된다.
    """
    out = text
    for one in sorted((v for v in values if v), key=len, reverse=True):
        out = out.replace(one, MASK)
    return out


__all__ = [
    "ACTIVE",
    "ORIGIN_RUN",
    "ORIGIN_TEST",
    "STATUS_ESCALATED",
    "STATUS_FAILED",
    "STATUS_SUCCEEDED",
    "AttemptReport",
    "Escalation",
    "HealedReport",
    "SessionReport",
    "DEFAULT_PRIORITY",
    "DEPRECATED",
    "DESKTOP",
    "DESKTOP_STRATEGIES",
    "MASK",
    "UNVERIFIED",
    "WEB",
    "WEB_STRATEGIES",
    "ElementInfo",
    "ExecutionPlan",
    "Failure",
    "HealRequest",
    "HealResponse",
    "LocatorSpec",
    "PlanStep",
    "Policy",
    "masked",
]

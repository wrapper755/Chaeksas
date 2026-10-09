"""C9 §관리 콘솔이 읽는 길 — UI 자동화 앱 관리 콘솔(UIA-01~03)이 읽는 모양.

단일 원본: `docs/03-contracts/C9-ui-page-registry.md`.

**업무 호출과 권한이 다르다** — 이 길은 **관리자 토큰**으로만 열린다 (C11 관리 API와 같은
관문, `service_kit.admin_guard`). 콘솔은 서비스 앱 키를 갖지 않는다 (ADR-0013) — 그래서
셀렉터를 보는 `registry_write` 키 대신, 더 강한 관리자 토큰으로 읽는다.

**업무 값은 없다** (원칙 6). 들어오는 것은 셀렉터·통계·진행이고, 무엇을 입력했고 읽었는지는
C8 보고 자체에 없다.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp

#: 「배포 전 확인」 한 줄의 등급 (UIA-01). **열린 문자열이다** (원칙 10).
CHECK_OK = "ok"
CHECK_WARN = "warn"
KNOWN_CHECK_LEVELS = frozenset({CHECK_OK, CHECK_WARN})


class SelectorCounts(ContractModel):
    """「관리 중인 셀렉터」 (UIA-01) — 레지스트리를 센 것."""

    pages: int = 0
    elements: int = 0
    locators: int = 0
    active: int = 0
    unverified: int = 0
    deprecated: int = 0


class LlmInfo(ContractModel):
    """「LLM」 (UIA-01). **주소·키는 보이지 않는다** (C11 §모델 연결).

    계획과 치유가 **같은 모델 하나**를 쓴다 (앱 설정이 하나다) — 둘을 따로 적지 않는다.
    """

    configured: bool = False
    model: str = ""
    #: 마지막 호출 결과 (`ok`·`failed`·`unknown`). 부른 적이 없으면 `unknown`.
    last_status: str = "unknown"
    #: 계획에 실어 보내는 치유 한도 (C8 `Policy.max_healing_attempts`).
    max_healing_attempts: int = 3


class SessionCounts(ContractModel):
    """「최근 UI 세션」 (UIA-01)과 UIA-03 요약 — **보고가 도착한 것만** 센다.

    **「진행 중」은 없다.** C8 보고는 세션이 **끝날 때** 한 번 오므로 앱은 도는 세션을 모른다
    (지금 무엇이 도는지는 현장의 BUI-09가 안다). 없는 수를 0으로 보이면 「아무것도 안 돈다」로
    읽히므로 칸 자체를 두지 않는다.

    `test`는 셀렉터 시험(BUI-08, C8 `origin: test`)이고 **나머지 수에 들어가지 않는다** —
    시험이 운영 통계를 흔들지 않는다 (C8·C9).
    """

    total: int = 0
    succeeded: int = 0
    escalated: int = 0
    failed: int = 0
    healed: int = 0
    today: int = 0
    test: int = 0


class DeployCheck(ContractModel):
    """「배포 전 확인」 한 줄 (UIA-01).

    **C11 앱이 자기 힘으로 볼 수 있는 것만** 둔다 — 모델 연결, 등록 담당자 키(`registry_write`),
    등록된 화면. (허용 주소·인증 설정은 외부 확장 어댑터의 개념이고(C13 §4) 이 앱에는 없다.)

    **막는 것이 아니라 알려 주는 것이다** — `warn`이어도 앱은 돈다.
    """

    id: str
    label: str
    level: str = CHECK_OK  # KNOWN_CHECK_LEVELS
    detail: str | None = None


class LocatorRow(ContractModel):
    """UIA-02 표의 한 줄 — 로케이터 하나와 그 성적.

    **셀렉터(물리 정보)가 나간다** — 관리자 토큰으로만 오는 길이다 (C9 §관리 콘솔이 읽는 길).
    """

    semantic_key: str
    #: 사다리 순서 (`LocatorSpec.rank` — 적지 않으면 전략의 기본값).
    rank: int
    type: str
    value: str
    name: str | None = None
    control_type: str | None = None
    status: str = "unverified"
    success: int = 0
    fail: int = 0
    #: 성공률 (0.0~1.0). 센 적이 없으면 `None` — 0%와 다르다.
    success_rate: float | None = None
    streak: int = 0
    last_success_at: Timestamp | None = None
    #: 자가 치유가 더한 것인가 — **보고가 적어 둔 것**으로 안다 (레지스트리에는 표시가 없다).
    healed: bool = False
    #: 이 로케이터가 밀어낸 것들 (치유 보고의 `supersedes`).
    supersedes: list[str] = Field(default_factory=list)


class ElementRow(ContractModel):
    """UIA-02 「선행 조건·화면 이동」 한 줄 — 요소 하나가 아는 것 (C9 `catalog`·`elements`)."""

    semantic_key: str
    name: str | None = None
    role: str | None = None
    description: str | None = None
    kind: str | None = None
    actions: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    navigates_to: str | None = None


class StrategyStat(ContractModel):
    """UIA-02 「전략별 성공·실패」 — 전략 하나의 합."""

    type: str
    success: int = 0
    fail: int = 0


class PageDetail(SchemaVersioned):
    """`GET /admin/v1/pages/{page_id}` — UIA-02 화면 하나 (대체된 것 포함)."""

    page_id: str
    name: str = ""
    platform: str = "web"
    revision: int = 1
    updated_at: Timestamp | None = None
    url_pattern: str | None = None
    app: str | None = None
    locators: list[LocatorRow] = Field(default_factory=list)
    elements: list[ElementRow] = Field(default_factory=list)
    strategies: list[StrategyStat] = Field(default_factory=list)
    #: 최근 실패율이 높은 `active` 로케이터 (C8 강등 규칙 — **경고만**).
    warnings: list[str] = Field(default_factory=list)


class PageBriefRow(ContractModel):
    """UIA-02 화면 고르기 한 줄 (C9 `PageBrief`와 같은 칸)."""

    page_id: str
    name: str = ""
    platform: str = "web"
    element_count: int = 0
    revision: int = 1
    updated_at: Timestamp | None = None


class PageListing(SchemaVersioned):
    """`GET /admin/v1/pages` — 화면 고르기 목록."""

    pages: list[PageBriefRow] = Field(default_factory=list)


class PathResult(SchemaVersioned):
    """`GET /admin/v1/path?start=&goal=` — UIA-02 「화면 간 경로 탐색」.

    간선은 요소의 `navigates_to`이고 **최단 하나**를 앱이 너비 우선으로 찾는다 (ADR-0040 —
    SQL에 밀어 넣지 않는다). 길이 없으면 `found: false`이고 **지어내지 않는다**.
    """

    start: str
    goal: str
    #: 출발부터 도착까지의 화면 id들. 길이 없으면 비어 있다.
    path: list[str] = Field(default_factory=list)
    found: bool = False


class SessionRow(SchemaVersioned):
    """UIA-03 「UI 세션 이력」 한 줄 — 보고 하나와 **봉투가 말해 준 것**.

    `caller`·`mode`·`bpm_process_id`·`host`는 C8 보고에 없다 — C11 호출 봉투
    (`OpRequest.caller`·`mode`)에서 함께 적어 둔 것이다.
    """

    at: Timestamp | None = None
    #: 요청한 쪽 (C11 `caller.type` — `bot_ui`·`studio`·`worker`).
    caller: str = ""
    #: 수행 모드 (C11 `mode`). **받는 쪽은 바꾸지 않는다** (원칙 7).
    mode: str = ""
    #: 어느 Bot이었나 (C11 `caller.bpm_process_id`).
    bpm_process_id: str | None = None
    #: 어느 PC였나 (C11 `caller.host`).
    host: str | None = None
    report: dict[str, Any] = Field(default_factory=dict)


class FallbackSpread(ContractModel):
    """UIA-03 「폴백 깊이 분포」 — 요소 하나를 찾기까지 사다리를 몇 칸 내려갔나.

    `attempts`에서 센다 (C8 보고). 열쇠는 깊이(글자)이고 값은 건수다 — `0`이 **1순위
    로케이터로 바로 성공**한 것이다.
    """

    depths: dict[str, int] = Field(default_factory=dict)
    #: 깊이 0으로 성공한 수와 센 전체 (비율은 보는 쪽이 만든다).
    first_hit: int = 0
    counted: int = 0


class SessionPage(SchemaVersioned):
    """`GET /admin/v1/sessions?limit=` — UIA-03 한 벌 (요약 + 이력 + 폴백 분포)."""

    rows: list[SessionRow] = Field(default_factory=list)
    counts: SessionCounts = Field(default_factory=lambda: SessionCounts())
    fallback: FallbackSpread = Field(default_factory=FallbackSpread)


class ConsoleOverview(SchemaVersioned):
    """`GET /admin/v1/overview` — UIA-01 개요 한 벌."""

    counts: SelectorCounts = Field(default_factory=SelectorCounts)
    llm: LlmInfo = Field(default_factory=LlmInfo)
    sessions: SessionCounts = Field(default_factory=SessionCounts)
    checks: list[DeployCheck] = Field(default_factory=list)
    #: 레지스트리 판 (C9) — 바뀔 때만 오른다.
    revision: int = 1
    generated_at: Timestamp | None = None


__all__ = [
    "CHECK_OK",
    "CHECK_WARN",
    "KNOWN_CHECK_LEVELS",
    "ConsoleOverview",
    "DeployCheck",
    "ElementRow",
    "FallbackSpread",
    "LlmInfo",
    "LocatorRow",
    "PageBriefRow",
    "PageDetail",
    "PageListing",
    "PathResult",
    "SelectorCounts",
    "SessionCounts",
    "SessionPage",
    "SessionRow",
    "StrategyStat",
]

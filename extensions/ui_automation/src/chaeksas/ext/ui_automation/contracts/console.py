"""C9 §관리 콘솔이 읽는 길 — UI 자동화 앱 관리 콘솔(UIA-01~03)이 읽는 모양.

단일 원본: `docs/03-contracts/C9-ui-page-registry.md`.

**업무 호출과 권한이 다르다** — 이 길은 **관리자 토큰**으로만 열린다 (C11 관리 API와 같은
관문, `service_kit.admin_guard`). 콘솔은 서비스 앱 키를 갖지 않는다 (ADR-0013) — 그래서
셀렉터를 보는 `registry_write` 키 대신, 더 강한 관리자 토큰으로 읽는다.

**업무 값은 없다** (원칙 6). 들어오는 것은 셀렉터·통계·진행이고, 무엇을 입력했고 읽었는지는
C8 보고 자체에 없다.
"""

from __future__ import annotations

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
    "LlmInfo",
    "SelectorCounts",
    "SessionCounts",
]

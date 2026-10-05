"""로케이터 사다리와 치유 — **Worker가 로컬에서 돈다** (C8).

폴백 도중에는 **네트워크를 타지 않는다.** 계획에 사다리 전부가 실려 내려오므로, 안정한
로케이터부터 차례로 시도하고 다 실패했을 때만 치유를 한 번 부른다.

- **`deprecated`는 시도하지 않는다.** 안정한 것부터(우선순위) 간다.
- **정확히 하나에 맞아야 한다** (`require_unique_match`) — 둘 이상 맞으면 엉뚱한 것을 누른다.
- **치유가 제안한 것도 그대로 믿지 않는다.** 지금 화면에서 하나에 맞는지 확인한 뒤에 쓴다.
- 한도를 넘으면 **전환**(escalation)이다 — 실패가 아니라 **사람에게 넘길 거리**다.
- **업무 값을 치유 요청에 싣지 않는다** (원칙 6) — 스냅샷은 가려서 보낸다.

여기서는 **화면을 모른다.** 찾기와 조작은 `Finder`가 한다 (브라우저·Windows UIA).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from chaeksas.ext.ui_automation.contracts.plan import (
    ExecutionPlan,
    Failure,
    HealRequest,
    HealResponse,
    LocatorSpec,
    PlanStep,
    Policy,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableRead:
    """표 읽기 (`read_table`) — 칸은 **보이는 글 그대로**다. 첫 줄이 머리글이다 (C10 `data`).

    사전 목록으로 바꾸고 수 규칙을 쓰는 일은 부르는 쪽이 한다 (ADR-0036).
    """

    rows: tuple[tuple[str, ...], ...]

    @property
    def text(self) -> str:
        """사람이 읽는 형태 (C10 `text` — TSV)."""
        return "\n".join("\t".join(row) for row in self.rows)

    def data(self) -> dict[str, Any]:
        return {
            "headers": list(self.rows[0]) if self.rows else [],
            "rows": [list(row) for row in self.rows[1:]],
        }


@dataclass(frozen=True)
class Match:
    """로케이터 하나로 찾아본 결과. **몇 개 맞았는지**가 중요하다."""

    count: int = 0
    handle: object | None = None
    error: str = ""

    @property
    def unique(self) -> bool:
        return self.count == 1


class Finder(Protocol):
    """화면에서 찾고 조작하는 쪽 (브라우저·Windows UIA).

    **여기가 바깥 세계다.** 사다리는 이 인터페이스만 보고 돈다 — 그래서 화면 없이 시험한다.
    """

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match: ...

    def act(self, handle: object, step: PlanStep, *, timeout_ms: int) -> str | TableRead | None:
        """조작하거나 읽는다. 읽기면 글을, 표 읽기면 `TableRead`를 돌려준다."""
        ...

    def snapshot(self) -> tuple[str, str]:
        """치유에 보낼 `(aria_snapshot, sub_dom)` — **값은 이미 가려져 있어야 한다**."""
        ...

    def url(self) -> str: ...


#: 치유를 부르는 길 (C8 `POST /v1/ops/heal`). 닿지 못하면 `None`을 돌려준다.
Healer = Callable[[HealRequest], HealResponse | None]


@dataclass
class Attempt:
    """스텝 하나를 수행한 결과 — 보고(C8)와 C3 `ui_session`이 이것을 센다."""

    ok: bool = False
    semantic_key: str = ""
    action: str = ""
    text: str | None = None
    #: 읽기 결과 구조 (C10 `data` — 표면 `{headers, rows}`). **보고에는 싣지 않는다.**
    data: dict[str, Any] | None = None
    #: 몇 번째 로케이터로 성공했나. **0이 건강한 상태**다.
    fallback_depth: int = 0
    healed: bool = False
    #: 사다리도 치유도 안 됐다 — **사람에게 넘긴다** (오류와 구분한다).
    escalated: bool = False
    error_code: str | None = None
    error: str | None = None
    duration_ms: int = 0
    #: 시도한 로케이터 열쇠들 (보고에 싣는다).
    tried: list[str] = field(default_factory=list)
    #: 치유가 제안해서 실제로 쓴 로케이터.
    used: LocatorSpec | None = None


def run_step(
    step: PlanStep,
    plan: ExecutionPlan,
    finder: Finder,
    *,
    heal: Healer | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Attempt:
    """스텝 하나 — 사다리를 타고, 다 실패하면 치유를 부른다 (C8).

    치유는 **한 스텝에 `max_healing_attempts`번까지**다. 그 뒤는 전환이다.
    """
    started = clock()
    found = Attempt(semantic_key=step.semantic_key, action=step.action)
    policy = plan.policy
    ladder = plan.ladder(step.semantic_key)

    if not ladder:
        # 계획에 사다리가 없다 — 그림·레지스트리가 어긋난 것이다 (C8: 422와 같은 뜻).
        found.error_code = "unknown_semantic_key"
        found.error = f"사다리가 없는 요소다: {step.semantic_key}"
        found.duration_ms = _ms(clock() - started)
        return found

    match, depth, reasons = _climb(ladder, finder, policy, found)
    if match is None:
        match, depth = _heal(step, plan, finder, heal, found, policy, reasons)

    if match is None:
        found.escalated = True
        found.error_code = found.error_code or "element_not_found"
        found.error = found.error or "사다리와 치유가 모두 맞지 않았다"
        found.duration_ms = _ms(clock() - started)
        return found

    found.fallback_depth = depth
    try:
        read = finder.act(match.handle, step, timeout_ms=policy.action_timeout_ms)
        if isinstance(read, TableRead):
            found.text, found.data = read.text, read.data()
        else:
            found.text = read
    except Exception as e:  # noqa: BLE001 — 화면이 무엇을 낼지 모른다
        found.error_code = "action_failed"
        found.error = f"{type(e).__name__}: {e}"
        found.duration_ms = _ms(clock() - started)
        return found

    found.ok = True
    found.duration_ms = _ms(clock() - started)
    return found


def _climb(
    ladder: list[LocatorSpec], finder: Finder, policy: Policy, found: Attempt
) -> tuple[Match | None, int, list[str]]:
    """사다리를 안정한 것부터 탄다. **정확히 하나**에 맞아야 쓴다."""
    reasons: list[str] = []
    for depth, locator in enumerate(ladder):
        found.tried.append(locator.key)
        match = finder.find(locator, timeout_ms=locator.timeout_ms or policy.locator_timeout_ms)
        if match.unique:
            return match, depth, reasons
        if match.count > 1 and not policy.require_unique_match:
            # 여러 개여도 된다고 정책이 말하면 첫 번째를 쓴다 (기본은 쓰지 않는다).
            return match, depth, reasons
        reasons.append(
            f"{locator.key}: {match.error or ('여러 개 맞았다' if match.count > 1 else '못 찾았다')}"
        )
    return None, 0, reasons


def _heal(
    step: PlanStep,
    plan: ExecutionPlan,
    finder: Finder,
    heal: Healer | None,
    found: Attempt,
    policy: Policy,
    reasons: list[str],
) -> tuple[Match | None, int]:
    """사다리가 다 실패했다 — 치유를 부른다. **제안도 확인한 뒤에 쓴다**."""
    if heal is None:
        return None, 0
    info = plan.elements.get(step.semantic_key)
    for attempt in range(1, policy.max_healing_attempts + 1):
        aria, sub_dom = finder.snapshot()
        asked = HealRequest(
            schema=1,
            page_id=plan.page_id,
            semantic_key=step.semantic_key,
            description=info.description if info else "",
            role=info.role if info else "",
            heal_attempt=attempt,
            failure=Failure(tried=list(found.tried), reasons=reasons, url=finder.url()),
            aria_snapshot=aria,
            sub_dom=sub_dom,
        )
        answer = heal(asked)
        if answer is None:
            # 닿지 못했다 — 더 물어도 소용없다 (C8: 앱이 없으면 캐시도 없다).
            found.error_code = "ui_automation_unreachable"
            return None, 0
        if answer.locator is None:
            continue  # **정상적인 분기다** — 제안할 것이 없다
        found.tried.append(answer.locator.key)
        match = finder.find(
            answer.locator, timeout_ms=answer.locator.timeout_ms or policy.locator_timeout_ms
        )
        if match.unique:
            found.healed = True
            found.used = answer.locator
            # 치유로 찾은 것은 사다리 **끝 다음**이다 (0이 건강한 상태라는 뜻을 지킨다).
            return match, len(plan.ladder(step.semantic_key))
        reasons.append(f"{answer.locator.key}: 치유 제안이 맞지 않았다")
    return None, 0


def _ms(seconds: float) -> int:
    return int(seconds * 1000)


__all__ = ["Attempt", "Finder", "Healer", "Match", "TableRead", "run_step"]

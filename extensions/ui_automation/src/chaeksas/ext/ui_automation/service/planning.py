"""목표로 계획 — 목표 한 줄로 스텝을 모델에게 세우게 하고 **거른다** (C8 「목표로 계획」, ADR-0035).

- 재료는 그 화면의 **시맨틱 정보**뿐이다 (키·이름·설명·역할·할 수 있는 동작·선행 입력). 스냅샷은
  없다 — 계획은 세션을 열 때, 화면을 보기 전에 세운다.
- 모델은 **값의 이름만** 본다 (`values`). 스텝 값은 `{이름}` 템플릿이고 수행기가 채운다 (원칙 6).
- 하나라도 어긋나면 `GoalPlanInvalid` → 422 `goal_plan_invalid`. 화면에 손대기 전에 멈춘다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import PlanStep
from chaeksas.ext.ui_automation.contracts.registry import PageRegistration
from chaeksas.ext.ui_automation.contracts.worker_local import (
    KNOWN_ACTIONS,
    MUTATING_ACTIONS,
    READING_ACTIONS,
    StepRequest,
    check_step,
)

#: 한 계획의 스텝 수 상한 (C8).
MAX_STEPS = 30
#: 템플릿 하나 — 수행기의 채우기와 같은 모양 (`{{`·`}}`는 중괄호 글자).
TEMPLATE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")

SYSTEM = """너는 UI 자동화의 계획 도우미다. 한 화면에서 목표를 이루는 스텝을 세운다.

규칙:
- 아래 「요소」에 있는 semantic_key만 쓴다. 셀렉터는 모른다.
- 동작은 {actions} 중 하나이고, 요소에 「할 수 있는 동작」이 적혀 있으면 그 안에서만 고른다.
- fill·press·select는 value가 있어야 하고 click은 value가 없다. 읽기 동작(read…)도 value가 없다.
- 값은 「쓸 값」의 이름을 {{이름}} 모양으로 넣거나, 목표에 글자로 적힌 것을 쓴다. 값을 지어내지 않는다.
- 읽은 값은 「결과 변수」 이름 중 하나를 result로 단다. 결과 변수가 없으면 result를 달지 않는다.
- 「선행 입력」이 있는 요소는 그것을 먼저 채운다.
- 스텝은 1개 이상 {max_steps}개 이하.

답은 JSON 하나만, 설명 없이:
{{"steps": [{{"semantic_key": "...", "action": "...", "value": "...", "result": "..."}}]}}"""


class GoalPlanInvalid(ValueError):
    """모델이 세운 계획이 거르기에 걸렸다 — C8 422 `goal_plan_invalid`."""

    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


def messages_for(
    goal: str, page: PageRegistration, values: Sequence[str], results: Sequence[str]
) -> list[dict[str, Any]]:
    """모델에게 갈 물음 — **시맨틱 정보 + 이름**뿐이다 (값도 셀렉터도 없다)."""
    elements = []
    for key in sorted(page.locators):
        hint = page.elements.get(key)
        catalog = page.catalog.get(key)
        one: dict[str, Any] = {"semantic_key": key}
        if hint is not None:
            one |= {"name": hint.name, "description": hint.description, "role": hint.role, "kind": hint.kind}
        if catalog is not None:
            if catalog.actions:
                one["actions"] = catalog.actions
            if catalog.depends_on:
                one["depends_on"] = catalog.depends_on
        elements.append({k: v for k, v in one.items() if v not in ("", [], None)})
    body = {
        "goal": goal,
        "page": {"page_id": page.page_id, "name": page.name, "platform": page.platform},
        "elements": elements,
        "values": list(values),
        "results": list(results),
    }
    system = SYSTEM.format(actions=", ".join(sorted(KNOWN_ACTIONS)), max_steps=MAX_STEPS)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, indent=1)},
    ]


def _json_object(text: str) -> Mapping[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1)
    found = json.loads(cleaned)
    if not isinstance(found, dict):
        raise ValueError("JSON 객체가 아니다")
    return found


def names_in(value: Any) -> list[str]:
    """값 안의 `{이름}`들 — 앞부분(변수 이름)과 경로 전체를 함께 본다."""
    if not isinstance(value, str):
        return []
    return [match.group(1).strip() for match in TEMPLATE.finditer(value) if match.group(1) is not None]


def _allowed(name: str, values: Sequence[str]) -> bool:
    """`{신청.이름}`은 `신청.이름`이나 `신청`이 허락됐으면 된다. 허락된 `신청.이름` 아래로 더 내려가도 된다."""
    return any(name == one or name.startswith(one + ".") for one in values)


def steps_from(
    text: str, page: PageRegistration, values: Sequence[str], results: Sequence[str]
) -> list[PlanStep]:
    """모델 답을 **걸러서** 스텝으로. 하나라도 어긋나면 `GoalPlanInvalid`(이유 전부)."""
    try:
        found = _json_object(text)
    except ValueError as e:
        raise GoalPlanInvalid(["모델 답이 JSON이 아니다"]) from e
    raw_steps = found.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise GoalPlanInvalid(["스텝이 없다"])
    if len(raw_steps) > MAX_STEPS:
        raise GoalPlanInvalid([f"스텝이 {MAX_STEPS}개를 넘는다 ({len(raw_steps)}개)"])

    reasons: list[str] = []
    steps: list[PlanStep] = []
    for number, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            reasons.append(f"{number}번: 객체가 아니다")
            continue
        key = str(raw.get("semantic_key") or "")
        action = str(raw.get("action") or "")
        value = raw.get("value")
        value = None if value in ("", None) else value
        result = raw.get("result") or None
        where = f"{number}번({key or '?'})"
        if key not in page.locators:
            reasons.append(f"{where}: 이 화면에 등록되지 않은 요소다")
            continue
        if action not in KNOWN_ACTIONS:
            reasons.append(f"{where}: 모르는 동작이다 ({action})")
            continue
        catalog = page.catalog.get(key)
        if catalog is not None and catalog.actions and action not in catalog.actions:
            reasons.append(f"{where}: 이 요소가 할 수 없는 동작이다 ({action})")
            continue
        if action == "click" and value is not None:
            reasons.append(f"{where}: click에는 값이 없다")
            continue
        problem = check_step(StepRequest(semantic_key=key, action=action, value=value), deterministic=False)
        if problem is not None:
            reasons.append(f"{where}: 값 규칙에 맞지 않는다 ({problem})")
            continue
        unknown = [name for name in names_in(value) if not _allowed(name, values)]
        if unknown:
            reasons.append(f"{where}: 쓸 값에 없는 이름이다 ({', '.join(unknown)})")
            continue
        if result is not None:
            if action not in READING_ACTIONS:
                reasons.append(f"{where}: 읽기 스텝이 아닌데 결과 변수를 달았다")
                continue
            if str(result) not in results:
                reasons.append(f"{where}: 결과 변수에 없는 이름이다 ({result})")
                continue
        if action in MUTATING_ACTIONS or action in READING_ACTIONS:
            steps.append(
                PlanStep(semantic_key=key, action=action, value=value, result=str(result) if result else None)
            )
    if reasons:
        raise GoalPlanInvalid(reasons)
    return steps


__all__ = ["MAX_STEPS", "GoalPlanInvalid", "messages_for", "names_in", "steps_from"]

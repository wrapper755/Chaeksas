"""치유 — 사다리가 모두 실패한 요소의 대체 로케이터를 모델에게 묻는다 (C8 `heal`, ADR-0034).

**모델의 답을 그대로 넘기지 않는다.** JSON이 아니거나, 화면에 없는 전략이거나, 이미 실패한
것이면 `locator: null`과 이유를 돌려준다 — 정상적인 분기다 (Worker가 다음 시도로 넘어간다).
남은 제안도 Worker가 **지금 화면에서 정확히 하나**에 맞는지 본 뒤에야 쓴다 (C8).

모델에게 가는 화면은 Worker가 **가린 것**뿐이다 (원칙 6). 셀렉터는 이 앱 안에서만 오간다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import (
    DESKTOP,
    DESKTOP_STRATEGIES,
    UNVERIFIED,
    WEB_STRATEGIES,
    HealRequest,
    HealResponse,
    LocatorSpec,
)
from chaeksas.ext.ui_automation.contracts.registry import PageRegistration

#: 스냅샷 상한 (C8 — 넘으면 413 `snapshot_too_large`).
ARIA_MAX = 32 * 1024
SUB_DOM_MAX = 16 * 1024
#: 모델이 쓴 이유를 이만큼에서 자른다 (C8).
REASONING_MAX = 400

#: 모델 답에서 받는 칸 — 나머지(`status`·`priority`·`platform`)는 앱이 정한다.
ACCEPTED_FIELDS = ("type", "value", "name", "exact", "control_type")

SYSTEM = """너는 UI 자동화의 치유 도우미다. 화면에서 요소 하나를 찾던 로케이터가 모두 실패했다.
화면 스냅샷을 보고 그 요소를 **정확히 하나** 가리키는 로케이터를 하나만 제안하라.

규칙:
- 쓸 수 있는 전략만 쓴다: {strategies}.
- `role` 전략이면 `value`는 ARIA role, `name`은 접근성 이름이고 `name`은 반드시 적는다.
- 데스크톱이면 `control_type`(UIA 이름, 예: Edit·Button·ComboBox)으로 좁힐 수 있다.
- 이미 실패한 로케이터는 다시 내지 않는다.
- 스냅샷의 `•••`는 가린 업무 값이다. 그것으로 찾지 않는다.
- 확신이 없으면 제안하지 않는다 (`locator`를 null로).

답은 JSON 하나만, 설명 없이:
{{"locator": {{"type": "...", "value": "...", "name": "..."}} 또는 null, "reasoning": "한두 문장"}}"""


class SnapshotTooLarge(ValueError):
    """C8 413 `snapshot_too_large` — Worker가 잘라서 다시 보낸다."""


def strategies_for(platform: str) -> tuple[str, ...]:
    return DESKTOP_STRATEGIES if platform == DESKTOP else WEB_STRATEGIES


def check_size(request: HealRequest) -> None:
    for name, text, limit in (
        ("aria_snapshot", request.aria_snapshot, ARIA_MAX),
        ("sub_dom", request.sub_dom, SUB_DOM_MAX),
    ):
        if text and len(text.encode("utf-8")) > limit:
            raise SnapshotTooLarge(f"{name}이 {limit // 1024} KB를 넘는다")


def messages_for(request: HealRequest, page: PageRegistration) -> list[dict[str, Any]]:
    """모델에게 갈 물음 (C8 「앱이 모델에게 묻는 것」). **시맨틱 정보 + 가린 화면**뿐이다."""
    hint = page.elements.get(request.semantic_key)
    ladder = page.locators.get(request.semantic_key, [])
    tried = sorted({*request.failure.tried, *(one.key for one in ladder)})
    element = {
        "semantic_key": request.semantic_key,
        "description": request.description or (hint.description if hint else "") or "",
        "role": request.role or (hint.role if hint else "") or "",
        "name": hint.name if hint else "",
    }
    body = {
        "page_id": page.page_id,
        "platform": page.platform,
        "element": element,
        "failed_locators": tried,
        "failure_reasons": request.failure.reasons,
        "url": request.failure.url,
        "heal_attempt": request.heal_attempt,
    }
    parts = [json.dumps(body, ensure_ascii=False, indent=1)]
    if request.aria_snapshot:
        parts.append("화면 스냅샷:\n" + request.aria_snapshot)
    if request.sub_dom:
        parts.append("실패 지점 주변:\n" + request.sub_dom)
    return [
        {"role": "system", "content": SYSTEM.format(strategies=", ".join(strategies_for(page.platform)))},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _json_object(text: str) -> Mapping[str, Any]:
    """답에서 JSON 객체 하나를 꺼낸다. 코드 울타리(```json)를 둘러도 받는다."""
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1)
    found = json.loads(cleaned)
    if not isinstance(found, dict):
        raise ValueError("JSON 객체가 아니다")
    return found


def _none(why: str) -> HealResponse:
    return HealResponse(locator=None, reasoning=why[:REASONING_MAX])


def answer_from(text: str, request: HealRequest, page: PageRegistration) -> HealResponse:
    """모델 답을 **걸러서** C8 응답으로. 쓸 수 없는 제안은 `null`과 이유가 된다."""
    try:
        found = _json_object(text)
    except ValueError:
        return _none("제안을 쓸 수 없었다: 모델 답이 JSON이 아니다")
    reasoning = str(found.get("reasoning") or "")[:REASONING_MAX]
    raw = found.get("locator")
    if raw is None:
        return HealResponse(locator=None, reasoning=reasoning)
    if not isinstance(raw, dict):
        return _none("제안을 쓸 수 없었다: locator가 객체가 아니다")

    picked = {name: raw[name] for name in ACCEPTED_FIELDS if raw.get(name) not in (None, "")}
    try:
        locator = LocatorSpec(**picked, status=UNVERIFIED, platform=page.platform)
    except (TypeError, ValueError):
        return _none("제안을 쓸 수 없었다: 로케이터 모양이 계약과 다르다")
    if locator.type not in strategies_for(page.platform):
        return _none(f"제안을 쓸 수 없었다: 이 화면({page.platform})에 없는 전략이다 ({locator.type})")
    if locator.type == "role" and not locator.name:
        return _none("제안을 쓸 수 없었다: role 전략인데 이름이 없다")
    known = {*request.failure.tried, *(one.key for one in page.locators.get(request.semantic_key, []))}
    if locator.key in known:
        return _none("제안을 쓸 수 없었다: 이미 실패했거나 사다리에 있는 로케이터다")
    return HealResponse(locator=locator, reasoning=reasoning)


__all__ = [
    "ARIA_MAX",
    "REASONING_MAX",
    "SUB_DOM_MAX",
    "SnapshotTooLarge",
    "answer_from",
    "check_size",
    "messages_for",
    "strategies_for",
]

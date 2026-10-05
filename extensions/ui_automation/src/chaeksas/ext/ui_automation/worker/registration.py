"""셀렉터 등록 — 화면을 분석하고 사다리를 검증한다 (C10 §5, BUI-06).

Worker가 **브라우저 일만** 한다. 레지스트리에 쓰는 것은 Bot UI 유틸리티가 직접 한다 (C9) —
Worker는 레지스트리를 모른다.

- **범위가 아무것도 못 찾으면 전체로 몰래 넓히지 않는다** (BUI-06 2번) — 그렇게 넓히면
  사람이 범위를 잘못 적은 것을 끝내 모른다.
- **잘렸으면 잘렸다고 말한다** — 조용히 자르면 없는 것을 없다고 단정한다.
- 검증은 **지금 열린 화면에서** 사다리 전체를 시험한다. 하나에 맞아야 통과다.
"""

from __future__ import annotations

import logging
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registration import (
    MAX_MAX,
    MIN_MAX,
    AnalyzeRequest,
    AnalyzeResult,
    Candidate,
    CheckRow,
    VerifyResult,
    actions_for,
    kind_for,
    suggest_key,
)

log = logging.getLogger(__name__)

#: 조작할 수 있는 것들 (`include_read`가 꺼져 있으면 이것만 가져온다).
CONTROL_SELECTOR = (
    "input:not([type=hidden]), textarea, select, button, "
    "a[href], [role=button], [role=textbox], [role=combobox], [role=checkbox], [role=radio]"
)
#: 읽기 대상까지 (`include_read`).
READ_SELECTOR = CONTROL_SELECTOR + ", table, [role=table], [role=grid], h1, h2, h3, [role=heading]"

#: 브라우저 안에서 요소 하나를 읽어 오는 코드. **셀렉터 후보도 여기서 만든다.**
COLLECT_JS = """
(element) => {
  const attr = (name) => element.getAttribute(name) || "";
  const css = [];
  if (element.id) css.push(`#${CSS.escape(element.id)}`);
  const name = attr("name");
  if (name) css.push(`${element.tagName.toLowerCase()}[name="${name}"]`);
  const classes = (element.getAttribute("class") || "").trim().split(/\\s+/).filter(Boolean);
  if (classes.length) css.push(`${element.tagName.toLowerCase()}.${classes.map(c => CSS.escape(c)).join(".")}`);
  return {
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute("role") || "",
    name: (element.getAttribute("aria-label") || element.innerText || attr("placeholder") || "").trim().slice(0, 120),
    element_id: element.id || "",
    field_name: name,
    test_id: attr("data-testid") || attr("data-test-id") || "",
    type: attr("type"),
    css,
  };
}
"""

#: 태그 → ARIA 역할 (역할 속성이 없을 때. 사다리의 `role` 전략이 이것을 쓴다).
ROLE_BY_TAG: dict[str, str] = {
    "button": "button",
    "a": "link",
    "select": "combobox",
    "textarea": "textbox",
    "table": "table",
    "h1": "heading",
    "h2": "heading",
    "h3": "heading",
}
ROLE_BY_INPUT_TYPE: dict[str, str] = {
    "checkbox": "checkbox",
    "radio": "radio",
    "button": "button",
    "submit": "button",
    "search": "searchbox",
}


def analyze(page: Any, request: AnalyzeRequest) -> AnalyzeResult:
    """지금 열린 화면에서 요소 후보를 모은다 (BUI-06 「분석」)."""
    wanted = READ_SELECTOR if request.include_read else CONTROL_SELECTOR
    limit = max(MIN_MAX, min(request.max, MAX_MAX))

    root = page.locator(request.scope_css) if request.scope_css else page
    if request.scope_css and root.count() == 0:
        # **전체로 몰래 넓히지 않는다** — 사람이 범위를 잘못 적은 것을 알아야 한다.
        return AnalyzeResult(scope_empty=True)

    found = (root.first if request.scope_css else page).locator(wanted)
    total = found.count()
    taken: set[str] = set()
    candidates = []
    for index in range(min(total, limit)):
        try:
            raw = found.nth(index).evaluate(COLLECT_JS)
        except Exception as e:  # noqa: BLE001 — 요소 하나가 사라져도 분석은 이어 간다
            log.debug("요소를 읽지 못했다 (%s): %s", index, e)
            continue
        one = _candidate(raw, taken)
        taken.add(one.suggested_key)
        candidates.append(one)

    return AnalyzeResult(candidates=candidates, total=total, truncated=total > limit)


def _candidate(raw: dict[str, Any], taken: set[str]) -> Candidate:
    tag = str(raw.get("tag") or "")
    role = str(raw.get("role") or "") or _role_of(tag, str(raw.get("type") or ""))
    made = Candidate(
        tag=tag,
        role=role,
        name=str(raw.get("name") or ""),
        element_id=str(raw.get("element_id") or ""),
        field_name=str(raw.get("field_name") or ""),
        test_id=str(raw.get("test_id") or ""),
        css=[str(one) for one in (raw.get("css") or [])],
        kind=kind_for(role, tag),
        actions=actions_for(role, tag),
    )
    return made.model_copy(update={"suggested_key": suggest_key(made, taken)})


def _role_of(tag: str, input_type: str) -> str:
    if tag == "input":
        return ROLE_BY_INPUT_TYPE.get(input_type, "textbox")
    return ROLE_BY_TAG.get(tag, "")


def verify(finder: Any, ladders: dict[str, list[LocatorSpec]], *, timeout_ms: int = 2000) -> VerifyResult:
    """사다리를 **지금 열린 화면에서** 시험한다 (BUI-06 「검증」).

    하나에 맞아야 통과다. 여럿이면 실패 — 실행에서 엉뚱한 것을 누른다.
    """
    rows = []
    for key in sorted(ladders):
        for rank, locator in enumerate(sorted(ladders[key], key=lambda one: one.rank)):
            match = finder.find(locator, timeout_ms=timeout_ms)
            rows.append(
                CheckRow(
                    semantic_key=key,
                    rank=rank,
                    strategy=locator.type,
                    selector=locator.value if not locator.name else f"{locator.value} ({locator.name})",
                    passed=match.unique,
                    matched=match.count,
                    reason=_why(match),
                )
            )
    return VerifyResult(rows=rows)


def _why(match: Any) -> str:
    if match.unique:
        return ""
    if match.error:
        return f"셀렉터가 깨졌다 ({match.error})"
    if match.count > 1:
        return f"{match.count}개가 잡힌다 — 모호해서 실패한다"
    return "못 찾았다"


def summarize(result: VerifyResult) -> str:
    """BUI-06 7번의 요약 한 줄. **막지는 않는다** — 사람이 보고 정한다."""
    if not result.rows:
        return "검증할 요소가 없습니다."
    if result.unreachable:
        return (
            f"잡히지 않는 요소가 있습니다 — {', '.join(result.unreachable)}. 자가 치유로 넘어갑니다."
        )
    if result.single:
        return (
            f"모두 잡힙니다 — 다만 {', '.join(result.single)}는 쓸 수 있는 로케이터가 하나뿐입니다."
        )
    return "모두 잡히고 대체 로케이터도 살아 있습니다. 등록해도 좋습니다."


__all__ = [
    "COLLECT_JS",
    "CONTROL_SELECTOR",
    "READ_SELECTOR",
    "ROLE_BY_INPUT_TYPE",
    "ROLE_BY_TAG",
    "analyze",
    "summarize",
    "verify",
]

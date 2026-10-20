"""셀렉터 등록 — 화면을 분석하고 사다리를 검증한다 (C10 §5, TOL-03).

Worker가 **브라우저 일만** 한다. 레지스트리에 쓰는 것은 셀렉터 등록 도구(Tool UI)가 직접 한다 (C9) —
Worker는 레지스트리를 모른다.

- **범위가 아무것도 못 찾으면 전체로 몰래 넓히지 않는다** (TOL-03 2번) — 그렇게 넓히면
  사람이 범위를 잘못 적은 것을 끝내 모른다.
- **잘렸으면 잘렸다고 말한다** — 조용히 자르면 없는 것을 없다고 단정한다.
- 검증은 **지금 열린 화면에서** 사다리 전체를 시험한다. 하나에 맞아야 통과다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import DESKTOP, LocatorSpec
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
    // 접근성 이름은 **브라우저가 짓는 대로** 어림한다 — 사다리의 「역할 + 이름」 칸이 이것으로 찾는다.
    // 내용(innerText)으로 이름을 짓는 것은 단추·링크·제목·칸 같은 요소뿐이다. 표처럼 글을 담은 그릇에
    // innerText를 쓰면 표 전체 글이 이름이 되어 그 칸이 늘 「못 찾았다」가 된다 (현장 리허설, 09-gaps §6).
    name: (() => {
      const labelled = attr("aria-label");
      if (labelled) return labelled;
      const by = attr("aria-labelledby");
      if (by) {
        const text = by.split(/\\s+/).map((id) => (document.getElementById(id) || {}).innerText || "").join(" ").trim();
        if (text) return text;
      }
      if (element.labels && element.labels.length) {
        const text = Array.from(element.labels).map((one) => one.innerText).join(" ").trim();
        if (text) return text;
      }
      if (element.tagName === "TABLE") return element.caption ? element.caption.innerText : "";
      const fromContent = [
        "BUTTON", "A", "OPTION", "SUMMARY", "LEGEND", "TH", "TD", "H1", "H2", "H3", "H4", "H5", "H6",
      ];
      const contentRoles = [
        "button", "link", "tab", "menuitem", "option", "heading", "cell", "columnheader", "rowheader",
      ];
      if (fromContent.includes(element.tagName) || contentRoles.includes(attr("role").toLowerCase())) {
        return element.innerText || "";
      }
      return attr("placeholder") || attr("title") || "";
    })().trim().slice(0, 120),
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


#: 읽기 대상인가 (테두리 색을 가른다 — 조작은 빨강, 읽기는 주황).
READ_KINDS_JS = "['table','grid','list','listbox','heading','paragraph','cell']"

#: 직접 고르기 (TOL-03 3번). 화면에 덧씌워 **누른 것을 담는다**.
#:
#: - **링크 이동과 폼 제출을 막는다** — 누르면 다른 화면으로 가 버린다.
#: - Shift+클릭은 둘러싼 표. Esc로 끝.
#: - 담은 것은 `window.__chk.picked`에 쌓이고 `pick/events`가 **비워 가져간다**.
PICK_JS = """
(collectSource) => {
  if (window.__chk && window.__chk.picking) return true;
  const collect = eval(collectSource);
  const readish = """ + READ_KINDS_JS + """;
  const state = { picking: true, picked: [], collect };
  window.__chk = state;

  const mark = (element, color) => {
    if (!element || !element.style) return;
    element.dataset.chkOutline = element.style.outline || "";
    element.style.outline = `2px solid ${color}`;
    element.style.outlineOffset = "1px";
  };
  const unmark = (element) => {
    if (!element || !element.style) return;
    element.style.outline = element.dataset.chkOutline || "";
    delete element.dataset.chkOutline;
  };
  const isRead = (element) => {
    const role = (element.getAttribute("role") || "").toLowerCase();
    const tag = element.tagName.toLowerCase();
    return readish.includes(role) || ["table", "ul", "ol", "h1", "h2", "h3", "td", "th", "p"].includes(tag);
  };

  let hovered = null;
  const over = (event) => {
    if (!state.picking) return;
    if (hovered) unmark(hovered);
    hovered = event.target;
    mark(hovered, isRead(hovered) ? "#e8810c" : "#d93025");
  };
  const out = () => { if (hovered) { unmark(hovered); hovered = null; } };

  const take = (event) => {
    if (!state.picking) return;
    // **이동·제출을 막는다** — 고르는 중에 화면이 바뀌면 담던 것이 날아간다.
    event.preventDefault();
    event.stopPropagation();
    let element = event.target;
    if (event.shiftKey) element = element.closest("table, [role=table], [role=grid]") || element;
    state.picked.push(state.collect(element));
  };
  const key = (event) => {
    if (event.key === "Escape") stop();
  };
  const stop = () => {
    state.picking = false;
    out();
    document.removeEventListener("mouseover", over, true);
    document.removeEventListener("mouseout", out, true);
    document.removeEventListener("click", take, true);
    document.removeEventListener("submit", take, true);
    document.removeEventListener("keydown", key, true);
  };
  state.stop = stop;

  document.addEventListener("mouseover", over, true);
  document.addEventListener("mouseout", out, true);
  document.addEventListener("click", take, true);
  document.addEventListener("keydown", key, true);
  return true;
}
"""

#: 담은 것을 **비워** 가져온다 (한 번 준 것은 다시 주지 않는다).
DRAIN_JS = """
() => {
  const state = window.__chk;
  if (!state) return { candidates: [], picking: false };
  const taken = state.picked;
  state.picked = [];
  return { candidates: taken, picking: !!state.picking };
}
"""

STOP_JS = """
() => {
  const state = window.__chk;
  if (state && state.stop) state.stop();
  return true;
}
"""

#: 표시 (TOL-03 5번) — 고른 줄을 **파란 테두리**로 잠깐 보인다.
HIGHLIGHT_JS = """
(selector) => {
  document.querySelectorAll("[data-chk-shown]").forEach((one) => {
    one.style.outline = one.dataset.chkShown === "-" ? "" : one.dataset.chkShown;
    delete one.dataset.chkShown;
  });
  const found = document.querySelectorAll(selector);
  found.forEach((one) => {
    one.dataset.chkShown = one.style.outline || "-";
    one.style.outline = "3px solid #1a73e8";
    one.style.outlineOffset = "1px";
  });
  if (found.length) found[0].scrollIntoView({ block: "center" });
  return found.length;
}
"""


def start_pick(page: Any) -> None:
    """직접 고르기를 켠다 (TOL-03 3번). **다시 켜도 두 번 걸리지 않는다**."""
    page.evaluate(PICK_JS, COLLECT_JS)


def drain_pick(page: Any) -> tuple[list[Candidate], bool]:
    """담은 것을 비워 가져온다. 두 번째 값은 **아직 고르는 중인가** (Esc로 끝났을 수 있다)."""
    raw = page.evaluate(DRAIN_JS)
    taken: set[str] = set()
    found = [_candidate(dict(one), taken) for one in (raw.get("candidates") or [])]
    for one in found:
        taken.add(one.suggested_key)
    return found, bool(raw.get("picking"))


def stop_pick(page: Any) -> None:
    page.evaluate(STOP_JS)


def highlight(page: Any, locators: list[LocatorSpec]) -> int:
    """사다리의 CSS로 화면에 표시한다 (TOL-03 5번) → 몇 개가 잡혔나.

    **하나가 아니면 그렇게 말한다** — 여럿이 잡히면 실행에서 엉뚱한 것을 누른다.
    """
    css = [one.value for one in locators if one.type == "css"]
    if not css:
        return 0
    return int(page.evaluate(HIGHLIGHT_JS, ", ".join(css)))


def analyze(page: Any, request: AnalyzeRequest) -> AnalyzeResult:
    """지금 열린 화면에서 요소 후보를 모은다 (TOL-03 「분석」)."""
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
    """사다리를 **지금 열린 화면에서** 시험한다 (TOL-03 「검증」).

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
    """TOL-03 7번의 요약 한 줄. **막지는 않는다** — 사람이 보고 정한다."""
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


# ─────────────────────────── 데스크톱 창에서 담기 (C10 §5, TOL-03) ───────────────────────────

#: UIA ControlTypeName → 역할. **조작 요소**는 늘, **읽기 대상**은 `include_read`일 때만 담는다.
DESKTOP_CONTROLS: dict[str, str] = {
    "EditControl": "textbox",
    "ButtonControl": "button",
    "ComboBoxControl": "combobox",
    "CheckBoxControl": "checkbox",
    "RadioButtonControl": "radio",
    "ListControl": "listbox",
    "HyperlinkControl": "link",
    "MenuItemControl": "menuitem",
}
DESKTOP_READS: dict[str, str] = {
    "TableControl": "table",
    "DataGridControl": "grid",
    "TextControl": "text",
}
#: 그 밑을 훑지 않는 컨트롤 — 창틀의 「최소화·최대화·닫기」는 앱의 요소가 아니다.
DESKTOP_SKIP = frozenset({"TitleBarControl", "ScrollBarControl"})
#: 훑는 깊이 (실행의 찾기와 같은 결 — 너무 깊은 트리는 자른다).
DESKTOP_DEPTH = 12


def desktop_candidates(
    controls: list[dict[str, str]], request: AnalyzeRequest, *, among: list[dict[str, str]] | None = None
) -> AnalyzeResult:
    """UIA 컨트롤 줄들 → 후보. **UIA를 모르는 순수 함수**다 (Linux CI에서도 시험한다).

    `controls`의 한 줄은 `{control_type, name, automation_id, class_name}`(ControlTypeName 그대로).
    **창 안에서 겹치는 값은 사다리에 넣지 않는다** — Qt 라벨들은 AutomationId(`…QLabel`)를 나눠 써서,
    그대로 두면 그 칸이 「여럿이 잡힌다」로 늘 실패한다. 겹치면 다음 전략(이름 + 종류)이 잡는다.
    """
    wanted = dict(DESKTOP_CONTROLS)
    if request.include_read:
        wanted.update(DESKTOP_READS)
    picked = [one for one in controls if one.get("control_type") in wanted]
    aid_count: dict[str, int] = {}
    class_count: dict[tuple[str, str], int] = {}
    # 겹침은 **창 전체**에서 센다 — 직접 고르기는 하나만 넘기므로 `among`(창의 모든 줄)을 준다.
    for one in among if among is not None else controls:
        aid = one.get("automation_id") or ""
        if aid:
            aid_count[aid] = aid_count.get(aid, 0) + 1
        key = (one.get("class_name") or "", one.get("control_type") or "")
        if key[0]:
            class_count[key] = class_count.get(key, 0) + 1

    limit = request.max
    taken: set[str] = set()
    candidates: list[Candidate] = []
    for one in picked[:limit]:
        control_type = one.get("control_type") or ""
        kind_name = control_type.removesuffix("Control")
        aid = one.get("automation_id") or ""
        class_name = one.get("class_name") or ""
        role = wanted[control_type]
        made = Candidate(
            tag=kind_name,
            role=role,
            name=one.get("name") or "",
            element_id=aid if aid_count.get(aid) == 1 else "",
            class_name=class_name if class_count.get((class_name, control_type)) == 1 else "",
            control_type=kind_name,
            platform=DESKTOP,
            kind=kind_for(role, ""),
            actions=actions_for(role, ""),
        )
        made = made.model_copy(update={"suggested_key": suggest_key(made, taken)})
        taken.add(made.suggested_key)
        candidates.append(made)
    return AnalyzeResult(candidates=candidates, total=len(picked), truncated=len(picked) > limit)


def desktop_controls(window: Any) -> list[dict[str, str]]:
    """붙은 창 하나의 UIA 트리를 줄로 — 창틀은 건너뛴다. **이것만 UIA를 안다.**"""
    out: list[dict[str, str]] = []

    def walk(control: Any, depth: int) -> None:
        if depth > DESKTOP_DEPTH:
            return
        for child in control.GetChildren():
            try:
                control_type = child.ControlTypeName or ""
                if control_type in DESKTOP_SKIP:
                    continue
                out.append(
                    {
                        "control_type": control_type,
                        "name": child.Name or "",
                        "automation_id": child.AutomationId or "",
                        "class_name": child.ClassName or "",
                    }
                )
            except Exception:  # noqa: BLE001 — 사라지는 중인 컨트롤
                continue
            walk(child, depth + 1)

    walk(window, 1)
    return out


@dataclass
class DesktopPick:
    """데스크톱 「직접 고르기」 한 번 (ADR-0072). **입력을 가로채지 않는다** — 읽기만 한다."""

    #: 켤 때 읽어 둔 창의 모든 컨트롤 줄 — 겹침을 「분석」과 **같은 규칙**으로 가른다.
    rows: list[dict[str, str]]
    #: 마지막으로 준 요소 — Ctrl을 누르고 있는 동안 같은 것을 두 번 주지 않는다.
    last: str = ""
    picking: bool = True


def row_of(control: Any) -> dict[str, str]:
    return {
        "control_type": control.ControlTypeName or "",
        "name": control.Name or "",
        "automation_id": control.AutomationId or "",
        "class_name": control.ClassName or "",
    }


def registrable(control: Any, window: Any, same: Any) -> Any:
    """커서 아래가 칸·틀이면 **위로 올라가** 등록할 만한 것을 찾는다. 붙은 창의 것이 아니면 없다.

    `same(a, b)`는 두 컨트롤이 같은가 (UIA `ControlsAreSame` — 시험이 바꿔 끼운다).
    """
    wanted = set(DESKTOP_CONTROLS) | set(DESKTOP_READS)
    seen: Any = control
    found: Any = None
    while seen is not None:
        if seen.ProcessId != window.ProcessId:
            return None
        if same(seen, window):
            return found
        if found is None and seen.ControlTypeName in wanted:
            found = seen
        seen = seen.GetParentControl()
    return None  # 창에 닿지 못했다 — 같은 프로세스의 다른 창이다


def desktop_drain(
    window: Any, state: DesktopPick, *, ctrl: bool, esc: bool, under_cursor: Any, same: Any
) -> tuple[list[Candidate], bool]:
    """「비워 가져오기」 한 번 — **Ctrl이 눌려 있을 때만** 커서 아래를 담는다. Esc면 끝낸다."""
    if esc:
        state.picking = False
    if not state.picking or not ctrl or under_cursor is None:
        if not ctrl:
            state.last = ""  # 뗐다 — 다음에 같은 것을 다시 담을 수 있다
        return [], state.picking
    found = registrable(under_cursor, window, same)
    if found is None:
        return [], True
    row = row_of(found)
    identity = "|".join(row.values())
    if identity == state.last:
        return [], True
    state.last = identity
    request = AnalyzeRequest(schema=1, include_read=True)
    return desktop_candidates([row], request, among=state.rows).candidates, True


def analyze_desktop(window: Any, request: AnalyzeRequest) -> AnalyzeResult:
    """TOL-03 「분석」(데스크톱). **창 하나가 범위다** — `scope_css`는 쓰지 않는다."""
    return desktop_candidates(desktop_controls(window), request)


__all__ = [
    "COLLECT_JS",
    "DESKTOP_CONTROLS",
    "DESKTOP_READS",
    "CONTROL_SELECTOR",
    "DRAIN_JS",
    "HIGHLIGHT_JS",
    "PICK_JS",
    "READ_SELECTOR",
    "ROLE_BY_INPUT_TYPE",
    "ROLE_BY_TAG",
    "STOP_JS",
    "analyze",
    "drain_pick",
    "highlight",
    "start_pick",
    "stop_pick",
    "summarize",
    "DesktopPick",
    "analyze_desktop",
    "desktop_drain",
    "registrable",
    "desktop_candidates",
    "desktop_controls",
    "verify",
]

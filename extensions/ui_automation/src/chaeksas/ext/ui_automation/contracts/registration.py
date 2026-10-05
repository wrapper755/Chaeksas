"""셀렉터 등록용 모양 (C10 §5).

**여기만 물리 정보(CSS 후보)가 나온다.** 다른 곳에서는 시맨틱 키만 경계를 넘는다 (C10) —
등록 화면은 사람이 셀렉터를 보고 고르는 자리라서 예외다.

- 시맨틱 키는 **자동 제안**하고 사람이 고친다 (BUI-06 4번). **한글 이름은 음역하지 않는다** —
  `고객명`을 `gogaegmyeong`으로 바꾸면 아무도 못 읽는다. 영문 단서가 없으면 역할로 짓는다.
- 사다리는 후보 하나에서 **안정한 순서로** 만든다 (C8 우선순위와 같다).
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec

#: 분석 한 번에 가져오는 요소 수 (BUI-06 「최대」 10~2000).
DEFAULT_MAX = 200
MIN_MAX = 10
MAX_MAX = 2000

#: 요소의 종류 (BUI-06 「종류」).
KIND_CONTROL = "control"
KIND_LIST = "list"
KIND_TABLE = "table"
KIND_TEXT = "text"

#: 시맨틱 키에 쓸 수 있는 글자 (C9) — 영소문자·숫자·`_`·`.`.
KEY_SAFE = re.compile(r"[^a-z0-9_.]+")

#: 역할 → 기본 동작 (BUI-06 「가능한 동작」).
ACTIONS_BY_ROLE: dict[str, list[str]] = {
    "textbox": ["fill", "read_selection"],
    "searchbox": ["fill", "read_selection"],
    "combobox": ["select", "read_options", "read_selection"],
    "listbox": ["select", "read_options"],
    "checkbox": ["click", "read_selection"],
    "radio": ["click"],
    "button": ["click"],
    "link": ["click"],
    "table": ["read_table"],
    "grid": ["read_table"],
    "list": ["read"],
    "heading": ["read"],
    "cell": ["read"],
}


class Candidate(ContractModel):
    """화면에서 찾은 요소 하나 (BUI-06 요소 표의 한 줄).

    **물리 정보가 들어 있다** — 등록 화면 전용이다 (C10 §5 예외).
    """

    tag: str = ""
    role: str = ""
    #: 접근성 이름 (사람이 읽는 이름).
    name: str = ""
    element_id: str = ""
    #: HTML `name` 속성 (서버로 보내는 칸 이름 — 사람이 지은 것이라 키로 쓸 만하다).
    field_name: str = ""
    test_id: str = ""
    #: CSS 후보 (안정한 순서로). 사람이 보고 고른다.
    css: list[str] = Field(default_factory=list)
    kind: str = KIND_CONTROL
    actions: list[str] = Field(default_factory=list)
    #: 제안된 시맨틱 키 — 사람이 고친다.
    suggested_key: str = ""


class AnalyzeRequest(SchemaVersioned):
    """`POST /v1/registration/{session_id}/analyze` (BUI-06 「분석」)."""

    SCHEMA: ClassVar[int] = 1

    scope_css: str | None = None
    max: int = DEFAULT_MAX
    include_read: bool = False


class AnalyzeResult(ContractModel):
    """분석 결과. **잘렸으면 잘렸다고 말한다** — 조용히 자르면 없는 것을 없다고 단정한다."""

    candidates: list[Candidate] = Field(default_factory=list)
    #: 범위 선택자가 찾은 전체 수 (잘리기 전).
    total: int = 0
    truncated: bool = False
    #: 범위가 아무것도 못 찾았다 — **전체로 몰래 넓히지 않는다** (BUI-06 2번).
    scope_empty: bool = False


class CheckRow(ContractModel):
    """검증 표 한 줄 (BUI-06 [V]) — 사다리 한 칸에 한 줄."""

    semantic_key: str
    rank: int
    strategy: str
    selector: str
    passed: bool = False
    reason: str = ""
    matched: int = 0


class VerifyResult(ContractModel):
    """검증 한 번. 요약 문구는 화면이 만든다 (BUI-06 7번)."""

    rows: list[CheckRow] = Field(default_factory=list)

    @property
    def unreachable(self) -> list[str]:
        """사다리가 **통째로** 안 잡히는 요소 — 자가 치유로 넘어간다."""
        by_key: dict[str, bool] = {}
        for row in self.rows:
            by_key[row.semantic_key] = by_key.get(row.semantic_key, False) or row.passed
        return sorted(key for key, ok in by_key.items() if not ok)

    @property
    def single(self) -> list[str]:
        """쓸 수 있는 로케이터가 **하나뿐인** 요소 — 하나 깨지면 바로 치유다."""
        counts: dict[str, int] = {}
        for row in self.rows:
            if row.passed:
                counts[row.semantic_key] = counts.get(row.semantic_key, 0) + 1
        return sorted(key for key, n in counts.items() if n == 1)


def english(text: str) -> bool:
    """영문 단서로 쓸 만한가 — **한글·한자가 섞이면 쓰지 않는다** (음역하지 않는다).

    문장 부호는 걸러 내면 될 일이라 막지 않는다 (`Customer Name!` → `customer_name`).
    """
    return text.isascii() and any(one.isalpha() for one in text)


def suggest_key(candidate: Candidate, taken: set[str]) -> str:
    """시맨틱 키를 제안한다 (BUI-06 4번) — `test_id` → `id` → `name` → 영문 이름 → 역할.

    **한글 이름은 음역하지 않는다.** `고객명`을 `gogaegmyeong`으로 바꾸면 사람도 기계도 못
    읽는다 — 그럴 바엔 역할로 짓고 사람이 고치게 한다.
    """
    for source in (candidate.test_id, candidate.element_id, candidate.field_name, candidate.name):
        if source and english(source):
            made = _slug(source)
            if made:
                return _unique(made, taken)
    base = _slug(candidate.role or candidate.tag or "element") or "element"
    return _unique(base, taken)


def _slug(text: str) -> str:
    found = KEY_SAFE.sub("_", text.strip().lower()).strip("_.")
    return found[:79]


def _unique(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    index = 2
    while f"{base}_{index}" in taken:
        index += 1
    return f"{base}_{index}"


def ladder_for(candidate: Candidate) -> list[LocatorSpec]:
    """후보 하나 → 사다리. **안정한 것부터** (C8 우선순위와 같다)."""
    out: list[LocatorSpec] = []
    if candidate.role and candidate.name:
        out.append(LocatorSpec(type="role", value=candidate.role, name=candidate.name, exact=True))
    if candidate.test_id:
        out.append(LocatorSpec(type="test_id", value=candidate.test_id))
    for css in candidate.css:
        out.append(LocatorSpec(type="css", value=css))
    return out


def actions_for(role: str, tag: str) -> list[str]:
    """그 요소로 할 수 있는 일 (BUI-06 「가능한 동작」)."""
    found = ACTIONS_BY_ROLE.get(role)
    if found is not None:
        return list(found)
    return ACTIONS_BY_ROLE.get(tag, ["read"])


def kind_for(role: str, tag: str) -> str:
    if role in ("table", "grid") or tag == "table":
        return KIND_TABLE
    if role in ("list", "listbox") or tag in ("ul", "ol", "select"):
        return KIND_LIST
    if role in ("heading", "paragraph", "cell") or tag in ("p", "span", "td", "th", "h1", "h2", "h3"):
        return KIND_TEXT
    return KIND_CONTROL


__all__ = [
    "ACTIONS_BY_ROLE",
    "DEFAULT_MAX",
    "KIND_CONTROL",
    "KIND_LIST",
    "KIND_TABLE",
    "KIND_TEXT",
    "MAX_MAX",
    "MIN_MAX",
    "AnalyzeRequest",
    "AnalyzeResult",
    "Candidate",
    "CheckRow",
    "VerifyResult",
    "actions_for",
    "english",
    "kind_for",
    "ladder_for",
    "suggest_key",
]

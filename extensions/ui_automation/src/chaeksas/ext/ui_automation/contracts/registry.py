"""C9. UI 화면 레지스트리 — **UI 자동화 확장이 소유한다** (ADR-0018).

단일 원본: `docs/03-contracts/C9-ui-page-registry.md`.

네 가지가 모델에 박혀 있다.

- **사다리 없는 정보는 받지 않는다** — `elements`·`catalog`의 키는 모두 `locators`에 있어야
  한다. 설명만 있고 찾을 수 없는 요소는 쓸모가 없다.
- **등록은 지우지 않는다.** 같은 요소에 로케이터를 **더한다**. 화면 개편은 재등록과
  `deprecated` 판정으로 한다.
- **새 로케이터는 `unverified`다.** 사람이 화면에서 검증했어도 그건 「그 순간 그 화면」에서만
  참이다 — `active` 승격은 **실행 통계로만** 한다 (C8).
- **바뀐 것이 있을 때만 `revision`을 올린다** — 같은 것을 다시 올려도 Worker 계획 캐시가
  버려지지 않는다.
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp, Violation
from chaeksas.ext.ui_automation.contracts.plan import (
    DESKTOP,
    DESKTOP_STRATEGIES,
    WEB,
    WEB_STRATEGIES,
    LocatorSpec,
    WindowSpec,
)
from chaeksas.ext.ui_automation.contracts.worker_local import KNOWN_ACTIONS

#: 이름 규칙 (C9 §이름 규칙).
PAGE_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
SEMANTIC_KEY = re.compile(r"^[a-z][a-z0-9_.]{0,79}$")

#: 요소의 종류 (BUI-06 「종류」).
KINDS = ("control", "list", "table", "text")


class ElementHint(ContractModel):
    """치유·계획이 쓰는 **시맨틱** 정보 (셀렉터가 아니다)."""

    description: str = ""
    role: str = ""
    name: str = ""
    kind: str = "control"


class CatalogEntry(ContractModel):
    """설계할 때 쓰는 관계 정보 (STU-13 요소 목록, LLM 계획)."""

    actions: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    navigates_to: str | None = None


class LocatorStats(ContractModel):
    """로케이터 하나의 성적 — **승격·강등이 이것으로 판단한다** (C8)."""

    success: int = 0
    fail: int = 0
    last_success_at: Timestamp | None = None
    #: 연속 성공 수 — `unverified`가 이만큼 쌓이면 `active`로 올린다.
    streak: int = 0


class PageRegistration(SchemaVersioned):
    """등록 단위 = 화면 하나 (C9)."""

    SCHEMA: ClassVar[int] = 1

    page_id: str
    platform: str = WEB
    name: str = ""
    url_pattern: str | None = None
    #: 데스크톱만 — 앱 이름. 실행 파일 경로는 두지 않는다 (PC마다 다르다, ADR-0033).
    app: str | None = None
    #: 데스크톱만 — 이 화면인 창의 조건. **데스크톱이면 필수**다.
    window: WindowSpec | None = None
    locators: dict[str, list[LocatorSpec]] = Field(default_factory=dict)
    elements: dict[str, ElementHint] = Field(default_factory=dict)
    catalog: dict[str, CatalogEntry] = Field(default_factory=dict)
    revision: int = 1
    updated_at: Timestamp | None = None


class Registered(ContractModel):
    """새로 생기거나 이미 있던 로케이터 하나."""

    semantic_key: str
    locator_key: str


class RegistrationResult(ContractModel):
    """`registry_register`의 결과 (BUI-06 결과 문구가 이것을 읽는다)."""

    page_id: str
    revision: int = 1
    created: list[Registered] = Field(default_factory=list)
    kept: list[Registered] = Field(default_factory=list)
    created_page: bool = False

    @property
    def unchanged(self) -> bool:
        """「이미 등록된 것과 같다」 — 새로 생긴 것이 없다."""
        return not self.created and bool(self.kept)

    def to_json_dict(self) -> dict[str, object]:
        found = super().to_json_dict()
        found["unchanged"] = self.unchanged
        return found


class BrokenLink(ContractModel):
    """지우면 끊기는 길 (`navigates_to`·`depends_on`)."""

    page_id: str
    semantic_key: str
    kind: str  # navigates_to | depends_on


class DeletionResult(ContractModel):
    """`registry_delete` — **되돌릴 수 없는 일이라 숫자로 남긴다**."""

    page_id: str
    semantic_key: str | None = None
    elements: int = 0
    locators: int = 0
    broken_links: list[BrokenLink] = Field(default_factory=list)
    revision: int = 1


class PageBrief(ContractModel):
    """`registry_list_pages` 한 줄 (BUI-06 「화면 ID」 콤보)."""

    page_id: str
    name: str = ""
    platform: str = WEB
    element_count: int = 0
    revision: int = 1
    updated_at: Timestamp | None = None


def validate(page: PageRegistration) -> list[Violation]:
    """등록 전 검사 (C9 §검사). **사다리 없는 정보는 거부한다.**"""
    out: list[Violation] = []
    if not PAGE_ID.match(page.page_id):
        out.append(Violation(rule="C9", code="page_id_invalid", message=f"화면 id 모양이 아니다: {page.page_id}"))
    if page.platform not in (WEB, DESKTOP):
        out.append(Violation(rule="C9", code="platform_invalid", message=f"모르는 플랫폼이다: {page.platform}"))
    if not page.locators:
        out.append(Violation(rule="C9", code="no_locators", message="요소가 하나도 없다"))

    if page.platform == DESKTOP:
        # 어느 창인지 모르면 Worker가 앞에 있는 아무 창에나 입력하게 된다 (ADR-0033).
        if page.window is None or page.window.empty:
            out.append(
                Violation(rule="C9", code="window_required", message="데스크톱 화면에는 창 조건(window)이 있어야 한다")
            )
        elif page.window.title:
            try:
                re.compile(page.window.title)
            except re.error as e:
                out.append(
                    Violation(rule="C9", code="window_title_invalid", message=f"창 제목 정규식이 틀렸다: {e}")
                )

    allowed = WEB_STRATEGIES if page.platform == WEB else DESKTOP_STRATEGIES
    for key, ladder in page.locators.items():
        if not SEMANTIC_KEY.match(key):
            out.append(Violation(rule="C9", code="key_invalid", message=f"시맨틱 키 모양이 아니다: {key}"))
        if not ladder:
            out.append(Violation(rule="C9", code="empty_ladder", message=f"사다리가 비었다: {key}"))
        for one in ladder:
            if one.type not in allowed:
                out.append(
                    Violation(
                        rule="C9",
                        code="strategy_mismatch",
                        message=f"{page.platform}에서 쓸 수 없는 전략이다: {one.type} ({key})",
                    )
                )
            if one.type == "role" and not one.name:
                # 접근성 이름 없이는 role 하나로 여럿이 맞는다.
                out.append(
                    Violation(rule="C9", code="role_needs_name", message=f"role 로케이터에 이름이 없다: {key}")
                )

    for where, keys in (("elements", page.elements), ("catalog", page.catalog)):
        for key in keys:
            if key not in page.locators:
                out.append(
                    Violation(
                        rule="C9",
                        code="no_ladder_for_info",
                        message=f"사다리 없는 요소의 {where}다: {key}",
                    )
                )

    for key, entry in page.catalog.items():
        if key in entry.depends_on:
            out.append(Violation(rule="C9", code="self_dependency", message=f"자기 자신에 기댄다: {key}"))
        for action in entry.actions:
            if action not in KNOWN_ACTIONS:
                out.append(
                    Violation(rule="C9", code="unknown_action", message=f"모르는 동작이다: {action} ({key})")
                )
    return out


__all__ = [
    "WEB",
    "KINDS",
    "PAGE_ID",
    "SEMANTIC_KEY",
    "BrokenLink",
    "CatalogEntry",
    "DeletionResult",
    "ElementHint",
    "LocatorStats",
    "PageBrief",
    "PageRegistration",
    "Registered",
    "RegistrationResult",
    "validate",
]

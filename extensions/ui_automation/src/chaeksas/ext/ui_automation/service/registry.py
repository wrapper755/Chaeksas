"""UI 자동화 앱의 레지스트리 — 화면·요소·사다리와 **승격 규칙** (C9·C8).

통계와 승격이 여기 있는 이유는 **실행이 말해 주는 것**이기 때문이다. 사람이 등록할 때
「맞다」고 한 것은 그 순간 그 화면에서만 참이라, `active`는 **실행에서 세 번 연속 성공**해야
준다 (C8 §승격 규칙).

- **등록은 지우지 않는다** — 더한다. 같은 로케이터(`locator_key`)는 그대로 둔다.
- **바뀐 것이 있을 때만 `revision`을 올린다** — 아니면 Worker 계획 캐시가 공연히 버려진다.
- **`test` 보고는 통계에 넣지 않는다** (셀렉터 시험, BUI-08).
- **자동 강등은 하지 않는다** — 실패가 잦으면 경고만 한다 (사람이 본다, UIA-02).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from chaeksas.ext.ui_automation.contracts.plan import (
    ACTIVE,
    DEPRECATED,
    ORIGIN_RUN,
    UNVERIFIED,
    LocatorSpec,
    SessionReport,
)
from chaeksas.ext.ui_automation.contracts.registry import (
    BrokenLink,
    DeletionResult,
    ElementHint,
    LocatorStats,
    PageBrief,
    PageRegistration,
    Registered,
    RegistrationResult,
    validate,
)

log = logging.getLogger(__name__)

#: `unverified`가 **실행에서** 이만큼 연속 성공하면 `active`로 올린다 (C8).
PROMOTE_AFTER = 3
PROMOTE_ENV = "CHK_SVC_UI_AUTOMATION__PROMOTE_AFTER"

#: 최근 이만큼을 보고 실패율이 이 값을 넘으면 **경고만** 한다 (자동 강등은 없다).
WARN_WINDOW = 10
WARN_RATE = 0.5


class RegistryError(ValueError):
    """등록·삭제를 할 수 없다. 사람이 읽을 한 줄."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Registry:
    """화면 레지스트리 하나. **메모리에 둔다** — 저장은 서비스 앱의 몫이다 (M5)."""

    pages: dict[str, PageRegistration] = field(default_factory=dict)
    #: `(page_id, semantic_key, locator_key)` → 성적.
    stats: dict[tuple[str, str, str], LocatorStats] = field(default_factory=dict)
    promote_after: int = PROMOTE_AFTER
    #: 어느 화면이든 바뀌면 오른다 (공개 카탈로그의 최상위 `revision`, C9).
    revision: int = 1

    # ── 등록 ──

    def register(self, page: PageRegistration) -> RegistrationResult:
        """등록·추가 (C9 `registry_register`). **기존 것을 지우지 않는다.**"""
        known = self.pages.get(page.page_id)
        if known is not None and page.window is None and known.window is not None:
            # 「보낸 칸만 바꾼다」 — 로케이터만 더하러 온 데스크톱 등록이 창 조건 검사에 걸리지 않게.
            page = page.model_copy(update={"window": known.window})
        problems = validate(page)
        if problems:
            raise RegistryError(problems[0].message)

        before = self.pages.get(page.page_id)
        found = RegistrationResult(
            page_id=page.page_id,
            created_page=before is None,
            revision=before.revision if before else 1,
        )
        made = before or PageRegistration(
            schema=1, page_id=page.page_id, platform=page.platform, name=page.name
        )

        for key, ladder in page.locators.items():
            existing = made.locators.setdefault(key, [])
            keys = {one.key for one in existing}
            for locator in ladder:
                if locator.key in keys:
                    found.kept.append(Registered(semantic_key=key, locator_key=locator.key))
                    continue
                # **사람이 검증했어도 `unverified`다** — 승격은 실행 통계로만 (C8).
                existing.append(locator.model_copy(update={"status": UNVERIFIED}))
                found.created.append(Registered(semantic_key=key, locator_key=locator.key))

        made.elements.update(page.elements)
        made.catalog.update(page.catalog)
        if page.name:
            made.name = page.name
        if page.url_pattern:
            made.url_pattern = page.url_pattern
        # 데스크톱 창 조건 (C9, ADR-0033) — **보낸 것만** 바꾼다. 바뀌면 계획 캐시가 옛 창을 쥐지
        # 않게 `revision`도 올린다.
        window_changed = False
        if page.app is not None and page.app != made.app:
            made.app, window_changed = page.app, True
        if page.window is not None and page.window != made.window:
            made.window, window_changed = page.window, True

        if found.created or before is None or window_changed:
            # **바뀐 것이 있을 때만** 올린다 — 같은 것을 다시 올려도 캐시가 살아 있게.
            made.revision = (before.revision + 1) if before else 1
            made.updated_at = now_iso()
            self.revision += 1
        found.revision = made.revision
        self.pages[page.page_id] = made
        return found

    # ── 조회 ──

    def pages_list(self, *, platform: str | None = None, query: str | None = None) -> list[PageBrief]:
        out = []
        for page in self.pages.values():
            if platform and page.platform != platform:
                continue
            if query and query not in page.page_id and query not in page.name:
                continue
            out.append(
                PageBrief(
                    page_id=page.page_id,
                    name=page.name,
                    platform=page.platform,
                    element_count=len(page.locators),
                    revision=page.revision,
                    updated_at=page.updated_at,
                )
            )
        return sorted(out, key=lambda one: one.page_id)

    def page(self, page_id: str) -> PageRegistration:
        found = self.pages.get(page_id)
        if found is None:
            raise RegistryError(f"그 화면이 없다: {page_id}")
        return found

    def ladder(self, page_id: str, semantic_key: str) -> list[LocatorSpec]:
        """계획이 쓸 사다리 — **`unverified`도 쓴다** (치유로 찾은 것이 바로 돌아야 한다)."""
        page = self.pages.get(page_id)
        if page is None:
            return []
        found = [one for one in page.locators.get(semantic_key, []) if one.status != DEPRECATED]
        return sorted(found, key=lambda one: one.rank)

    # ── 삭제 ──

    def links_to(self, page_id: str, semantic_key: str | None = None) -> list[BrokenLink]:
        """지우면 끊기는 길 (`navigates_to`·`depends_on`)."""
        out = []
        for page in self.pages.values():
            for key, entry in page.catalog.items():
                if entry.navigates_to == page_id and semantic_key is None:
                    out.append(BrokenLink(page_id=page.page_id, semantic_key=key, kind="navigates_to"))
                if page.page_id == page_id and semantic_key and semantic_key in entry.depends_on:
                    out.append(BrokenLink(page_id=page.page_id, semantic_key=key, kind="depends_on"))
        return out

    def delete(self, page_id: str, semantic_key: str | None = None, *, force: bool = False) -> DeletionResult:
        """**잘못 만든 것을 없애는 길이다** — 화면 개편용이 아니다 (C9).

        끊기는 길이 있으면 `force` 없이는 막는다 — 사람이 한 번 더 보게 (U9).
        """
        page = self.page(page_id)
        broken = self.links_to(page_id, semantic_key)
        if broken and not force:
            raise HasLinks(f"이것을 가리키는 곳이 {len(broken)}개 있다", broken)

        if semantic_key:
            ladder = page.locators.pop(semantic_key, [])
            page.elements.pop(semantic_key, None)
            page.catalog.pop(semantic_key, None)
            found = DeletionResult(page_id=page_id, semantic_key=semantic_key, elements=1, locators=len(ladder))
        else:
            found = DeletionResult(
                page_id=page_id,
                elements=len(page.locators),
                locators=sum(len(one) for one in page.locators.values()),
            )
            del self.pages[page_id]
        found.broken_links = broken
        page.revision += 1
        found.revision = page.revision
        self.revision += 1
        for key in [k for k in self.stats if k[0] == page_id and (not semantic_key or k[1] == semantic_key)]:
            del self.stats[key]
        return found

    # ── 보고 반영 (C8 §승격 규칙) ──

    def apply(self, report: SessionReport) -> list[str]:
        """보고 하나를 반영한다 → 승격된 `locator_key`들.

        **`test` 보고는 통계에 넣지 않는다** (셀렉터 시험은 승격 근거가 아니다).
        """
        if report.origin != ORIGIN_RUN:
            return []

        page = self.pages.get(report.page_id)
        if page is None:
            return []

        for attempt in report.attempts:
            stats = self.stats.setdefault(
                (report.page_id, attempt.semantic_key, attempt.locator_key), LocatorStats()
            )
            if attempt.succeeded:
                stats.success += 1
                stats.streak += 1
                stats.last_success_at = now_iso()
            else:
                stats.fail += 1
                stats.streak = 0

        # 치유로 찾은 것은 **사다리에 더한다** (`unverified`) — 조회가 바로 쓴다.
        for healed in report.healed:
            ladder = page.locators.setdefault(healed.semantic_key, [])
            if healed.locator.key not in {one.key for one in ladder}:
                ladder.append(healed.locator.model_copy(update={"status": UNVERIFIED}))
                page.revision += 1
                self.revision += 1

        return self._promote(report.page_id)

    def _promote(self, page_id: str) -> list[str]:
        """**실행에서 세 번 연속 성공**한 `unverified`를 `active`로 (C8)."""
        page = self.pages[page_id]
        promoted = []
        for key, ladder in page.locators.items():
            for locator in ladder:
                stats = self.stats.get((page_id, key, locator.key))
                if locator.status != UNVERIFIED or stats is None or stats.streak < self.promote_after:
                    continue
                index = ladder.index(locator)
                ladder[index] = locator.model_copy(update={"status": ACTIVE})
                promoted.append(locator.key)
                self._supersede(page_id, key, locator.key)
        if promoted:
            page.revision += 1
            self.revision += 1
        return promoted

    def _supersede(self, page_id: str, semantic_key: str, winner: str) -> None:
        """승격된 것이 밀어낸 것을 `deprecated`로 — **치유가 적어 둔 대로만** 내린다."""
        page = self.pages[page_id]
        ladder = page.locators[semantic_key]
        for index, locator in enumerate(ladder):
            if locator.key == winner or locator.status == DEPRECATED:
                continue
            stats = self.stats.get((page_id, semantic_key, locator.key))
            if stats is not None and stats.fail > 0 and stats.streak == 0:
                ladder[index] = locator.model_copy(update={"status": DEPRECATED})

    def warnings(self, page_id: str) -> list[str]:
        """최근 실패율이 높은 `active` 로케이터 (UIA-02 띠). **자동 강등은 하지 않는다.**"""
        page = self.pages.get(page_id)
        if page is None:
            return []
        out = []
        for key, ladder in page.locators.items():
            for locator in ladder:
                stats = self.stats.get((page_id, key, locator.key))
                if locator.status != ACTIVE or stats is None:
                    continue
                total = stats.success + stats.fail
                if total >= WARN_WINDOW and stats.fail / total > WARN_RATE:
                    out.append(f"{key}: {locator.key} (최근 실패 {stats.fail}/{total})")
        return out

    # ── 공개 카탈로그 (C9 §공개 카탈로그) ──

    def catalog(self) -> dict[str, object]:
        """`GET /v1/catalog` — **셀렉터는 나가지 않는다** (C13 §5).

        치유 프롬프트용 `description` 원문과 통계 세부도 빠진다.
        """
        items = []
        for page in sorted(self.pages.values(), key=lambda one: one.page_id):
            counts = {ACTIVE: 0, UNVERIFIED: 0, DEPRECATED: 0}
            for ladder in page.locators.values():
                for locator in ladder:
                    counts[locator.status] = counts.get(locator.status, 0) + 1
            items.append(
                {
                    "type": "ui_page",
                    "id": page.page_id,
                    "name": page.name or page.page_id,
                    "summary": (
                        f"요소 {len(page.locators)}개 · 사용 중 {counts[ACTIVE]}"
                        f" · 검증 전 {counts[UNVERIFIED]}"
                    ),
                    "updated_at": page.updated_at,
                    "data": {
                        "platform": page.platform,
                        "revision": page.revision,
                        "elements": [
                            {
                                "semantic_key": key,
                                "name": page.elements.get(key, _EMPTY).name,
                                "kind": page.elements.get(key, _EMPTY).kind,
                                "actions": page.catalog[key].actions if key in page.catalog else [],
                                "depends_on": page.catalog[key].depends_on if key in page.catalog else [],
                                **(
                                    {"navigates_to": page.catalog[key].navigates_to}
                                    if key in page.catalog and page.catalog[key].navigates_to
                                    else {}
                                ),
                            }
                            for key in sorted(page.locators)
                        ],
                        "locator_summary": counts,
                    },
                }
            )
        return {"schema": 1, "revision": self.revision, "items": items}


class HasLinks(RegistryError):
    """다른 곳이 이것을 가리킨다 (409 `has_links`) — 사람이 한 번 더 본다."""

    def __init__(self, message: str, links: list[BrokenLink]) -> None:
        super().__init__(message)
        self.links = links


#: `elements`에 없는 요소를 그릴 때 쓰는 빈 값.
_EMPTY = ElementHint()


__all__ = [
    "PROMOTE_AFTER",
    "PROMOTE_ENV",
    "WARN_RATE",
    "WARN_WINDOW",
    "HasLinks",
    "Registry",
    "RegistryError",
    "now_iso",
]

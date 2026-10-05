"""공개 카탈로그를 읽는다 — STU-13이 고를 화면·요소 (C9·C13 §5).

**셀렉터는 여기 없다** (ADR-0008). 그래서 Studio는 키 없이 읽을 수 있고, 설계할 때 물리
정보가 그림에 섞이지 않는다.

- 닿지 못하면 **마지막으로 읽은 것**을 쓰고 그렇다고 말한다 (「(오프라인)」) — 비행기에서도
  태스크를 고칠 수 있어야 한다.
- 메모리에만 둔다. 창을 다시 열면 다시 읽는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: 요소 종류 → 사람이 읽는 말 (BUI-06과 같은 낱말).
KIND_LABEL = {"control": "조작", "list": "목록", "table": "표", "text": "글자"}


@dataclass(frozen=True)
class UiElement:
    """카탈로그의 요소 하나. **시맨틱 정보뿐이다.**"""

    semantic_key: str
    name: str = ""
    kind: str = "control"
    actions: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    navigates_to: str | None = None

    @property
    def label(self) -> str:
        kind = KIND_LABEL.get(self.kind, self.kind)
        return f"{self.semantic_key} — {self.name or '이름 없음'} ({kind})"


@dataclass(frozen=True)
class UiPage:
    """카탈로그의 화면 하나."""

    page_id: str
    name: str = ""
    platform: str = "web"
    revision: int = 1
    elements: tuple[UiElement, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.name or self.page_id} — 요소 {len(self.elements)}개"

    def element(self, semantic_key: str) -> UiElement | None:
        return next((one for one in self.elements if one.semantic_key == semantic_key), None)


def read_catalog(raw: dict[str, Any]) -> list[UiPage]:
    """`GET /v1/catalog` 본문 → 화면 목록. 모르는 칸은 지나간다 (열린 모양이다)."""
    out = []
    for item in raw.get("items") or []:
        if item.get("type") != "ui_page":
            continue
        data = item.get("data") or {}
        out.append(
            UiPage(
                page_id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                platform=str(data.get("platform") or "web"),
                revision=int(data.get("revision") or 1),
                elements=tuple(
                    UiElement(
                        semantic_key=str(one.get("semantic_key") or ""),
                        name=str(one.get("name") or ""),
                        kind=str(one.get("kind") or "control"),
                        actions=tuple(str(x) for x in (one.get("actions") or [])),
                        depends_on=tuple(str(x) for x in (one.get("depends_on") or [])),
                        navigates_to=one.get("navigates_to"),
                    )
                    for one in (data.get("elements") or [])
                ),
            )
        )
    return out


@dataclass
class Catalog:
    """화면 목록 한 벌. **마지막으로 읽은 것**을 들고 있는다."""

    base_url: str | None = None
    timeout_s: float = 10.0
    client: Any = None  # httpx.Client (시험이 끼운다)

    pages: list[UiPage] = field(default_factory=list)
    #: 마지막 읽기가 실패했나 (화면이 「(오프라인)」으로 보인다).
    offline: bool = False
    last_error: str = ""

    def reload(self) -> bool:
        """다시 읽는다 → 성공했나. **실패해도 들고 있던 것은 버리지 않는다.**"""
        import httpx  # noqa: PLC0415 — 읽을 때만 든다

        if not self.base_url:
            self.offline = True
            self.last_error = "UI 자동화 앱 주소를 모릅니다"
            return False
        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            answer = client.get(f"{self.base_url.rstrip('/')}/v1/catalog")
        except httpx.HTTPError as e:
            self.offline = True
            self.last_error = f"닿지 못했습니다 ({type(e).__name__})"
            return False
        finally:
            if own:
                client.close()

        if answer.status_code != 200:
            self.offline = True
            self.last_error = f"서버가 {answer.status_code}로 답했습니다"
            return False
        try:
            self.pages = read_catalog(answer.json())
        except ValueError as e:
            self.offline = True
            self.last_error = f"카탈로그를 읽지 못했습니다 ({e})"
            return False
        self.offline = False
        self.last_error = ""
        return True

    def page(self, page_id: str) -> UiPage | None:
        return next((one for one in self.pages if one.page_id == page_id), None)


__all__ = ["KIND_LABEL", "Catalog", "UiElement", "UiPage", "read_catalog"]

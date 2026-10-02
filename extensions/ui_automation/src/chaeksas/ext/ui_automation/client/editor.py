"""UI 태스크 속성 편집기 (STU-13) — Studio 속성 패널에 붙는다.

> 상태: **뼈대만.** 실제 화면은 M4다. 위젯을 만드는 쪽이라 PySide6를 쓰게 되지만, 지금은 아직
> 외부 의존을 들이지 않았다 (`docs/05-roadmap.md` M1 「아직 없는 것」).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.extension_api import ExtensionContext


class UiTaskEditor:
    """`task_types[].editor` (`kind="builtin"`) — `extension_api.TaskEditor`."""

    def __init__(self) -> None:
        self._properties: dict[str, Any] = {}

    def widget(self, ctx: ExtensionContext) -> object:
        raise NotImplementedError("UI 태스크 편집기 화면(STU-13)은 M4다")

    def load(self, properties: Mapping[str, Any]) -> None:
        """BPMN `chk:*` 속성(C14)을 칸에 채운다."""
        self._properties = dict(properties)

    def dump(self) -> Mapping[str, Any]:
        return dict(self._properties)

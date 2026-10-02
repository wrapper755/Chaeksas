"""「UI 셀렉터 등록」 (BUI-06~08) — Bot UI 「도구」 메뉴의 유틸리티.

ADR-0018로 이것은 Bot UI의 고유 기능이 아니라 **이 확장이 기여하는 도구**가 되었다. 그래서
Bot UI 코드에 셀렉터·화면 레지스트리라는 말이 나오지 않는다.

> 상태: **뼈대만.** 실제 화면과 Worker 분석 호출(C9·C10)은 M4다.
"""

from __future__ import annotations

from chaeksas.extension_api import ExtensionContext


class SelectorRegistration:
    """`bot_ui.utilities` — `extension_api.BotUiUtility`.

    `needs_runtime: "worker"`라서, Bot UI가 이 탭을 열 때 Worker 프로세스를 먼저 띄운다.
    등록 담당자 키는 설정 칸 `registrar_key`(비밀)로 받는다 (`ctx.secret("registrar_key")`).
    """

    def widget(self, ctx: ExtensionContext) -> object:
        raise NotImplementedError("셀렉터 등록 화면(BUI-06~08)은 M4다")

    def closed(self) -> None:
        """탭을 닫을 때 — Worker의 UI 세션을 놓는다 (세션은 한 번에 하나다, ADR-0014)."""
        return None

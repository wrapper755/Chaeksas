"""「UI 셀렉터 등록」 (BUI-06~08) — Bot UI 「도구」 메뉴의 유틸리티.

ADR-0018로 이것은 Bot UI의 고유 기능이 아니라 **이 확장이 기여하는 도구**가 되었다. 그래서
Bot UI 코드에 셀렉터·화면 레지스트리라는 말이 나오지 않는다.

Worker가 어디 있는지는 **호스트가 설정으로 알려 준다** (C13 예약 키 `runtime.worker.*`) —
`needs_runtime: "worker"`라서 Bot UI가 먼저 띄워 두고 연다.
"""

from __future__ import annotations

from chaeksas.extension_api import ExtensionContext


class SelectorRegistration:
    """`bot_ui.utilities` — `extension_api.BotUiUtility`.

    등록 담당자 키는 설정 칸 `registrar_key`(비밀)로 받는다 (`ctx.secret("registrar_key")`) —
    레지스트리에 쓰는 것(C9)은 다음 조각이라 아직 읽지 않는다.
    """

    def __init__(self) -> None:
        self._widget: object | None = None

    def widget(self, ctx: ExtensionContext) -> object:
        from chaeksas.ext.ui_automation.client.registration_window import (  # noqa: PLC0415
            RegistrationWidget,
            worker_client,
        )

        made = RegistrationWidget(worker_client(ctx.settings))
        self._widget = made
        return made

    def closed(self) -> None:
        """탭을 닫을 때 — Worker의 UI 세션을 놓는다 (세션은 한 번에 하나다, ADR-0014)."""
        found = self._widget
        release = getattr(found, "release", None)
        if callable(release):
            release()
        self._widget = None

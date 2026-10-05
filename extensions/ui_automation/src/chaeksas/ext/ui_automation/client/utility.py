"""「UI 셀렉터 등록」 (BUI-06~08) — Bot UI 「도구」 메뉴의 유틸리티.

ADR-0018로 이것은 Bot UI의 고유 기능이 아니라 **이 확장이 기여하는 도구**가 되었다. 그래서
Bot UI 코드에 셀렉터·화면 레지스트리라는 말이 나오지 않는다.

창 하나에 탭 둘이다 — 「등록」(BUI-06·07)과 「시험」(BUI-08). **UI 세션은 한 번에 하나**라
(ADR-0014) 한쪽이 열려 있으면 다른 쪽이 놓게 한다.

Worker가 어디 있는지는 **호스트가 설정으로 알려 준다** (C13 예약 키 `runtime.worker.*`) —
`needs_runtime: "worker"`라서 Bot UI가 먼저 띄워 두고 연다.
"""

from __future__ import annotations

from chaeksas.extension_api import ExtensionContext

#: 등록 담당자 키를 받는 설정 칸 (C13 `configuration`, BUI-03).
REGISTRAR_KEY = "registrar_key"


class SelectorRegistration:
    """`bot_ui.utilities` — `extension_api.BotUiUtility`.

    등록 담당자 키는 설정 칸 `registrar_key`(비밀)로 받고, UI 자동화 앱 주소는 **호스트가**
    예약 키 `service.base_url`로 알려 준다 (C13 — 주소 출처는 하나). 둘 중 하나라도 없으면
    등록·시험이 꺼지고 왜 꺼졌는지 화면이 말한다.
    """

    def __init__(self) -> None:
        self._widget: object | None = None
        self._parts: tuple[object, ...] = ()

    def widget(self, ctx: ExtensionContext) -> object:
        from PySide6.QtWidgets import QTabWidget  # noqa: PLC0415

        from chaeksas.ext.ui_automation.client.registration_window import (  # noqa: PLC0415
            RegistrationWidget,
            registry_client,
            worker_client,
        )
        from chaeksas.ext.ui_automation.client.trial_window import TrialWidget  # noqa: PLC0415

        worker = worker_client(ctx.settings)
        registry = registry_client(ctx)

        made = QTabWidget()
        register = RegistrationWidget(worker, registry)
        trial = TrialWidget(
            worker,
            registry,
            service_key=ctx.secret(REGISTRAR_KEY),
            # **세션은 한 번에 하나다** — 시험을 시작하면 등록 탭이 쥔 것을 놓는다.
            release_other=register.close_browser,
        )
        made.addTab(register, "등록")
        made.addTab(trial, "시험")
        self._widget = made
        self._parts = (register, trial)
        return made

    def closed(self) -> None:
        """탭을 닫을 때 — Worker의 UI 세션을 놓는다 (세션은 한 번에 하나다, ADR-0014)."""
        for part in getattr(self, "_parts", ()):
            release = getattr(part, "release", None)
            if callable(release):
                release()
        self._widget = None
        self._parts = ()

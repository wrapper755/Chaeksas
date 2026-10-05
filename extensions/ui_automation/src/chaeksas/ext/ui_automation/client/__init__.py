"""클라이언트 기여 — UI 태스크 수행기, Studio 편집기(STU-13), Bot UI 유틸리티(BUI-06~08), 사전 점검, 데스크톱 AI 환경

`extension.json`의 `entry`가 여기를 가리킨다 (`ui_automation.client:<이름>`). 확장 호스트는
확장의 패키지 안만 가리킬 수 있게 막으므로, 밖으로 나가는 `entry`는 쓸 수 없다.

이 모듈들은 `chaeksas.extension_api`만 import한다 — `chaeksas.core`도, 다른 확장도 보지 않는다
(docs/01-architecture.md §5).
"""

from chaeksas.ext.ui_automation.client.agent_env import DesktopEnvironment
from chaeksas.ext.ui_automation.client.editor import UiTaskEditor
from chaeksas.ext.ui_automation.client.preflight import PagesRegisteredCheck
from chaeksas.ext.ui_automation.client.task import UiTaskExecutor
from chaeksas.ext.ui_automation.client.utility import SelectorRegistration

__all__ = [
    "DesktopEnvironment",
    "PagesRegisteredCheck",
    "SelectorRegistration",
    "UiTaskEditor",
    "UiTaskExecutor",
]

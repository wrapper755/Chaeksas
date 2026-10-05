"""Studio가 확장을 싣는다 — 태스크 종류와 그 편집기 (C13, ADR-0018).

Studio는 **어느 확장인지 모른다.** `chk:task`의 `type`으로 기여된 편집기를 찾아 속성
패널에 끼울 뿐이다 (STU-13이 그 첫 손님이다).

- **읽다 실패해도 Studio는 뜬다** — 확장 하나 때문에 그림을 못 열면 더 나쁘다.
- 편집기는 **태스크 종류마다 하나**를 만들어 두고 다시 쓴다 (`load()`/`dump()`로 오간다).
- 서버 주소는 **호스트가 예약 키로** 준다 (C13 `service.base_url`) — 확장이 설정에
  따로 두지 않는다. 출처는 하나다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts import SCOPE_STUDIO, SERVICE_URL_SETTING
from chaeksas.core.extensions import ExtensionHost
from chaeksas.extension_api import HOST_STUDIO, Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlainSettings:
    """`extension_api.Settings` — 확장 설정 칸 + 호스트가 채운 예약 키 (C13)."""

    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@dataclass(frozen=True)
class NoSecrets:
    """`extension_api.Secrets` — **Studio에는 비밀이 없다**.

    설계할 때는 키가 필요 없다 (공개 카탈로그만 읽는다, ADR-0008·C9). 키가 필요한 일은
    Bot UI·실행기가 한다 (ADR-0013).
    """

    def resolve(self, ref: str) -> str | None:
        return None


@dataclass
class Extensions:
    """실은 확장들과 만들어 둔 편집기."""

    host: ExtensionHost = field(default_factory=ExtensionHost)
    _editors: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> Extensions:
        host = ExtensionHost()
        try:
            host.load_entry_points()
        except Exception as e:  # noqa: BLE001 — 확장 때문에 Studio가 안 뜨면 안 된다
            log.warning("확장을 읽지 못했다: %s", e)
        for failure in host.failures:
            log.warning("확장을 켜지 못했다: %s", failure)
        return cls(host=host)

    def label(self, task_type: str) -> str:
        found = self.host.task_type(task_type)
        return found.value.label if found is not None else task_type

    def settings_for(self, extension_id: str) -> Settings:
        """그 확장의 Studio 설정 + 예약 키. **주소의 출처는 하나다** (C13)."""
        found = self.host.get(extension_id)
        values: dict[str, Any] = {}
        if found is not None:
            for item in found.manifest.contributes.configuration:
                if item.scope == SCOPE_STUDIO:
                    values[item.key] = None
            service = found.manifest.service
            values[SERVICE_URL_SETTING] = service.base_url if service is not None else None
        return PlainSettings(values=values)

    def editor(self, task_type: str) -> Any | None:
        """그 태스크 종류의 편집기 위젯. 없거나 깨졌으면 `None` (JSON 탭이 그 자리를 메운다)."""
        if task_type in self._editors:
            return self._editors[task_type]
        found = self.host.task_type(task_type)
        if found is None:
            return None
        made: Any | None = None
        try:
            editor = self.host.editor(task_type)
            if editor is not None:
                context = self.host.context(
                    found.extension_id,
                    host=HOST_STUDIO,
                    settings=self.settings_for(found.extension_id),
                    secrets=NoSecrets(),
                )
                made = editor.widget(context)
        except Exception:  # noqa: BLE001 — 확장이 깨져도 속성 패널은 산다
            log.exception("편집기를 만들지 못했다: %s", task_type)
            made = None
        self._editors[task_type] = made
        return made


__all__ = ["Extensions", "NoSecrets", "PlainSettings"]

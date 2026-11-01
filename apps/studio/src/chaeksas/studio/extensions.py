"""Studio가 확장을 싣는다 — 태스크 종류와 그 편집기 (C13, ADR-0018).

Studio는 **어느 확장인지 모른다.** `bpm:task`의 `type`으로 기여된 편집기를 찾아 속성
패널에 끼울 뿐이다 (STU-13이 그 첫 손님이다).

- **읽다 실패해도 Studio는 뜬다** — 확장 하나 때문에 그림을 못 열면 더 나쁘다.
- 편집기는 **태스크 종류마다 하나**를 만들어 두고 다시 쓴다 (`load()`/`dump()`로 오간다).
- 서버 주소는 **호스트가 예약 키로** 준다 (C13 `service.base_url`) — 확장이 설정에
  따로 두지 않는다. 출처는 하나다.
- **시험 실행도 확장을 쓴다** (`tasks()`) — 확장 태스크의 수행기를 호스트에서 받는다.
- 서비스 앱 키는 없다 (ADR-0102) — 바깥 기능은 Studio 키로 Center에 시험 일감을 올린다 (C15,
  `services.py`). 확장의 비밀 칸만 OS 비밀 저장소(`chaeksas-studio`, `ext:<확장>:<칸>`)에서 푼다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts import (
    CALL_TOKEN_SECRET,
    CENTER_URL_SETTING,
    SCOPE_STUDIO,
)
from chaeksas.core.extensions import ExtensionHost, HostTasks
from chaeksas.extension_api import HOST_STUDIO, ExtensionContext, Settings
from chaeksas.studio.credentials import StudioCredentials

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlainSettings:
    """`extension_api.Settings` — 확장 설정 칸 + 호스트가 채운 예약 키 (C13)."""

    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@dataclass(frozen=True)
class LiveSettings:
    """`extension_api.Settings` — **물을 때마다** 다시 짓는다 (편집기는 한 번 만들어 다시 쓴다).

    사람이 STU-10에서 설정을 바꾸면 열어 둔 편집기도 새 값을 본다.
    """

    values: Callable[[], Mapping[str, Any]]

    def get(self, key: str, default: Any = None) -> Any:
        found = self.values().get(key)
        return default if found is None else found


@dataclass(frozen=True)
class NoSecrets:
    """`extension_api.Secrets` — **Studio에는 비밀이 없다**.

    설계할 때는 키가 필요 없다 (공개 카탈로그만 읽는다, ADR-0008·C9). 키가 필요한 일은
    PC 실행기·실행기가 한다 (ADR-0013).
    """

    def resolve(self, ref: str) -> str | None:
        return None


@dataclass(frozen=True)
class StudioSecrets:
    """`extension_api.Secrets` — Studio에서 확장이 묻는 비밀을 푼다 (ADR-0013).

    `call_token`은 **Studio가 제 키로 청한 호출 토큰**이다 (C15).
    나머지는 그 확장의 비밀 설정 칸이다(STU-10 「확장별 설정」, 환경변수가 먼저). 없으면 `None`.
    """

    credentials: StudioCredentials = field(default_factory=StudioCredentials)
    extension_id: str = ""
    #: 호출 토큰을 주는 쪽 (`studio.call_token.CallTokens`) — 메인 창이 준다. 없으면 `None`이다.
    call_tokens: Callable[[], str | None] | None = None

    def resolve(self, ref: str) -> str | None:
        if ref == CALL_TOKEN_SECRET:
            return self.call_tokens() if self.call_tokens is not None else None
        if not self.extension_id:
            return None
        return self.credentials.extension_secret(self.extension_id, ref)


def installed_host(off: Iterable[str] = ()) -> ExtensionHost:
    """설치된 확장(엔트리 포인트)을 읽은 호스트 하나. `off`는 **사람이 꺼 둔** id다 (ADR-0043)."""
    host = ExtensionHost(off=off)
    try:
        host.load_entry_points()
    except Exception as e:  # noqa: BLE001 — 확장 때문에 Studio가 안 뜨면 안 된다
        log.warning("확장을 읽지 못했다: %s", e)
    for failure in host.failures:
        log.warning("확장을 켜지 못했다: %s", failure)
    return host


@dataclass
class Extensions:
    """실은 확장들과 만들어 둔 편집기."""

    host: ExtensionHost = field(default_factory=ExtensionHost)
    #: 호스트를 **다시 읽는 길** — 끈 목록이 바뀔 때 부른다 (STU-15). 시험이 바꿔 끼운다.
    loader: Callable[[Iterable[str]], ExtensionHost] = field(default_factory=lambda: installed_host)
    #: STU-10 「확장별 설정」에 사람이 넣은 값 — `Settings.extensions` (비밀은 없다, ADR-0073).
    configured: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Center 주소 (`center.url`) — 메인 창이 준다(STU-10 설정). 없으면 `None`이다.
    center_url: Callable[[], str | None] = field(default_factory=lambda: lambda: None)
    #: 호출 토큰을 주는 쪽 (C15) — 메인 창이 준다.
    call_tokens: Callable[[], str | None] | None = None
    _editors: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls, *, off: Iterable[str] = (), configured: dict[str, dict[str, Any]] | None = None
    ) -> Extensions:
        """설치된 확장을 읽는다. `off`는 **사람이 꺼 둔** id다 (STU-15, ADR-0043).

        꺼 둔 것은 기여를 내지 않으므로 팔레트·편집기·시험 실행에서 한꺼번에 사라진다.
        """
        return cls(host=installed_host(off), configured=dict(configured or {}))

    def reload(self, *, off: Iterable[str]) -> None:
        """끈 목록이 바뀌었다 — 호스트를 다시 읽고 **만들어 둔 편집기를 버린다**.

        편집기는 켜져 있던 확장이 준 위젯이라 그대로 두면 꺼진 확장의 화면이 속성 패널에 남는다.
        속성 패널은 고를 때마다 `editor()`를 다시 묻는다 (`properties.py`).
        """
        self.host = self.loader(off)
        self._editors.clear()

    def label(self, task_type: str) -> str:
        found = self.host.task_type(task_type)
        return found.value.label if found is not None else task_type

    def settings_for(self, extension_id: str) -> Settings:
        """그 확장의 Studio 설정 + 예약 키 (C13 — `center.url`).

        칸의 값은 STU-10 「확장별 설정」이 넣은 것이고, 넣지 않은 칸은 `None`이다. **비밀 칸은
        여기 오지 않는다** — `secrets.resolve(<칸>)`으로 푼다 (PC 실행기와 같다).
        """
        found = self.host.get(extension_id)
        values: dict[str, Any] = {}
        if found is not None:
            stored = self.configured.get(extension_id, {})
            for item in found.manifest.contributes.configuration:
                if item.scope == SCOPE_STUDIO and not item.secret:
                    values[item.key] = stored.get(item.key) or None
            values[CENTER_URL_SETTING] = self.center_url()
        return PlainSettings(values=values)

    def _values(self, extension_id: str) -> dict[str, Any]:
        return dict(getattr(self.settings_for(extension_id), "values", {}))

    def editor_context(self, extension_id: str) -> ExtensionContext:
        """확장 편집기의 바깥 세상 — **시험 실행과 같은 것**이다 (ADR-0074).

        편집기가 바깥을 부를 때 시험 실행과 같은 설정·같은 호출 토큰을 본다. 값은 물을 때마다
        읽는다 (`LiveSettings`).
        """
        return self.host.context(
            extension_id,
            host=HOST_STUDIO,
            settings=LiveSettings(values=lambda: self._values(extension_id)),
            secrets=StudioSecrets(extension_id=extension_id, call_tokens=self.call_tokens),
        )

    def context(self, extension_id: str) -> ExtensionContext:
        """확장 코드에 넘길 바깥 세상 — 그 확장의 설정 + 호스트가 채우는 예약 키 (C13).

        시험 실행(`tasks()`)과 **사전 점검**이 같은 것을 쓴다 — 점검이 다른 설정을 보면
        「점검은 통과했는데 실행이 안 된다」가 된다.
        """
        values = self._values(extension_id)
        return self.host.context(
            extension_id,
            host=HOST_STUDIO,
            settings=PlainSettings(values=values),
            secrets=StudioSecrets(extension_id=extension_id, call_tokens=self.call_tokens),
        )

    def tasks(self) -> HostTasks:
        """시험 실행의 `RunEnv.extensions` — 확장 태스크 (ADR-0018)."""
        return HostTasks(host=self.host, make_context=self.context)

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
                made = editor.widget(self.editor_context(found.extension_id))
        except Exception:  # noqa: BLE001 — 확장이 깨져도 속성 패널은 산다
            log.exception("편집기를 만들지 못했다: %s", task_type)
            made = None
        self._editors[task_type] = made
        return made


__all__ = [
    "Extensions",
    "LiveSettings",
    "NoSecrets",
    "PlainSettings",
    "StudioSecrets",
    "installed_host",
]

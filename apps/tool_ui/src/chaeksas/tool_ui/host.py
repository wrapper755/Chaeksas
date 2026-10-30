"""Tool UI가 확장을 싣는다 — 도구와 그 바깥 세상 (C13 `tool_ui.tools`, ADR-0077).

**Qt를 모른다** — 화면(`window.py`)과 갈라 판단을 시험할 수 있게 한다.

- **로컬 런타임은 띄우지 않는다.** PC 실행기가 띄운 것을 Studio와 같은 길(`runtime.json`·토큰 파일)로
  찾아 예약 키 `runtime.<id>.*`를 채운다. 그 런타임이 `health`에 답하지 않으면 **도구를 열지 않고**
  까닭과 길을 말한다(「없는데 된 척」하지 않는다).
- 서버 주소(`service.base_url`)는 **PC 실행기가 받아 둔 명부**를 읽는다 — Tool UI는 Center를 부르지
  않는다. 출처는 그대로 하나다 (Center 리소스 등록 > 정의).
- 끈 확장은 **PC 실행기의 목록**을 따른다 (BUI-11이 이 PC의 유일한 켜기·끄기다, ADR-0043).
- BPM 프로세스 실행과의 차례는 **런타임이 가른다** (Worker는 세션 하나·예약, C10) — 여기서 조정하지 않는다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from chaeksas.contracts import (
    CENTER_URL_SETTING,
    RESERVED_CONFIG_PREFIX,
    SCOPE_TOOL_UI,
    STORAGE_DIR_SETTING,
    LocalRuntime,
    Tool,
)
from chaeksas.core.extensions import Contribution, ExtensionHost
from chaeksas.extension_api import HOST_TOOL_UI, ExtensionContext, ToolUiTool
from chaeksas.tool_ui.credentials import ToolCredentials, ToolSecrets
from chaeksas.tool_ui.places import (
    bot_ui_center_url,
    bot_ui_data_dir,
    bot_ui_turned_off,
    data_dir,
    runtime_folder,
    runtime_port,
)
from chaeksas.tool_ui.settings import ToolSettings

log = logging.getLogger(__name__)

LOCAL_HOST = "127.0.0.1"
#: `health`를 묻는 제한 시간 (초) — 창을 그리는 자리에서 부르므로 짧게.
HEALTH_TIMEOUT_S = 1.0

#: 런타임이 답하지 않을 때 (TOL-01). **까닭과 길을 함께 말한다** (U3).
RUNTIME_DOWN = (
    "{label}가 답하지 않습니다 (127.0.0.1:{port}) — PC 실행기를 켜고 PC 실행기 「도구」에서 이 도구를 열면 "
    "PC 실행기가 {label}를 띄웁니다"
)
RUNTIME_UNKNOWN = "이 도구가 쓰는 로컬 런타임({runtime})을 기여한 확장이 없습니다"


def healthy(port: int, path: str, *, timeout_s: float = HEALTH_TIMEOUT_S) -> bool:
    """그 런타임의 `health`가 200으로 답하나 (PC 실행기의 `runtimes.healthy`와 같은 물음)."""
    try:
        answer = httpx.get(f"http://{LOCAL_HOST}:{port}{path}", timeout=timeout_s)
    except httpx.HTTPError:
        return False
    return answer.status_code == 200


@dataclass(frozen=True)
class PlainSettings:
    """`extension_api.Settings` — 확장 설정 칸 + 호스트가 채운 예약 키 (C13)."""

    values: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


def installed_host(off: Iterable[str] = ()) -> ExtensionHost:
    """설치된 확장(엔트리 포인트)을 읽은 호스트. **읽다 실패해도 창은 뜬다.**"""
    host = ExtensionHost(off=off)
    try:
        host.load_entry_points()
    except Exception as e:  # noqa: BLE001 — 확장 때문에 Tool UI가 안 뜨면 고칠 길이 없다
        log.warning("확장을 읽지 못했다: %s", e)
    for failure in host.failures:
        log.warning("확장을 켜지 못했다: %s", failure)
    return host


@dataclass
class ToolHost:
    """Tool UI 한 벌의 확장 — 도구 목록, 도구마다의 바깥 세상, 런타임이 떠 있나."""

    host: ExtensionHost
    settings: ToolSettings = field(default_factory=ToolSettings)
    credentials: ToolCredentials = field(default_factory=ToolCredentials)
    #: PC 실행기 데이터 폴더 — **읽기만** 한다 (런타임 자리·앱 주소 명부·끈 확장).
    bot_ui_root: Path = field(default_factory=bot_ui_data_dir)
    #: Tool UI 제 데이터 폴더 (`storage.dir`가 여기 아래다).
    root: Path = field(default_factory=data_dir)
    #: `health`를 묻는 자리 — 시험이 바꿔 끼운다.
    probe: Callable[[int, str], bool] = healthy

    @classmethod
    def load(
        cls,
        *,
        settings: ToolSettings | None = None,
        bot_ui_root: Path | None = None,
        root: Path | None = None,
        loader: Callable[[Iterable[str]], ExtensionHost] = installed_host,
    ) -> ToolHost:
        """설치된 확장을 읽는다 — **PC 실행기에서 끈 것은 빼고** (ADR-0043·0077)."""
        bot_ui = bot_ui_root or bot_ui_data_dir()
        return cls(
            host=loader(bot_ui_turned_off(root=bot_ui)),
            settings=settings if settings is not None else ToolSettings.load(),
            bot_ui_root=bot_ui,
            root=root or data_dir(),
        )

    # ── 도구 ──

    def tools(self) -> list[Contribution[Tool]]:
        """도구들 — **확장 이름순**, 그 안에서 `label`순 (TOL-01 「도구」 메뉴)."""
        return sorted(self.host.tools(), key=lambda c: (c.extension_id, c.value.label))

    def find(self, extension_id: str, tool_id: str) -> Contribution[Tool] | None:
        return next(
            (c for c in self.host.tools() if c.extension_id == extension_id and c.value.id == tool_id), None
        )

    def make(self, extension_id: str, tool_id: str) -> ToolUiTool:
        """탭을 열 때마다 새로 만든다 (`ExtensionHost.tool`)."""
        return self.host.tool(extension_id, tool_id)

    # ── 런타임 (빌려 쓴다) ──

    def _runtime(self, runtime_id: str) -> LocalRuntime | None:
        return next((c.value for c in self.host.local_runtimes() if c.value.id == runtime_id), None)

    def runtime_port(self, runtime: LocalRuntime) -> int:
        """PC 실행기가 남긴 포트 → 그 런타임의 설정 환경변수 → 기여의 기본 포트 (Studio와 같은 순서)."""
        found = runtime_port(runtime.id, root=self.bot_ui_root)
        if found:
            return found
        raw = os.environ.get(runtime.port_setting) if runtime.port_setting else None
        if raw and raw.isdigit():
            return int(raw)
        return runtime.default_port or 0

    def runtime_problem(self, runtime_id: str | None) -> str | None:
        """그 런타임을 **지금 쓸 수 있나** — 쓸 수 있으면 `None`, 아니면 사람에게 보일 한 줄."""
        if not runtime_id:
            return None
        runtime = self._runtime(runtime_id)
        if runtime is None:
            return RUNTIME_UNKNOWN.format(runtime=runtime_id)
        port = self.runtime_port(runtime)
        if runtime.health and not self.probe(port, runtime.health):
            return RUNTIME_DOWN.format(label=runtime.label, port=port)
        return None

    def runtime_values(self, runtime_ids: Iterable[str]) -> dict[str, Any]:
        """예약 키 `runtime.<id>.*` (C13) — **PC 실행기가 띄운 것**을 가리킨다.

        `state`는 Tool UI가 감시하지 않으므로 「답했다」를 `running`으로만 적는다(모르면 `off`).
        """
        out: dict[str, Any] = {}
        for runtime_id in runtime_ids:
            runtime = self._runtime(runtime_id)
            if runtime is None:
                continue
            head = f"{RESERVED_CONFIG_PREFIX}{runtime_id}"
            port = self.runtime_port(runtime)
            out[f"{head}.port"] = port
            if runtime.token_dir:
                out[f"{head}.token_dir"] = str(runtime_folder(runtime_id, root=self.bot_ui_root))
            up = not runtime.health or self.probe(port, runtime.health)
            out[f"{head}.state"] = "running" if up else "off"
        return out

    # ── 바깥 세상 ──

    def center_url(self) -> str | None:
        """도구가 외부 작업을 올릴 Center — **PC 실행기의 설정을 읽는다** (Tool UI는 Center에 붙지 않는다)."""
        return bot_ui_center_url(root=self.bot_ui_root)

    def storage_dir(self, extension_id: str) -> Path:
        """확장이 자기 파일을 둘 폴더 (C13 `storage.dir`) — **Tool UI 제 자리**다. 비밀은 두지 않는다."""
        found = self.root / "extensions" / extension_id
        found.mkdir(parents=True, exist_ok=True)
        return found

    def values(self, extension_id: str, *, runtime_ids: Iterable[str] = ()) -> dict[str, Any]:
        """확장에게 줄 설정 — **그 확장의 `scope: tool_ui` 칸 + 예약 키**. 비밀은 없다."""
        values: dict[str, Any] = {}
        found = self.host.get(extension_id)
        if found is not None:
            stored = self.settings.extension(extension_id)
            for item in found.manifest.contributes.configuration:
                if item.scope == SCOPE_TOOL_UI and not item.secret:
                    values[item.key] = stored.get(item.key)
        values.update(self.runtime_values(runtime_ids))
        values[CENTER_URL_SETTING] = self.center_url()
        values[STORAGE_DIR_SETTING] = str(self.storage_dir(extension_id))
        return values

    def context(self, extension_id: str, *, runtime_ids: Iterable[str] = ()) -> ExtensionContext:
        """도구에 넘길 바깥 세상 — 호스트는 `tool_ui`다 (C11 `caller.type`도 이것을 쓴다)."""
        return self.host.context(
            extension_id,
            host=HOST_TOOL_UI,
            settings=PlainSettings(values=self.values(extension_id, runtime_ids=tuple(runtime_ids))),
            secrets=ToolSecrets(credentials=self.credentials, extension_id=extension_id),
        )


def parse_spec(spec: str | None) -> tuple[str, str] | None:
    """`<확장>:<도구>` → `(확장, 도구)`. 모양이 아니면 `None` (열지 않는다)."""
    if not spec or ":" not in spec:
        return None
    extension_id, _, tool_id = spec.partition(":")
    extension_id, tool_id = extension_id.strip(), tool_id.strip()
    return (extension_id, tool_id) if extension_id and tool_id else None


__all__ = [
    "HEALTH_TIMEOUT_S",
    "RUNTIME_DOWN",
    "RUNTIME_UNKNOWN",
    "PlainSettings",
    "ToolHost",
    "healthy",
    "installed_host",
    "parse_spec",
]

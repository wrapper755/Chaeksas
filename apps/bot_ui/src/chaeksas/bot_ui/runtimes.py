"""로컬 런타임 — 확장이 기여한 자식 서버를 띄우고 감시한다 (C13, BUI-09, ADR-0024).

지금은 UI 자동화 확장의 **Worker 프로세스** 하나뿐이지만, Bot UI는 그것을 모른다 — 기여
목록(`bot_ui.local_runtimes`)을 읽어 그대로 띄울 뿐이다 (ADR-0018).

- **명령줄은 Bot UI가 만든다.** 확장은 진입점(`entry`)만 준다. 묶은 앱 안에는 콘솔 스크립트가
  없으므로 **자기 실행 파일을 자식으로 다시 띄운다** (`--local-runtime <확장>:<런타임>`).
- 띄우기·끄기·Job Object는 `core.processes`가 한다 (ADR-0023). 여기서 `os.killpg`를 부르지
  않는다.
- **토큰은 파일로만** 준다 (명령줄은 프로세스 목록에 뜬다). 폴더만 넘기고 내용은 자식이 쓴다.
- 떴다고 바로 쓰지 않는다 — `health`가 답할 때까지 기다린다. **「없는데 된 척」하지 않는다.**
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from chaeksas.bot_ui.settings import Settings, data_dir
from chaeksas.contracts import RESERVED_CONFIG_PREFIX, LocalRuntime
from chaeksas.core.extensions import ExtensionHost
from chaeksas.core.processes import ChildProcess, Supervisor

log = logging.getLogger(__name__)

#: 자식에게 주는 깃발 (C13 — `<실행 파일> --local-runtime <확장 id>:<런타임 id>`).
RUNTIME_FLAG = "--local-runtime"
#: 소스에서 돌 때의 모듈 (묶은 앱에서는 실행 파일 자신이다, ADR-0024).
BOT_UI_MODULE = "chaeksas.bot_ui"

#: `health`가 답할 때까지 기다리는 시간과 간격 (초).
READY_TIMEOUT_S = 15.0
READY_POLL_S = 0.2
HEALTH_TIMEOUT_S = 2.0

#: 이 PC에서 띄운 런타임의 주소 — **127.0.0.1 고정** (01-architecture §4).
LOCAL_HOST = "127.0.0.1"


class RuntimeUnavailable(RuntimeError):
    """런타임을 띄우지 못했거나 제때 답하지 않았다. **유틸리티를 열지 않는다.**"""


def frozen() -> bool:
    """설치 파일로 묶인 앱인가 (PyInstaller). 묶였으면 실행 파일 자신을 다시 띄운다."""
    return bool(getattr(sys, "frozen", False))


def runtime_args(spec: str, *, port: int, token_dir: Path | None) -> list[str]:
    """자식 명령줄. **비밀은 싣지 않는다** — 토큰은 자식이 폴더에 쓴다 (C10)."""
    head = [sys.executable] if frozen() else [sys.executable, "-m", BOT_UI_MODULE]
    args = [*head, RUNTIME_FLAG, spec, "--port", str(port)]
    if token_dir is not None:
        args += ["--token-dir", str(token_dir)]
    return args


def token_dir_for(runtime_id: str, *, root: Path | None = None) -> Path:
    """토큰 파일을 둘 폴더. 런타임마다 하나 (현재 사용자 자리 밑이다)."""
    return (root or data_dir()) / "runtimes" / runtime_id


def port_for(runtime: LocalRuntime, settings: Settings) -> int:
    """포트는 **설정에서** 온다 (CLAUDE.md §5 — 코드에 숫자를 적지 않는다)."""
    found = settings.runtime(runtime.id)
    if found is not None:
        return found.port
    if runtime.default_port is None:
        raise RuntimeUnavailable(f"런타임 {runtime.id}의 포트를 알 수 없습니다 (설정도 기본값도 없습니다)")
    return runtime.default_port


def healthy(port: int, path: str, *, timeout_s: float = HEALTH_TIMEOUT_S) -> dict[str, Any] | None:
    """`health`가 답하나. 답하면 그 본문(열린 모양이다), 아니면 `None`."""
    try:
        answer = httpx.get(f"http://{LOCAL_HOST}:{port}{path}", timeout=timeout_s)
    except httpx.HTTPError:
        return None
    if answer.status_code != 200:
        return None
    try:
        body = answer.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@dataclass
class Runtimes:
    """띄운 런타임들. Bot UI 한 벌에 하나다.

    `ensure()`가 「켜져 있고 답한다」까지 책임진다 — 부르는 쪽(유틸리티를 여는 화면)은
    **된 척하는 런타임**을 받지 않는다.
    """

    host: ExtensionHost
    settings: Settings
    supervisors: dict[str, Supervisor] = field(default_factory=dict)
    #: 시험에서 자식 프로세스를 바꿔 끼우는 자리.
    supervisor_factory: Callable[[str, LocalRuntime, int, Path | None], Supervisor] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

    def contributions(self) -> list[tuple[str, LocalRuntime]]:
        return [(c.extension_id, c.value) for c in self.host.local_runtimes()]

    def find(self, runtime_id: str) -> tuple[str, LocalRuntime]:
        for extension_id, runtime in self.contributions():
            if runtime.id == runtime_id:
                return extension_id, runtime
        raise RuntimeUnavailable(f"기여된 로컬 런타임이 아닙니다: {runtime_id}")

    def supervisor(self, runtime_id: str) -> Supervisor:
        """감시자를 만들어 둔다 (**띄우지는 않는다**)."""
        found = self.supervisors.get(runtime_id)
        if found is not None:
            return found
        extension_id, runtime = self.find(runtime_id)
        port = port_for(runtime, self.settings)
        where = token_dir_for(runtime.id) if runtime.token_dir else None
        if where is not None:
            where.mkdir(parents=True, exist_ok=True)
        if self.supervisor_factory is not None:
            made = self.supervisor_factory(extension_id, runtime, port, where)
        else:
            made = Supervisor(
                child=ChildProcess(
                    args=runtime_args(f"{extension_id}:{runtime.id}", port=port, token_dir=where),
                    log_path=data_dir() / "logs" / f"{runtime.id}.log",
                    name=runtime.label,
                )
            )
        self.supervisors[runtime_id] = made
        return made

    def ensure(self, runtime_id: str, *, timeout_s: float = READY_TIMEOUT_S) -> Supervisor:
        """띄우고 **답할 때까지** 기다린다. 못 띄우면 `RuntimeUnavailable`."""
        _, runtime = self.find(runtime_id)
        found = self.supervisor(runtime_id)
        if found.state != "running" or not found.child.alive:
            found.start()
        if found.state != "running":
            raise RuntimeUnavailable(f"{runtime.label}을 띄우지 못했습니다 — {found.last_error or '알 수 없음'}")
        if runtime.health is None:
            return found

        port = port_for(runtime, self.settings)
        until = self.clock() + timeout_s
        while self.clock() < until:
            if healthy(port, runtime.health) is not None:
                return found
            if not found.child.alive:
                break
            self.sleep(READY_POLL_S)
        found.stop()
        raise RuntimeUnavailable(
            f"{runtime.label}이 제때 답하지 않았습니다 (포트 {port}) — 포트가 쓰이고 있는지 보세요"
        )

    def health_of(self, runtime_id: str) -> dict[str, Any] | None:
        """BUI-09가 그릴 내용. 기여가 없거나 답하지 않으면 `None` — **묻는 쪽을 막지 않는다**."""
        try:
            _, runtime = self.find(runtime_id)
        except RuntimeUnavailable:
            return None
        if runtime.health is None:
            return None
        return healthy(port_for(runtime, self.settings), runtime.health)

    def stop_all(self) -> None:
        """종료 순서의 마지막 (BUI-01 10번) — 트리째 끈다 (ADR-0023)."""
        for supervisor in self.supervisors.values():
            supervisor.stop()

    def tick(self) -> None:
        """하트비트마다. 죽었으면 감시자가 다시 띄운다."""
        for supervisor in self.supervisors.values():
            supervisor.tick()

    def host_settings(self, runtime_ids: tuple[str, ...]) -> dict[str, Any]:
        """확장에게 줄 **예약 설정 키** (C13) — 띄운 런타임이 어디 있는지.

        확장이 포트를 다시 계산하거나 토큰 파일 자리를 추측하지 않게 한다.
        """
        out: dict[str, Any] = {}
        for runtime_id in runtime_ids:
            try:
                _, runtime = self.find(runtime_id)
            except RuntimeUnavailable:
                continue
            head = f"{RESERVED_CONFIG_PREFIX}{runtime_id}"
            out[f"{head}.port"] = port_for(runtime, self.settings)
            if runtime.token_dir:
                out[f"{head}.token_dir"] = str(token_dir_for(runtime_id))
            found = self.supervisors.get(runtime_id)
            out[f"{head}.state"] = found.state if found is not None else "off"
        return out


@dataclass(frozen=True)
class HostSettings:
    """`extension_api.Settings` — 확장 자기 설정 + 호스트가 채운 예약 키 (C13)."""

    values: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


def serve(spec: str, *, port: int, token_dir: Path | None, host: ExtensionHost | None = None) -> int:
    """`--local-runtime <확장 id>:<런타임 id>`로 다시 뜬 자식이 도는 길 (C13·ADR-0024).

    **Qt를 띄우지 않는다** — 화면 없는 서버로 돌다가 종료 코드를 돌려준다.
    """
    extension_id, _, runtime_id = spec.partition(":")
    if not extension_id or not runtime_id:
        log.error("--local-runtime은 <확장 id>:<런타임 id> 모양이다: %r", spec)
        return 2
    found = host
    if found is None:
        found = ExtensionHost()
        found.load_entry_points()
    entry = found.local_runtime(extension_id, runtime_id)
    return int(entry(port=port, token_dir=token_dir))


__all__ = [
    "BOT_UI_MODULE",
    "LOCAL_HOST",
    "READY_TIMEOUT_S",
    "RUNTIME_FLAG",
    "HostSettings",
    "RuntimeUnavailable",
    "Runtimes",
    "frozen",
    "healthy",
    "port_for",
    "runtime_args",
    "serve",
    "token_dir_for",
]

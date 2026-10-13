"""서버 실행기 설정 — 환경변수 `CHK_SERVER_RUNNER__*` (ADR-0011).

**화면이 없으므로 설정 파일도 없다** — 서버는 환경변수·compose로 설정한다 (Bot UI의 BUI-03에
해당하는 자리가 없다). 기본값은 여기 한 곳에만 둔다 (`docs/04-setup.md` §6).

**비밀은 여기 두지 않는다** — Center API 키는 `credentials.py`가 환경변수나 OS 비밀 저장소에서
읽는다 (CLAUDE.md §5).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

from chaeksas.contracts.server_runner import DEFAULT_MAX_CONCURRENCY

#: 기본값의 원본은 `docs/04-setup.md` §6의 표다.
DEFAULT_CENTER_URL = "http://localhost:8800"
#: 하트비트 주기의 **첫 값**. 그다음은 응답의 `next_heartbeat_s`를 따른다 (C12).
DEFAULT_HEARTBEAT_S = 10
#: 닿지 못했을 때 다시 걸기까지 (ADR-0007 — 부르는 쪽이 다시 온다). 주기보다 길게 둔다.
DEFAULT_RETRY_S = 30

ENV_PREFIX = "CHK_SERVER_RUNNER__"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def data_dir() -> Path:
    """데이터 위치. Linux `~/.local/share`, Windows `%LOCALAPPDATA%` (CLAUDE.md §5).

    서버는 Linux가 주 환경이지만(ADR-0003) 경로를 하드코딩하지 않는다 — 개발 PC가 Windows일
    수 있고, `platformdirs`가 그 차이를 덮는다.
    """
    override = _env("DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "server-runner"


@dataclass(frozen=True)
class Settings:
    """실행기 한 벌의 설정. `from_env()`로 만든다."""

    center_url: str = DEFAULT_CENTER_URL
    #: 사람이 알아볼 이름 (C12 `name`). 비우면 호스트 이름을 쓴다.
    name: str = ""
    #: 한 번에 도는 실행 수의 상한 (C12 `max_concurrency`, 기본 10).
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    heartbeat_s: int = DEFAULT_HEARTBEAT_S
    retry_s: int = DEFAULT_RETRY_S
    data_path: Path = field(default_factory=data_dir)

    @property
    def runs_dir(self) -> Path:
        """실행 기록이 쌓이는 곳 (C3 — 파일이 원본이다)."""
        return self.data_path / "runs"

    @property
    def state_db(self) -> Path:
        """기다리는 실행의 스냅샷 저장소 (ADR-0054 — SQLite 한 파일)."""
        return self.data_path / "state.sqlite3"

    @classmethod
    def from_env(cls) -> Settings:
        limit = _env("MAX_CONCURRENCY")
        heartbeat = _env("HEARTBEAT_S")
        retry = _env("RETRY_S")
        return cls(
            center_url=_env("CENTER_URL") or DEFAULT_CENTER_URL,
            name=_env("NAME") or "",
            max_concurrency=max(1, int(limit)) if limit else DEFAULT_MAX_CONCURRENCY,
            heartbeat_s=max(1, int(heartbeat)) if heartbeat else DEFAULT_HEARTBEAT_S,
            retry_s=max(1, int(retry)) if retry else DEFAULT_RETRY_S,
            data_path=data_dir(),
        )


__all__ = [
    "DEFAULT_CENTER_URL",
    "DEFAULT_HEARTBEAT_S",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_RETRY_S",
    "ENV_PREFIX",
    "Settings",
    "data_dir",
]

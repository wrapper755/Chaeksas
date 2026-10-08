"""Center 설정 — 환경변수 `CHK_CENTER__*` (ADR-0011).

**포트·경로를 코드에 직접 쓰지 않는다.** 기본값은 여기 한 곳에만 둔다 (`docs/04-setup.md` §6).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

#: 기본 포트 (`docs/04-setup.md` §6의 표가 원본이다).
DEFAULT_PORT = 8800
#: 하트비트 주기와 온라인 판정 (C4).
DEFAULT_HEARTBEAT_S = 30
ONLINE_WITHIN_S = 90
#: 요청 크기 한도 (C4 — 256 KB), 패키지 zip 한도.
MAX_REQUEST_KB = 256
MAX_PACKAGE_MB = 200

#: 서비스 앱 상태·manifest를 다시 읽는 간격 (C7 §리소스 모으는 방식).
#: 「새로 고침」은 이것을 무시하고 바로 읽는다.
RESOURCE_STATUS_S = 60
RESOURCE_MANIFEST_S = 600
#: 확장 기여 자원 카탈로그를 다시 읽는 간격 (C7 — 5분).
RESOURCE_CATALOG_S = 300
#: Center가 서비스 앱을 읽을 때 기다리는 시간. 짧게 — 한 앱이 느려도 목록이 멈추면 안 된다.
RESOURCE_TIMEOUT_S = 5.0

ENV_PREFIX = "CHK_CENTER__"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def data_dir() -> Path:
    """사용자·서버 데이터 위치. Windows `%LOCALAPPDATA%`, Linux `~/.local/share` (CLAUDE.md §5)."""
    override = _env("DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "center"


@dataclass(frozen=True)
class Settings:
    """Center 한 벌의 설정. `from_env()`로 만든다."""

    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"  # noqa: S104 — 서버다. 컨테이너·역방향 프록시 뒤에 둔다
    db_path: Path = field(default_factory=lambda: data_dir() / "center.sqlite3")
    #: 패키지 zip을 두는 곳. **DB에는 메타데이터만** 둔다 (01-architecture §7).
    package_dir: Path = field(default_factory=lambda: data_dir() / "packages")
    heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
    #: 관리자·읽기 토큰. **비어 있으면 그 권한으로 부를 수 없다** (C5 권한표).
    #: 코드·설정 파일에 넣지 않고 환경변수로 준다 (CLAUDE.md §5).
    admin_token: str | None = None
    read_token: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        port = _env("PORT")
        db = _env("DB_PATH")
        packages = _env("PACKAGE_DIR")
        return cls(
            port=int(port) if port else DEFAULT_PORT,
            host=_env("HOST") or "0.0.0.0",  # noqa: S104
            db_path=Path(db) if db else data_dir() / "center.sqlite3",
            package_dir=Path(packages) if packages else data_dir() / "packages",
            heartbeat_interval_s=int(_env("HEARTBEAT_INTERVAL_S") or DEFAULT_HEARTBEAT_S),
            admin_token=_env("ADMIN_TOKEN"),
            read_token=_env("READ_TOKEN"),
        )

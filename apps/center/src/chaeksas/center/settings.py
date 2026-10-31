"""Center 설정 — 환경변수 `CHK_CENTER__*` (ADR-0011).

**포트·경로를 코드에 직접 쓰지 않는다.** 기본값은 여기 한 곳에만 둔다 (`docs/04-setup.md` §6).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import platformdirs

#: 기본 포트 (`docs/04-setup.md` §6의 표가 원본이다).
DEFAULT_PORT = 8800
#: 하트비트 주기와 온라인 판정 (C4).
DEFAULT_HEARTBEAT_S = 30
ONLINE_WITHIN_S = 90
#: 서버 실행기의 주기 — **더 촘촘하다** (C12 기본 10초). 오프라인 판정은 계약이 쥔다
#: (`contracts.server_runner.OFFLINE_AFTER_S`) — 두 자리에 적으면 갈라진다.
DEFAULT_RUNNER_HEARTBEAT_S = 10
#: 요청 크기 한도 (C4 — 256 KB), 패키지 zip 한도.
MAX_REQUEST_KB = 256
MAX_PACKAGE_MB = 200


ENV_PREFIX = "CHK_CENTER__"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def data_dir() -> Path:
    """사용자·서버 데이터 위치. Windows `%LOCALAPPDATA%`, Linux `~/.local/share` (CLAUDE.md §5)."""
    override = _env("DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "center"


#: 외부 작업 롱폴링을 함께 물고 있을 수 있는 수 (C15 「정한 것」 — 올리는 쪽·일꾼을 함께 센다).
DEFAULT_EXTERNAL_TASK_WAITERS = 200

#: 타이머 시작의 cron을 읽는 벽시계 (ADR-0110 §3) — Center 한 벌에 하나다. IANA 이름이다.
DEFAULT_TIMEZONE = "Asia/Seoul"



@dataclass(frozen=True)
class Settings:
    """Center 한 벌의 설정. `from_env()`로 만든다."""

    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"  # noqa: S104 — 서버다. 컨테이너·역방향 프록시 뒤에 둔다
    db_path: Path = field(default_factory=lambda: data_dir() / "center.sqlite3")
    #: 패키지 zip을 두는 곳. **DB에는 메타데이터만** 둔다 (01-architecture §7).
    package_dir: Path = field(default_factory=lambda: data_dir() / "packages")
    heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
    #: 서버 실행기에게 내려 줄 주기 (C12 — `next_heartbeat_s`).
    runner_heartbeat_s: int = DEFAULT_RUNNER_HEARTBEAT_S
    #: 관리자·읽기 토큰. **비어 있으면 그 권한으로 부를 수 없다** (C5 권한표).
    #: 코드·설정 파일에 넣지 않고 환경변수로 준다 (CLAUDE.md §5).
    admin_token: str | None = None
    read_token: str | None = None
    #: 같이 배포된 서버 실행기를 승인 없이 들이는 비밀 (C12 §등록 요청과 승인, ADR-0117). 비면 그 길이 닫힌다.
    server_runner_join_token: str | None = None
    #: 첫 관리자 계정 (ADR-0090 §2) — **계정이 하나도 없을 때만** 쓴다. 비밀번호를 비우면 Center가
    #: 만들어 로그와 데이터 폴더의 파일에 둔다. 아이디를 비우면 `admin`이다.
    first_admin_username: str | None = None
    first_admin_password: str | None = None
    #: 외부 작업 롱폴링 상한 (C15) — 넘으면 503 `too_many_waiters`.
    external_task_max_waiters: int = DEFAULT_EXTERNAL_TASK_WAITERS
    #: 타이머 시작의 시간대 (ADR-0110 §3). 풀 수 없으면 Center가 뜨지 않는다 (`zone()`).
    timezone: str = DEFAULT_TIMEZONE
    #: 일꾼 폴더 (ADR-0122) — Center가 **뜰 때** 여기의 `<이름>.consumer.json`으로 일꾼을 들인다(일꾼이 들어오는
    #: 유일한 길). `from_env()`는 적지 않으면 `<데이터>/consumers`를 쓴다. 비면 닫힌다(시험).
    consumers_dir: Path | None = None
    #: `consumers_dir`를 사람이 적었나 — 적었는데 폴더가 없으면 사유를 남기고, 기본 자리가 없으면 조용히 지나간다.
    consumers_dir_explicit: bool = True

    def zone(self) -> tzinfo:
        """일정의 시간대. **풀 수 없으면 실패한다** — 틀린 시간대로 조용히 도는 일정은 없다."""
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"{ENV_PREFIX}TIMEZONE 「{self.timezone}」을 풀 수 없다 (IANA 이름이어야 한다)") from e

    def data_folder(self) -> Path | None:
        """DB가 있는 폴더 — 첫 비밀번호 파일을 둔다. 메모리 DB면 `None`."""
        return None if str(self.db_path) == ":memory:" else self.db_path.parent

    @classmethod
    def from_env(cls) -> Settings:
        port = _env("PORT")
        db = _env("DB_PATH")
        packages = _env("PACKAGE_DIR")
        consumers_dir = _env("CONSUMERS_DIR")
        return cls(
            port=int(port) if port else DEFAULT_PORT,
            host=_env("HOST") or "0.0.0.0",  # noqa: S104
            db_path=Path(db) if db else data_dir() / "center.sqlite3",
            package_dir=Path(packages) if packages else data_dir() / "packages",
            heartbeat_interval_s=int(_env("HEARTBEAT_INTERVAL_S") or DEFAULT_HEARTBEAT_S),
            runner_heartbeat_s=int(_env("RUNNER_HEARTBEAT_S") or DEFAULT_RUNNER_HEARTBEAT_S),
            admin_token=_env("ADMIN_TOKEN"),
            read_token=_env("READ_TOKEN"),
            server_runner_join_token=_env("SERVER_RUNNER_JOIN_TOKEN"),
            first_admin_username=_env("FIRST_ADMIN__USERNAME"),
            first_admin_password=_env("FIRST_ADMIN__PASSWORD"),
            external_task_max_waiters=int(
                _env("EXTERNAL_TASKS__MAX_WAITERS") or DEFAULT_EXTERNAL_TASK_WAITERS
            ),
            timezone=_env("TIMEZONE") or DEFAULT_TIMEZONE,
            consumers_dir=Path(consumers_dir) if consumers_dir else data_dir() / "consumers",
            consumers_dir_explicit=bool(consumers_dir),
        )

"""서버 실행기 설정 — 환경변수 `CHK_SERVER_RUNNER__*` (ADR-0011).

**화면이 없으므로 설정 파일도 없다** — 서버는 환경변수·compose로 설정한다 (PC 실행기의 BUI-03에
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
from chaeksas.core.senders import (
    DEFAULT_ATTACHMENT_MB,
    DEFAULT_SMTP_TIMEOUT_S,
    SECURITY_STARTTLS,
    SmtpConfig,
    WebhookConfig,
)

#: 기본값의 원본은 `docs/04-setup.md` §6의 표다.
DEFAULT_CENTER_URL = "http://localhost:8800"
#: 하트비트 주기의 **첫 값**. 그다음은 응답의 `next_heartbeat_s`를 따른다 (C12).
DEFAULT_HEARTBEAT_S = 10
#: 닿지 못했을 때 다시 걸기까지 (ADR-0007 — 부르는 쪽이 다시 온다). 주기보다 길게 둔다.
DEFAULT_RETRY_S = 30
#: 외부 작업을 **이만큼 기다려 끝나지 않으면** 기다림으로 넘기고 자리를 놓는다 (초, ADR-0103).
DEFAULT_PARK_AFTER_S = 20.0
#: 기본 모델 (ADR-0027). **이 앱의 기본값은 이 앱이 가진다** — PC 실행기의 것을 import하지 않는다
#: (앱끼리 import하지 않는다). 둘이 어긋나면 `docs/04-setup.md` §6의 표가 원본이다.
DEFAULT_LLM_MODEL = "qwen2.5:7b"

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
    #: 모델 주소·이름 (ADR-0027). **비우면 AI 태스크가 `NoLlm`으로 실패한다** — 조용히
    #: 넘어가지 않는다. 키는 여기 없다 (`credentials.llm_api_key()`).
    llm_base_url: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    #: 읽기·쓰기 허용 폴더 (ADR-0032). **기본은 비어 있고** 운영자가 환경변수로 열어야 한다 —
    #: 출력 폴더 밖은 적어 주지 않으면 `PathDenied`다. 쓸 수 있는 곳은 읽기도 된다.
    readable_dirs: tuple[Path, ...] = ()
    writable_dirs: tuple[Path, ...] = ()
    #: 보내기 (ADR-0059). **비우면 `chk:email`이 보내지 않고 실패한다** — 조용히 넘어가지 않는다.
    #: 비밀번호는 여기 없다 (`credentials.smtp_password()`).
    smtp_host: str = ""
    smtp_port: int = 0
    smtp_security: str = SECURITY_STARTTLS
    smtp_username: str = ""
    smtp_sender: str = ""
    smtp_timeout_s: float = DEFAULT_SMTP_TIMEOUT_S
    smtp_attachment_mb: float = DEFAULT_ATTACHMENT_MB
    #: 웹훅을 보낼 수 있는 호스트. **기본은 비어 있고 비면 아무 데도 보내지 않는다** (ADR-0059 §2).
    #: **사설망을 여는 스위치는 두지 않는다** — 한 번 켜면 모든 BPM 프로세스의 모든 웹훅에 적용된다.
    webhook_allowed_hosts: tuple[str, ...] = ()
    #: 외부 작업을 이만큼 기다려 끝나지 않으면 기다림으로 넘긴다 (ADR-0103). 0이면 바로 넘긴다.
    park_after_s: float = DEFAULT_PARK_AFTER_S

    def smtp(self) -> SmtpConfig:
        """보내기 설정 한 벌 — **PC 실행기와 같은 모양**이다 (`core.senders`)."""
        return SmtpConfig(
            host=self.smtp_host,
            port=self.smtp_port,
            security=self.smtp_security,
            username=self.smtp_username,
            sender=self.smtp_sender,
            timeout_s=self.smtp_timeout_s,
            max_attachment_mb=self.smtp_attachment_mb,
        )

    def webhook(self) -> WebhookConfig:
        return WebhookConfig(allowed_hosts=self.webhook_allowed_hosts)

    def ready_settings(self) -> tuple[str, ...]:
        """갖춰진 설정 이름들 (C1 `requires.settings`) — 사전 점검이 이것으로 막는다."""
        return ("smtp",) if self.smtp().configured else ()

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
            llm_base_url=_env("LLM__BASE_URL") or "",
            llm_model=_env("LLM__MODEL") or DEFAULT_LLM_MODEL,
            readable_dirs=_dirs(_env("READABLE_DIRS")),
            writable_dirs=_dirs(_env("WRITABLE_DIRS")),
            smtp_host=_env("SMTP__HOST") or "",
            smtp_port=int(_env("SMTP__PORT") or 0),
            smtp_security=_env("SMTP__SECURITY") or SECURITY_STARTTLS,
            smtp_username=_env("SMTP__USERNAME") or "",
            smtp_sender=_env("SMTP__FROM") or "",
            smtp_timeout_s=float(_env("SMTP__TIMEOUT_S") or DEFAULT_SMTP_TIMEOUT_S),
            smtp_attachment_mb=float(_env("SMTP__ATTACHMENT_MB") or DEFAULT_ATTACHMENT_MB),
            # 여럿은 **쉼표**로 가른다 — 호스트 이름에는 `os.pathsep`(`:`)이 들어갈 수 있다
            # (`host:port`를 적는 실수를 섞지 않으려고 폴더 목록과 규칙을 다르게 둔다).
            webhook_allowed_hosts=_hosts(_env("WEBHOOK__ALLOWED_HOSTS")),
            park_after_s=max(0.0, float(_env("PARK_AFTER_S") or DEFAULT_PARK_AFTER_S)),
        )


def _dirs(raw: str | None) -> tuple[Path, ...]:
    """`os.pathsep`으로 가른 폴더 목록 (Linux `:`, Windows `;`).

    **빈 조각은 버린다** — 끝에 구분자가 하나 붙었다고 현재 폴더(`Path("")`)가 열리면 안 된다.
    """
    if not raw:
        return ()
    return tuple(Path(one) for one in raw.split(os.pathsep) if one.strip())


def _hosts(raw: str | None) -> tuple[str, ...]:
    """쉼표로 가른 호스트 목록. 빈 조각·공백은 버린다."""
    if not raw:
        return ()
    return tuple(one.strip() for one in raw.split(",") if one.strip())


__all__ = [
    "DEFAULT_CENTER_URL",
    "DEFAULT_HEARTBEAT_S",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_RETRY_S",
    "ENV_PREFIX",
    "Settings",
    "data_dir",
]

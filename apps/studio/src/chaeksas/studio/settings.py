"""Studio 설정 — 환경변수 `CHK_STUDIO__*` (ADR-0011), 값은 설정 파일에 저장 (STU-10).

**포트·경로를 코드에 직접 쓰지 않는다.** 기본값은 여기 한 곳에만 둔다 (`docs/04-setup.md` §6).
**비밀은 여기 두지 않는다** — Center API 키·서비스 앱 키·모델 키는 OS 비밀 저장소다 (CLAUDE.md §5).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import platformdirs

ENV_PREFIX = "CHK_STUDIO__"

#: 기본값의 원본은 `docs/04-setup.md` §6의 표다.
DEFAULT_CENTER_URL = "http://localhost:8800"
#: Studio 시험 수신기 (케이스의 `$test_receiver`가 가리키는 곳, C14).
DEFAULT_RECEIVER_PORT = 8791
#: 모델 — 주소만 설정에 두고 **키는 비밀 저장소**다 (ADR-0027).
DEFAULT_LLM_BASE_URL = "http://localhost:11434"
DEFAULT_LLM_MODEL = "qwen2.5:7b"
#: 시험 실행 한 케이스의 시간 제한 (C14 시험 케이스 형식).
DEFAULT_CASE_TIMEOUT_S = 300

APP_NAME = "Chaeksas"
APP_AUTHOR = "Chaeksas"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def data_dir() -> Path:
    """사용자 데이터 위치 (Windows `%LOCALAPPDATA%`, Linux `~/.local/share`)."""
    override = _env("DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR)) / "studio"


@dataclass(frozen=True)
class ServiceKeyRef:
    """STU-10 「서비스 앱 키」의 한 줄 — **이름만**이다. 값은 OS 비밀 저장소에 있다 (ADR-0013)."""

    ref: str
    app_id: str = ""


@dataclass(frozen=True)
class Settings:
    """STU-10. 환경변수가 **파일보다 세다** (개발·CI에서 덮어쓰기 쉬우라고)."""

    data_dir: Path = field(default_factory=data_dir)
    center_url: str = DEFAULT_CENTER_URL
    receiver_port: int = DEFAULT_RECEIVER_PORT
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    llm_model: str = DEFAULT_LLM_MODEL
    case_timeout_s: int = DEFAULT_CASE_TIMEOUT_S
    #: 파일 목록 태스크가 들여다볼 수 있는 폴더 (ADR-0026 — 주지 않으면 출력 폴더만).
    readable_dirs: tuple[Path, ...] = ()
    #: 출력 폴더 **밖에 쓸 수 있는** 폴더 (ADR-0032). 기본은 비어 있다.
    writable_dirs: tuple[Path, ...] = ()
    #: 마지막으로 연 정의 (STU-01 — 시작하면 다시 연다).
    last_opened: str = ""
    #: STU-10 「서비스 앱 키」의 줄들 (참조 이름·서비스 앱). **값은 여기 없다.**
    service_keys: tuple[ServiceKeyRef, ...] = ()
    #: STU-15에서 **사람이 꺼 둔** 확장 id ([ADR-0043](../../../../../docs/decisions/0043-turned-off-extensions.md)).
    #: **Studio의 것이다** — Bot UI는 제 설정에 따로 둔다 (개발 도구의 실험이 현장 실행을 멈추지
    #: 않는다). 판은 적지 않는다 — 올려도 꺼 둔 채로 있는 것이 사람의 뜻이다.
    disabled_extensions: tuple[str, ...] = ()

    @property
    def workspace_dir(self) -> Path:
        """BPM 프로세스가 사는 곳 (STU-02 탐색기가 읽는다)."""
        return self.data_dir / "workspace"

    @property
    def outputs_dir(self) -> Path:
        """시험 실행이 파일을 쓰는 곳 (ADR-0026 출력 폴더의 뿌리)."""
        return self.data_dir / "outputs"

    @property
    def path(self) -> Path:
        return self.data_dir / "settings.json"

    # ── 읽고 쓰기 ──

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        found = cls()
        file = path or found.path
        if file.is_file():
            try:
                raw = json.loads(file.read_text(encoding="utf-8"))
            except ValueError:
                raw = {}
            found = found.merged(raw)
        return found.from_env()

    def merged(self, raw: dict[str, Any]) -> Settings:
        known = {
            "center_url": str,
            "receiver_port": int,
            "llm_base_url": str,
            "llm_model": str,
            "case_timeout_s": int,
            "last_opened": str,
        }
        values = {name: kind(raw[name]) for name, kind in known.items() if name in raw}
        for name in ("readable_dirs", "writable_dirs"):
            if name in raw:
                values[name] = tuple(Path(p) for p in raw[name])
        if isinstance(raw.get("disabled_extensions"), list):
            values["disabled_extensions"] = tuple(
                str(one) for one in raw["disabled_extensions"] if isinstance(one, str) and one
            )
        if isinstance(raw.get("service_keys"), list):
            values["service_keys"] = tuple(
                ServiceKeyRef(ref=str(one.get("ref") or ""), app_id=str(one.get("app_id") or ""))
                for one in raw["service_keys"]
                if isinstance(one, dict) and one.get("ref")
            )
        return replace(self, **values)

    def from_env(self) -> Settings:
        dirs = _env("READABLE_DIRS")
        writable = _env("WRITABLE_DIRS")
        return replace(
            self,
            center_url=_env("CENTER__URL", self.center_url) or self.center_url,
            receiver_port=_env_int("RECEIVER__PORT", self.receiver_port),
            llm_base_url=_env("LLM__BASE_URL", self.llm_base_url) or self.llm_base_url,
            llm_model=_env("LLM__MODEL", self.llm_model) or self.llm_model,
            case_timeout_s=_env_int("CASE_TIMEOUT_S", self.case_timeout_s),
            readable_dirs=(
                tuple(Path(p) for p in dirs.split(os.pathsep) if p.strip()) if dirs else self.readable_dirs
            ),
            writable_dirs=(
                tuple(Path(p) for p in writable.split(os.pathsep) if p.strip())
                if writable
                else self.writable_dirs
            ),
        )

    def save(self, path: Path | None = None) -> Path:
        file = path or self.path
        file.parent.mkdir(parents=True, exist_ok=True)
        skip = ("data_dir", "readable_dirs", "writable_dirs", "service_keys")
        body = {k: v for k, v in asdict(self).items() if k not in skip}
        body["service_keys"] = [{"ref": one.ref, "app_id": one.app_id} for one in self.service_keys]
        body["readable_dirs"] = [p.as_posix() for p in self.readable_dirs]
        body["writable_dirs"] = [p.as_posix() for p in self.writable_dirs]
        file.write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        return file


__all__ = [
    "APP_AUTHOR",
    "APP_NAME",
    "DEFAULT_CASE_TIMEOUT_S",
    "DEFAULT_CENTER_URL",
    "DEFAULT_LLM_BASE_URL",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_RECEIVER_PORT",
    "ENV_PREFIX",
    "Settings",
    "data_dir",
]

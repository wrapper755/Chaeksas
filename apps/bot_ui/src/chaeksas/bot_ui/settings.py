"""Bot UI 설정 — 환경변수 `CHK_BOT_UI__*` (ADR-0011), 값은 설정 파일에 저장 (BUI-03).

**포트·경로를 코드에 직접 쓰지 않는다.** 기본값은 여기 한 곳에만 둔다 (`docs/04-setup.md` §6).
**비밀은 여기 두지 않는다** — Center API 키는 OS 비밀 저장소다 (`secrets.py`, CLAUDE.md §5).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import platformdirs

#: 기본값의 원본은 `docs/04-setup.md` §6의 표다.
DEFAULT_CENTER_URL = "http://localhost:8800"
DEFAULT_WORKER_PORT = 8899
DEFAULT_WEBHOOK_PORT = 8790
#: 대기열 크기 (ADR-0014 — 실행 자리는 1로 고정이라 설정이 없다).
DEFAULT_QUEUE_MAX = 20

#: 모델 이름의 기본값 (주소는 비어 있다 — 사람이 넣어야 AI 태스크가 돈다).
DEFAULT_LLM_MODEL = "qwen2.5:7b"

ENV_PREFIX = "CHK_BOT_UI__"

#: 로컬 런타임 시작 방식 (BUI-03 「로컬 런타임」).
START_WHEN_NEEDED = "when_needed"
START_ALWAYS = "always"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def data_dir() -> Path:
    """사용자 데이터 위치. Windows `%LOCALAPPDATA%`, Linux `~/.local/share` (CLAUDE.md §5)."""
    override = _env("DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "bot-ui"


@dataclass(frozen=True)
class ServiceKeyRef:
    """BUI-10에 등록한 키 참조 하나 — **이름만** 둔다 (값은 OS 비밀 저장소다, ADR-0013).

    설치된 Bot의 매니페스트에서도 참조를 읽을 수 있지만(C1 `requires.service_apps`), 그것만으로는
    부족하다: 비밀 저장소는 **목록을 뽑을 수 없어서** 쓰는 Bot이 없는 참조는 화면에 뜨지 않고,
    지울 수도 없게 된다 (보이지 않는 키가 남는다). Studio의 `Settings.service_keys`와 같은 꼴이다.
    """

    ref: str
    app_id: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {"ref": self.ref, "app_id": self.app_id}


@dataclass(frozen=True)
class RuntimeSettings:
    """로컬 런타임 하나의 설정 (BUI-03). 지금은 Worker 프로세스뿐이다 (확장이 기여한다)."""

    runtime_id: str
    port: int
    start: str = START_WHEN_NEEDED

    def to_json_dict(self) -> dict[str, Any]:
        return {"runtime_id": self.runtime_id, "port": self.port, "start": self.start}


@dataclass(frozen=True)
class Settings:
    """Bot UI 한 벌의 설정.

    `load()`로 파일에서 읽고, 환경변수가 **덮어쓴다** (CI·개발에서 편하게). 저장은 `save()`.
    """

    center_url: str = DEFAULT_CENTER_URL
    #: 표시 이름 (기본: PC 이름). C4 `name`.
    name: str | None = None
    autostart: bool = True
    #: 결재를 Center로 올린다 (BUI-03 「실행」 — BPM 프로세스가 「Bot UI 설정을 따름」일 때만).
    remote_approval: bool = False
    signed_only: bool = True
    queue_max: int = DEFAULT_QUEUE_MAX
    webhook_port: int = DEFAULT_WEBHOOK_PORT
    webhook_external: bool = False
    #: 모델 (BUI-03 「모델」, ADR-0027). **비우면 AI 태스크가 돌지 않는다** — 키는 설정 파일이
    #: 아니라 OS 비밀 저장소에 둔다 (CLAUDE.md §5).
    llm_base_url: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    #: Bot이 **읽을 수 있는 폴더** (BUI-03 「파일」, ADR-0026). 비어 있으면 아무것도 못 읽는다.
    readable_dirs: tuple[Path, ...] = ()
    #: Bot이 출력 폴더 **밖에 쓸 수 있는 폴더** (BUI-03 「파일」, ADR-0032). 기본은 비어 있다 —
    #: 적은 폴더 안의 파일은 Bot이 고칠 수 있다.
    writable_dirs: tuple[Path, ...] = ()
    #: BUI-10에 등록한 서비스 앱 키 참조 (**이름만** — 값은 OS 비밀 저장소다).
    service_keys: tuple[ServiceKeyRef, ...] = ()
    runtimes: tuple[RuntimeSettings, ...] = field(
        default_factory=lambda: (RuntimeSettings(runtime_id="worker", port=DEFAULT_WORKER_PORT),)
    )
    #: 확장별 설정 (BUI-03 「확장별 설정」, C13 `configuration`). `{확장 id: {칸: 값}}`.
    #: **비밀 칸은 여기 들어오지 않는다** — OS 비밀 저장소로 간다 (`credentials.py`).
    extensions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: 사람이 꺼 둔 확장 id (BUI-11, [ADR-0043](../../../../../docs/decisions/0043-turned-off-extensions.md)).
    #: **Studio의 것과 다른 자리다** — 개발 도구에서 끈 것이 현장 Bot을 멈추면 안 된다. 판은
    #: 적지 않는다 (올려도 꺼 둔 채로 있는 것이 사람의 뜻이다).
    disabled_extensions: tuple[str, ...] = ()

    def extension(self, extension_id: str) -> dict[str, Any]:
        return dict(self.extensions.get(extension_id, {}))

    def with_extension(self, extension_id: str, values: Mapping[str, Any]) -> Settings:
        found = {key: dict(value) for key, value in self.extensions.items()}
        found[extension_id] = dict(values)
        return replace(self, extensions=found)

    @property
    def config_path(self) -> Path:
        return data_dir() / "settings.json"

    def runtime(self, runtime_id: str) -> RuntimeSettings | None:
        return next((r for r in self.runtimes if r.runtime_id == runtime_id), None)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "center_url": self.center_url,
            "name": self.name,
            "autostart": self.autostart,
            "remote_approval": self.remote_approval,
            "signed_only": self.signed_only,
            "queue_max": self.queue_max,
            "webhook_port": self.webhook_port,
            "webhook_external": self.webhook_external,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "readable_dirs": [str(one) for one in self.readable_dirs],
            "writable_dirs": [str(one) for one in self.writable_dirs],
            "service_keys": [one.to_json_dict() for one in self.service_keys],
            "runtimes": [r.to_json_dict() for r in self.runtimes],
            "extensions": {key: dict(value) for key, value in self.extensions.items()},
            "disabled_extensions": list(self.disabled_extensions),
        }

    def save(self, path: Path | None = None) -> Path:
        """설정 파일에 쓴다. **비밀은 들어가지 않는다** (CLAUDE.md §5)."""
        target = path or self.config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # 임시 파일에 쓰고 바꿔치운다 — 쓰다 죽어도 설정이 깨지지 않는다.
        staged = target.with_suffix(".json.tmp")
        staged.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        staged.replace(target)
        return target

    def with_env(self) -> Settings:
        """환경변수로 덮어쓴 사본. `CHK_BOT_UI__CENTER__URL`처럼 중첩은 `__`."""
        runtimes = list(self.runtimes)
        worker_port = _env("WORKER__PORT")
        if worker_port:
            runtimes = [replace(r, port=int(worker_port)) if r.runtime_id == "worker" else r for r in runtimes]
        return replace(
            self,
            center_url=_env("CENTER__URL") or self.center_url,
            name=_env("NAME") or self.name,
            autostart=_env_bool("AUTOSTART", self.autostart),
            remote_approval=_env_bool("REMOTE_APPROVAL", self.remote_approval),
            signed_only=_env_bool("SIGNED_ONLY", self.signed_only),
            queue_max=int(_env("QUEUE__MAX") or self.queue_max),
            webhook_port=int(_env("WEBHOOK__PORT") or self.webhook_port),
            webhook_external=_env_bool("WEBHOOK__EXTERNAL", self.webhook_external),
            llm_base_url=_env("LLM__BASE_URL") or self.llm_base_url,
            llm_model=_env("LLM__MODEL") or self.llm_model,
            runtimes=tuple(runtimes),
        )

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> Settings:
        runtimes = tuple(
            RuntimeSettings(
                runtime_id=str(item["runtime_id"]),
                port=int(item["port"]),
                start=str(item.get("start", START_WHEN_NEEDED)),
            )
            for item in raw.get("runtimes", [])
        )
        base = cls()
        return replace(
            base,
            center_url=str(raw.get("center_url") or base.center_url),
            name=raw.get("name") or None,
            autostart=bool(raw.get("autostart", base.autostart)),
            remote_approval=bool(raw.get("remote_approval", base.remote_approval)),
            signed_only=bool(raw.get("signed_only", base.signed_only)),
            queue_max=int(raw.get("queue_max", base.queue_max)),
            webhook_port=int(raw.get("webhook_port", base.webhook_port)),
            webhook_external=bool(raw.get("webhook_external", base.webhook_external)),
            llm_base_url=str(raw.get("llm_base_url") or base.llm_base_url),
            llm_model=str(raw.get("llm_model") or base.llm_model),
            readable_dirs=tuple(Path(one) for one in raw.get("readable_dirs", [])),
            writable_dirs=tuple(Path(one) for one in raw.get("writable_dirs", [])),
            service_keys=tuple(
                ServiceKeyRef(ref=str(one["ref"]), app_id=str(one.get("app_id") or ""))
                for one in raw.get("service_keys", [])
                if isinstance(one, dict) and one.get("ref")
            ),
            runtimes=runtimes or base.runtimes,
            extensions={
                str(key): dict(value)
                for key, value in (raw.get("extensions") or {}).items()
                if isinstance(value, dict)
            },
            disabled_extensions=tuple(
                str(one) for one in (raw.get("disabled_extensions") or []) if isinstance(one, str) and one
            ),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """설정 파일 + 환경변수. 파일이 없거나 깨졌으면 기본값으로 간다 (처음 실행 = BUI-03)."""
        target = path or cls().config_path
        if not target.exists():
            return cls().with_env()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 설정이 깨졌다고 앱이 안 뜨면 고칠 길이 없다 — 기본값으로 띄우고 BUI-03을 보인다.
            return cls().with_env()
        return cls.from_json_dict(raw).with_env()


__all__ = [
    "DEFAULT_CENTER_URL",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_QUEUE_MAX",
    "DEFAULT_WEBHOOK_PORT",
    "DEFAULT_WORKER_PORT",
    "START_ALWAYS",
    "START_WHEN_NEEDED",
    "RuntimeSettings",
    "ServiceKeyRef",
    "Settings",
    "data_dir",
]

"""Tool UI 설정 (TOL-02) — 확장이 선언한 `scope: tool_ui` 칸의 값뿐이다.

**비밀 칸은 여기 오지 않는다** — OS 비밀 저장소(`credentials.py`)로 간다. 쓰는 곳이 없는 칸은
두지 않는다 (ADR-0073과 같은 결).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.tool_ui.places import data_dir

SETTINGS_FILE = "settings.json"


@dataclass(frozen=True)
class ToolSettings:
    """`{확장 id: {칸: 값}}` — 비밀이 아닌 칸만."""

    extensions: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        return data_dir() / SETTINGS_FILE

    def extension(self, extension_id: str) -> dict[str, Any]:
        return dict(self.extensions.get(extension_id, {}))

    def to_json_dict(self) -> dict[str, Any]:
        return {"extensions": {key: dict(value) for key, value in self.extensions.items()}}

    @classmethod
    def from_json_dict(cls, raw: Any) -> ToolSettings:
        found = raw.get("extensions") if isinstance(raw, dict) else None
        if not isinstance(found, dict):
            return cls()
        return cls(
            extensions={
                str(key): dict(value) for key, value in found.items() if isinstance(value, dict)
            }
        )

    def save(self, path: Path | None = None) -> None:
        target = path or self.config_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path | None = None) -> ToolSettings:
        """없거나 깨졌으면 빈 설정 — 설정 하나 때문에 창이 뜨지 않으면 고칠 길이 없다."""
        target = path or cls().config_path
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_json_dict(raw)


__all__ = ["SETTINGS_FILE", "ToolSettings"]

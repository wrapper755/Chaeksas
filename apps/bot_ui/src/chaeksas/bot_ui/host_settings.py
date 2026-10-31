"""확장에게 주는 설정 — 확장 자기 칸 + 호스트가 채운 예약 키 (C13).

PC 실행기(`agent.py`)와 실행 프로세스(`runner_main.py`)가 같은 것을 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HostSettings:
    """`extension_api.Settings` — 확장 자기 설정 + 호스트가 채운 예약 키 (C13)."""

    values: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

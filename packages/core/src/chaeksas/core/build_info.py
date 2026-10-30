"""산출물의 판 — 빌드가 찍은 것을 읽는 자리 하나 ([ADR-0067](../../../../../docs/decisions/0067-build-stamp.md)).

`packaging/build.py`가 묶은 실행 파일 옆에 `chaeksas-build.json`(`STAMP_NAME`)을 둔다. 묶인 앱은
그것을 읽어 C4 `versions`로 올린다. **묶지 않은 것**(소스·`uv sync`)에는 그 파일이 없고 판은
설치된 배포판의 dist-info에서 온다.

**판을 짓지 않는다** — 짓는 것은 빌드다(`STAMP_NAME`을 쓰는 쪽도, 판 모양을 보는 쪽도 이 모듈의
함수를 쓴다 — 둘이 갈라지면 빌드가 되읽어 확인하는 일이 거짓이 된다).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

#: 실행 파일 옆에 찍는 파일 이름 — Studio·PC 실행기가 같다.
STAMP_NAME = "chaeksas-build.json"

#: 판 모양 — PEP 440 공개 판(`1.2.3`·`1.2.3rc1`·`1.2.3.post1`·`1.2.3.dev4`)에 **로컬 판**
#: (`+g<커밋>`·`.dirty`)을 붙일 수 있다. 「판 올리기」가 견주어야 하므로 아무 글이나 받지 않는다.
VERSION_PATTERN = re.compile(
    r"^\d+(\.\d+){1,3}((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$"
)

#: 판을 모를 때 — 소스에서 설치하지 않고 돌릴 때만 생긴다.
UNKNOWN = "0.0.0"


@dataclass(frozen=True)
class Stamp:
    """빌드가 찍은 것 (`chaeksas-build.json`)."""

    version: str
    commit: str
    built_at: str

    def to_json(self) -> dict[str, Any]:
        return {"schema": 1, "version": self.version, "commit": self.commit, "built_at": self.built_at}


def valid_version(value: str) -> bool:
    return bool(VERSION_PATTERN.match(value))


def stamp_path(executable: Path | None = None) -> Path:
    """찍힌 파일의 자리 — **실행 파일 옆**이다 (사람이 열어 볼 수 있다)."""
    return (executable or Path(sys.executable)).resolve().parent / STAMP_NAME


def read_stamp(path: Path) -> Stamp | None:
    """그 파일을 읽는다. 없거나 깨졌거나 판 모양이 아니면 `None` — **판 하나로 앱이 죽지 않는다**."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    found = {key: raw.get(key) for key in ("version", "commit", "built_at")}
    if not all(isinstance(value, str) and value for value in found.values()):
        return None
    if not valid_version(str(found["version"])):
        return None
    return Stamp(version=str(found["version"]), commit=str(found["commit"]), built_at=str(found["built_at"]))


def stamp() -> Stamp | None:
    """**묶인 앱이면** 찍힌 것. 묶지 않은 것이면 `None` (그 자리의 `python` 옆을 뒤지지 않는다)."""
    if not getattr(sys, "frozen", False):
        return None
    return read_stamp(stamp_path())


def package_version(distribution: str) -> str:
    """설치된 배포판의 판 — 없으면 `UNKNOWN`."""
    try:
        return version(distribution)
    except PackageNotFoundError:
        return UNKNOWN


def product_version(distribution: str) -> str:
    """산출물의 판 — **찍힌 판** > 그 배포판의 dist-info > `UNKNOWN`."""
    found = stamp()
    return found.version if found is not None else package_version(distribution)


__all__ = [
    "STAMP_NAME",
    "UNKNOWN",
    "VERSION_PATTERN",
    "Stamp",
    "package_version",
    "product_version",
    "read_stamp",
    "stamp",
    "stamp_path",
    "valid_version",
]

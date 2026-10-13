"""STU-01 창 배치를 기억하고 되돌린다 — 「크기·위치를 기억한다」·「레이아웃 초기화」.

**설정 파일과 따로 둔다** (`layout.json`) — 사람이 읽고 고치는 설정(주소·참조 이름·키 참조)에
Qt의 불투명한 바이트 뭉치를 섞지 않는다. 지워도 되는 파일이라 「초기화」가 **파일 지우기**로
끝나고, 파일이 깨져 있으면 **없는 것으로 보고** 기본 배치로 뜬다 (배치 하나 때문에 Studio가
뜨지 않으면 안 된다 — 작업 폴더 기록과 같은 결).

**어느 위젯을 기억하는지는 창이 안다** — 이 모듈은 받은 것만 담고 되돌린다. Qt가 주는
`saveGeometry()`·`saveState()`는 판이 바뀌면 거부되므로(`restore*`가 `False`를 돌려준다)
**되돌리지 못한 것은 조용히 기본값으로** 둔다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QByteArray

LAYOUT_NAME = "layout.json"
SCHEMA = 1


class Window(Protocol):
    """창에서 쓰는 둘 (`QMainWindow`)."""

    def saveGeometry(self) -> QByteArray: ...  # noqa: N802 - Qt 이름 그대로
    def saveState(self) -> QByteArray: ...  # noqa: N802
    def restoreGeometry(self, state: QByteArray) -> bool: ...  # noqa: N802
    def restoreState(self, state: QByteArray) -> bool: ...  # noqa: N802


class Splitter(Protocol):
    """분할자에서 쓰는 둘 (`QSplitter`)."""

    def saveState(self) -> QByteArray: ...  # noqa: N802
    def restoreState(self, state: QByteArray) -> bool: ...  # noqa: N802


@dataclass(frozen=True)
class Layout:
    """담아 두는 것. Qt의 바이트 뭉치는 **base64 글자**로 적는다 (JSON에 담으려고)."""

    geometry: str = ""
    window_state: str = ""
    middle: str = ""
    split: str = ""
    #: 「속성 패널 접기」가 켜져 있었나 (STU-01 도구 메뉴, Ctrl+Shift+P).
    properties_collapsed: bool = False


def layout_path(data_dir: Path) -> Path:
    return data_dir / LAYOUT_NAME


def _text(state: QByteArray) -> str:
    return bytes(state.toBase64().data()).decode("ascii")


def _bytes(text: str) -> QByteArray:
    return QByteArray.fromBase64(QByteArray(text.encode("ascii")))


def read(path: Path) -> Layout | None:
    """담아 둔 배치. 없거나 **읽을 수 없으면 `None`** (기본 배치로 뜬다)."""
    if not path.is_file():
        return None
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    fields = {name: raw.get(name) for name in Layout().__dict__}
    try:
        return Layout(
            geometry=str(fields["geometry"] or ""),
            window_state=str(fields["window_state"] or ""),
            middle=str(fields["middle"] or ""),
            split=str(fields["split"] or ""),
            properties_collapsed=bool(fields["properties_collapsed"]),
        )
    except (TypeError, ValueError):
        return None


def write(path: Path, found: Layout) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA, **asdict(found)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def capture(
    window: Window, middle: Splitter, split: Splitter, *, collapsed: bool
) -> Layout:
    """지금 배치를 담는다 (창을 닫을 때)."""
    return Layout(
        geometry=_text(window.saveGeometry()),
        window_state=_text(window.saveState()),
        middle=_text(middle.saveState()),
        split=_text(split.saveState()),
        properties_collapsed=collapsed,
    )


def apply(found: Layout, window: Window, middle: Splitter, split: Splitter) -> bool:
    """담아 둔 배치를 되돌린다. **비어 있는 칸은 건드리지 않는다.**

    **Qt가 받아들였나**를 돌려준다 — 판이 바뀌었거나 담아 둔 것이 깨졌으면 `restore*`가
    `False`를 주고, 그때는 **되돌리지 못한 자리가 기본값으로 남는다**(창이 뜨는 것을 막지
    않는다). 창 크기는 화면 크기에 맞춰 **깎일 수 있다** — 받아들인 것과 실제가 다를 수 있다.
    """
    done = True
    if found.geometry:
        done &= window.restoreGeometry(_bytes(found.geometry))
    if found.window_state:
        done &= window.restoreState(_bytes(found.window_state))
    if found.middle:
        done &= middle.restoreState(_bytes(found.middle))
    if found.split:
        done &= split.restoreState(_bytes(found.split))
    return bool(done)


def clear(path: Path) -> None:
    """「레이아웃 초기화」 — 담아 둔 것을 지운다 (다음에 뜰 때도 기본 배치다)."""
    path.unlink(missing_ok=True)


__all__ = [
    "LAYOUT_NAME",
    "SCHEMA",
    "Layout",
    "Splitter",
    "Window",
    "apply",
    "capture",
    "clear",
    "layout_path",
    "read",
    "write",
]

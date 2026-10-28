"""자리 — Tool UI 제 데이터 폴더와, **빌려 읽는** Bot UI 데이터 폴더 (ADR-0077 §4).

Tool UI는 Bot UI를 import하지 않는다(앱끼리 import하지 않는다). 그래서 Bot UI의 데이터 위치
규칙을 **여기 한 번 더** 적는다 — Studio(`studio.extensions.bot_ui_data_dir`)와 같은 결이고,
어긋나면 `tests/test_tool_ui_host.py`가 잡는다.

**Bot UI 쪽은 읽기만 한다** — 쓰는 것은 제 자리(`data_dir()`)뿐이다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import platformdirs

ENV_PREFIX = "CHK_TOOL_UI__"

#: Bot UI가 런타임 폴더에 남기는 자리 정보 (`{"runtime", "port"}`, C13 `token_dir`).
RUNTIME_FILE = "runtime.json"
#: Bot UI 설정 파일 — 끈 확장 목록(`disabled_extensions`)을 읽는다 (BUI-11이 이 PC의 유일한 켜기·끄기다).
BOT_UI_SETTINGS_FILE = "settings.json"
DISABLED_EXTENSIONS = "disabled_extensions"


def data_dir() -> Path:
    """Tool UI 사용자 데이터 위치. Windows `%LOCALAPPDATA%`, Linux `~/.local/share` (CLAUDE.md §5)."""
    override = os.environ.get(f"{ENV_PREFIX}DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "tool-ui"


def bot_ui_data_dir() -> Path:
    """이 PC Bot UI의 데이터 위치 — Bot UI와 **같은 규칙**이다 (`CHK_BOT_UI__DATA_DIR`가 이긴다)."""
    override = os.environ.get("CHK_BOT_UI__DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("chaeksas", appauthor=False)) / "bot-ui"


def runtime_folder(runtime_id: str, *, root: Path | None = None) -> Path:
    """Bot UI가 그 런타임의 토큰·`runtime.json`을 두는 폴더 (C13 `token_dir`)."""
    return (root or bot_ui_data_dir()) / "runtimes" / runtime_id


def runtime_port(runtime_id: str, *, root: Path | None = None) -> int | None:
    """Bot UI가 남긴 포트. **없거나 깨졌으면 `None`** — 부르는 쪽이 다음 출처로 간다."""
    try:
        raw = json.loads((runtime_folder(runtime_id, root=root) / RUNTIME_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    port = raw.get("port") if isinstance(raw, dict) else None
    return int(port) if isinstance(port, int) and not isinstance(port, bool) and port > 0 else None


def bot_ui_turned_off(*, root: Path | None = None) -> tuple[str, ...]:
    """Bot UI에서 사람이 끈 확장 (ADR-0043). **읽기만 한다** — 없거나 깨졌으면 끈 것이 없다."""
    try:
        raw = json.loads((root or bot_ui_data_dir()).joinpath(BOT_UI_SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    found = raw.get(DISABLED_EXTENSIONS) if isinstance(raw, dict) else None
    if not isinstance(found, list):
        return ()
    return tuple(one for one in found if isinstance(one, str) and one)


def bot_ui_center_url(*, root: Path | None = None) -> str | None:
    """Bot UI가 붙은 Center 주소 (C13 `center.url`) — 도구가 외부 작업을 올리는 곳 (ADR-0102).

    **읽기만 한다.** Bot UI처럼 환경변수 `CHK_BOT_UI__CENTER__URL`이 이긴다(같은 규칙).
    """
    found = os.environ.get("CHK_BOT_UI__CENTER__URL")
    if found:
        return found
    try:
        raw = json.loads((root or bot_ui_data_dir()).joinpath(BOT_UI_SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = raw.get("center_url") if isinstance(raw, dict) else None
    return url if isinstance(url, str) and url else None


__all__ = [
    "BOT_UI_SETTINGS_FILE",
    "bot_ui_center_url",
    "DISABLED_EXTENSIONS",
    "ENV_PREFIX",
    "RUNTIME_FILE",
    "bot_ui_data_dir",
    "bot_ui_turned_off",
    "data_dir",
    "runtime_folder",
    "runtime_port",
]

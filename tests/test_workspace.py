"""워크스페이스 뼈대가 성립하는지 — 멤버가 모두 import되고, 인터프리터가 3.12인가."""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

MEMBERS = {
    "packages/contracts": "chaeksas.contracts",
    "packages/extension_api": "chaeksas.extension_api",
    "packages/core": "chaeksas.core",
    "packages/llm": "chaeksas.llm",
    "packages/qt": "chaeksas.qt",
    "packages/service_kit": "chaeksas.service_kit",
    "apps/studio": "chaeksas.studio",
    "apps/bot_ui": "chaeksas.bot_ui",
    "apps/server_runner": "chaeksas.server_runner",
    "apps/admin": "chaeksas.admin",
    "apps/center": "chaeksas.center",
    "extensions/ui_automation": "chaeksas.ext.ui_automation",
}


def test_interpreter_is_312() -> None:
    """ADR-0005: 3.12로 통일. uv가 관리하는 인터프리터를 쓴다."""
    assert sys.version_info[:2] == (3, 12), f"3.12가 아니다: {sys.version}"


def test_workspace_members_match_disk() -> None:
    """이 표가 실제 멤버 목록과 같은가 (멤버를 더하면 표도 고쳐야 한다)."""
    # as_posix(): Windows에서 `str()`은 `apps\admin`을 주므로 표와 비교할 수 없다.
    found = {
        p.parent.relative_to(ROOT).as_posix()
        for pattern in ("packages/*", "apps/*", "extensions/*")
        for p in ROOT.glob(f"{pattern}/pyproject.toml")
    }
    assert found == set(MEMBERS), f"표에 없음: {found - set(MEMBERS)}, 디스크에 없음: {set(MEMBERS) - found}"


@pytest.mark.parametrize("module", sorted(MEMBERS.values()))
def test_member_is_importable(module: str) -> None:
    assert importlib.import_module(module).__name__ == module


def test_chaeksas_is_namespace_package() -> None:
    """chaeksas·chaeksas.ext는 PEP 420 네임스페이스 — __init__.py를 두면 멤버 하나만 보인다."""
    import chaeksas
    import chaeksas.ext

    assert chaeksas.__file__ is None, "chaeksas/__init__.py가 생겼다 — 지워야 한다"
    assert chaeksas.ext.__file__ is None, "chaeksas/ext/__init__.py가 생겼다 — 지워야 한다"
    # 멤버 11개가 모두 src/chaeksas를 하나씩 더한다 (확장도 chaeksas/ext/를 담고 있으므로 포함).
    assert len(chaeksas.__path__) == len(MEMBERS)


@pytest.mark.parametrize("rel", sorted(MEMBERS))
def test_member_pins_python_312(rel: str) -> None:
    """멤버마다 requires-python이 같아야 한다 (lock 파일 하나, ADR-0005)."""
    data = tomllib.loads((ROOT / rel / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.12,<3.13"


def test_root_is_not_a_package() -> None:
    """루트는 워크스페이스 루트일 뿐 패키지가 아니다 (01-architecture §8)."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "project" not in data
    assert data["tool"]["uv"]["python-preference"] == "only-managed"

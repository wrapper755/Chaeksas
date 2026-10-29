"""서버 시험 표시가 거짓말하지 않는다 (`ci_scope.py`, ADR-0104).

표시를 잘못 붙이면 클라이언트 시험이 **Windows에서 조용히 빠진다** — 그래서 셋을 본다:
적힌 파일이 정말 있는가, 그 파일이 PC에서 도는 코드를 import하지 않는가, CI가 정말 빼고 있는가.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from ci_scope import CLIENT_MODULES, SERVER_SIDE

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent


def test_every_listed_file_exists() -> None:
    missing = sorted(name for name in SERVER_SIDE if not (TESTS / f"{name}.py").is_file())
    assert missing == [], "없는 파일을 서버로 적었다 — 이름을 바꿨으면 목록도 고친다"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("name", sorted(SERVER_SIDE))
def test_a_server_file_does_not_run_client_code(name: str) -> None:
    """PC에서 도는 코드(Bot UI·Tool UI·Qt·Worker·UI 자동화 클라이언트)를 부르면 그 파일은 양쪽이다."""
    used = _imports(TESTS / f"{name}.py")
    client = sorted(m for m in used if any(m == c or m.startswith(c + ".") for c in CLIENT_MODULES))
    assert client == [], f"{name}은 클라이언트 코드를 쓴다 — 서버 목록에서 뺀다"


def test_the_marker_is_put_on_server_files(pytestconfig: pytest.Config) -> None:
    assert any("server:" in line for line in pytestconfig.getini("markers")), "pyproject에 표시를 등록한다"


def test_windows_ci_leaves_out_server_tests_and_linux_runs_all() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'uv run pytest -m "not server"' in workflow, "Windows 잡이 서버 시험을 뺀다"
    assert "uv run pytest\n" in workflow, "Linux 잡은 전부 돈다"

"""**한글로 말하는 도구**가 Windows 기본 코드페이지에서도 돌아가는지.

CI의 `windows-latest`에서 실제로 터진 것을 Linux에서도 잡기 위한 테스트다.
Windows 콘솔·파이프의 기본 인코딩은 cp949(한국어)·cp1252(영어)인데, 이 도구들은
한글로 말한다. `PYTHONIOENCODING`으로 그 환경을 흉내 낸다.

**생성기만이 아니다** — `packaging/build.py`(데스크톱 묶기)가 이 목록에 없어서 첫 Windows
산출물 실행이 `print("── 묶는다")` 한 줄에서 멈췄다 (2026-10-16). **한글을 찍는 도구를 새로
만들면 여기 한 줄을 더한다.**
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: `--check`로 **아무것도 쓰지 않고** 돌려 볼 수 있는 것들.
GENERATORS = [
    "scripts/gen_schemas.py",
    "scripts/gen_tokens.py",
    "scripts/gen_console_pages.py",
    "docs/08-business-examples/_source/build.py",
]

#: `--check`가 없는 것들 — **도움말만** 찍어 본다. 한글 도움말·오류 글이 인코딩에 걸리는지는
#: 그것으로 드러나고, 진짜 일(묶기)은 몇 분이 걸려 단위 시험에서 돌릴 수 없다.
HELP_ONLY = ["packaging/build.py"]


@pytest.mark.parametrize("script", GENERATORS)
@pytest.mark.parametrize("encoding", ["cp1252", "cp949", "ascii"])
def test_generator_survives_non_utf8_stdout(script: str, encoding: str) -> None:
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    r = subprocess.run(
        [sys.executable, str(ROOT / script), "--check"],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert r.returncode == 0, f"{script}가 stdout 인코딩 {encoding}에서 깨졌다:\n{r.stdout}{r.stderr}"


@pytest.mark.parametrize("script", HELP_ONLY)
@pytest.mark.parametrize("encoding", ["cp1252", "cp949", "ascii"])
def test_tool_help_survives_non_utf8_stdout(script: str, encoding: str) -> None:
    """도움말을 찍는 것만으로도 **한글 글**이 지나간다 — 거기서 죽으면 본문도 죽는다."""
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    r = subprocess.run(
        [sys.executable, str(ROOT / script), "--help"],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert r.returncode == 0, f"{script} --help가 stdout 인코딩 {encoding}에서 깨졌다:\n{r.stdout}{r.stderr}"

"""생성기가 **Windows 기본 코드페이지에서도** 돌아가는지.

CI의 `windows-latest`에서 실제로 터진 것을 Linux에서도 잡기 위한 테스트다.
Windows 콘솔·파이프의 기본 인코딩은 cp949(한국어)·cp1252(영어)인데, 이 도구들은
한글로 말한다. `PYTHONIOENCODING`으로 그 환경을 흉내 낸다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

GENERATORS = [
    "scripts/gen_schemas.py",
    "scripts/gen_tokens.py",
    "docs/08-business-examples/_source/build.py",
]


@pytest.mark.parametrize("script", GENERATORS)
@pytest.mark.parametrize("encoding", ["cp1252", "cp949", "ascii"])
def test_generator_survives_non_utf8_stdout(script: str, encoding: str) -> None:
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    r = subprocess.run(
        [sys.executable, str(ROOT / script), "--check"],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    assert r.returncode == 0, f"{script}가 stdout 인코딩 {encoding}에서 깨졌다:\n{r.stdout}{r.stderr}"

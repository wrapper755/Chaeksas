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


#: `packaging/build.py`에서 자식 환경만 꺼내 보는 한 줄 (그 파일은 모듈 수준에서 stdout을
#: 다시 설정하므로 **따로 돌린다** — pytest가 가로챈 stdout에 그것을 걸지 않는다).
_ENV_PEEK = (
    "import importlib.util, json, pathlib, sys;"
    "spec=importlib.util.spec_from_file_location('chk_build', pathlib.Path('packaging/build.py'));"
    "m=importlib.util.module_from_spec(spec); sys.modules['chk_build']=m;"  # `@dataclass`가 여기를 찾는다
    "spec.loader.exec_module(m);"
    "print(json.dumps({k: m.child_env()[k] for k in ('PYTHONIOENCODING', 'PYTHONUTF8')}))"
)


def test_the_desktop_build_fixes_the_encoding_of_its_children() -> None:
    """**자식 프로세스의 한글 출력까지** 챙기는가 (`packaging/build.py`).

    빌드 자신의 `print`를 고쳐도 모자랐다 — `core`의 PyInstaller 훅이 **PyInstaller의
    프로세스**에서 한글을 찍어 거기서 또 죽었다 (2026-10-16, 두 번째 Windows 산출물 실행).
    그 프로세스의 stdout은 우리가 고칠 수 없으므로 **띄우는 쪽이 환경으로** 정해 준다.

    진짜 묶기는 몇 분이 걸려 여기서 돌릴 수 없다 — **무엇을 물려주는가**만 본다.
    """
    import json  # noqa: PLC0415

    # 바깥 환경이 cp1252라고 해도 **덮어써야** 한다 (`PYTHONIOENCODING`이 `PYTHONUTF8`을 이긴다).
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, "-c", _ENV_PEEK], capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


def test_the_child_encoding_wins_over_a_cp1252_environment() -> None:
    """**바깥이 cp1252여도 자식은 산다** — 그 덮어쓰기가 이 고침의 전부다.

    `PYTHONIOENCODING`은 `PYTHONUTF8`을 **이긴다**(이 시험을 쓰다 확인했다) — 그래서 빌드가
    그 값을 **못 박는다**. 훅이 찍는 한글을 같은 모양으로 흘려 본다.
    """
    hook = ROOT / "packages/core/src/chaeksas/core/__pyinstaller/hook-chaeksas.core.extensions.py"
    assert hook.is_file(), hook
    말 = "print('[hook] 확장 1개, hiddenimports 35개, datas 8개')"

    outer = dict(os.environ, PYTHONIOENCODING="cp1252")
    died = subprocess.run([sys.executable, "-c", 말], capture_output=True, text=True, cwd=ROOT, env=outer)
    assert died.returncode != 0, "cp1252에서 한글이 지나갔다 — 이 시험의 전제가 깨졌다"

    fixed = dict(outer, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    lived = subprocess.run([sys.executable, "-c", 말], capture_output=True, text=True, cwd=ROOT, env=fixed)
    assert lived.returncode == 0, f"덮어썼는데도 죽었다:\n{lived.stderr}"


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

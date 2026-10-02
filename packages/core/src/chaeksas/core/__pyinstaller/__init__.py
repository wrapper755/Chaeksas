"""PyInstaller 훅이 있는 곳 — 설치 파일을 만들 때 **확장이 함께 들어가게** 한다 (ADR-0024).

PyInstaller는 `pyinstaller40` 엔트리 포인트로 라이브러리가 준 훅 폴더를 찾는다. 그래서 우리 앱을
묶는 사람은 아무 인자도 적지 않아도 된다 — `chaeksas.core`를 쓰면 이 폴더가 딸려 온다.

이 폴더의 파일은 PyInstaller의 분석 과정이 읽는다. 평범한 모듈이 아니라서(파일 이름에 점이 있고
전역 변수로 결과를 돌려준다) ruff·mypy 검사에서 뺀다 (루트 `pyproject.toml`).

왜 훅이 필요한지는 `spikes/S5-extension-packaging/linux-core-hook/NOTES.md`에 있다.
"""

from __future__ import annotations

from pathlib import Path


def get_hook_dirs() -> list[str]:
    return [str(Path(__file__).parent)]

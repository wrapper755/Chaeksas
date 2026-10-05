"""모델 클라이언트 패키지 `chaeksas.llm` — 맨 아래이고, 엔진과 같은 한 벌이다 (ADR-0034).

어댑터 자체의 동작(헤더·응답 풀기·오류 분류)은 `test_core_ai_task.py`가 본다. 여기서는
「서비스 앱이 `core` 없이 쓸 수 있다」는 것과 「엔진이 쓰는 것과 같은 것이다」만 본다.
"""

from __future__ import annotations

import subprocess
import sys

import chaeksas.core.llm as core_llm
import chaeksas.llm as llm


def test_importing_llm_pulls_in_nothing_of_ours() -> None:
    """서비스 앱이 들여도 엔진·계약이 딸려 오지 않는다 — 새 프로세스에서 본다."""
    probe = (
        "import sys, chaeksas.llm\n"
        "ours = sorted(m for m in sys.modules if m.startswith('chaeksas.') and m != 'chaeksas.llm')\n"
        "print(','.join(ours))\n"
    )
    found = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert found.stdout.strip() == "", f"chaeksas.llm이 다른 멤버를 들인다: {found.stdout.strip()}"


def test_the_engine_uses_the_same_client() -> None:
    """두 벌이 갈라지지 않는다 — `core.llm`은 다시 내보내기일 뿐이다."""
    for name in core_llm.__all__:
        assert getattr(core_llm, name) is getattr(llm, name), name


def test_no_adapter_fails_instead_of_passing_silently() -> None:
    try:
        llm.NoLlm().ask([{"role": "user", "content": "안녕"}])
    except llm.LlmError:
        return
    raise AssertionError("어댑터가 없는데 답이 왔다")

"""짜 둔 모델 답의 **자리가 하나다** (`tests/canned_answers.py`) — M3·M5·M7이 함께 쓴다.

**이 파일이 막는 것은 조용한 덮어쓰기다.** 답은 `results`의 이름들로 찾으므로, 두 예제가 같은
열쇠를 쓰면 **먼저 적힌 쪽이 이기고** 뒤쪽 예제는 남의 답을 받는다 — 묶음은 그냥 실패하고
까닭은 모델 답이라고 적히지 않는다 (조각 12에서 그런 자리를 둘 겪었다).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from canned_answers import canned

SOURCE = Path(__file__).resolve().parent / "canned_answers.py"


def keys() -> list[tuple[str, ...]]:
    """`if key == (...)`의 열쇠들 — **글이 아니라 구문으로** 읽는다 (주석에 속지 않는다)."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    out: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Name):
            continue
        if node.left.id != "key" or not isinstance(node.comparators[0], ast.Tuple):
            continue
        names = tuple(
            one.value
            for one in node.comparators[0].elts
            if isinstance(one, ast.Constant) and isinstance(one.value, str)
        )
        if names:
            out.append(names)
    return out


def test_no_two_examples_share_a_key() -> None:
    """**열쇠가 겹치지 않는다** — 겹치면 한 예제의 답이 다른 예제를 조용히 바꾼다."""
    found = keys()
    assert len(found) >= 20, f"열쇠를 못 읽었다: {found}"
    seen: dict[tuple[str, ...], int] = {}
    for one in found:
        seen[one] = seen.get(one, 0) + 1
    duplicated = {name: count for name, count in seen.items() if count > 1}
    assert not duplicated, f"같은 열쇠를 두 번 적었다: {duplicated}"


def test_every_key_is_sorted() -> None:
    """열쇠는 **정렬한** 이름들이다 (`tuple(sorted(wanted))`와 맞아야 찾힌다).

    정렬하지 않고 적으면 그 분기는 **영원히 안 걸린다** — 시험은 그냥 실패하고 까닭이 보이지
    않는다. 사람이 눈으로 맞출 거리가 아니다.
    """
    wrong = [one for one in keys() if list(one) != sorted(one)]
    assert not wrong, f"정렬하지 않은 열쇠: {wrong}"


def test_an_unknown_ask_gets_nothing() -> None:
    """짜 둔 답이 없으면 `None`이다 — 스텁이 타입에 맞는 아무 값으로 때운다 (`answer_for`)."""
    assert canned({"아무것도아닌것": "string"}, {}) is None


def test_the_answers_the_three_bundles_need_are_here() -> None:
    """세 묶음이 **같은 답**을 받는다 — 조각 12가 연 자리다 (FX-09·BX-10·BX-30).

    값까지 본다: 예제는 결과의 **칸을 읽으므로**(`판정.승인`) 타입만 맞는 아무 값으로는
    케이스가 어긋난다. 그것이 `_NO_CANNED`의 정체였다.
    """
    judged: Any = canned({"판정": "dict"}, {"신청": {"id": 2, "금액": 900000, "영수증": True}})
    assert judged is not None and judged["판정"]["승인"] is False, "금액이 기준을 넘으면 반려다"

    papers: Any = canned({"서류결과": "dict"}, {"서류": ["biz.pdf", "bank.pdf"]})
    assert papers is not None and papers["서류결과"]["충족"] is True

    clauses: Any = canned(
        {"손해배상조항": "string", "지재권조항": "string", "해지조항": "string"},
        {"계약서": "unlimited.pdf"},
    )
    assert clauses is not None and "모든 손해" in clauses["손해배상조항"], "계약서로 답이 갈린다"

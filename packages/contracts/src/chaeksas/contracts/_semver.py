"""SemVer 비교와 버전 범위 — 계약 안에서만 쓰는 도우미 (계약 자체는 아니다).

`requires.extensions[].version`(`>=0.4,<0.5`)이나 `requires.core`처럼 **범위**로 적힌 값을
실제 버전과 맞춰 보는 데 쓴다. 의존성을 늘리지 않으려고 작게 직접 구현한다.

규칙은 SemVer 2.0 우선순위를 따른다.

- 주·부·수 번호를 숫자로 비교한다.
- 사전 배포(`-rc.1`)는 같은 번호의 정식 배포보다 **낮다**.
- 사전 배포끼리는 식별자를 차례로 비교하고, 숫자 식별자가 글자 식별자보다 낮다.
- 빌드 메타데이터(`+build`)는 우선순위에 넣지 않는다.
"""

from __future__ import annotations

import re

_CORE = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
_COMPARATOR = re.compile(r"^(>=|<=|==|!=|>|<)?\s*(.+)$")

#: 우선순위 비교용 키. 사전 배포가 없으면 뒤에 오도록 (1,)을 붙인다.
_SortKey = tuple[tuple[int, int, int], tuple[object, ...]]


class InvalidVersion(ValueError):
    """버전이나 범위를 읽을 수 없다."""


def _prerelease_key(pre: str | None) -> tuple[object, ...]:
    if pre is None:
        return (1,)  # 정식 배포가 사전 배포보다 높다
    out: list[object] = [0]
    for part in pre.split("."):
        if part.isdigit():
            out.append((0, int(part), ""))  # 숫자 식별자가 글자 식별자보다 낮다
        else:
            out.append((1, 0, part))
    return tuple(out)


def sort_key(version: str) -> _SortKey:
    """버전 하나를 비교 가능한 키로. `1.2.0`, `0.4`, `1.0.0-rc.1+build` 모두 받는다."""
    text = version.strip()
    if not text:
        raise InvalidVersion("빈 버전")
    text = text.split("+", 1)[0]  # 빌드 메타데이터는 버린다
    core_text, _, pre = text.partition("-")
    m = _CORE.match(core_text)
    if not m:
        raise InvalidVersion(f"버전을 읽을 수 없다: {version!r}")
    major, minor, patch = (int(g) if g is not None else 0 for g in m.groups())
    return (major, minor, patch), _prerelease_key(pre or None)


def compare(a: str, b: str) -> int:
    """`a`가 `b`보다 작으면 -1, 같으면 0, 크면 1."""
    ka, kb = sort_key(a), sort_key(b)
    return -1 if ka < kb else (0 if ka == kb else 1)


def satisfies(version: str, spec: str) -> bool:
    """버전이 범위를 만족하나. 범위는 쉼표로 나눈 비교식들의 **and**다 (`>=0.4,<0.5`).

    연산자를 적지 않으면 `==`로 본다. 범위 쪽 버전은 짧게 적어도 된다 (`1` = `1.0.0`).
    빈 범위는 "제한 없음"이다.
    """
    if not spec.strip():
        return True
    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            continue
        m = _COMPARATOR.match(part)
        if not m:
            raise InvalidVersion(f"범위를 읽을 수 없다: {spec!r}")
        op, bound = m.group(1) or "==", m.group(2).strip()
        got = compare(version, bound)
        ok = {
            ">=": got >= 0,
            "<=": got <= 0,
            ">": got > 0,
            "<": got < 0,
            "==": got == 0,
            "!=": got != 0,
        }[op]
        if not ok:
            return False
    return True

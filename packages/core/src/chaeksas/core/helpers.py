"""식 도우미 함수 — **플랫폼이 주는 것은 이 목록뿐이다** (ADR-0025 §도우미 함수).

**순수 함수만 둔다.** 디스크·환경·네트워크를 읽는 함수는 넣지 않는다 — 자율 수행으로 돌린 것을
결정 수행으로 재생할 때 같은 값이 나와야 한다. 디스크를 읽어야 하면 태스크로 만든다.

날짜 도우미는 「지금」을 인자로 받지 않는다. 실행이 시작한 시각을 `bind(now=…)`로 묶어 쓴다 —
같은 실행 안에서 `오늘()`이 자정을 넘기며 달라지면 안 된다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

#: 날짜 표기 (C14 §9의 `오늘`과 같다).
DATE_FORMAT = "%Y-%m-%d"
MONTH_FORMAT = "%Y-%m"


def _as_date(value: Any, *, what: str = "날짜") -> date:
    """`YYYY-MM-DD` 문자열·date·datetime을 날짜로."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], DATE_FORMAT).replace(tzinfo=None).date()
        except ValueError as e:
            raise ValueError(f"{what}이 `YYYY-MM-DD` 모양이 아니다: {value}") from e
    raise ValueError(f"{what}으로 쓸 수 없는 값이다: {type(value).__name__}")


def _rows(value: Any, *, what: str) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError(f"{what}은 목록이어야 한다 (받은 것: {type(value).__name__})")
    return value


def _column(rows: Any, column: str, *, what: str) -> list[Any]:
    out = []
    for row in _rows(rows, what=what):
        if not isinstance(row, Mapping):
            raise ValueError(f"{what}의 줄이 사전이 아니다 ({type(row).__name__})")
        if column not in row:
            raise ValueError(f"줄에 「{column}」 열이 없다 (있는 것: {', '.join(map(str, row))[:60]})")
        out.append(row[column])
    return out


# ─────────────────────────── 표 ───────────────────────────


def 합계(목록: Any, 열: str) -> Any:  # noqa: N802, N803 — 식에 쓰는 이름이다 (업무 사용자가 읽는다)
    """사전 목록의 한 열을 더한다. 빈 목록은 0."""
    values = _column(목록, 열, what="합계")
    return sum(values) if values else 0


def 평균(목록: Any, 열: str) -> Any:  # noqa: N802, N803
    values = _column(목록, 열, what="평균")
    return sum(values) / len(values) if values else 0


def 세기(목록: Any) -> int:  # noqa: N802
    return len(_rows(목록, what="세기"))


def 열뽑기(목록: Any, 열: str) -> list[Any]:  # noqa: N802, N803
    """한 열만 뽑아 목록으로."""
    return _column(목록, 열, what="열뽑기")


def 골라내기(목록: Any, 열: str, 값: Any) -> list[Any]:  # noqa: N802, N803
    """그 열이 그 값인 줄만."""
    return [row for row in _rows(목록, what="골라내기") if isinstance(row, Mapping) and row.get(열) == 값]


def 표를사전(목록: Any, 열: str) -> dict[Any, Any]:  # noqa: N802, N803
    """그 열을 열쇠로 하는 사전. 같은 열쇠가 또 오면 **뒤가 이긴다.**"""
    return {row[열]: row for row in _rows(목록, what="표를사전") if isinstance(row, Mapping) and 열 in row}


def 묶기(목록: Any, 열: str) -> dict[Any, list[Any]]:  # noqa: N802, N803
    """그 열의 값으로 묶는다 (`{값: [줄, …]}`)."""
    out: dict[Any, list[Any]] = {}
    for row in _rows(목록, what="묶기"):
        if isinstance(row, Mapping) and 열 in row:
            out.setdefault(row[열], []).append(row)
    return out


def 펼치기(목록: Any) -> list[Any]:  # noqa: N802
    """목록의 목록을 **한 겹** 펴낸다."""
    out: list[Any] = []
    for item in _rows(목록, what="펼치기"):
        out.extend(item if isinstance(item, Sequence) and not isinstance(item, str) else [item])
    return out


def 쪼개기(목록: Any, 크기: Any) -> list[list[Any]]:  # noqa: N802, N803
    """목록을 `크기`씩 묶음으로 쪼갠다 (`펼치기`의 반대). 묶음 단위 반복에 쓴다.

    마지막 묶음은 남은 만큼이고, 빈 목록은 빈 목록이다.
    """
    items = list(_rows(목록, what="쪼개기"))
    size = int(크기)
    if size < 1:
        raise ValueError(f"쪼갤 크기는 1보다 작을 수 없다: {크기}")
    return [items[start : start + size] for start in range(0, len(items), size)]


# ─────────────────────────── 수 ───────────────────────────


def 나누기(a: Any, b: Any) -> Any:  # noqa: N802
    """**0으로 나누면 0**이다 — 식에서 실행이 멈추지 않게 (ADR-0025)."""
    return (a / b) if b else 0


def 비율(a: Any, b: Any) -> Any:  # noqa: N802
    """`a / b`. 0으로 나누면 0. 백분율은 `round(비율(a, b) * 100, 1)`."""
    return 나누기(a, b)


# ─────────────────────────── 검사 ───────────────────────────


def 빈칸없음(줄: Any, 열목록: Any) -> bool:  # noqa: N802, N803
    """그 줄의 열들이 모두 채워져 있나 (`None`·빈 문자열·빈 목록이 없나)."""
    if not isinstance(줄, Mapping):
        raise ValueError(f"빈칸없음의 첫 인자는 사전이어야 한다 ({type(줄).__name__})")
    names = 열목록 if isinstance(열목록, Sequence) and not isinstance(열목록, str) else [열목록]
    return all(줄.get(name) not in (None, "", [], {}) for name in names)


def 범위벗어남(값: Any, 아래: Any, 위: Any) -> bool:  # noqa: N802, N803
    """`아래 <= 값 <= 위`가 아니면 참. 값이 없으면(`None`) 벗어난 것으로 본다."""
    if 값 is None:
        return True
    return not (아래 <= 값 <= 위)


# ─────────────────────────── 날짜 ───────────────────────────


def _date_helpers(now: datetime) -> dict[str, Callable[..., Any]]:
    """실행 시작 시각에 묶인 날짜 도우미 (같은 실행에서 값이 흔들리지 않는다)."""
    today = now.date()

    def 오늘() -> str:  # noqa: N802
        return today.strftime(DATE_FORMAT)

    def 지금() -> str:  # noqa: N802
        """실행이 시작한 시각 (ISO 8601 + 시간대). 변수 `지금`과 같은 값이다 (C14 §9)."""
        return now.isoformat()

    def 어제() -> str:  # noqa: N802
        return (today - timedelta(days=1)).strftime(DATE_FORMAT)

    def 이번달() -> str:  # noqa: N802
        return today.strftime(MONTH_FORMAT)

    def 지난달() -> str:  # noqa: N802
        first = today.replace(day=1)
        return (first - timedelta(days=1)).strftime(MONTH_FORMAT)

    def 이번주표기() -> str:  # noqa: N802
        year, week, _ = today.isocalendar()
        return f"{year}-W{week:02d}"

    def 지난주표기() -> str:  # noqa: N802
        year, week, _ = (today - timedelta(days=7)).isocalendar()
        return f"{year}-W{week:02d}"

    return {
        "오늘": 오늘,
        "지금": 지금,
        "어제": 어제,
        "이번달": 이번달,
        "지난달": 지난달,
        "이번주표기": 이번주표기,
        "지난주표기": 지난주표기,
    }


def 날짜더하기(날짜: Any, 일수: int) -> str:  # noqa: N802, N803
    return (_as_date(날짜) + timedelta(days=int(일수))).strftime(DATE_FORMAT)


def 달더하기(달: Any, 개월: int) -> str:  # noqa: N802, N803
    """`YYYY-MM`에 개월을 더한다 (`2026-10`, 3 → `2027-01`)."""
    text = str(달)[:7]
    try:
        year, month = (int(part) for part in text.split("-"))
    except ValueError as e:
        raise ValueError(f"달이 `YYYY-MM` 모양이 아니다: {달}") from e
    total = (year * 12 + (month - 1)) + int(개월)
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def 기간(시작: Any, 끝: Any) -> dict[str, str]:  # noqa: N802, N803
    """`{"from": …, "to": …}`. 서비스 앱·DMN 입력에 자주 넘긴다."""
    first, last = _as_date(시작, what="시작"), _as_date(끝, what="끝")
    if last < first:
        raise ValueError("기간의 끝이 시작보다 앞이다")
    return {"from": first.strftime(DATE_FORMAT), "to": last.strftime(DATE_FORMAT)}


# ─────────────────────────── 목록 ───────────────────────────


def _sorted(목록: Any, 열: str | None = None, *, 거꾸로: bool = False) -> list[Any]:  # noqa: N803
    """`sorted(목록)` 또는 `sorted(목록, '열')` (사전 목록을 그 열로)."""
    items = list(_rows(목록, what="sorted"))
    if 열 is None:
        return sorted(items, reverse=거꾸로)
    return sorted(items, key=lambda row: row[열] if isinstance(row, Mapping) else row, reverse=거꾸로)


#: BPMN·JSON에서 온 소문자 이름 (ADR-0025). 흐름 조건에 `true`라고 적힌 예제가 있고,
#: BPMN 도구·JSON을 손으로 쓰는 사람이 자연히 소문자로 적는다. 값이라 함수가 아니다.
JSON_LITERALS: dict[str, Any] = {"true": True, "false": False, "null": None}

#: 파이썬에서 그대로 쓰는 것 (ADR-0025 §도우미 함수의 「내장」).
BUILTIN_HELPERS: dict[str, Callable[..., Any]] = {
    "len": len,
    "sum": sum,
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "sorted": _sorted,
    # `zip`은 게으른 값을 내므로 목록으로 만들어 준다 (식 언어에 게으른 값은 두지 않는다).
    "zip": lambda *args: [list(row) for row in zip(*args, strict=False)],
    "dict": dict,
    "list": list,
    "set": set,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}

#: 업무 도우미 (날짜 뺀 것 — 날짜는 실행 시각에 묶어 `bind()`가 더한다).
BUSINESS_HELPERS: dict[str, Callable[..., Any]] = {
    "합계": 합계,
    "평균": 평균,
    "세기": 세기,
    "열뽑기": 열뽑기,
    "골라내기": 골라내기,
    "표를사전": 표를사전,
    "묶기": 묶기,
    "펼치기": 펼치기,
    "쪼개기": 쪼개기,
    "나누기": 나누기,
    "비율": 비율,
    "빈칸없음": 빈칸없음,
    "범위벗어남": 범위벗어남,
    "날짜더하기": 날짜더하기,
    "달더하기": 달더하기,
    "기간": 기간,
}


def bind(*, now: datetime) -> dict[str, Any]:
    """그 실행의 도우미 묶음. 날짜 도우미가 **실행 시작 시각**에 묶인다."""
    return {**BUILTIN_HELPERS, **BUSINESS_HELPERS, **JSON_LITERALS, **_date_helpers(now)}


#: 시각을 주지 않았을 때 쓰는 묶음 (검사·Studio 도움말처럼 값을 내지 않는 곳).
HELPERS: Mapping[str, Any] = {
    **BUILTIN_HELPERS,
    **BUSINESS_HELPERS,
    **JSON_LITERALS,
    **_date_helpers(datetime(2000, 1, 1)),  # noqa: DTZ001 — 자리만 채운다. `bind()`가 덮는다
}

#: 이름만 보는 곳(검사 B11·Studio 자동완성)에서 쓴다.
HELPER_NAMES = frozenset(HELPERS)

__all__ = [
    "BUILTIN_HELPERS",
    "JSON_LITERALS",
    "BUSINESS_HELPERS",
    "DATE_FORMAT",
    "HELPERS",
    "HELPER_NAMES",
    "MONTH_FORMAT",
    "bind",
]

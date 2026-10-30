"""타이머 시작의 일정 — `timeCycle` 식을 읽고 차례를 센다 (C14 §이벤트, C1 R13, ADR-0110).

**읽는 함수는 여기 하나다.** Center가 일정을 쓸 때(`center/api/timers.py`), 올릴 때 R13이 막을 때,
Studio 이벤트 편집기가 식을 볼 때 같은 함수를 쓴다 — 셋이 다른 문법을 받으면 「올라갔는데 안 돈다」가
된다.

식은 둘이다.

- **5필드 cron** — 분 시 일 월 요일. 칸마다 `*`·수·`a-b`·`/n`·쉼표. 일 칸의 `L`은 그달 마지막 날,
  요일은 0~7(0과 7이 일요일). 일과 요일을 **둘 다** 적으면 둘 중 하나에 맞으면 된다(cron의 관례).
  이름(`MON`·`JAN`)은 받지 않는다.
- **ISO 반복** — `R[n]/<시작>/<기간>` 또는 `R[n]/<기간>`. 시작이 없으면 부르는 쪽이 준 기준(배포가 생긴
  때)부터 센다. 기간의 일·주·월·년은 **달력**(벽시계)으로, 시·분·초는 흐른 시간으로 더한다.

cron은 벽시계라 **시간대가 있어야** 뜻이 있다 — 부르는 쪽이 준다(Center 설정). 없는 시각(서머타임
건너뛰기)은 건너뛰고 두 번 오는 시각은 한 번이다.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo

#: 너무 멀리는 보지 않는다 — 놓친 차례를 셀 때의 끝 (ADR-0110 §4).
LOOKBACK = timedelta(days=400)

#: 차례를 하나도 못 찾은 채 더 걷지 않는 끝 — 「2월 30일」처럼 오지 않는 식이 영원히 돌지 않게.
_MAX_DAYS = 366 * 5


class CycleError(ValueError):
    """읽을 수 없는 식 — R13 `timer_expression_invalid`."""


# ─────────────────────────── cron ───────────────────────────

_FIELDS = (("분", 0, 59), ("시", 0, 23), ("일", 1, 31), ("월", 1, 12), ("요일", 0, 7))
_ITEM = re.compile(r"^(?:(\*)|(\d+)(?:-(\d+))?)(?:/(\d+))?$")


def _field(text: str, name: str, low: int, high: int) -> frozenset[int]:
    out: set[int] = set()
    for item in text.split(","):
        found = _ITEM.match(item)
        if not found:
            raise CycleError(f"cron {name} 칸을 읽을 수 없다: {item!r}")
        star, first, last, step = found.groups()
        if star:
            start, end = low, high
        else:
            start = int(first)
            # `5/15`는 「5부터 끝까지 15마다」다 (cron의 관례).
            end = int(last) if last is not None else (high if step else start)
        if not (low <= start <= high and low <= end <= high) or start > end:
            raise CycleError(f"cron {name} 칸이 {low}~{high} 밖이다: {item!r}")
        stride = int(step) if step else 1
        if stride < 1:
            raise CycleError(f"cron {name} 칸의 간격은 1 이상이다: {item!r}")
        out.update(range(start, end + 1, stride))
    return frozenset(out)


@dataclass(frozen=True)
class Cron:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    last_day: bool  # 일 칸에 `L`
    months: frozenset[int]
    weekdays: frozenset[int]  # 0=일요일
    any_day: bool  # 일 칸이 `*`
    any_weekday: bool  # 요일 칸이 `*`

    def matches_day(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        last = calendar.monthrange(day.year, day.month)[1]
        by_day = day.day in self.days or (self.last_day and day.day == last)
        by_weekday = (day.weekday() + 1) % 7 in self.weekdays
        if self.any_day and self.any_weekday:
            return True
        if self.any_day:
            return by_weekday
        if self.any_weekday:
            return by_day
        return by_day or by_weekday  # 둘 다 적으면 둘 중 하나 (cron의 관례)

    def between(self, after: datetime, until: datetime, tz: tzinfo, anchor: datetime) -> Iterator[datetime]:
        del anchor  # cron은 기준이 없다 — 벽시계가 정한다
        day = after.astimezone(tz).date()
        last = until.astimezone(tz).date()
        while day <= last:
            if self.matches_day(day):
                for hour in sorted(self.hours):
                    for minute in sorted(self.minutes):
                        at = _wall(day, hour, minute, tz)
                        if at is not None and after < at <= until:
                            yield at
            day += timedelta(days=1)

    def after(self, moment: datetime, tz: tzinfo, anchor: datetime) -> datetime | None:
        del anchor
        day = moment.astimezone(tz).date()
        for _ in range(_MAX_DAYS):
            if self.matches_day(day):
                for hour in sorted(self.hours):
                    for minute in sorted(self.minutes):
                        at = _wall(day, hour, minute, tz)
                        if at is not None and at > moment:
                            return at
            day += timedelta(days=1)
        return None


def _wall(day: date, hour: int, minute: int, tz: tzinfo) -> datetime | None:
    """벽시계 시각 → 시각. **없는 시각**(서머타임 건너뛰기)이면 `None`, 두 번 오는 시각은 앞의 것."""
    at = datetime.combine(day, time(hour, minute), tzinfo=tz)
    back = at.astimezone(UTC).astimezone(tz)
    if (back.hour, back.minute) != (hour, minute):
        return None
    return at


def _cron(text: str) -> Cron:
    parts = text.split()
    if len(parts) != 5:
        raise CycleError(f"cron은 다섯 칸이다 (분 시 일 월 요일): {text!r}")
    minute, hour, day, month, weekday = parts
    day_items = [one for one in day.split(",") if one != "L"]
    last_day = len(day_items) != len(day.split(","))
    days = _field(",".join(day_items), *_FIELDS[2]) if day_items else frozenset()
    weekdays = frozenset(one % 7 for one in _field(weekday, *_FIELDS[4]))
    return Cron(
        minutes=_field(minute, *_FIELDS[0]),
        hours=_field(hour, *_FIELDS[1]),
        days=days,
        last_day=last_day,
        months=_field(month, *_FIELDS[3]),
        weekdays=weekdays,
        any_day=day == "*",
        any_weekday=weekday == "*",
    )


# ─────────────────────────── ISO 반복 ───────────────────────────

_PERIOD = re.compile(
    r"^P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


@dataclass(frozen=True)
class Period:
    months: int  # 년은 12개월로 담는다
    days: int  # 주는 7일로 담는다
    clock: timedelta  # 시·분·초 — 흐른 시간

    def rough(self) -> timedelta:
        """대강의 길이 — 어디서부터 걸을지 어림할 때만 쓴다."""
        return timedelta(days=self.months * 30.436875 + self.days) + self.clock


def _period(text: str) -> Period:
    found = _PERIOD.match(text)
    if not found or text in ("P", "PT") or text.endswith("T"):
        raise CycleError(f"ISO 기간을 읽을 수 없다: {text!r}")
    v = {k: int(n) for k, n in found.groupdict(default="0").items()}
    period = Period(
        months=v["years"] * 12 + v["months"],
        days=v["weeks"] * 7 + v["days"],
        clock=timedelta(hours=v["hours"], minutes=v["minutes"], seconds=v["seconds"]),
    )
    if period.rough() < timedelta(minutes=1):
        raise CycleError(f"주기는 1분 이상이다: {text!r}")
    return period


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Repeat:
    count: int | None  # `Rn`의 n. 없으면 끝없이
    start: datetime | None  # 없으면 부르는 쪽의 기준
    period: Period

    def nth(self, k: int, tz: tzinfo, anchor: datetime) -> datetime:
        base = (self.start or anchor).astimezone(tz)
        day = _add_months(base.date(), k * self.period.months) + timedelta(days=k * self.period.days)
        wall = datetime.combine(day, base.timetz().replace(tzinfo=None), tzinfo=base.tzinfo)
        return wall + k * self.period.clock

    def _from(self, moment: datetime, tz: tzinfo, anchor: datetime) -> Iterator[tuple[int, datetime]]:
        base = self.start or anchor
        guess = int((moment - base) / self.period.rough()) - 2 if moment > base else 0
        k = max(0, guess)
        while self.count is None or k < self.count:
            yield k, self.nth(k, tz, anchor)
            k += 1

    def between(self, after: datetime, until: datetime, tz: tzinfo, anchor: datetime) -> Iterator[datetime]:
        for _, at in self._from(after, tz, anchor):
            if at > until:
                return
            if at > after:
                yield at

    def after(self, moment: datetime, tz: tzinfo, anchor: datetime) -> datetime | None:
        for _, at in self._from(moment, tz, anchor):
            if at > moment:
                return at
        return None


def _repeat(text: str) -> Repeat:
    head, _, rest = text.partition("/")
    if not re.fullmatch(r"R\d*", head) or not rest:
        raise CycleError(f"ISO 반복은 R[n]/<시작>/<기간> 또는 R[n]/<기간>이다: {text!r}")
    count = int(head[1:]) if head[1:] else None
    if count is not None and count < 1:
        raise CycleError(f"반복 횟수는 1 이상이다: {text!r}")
    pieces = rest.split("/")
    if len(pieces) == 1:
        return Repeat(count=count, start=None, period=_period(pieces[0]))
    if len(pieces) != 2:
        raise CycleError(f"ISO 반복은 R[n]/<시작>/<기간> 또는 R[n]/<기간>이다: {text!r}")
    try:
        start = datetime.fromisoformat(pieces[0])
    except ValueError as e:
        raise CycleError(f"ISO 반복의 시작 시각을 읽을 수 없다: {pieces[0]!r}") from e
    return Repeat(count=count, start=start, period=_period(pieces[1]))


# ─────────────────────────── 바깥에 보이는 것 ───────────────────────────


@dataclass(frozen=True)
class Cycle:
    """읽은 식 하나. 시각은 모두 시간대가 있는 `datetime`이다."""

    text: str
    rule: Cron | Repeat

    def between(self, after: datetime, until: datetime, tz: tzinfo, *, anchor: datetime) -> list[datetime]:
        """`after` < 차례 ≤ `until`인 차례들, 오래된 것부터. `after`는 `until - LOOKBACK`보다 앞서지 않는다."""
        after = max(after, until - LOOKBACK)
        return list(self._in(tz).between(after, until, tz, anchor))

    def next_after(self, moment: datetime, tz: tzinfo, *, anchor: datetime) -> datetime | None:
        """`moment` 다음 차례. 더 오지 않으면 `None` (`R3/…`을 다 썼다)."""
        return self._in(tz).after(moment, tz, anchor)

    def _in(self, tz: tzinfo) -> Cron | Repeat:
        """시간대 없는 ISO 시작 시각은 **그 시간대의 벽시계**다 (오프셋을 적었으면 그것이 이긴다)."""
        rule = self.rule
        if isinstance(rule, Repeat) and rule.start is not None and rule.start.tzinfo is None:
            return Repeat(count=rule.count, start=rule.start.replace(tzinfo=tz), period=rule.period)
        return rule


def parse_cycle(text: str) -> Cycle:
    """`timeCycle` 본문 → `Cycle`. 읽지 못하면 `CycleError`."""
    value = (text or "").strip()
    if not value:
        raise CycleError("타이머 식이 비었다")
    if value.startswith("R"):
        return Cycle(text=value, rule=_repeat(value))
    return Cycle(text=value, rule=_cron(value))


def cycle_problem(text: str) -> str | None:
    """읽을 수 있으면 `None`, 아니면 사람이 읽을 까닭 (R13·Studio 편집기)."""
    try:
        parse_cycle(text)
    except CycleError as e:
        return str(e)
    return None


__all__ = ["LOOKBACK", "Cycle", "CycleError", "cycle_problem", "parse_cycle"]

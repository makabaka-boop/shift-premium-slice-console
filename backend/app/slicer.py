"""Pure pay-slicing core.

A duty interval is a naive local wall-clock range, minute precise, at most
36 hours long. Weekly recurring rules describe minute-of-day windows that may
straddle midnight (e.g. 22:00-06:00). Every duty minute belongs to exactly one
rule: the matching rule with the highest ``priority``; ties are broken by the
smallest rule id in UTF-8 byte order. Minutes with no match fall back to the
implicit baseline multiplier of 10000 basis points.

The timeline is cut at every midnight and every point where the winning rule
changes. All money math goes through :class:`fractions.Fraction`, so the
returned per-segment wages and the total are exact irreducible fractions; no
rounding happens anywhere along the way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Iterable, Sequence

MINUTES_PER_DAY = 1440
BASELINE_BPS = 10000
MAX_INTERVAL_MINUTES = 36 * 60

# Concrete (denominator) of basis points and of the per-hour clock.
BPS_DENOMINATOR = 10000
MINUTES_PER_HOUR = 60


@dataclass(frozen=True)
class Rule:
    id: str
    weekdays: frozenset[int]
    startMinute: int  # inclusive minute of day, 0..1439
    endMinute: int  # exclusive minute of day, 1..1440; < start wraps midnight
    priority: int
    basisPoints: int

    def covers(self, weekday: int, minute_of_day: int) -> bool:
        """Return whether the minute (0..1439) on ``weekday`` is in the window.

        Weekdays follow Python's convention: Monday=0 ... Sunday=6. A wrapping
        window (start > end) covers ``[start, 1440)`` on its own weekday and
        ``[0, end)`` in the early hours of the following calendar day.
        """
        if weekday not in self.weekdays:
            return False
        if self.startMinute < self.endMinute:
            return self.startMinute <= minute_of_day < self.endMinute
        return minute_of_day >= self.startMinute or minute_of_day < self.endMinute


@dataclass(frozen=True)
class Segment:
    """A half-open span of duty minutes sharing one winning rule."""

    start: int  # absolute minute offset from interval start, inclusive
    end: int  # exclusive
    startWall: datetime
    endWall: datetime
    weekday: int  # weekday of every minute in the segment (cuts at midnight)
    ruleId: str | None  # None means the implicit 10000 bps baseline
    basisPoints: int
    pay: Fraction  # exact wage for the whole segment

    @property
    def minutes(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class MinuteTrace:
    """Which rule a single duty minute was billed under, for the audit trail."""

    offset: int
    wall: datetime
    weekday: int
    minuteOfDay: int
    ruleId: str | None
    basisPoints: int


def pick_winner(
    rules: Iterable[Rule], weekday: int, minute_of_day: int
) -> Rule | None:
    """Highest priority covering the minute; ties broken by smallest UTF-8 id."""
    best: Rule | None = None
    best_id: bytes | None = None
    for rule in rules:
        if not rule.covers(weekday, minute_of_day):
            continue
        rid = rule.id.encode("utf-8")
        if (
            best is None
            or rule.priority > best.priority  # type: ignore[union-attr]
            or (rule.priority == best.priority and (best_id is None or rid < best_id))
        ):
            best = rule
            best_id = rid
    return best


@dataclass(frozen=True)
class SliceResult:
    segments: tuple[Segment, ...]
    minutes: tuple[MinuteTrace, ...]
    total: Fraction

    @property
    def total_minutes(self) -> int:
        return len(self.minutes)


def slice_duty(
    start: datetime,
    end: datetime,
    rules: Sequence[Rule],
    base_rate_cents: int,
) -> SliceResult:
    """Slice ``[start, end)`` at midnights and winner-change boundaries.

    ``start``/``end`` must already be validated: naive, minute-aligned,
    ``end > start``, duration at most 36 hours. Wages are
    ``base_rate_cents * minutes/60 * basisPoints/10000``, summed exactly.
    """
    total_minutes = int((end - start).total_seconds() // 60)
    if total_minutes <= 0 or total_minutes > MAX_INTERVAL_MINUTES:
        raise ValueError("interval must be in (0, 36h]")

    traces: list[MinuteTrace] = []
    winners: list[Rule | None] = []
    days: list[int] = []
    for offset in range(total_minutes):
        wall = start + timedelta(minutes=offset)
        winner = pick_winner(rules, wall.weekday(), wall.hour * 60 + wall.minute)
        winners.append(winner)
        days.append(wall.toordinal())
        traces.append(
            MinuteTrace(
                offset=offset,
                wall=wall,
                weekday=wall.weekday(),
                minuteOfDay=wall.hour * 60 + wall.minute,
                ruleId=winner.id if winner else None,
                basisPoints=winner.basisPoints if winner else BASELINE_BPS,
            )
        )

    # Cut between minute i-1 and i when crossing midnight or changing winner.
    cuts = [0]
    for i in range(1, total_minutes):
        if days[i] != days[i - 1] or winners[i] != winners[i - 1]:
            cuts.append(i)
    cuts.append(total_minutes)

    rate_scale = Fraction(1, MINUTES_PER_HOUR * BPS_DENOMINATOR)
    segments: list[Segment] = []
    total = Fraction(0)
    for left, right in zip(cuts, cuts[1:]):
        winner = winners[left]
        bps = winner.basisPoints if winner else BASELINE_BPS
        count = right - left
        # base cents/hour * hours(count/60) * multiplier(bps/10000)
        pay = base_rate_cents * Fraction(count) * bps * rate_scale
        seg = Segment(
            start=left,
            end=right,
            startWall=start + timedelta(minutes=left),
            endWall=start + timedelta(minutes=right),
            weekday=traces[left].weekday,
            ruleId=winner.id if winner else None,
            basisPoints=bps,
            pay=pay,
        )
        segments.append(seg)
        total += pay

    return SliceResult(
        segments=tuple(segments), minutes=tuple(traces), total=total
    )

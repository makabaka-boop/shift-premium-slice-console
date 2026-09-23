"""Minute-by-minute cross-check against an independent oracle.

The implementation groups minutes into segments. These tests recompute the
winning rule of every minute with deliberately simple independent logic
(sorted keys instead of the imperative pick in the package), sum wages as
per-minute Fractions, and verify the segment partition from scratch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from fractions import Fraction

import pytest

from app.slicer import (
    BASELINE_BPS,
    MINUTES_PER_DAY,
    Rule,
    pick_winner,
    slice_duty,
)


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M")


def oracle_winner(rules: list[Rule], dt: datetime) -> Rule | None:
    """Independent winner computation: sort by (-priority, utf8 id bytes)."""
    mod = dt.weekday()
    m = dt.hour * 60 + dt.minute
    matching = [r for r in rules if r.covers(mod, m)]
    if not matching:
        return None
    matching.sort(key=lambda r: (-r.priority, r.id.encode("utf-8")))
    return matching[0]


def oracle_minute_pay(rate: int, bps: int) -> Fraction:
    return Fraction(rate) * Fraction(bps, 600_000)


def assert_partition_matches(
    start: datetime,
    end: datetime,
    rules: list[Rule],
    rate: int,
    result,
) -> None:
    total_minutes = int((end - start).total_seconds() // 60)
    assert result.total_minutes == total_minutes
    assert len(result.minutes) == total_minutes

    # 1) The per-minute trace agrees with the independent oracle.
    expected_total = Fraction(0)
    prev_day = None
    prev_winner = object()
    expected_cuts = [0]
    for i in range(total_minutes):
        wall = start + timedelta(minutes=i)
        winner = oracle_winner(rules, wall)
        bps = winner.basisPoints if winner else BASELINE_BPS
        trace = result.minutes[i]
        assert trace.offset == i
        assert trace.wall == wall
        assert trace.weekday == wall.weekday()
        assert trace.minuteOfDay == wall.hour * 60 + wall.minute
        assert trace.ruleId == (winner.id if winner else None)
        assert trace.basisPoints == bps
        expected_total += oracle_minute_pay(rate, bps)

        if i > 0 and (
            wall.toordinal() != prev_day or winner is not prev_winner
        ):
            expected_cuts.append(i)
        prev_day = wall.toordinal()
        prev_winner = winner
    expected_cuts.append(total_minutes)

    # 2) Segments are exactly the maximal runs cut at midnight/winner changes.
    assert [s.start for s in result.segments] == expected_cuts[:-1]
    assert [s.end for s in result.segments] == expected_cuts[1:]

    seg_total = Fraction(0)
    for seg in result.segments:
        # every minute in the segment shares weekday (midnight was a cut) ...
        walls = [start + timedelta(minutes=j) for j in range(seg.start, seg.end)]
        assert len({w.weekday() for w in walls}) == 1
        assert seg.weekday == walls[0].weekday()
        # ... and shares the oracle's winner
        winners = {oracle_winner(rules, w) for w in walls}
        assert winners == {
            next(
                (r for r in rules if r.id == seg.ruleId),
                None,
            )
        }
        bps = seg.basisPoints
        assert seg.pay == sum(
            oracle_minute_pay(rate, bps) for _ in walls
        ), Fraction(rate) * len(walls) * bps / 600_000
        # fraction must already be irreducible
        assert Fraction(seg.pay.numerator, seg.pay.denominator) == seg.pay
        assert seg.pay.denominator > 0
        seg_total += seg.pay

    # 3) Total is the exact irreducible sum, no intermediate rounding.
    assert seg_total == expected_total
    assert result.total == expected_total
    assert Fraction(result.total.numerator, result.total.denominator) == result.total


def test_baseline_no_rules_single_day():
    start, end = parse("2026-09-23T09:00"), parse("2026-09-23T17:00")
    result = slice_duty(start, end, [], 100)
    assert_partition_matches(start, end, [], 100, result)
    assert len(result.segments) == 1
    assert result.segments[0].ruleId is None
    assert result.total == Fraction(800, 1)  # 8h * 100 cents


def test_baseline_cuts_at_midnight_even_without_rule_change():
    start, end = parse("2026-09-23T23:00"), parse("2026-09-24T01:00")
    result = slice_duty(start, end, [], 100)
    assert_partition_matches(start, end, [], 100, result)
    # same implicit winner before and after midnight, but still two segments
    assert len(result.segments) == 2
    assert result.segments[0].endWall == parse("2026-09-24T00:00")
    assert result.segments[1].startWall == parse("2026-09-24T00:00")


def test_cross_midnight_night_weekend_special_overlap():
    # Friday 2026-09-25 22:00 -> Saturday 2026-09-26 06:00 (480 minutes).
    assert parse("2026-09-25T22:00").weekday() == 4  # Fri
    assert parse("2026-09-26T06:00").weekday() == 5  # Sat

    night = Rule(
        id="night",
        weekdays=frozenset(range(7)),
        startMinute=22 * 60,
        endMinute=6 * 60,  # wraps midnight
        priority=1,
        basisPoints=13_000,
    )
    weekend = Rule(
        id="weekend",
        weekdays=frozenset({5, 6}),
        startMinute=0,
        endMinute=1440,
        priority=1,
        basisPoints=15_000,
    )
    special = Rule(
        id="special",
        weekdays=frozenset({5}),
        startMinute=0,
        endMinute=4 * 60,
        priority=2,
        basisPoints=20_000,
    )
    rules = [weekend, special, night]
    start, end = parse("2026-09-25T22:00"), parse("2026-09-26T06:00")
    result = slice_duty(start, end, rules, 1000)
    assert_partition_matches(start, end, rules, 1000, result)

    by_range = {(s.start, s.end): s for s in result.segments}
    # Fri 22:00-24:00: night only (weekday Fri is not a weekend day)
    assert by_range[(0, 120)].ruleId == "night"
    # midnight cut; Sat 00:00-04:00: special outranks both
    assert by_range[(120, 360)].ruleId == "special"
    # Sat 04:00-06:00: night vs weekend tie on priority -> byte order decides
    tie = by_range[(360, 480)]
    assert tie.ruleId == pick_winner(rules, 5, 5 * 60).id == "night"
    assert tie.basisPoints == 13_000

    # Hand-computed total, in exact cents:
    # 240 minutes @13000 bps + 240 minutes @20000 bps, rate 1000 cents/h
    expected = (
        Fraction(1000)
        * Fraction(240 * 13_000 + 240 * 20_000)
        / 600_000
    )
    assert result.total == expected


def test_tie_breaks_by_utf8_byte_order():
    # UTF-8 preserves code-point order; check explicit byte contract.
    assert "a".encode() < "z".encode() < "é".encode()
    ids = ["z", "é", "a"]
    rules = [
        Rule(
            id=i,
            weekdays=frozenset({2}),
            startMinute=540,
            endMinute=1080,
            priority=7,
            basisPoints=11_000,
        )
        for i in ids
    ]
    start, end = parse("2026-09-23T09:00"), parse("2026-09-23T10:00")
    assert start.weekday() == 2  # Wednesday
    result = slice_duty(start, end, rules, 500)
    assert_partition_matches(start, end, rules, 500, result)
    assert all(s.ruleId == "a" for s in result.segments)


def test_higher_priority_wins_over_earlier_id():
    hi = Rule("a", frozenset({2}), 540, 1080, priority=1, basisPoints=11_000)
    lo = Rule("b", frozenset({2}), 540, 1080, priority=2, basisPoints=19_000)
    start, end = parse("2026-09-23T09:00"), parse("2026-09-23T09:01")
    result = slice_duty(start, end, [hi, lo], 100)
    assert result.minutes[0].ruleId == "b"
    assert result.total == Fraction(19, 6)  # 19000 bps for one minute @100


def test_full_36_hour_interval_supported():
    start = parse("2026-09-23T00:00")
    end = start + timedelta(hours=36)
    rules = [
        Rule("r", frozenset({0, 1, 2, 3, 4, 5, 6}), 0, 1440, 0, 12_345)
    ]
    result = slice_duty(start, end, rules, 777)
    assert result.total_minutes == 36 * 60
    assert_partition_matches(start, end, rules, 777, result)
    # midnight cuts: 36h from day-1 00:00 to day-2 12:00 -> 2 segments
    assert len(result.segments) == 2


def test_one_minute_fraction_is_irreducible():
    start, end = parse("2026-09-23T12:00"), parse("2026-09-23T12:01")
    result = slice_duty(start, end, [], 1)
    # 1 cent/h * 1/60 h * 10000/10000 = 1/60 cent
    assert result.total == Fraction(1, 60)


def test_window_ending_at_midnight_is_not_wrapping():
    # 08:00-24:00 same-day window must not cover early morning minutes.
    r = Rule("day", frozenset(range(7)), 8 * 60, 1440, 1, 12_000)
    assert r.covers(2, 7 * 60 + 59) is False
    assert r.covers(2, 8 * 60) is True
    assert r.covers(2, 23 * 60 + 59) is True


def test_invalid_interval_rejected_by_validator_layer():
    from app.main import SliceRequest

    def expect_422(payload: dict):
        with pytest.raises(ValueError):
            SliceRequest(**payload)

    base = {
        "start": "2026-09-23T09:00",
        "end": "2026-09-23T17:00",
        "baseRateCents": 100,
        "rules": [],
    }
    # invalid calendar date
    expect_422({**base, "start": "2026-02-29T09:00"})
    # end before / equal to start
    expect_422({**base, "end": "2026-09-23T09:00"})
    expect_422({**base, "end": "2026-09-23T08:00"})
    # over 36 hours
    expect_422(
        {
            **base,
            "start": "2026-09-23T09:00",
            "end": "2026-09-24T21:01",
        }
    )
    # non-positive base rate
    expect_422({**base, "baseRateCents": 0})
    # seconds / timezone not accepted
    expect_422({**base, "start": "2026-09-23T09:00:30"})
    expect_422({**base, "end": "2026-09-23T17:00+08:00"})
    # empty weekdays
    expect_422(
        {
            **base,
            "rules": [
                {
                    "id": "x",
                    "weekdays": [],
                    "startMinute": 0,
                    "endMinute": 60,
                    "priority": 1,
                    "basisPoints": 11_000,
                }
            ],
        }
    )
    # bad weekday value
    expect_422(
        {
            **base,
            "rules": [
                {
                    "id": "x",
                    "weekdays": [7],
                    "startMinute": 0,
                    "endMinute": 60,
                    "priority": 1,
                    "basisPoints": 11_000,
                }
            ],
        }
    )
    # duplicate ids
    expect_422(
        {
            **base,
            "rules": [
                {
                    "id": "x",
                    "weekdays": [0],
                    "startMinute": 0,
                    "endMinute": 60,
                    "priority": 1,
                    "basisPoints": 11_000,
                },
                {
                    "id": "x",
                    "weekdays": [1],
                    "startMinute": 0,
                    "endMinute": 60,
                    "priority": 1,
                    "basisPoints": 11_000,
                },
            ],
        }
    )
    # > 20 rules
    expect_422(
        {
            **base,
            "rules": [
                {
                    "id": f"r{i}",
                    "weekdays": [0],
                    "startMinute": 0,
                    "endMinute": 60,
                    "priority": 1,
                    "basisPoints": 11_000,
                }
                for i in range(21)
            ],
        }
    )
    # bad minute windows
    expect_422(
        {
            **base,
            "rules": [
                {
                    "id": "x",
                    "weekdays": [0],
                    "startMinute": 1440,
                    "endMinute": 60,
                    "priority": 1,
                    "basisPoints": 11_000,
                }
            ],
        }
    )
    expect_422(
        {
            **base,
            "rules": [
                {
                    "id": "x",
                    "weekdays": [0],
                    "startMinute": 0,
                    "endMinute": 0,
                    "priority": 1,
                    "basisPoints": 11_000,
                }
            ],
        }
    )

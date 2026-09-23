"""精确切片核心：逐分钟裁决规则，在午夜与规则边界分段。

约定：
- 星期用 0..6 表示，0 = 周一（与 Python ``date.weekday()`` 一致）。
- 时间窗口为半开区间 ``[startMinute, endMinute)``，单位为当天 00:00 起的分钟数。
- ``endMinute < startMinute`` 表示跨午夜：当天 [start, 1440) 与次日 [0, end)。
- ``endMinute == 1440``（即 24:00）覆盖当天全部剩余分钟，不算跨午夜。
- 同一分钟命中多条规则时取 priority 最大者；仍并列取 id 的 UTF-8 字节序最小者。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Optional

# 默认倍率（无规则命中）
DEFAULT_BASIS_POINTS = 10000
BASIS_POINT_DENOMINATOR = 10000
MINUTES_PER_HOUR = 60
MAX_SHIFT_MINUTES = 36 * MINUTES_PER_HOUR


@dataclass(frozen=True)
class Rule:
    id: str
    weekdays: frozenset[int]
    start_minute: int
    end_minute: int
    priority: int
    basis_points: int

    def covers(self, weekday: int, minute_of_day: int) -> bool:
        """该规则是否覆盖某个（星期几, 当天第几分钟）。"""
        m = minute_of_day
        if self.end_minute > self.start_minute:
            # 普通窗口（含 00:00-24:00 全天）：仅当天 [start, end)
            return self.start_minute <= m < self.end_minute and weekday in self.weekdays
        # 跨午夜窗口：当天 [start, 1440) ∪ 次日 [0, end)
        return (
            (m >= self.start_minute and weekday in self.weekdays)
            or (m < self.end_minute and (weekday - 1) % 7 in self.weekdays)
        )


@dataclass(frozen=True)
class ChosenRule:
    """一分钟裁决结果。rule_id 为 None 表示无规则命中（按 10000）。"""

    rule_id: Optional[str]
    basis_points: int


def choose_rule(minute: datetime, rules: list[Rule]) -> ChosenRule:
    weekday = minute.weekday()
    minute_of_day = minute.hour * MINUTES_PER_HOUR + minute.minute

    winner: Optional[Rule] = None
    for rule in rules:
        if not rule.covers(weekday, minute_of_day):
            continue
        if winner is None:
            winner = rule
            continue
        if rule.priority > winner.priority:
            winner = rule
        elif rule.priority == winner.priority and rule.id.encode("utf-8") < winner.id.encode("utf-8"):
            winner = rule

    if winner is None:
        return ChosenRule(rule_id=None, basis_points=DEFAULT_BASIS_POINTS)
    return ChosenRule(rule_id=winner.id, basis_points=winner.basis_points)


@dataclass(frozen=True)
class Segment:
    start: datetime
    end: datetime
    minutes: int
    weekday: int
    rule_id: Optional[str]
    basis_points: int
    pay: Fraction


def _minute_pay(base_rate_cents: int, basis_points: int) -> Fraction:
    """单分钟工资 = 时薪 * 倍率 * (1/60)，全程分数精确。"""
    return Fraction(base_rate_cents * basis_points, BASIS_POINT_DENOMINATOR * MINUTES_PER_HOUR)


def slice_shift(
    start: datetime,
    end: datetime,
    base_rate_cents: int,
    rules: list[Rule],
) -> tuple[list[Segment], Fraction]:
    """把 [start, end) 逐分钟切片并归并相邻同类段。

    分段键包含日期，因此跨午夜时即使规则相同也会在 00:00 处断开。
    """
    segments: list[Segment] = []
    total = Fraction(0, 1)

    current = start
    current_date = start.date()
    chosen = choose_rule(current, rules)

    seg_start = current
    seg_minutes = 0

    while current < end:
        current_chosen = choose_rule(current, rules)
        # 规则变化 或 越过午夜 → 关闭旧段
        if (
            current_chosen.rule_id != chosen.rule_id
            or current_chosen.basis_points != chosen.basis_points
            or current.date() != current_date
        ):
            pay = Fraction(seg_minutes * base_rate_cents * chosen.basis_points,
                           BASIS_POINT_DENOMINATOR * MINUTES_PER_HOUR)
            segments.append(Segment(
                start=seg_start,
                end=current,
                minutes=seg_minutes,
                weekday=seg_start.weekday(),
                rule_id=chosen.rule_id,
                basis_points=chosen.basis_points,
                pay=pay,
            ))
            total += pay
            seg_start = current
            seg_minutes = 0
            chosen = current_chosen
            current_date = current.date()

        seg_minutes += 1
        current += timedelta(minutes=1)

    if seg_minutes > 0:
        pay = Fraction(seg_minutes * base_rate_cents * chosen.basis_points,
                       BASIS_POINT_DENOMINATOR * MINUTES_PER_HOUR)
        segments.append(Segment(
            start=seg_start,
            end=current,
            minutes=seg_minutes,
            weekday=seg_start.weekday(),
            rule_id=chosen.rule_id,
            basis_points=chosen.basis_points,
            pay=pay,
        ))
        total += pay

    return segments, total

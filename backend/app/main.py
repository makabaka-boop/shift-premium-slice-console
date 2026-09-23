"""FastAPI review console: validates one duty request and returns exact slices."""

from __future__ import annotations

import re
from datetime import datetime
from fractions import Fraction

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator

from .slicer import (
    BASELINE_BPS,
    MINUTES_PER_DAY,
    Rule,
    slice_duty,
)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Accept plain local wall-clock time, minute precision. No timezone suffix,
# no seconds -- the contract is minute-exact local time, nothing else.
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}$")


def _parse_local_minute(value: str) -> datetime:
    if not isinstance(value, str) or not _DATETIME_RE.match(value):
        raise ValueError("expected local datetime 'YYYY-MM-DDTHH:MM', minute precision")
    try:
        dt = datetime.strptime(value.replace(" ", "T"), "%Y-%m-%dT%H:%M")
    except ValueError as exc:  # invalid calendar date, e.g. 2026-02-29
        raise ValueError(f"invalid calendar date: {value!r}") from exc
    return dt


class RuleIn(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    weekdays: list[int] = Field(min_length=1)
    startMinute: int = Field(ge=0, le=MINUTES_PER_DAY - 1)
    endMinute: int = Field(ge=1, le=MINUTES_PER_DAY)
    priority: int
    basisPoints: int = Field(ge=1)

    @field_validator("weekdays")
    @classmethod
    def _weekdays_valid(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("weekdays must be in 0..6 (Mon=0 .. Sun=6)")
        if len(set(v)) != len(v):
            raise ValueError("weekdays must not repeat")
        return v


class SliceRequest(BaseModel):
    start: str
    end: str
    baseRateCents: int = Field(ge=1)
    rules: list[RuleIn] = Field(max_length=20)

    @model_validator(mode="after")
    def _cross_field(self) -> "SliceRequest":
        start = _parse_local_minute(self.start)
        end = _parse_local_minute(self.end)
        if end <= start:
            raise ValueError("end must be strictly after start")
        minutes = int((end - start).total_seconds() // 60)
        if minutes > 36 * 60:
            raise ValueError("duty interval must not exceed 36 hours")
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rule ids must be unique")
        return self


class FractionOut(BaseModel):
    numerator: int
    denominator: int


def _fraction_out(f: Fraction) -> FractionOut:
    return FractionOut(numerator=f.numerator, denominator=f.denominator)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


app = FastAPI(title="Duty Pay Review Console", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/slice", status_code=200)
def slice_endpoint(req: SliceRequest) -> dict:
    start = _parse_local_minute(req.start)
    end = _parse_local_minute(req.end)
    rules = [
        Rule(
            id=r.id,
            weekdays=frozenset(r.weekdays),
            startMinute=r.startMinute,
            endMinute=r.endMinute,
            priority=r.priority,
            basisPoints=r.basisPoints,
        )
        for r in req.rules
    ]
    result = slice_duty(start, end, rules, req.baseRateCents)

    return {
        "request": {
            "start": _iso(start),
            "end": _iso(end),
            "baseRateCents": req.baseRateCents,
        },
        "totalMinutes": result.total_minutes,
        "totalPay": _fraction_out(result.total).model_dump(),
        "segments": [
            {
                "index": i,
                "startOffset": s.start,
                "endOffset": s.end,
                "start": _iso(s.startWall),
                "end": _iso(s.endWall),
                "weekday": s.weekday,
                "weekdayName": WEEKDAY_NAMES[s.weekday],
                "minutes": s.minutes,
                "ruleId": s.ruleId,  # null => implicit 10000 baseline
                "basisPoints": s.basisPoints,
                "pay": _fraction_out(s.pay).model_dump(),
            }
            for i, s in enumerate(result.segments)
        ],
        "minutes": [
            {
                "offset": m.offset,
                "time": _iso(m.wall),
                "weekday": m.weekday,
                "minuteOfDay": m.minuteOfDay,
                "ruleId": m.ruleId,
                "basisPoints": m.basisPoints,
            }
            for m in result.minutes
        ],
        "baselineBasisPoints": BASELINE_BPS,
    }

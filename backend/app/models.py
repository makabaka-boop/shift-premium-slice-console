"""请求/响应模型。对外字段使用 camelCase。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RuleIn(CamelModel):
    id: str = Field(min_length=1)
    weekdays: list[int] = Field(min_length=1)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)
    priority: int
    basis_points: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("规则 id 不能为空串")
        return v

    @field_validator("weekdays")
    @classmethod
    def weekdays_valid(cls, v: list[int]) -> list[int]:
        for d in v:
            if d < 0 or d > 6:
                raise ValueError("星期取值必须在 0..6（0=周一）")
        if len(set(v)) != len(v):
            raise ValueError("星期集合不能重复")
        return v

    @model_validator(mode="after")
    def window_not_empty(self) -> "RuleIn":
        # start == end 是空窗口（不把 00:00-00:00 解释为全天，避免歧义）
        if self.start_minute == self.end_minute:
            raise ValueError("时间窗口不能为空（startMinute 不得等于 endMinute）")
        return self


class ShiftRequest(CamelModel):
    start: datetime
    end: datetime
    base_rate_cents: int = Field(ge=1)
    rules: list[RuleIn] = Field(max_length=20)

    @field_validator("start", "end")
    @classmethod
    def naive_local(cls, v: datetime) -> datetime:
        if v.tzinfo is not None:
            raise ValueError("时间必须为不带时区的本地时间")
        if v.second != 0 or v.microsecond != 0:
            raise ValueError("时间精确到分钟")
        return v

    @model_validator(mode="after")
    def interval_valid(self) -> "ShiftRequest":
        if self.end <= self.start:
            raise ValueError("值班区间结束时间必须晚于开始时间")
        minutes = int((self.end - self.start).total_seconds() // 60)
        if minutes > 36 * 60:
            raise ValueError("值班区间不得超过 36 小时")
        ids = [r.id for r in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("规则 id 必须唯一")
        return self


class FractionOut(CamelModel):
    numerator: int
    denominator: int
    decimal: str


class SegmentOut(CamelModel):
    start: datetime
    end: datetime
    minutes: int
    weekday: int
    rule_id: Optional[str]
    basis_points: int
    pay: FractionOut


class CalculateResponse(CamelModel):
    segments: list[SegmentOut]
    total: FractionOut
    total_minutes: int

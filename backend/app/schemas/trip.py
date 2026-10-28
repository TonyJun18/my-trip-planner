"""行程聚合根 Schemas：Trip / Day / Stop 的请求与响应模型。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# DayIn.date 字段名与 datetime.date 类型同名，模型构建时字段名会遮蔽类型名，
# 使用模块级别别名避免 `date | None` 被解析成 `None | None`。
_Date = date

StopType = Literal["attraction", "food", "hotel"]


class StopIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    stop_type: StopType = "attraction"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)


class StopOut(StopIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order_index: int
    checked: bool = False
    details: dict | None = None


class StopUpdate(BaseModel):
    """手动编辑站点：所有字段可选，未传字段保持原值。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    stop_type: StopType | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)


class StopOrderIn(BaseModel):
    """整日站点顺序重排：提供该日全部站点 id，按给定顺序写入 order_index。"""

    order: list[str] = Field(min_length=1, description="该日全部站点 id，按目标顺序排列")


class DayIn(BaseModel):
    day_number: int = Field(ge=1)
    date: _Date | None = None
    note: str | None = None


class DayOut(DayIn):
    model_config = ConfigDict(from_attributes=True)
    id: str
    stops: list[StopOut] = []


class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    departure: str | None = Field(default=None, max_length=200, description="出发地（可选）")
    trip_type: str | None = Field(default=None, max_length=20, description="出行性质：休闲旅游/商务出差/探亲访友/亲子出游/蜜月度假")
    start_date: date
    end_date: date
    travelers: int = Field(default=1, ge=1)
    budget: float | None = Field(default=None, ge=0)

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date 不能早于 start_date")
        return v


class TripUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    destination: str | None = Field(default=None, min_length=1, max_length=200)
    departure: str | None = Field(default=None, max_length=200, description="出发地（可选）；传 null 清空")
    trip_type: str | None = Field(default=None, max_length=20, description="出行性质：休闲旅游/商务出差/探亲访友/亲子出游/蜜月度假")
    start_date: date | None = None
    end_date: date | None = None
    travelers: int | None = Field(default=None, ge=1)
    budget: float | None = Field(default=None, ge=0)
    status: Literal["draft", "planning", "confirmed", "archived"] | None = None


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    destination: str
    departure: str | None = None
    trip_type: str | None = None
    start_date: date
    end_date: date
    travelers: int
    budget: float | None
    status: str
    share_token: str | None = None
    edit_token: str | None = None
    # 人工兜底（task-human-escalation-eval）：最新 AI plan 的 quality 是否命中
    # 需人工复核信号（finalized / passed=false / degraded）。派生字段，非存储。
    escalated: bool = False
    created_at: datetime
    updated_at: datetime
    days: list[DayOut] = []


class TripListOut(BaseModel):
    items: list[TripOut]
    total: int
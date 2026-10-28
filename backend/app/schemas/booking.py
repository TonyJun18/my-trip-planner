"""预订条目 Schemas（task-booking-outlink：可预订建议 + 凭证回填）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BookingIn(BaseModel):
    """新增/回填一条预订条目。

    - kind/provider/title/provider_url 为「建议」字段（plan.generated 场景）；
    - order_no/credential 为「凭证回填」字段（user.confirmed 场景）；
    - reference：plan.generated / user.confirmed / channel.callback
    """

    kind: Literal["train", "hotel"] = "train"
    provider: Literal["ctrip", "qunar", "12306", "feizhu", "tongcheng", "manual"] = "ctrip"
    title: str | None = Field(default=None, max_length=300)
    provider_url: str | None = Field(default=None, max_length=500)
    order_no: str | None = Field(default=None, max_length=100)
    credential: str | None = Field(default=None, max_length=200)
    status: Literal["suggested", "pending", "confirmed", "cancelled"] = "suggested"
    reference: Literal["plan.generated", "user.confirmed", "channel.callback"] = "user.confirmed"
    amount: float | None = Field(default=None, ge=0)
    currency: str = "CNY"


class BookingOut(BaseModel):
    """一条预订条目（响应）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    kind: str
    provider: str
    title: str | None = None
    provider_url: str | None = None
    order_no: str | None = None
    credential: str | None = None
    status: str = "suggested"
    reference: str = "plan.generated"
    amount: float | None = None
    currency: str = "CNY"
    created_at: datetime
    updated_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None


class BookingStatusIn(BaseModel):
    """更新预订状态（confirm / cancel）。"""

    status: Literal["pending", "confirmed", "cancelled"] = "confirmed"
    order_no: str | None = Field(default=None, max_length=100)
    credential: str | None = Field(default=None, max_length=200)


class BookingSuggestedOut(BaseModel):
    """规划后 BookingAgent 产出的可预订建议（挂 plan.bookings）。"""

    kind: Literal["train", "hotel"] = "train"
    provider: Literal["ctrip", "qunar", "12306", "feizhu", "tongcheng", "manual"] = "ctrip"
    title: str | None = None
    provider_url: str | None = None
    price_estimate: float | None = None
    currency: str = "CNY"
    reference: Literal["plan.generated", "user.confirmed", "channel.callback"] = "plan.generated"
    status: Literal["suggested", "pending", "confirmed", "cancelled"] = "suggested"


class BookingListOut(BaseModel):
    """行程预订列表（owner 视角）。"""

    items: list[BookingOut] = Field(default_factory=list)
    total: int = 0
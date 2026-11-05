"""预订条目 Schemas（task-booking-outlink：可预订建议 + 凭证回填；task-book-ahead-scan：前瞻扫描）。"""
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

    kind: Literal["train", "hotel", "ticket"] = "train"
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


class BookingScanItemOut(BaseModel):
    """前瞻扫描建议（task-book-ahead-scan：Passage AI「Need tickets?」）。

    - 规则库扫描（timed-entry / 热门类目关键词）产出，basis=rule_based 诚实标注；
    - ``booking_payload``：可直接提交 POST /trips/{id}/bookings 的 BookingIn 载荷
      （复用既有 booking 链路落库；前端一键采纳）。
    """

    stop_id: str
    stop_name: str
    kind: Literal["train", "hotel", "ticket"] = "ticket"
    provider: Literal["ctrip", "qunar", "12306", "feizhu", "tongcheng", "manual"] = "ctrip"
    title: str | None = None
    reason: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    timed_entry: bool = False
    booking_payload: dict = Field(default_factory=dict)


class BookingScanOut(BaseModel):
    """行程预订前瞻扫描结果（owner 触发，规则库零凭证）。"""

    items: list[BookingScanItemOut] = Field(default_factory=list)
    total: int = 0
    basis: str = "rule_based"
    note: str = "规则库扫描，不含实时价格/余票；确认前请以 OTA 页面为准"


class StopLinkIn(BaseModel):
    """预订 ↔ 站点绑定请求（task-book-ahead-scan：确认号回填 stop）。"""

    stop_id: str = Field(min_length=1, max_length=36, description="行程内站点 id")
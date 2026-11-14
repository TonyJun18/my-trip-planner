"""预订条目 Schemas（task-booking-outlink：可预订建议 + 凭证回填；task-book-ahead-scan：前瞻扫描）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BookingIn(BaseModel):
    """新增/回填一条预订条目。

    - kind/provider/title/provider_url 为「建议」字段（plan.generated 场景）；
    - order_no/credential 为「凭证回填」字段（user.confirmed 场景）；
    - reference：plan.generated / user.confirmed / channel.callback / email.import
      （email.import = task-booking-ledger-rhythm 邮件归并台账）；
    - service_date/service_note：服务日期与备注（台账排序/倒计时/投影键，可选）。
    """

    kind: Literal["train", "hotel", "ticket", "flight"] = "train"
    provider: Literal["ctrip", "qunar", "12306", "feizhu", "tongcheng", "trip", "manual"] = "ctrip"
    title: str | None = Field(default=None, max_length=300)
    provider_url: str | None = Field(default=None, max_length=500)
    order_no: str | None = Field(default=None, max_length=100)
    credential: str | None = Field(default=None, max_length=200)
    status: Literal["suggested", "pending", "confirmed", "cancelled"] = "suggested"
    reference: Literal["plan.generated", "user.confirmed", "channel.callback", "email.import"] = (
        "user.confirmed"
    )
    service_date: date | None = None
    service_note: str | None = Field(default=None, max_length=500)
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
    service_date: date | None = None
    service_note: str | None = None
    amount: float | None = None
    currency: str = "CNY"
    days_until: int | None = None  # 台账倒计时（响应构造时计算，非 ORM 字段）
    created_at: datetime
    updated_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None


class BookingStatusIn(BaseModel):
    """更新预订状态（confirm / cancel）。

    - service_date/service_note：顺带修正服务日期与备注（可选）。显式传
      ``null`` 表示**清空**（pydantic ``model_fields_set`` 可区分「未传」与
      「显式清空」——task-booking-ledger-minors）。
    - amount：顺带修正金额（回填确认时用户填写的实付金额，默认可不传）。
    """

    status: Literal["pending", "confirmed", "cancelled"] = "confirmed"
    order_no: str | None = Field(default=None, max_length=100)
    credential: str | None = Field(default=None, max_length=200)
    service_date: date | None = None
    service_note: str | None = Field(default=None, max_length=500)
    amount: float | None = Field(default=None, ge=0)


class EmailMergeItem(BaseModel):
    """邮件解析出的预订条目（task-booking-ledger-rhythm 归并请求项）。

    - 字段与 email_import.EmailBookingOut 对齐（kind: flight/hotel/activity）；
    - 服务端绝不信任 status/credential——归并一律落 pending + reference=email.import；
    - code 缺失时服务端按内容合成 `em-` 幂等键（或校验客户端 fingerprint）。
    """

    kind: str = Field(default="hotel", max_length=20)  # flight/hotel/activity（activity→ticket）
    name: str | None = Field(default=None, max_length=300)
    code: str | None = Field(default=None, max_length=100)
    datetime: str | None = Field(default=None, max_length=40)
    amount: float | None = Field(default=None, ge=0)
    currency: str = "CNY"
    fingerprint: str | None = Field(default=None, max_length=64)


class EmailMergeListIn(BaseModel):
    """邮件条目批量归并请求体。"""

    items: list[EmailMergeItem] = Field(default_factory=list)


class EmailMergeOut(BaseModel):
    """归并结果（返回台账条目）。"""

    merged: list[BookingOut] = Field(default_factory=list)
    total: int = 0


class BookingRhythmItemOut(BaseModel):
    """一条节奏条目（task-booking-ledger-rhythm · booking-rhythm spec）。

    - phase：open=窗口已开 / upcoming=窗口未开 / closing=临近截止（≤3 天）；
    - basis 恒为 rule_based（纯日期数学，零外部源），note 带「以官方渠道为准」；
    - booking_id/stop_id：条目来源（台账条目或行程站点），二选一或均空。
    """

    kind: str
    target: str
    target_date: date
    window_open: date
    window_deadline: date
    phase: Literal["open", "upcoming", "closing"]
    basis: Literal["rule_based"] = "rule_based"
    note: str
    booking_id: str | None = None
    stop_id: str | None = None


class BookingRhythmOut(BaseModel):
    """节奏表（GET /bookings/rhythm 响应，实时计算不落库）。"""

    items: list[BookingRhythmItemOut] = Field(default_factory=list)
    total: int = 0


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
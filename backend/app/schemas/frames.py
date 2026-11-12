"""旅拍相框市场 Schemas（frame-marketplace）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RedeemRequest(BaseModel):
    """兑换码兑换请求。"""

    code: str = Field(min_length=4, max_length=64)


class FrameTemplateOut(BaseModel):
    """模板目录条目（含当前用户的 locked 标注）。"""

    slug: str
    name: str
    tier: Literal["free", "paid"]
    theme: str
    layout_config: dict[str, Any]
    price_cents: int = 0
    locked: bool = False


class FramePackOut(BaseModel):
    """模板包（售卖单元）。"""

    slug: str
    name: str
    description: str | None = None
    template_slugs: list[str] = []
    price_cents: int = 0


class CatalogOut(BaseModel):
    """模板目录（商店页展示，免登录可看）。"""

    templates: list[FrameTemplateOut]
    packs: list[FramePackOut]


class EntitlementOut(BaseModel):
    """已解锁模板包权益。"""

    pack_slug: str
    redeemed_at: str | None = None


class EntitlementsOut(BaseModel):
    """我的已解锁包列表。"""

    entitlements: list[EntitlementOut]


class RedeemOut(BaseModel):
    """兑换结果（幂等：重放返回已解锁）。"""

    redeemed: bool
    pack_slug: str
    entitlements: list[EntitlementOut]


class FrameStopOut(BaseModel):
    """投影中的打卡站点（坐标 + 趣事备注）。"""

    stop_id: str
    name: str
    stop_type: str
    lat: float | None = None
    lng: float | None = None
    description: str | None = None
    order_index: int = 0


class DayProjectionOut(BaseModel):
    """单日打卡卡数据投影（empty=true 表示当日无打卡数据）。"""

    trip_id: str
    destination: str
    day_id: str
    day_number: int
    date: str | None = None
    day_note: str | None = None
    empty: bool
    stops: list[FrameStopOut]


class SummaryDayOut(BaseModel):
    """总结图中的一天（有打卡数据的日期）。"""

    day_id: str
    day_number: int
    date: str | None = None
    day_note: str | None = None
    stops: list[FrameStopOut]


class SummaryStatsOut(BaseModel):
    """全程统计水印数据。"""

    days_with_checkins: int
    total_days: int
    checked_stops: int


class SummaryProjectionOut(BaseModel):
    """整程总结图数据投影（空日跳过；全程无打卡 empty=true）。"""

    trip_id: str
    destination: str
    start_date: str | None = None
    end_date: str | None = None
    empty: bool
    stats: SummaryStatsOut
    days: list[SummaryDayOut]


class CopyRequest(BaseModel):
    """配文生成请求。"""

    channel: Literal["xhs", "moments"] = "xhs"
    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"


class CopyOut(BaseModel):
    """配文生成结果（source 诚实标注；无自动发布副作用）。"""

    trip_id: str
    day_id: str | None = None
    channel: str
    empty: bool
    title: str
    body: str
    topics: list[str] = []
    source: Literal["llm", "template"]

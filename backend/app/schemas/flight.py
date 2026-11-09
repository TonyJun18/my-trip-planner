"""机票特价 Schemas（FlightDeals：2–3 个方案 + 用户确认）。

口径（与 flight_deals_service 一致）：
- ``price_kind`` 恒为 ``from``：航线页展示的最低「起价」，不是所选日期实时报价；
- 每条 option 必须带 ``source_url``（可点开核对）与 ``confidence``（0–1）；
- ``status``：completed / partial / degraded / skipped —— 前端据此决定展示卡片还是降级文案。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FlightDealOptionOut(BaseModel):
    """一个可选机票方案（确定性排序产出：最省 / 日期最贴合 / 直飞优先）。"""

    model_config = ConfigDict(extra="allow")

    option_id: str
    strategy: str = Field(default="alternative", description="cheapest | best_dates | safest | alternative")
    title: str = ""
    reason: str | None = None
    price: float | None = None
    currency: str = "CNY"
    price_kind: str = "from"
    airlines: list[str] = Field(default_factory=list)
    outbound_date: str | None = None
    inbound_date: str | None = None
    stops: int | None = None
    source: str | None = None
    source_url: str | None = None
    confidence: float = 0.0
    note: str | None = None


class FlightDealPromoOut(BaseModel):
    """促销活动摘要（不做价格断言，只给标题 + 链接 + 摘要）。"""

    model_config = ConfigDict(extra="allow")

    title: str
    source_url: str
    snippet: str | None = None
    source: str | None = None
    confidence: float = 0.0
    note: str | None = None


class FlightDealsOut(BaseModel):
    """行程机票推荐视图（GET /trips/{id}/flight-deals）。"""

    trip_id: str
    route: dict = Field(default_factory=dict)
    fetched_at: str | None = None
    provider: str | None = None
    status: str = "degraded"
    price_kind: str = "from"
    options: list[FlightDealOptionOut] = Field(default_factory=list)
    promos: list[FlightDealPromoOut] = Field(default_factory=list)
    note: str | None = None
    is_cached: bool = False
    # 用户已选的方案（来自 TripBooking kind=flight, status=pending）；未选为 None
    selected: dict | None = None
    selected_booking_id: str | None = None


class FlightChoiceIn(BaseModel):
    """确认选择一个机票方案（或手动填写）。

    - ``option_id``：从 ``GET /flight-deals`` 的 options 里选（推荐路径）；
    - ``option``：手动兜底（用户自己找到的航班），必须带 title/price/currency；
    - 二者至少有其一。
    """

    option_id: str | None = Field(default=None, max_length=64)
    option: dict | None = Field(default=None, description="手动方案：{title, price, currency, source_url?}")
    travelers: int | None = Field(default=None, ge=1, le=20)


class FlightChoiceOut(BaseModel):
    """确认结果：写入的预订条目（status=pending，表示「已选未出票」）+ 方案快照。"""

    trip_id: str
    booking_id: str
    status: str
    reference: str
    amount: float | None = None
    currency: str = "CNY"
    title: str | None = None
    provider_url: str | None = None
    option: dict | None = None
    updated_at: datetime | None = None

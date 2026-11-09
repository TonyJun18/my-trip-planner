"""机票特价快照（FlightDeals 采集结果的持久缓存）。

为什么不放进 ``trips``/``trip_plans``：
- 快照是「航线 × 日期窗」维度的公共素材，与具体行程无关（同一航线可被多个行程复用）；
- 与 `plan_tasks` 一样是运行时产物，不应污染行程聚合根；
- TTL 语义由 ``expires_at`` 表达，读取侧按新鲜度决定是否重采。
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


class FlightDealSnapshot(Base):
    """一次机票采集的结果快照（``payload`` 与 ``plan.flight_deals`` 同构）。"""

    __tablename__ = "flight_deal_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    route_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    """出发地|目的地|start_date|end_date|travelers（见 flight_deals_service.route_key）。"""
    provider: Mapped[str] = mapped_column(String(32), default="tavily", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="degraded", nullable=False)
    options_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

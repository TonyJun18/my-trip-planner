"""收藏 → 一键成路线 Schemas（task-favorites-to-route）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class FavoriteStopCandidate(BaseModel):
    """聚合候选：收藏行程站点（按站点名去重，附来源行程标题）。"""

    name: str
    stop_type: str = "attraction"
    lat: float | None = None
    lng: float | None = None
    estimated_cost: float | None = None
    estimated_duration_minutes: int | None = None
    description: str | None = None
    source_trips: list[str] = []


class FavoriteStopsOut(BaseModel):
    """收藏聚合端点输出（{items, total, trips}）。"""

    items: list[FavoriteStopCandidate]
    total: int
    trips: int


def favorite_stops_out(payload: dict[str, Any]) -> FavoriteStopsOut:
    """dict → schema（service 保持纯 dict，便于测试）。"""
    return FavoriteStopsOut(
        items=[FavoriteStopCandidate(**item) for item in payload["items"]],
        total=payload["total"],
        trips=payload["trips"],
    )
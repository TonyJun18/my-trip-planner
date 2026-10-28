"""收藏灵感夹 Schemas（task-share-token-lifecycle）。"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class FavoriteOut(BaseModel):
    """一条收藏：展示行程摘要 + 分享令牌（前端可直接打开分享页）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    share_token: str | None = None
    created_at: datetime


class FavoriteListOut(BaseModel):
    items: list[FavoriteOut]
    total: int
"""行程评分 / 信任信号 Schemas（task-trip-rating-signal）。

契约：
- POST /trips/{trip_id}/rating   {rating: 1-5, visited?: bool} → RatingOut（登录）
- PUT  /trips/{trip_id}/rating   同上（幂等改分 / 翻转 visited）→ RatingOut
- GET  /trips/{trip_id}/rating   单行程评分详情（登录可见自己的 user_rating）
- DELETE /trips/{trip_id}/rating 删除自己的评分 → 204（幂等）
- GET  /trips/ratings/summary?trip_ids=a,b,c  批量聚合（免登录）
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RatingIn(BaseModel):
    """提交评分：1-5 星整数；visited 为「我去过」标记（默认 False）。"""

    rating: int = Field(ge=1, le=5)
    visited: bool = False


class RatingOut(BaseModel):
    """单条评分响应。"""

    model_config = ConfigDict(from_attributes=True)

    trip_id: str
    rating: int
    visited: bool
    created_at: datetime
    updated_at: datetime


class RatingSummaryOut(BaseModel):
    """画廊热度聚合（免登录）：count / avg / visited_count。"""

    trip_id: str
    count: int = 0
    avg: float | None = None  # 无评分时为 None，避免 0 被误解为「差评」
    visited_count: int = 0


class RatingListOut(BaseModel):
    items: list[RatingSummaryOut]
    total: int
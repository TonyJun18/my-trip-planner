"""旅程护照 Schemas（task-journey-passport）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BadgeOut(BaseModel):
    """一枚旅程徽章。"""

    key: str
    label: str
    earned_at: str | None = None


class PassportOut(BaseModel):
    """行程护照视图（owner 与分享只读共用）。"""

    trip_id: str
    phase: str = "upcoming"
    badges: list[BadgeOut] = Field(default_factory=list)
    badge_count: int = 0
    last_progress_at: str | None = None
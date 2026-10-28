"""旅程追踪 Schemas（task-journey-timeline：行中事件流投影 + 高光）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DayJourneyOut(BaseModel):
    """一天的旅程投影。

    - status: todo / partial / completed / skipped（按该日站点打卡与跳过事件）
    - completed / total: 已打卡站点数 / 总站点数（total≥1 才有意义）
    """

    day_number: int
    date: str | None = None
    theme: str | None = None
    status: str = "todo"
    completed: int = 0
    total: int = 0
    highlights: list[str] = Field(default_factory=list)


class HighlightOut(BaseModel):
    """一条旅程有故事的高光（来自 check/delay/vote/booking 事件）。"""

    event_type: str
    summary: str
    day_number: int | None = None
    created_at: str | None = None


class JourneyOut(BaseModel):
    """旅程全程追踪投影（读时聚合，零新表）。

    - journey_progress: 已打卡站点数 / 总站点数 × 100（只算非酒店站点；
      行中打卡只针对 attraction/food，酒店/交通占位不计入）
    - day_status[]: 按天分组（completed/partial/todo/skipped + 高光）
    - expense_total / by_category / per_person: 复用 expense.compute_balance 口径
    - booking_status[]: suggested/pending/confirmed/cancelled 计数（接预订方案 TripBooking）
    - highlights[]: 从事件流里挑「有故事」的（check/delay/vote/comment）
    """

    trip_id: str
    phase: str = "upcoming"  # upcoming / live / finished
    journey_progress: float = 0.0
    completed_stops: int = 0
    total_stops: int = 0
    days: list[DayJourneyOut] = Field(default_factory=list)
    expense_total: float = 0.0
    by_category: dict[str, float] = Field(default_factory=dict)
    per_person: float = 0.0
    booking_status: dict[str, int] = Field(default_factory=dict)
    highlights: list[HighlightOut] = Field(default_factory=list)
    data_complete: bool = True  # 事件流缺失部分站点时 False（诚实口径）
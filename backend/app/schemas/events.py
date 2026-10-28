"""行程事件 Schemas（task-trip-event-notify：append-only 事件流）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TripEventOut(BaseModel):
    """行程事件（task-trip-event-notify）：append-only 事件流的单条记录。

    - event_type: revise / check / skip / delay / comment / vote / edit / share
    - payload: 可读摘要（前端 feed 直接展示）
    """

    id: str
    trip_id: str
    event_type: str
    payload: dict | None = None
    created_at: datetime | None = None


class TripEventListOut(BaseModel):
    """行程事件列表（最新在前，分页）。"""

    items: list[TripEventOut] = []
    total: int = 0
"""旅程故事 Schemas（task-trip-story：晒图高光卡）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StoryRequest(BaseModel):
    """生成旅程故事请求。"""

    channel: Literal["xhs", "moments", "poster"] = "xhs"
    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"


class StoryStatsOut(BaseModel):
    """故事引用到的确定性数据（只来自真实投影，不编造）。"""

    destination: str = ""
    days: int = 0
    stops: int = 0
    checked: int = 0
    expense_total: float = 0.0
    per_person: float = 0.0
    badge_count: int = 0
    phase: str = "upcoming"


class StoryOut(BaseModel):
    """旅程故事卡产物。"""

    trip_id: str
    empty: bool = False
    channel: str = "xhs"
    title: str = ""
    body: str = ""
    topics: list[str] = Field(default_factory=list)
    stats: StoryStatsOut = Field(default_factory=StoryStatsOut)
    badges: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    source: str = "template"  # llm / template
    image_spec: dict = Field(default_factory=dict)  # {width,height,ratio}
    message: str | None = None  # empty=True 时的引导文案
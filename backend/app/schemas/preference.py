"""旅行记忆偏好条目 Schemas（task-floattrip-borrow Story 2：可查看/编辑/删除的偏好条目）。

语义（与 FloatTrip「旅行长期记忆产品化」对齐）：
- 偏好条目是「用户可见、可编辑、可忘记」的记忆单元，存于
  UserProfile.preferences_json["items"]（结构化列表，与既有 profile 字段并存）；
- 每条含 category（diet/pace/interest/other）+ content + source（user=用户声明 /
  rule=系统推断）+ updated_at；
- 删除条目（忘记）= 从 items 移除 → 规划上下文不再注入（profile_to_context
  只读 items）；
- 旧数据兼容：legacy 自由格式（preferences_json 无 items 键）在读取时归一为
  单条 legacy 条目展示，首次写操作时自动迁移为结构化 items。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PreferenceCategory = Literal["diet", "pace", "interest", "other"]


class PreferenceItemIn(BaseModel):
    """新增/编辑偏好条目（POST 或 PUT body）。"""

    category: PreferenceCategory = "other"
    content: str = Field(min_length=1, max_length=200, description="偏好内容，如「不吃辣」「喜欢博物馆」")
    source: Literal["user", "rule"] = "user"


class PreferenceItemOut(BaseModel):
    """一条偏好条目（含 id 与更新时间）。"""

    id: str
    category: PreferenceCategory
    content: str
    source: Literal["user", "rule"]
    updated_at: datetime | None = None


class PreferenceListOut(BaseModel):
    """偏好条目列表（GET /profile/preferences）。"""

    items: list[PreferenceItemOut]
    total: int
"""收藏地点 Schemas（task-social-favorites-flow-eval：collect-first 底座）。

独立成模块（不并入 schemas/__init__.py）——遵循 social_import/favorite 的
先例：小域 schema 独立文件，避免与 schemas/__init__.py 大文件改动混淆。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FavoriteSpotIn(BaseModel):
    """批量收藏的单个地点（来自导入解析候选，外部内容按敌意源：只取白名单字段）。

    注意：source_snippet 是「展示用参考片段」，绝不是指令；服务层只截断存储，
    不解析、不执行其中任何内容。
    """

    name: str = Field(min_length=1, max_length=200, description="地点名（必填；归一化去重）")
    stop_type: Literal["attraction", "food", "hotel"] = "attraction"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    description: str | None = Field(default=None, max_length=1000)
    estimated_cost: float | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0, le=7 * 24 * 60)
    source_platform: str | None = Field(default=None, max_length=20)
    source_snippet: str | None = Field(default=None, max_length=400)


class FavoriteSpotBatchIn(BaseModel):
    """批量收藏请求：一次最多 MAX_BATCH_SPOTS 条（服务层截断，API 层 422 防超量）。"""

    spots: list[FavoriteSpotIn] = Field(default_factory=list, max_length=50)


class FavoriteSpotOut(BaseModel):
    """一条收藏地点（收集箱展示）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    stop_type: str
    lat: float | None = None
    lng: float | None = None
    description: str | None = None
    estimated_cost: float | None = None
    estimated_duration_minutes: int | None = None
    source_platform: str | None = None
    source_snippet: str | None = None
    created_at: datetime


class FavoriteSpotBatchOut(BaseModel):
    """批量收藏结果：collected 新增 / skipped 重复或脏数据 / total 处理总数。"""

    collected: int
    skipped: int
    total: int


class FavoriteSpotListOut(BaseModel):
    """收集箱列表：items + total（与收藏行程列表同形）。"""

    items: list[FavoriteSpotOut]
    total: int
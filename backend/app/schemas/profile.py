"""用户画像 Schemas：跨会话偏好记忆的请求/响应模型。

CRUD 语义：
- GET /api/v1/profile          → 读取当前用户画像（不存在返回默认空画像，不报错）
- PUT /api/v1/profile          → 全量覆盖 upsert（不存在则创建，存在则整体替换）
- PATCH 暂不提供：画像字段少且常整段更新，PUT 即可满足；避免过度设计
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileIn(BaseModel):
    """画像写入模型：所有字段可选，未传字段在 upsert 时清空/置 None。

    显式全量语义：只传部分字段时，其余画像维度会被重置为空（前端每次提交完整画像）。
    """

    traveler_type: str | None = Field(default=None, max_length=30, description="出行人群：情侣/亲子/朋友/独自/商务")
    pace: str | None = Field(default=None, max_length=30, description="节奏偏好：轻松/适中/紧凑")
    budget_tier: str | None = Field(default=None, max_length=30, description="预算档：经济/舒适/豪华")
    favorite_cities: list[str] | None = Field(default=None, max_length=20, description="常去城市列表")
    preferences_json: dict | None = Field(default=None, description="自由格式偏好（饮食禁忌/兴趣标签等）")

    @field_validator("favorite_cities")
    @classmethod
    def _clean_cities(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [c.strip() for c in v if c and c.strip()]
        return cleaned or None

    @field_validator("traveler_type", "pace", "budget_tier")
    @classmethod
    def _clean_str(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ProfileOut(BaseModel):
    """画像响应模型：from_attributes 从 ORM 直接序列化。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    traveler_type: str | None = None
    pace: str | None = None
    budget_tier: str | None = None
    favorite_cities: list[str] | None = None
    preferences_json: dict | None = None
    updated_at: datetime
"""用户画像模型：跨会话偏好记忆（同程记忆关联性 / 飞猪微细分 / Layla 个性化）。"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


class UserProfile(Base):
    """用户偏好画像：每个用户一行（user_id 唯一），规划时注入 Agent 上下文。

    - 字段来自 task-user-profile-memory 的验收要求：人群 / 节奏 / 预算档 / 常去城市
      （同程记忆关联性、飞猪微细分、Layla 个性化）。
    - ``preferences_json`` 兜底承载其它自由格式偏好（饮食禁忌、出行偏好等），
      避免画像结构频繁加列；前端/API 可整体读写。
    - ``updated_at`` 供前端/后台判断画像新鲜度，不参与规划上下文。
    """

    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profiles_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 一用户一画像：user_id 唯一；级联删除（用户注销时画像一并清理）
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 出行人群：如 情侣 / 亲子（带娃） / 朋友 / 独自 / 商务
    traveler_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 节奏偏好：轻松 / 适中 / 紧凑（慢节奏每天 <=3 点等）
    pace: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 预算档：经济 / 舒适 / 豪华（映射为规划时的预算倾向与酒店档位）
    budget_tier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # 常去城市（最近去过的城市，逗号分隔或 JSON 数组；用于推荐/记忆关联）
    favorite_cities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 自由格式偏好（饮食禁忌、兴趣标签、交通偏好等），整体读写
    preferences_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
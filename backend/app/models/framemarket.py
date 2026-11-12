"""SQLAlchemy ORM 模型：旅拍相框市场（frame-marketplace）领域实体。

模板目录为代码内置种子数据（tier=free/paid），模板本体是前端渲染器
可执行的 JSON 配置（layout_config），后端只存目录与价格。
兑换码只存 SHA-256 哈希——明文由一次性脚本输出供上架，不落库。
权益以 (user_id, pack_slug) 唯一约束保证幂等兑换。
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


class FrameTemplate(Base):
    """相框模板目录条目（种子数据，非用户数据）。"""

    __tablename__ = "frame_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tier: Mapped[str] = mapped_column(String(10), default="free", server_default="free")  # free/paid
    theme: Mapped[str] = mapped_column(String(20), default="minimal")  # 文艺/搞笑/极简/手账 -> minimal/warm/cheerful/journal
    layout_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    price_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class FramePack(Base):
    """模板包（售卖单元，1 包 N 套模板）。"""

    __tablename__ = "frame_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    template_slugs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    price_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class RedemptionCode(Base):
    """兑换码（只存哈希；status: unused/used/revoked）。"""

    __tablename__ = "redemption_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    pack_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="unused", server_default="unused")
    redeemed_by: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class FrameEntitlement(Base):
    """用户已解锁模板包权益（兑换后落库，幂等去重）。"""

    __tablename__ = "frame_entitlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    pack_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("user_id", "pack_slug", name="uq_frame_entitlement_user_pack"),)

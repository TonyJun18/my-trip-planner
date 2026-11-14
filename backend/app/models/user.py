"""用户模型：邮箱 / 手机号注册登录。"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


class User(Base):
    """系统用户（owner）—— 邮箱/手机号密码注册，或 Google OAuth 登录。"""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # 登录标识：邮箱 或 手机号（两者至少一个）
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    # Google 账号唯一标识（sub）—— 登录绑定用；同一 Google 账号始终映射同一用户
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    # Google 用户头像（可选，前端展示）
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 显示名（可选，默认取 email/phone 前缀）
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 密码哈希（PBKDF2-SHA256，不存明文）。未设置密码（如仅手机号验证码登录）可为空
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 运营编辑能力（ADR-0001 内容发现层）：staff 可对任意公开行程标 featured，
    # 通过 env STAFF_USER_IDS 白名单授予，不建管理后台。
    is_staff: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def login_id(self) -> str:
        """用于展示的登录标识。"""
        return self.email or self.phone or self.id
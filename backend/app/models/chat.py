"""SQLAlchemy ORM 模型：对话式行程助手（B 期，参考 pi-durable conversation 简化版）。

- ChatSession：一段持久会话（属于某个登录用户），保存系统提示词与元数据。
- ChatMessage：会话内的一条消息（user / assistant / tool），content 存结构化 JSON。
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid4())


class ChatSession(Base):
    """一段对话式行程助手会话。

    归属：``user_id`` 非空（登录用户专有）。会话保存：
    - ``title``：首条用户消息截断（前端展示用）
    - ``context_json``：会话级上下文（如当前关联的 trip_id / 目的地 / 日期范围），
      用于多轮对话间保持业务状态（B 期最小实现；后续可扩展为完整画像）。
    """

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    """会话内一条消息。

    - ``role``：user / assistant / tool（与 Agent 消息角色对应）
    - ``content``：文本内容；``tool_call`` / ``tool_result`` 为可选 JSON（工具调用记录）
    - ``error``：可选，assistant 失败时记录错误摘要
    - 排序用 ``created_at``（不依赖自增 id，避免迁移复杂度）
    """

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_call: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="messages")
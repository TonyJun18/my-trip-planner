"""Chat Schemas：会话与消息（B 期：对话式行程助手）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreate(BaseModel):
    """创建会话：可选标题与初始上下文（如关联 trip_id / 目的地）。"""

    title: str | None = Field(default=None, max_length=200, description="会话标题；缺省取首条消息摘要")
    context: dict | None = Field(default=None, description="会话级上下文（如关联 trip_id / 目的地）")


class ChatSessionOut(BaseModel):
    """会话列表/详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    context: dict | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionListOut(BaseModel):
    items: list[ChatSessionOut]
    total: int


class ChatMessageOut(BaseModel):
    """会话内一条消息。

    role: user / assistant / tool。
    content: 文本内容；tool_call / tool_result 为可选 JSON（工具调用记录）。
    error: 可选；assistant 失败时记录摘要。
    """

    id: str
    session_id: str
    role: str
    content: str = ""
    tool_call: dict | None = None
    tool_result: dict | None = None
    error: str | None = None
    created_at: datetime


class ChatMessageListOut(BaseModel):
    items: list[ChatMessageOut]
    total: int


class ChatSendIn(BaseModel):
    """发送一条用户消息。

    message 必填（1-2000 字符）；provider 可选（对齐 PlanRequest 默认 auto）。
    """

    message: str = Field(min_length=1, max_length=2000, description="用户输入（文本）")
    provider: str = "auto"
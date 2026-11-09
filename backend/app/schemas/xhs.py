"""小红书笔记 Schemas：内容生成（方案 A）+ 发布通道（方案 C）。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class XhsNoteRequest(BaseModel):
    """生成小红书笔记请求。"""

    provider: Literal["auto", "openai", "deepseek", "ollama"] = "auto"


class XhsNoteOut(BaseModel):
    """小红书笔记产物：标题/正文/话题 + 复制用完整文案 + 生成来源。"""

    title: str
    body: str
    topics: list[str] = Field(default_factory=list)
    full_text: str
    source: str = "template"  # llm / template（标注生成方式，前端提示用）
    image_spec: dict = Field(default_factory=dict)  # {width,height,ratio} 封面规格


class XhsAssetRequest(BaseModel):
    """上传发布用图片（前端 canvas → dataURL）。"""

    data_url: str = Field(min_length=32, max_length=32_000_000)


class XhsAssetOut(BaseModel):
    """已落盘的图片资产。"""

    asset_id: str
    mime: str
    bytes: int
    width: int | None = None
    height: int | None = None
    url: str


class XhsPublishRequest(BaseModel):
    """提交一次发布（异步任务，立刻返回 job_id）。"""

    title: str = Field(min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=4000)
    topics: list[str] = Field(default_factory=list, max_length=20)
    asset_ids: list[str] = Field(default_factory=list, max_length=9)
    mode: Literal["manual", "rpa"] | None = None
    auto_submit: bool = False


class XhsPublishJobOut(BaseModel):
    """发布任务状态（含诚实口径的 state / reason / message）。"""

    job_id: str
    trip_id: str
    channel: str = "xhs"
    mode: str
    state: str
    submitted: bool = False
    reason: str | None = None
    message: str | None = None
    note_url: str | None = None
    screenshot: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    auto_submit: bool = False
    hint_key: str | None = None
    created_at: datetime
    updated_at: datetime


class XhsChannelOut(BaseModel):
    """发布通道能力（前端据此决定显示"发布"按钮还是"复制"引导）。"""

    channel: str = "xhs"
    mode: str = "manual"
    connected: bool = False
    requires_images: bool = False
    supports_auto_submit: bool = False
    hint: str = ""
    available_modes: list[str] = Field(default_factory=list)
    driver: str | None = None

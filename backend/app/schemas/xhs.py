"""小红书笔记 Schemas（方案 A：内容工厂）。"""
from __future__ import annotations

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
"""社交收藏导入 Schema：请求/响应的 Pydantic 模型。

独立成模块（不并入 schemas/__init__.py），避免与 schemas/__init__.py
改动混淆；API 层直接从本模块 import。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 输入上限（字符），与 service 层 MAX_TEXT_LENGTH 对齐；API 层 422 校验。
MAX_SOCIAL_TEXT_LENGTH = 20_000


class SocialImportRequest(BaseModel):
    """用户粘贴的社交分享文本（caption + 链接）。

    外部内容按敌意输入处理：服务层会剥离指令型行并标记，绝不把文本当指令。
    """

    text: str = Field(min_length=1, max_length=MAX_SOCIAL_TEXT_LENGTH, description="社交分享文本（caption + 链接）")


class SocialCandidateOut(BaseModel):
    """解析出的一个地点候选（前端勾选后并入行程）。"""

    name: str
    stop_type: Literal["attraction", "food", "hotel"] = "attraction"
    description: str = ""
    estimated_cost: float | None = None
    estimated_duration_minutes: int | None = None
    source_lines: list[int] = Field(default_factory=list, description="来源行号（1-based）")


class SocialFlaggedLineOut(BaseModel):
    """被判定为敌意/指令型的原文行（展示给用户确认，不进入候选）。"""

    line_number: int
    content: str
    reason: str


class SocialImportResultOut(BaseModel):
    """社交 caption 解析结果：地点候选 + 敌意行标记。"""

    candidates: list[SocialCandidateOut] = Field(default_factory=list)
    flagged_lines: list[SocialFlaggedLineOut] = Field(default_factory=list)
    dropped_lines: int = Field(default=0, ge=0, description="超出候选上限被丢弃的候选数")
    source_platform: str = Field(default="", description="识别到的平台（tiktok/instagram/xiaohongshu/douyin/weibo/bilibili/unknown）")
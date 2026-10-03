"""邮件导入 Schema：请求/响应的 Pydantic 模型。

独立成模块（不并入 schemas/__init__.py），避免与用户未提交的
schemas/__init__.py 改动混淆；API 层直接从本模块 import。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 输入上限（字符），与 service 层 MAX_TEXT_LENGTH 对齐；API 层 422 校验。
MAX_EMAIL_TEXT_LENGTH = 20_000


class EmailImportRequest(BaseModel):
    """用户粘贴的预订确认邮件文本。

    外部内容按敌意输入处理：服务层会剥离指令型行并标记，绝不把文本当指令。
    """

    text: str = Field(min_length=1, max_length=MAX_EMAIL_TEXT_LENGTH, description="预订确认邮件原文")


class EmailBookingOut(BaseModel):
    """一条结构化预订条目（航班/酒店/活动）。

    金额字段（amount + currency）可由前端并入预算视图。
    """

    kind: Literal["flight", "hotel", "activity"]
    name: str = ""
    code: str | None = None
    datetime: str | None = None
    amount: float | None = None
    currency: str = "CNY"
    source_lines: list[int] = Field(default_factory=list, description="来源行号（1-based）")


class EmailFlaggedLineOut(BaseModel):
    """被判定为敌意/指令型的原文行（展示给用户确认，不进入条目/候选）。"""

    line_number: int
    content: str
    reason: str


class EmailImportResultOut(BaseModel):
    """邮件解析结果：预订条目 + 站点候选（活动/酒店）+ 敌意行标记。"""

    bookings: list[EmailBookingOut] = Field(default_factory=list)
    # 候选复用 note-import 结构：酒店/活动条目可勾选并入行程。
    candidates: list[dict] = Field(default_factory=list)
    flagged_lines: list[EmailFlaggedLineOut] = Field(default_factory=list)
    dropped_lines: int = Field(default=0, ge=0, description="超出候选上限被丢弃的候选数")
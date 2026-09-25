"""笔记导入 Schema：请求/响应的 Pydantic 模型。

独立成模块（不并入 schemas/__init__.py），避免与用户未提交的
schemas/__init__.py 改动混淆；API 层直接从这里 import。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NoteImportRequest(BaseModel):
    """用户粘贴的攻略/种草笔记文本。

    外部内容按敌意输入处理：服务层会剥离指令型行并标记，绝不把文本当指令。
    """

    text: str = Field(min_length=1, max_length=20000, description="攻略/种草笔记原文")


class NoteStopCandidateOut(BaseModel):
    """解析出的一个站点候选（前端勾选后并入行程）。"""

    name: str
    stop_type: Literal["attraction", "food", "hotel"] = "attraction"
    description: str = ""
    estimated_cost: float | None = None
    estimated_duration_minutes: int | None = None
    source_lines: list[int] = Field(default_factory=list, description="来源行号（1-based）")


class NoteFlaggedLineOut(BaseModel):
    """被判定为敌意/指令型的原文行（展示给用户确认，不进入候选）。"""

    line_number: int
    content: str
    reason: str


class NoteImportResultOut(BaseModel):
    """笔记解析结果：站点候选 + 敌意行标记。"""

    candidates: list[NoteStopCandidateOut] = Field(default_factory=list)
    flagged_lines: list[NoteFlaggedLineOut] = Field(default_factory=list)
    dropped_lines: int = Field(default=0, ge=0, description="超出候选上限被丢弃的行数")
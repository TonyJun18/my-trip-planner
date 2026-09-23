"""分享页协作 Schemas：评论 / 站点投票（免登录，凭 share_token）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommentIn(BaseModel):
    """访客发表评论。"""

    author_name: str | None = Field(default=None, max_length=50, description="访客昵称（可选，默认匿名访客）")
    content: str = Field(min_length=1, max_length=500, description="评论内容")

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("评论内容不能为空")
        return v


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trip_id: str
    author_name: str | None = None
    content: str
    created_at: datetime


class VoteIn(BaseModel):
    """站点投票：方向 1=👍 / -1=👎。"""

    value: int = Field(ge=-1, le=1, description="1=👍 / -1=👎")


class VoteOut(BaseModel):
    """投票结果：该站点最新计数 + 我的选择（-1/0/1）。"""

    stop_id: str
    up: int
    down: int
    my_value: int = Field(ge=-1, le=1)
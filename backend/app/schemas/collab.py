"""分享页协作 Schemas：评论 / 站点投票 / 受邀编辑（免登录，凭令牌）。"""
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


class InvitedStopUpdate(BaseModel):
    """受邀编辑：站点受限字段更新（不经 AI 修订，直接写库）。

    只允许协作者改「轻量协作字段」：备注/描述/名称/勾选。
    坐标、花费、时长等结构化规划数据不可由受邀者改动（保持规划层权威）。
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    checked: bool | None = None


class SharedEditOut(BaseModel):
    """受邀编辑状态：edit_token 是否存在 + 完整分享 URL。"""

    trip_id: str
    edit_token: str
    edit_url: str
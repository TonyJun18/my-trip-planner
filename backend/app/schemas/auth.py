"""认证 Schemas：注册 / 登录 / 用户信息 / 令牌。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RegisterIn(BaseModel):
    """注册：邮箱或手机号（至少一个）+ 密码。"""

    email: str | None = Field(default=None, max_length=255, description="邮箱（与手机号至少一个）")
    phone: str | None = Field(default=None, max_length=32, description="手机号（与邮箱至少一个）")
    password: str = Field(min_length=8, max_length=128, description="密码（至少 8 位）")
    display_name: str | None = Field(default=None, max_length=100)


class LoginIn(BaseModel):
    """登录：邮箱或手机号 + 密码。"""

    account: str = Field(min_length=3, max_length=255, description="邮箱或手机号")
    password: str = Field(min_length=1, max_length=128)


class UserMeOut(BaseModel):
    """当前用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None = None
    phone: str | None = None
    display_name: str | None = None


class TokenOut(BaseModel):
    """登录/注册响应：JWT + 用户信息。"""

    access_token: str
    token_type: str = "bearer"
    user: UserMeOut


class UserCreateOut(UserMeOut):
    """（预留）管理员创建用户响应。"""


class GoogleLoginIn(BaseModel):
    """Google 登录：前端传回的 ID Token（Google Identity Services 的 credential）。"""

    id_token: str = Field(min_length=20, max_length=8192, description="Google ID Token (JWT)")
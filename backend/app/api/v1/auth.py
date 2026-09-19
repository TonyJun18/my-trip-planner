"""认证 API：注册 / 登录 / 当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserMeOut
from app.services import auth_service

router = APIRouter()


@router.post("/register", response_model=TokenOut, status_code=201, summary="注册（邮箱或手机号）")
async def register(data: RegisterIn, db: AsyncSession = Depends(get_session)) -> TokenOut:
    return await auth_service.register(db, data)


@router.post("/login", response_model=TokenOut, summary="登录（邮箱或手机号 + 密码）")
async def login(data: LoginIn, db: AsyncSession = Depends(get_session)) -> TokenOut:
    return await auth_service.login(db, data)


@router.get("/me", response_model=UserMeOut, summary="当前用户信息")
async def me(
    current: User = Depends(get_current_user),
) -> UserMeOut:
    return auth_service.to_me_out(current)
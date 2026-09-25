"""认证服务：注册 / 登录 / 当前用户。"""
from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import User
from app.schemas import (
    LoginIn,
    RegisterIn,
    TokenOut,
    UserMeOut,
)


class AuthError(AppError):
    """认证业务错误（统一走 AppError 格式: {"error": {...}}）。"""

    status_code = 400
    code = "auth_error"


def _validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def _validate_phone(phone: str) -> bool:
    # 支持中国大陆 11 位手机号 + 国际区号（+CC N）
    return bool(re.match(r"^\+?[1-9]\d{7,14}$", phone))


def _normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    return phone


async def register(db: AsyncSession, data: RegisterIn) -> TokenOut:
    """注册：邮箱或手机号（至少一个），返回 token + 用户信息。"""
    email = data.email.strip().lower() if data.email else None
    phone = _normalize_phone(data.phone) if data.phone else None

    if not email and not phone:
        raise AuthError("邮箱或手机号至少填一个")
    if email and not _validate_email(email):
        raise AuthError("邮箱格式不正确")
    if phone and not _validate_phone(phone):
        raise AuthError("手机号格式不正确")

    display_name = data.display_name or email.split("@")[0] if email else (phone or "用户")

    # 唯一性校验（email / phone 各自唯一）
    conditions = []
    if email:
        conditions.append(User.email == email)
    if phone:
        conditions.append(User.phone == phone)
    existing = (
        await db.execute(select(User).where(or_(*conditions)))
    ).scalar_one_or_none()
    if existing is not None:
        raise AuthError("该邮箱或手机号已注册")

    user = User(
        email=email,
        phone=phone,
        display_name=display_name,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # 并发注册竞态：先查后插的两步之间另一个请求已插入同 email/phone，
        # 撞上唯一约束。回滚后统一转成 400（而非 500）。
        await db.rollback()
        raise AuthError("该邮箱或手机号已注册")
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        user=UserMeOut(id=user.id, email=user.email, phone=user.phone, display_name=user.display_name),
    )


async def login(db: AsyncSession, data: LoginIn) -> TokenOut:
    """登录：邮箱或手机号 + 密码。"""
    account = data.account.strip().lower()
    if not account:
        raise AuthError("请输入邮箱或手机号")

    phone = _normalize_phone(account) if not _validate_email(account) else None
    conditions = [User.email == account]
    if phone:
        conditions.append(User.phone == phone)
    user = (
        await db.execute(select(User).where(or_(*conditions)))
    ).scalar_one_or_none()

    if user is None or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise UnauthorizedError("账号或密码错误", code="bad_credentials")

    token = create_access_token(user.id)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        user=UserMeOut(id=user.id, email=user.email, phone=user.phone, display_name=user.display_name),
    )


async def get_user_by_token(db: AsyncSession, token: str) -> User | None:
    """从 Bearer token 解析用户。"""
    user_id = decode_access_token(token)
    if not user_id:
        return None
    return await db.get(User, user_id)


def to_me_out(user: User) -> UserMeOut:
    return UserMeOut(
        id=user.id,
        email=user.email,
        phone=user.phone,
        display_name=user.display_name,
    )
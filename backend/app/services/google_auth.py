"""Google OAuth 登录服务。

流程：前端使用 Google Identity Services (GIS) 拿到 ID Token（JWT），
后端通过 ``google-auth`` 库验证签名与声明（aud / iss / exp / email_verified），
并按 ``google_sub`` 或 ``email`` 查找/创建用户，最后签发项目自己的 JWT。

安全要点：
- 必须校验 ``email_verified=True``：Google 未验证的邮箱不能直接绑定账号，防冒用
- 校验 ``aud`` 等于本站 GOOGLE_CLIENT_ID（防 token 被其他应用复用）
- 校验 ``iss`` 为 Google 白名单（accounts.google.com / https://accounts.google.com）
- ``clock_skew_in_seconds`` 放宽容许少量时钟偏差
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token
from app.models import User
from app.schemas import TokenOut, UserMeOut

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthError(UnauthorizedError):
    """Google 登录失败（token 无效 / 配置缺失等）。统一 401。"""

    code = "google_auth_failed"


def _google_credentials() -> tuple[str, str]:
    client_id = settings.GOOGLE_CLIENT_ID
    if not client_id:
        raise GoogleAuthError("服务端未配置 GOOGLE_CLIENT_ID，请先在后端 .env 配置")
    return client_id


async def _find_or_create_user(db: AsyncSession, info: dict) -> User:
    """按 google_sub 或 email 查找/创建用户。

    - 已有 google_sub → 直接复用（重复登录幂等）
    - 无 google_sub 但 email 已注册（密码用户）→ 绑定到现有账号（同一人升级登录方式）
    - 都无 → 创建新用户（password_hash 留空，与「仅手机号用户无密码」设计一致）
    """
    google_sub: str = info["sub"]
    email: str | None = info.get("email") or None

    # 先按 google_sub 查
    user = (
        await db.execute(select(User).where(User.google_sub == google_sub))
    ).scalar_one_or_none()
    if user is not None:
        return user

    # 再按 email 查（仅当 Google 邮箱已验证，见 verify_google_id_token 前置校验）
    if email:
        user = (
            await db.execute(select(User).where(or_(User.email == email, User.google_sub == google_sub)))
        ).scalar_one_or_none()
        if user is not None:
            # 绑定：把 Google sub 挂到现有账号，以后直接用 sub 幂等登录
            user.google_sub = google_sub
            if not user.display_name:
                user.display_name = info.get("name")
            await db.commit()
            await db.refresh(user)
            return user

    user = User(
        email=email,
        google_sub=google_sub,
        display_name=info.get("name") or (email.split("@")[0] if email else None),
        avatar_url=info.get("picture"),
        # Google 用户不设密码：password_hash 留空
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _to_token_out(user: User) -> TokenOut:
    token = create_access_token(user.id)
    return TokenOut(
        access_token=token,
        token_type="bearer",
        user=UserMeOut(
            id=user.id,
            email=user.email,
            phone=user.phone,
            display_name=user.display_name,
        ),
    )


async def google_login(db: AsyncSession, id_token: str) -> TokenOut:
    """验证 Google ID Token 并完成登录/注册，返回项目 JWT。"""
    client_id = _google_credentials()[0]

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        info = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            audience=client_id,
            clock_skew_in_seconds=10,
        )
    except Exception as exc:  # ValueError / GoogleAuthError 等
        raise GoogleAuthError("Google ID Token 无效或已过期") from exc

    if info.get("iss") not in _GOOGLE_ISSUERS:
        raise GoogleAuthError("Google ID Token 签发者无效")
    if not info.get("email_verified"):
        raise GoogleAuthError("Google 邮箱未验证，无法登录")
    if not info.get("sub"):
        raise GoogleAuthError("Google ID Token 缺少 sub")

    user = await _find_or_create_user(db, info)
    return _to_token_out(user)
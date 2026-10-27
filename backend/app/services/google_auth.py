"""Google OAuth 登录服务。

流程：前端使用 Google Identity Services (GIS) 拿到 ID Token（JWT），
后端通过 ``google-auth`` 库验证签名与声明（aud / iss / exp / email_verified），
并按 ``google_sub`` 或 ``email`` 查找/创建用户，最后签发项目自己的 JWT。

安全要点：
- 必须校验 ``email_verified=True``：Google 未验证的邮箱不能直接绑定账号，防冒用
- 校验 ``aud`` 等于本站 GOOGLE_CLIENT_ID（防 token 被其他应用复用）
- 校验 ``iss`` 为 Google 白名单（accounts.google.com / https://accounts.google.com）
- ``clock_skew_in_seconds`` 放宽容许少量时钟偏差

网络可靠性（2026-10 修复）：
- google-auth 默认每次验证都重新拉取 Google 公钥（``www.googleapis.com/oauth2/v1/certs``），
  且其默认超时长达 120s——国内网络访问该端点 TLS 握手常卡数秒甚至数十秒，
  曾导致前端 Google 登录"授权后永远 loading"。
- 修复：``_CachedGoogleRequest`` 强制 10s 超时 + 进程内 TTL 缓存公钥响应（24h），
  并把 verify 挪到 ``asyncio.to_thread``，避免阻塞 FastAPI 事件循环。
"""
from __future__ import annotations

import asyncio
import threading
import time

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.common.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token
from app.models import User
from app.schemas import TokenOut, UserMeOut

_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

# 公钥端点请求超时（秒）。google-auth 默认 120s，国内网络访问 Google 常卡死，
# 前端 axios 又设 300s 超时 → 表现为"授权完成但一直 loading"。10s 后快速失败。
_GOOGLE_REQ_TIMEOUT = 10

# Google 公钥 TTL：官方说明约每天轮换一次，缓存 24h 内无需再联网。
_GOOGLE_CERTS_TTL_SECONDS = 24 * 3600


class _CachedCertsResponse:
    """极简 Response 兼容对象：google-auth verify 只读 ``.status`` / ``.data``。"""

    __slots__ = ("status", "data")

    def __init__(self, status: int, data: bytes):
        self.status = status
        self.data = data


class _CachedGoogleRequest:
    """包装 ``google.auth.transport.requests.Request``：

    - 强制短超时（默认 120s → 10s），Google 网络抖动时快速失败而非无限挂起；
    - 对 Google 公钥端点做进程内 TTL 缓存，登录热路径不再依赖外网，秒回。
    """

    def __init__(self) -> None:
        self._inner = google_requests.Request()  # type: ignore[assignment]  # 鸭子类型：测试注入 _FakeInner
        self._lock = threading.Lock()
        self._cached: tuple[float, _CachedCertsResponse] | None = None

    def __call__(self, url, method="GET", body=None, headers=None, timeout=_GOOGLE_REQ_TIMEOUT, **kwargs):
        if method == "GET" and url.startswith("https://www.googleapis.com/"):
            with self._lock:
                if self._cached and self._cached[0] > time.monotonic():
                    return self._cached[1]
            resp = self._inner(url, method=method, body=body, headers=headers, timeout=timeout, **kwargs)
            with self._lock:
                self._cached = (
                    time.monotonic() + _GOOGLE_CERTS_TTL_SECONDS,
                    _CachedCertsResponse(resp.status, resp.data),
                )
            return self._cached[1]
        # 非公钥端点：透传（同样强制超时）
        return self._inner(url, method=method, body=body, headers=headers, timeout=timeout, **kwargs)


class GoogleAuthError(UnauthorizedError):
    """Google 登录失败（token 无效 / 配置缺失等）。统一 401。"""

    code = "google_auth_failed"


def _google_credentials() -> str:
    """返回配置的 Google OAuth Client ID（校验已配置）。

    统一返回 str，调用方直接使用完整 Client ID（此前错误声明为 tuple
    导致 ``[0]`` 取到第一个字符，audience 校验必然失败）。
    """
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
    client_id = _google_credentials()

    try:
        # 同步网络验证挪到线程池；公钥请求带 10s 超时 + 24h 缓存（见 _CachedGoogleRequest）
        info = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            id_token,
            _CachedGoogleRequest(),
            audience=client_id,
            clock_skew_in_seconds=10,
        )
    except Exception as exc:  # ValueError / TransportError 等
        raise GoogleAuthError("Google ID Token 无效或已过期") from exc

    if info.get("iss") not in _GOOGLE_ISSUERS:
        raise GoogleAuthError("Google ID Token 签发者无效")
    if not info.get("email_verified"):
        raise GoogleAuthError("Google 邮箱未验证，无法登录")
    if not info.get("sub"):
        raise GoogleAuthError("Google ID Token 缺少 sub")

    user = await _find_or_create_user(db, info)
    return _to_token_out(user)
"""安全工具：密码哈希（PBKDF2-SHA256）+ JWT 签发/校验。

- 密码：标准库 ``hashlib.pbkdf2_hmac``（无第三方依赖、抗 GPU 爆破）
- JWT：PyJWT，HS256，带过期时间与签发者
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.common.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_ALGORITHM = "HS256"
_ITERATIONS = 600_000  # OWASP 推荐（2023+）
_PBKDF2_SALT_BYTES = 16


# ── 密码 ─────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    """生成 PBKDF2 哈希，格式: pbkdf2$iterations$salt_hex$hash_hex。"""
    salt = secrets.token_bytes(_PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码（常量时间比较，防时序攻击）。"""
    try:
        scheme, iterations, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


# ── JWT ──────────────────────────────────────────────────────
def _jwt_secret() -> str:
    """JWT 签名密钥：优先环境变量，否则进程级随机（重启后失效）。"""
    if getattr(settings, "JWT_SECRET", None):
        return settings.JWT_SECRET
    return getattr(_jwt_secret, "_fallback", None) or _gen_fallback()


def _gen_fallback() -> str:
    secret = secrets.token_hex(32)
    _jwt_secret._fallback = secret  # type: ignore[attr-defined]
    return secret


def assert_secure_jwt_secret() -> None:
    """启动期校验：非 dev 环境必须显式配置 JWT_SECRET，否则拒绝启动。

    背景：JWT_SECRET 缺失时 security 模块会退回进程级随机密钥——签发/校验
    用的是同一个进程内密钥，开发自测没问题；但部署后每次重启都会生成新
    密钥，导致**所有已登录用户全部 401 被登出**，且日志只显示 token_invalid，
    运维会误判为「登录过期」而非「部署配置错误」。

    本函数在 lifespan 启动时被 main.py 调用：
    - ``ENV != dev``（staging / prod / 任意非 dev）且 ``JWT_SECRET`` 为空 → 抛
      RuntimeError（启动失败，fail fast）；dev 环境允许随机密钥（开发便利），
      但打 warning 提示生产风险。
    """
    if settings.JWT_SECRET is not None and settings.JWT_SECRET.strip():
        return  # 已显式配置安全密钥

    if settings.ENV != "dev":
        raise RuntimeError(
            "JWT_SECRET 未配置：非 dev 环境必须显式设置 JWT_SECRET "
            "(生成: python -c \"import secrets; print(secrets.token_hex(32))\"，"
            f"当前 ENV={settings.ENV!r})。缺失会导致重启后所有已签发 token 失效"
            "（全员被迫重新登录）。"
        )

    # dev 环境：允许进程级随机密钥，但明确警告
    logger.warning(
        "JWT_SECRET 未配置：使用进程级随机密钥（重启后所有已签发 token 失效）。"
        "仅适用于本地开发；非 dev 环境启动将被拒绝。"
    )


def create_access_token(user_id: str, *, expires_minutes: int | None = None) -> str:
    """签发访问令牌。"""
    minutes = expires_minutes or settings.JWT_EXPIRE_MINUTES
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "iss": "my-trip-planner",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """校验并解析令牌，返回 user_id（无效/过期返回 None）。"""
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[_ALGORITHM], issuer="my-trip-planner")
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
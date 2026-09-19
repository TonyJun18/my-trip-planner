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
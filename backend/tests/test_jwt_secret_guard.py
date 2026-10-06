"""启动期 JWT_SECRET 校验（fail fast）。

对应审查结论「#4 JWT_SECRET 缺失时静默随机——一次重启，全站用户被登出且无法排查」：
- 非 dev 环境缺 JWT_SECRET → assert_secure_jwt_secret 抛 RuntimeError（启动失败）；
- dev 环境允许随机密钥但打 warning；
- 显式配置后任意环境放行。
"""
from __future__ import annotations

import pytest

from app.core.security import assert_secure_jwt_secret


@pytest.mark.parametrize(
    ("env", "secret", "expect_raise"),
    [
        ("dev", None, False),          # dev + 缺密钥 → 放行（打 warning）
        ("prod", None, True),          # prod + 缺密钥 → 拒绝启动
        ("staging", None, True),       # 其他非 dev + 缺密钥 → 拒绝启动
        ("prod", "s3cret", False),     # prod + 显式密钥 → 放行
        ("prod", "  ", True),          # 空白密钥视为未配置 → 拒绝启动
    ],
)
def test_assert_secure_jwt_secret(monkeypatch, env, secret, expect_raise):
    # 空白密钥也视为未配置
    effective_secret = secret if (secret is not None and secret.strip()) else None
    # 直接打桩 settings 的属性（避免改全局 settings 影响其他测试）
    class _FakeSettings:
        ENV = env
        JWT_SECRET = effective_secret

    monkeypatch.setattr("app.core.security.settings", _FakeSettings())
    if expect_raise:
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            assert_secure_jwt_secret()
    else:
        assert_secure_jwt_secret()  # 不应抛


def test_dev_missing_secret_logs_warning(monkeypatch, caplog):
    """dev 缺密钥 → 不抛但记录 warning，运维能看到风险提示。"""
    import logging

    class _FakeSettings:
        ENV = "dev"
        JWT_SECRET = None

    monkeypatch.setattr("app.core.security.settings", _FakeSettings())
    with caplog.at_level(logging.WARNING, logger="app.core.security"):
        assert_secure_jwt_secret()
    assert any("JWT_SECRET" in rec.message and "随机密钥" in rec.message for rec in caplog.records)


def test_configured_secret_any_env_passes(monkeypatch):
    """显式配置 JWT_SECRET 后任意环境启动通过。"""
    for env in ("dev", "prod", "staging"):
        class _FakeSettings:
            ENV = env
            JWT_SECRET = "a-very-secure-secret-0123456789abcdef"

        monkeypatch.setattr("app.core.security.settings", _FakeSettings())
        assert_secure_jwt_secret()
"""Google OAuth 登录测试。

验证策略：不请求 Google（测试环境无网络），monkeypatch
``google.oauth2.id_token.verify_oauth2_token`` 直接返回伪造 payload，
覆盖 google_auth 服务的全部业务逻辑：新建用户 / sub 幂等 / 邮箱绑定 /
安全校验（email_verified / iss / 无效 token / 未配置 Client ID）。
"""
from __future__ import annotations

import pytest

from app.common.config import settings

_CLIENT_ID = "test-client.apps.googleusercontent.com"


def _make_payload(**overrides):
    payload = {
        "iss": "accounts.google.com",
        "sub": "google-sub-123",
        "email": "guser@example.com",
        "email_verified": True,
        "name": "Google User",
        "picture": "https://example.com/avatar.png",
        "aud": _CLIENT_ID,
    }
    payload.update(overrides)
    return payload


def _patch_google(monkeypatch, payload_factory):
    """把 verify_oauth2_token 替换为固定 payload；并设置测试 Client ID。"""
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", _CLIENT_ID, raising=False)
    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda token, req, audience, clock_skew_in_seconds=0: payload_factory(),
        raising=False,
    )


_FAKE_TOKEN = "fake-google-id-token-abcdefghijklmnopqrstuvwxyz"


async def test_google_login_creates_user(client, monkeypatch):
    """首次 Google 登录 → 创建用户并签发项目 JWT。"""
    _patch_google(monkeypatch, _make_payload)

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "guser@example.com"
    assert body["user"]["display_name"] == "Google User"

    # 签发的 JWT 能访问受保护接口
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "guser@example.com"


async def test_google_login_same_sub_idempotent(client, monkeypatch):
    """同一 Google 账号重复登录 → 复用同一用户（不重复建号）。"""
    _patch_google(monkeypatch, _make_payload)

    r1 = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    r2 = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["user"]["id"] == r2.json()["user"]["id"]

    # 库里只有一个该邮箱用户
    r3 = await client.post("/api/v1/auth/register", json={
        "email": "guser@example.com", "password": "test1234"},
    )
    assert r3.status_code == 400  # 已注册


async def test_google_login_binds_existing_email_user(client, monkeypatch):
    """已有邮箱密码账号 → Google 登录绑定到同一账号（google_sub 落库）。"""
    _patch_google(monkeypatch, _make_payload)

    reg = await client.post("/api/v1/auth/register", json={
        "email": "guser@example.com", "password": "test1234", "display_name": "老账号",
    })
    orig_id = reg.json()["user"]["id"]

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["id"] == orig_id  # 不是新账号


async def test_google_login_rejects_unverified_email(client, monkeypatch):
    """Google 邮箱未验证 → 拒绝（401）。"""
    _patch_google(monkeypatch, lambda: _make_payload(email_verified=False))

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "google_auth_failed"


async def test_google_login_rejects_bad_issuer(client, monkeypatch):
    """iss 不在 Google 白名单 → 拒绝。"""
    _patch_google(monkeypatch, lambda: _make_payload(iss="https://evil.example.com"))

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 401


async def test_google_login_rejects_missing_sub(client, monkeypatch):
    """payload 缺 sub → 拒绝。"""
    _patch_google(monkeypatch, lambda: {k: v for k, v in _make_payload().items() if k != "sub"})

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 401


async def test_google_login_rejects_invalid_token(client, monkeypatch):
    """verify_oauth2_token 抛异常（伪造/过期 token）→ 401。"""
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", _CLIENT_ID, raising=False)

    def _boom(*args, **kwargs):
        raise ValueError("Invalid token")

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", _boom, raising=False)

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "google_auth_failed"


async def test_google_login_missing_config(client, monkeypatch):
    """服务端未配置 GOOGLE_CLIENT_ID → 401 且提示配置。"""
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None, raising=False)
    monkeypatch.setattr(google_id_token, "verify_oauth2_token", lambda *a, **k: _make_payload(), raising=False)

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 401
    assert "GOOGLE_CLIENT_ID" in resp.json()["error"]["message"]


@pytest.mark.parametrize("bad_token", ["short", ""])
async def test_google_login_schema_validation(client, bad_token):
    """id_token 过短 → 422（schemas 层校验）。"""
    resp = await client.post("/api/v1/auth/google", json={"id_token": bad_token})
    assert resp.status_code == 422


async def test_google_login_passes_full_client_id_as_audience(client, monkeypatch):
    """audience 必须是完整 Client ID（回归：曾把 str 当 tuple 取 [0]，只传首字符）。"""
    from google.oauth2 import id_token as google_id_token

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", _CLIENT_ID, raising=False)
    captured: dict = {}

    def _spy(token, req, audience, clock_skew_in_seconds=0):
        captured["audience"] = audience
        return _make_payload()

    monkeypatch.setattr(google_id_token, "verify_oauth2_token", _spy, raising=False)

    resp = await client.post("/api/v1/auth/google", json={"id_token": _FAKE_TOKEN})
    assert resp.status_code == 200, resp.text
    # 完整 Client ID，而不是其首字符（如 "t"）
    assert captured.get("audience") == _CLIENT_ID
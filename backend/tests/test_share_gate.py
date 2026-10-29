"""分享链接访问密码锁 API 测试（task-share-gate-eval：可选密码锁）。

覆盖：
- owner 设置密码 → lifecycle 透出 has_password
- 未带密码访问分享端点 → 403 share_password_required
- 带 X-Share-Password → 200（只读）
- 密码错误 → 403
- POST /share/{token}/verify 验证 → 签发 gate_token → 带 X-Share-Gate 免验
- 清除密码（空串）→ 恢复免密访问
- 门禁覆盖分享全链路：journey / passport / live / comments
- edit 令牌独立密码（kind=edit）
"""
from __future__ import annotations

from datetime import date, timedelta


async def _make_shared_trip(client, headers) -> tuple[str, str]:
    """建行程 → 分享 → 返回 (trip_id, token)。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州锁之旅", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": (today + timedelta(days=1)).isoformat(),
        "travelers": 1, "budget": 1000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    return trip_id, resp.json()["share_token"]


# ── 设置 / 清除密码 ─────────────────────────────────────────────
async def test_set_password_and_require_it(client, auth_user):
    """owner 设置密码后：无密码访问 → 403 share_password_required；带密码 → 200。"""
    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)

    # 设置密码
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/password",
                             json={"kind": "share", "password": "s3cret"},
                             headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_password"] is True

    # 无密码 → 403
    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 403, resp.text
    assert "share_password_required" in resp.text

    # 带密码 → 200
    resp = await client.get(f"/api/v1/trips/share/{token}",
                            headers={"X-Share-Password": "s3cret"})
    assert resp.status_code == 200, resp.text

    # 错误密码 → 403
    resp = await client.get(f"/api/v1/trips/share/{token}",
                            headers={"X-Share-Password": "wrong"})
    assert resp.status_code == 403, resp.text


async def test_lifecycle_shows_has_password(client, auth_user):
    """lifecycle 端点透出 has_password（密码本身绝不出现）。"""
    _, headers = auth_user
    trip_id, _ = await _make_shared_trip(client, headers)

    await client.post(f"/api/v1/trips/{trip_id}/share/password",
                      json={"kind": "share", "password": "pw1234"},
                      headers=headers)
    resp = await client.get(f"/api/v1/trips/{trip_id}/share/lifecycle", headers=headers)
    assert resp.status_code == 200, resp.text
    share = next(i for i in resp.json() if i["kind"] == "share")
    assert share["has_password"] is True
    assert "pw1234" not in resp.text  # 明文绝不出现在响应


async def test_clear_password_restores_open(client, auth_user):
    """密码清空（空串）→ 恢复免密访问（幂等）。"""
    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)

    await client.post(f"/api/v1/trips/{trip_id}/share/password",
                      json={"kind": "share", "password": "pw1234"},
                      headers=headers)
    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 403

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/password",
                             json={"kind": "share", "password": ""},
                             headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_password"] is False

    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 200, resp.text


# ── 访客验证 + 免验凭证 ─────────────────────────────────────────
async def test_verify_issues_gate_token(client, auth_user):
    """verify 验证通过 → 签发 gate_token → X-Share-Gate 免验；错误密码 → 403。"""
    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)
    await client.post(f"/api/v1/trips/{trip_id}/share/password",
                      json={"kind": "share", "password": "pw1234"},
                      headers=headers)

    # 错误密码
    resp = await client.post(f"/api/v1/trips/share/{token}/verify",
                             json={"password": "nope"})
    assert resp.status_code == 403, resp.text

    # 正确密码 → gate_token
    resp = await client.post(f"/api/v1/trips/share/{token}/verify",
                             json={"password": "pw1234"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    gate = body["gate_token"]
    assert gate

    # 带 X-Share-Gate 免验访问
    resp = await client.get(f"/api/v1/trips/share/{token}",
                            headers={"X-Share-Gate": gate})
    assert resp.status_code == 200, resp.text


# ── 门禁覆盖分享全链路 ──────────────────────────────────────────
async def test_gate_covers_journey_and_passport(client, auth_user):
    """脱敏投影 / 护照等分享读端点同样受密码门禁。"""
    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)
    await client.post(f"/api/v1/trips/{trip_id}/share/password",
                      json={"kind": "share", "password": "pw1234"},
                      headers=headers)

    for path in (
        f"/api/v1/trips/share/{token}/journey",
        f"/api/v1/trips/share/{token}/passport",
        f"/api/v1/trips/share/{token}/live",
        f"/api/v1/trips/share/{token}/comments",
    ):
        resp = await client.get(path)
        assert resp.status_code == 403, f"{path} 应被门禁 (got {resp.status_code})"
        resp = await client.get(path, headers={"X-Share-Password": "pw1234"})
        assert resp.status_code == 200, f"{path} 带密码应放行 (got {resp.status_code})"


async def test_gate_covers_comments_write(client, auth_user):
    """评论写入同样受门禁（防绕过只读校验直接发评论）。"""
    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)
    await client.post(f"/api/v1/trips/{trip_id}/share/password",
                      json={"kind": "share", "password": "pw1234"},
                      headers=headers)

    resp = await client.post(f"/api/v1/trips/share/{token}/comments",
                             json={"content": "hi"})
    assert resp.status_code == 403, resp.text

    resp = await client.post(f"/api/v1/trips/share/{token}/comments",
                             json={"content": "hi"},
                             headers={"X-Share-Password": "pw1234"})
    assert resp.status_code == 201, resp.text


# ── edit 令牌独立密码 ───────────────────────────────────────────
async def test_edit_token_own_password(client, auth_user):
    """edit 令牌可单独设密码；share 未设锁不受影响。"""
    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
    assert resp.status_code == 200, resp.text
    edit_token = resp.json()["edit_token"]

    # 给 edit 设密码
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/password",
                             json={"kind": "edit", "password": "editpw"},
                             headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["has_password"] is True

    # edit 链接需密码；share 链接仍免密
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}")
    assert resp.status_code == 403, resp.text
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}",
                            headers={"X-Share-Password": "editpw"})
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 200, resp.text
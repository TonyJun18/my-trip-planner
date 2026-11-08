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


# ── edit 侧 verify（2026-11-08：补齐受邀编辑链接的解锁入口） ──────
async def test_edit_verify_issues_gate_token(client, auth_user):
    """edit 令牌密码：错误 → 403；正确 → gate_token，可凭它免验读取编辑链路。"""
    _, headers = auth_user
    trip_id, _ = await _make_shared_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
    assert resp.status_code == 200, resp.text
    edit_token = resp.json()["edit_token"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/password",
                             json={"kind": "edit", "password": "editpw"},
                             headers=headers)
    assert resp.status_code == 200, resp.text

    # 错误密码 → 403 share_password_required
    resp = await client.post(f"/api/v1/trips/edit/{edit_token}/verify",
                             json={"password": "nope"})
    assert resp.status_code == 403, resp.text
    assert "share_password_required" in resp.text

    # 正确密码 → 签发 gate_token
    resp = await client.post(f"/api/v1/trips/edit/{edit_token}/verify",
                             json={"password": "editpw"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["gate_token"]
    assert body["expires_in_seconds"] > 0

    # 带 X-Share-Gate 免验读取（编辑链路）→ 200
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}",
                            headers={"X-Share-Gate": body["gate_token"]})
    assert resp.status_code == 200, resp.text

    # 空密码同样被门禁拦下（不放过）
    resp = await client.post(f"/api/v1/trips/edit/{edit_token}/verify",
                             json={"password": ""})
    assert resp.status_code == 403, resp.text


# ── 审计写不得持锁（回归 2026-11-08 事故） ────────────────────────
async def test_usage_audit_does_not_hold_row_lock(client, auth_user, db_session, test_engine):
    """`last_used_at` 审计写必须独立提交，不能在调用方事务里持 share_tokens 行锁。

    事故现场：WS 端点为整条连接持有请求 session，`touch_token_usage` 只 flush 不提交，
    UPDATE 的行锁常驻 → 同令牌的 `/verify` 与所有鉴权读永久排队（curl 无响应）。
    断言两点：① 鉴权读之后，别的连接能 NOWAIT 立刻拿到行锁；② 审计值确实落库。
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services import collab_service

    _, headers = auth_user
    trip_id, token = await _make_shared_trip(client, headers)
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/password",
                             json={"kind": "share", "password": "s3cret"},
                             headers=headers)
    assert resp.status_code == 200, resp.text

    # 调用方 session 做一次完整鉴权读取（内部会 touch last_used_at）
    trip = await collab_service._get_trip_by_token(db_session, token, password="s3cret")
    assert trip.id == trip_id

    # ① 另一个连接应能立刻拿到行锁（NOWAIT = 不等锁，拿不到会直接报错）
    async with AsyncSession(bind=test_engine) as probe:
        row = (await probe.execute(
            text("select id from share_tokens where token = :t for update nowait"),
            {"t": token},
        )).first()
        assert row is not None, "share_tokens 记录应存在"
        await probe.rollback()

    # ② 审计值已由独立事务提交（不是留在内存里 pending）
    async with AsyncSession(bind=test_engine) as probe2:
        used = (await probe2.execute(
            text("select last_used_at from share_tokens where token = :t"),
            {"t": token},
        )).scalar_one()
        assert used is not None, "last_used_at 应已落库"
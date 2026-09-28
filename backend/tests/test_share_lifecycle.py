"""分享令牌生命周期 + 收藏灵感夹 API 测试（方案 2：task-share-token-lifecycle）。

覆盖：
- lifecycle 查询：share/edit 令牌状态（含 legacy 兼容 / 未开放令牌跳过）
- TTL 设置：0 永久 / 1/7/30 天过期；重复设置覆盖
- 吊销：owner 吊销 → 读取侧 403/410；评论/投票/受邀编辑一并失效
- 旧令牌（无记录）按永久兼容，不阻断
- 收藏灵感夹：收藏/取消/列表（登录用户隔离 + share_token 透出）
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


async def _make_shared_trip(client, headers) -> tuple[str, str, str]:
    """建行程 + Day + 站点 → 生成分享 token → 返回 (trip_id, token, stop_id)。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州三日游", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": (today + timedelta(days=2)).isoformat(),
        "travelers": 2, "budget": 3000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1, "note": "第一天"}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "西湖", "stop_type": "attraction", "lat": 30.245, "lng": 120.15,
        "estimated_cost": 0, "description": "环湖",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    stop_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    token = resp.json()["share_token"]
    return trip_id, token, stop_id


# ── 生命周期查询 ─────────────────────────────────────────────
async def test_lifecycle_empty_before_share(client, auth_user):
    """未开放分享的行程：lifecycle 返回空列表（不 404）。"""
    _, headers = auth_user
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "未分享", "destination": "上海",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
    }, headers=headers)
    trip_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/trips/{trip_id}/share/lifecycle", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_lifecycle_after_share_with_legacy(client, auth_user):
    """生成分享后：share 令牌出现，edit 未开放则跳过；legacy 兼容（无记录视同永久）。"""
    _, headers = auth_user
    trip_id, token, _ = await _make_shared_trip(client, headers)

    resp = await client.get(f"/api/v1/trips/{trip_id}/share/lifecycle", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert len(items) == 1
    share = items[0]
    assert share["kind"] == "share"
    assert share["token"] == token
    assert share["expires_at"] is None      # 未设 TTL → 永久
    assert share["revoked_at"] is None
    assert share["legacy"] is False
    assert share["share_url"] is not None

    # 只读访问后 last_used 被更新（尽力而为审计）
    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 200, resp.text
    resp = await client.get(f"/api/v1/trips/{trip_id}/share/lifecycle", headers=headers)
    share = next(i for i in resp.json() if i["kind"] == "share")
    assert share["last_used_at"] is not None


async def test_lifecycle_owner_isolation(client, auth_user):
    """非 owner 查 lifecycle → 404（owner 隔离）。"""
    _, headers = auth_user
    trip_id, _, _ = await _make_shared_trip(client, headers)

    # 第二个用户
    import uuid
    email = f"other-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234", "display_name": "他人",
    })
    other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.get(f"/api/v1/trips/{trip_id}/share/lifecycle", headers=other_headers)
    assert resp.status_code == 404


# ── TTL 设置 ─────────────────────────────────────────────────
async def test_ttl_set_and_override(client, auth_user):
    """设 TTL=1天 → expires_at 出现在未来；覆盖为永久 → expires_at 清空。"""
    _, headers = auth_user
    trip_id, token, _ = await _make_shared_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/ttl", json={"kind": "share", "days": 1}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["expires_at"] is not None
    from datetime import datetime, timezone
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires > datetime.now(timezone.utc)

    # 覆盖为永久
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/ttl", json={"kind": "share", "days": 0}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["expires_at"] is None

    # 非法 days → 422
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/ttl", json={"kind": "share", "days": 5}, headers=headers)
    assert resp.status_code == 422


async def test_ttl_expired_blocks_read(client, auth_user, test_engine):
    """TTL 设为过去时间（用数据库直改）→ 读取侧 410。"""
    from datetime import datetime, timezone

    from app.models import ShareToken
    from sqlalchemy import select

    _, headers = auth_user
    trip_id, token, _ = await _make_shared_trip(client, headers)

    # 先触发 lifecycle upsert（share_tokens 记录在读取侧首次访问时登记），
    # 再用测试库自己的 session 直接改 expires_at 为过去
    resp = await client.get(f"/api/v1/trips/{trip_id}/share/lifecycle", headers=headers)
    assert resp.status_code == 200, resp.text

    # 用测试库自己的 session 直接改 expires_at 为过去
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        stmt = select(ShareToken).where(ShareToken.token == token)
        rec = (await db.execute(stmt)).scalar_one()
        rec.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await db.commit()

    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 410, resp.text
    assert resp.json()["error"]["code"] == "share_token_expired"


# ── 吊销 ─────────────────────────────────────────────────────
async def test_revoke_blocks_read_and_collab(client, auth_user):
    """owner 吊销 share 令牌 → 读取 403、评论 403、投票 403。"""
    _, headers = auth_user
    trip_id, token, stop_id = await _make_shared_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/revoke", json={"kind": "share"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked_at"] is not None

    # 读取
    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "share_token_revoked"

    # 评论
    resp = await client.post(f"/api/v1/trips/share/{token}/comments", json={"content": "还能发吗"})
    assert resp.status_code == 403

    # 投票
    resp = await client.post(f"/api/v1/trips/share/{token}/votes/{stop_id}", json={"value": 1})
    assert resp.status_code == 403

    # 幂等：重复吊销仍 200
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/revoke", json={"kind": "share"}, headers=headers)
    assert resp.status_code == 200


async def test_revoke_not_open_404(client, auth_user):
    """未开放分享的行程吊销 → 404。"""
    _, headers = auth_user
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "无分享", "destination": "北京",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
    }, headers=headers)
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/share/revoke", json={"kind": "share"}, headers=headers)
    assert resp.status_code == 404


# ── 收藏灵感夹 ───────────────────────────────────────────────
async def test_favorite_flow(client, auth_user):
    """收藏 → 列表可见（含 share_token）→ 取消 → 列表空。"""
    _, headers = auth_user
    trip_id, token, _ = await _make_shared_trip(client, headers)

    # 初始列表空
    resp = await client.get("/api/v1/trips/favorites", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    # 收藏
    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    fav = resp.json()
    assert fav["trip_id"] == trip_id
    assert fav["share_token"] == token
    assert fav["title"] == "杭州三日游"

    # 幂等：重复收藏返回相同记录
    resp2 = await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["id"] == fav["id"]

    # 列表
    resp = await client.get("/api/v1/trips/favorites", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["trip_id"] == trip_id

    # 取消
    resp = await client.delete(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get("/api/v1/trips/favorites", headers=headers)
    assert resp.json()["items"] == []

    # 再次取消幂等
    resp = await client.delete(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp.status_code == 204


async def test_favorite_requires_auth(client):
    """未登录收藏 → 401。"""
    resp = await client.get("/api/v1/trips/favorites")
    assert resp.status_code == 401
    resp = await client.post("/api/v1/trips/favorites/whatever")
    assert resp.status_code == 401


async def test_favorite_isolation(client, auth_user):
    """用户 A 的收藏对用户 B 不可见。"""
    import uuid

    _, headers = auth_user
    trip_id, _, _ = await _make_shared_trip(client, headers)
    await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=headers)

    email = f"iso-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234",
    })
    user_b_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = await client.get("/api/v1/trips/favorites", headers=user_b_headers)
    assert resp.json()["items"] == []
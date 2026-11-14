"""画廊点赞 + staff 精选测试（ADR-0001 内容发现层）。

覆盖：
- like/unlike 幂等、owner 不可自赞（403）
- 未登录 like 401
- 画廊列表返回 like_count
- staff feature：非 staff 403、staff 可精选任意公开行程（自动建 share_token）
- is_staff 同步：STAFF_USER_IDS 白名单登录后为 staff
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.common.config import settings


async def _make_trip(client: AsyncClient, headers: dict, title: str = "画廊点赞行程") -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州",
        "start_date": "2026-12-01", "end_date": "2026-12-02",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _publish(client: AsyncClient, headers: dict, trip_id: str) -> None:
    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/publish",
                             headers=headers, json={"blurb": "点赞测试行程"})
    assert resp.status_code == 200, resp.text


async def _register(client: AsyncClient, prefix: str = "user") -> tuple[dict, dict]:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post("/api/v1/auth/register",
                             json={"email": email, "password": "test1234", "display_name": prefix})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return data["user"], {"Authorization": f"Bearer {data['access_token']}"}


# ── like / unlike 幂等 ──
@pytest.mark.asyncio
async def test_like_unlike_idempotent(client: AsyncClient, auth_user):
    owner, owner_headers = auth_user
    trip_id = await _make_trip(client, owner_headers, "点赞目标")
    await _publish(client, owner_headers, trip_id)

    _, liker_headers = await _register(client, "liker")
    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/like", headers=liker_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["liked"] is True
    assert body["like_count"] == 1

    # 重复点赞幂等：不新增
    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/like", headers=liker_headers)
    assert resp.status_code == 200
    assert resp.json()["like_count"] == 1

    # 画廊列表返回 like_count（登录态附带 liked）
    resp = await client.get("/api/v1/trips/gallery", headers=liker_headers)
    assert resp.status_code == 200
    mine = next(i for i in resp.json()["items"] if i["trip_id"] == trip_id)
    assert mine["like_count"] == 1
    assert mine["liked"] is True

    # 未登录视图不带 liked（或 false）
    resp = await client.get("/api/v1/trips/gallery")
    mine = next(i for i in resp.json()["items"] if i["trip_id"] == trip_id)
    assert mine["like_count"] == 1
    assert mine.get("liked") is False

    # unlike 幂等
    resp = await client.delete(f"/api/v1/trips/gallery/{trip_id}/like", headers=liker_headers)
    assert resp.status_code == 200
    assert resp.json()["liked"] is False
    assert resp.json()["like_count"] == 0
    resp = await client.delete(f"/api/v1/trips/gallery/{trip_id}/like", headers=liker_headers)
    assert resp.status_code == 200
    assert resp.json()["like_count"] == 0


# ── owner 不可自赞（403）──
@pytest.mark.asyncio
async def test_owner_cannot_like_own(client: AsyncClient, auth_user):
    owner, owner_headers = auth_user
    trip_id = await _make_trip(client, owner_headers, "自赞目标")
    await _publish(client, owner_headers, trip_id)

    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/like", headers=owner_headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "permission_denied"


# ── 未登录不能点赞（401）──
@pytest.mark.asyncio
async def test_like_requires_login(client: AsyncClient, auth_user):
    owner, owner_headers = auth_user
    trip_id = await _make_trip(client, owner_headers)
    await _publish(client, owner_headers, trip_id)

    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/like")
    assert resp.status_code == 401, resp.text


# ── 点赞目标必须已发布到画廊（404）──
@pytest.mark.asyncio
async def test_like_unpublished_trip_404(client: AsyncClient, auth_user):
    owner, owner_headers = auth_user
    trip_id = await _make_trip(client, owner_headers, "未发布行程")

    _, liker_headers = await _register(client, "liker2")
    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/like", headers=liker_headers)
    assert resp.status_code == 404, resp.text


# ── staff feature：非 staff 403 ──
@pytest.mark.asyncio
async def test_feature_requires_staff(client: AsyncClient, auth_user):
    owner, owner_headers = auth_user
    trip_id = await _make_trip(client, owner_headers, "待精选行程")

    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/feature", headers=owner_headers,
                             json={"blurb": "假装运营"})
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "permission_denied"


# ── staff feature：可精选任意公开行程（未发布也自动建 share_token + featured）──
@pytest.mark.asyncio
async def test_staff_feature_any_public_trip(client: AsyncClient, auth_user, monkeypatch):
    # 把一个用户设为 staff（env 白名单模拟）
    owner, owner_headers = auth_user
    monkeypatch.setattr(settings, "STAFF_USER_IDS", owner["id"])

    # 重新登录拿到 is_staff 同步结果（模拟登录路径）
    email = owner["email"]
    resp = await client.post("/api/v1/auth/login",
                             json={"account": email, "password": "test1234"})
    assert resp.status_code == 200, resp.text
    staff_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    assert resp.json()["user"]["is_staff"] is True

    trip_id = await _make_trip(client, owner_headers, "staff 精选目标（未分享）")
    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/feature", headers=staff_headers,
                             json={"blurb": "运营精选"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_featured"] is True
    assert body["share_token"]

    # 公开画廊可见
    resp = await client.get("/api/v1/trips/gallery")
    items = [i for i in resp.json()["items"] if i["trip_id"] == trip_id]
    assert len(items) == 1

    # 幂等：重复 feature 只更新 blurb
    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/feature", headers=staff_headers,
                             json={"blurb": "运营精选 v2"})
    assert resp.status_code == 200
    assert resp.json()["blurb"] == "运营精选 v2"


# ── staff 白名单登录同步 is_staff ──
@pytest.mark.asyncio
async def test_staff_whitelist_synced_on_login(client: AsyncClient, monkeypatch):
    _user, _headers = await _register(client, "staffer")
    # 初始不是 staff
    assert _user["is_staff"] is False

    # 加入白名单后登录 → is_staff=True
    monkeypatch.setattr(settings, "STAFF_USER_IDS", _user["id"])
    resp = await client.post("/api/v1/auth/login",
                             json={"account": _user["email"], "password": "test1234"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["is_staff"] is True

    # 移出白名单后登录 → is_staff=False
    monkeypatch.setattr(settings, "STAFF_USER_IDS", "")
    resp = await client.post("/api/v1/auth/login",
                             json={"account": _user["email"], "password": "test1234"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["is_staff"] is False
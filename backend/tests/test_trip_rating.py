"""行程评分 / 信任信号测试（task-trip-rating-signal）。

覆盖：
- 提交/更新/删除评分（幂等、1-5 越界 422、未登录 401）
- 「我去过」标记翻转
- 单行程详情（聚合 + 我的评分；未登录 user_rating=None）
- 批量聚合 summary（多行程、无评分行程 count=0 avg=None）
- 画廊列表透出评分热度（rating_count / rating_avg / visited_count）
- 可见性语义与收藏一致（存在即可评，不校验 owner）；不存在的行程 404
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_trip(client: AsyncClient, headers: dict, title: str = "评分行程") -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州",
        "start_date": "2026-11-01", "end_date": "2026-11-02",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 提交 / 更新 / 删除 ───────────────────────────────
@pytest.mark.asyncio
async def test_submit_and_update_rating(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    # 首次评分 4 星
    resp = await client.post(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                             json={"rating": 4, "visited": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 4
    assert body["visited"] is True

    # 改分 5 星（幂等 upsert，仍一条）
    resp = await client.put(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                            json={"rating": 5, "visited": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rating"] == 5

    # 翻转 visited
    resp = await client.put(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                            json={"rating": 5, "visited": False})
    assert resp.json()["visited"] is False


@pytest.mark.asyncio
async def test_rating_validation_and_auth(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    # 越界评分 → 422
    resp = await client.post(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                             json={"rating": 6})
    assert resp.status_code == 422

    # 未登录 → 401
    resp = await client.post(f"/api/v1/trips/{trip_id}/rating", json={"rating": 3})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_rating_idempotent(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                             json={"rating": 2})
    assert resp.status_code == 201

    resp = await client.delete(f"/api/v1/trips/{trip_id}/rating", headers=headers)
    assert resp.status_code == 204

    # 再次删除 → no-op 204
    resp = await client.delete(f"/api/v1/trips/{trip_id}/rating", headers=headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_rating_404_unknown_trip(client: AsyncClient, auth_user):
    _user, headers = auth_user
    resp = await client.post("/api/v1/trips/no-such-trip/rating", headers=headers,
                             json={"rating": 3})
    assert resp.status_code == 404


# ── 详情 / 聚合 ─────────────────────────────────────
@pytest.mark.asyncio
async def test_get_rating_detail(client: AsyncClient, auth_user):
    user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    # 未评分：聚合 0、user_rating None
    resp = await client.get(f"/api/v1/trips/{trip_id}/rating")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["avg"] is None
    assert body["user_rating"] is None
    assert body["user_visited"] is False

    # 评分后：聚合 1、我的评分可见
    await client.post(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                      json={"rating": 5, "visited": True})
    resp = await client.get(f"/api/v1/trips/{trip_id}/rating", headers=headers)
    body = resp.json()
    assert body["count"] == 1
    assert body["avg"] == 5.0
    assert body["visited_count"] == 1
    assert body["user_rating"] == 5
    assert body["user_visited"] is True


@pytest.mark.asyncio
async def test_rating_summary_batch(client: AsyncClient, auth_user):
    user_a, headers_a = auth_user
    # 第二个用户
    resp = await client.post("/api/v1/auth/register", json={
        "email": "rater_b@test.com", "password": "pass12345",
    })
    assert resp.status_code in (200, 201), resp.text
    headers_b = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    t1 = await _make_trip(client, headers_a, "杭州两日")
    t2 = await _make_trip(client, headers_a, "上海两日")

    await client.post(f"/api/v1/trips/{t1}/rating", headers=headers_a, json={"rating": 4})
    await client.post(f"/api/v1/trips/{t1}/rating", headers=headers_b, json={"rating": 5, "visited": True})

    resp = await client.get(f"/api/v1/trips/ratings/summary?trip_ids={t1},{t2}")
    assert resp.status_code == 200
    items = {i["trip_id"]: i for i in resp.json()["items"]}
    assert items[t1]["count"] == 2
    assert items[t1]["avg"] == 4.5
    assert items[t1]["visited_count"] == 1
    # 无评分行程：count=0, avg=None
    assert items[t2]["count"] == 0
    assert items[t2]["avg"] is None


# ── 画廊透出 ────────────────────────────────────────
@pytest.mark.asyncio
async def test_gallery_ratings_exposure(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    # 发布到画廊
    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/publish",
                             headers=headers, json={"blurb": "西湖半日"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["share_token"]

    # 未评分时画廊卡片为 0 / None
    resp = await client.get("/api/v1/trips/gallery")
    card = next(i for i in resp.json()["items"] if i["trip_id"] == trip_id)
    assert card["rating_count"] == 0
    assert card["rating_avg"] is None
    assert card["visited_count"] == 0

    # 评分后画廊卡片透出热度
    await client.post(f"/api/v1/trips/{trip_id}/rating", headers=headers,
                      json={"rating": 5, "visited": True})
    resp = await client.get("/api/v1/trips/gallery")
    card = next(i for i in resp.json()["items"] if i["trip_id"] == trip_id)
    assert card["rating_count"] == 1
    assert card["rating_avg"] == 5.0
    assert card["visited_count"] == 1


# ── 可见性语义（与收藏一致：存在即可评） ───────────────
@pytest.mark.asyncio
async def test_rating_visibility_semantics(client: AsyncClient, auth_user):
    user_a, headers_a = auth_user
    resp = await client.post("/api/v1/auth/register", json={
        "email": "rater_c@test.com", "password": "pass12345",
    })
    headers_c = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # A 建一个未发布、未分享的私有行程
    trip_id = await _make_trip(client, headers_a, "私有行程")

    # C 也能评分（与收藏同语义：存在即可评，不校验分享/发布状态）
    resp = await client.post(f"/api/v1/trips/{trip_id}/rating", headers=headers_c,
                             json={"rating": 3})
    assert resp.status_code == 201, resp.text
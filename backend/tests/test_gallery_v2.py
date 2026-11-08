"""灵感画廊 v2：分页总数 / 排序 / 目的地筛选 / 我的发布（task-gallery-v2）。

覆盖 2026-11-06 新增能力：
- ``GET /trips/gallery`` 返回真实 ``total``（此前是 ``len(items)``）+ ``limit/offset``
- ``sort=new|hot``：hot 按评分热度（人数 → 均分 → 更新时间）排序
- ``destination=``：目的地模糊筛选
- ``mine=1``：只列当前登录用户的发布（未登录 401）
- 分享详情载荷暴露 ``is_featured`` / ``gallery_blurb``（详情页 CTA 依据）
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_trip(
    client: AsyncClient, headers: dict, title: str = "画廊行程", destination: str = "杭州",
) -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": destination,
        "start_date": "2026-11-01", "end_date": "2026-11-02",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _publish(client: AsyncClient, headers: dict, trip_id: str, blurb: str = "") -> dict:
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/gallery/publish", headers=headers, json={"blurb": blurb},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _register(client: AsyncClient, email: str) -> dict:
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234", "display_name": email.split("@")[0],
    })
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── 分页：total 是过滤后的真实总数，不是当前页长度 ──
@pytest.mark.asyncio
async def test_gallery_total_and_pagination(client: AsyncClient, auth_user):
    _user, headers = auth_user
    ids = []
    for i in range(3):
        trip_id = await _make_trip(client, headers, f"分页行程{i}", destination="分页城")
        await _publish(client, headers, trip_id, f"卖点{i}")
        ids.append(trip_id)

    resp = await client.get("/api/v1/trips/gallery", params={"destination": "分页城", "limit": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert body["limit"] == 1 and body["offset"] == 0

    page2 = (await client.get(
        "/api/v1/trips/gallery", params={"destination": "分页城", "limit": 1, "offset": 1},
    )).json()
    assert page2["total"] == 3
    assert page2["items"][0]["trip_id"] != body["items"][0]["trip_id"]


# ── 目的地筛选（模糊匹配；不匹配则空）──
@pytest.mark.asyncio
async def test_gallery_destination_filter(client: AsyncClient, auth_user):
    _user, headers = auth_user
    hangzhou = await _make_trip(client, headers, "杭州行程", destination="杭州")
    await _publish(client, headers, hangzhou, "西湖")

    resp = await client.get("/api/v1/trips/gallery", params={"destination": "杭州"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and all("杭州" in i["destination"] for i in items)

    resp = await client.get(
        "/api/v1/trips/gallery", params={"destination": "不存在的城市zzz"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0


# ── 热度排序：被评分的那条排前面 ──
@pytest.mark.asyncio
async def test_gallery_sort_hot(client: AsyncClient, auth_user):
    _user, headers = auth_user
    cold = await _make_trip(client, headers, "没人评的行程", destination="热度城")
    hot = await _make_trip(client, headers, "有人评的行程", destination="热度城")
    await _publish(client, headers, cold, "冷门")
    await _publish(client, headers, hot, "热门")

    resp = await client.post(
        f"/api/v1/trips/{hot}/rating", headers=headers, json={"rating": 5, "visited": True},
    )
    assert resp.status_code == 201, resp.text

    body = (await client.get(
        "/api/v1/trips/gallery", params={"destination": "热度城", "sort": "hot"},
    )).json()
    ids = [i["trip_id"] for i in body["items"]]
    assert ids[0] == hot
    assert body["items"][0]["rating_count"] == 1
    assert body["items"][0]["rating_avg"] == 5
    assert body["items"][0]["visited_count"] == 1

    # new 排序仍按更新时间：两条都在，顺序不影响断言
    body_new = (await client.get(
        "/api/v1/trips/gallery", params={"destination": "热度城", "sort": "new"},
    )).json()
    assert {i["trip_id"] for i in body_new["items"]} == {cold, hot}


# ── 我的发布：未登录 401 / 只返回自己的 ──
@pytest.mark.asyncio
async def test_gallery_mine_requires_login(client: AsyncClient):
    resp = await client.get("/api/v1/trips/gallery", params={"mine": 1})
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_gallery_mine_lists_only_own(client: AsyncClient, auth_user):
    _user, headers = auth_user
    mine = await _make_trip(client, headers, "我的发布", destination="我的城")
    await _publish(client, headers, mine, "我的卖点")

    other_headers = await _register(client, "gallery-mine-other@test.com")
    other = await _make_trip(client, other_headers, "别人的发布", destination="我的城")
    await _publish(client, other_headers, other, "别人的卖点")

    body = (await client.get(
        "/api/v1/trips/gallery", params={"mine": 1, "destination": "我的城"}, headers=headers,
    )).json()
    ids = [i["trip_id"] for i in body["items"]]
    assert mine in ids
    assert other not in ids
    assert body["total"] == 1

    # 撤回后「我的发布」里消失（管理闭环）
    resp = await client.delete(f"/api/v1/trips/{mine}/gallery/publish", headers=headers)
    assert resp.status_code == 204
    body = (await client.get(
        "/api/v1/trips/gallery", params={"mine": 1, "destination": "我的城"}, headers=headers,
    )).json()
    assert body["items"] == []
    assert body["total"] == 0


# ── 分享详情载荷暴露画廊状态（详情页「以此为蓝本创建」CTA 依据）──
@pytest.mark.asyncio
async def test_share_payload_exposes_gallery_state(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "详情页行程")
    published = await _publish(client, headers, trip_id, "一句卖点")

    resp = await client.get(f"/api/v1/trips/share/{published['share_token']}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_featured"] is True
    assert body["gallery_blurb"] == "一句卖点"

    # 撤回后详情页不再标记为画廊来源
    resp = await client.delete(f"/api/v1/trips/{trip_id}/gallery/publish", headers=headers)
    assert resp.status_code == 204
    body = (await client.get(f"/api/v1/trips/share/{published['share_token']}")).json()
    assert body["is_featured"] is False

"""灵感画廊 + 城市模板测试（task-gallery-featured + city-gallery-city-templates）。"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_trip(client: AsyncClient, headers: dict, title: str = "画廊行程") -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州",
        "start_date": "2026-11-01", "end_date": "2026-11-02",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_day_and_stop(client: AsyncClient, headers: dict, trip_id: str) -> str:
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers,
                             json={"day_number": 1, "note": "西湖日"})
    assert resp.status_code in (200, 201), resp.text
    day_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", headers=headers,
                             json={"name": "西湖", "type": "attraction",
                                   "estimated_cost": 0, "duration_minutes": 120})
    assert resp.status_code in (200, 201), resp.text
    return day_id


# ── 城市模板：23 目的地知识库规则生成 ──
@pytest.mark.asyncio
async def test_city_templates_public(client: AsyncClient):
    resp = await client.get("/api/v1/trips/gallery/templates?limit=23")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 20
    first = body["items"][0]
    assert {"destination", "days", "budget_tier", "title", "basis"} <= set(first)
    assert first["basis"] == "rule_based"


# ── 画廊：发布 → 公开列表可见 → 撤回 ──
@pytest.mark.asyncio
async def test_publish_list_unpublish(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "西湖骑行两日")

    # 发布（带卖点）→ 自动创建 share_token
    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/publish",
                             headers=headers, json={"blurb": "环湖骑行 + 灵隐半日"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["blurb"] == "环湖骑行 + 灵隐半日"
    assert body["share_token"]

    # 公开列表（免登录）可见
    resp = await client.get("/api/v1/trips/gallery")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(i["trip_id"] == trip_id for i in items)
    mine = next(i for i in items if i["trip_id"] == trip_id)
    assert mine["source"] == "user"
    assert mine["share_token"]

    # 撤回 → 列表不再出现
    resp = await client.delete(f"/api/v1/trips/{trip_id}/gallery/publish", headers=headers)
    assert resp.status_code == 204
    resp = await client.get("/api/v1/trips/gallery")
    assert all(i["trip_id"] != trip_id for i in resp.json()["items"])


# ── 一键复制创建：日程/站点复制，令牌/精选不复制 ──
@pytest.mark.asyncio
async def test_clone_gallery_trip(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "模板行程")
    await _add_day_and_stop(client, headers, trip_id)
    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/publish",
                             headers=headers, json={"blurb": "经典路线"})
    assert resp.status_code == 200, resp.text

    # 另一个用户复制
    other = await client.post("/api/v1/auth/register", json={
        "email": "clone-user@test.com", "password": "test1234", "display_name": "复制者",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/clone", headers=other_headers)
    assert resp.status_code == 201, resp.text
    cloned = resp.json()
    assert cloned["id"] != trip_id
    assert cloned["title"].endswith("（副本）")
    assert cloned.get("share_token") in (None, "")  # 不复制令牌

    # 副本带日程与站点
    resp = await client.get(f"/api/v1/trips/{cloned['id']}", headers=other_headers)
    assert resp.status_code == 200
    days = resp.json()["days"]
    assert len(days) == 1
    assert len(days[0]["stops"]) == 1
    assert days[0]["stops"][0]["name"] == "西湖"


# ── 未发布他人行程不可复制（404，防越权）──
@pytest.mark.asyncio
async def test_clone_private_trip_forbidden(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "私有行程")

    other = await client.post("/api/v1/auth/register", json={
        "email": "pry-user@test.com", "password": "test1234", "display_name": "路人",
    })
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.post(f"/api/v1/trips/gallery/{trip_id}/clone", headers=other_headers)
    assert resp.status_code == 404


# ── 发布需要 owner（他人不可发布）──
@pytest.mark.asyncio
async def test_publish_requires_owner(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, "受保护行程")

    other = await client.post("/api/v1/auth/register", json={
        "email": "hack-user@test.com", "password": "test1234", "display_name": "他人",
    })
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.post(f"/api/v1/trips/{trip_id}/gallery/publish", headers=other_headers,
                             json={"blurb": "抢发"})
    assert resp.status_code == 404
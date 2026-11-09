"""收藏 → 一键成路线测试（task-favorites-to-route）。

覆盖：
- 聚合端点：站点候选聚合 + 按名去重 + 来源行程标题 + 空收藏
- 成路线端点：复制为我的草稿（days/stops 全量、token/协作不复制）、
  未收藏 404（防枚举）、来源隔离（A 收藏的行程 B 不能成路线）、鉴权
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _register_user(client: AsyncClient, email: str) -> dict:
    """注册一个用户，返回 {user, headers}。"""
    resp = await client.post("/api/v1/auth/register", json={
        "email": email, "password": "test1234", "display_name": "测试用户",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"user": data["user"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}


async def _make_owner_trip(client: AsyncClient, headers: dict, title: str = "收藏源行程") -> tuple[str, str]:
    """建行程 + Day + 两个站点 → 生成分享 token → 返回 (trip_id, stop_id)。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": title, "destination": "杭州",
        "start_date": today.isoformat(), "end_date": (today + timedelta(days=1)).isoformat(),
        "travelers": 1, "budget": 2000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1, "note": "第一天"}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    stop_ids = []
    for name, stype in (("西湖", "attraction"), ("楼外楼", "food")):
        resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": stype, "lat": 30.245, "lng": 120.15,
            "estimated_cost": 0, "description": f"{name}描述",
        }, headers=headers)
        assert resp.status_code == 201, resp.text
        stop_ids.append(resp.json()["id"])

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    return trip_id, stop_ids[0]


# ── 聚合端点 ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_aggregate_empty(client: AsyncClient, auth_user):
    """空收藏 → items=[] / total=0 / trips=0（不报错）。"""
    _, headers = auth_user
    resp = await client.get("/api/v1/trips/favorites/stops", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["trips"] == 0


@pytest.mark.asyncio
async def test_aggregate_dedup_and_source(client: AsyncClient, auth_user):
    """聚合：站点按名去重，来源行程标题聚合，参与行程数正确。"""
    u1, h1 = auth_user
    h2 = (await _register_user(client, f"second-{uuid.uuid4().hex[:8]}@test.com"))["headers"]

    # A 建两条行程（站点含同名「西湖」）
    trip1, _ = await _make_owner_trip(client, h1, "杭州经典")
    trip2, _ = await _make_owner_trip(client, h1, "西湖深度")
    # B 建一条行程（不同目的地，验证来源隔离）
    trip3, _ = await _make_owner_trip(client, h2, "B的行程")

    for tid in (trip1, trip2, trip3):
        resp = await client.post(f"/api/v1/trips/favorites/{tid}", headers=h1)
        assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/trips/favorites/stops", headers=h1)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 3 条收藏行程参与聚合（含 B 的，因为 A 收藏了 B 的行程）
    assert body["trips"] == 3
    # 「西湖」只出现一次（三条行程都有同名站点，按名去重），来源聚合 3 条行程
    names = {item["name"]: item for item in body["items"]}
    assert "西湖" in names
    assert set(names["西湖"]["source_trips"]) == {"杭州经典", "西湖深度", "B的行程"}
    assert "楼外楼" in names
    assert set(names["楼外楼"]["source_trips"]) == {"杭州经典", "西湖深度", "B的行程"}


@pytest.mark.asyncio
async def test_aggregate_limit(client: AsyncClient, auth_user):
    """聚合 limit 生效：total 为全量去重数，items 截断到 limit。"""
    _, headers = auth_user
    trip_id, _ = await _make_owner_trip(client, headers, "多站点")
    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp.status_code == 200

    resp = await client.get("/api/v1/trips/favorites/stops?limit=1", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["total"] == 2  # 西湖 + 楼外楼（不去重也 2 个）


@pytest.mark.asyncio
async def test_aggregate_requires_auth(client: AsyncClient):
    """未登录聚合 → 401。"""
    resp = await client.get("/api/v1/trips/favorites/stops")
    assert resp.status_code == 401


# ── 一键成路线 ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_route_from_favorite(client: AsyncClient, auth_user):
    """成路线：复制为我的草稿（days/stops 全量、token/标记不复制）。"""
    _, headers = auth_user
    trip_id, stop_id = await _make_owner_trip(client, headers, "杭州经典")
    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp.status_code == 200

    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}/route", headers=headers)
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    assert copy["title"] == "杭州经典（收藏路线）"
    assert copy["status"] == "draft"
    assert copy["destination"] == "杭州"
    assert copy["id"] != trip_id  # 新行程
    assert copy["share_token"] is None  # 不复制令牌

    # 站点复制（两天各 2 站 → 2 站；这里 1 天 2 站）
    assert len(copy["days"]) == 1
    stops = copy["days"][0]["stops"]
    assert [s["name"] for s in stops] == ["西湖", "楼外楼"]
    assert stops[0]["description"] == "西湖描述"
    assert stops[0]["checked"] is False  # checked 重置


@pytest.mark.asyncio
async def test_create_route_not_favorited_404(client: AsyncClient, auth_user):
    """未收藏他人行程 → 404（防枚举，不泄露存在性）。"""
    u1, h1 = auth_user
    h2 = (await _register_user(client, f"second-{uuid.uuid4().hex[:8]}@test.com"))["headers"]
    trip_id, _ = await _make_owner_trip(client, h2, "别人的行程")

    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}/route", headers=h1)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "trip_not_found"


@pytest.mark.asyncio
async def test_create_route_isolation(client: AsyncClient, auth_user):
    """来源隔离：A 收藏的行程，B 不能成路线（B 未收藏）→ 404。"""
    u1, h1 = auth_user
    h2 = (await _register_user(client, f"second-{uuid.uuid4().hex[:8]}@test.com"))["headers"]
    trip_id, _ = await _make_owner_trip(client, h1, "A的收藏源")
    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=h1)
    assert resp.status_code == 200

    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}/route", headers=h2)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_route_requires_auth(client: AsyncClient):
    """未登录成路线 → 401。"""
    resp = await client.post("/api/v1/trips/favorites/whatever/route")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_route_copy_keeps_owner_trip_untouched(client: AsyncClient, auth_user):
    """成路线后原行程不变（源行程仍可分享访问、站点数不变）。"""
    _, headers = auth_user
    trip_id, _ = await _make_owner_trip(client, headers, "源")
    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}", headers=headers)
    assert resp.status_code == 200

    resp = await client.post(f"/api/v1/trips/favorites/{trip_id}/route", headers=headers)
    assert resp.status_code == 201
    copy_id = resp.json()["id"]
    assert copy_id != trip_id

    # 原行程仍可读且站点数不变
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["days"][0]["stops"]) == 2
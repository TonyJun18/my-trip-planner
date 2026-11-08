"""单日「按最优顺序重排」测试（task-auto-optimize-cta）。

覆盖：
- 纯函数：站数不足 / 坐标不足 / 真变短才变更 / 已最优 / 缺坐标槽位保持 / 平局确定性
- 服务+API：重排落库后顺序真的变了、再跑一次 already_optimal、他人行程 404、未知日程 404
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.day_optimizer import optimize_order


def _stop(sid: str, name: str, order: int, lat=None, lng=None) -> dict:
    return {"id": sid, "name": name, "order_index": order, "lat": lat, "lng": lng}


# ── 纯函数 ────────────────────────────────────────────────────
def test_optimize_too_few_stops():
    proposal = optimize_order([
        _stop("a", "西湖", 1, 30.0, 120.0),
        _stop("b", "灵隐寺", 2, 30.1, 120.1),
    ])
    assert proposal["changed"] is False
    assert proposal["reason"] == "too_few_stops"
    assert proposal["order"] == ["a", "b"]


def test_optimize_insufficient_coords():
    proposal = optimize_order([
        _stop("a", "西湖", 1, 30.0, 120.0),
        _stop("b", "灵隐寺", 2),
        _stop("c", "龙井村", 3),
    ])
    assert proposal["changed"] is False
    assert proposal["reason"] == "insufficient_coords"


def test_optimize_reorders_zigzag():
    """首站锚定不变，其余按最近邻变短（贪心：起点 → 近点 → 次远 → 远点）。"""
    proposal = optimize_order([
        _stop("a", "起点", 1, 30.00, 120.00),
        _stop("b", "远点", 2, 30.50, 120.50),
        _stop("c", "近点", 3, 30.02, 120.02),
        _stop("d", "次远", 4, 30.40, 120.40),
    ])
    assert proposal["changed"] is True
    assert proposal["reason"] == "reordered"
    assert proposal["order"][0] == "a", "首站必须锚定"
    # 最近邻：从 a 出发先到 c（≈3km），再从 c 挑 d（≈54km）而不是 b（≈68km）
    assert proposal["order"] == ["a", "c", "d", "b"]
    assert proposal["saved_km"] > 0
    assert proposal["distance_after_km"] < proposal["distance_before_km"]
    # names 与新顺序对齐
    assert proposal["names"] == ["起点", "近点", "次远", "远点"]


def test_optimize_already_optimal():
    proposal = optimize_order([
        _stop("a", "起点", 1, 30.00, 120.00),
        _stop("c", "近点", 2, 30.02, 120.02),
        _stop("b", "远点", 3, 30.50, 120.50),
    ])
    assert proposal["changed"] is False
    assert proposal["reason"] == "already_optimal"
    assert proposal["order"] == ["a", "c", "b"]


def test_optimize_keeps_missing_coord_slot():
    """缺坐标的站点保持原槽位，不被挤到前面或末尾。"""
    proposal = optimize_order([
        _stop("a", "起点", 1, 30.00, 120.00),
        _stop("x", "无坐标", 2),
        _stop("b", "远点", 3, 30.50, 120.50),
        _stop("c", "近点", 4, 30.02, 120.02),
    ])
    assert proposal["changed"] is True
    assert proposal["order"][0] == "a"
    assert proposal["order"][1] == "x", "第 2 槽位仍是无坐标站点"
    assert proposal["order"][2:] == ["c", "b"]


def test_optimize_is_deterministic_on_ties():
    """等距平局按 id 排序，结果稳定（不随字典顺序漂移）。"""
    first = optimize_order([
        _stop("a", "起点", 1, 30.00, 120.00),
        _stop("b", "东", 2, 30.00, 120.10),
        _stop("c", "西", 3, 30.00, 119.90),
        _stop("d", "北", 4, 30.10, 120.00),
    ])
    second = optimize_order([
        _stop("a", "起点", 1, 30.00, 120.00),
        _stop("c", "西", 3, 30.00, 119.90),
        _stop("d", "北", 4, 30.10, 120.00),
        _stop("b", "东", 2, 30.00, 120.10),
    ])
    assert first["order"] == second["order"]


# ── 服务 + API ────────────────────────────────────────────────
async def _make_trip_with_zigzag_day(client: AsyncClient, headers: dict) -> tuple[str, str]:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "重排测试行程", "destination": "杭州", "departure": "上海",
        "start_date": "2026-11-01", "end_date": "2026-11-01", "travelers": 2, "budget": 3000,
    })
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers,
                             json={"day_number": 1, "date": "2026-11-01"})
    assert resp.status_code in (200, 201), resp.text
    day_id = resp.json()["id"]

    # 之字形顺序：起点 → 远点 → 近点（应被改成 起点 → 近点 → 远点）
    for name, lat, lng in [("起点", 30.00, 120.00), ("远点", 30.50, 120.50), ("近点", 30.02, 120.02)]:
        resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", headers=headers,
                                 json={"name": name, "stop_type": "attraction", "lat": lat, "lng": lng})
        assert resp.status_code in (200, 201), resp.text
    return trip_id, day_id


@pytest.mark.asyncio
async def test_optimize_endpoint_applies_and_persists(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, day_id = await _make_trip_with_zigzag_day(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/days/{day_id}/optimize-order", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["changed"] is True
    assert body["reason"] == "reordered"
    assert body["day_id"] == day_id
    assert body["names"] == ["起点", "近点", "远点"]
    assert body["saved_km"] > 0
    assert body["summary"]

    # 落库校验：重新读取行程，站点顺序已是新顺序
    trip = (await client.get(f"/api/v1/trips/{trip_id}", headers=headers)).json()
    names = [s["name"] for s in trip["days"][0]["stops"]]
    assert names == ["起点", "近点", "远点"]
    indexes = [s["order_index"] for s in trip["days"][0]["stops"]]
    assert indexes == [1, 2, 3]


@pytest.mark.asyncio
async def test_optimize_second_call_is_noop(client: AsyncClient, auth_user):
    """已经最优时不再落库，返回 already_optimal（不假装优化）。"""
    _user, headers = auth_user
    trip_id, day_id = await _make_trip_with_zigzag_day(client, headers)

    first = await client.post(f"/api/v1/trips/{trip_id}/days/{day_id}/optimize-order", headers=headers)
    assert first.status_code == 200 and first.json()["changed"] is True

    second = await client.post(f"/api/v1/trips/{trip_id}/days/{day_id}/optimize-order", headers=headers)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["changed"] is False
    assert body["reason"] == "already_optimal"
    assert body["saved_km"] == 0.0


@pytest.mark.asyncio
async def test_optimize_requires_login(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, day_id = await _make_trip_with_zigzag_day(client, headers)
    resp = await client.post(f"/api/v1/trips/{trip_id}/days/{day_id}/optimize-order")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_optimize_other_users_trip(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, day_id = await _make_trip_with_zigzag_day(client, headers)

    other = await client.post("/api/v1/auth/register", json={
        "email": "other-optimize@test.com", "password": "test1234", "display_name": "他者",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/days/{day_id}/optimize-order", headers=other_headers,
    )
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_optimize_unknown_day(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id, _day_id = await _make_trip_with_zigzag_day(client, headers)
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/days/not-a-day/optimize-order", headers=headers,
    )
    assert resp.status_code == 404

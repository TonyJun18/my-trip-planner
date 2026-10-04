"""地图拖拽修订（task-map-drag-edit）测试。

覆盖：
- 拖拽 marker 改坐标 → 原子应用 + 落库 + plan 返回（最小 diff 内核）
- 坐标未变化 → no-op（applied=False，不落库）
- 站点不存在 → 404
- 坐标越界 → 422（Pydantic 强校验）
- 自驾约束门（DrivingGate）：拖到超距 → 400 拒绝，站点坐标不回滚残留
- 鉴权：未登录 401 / 非 owner 404
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta


def _rand_email() -> str:
    return f"map-{uuid.uuid4().hex[:8]}@test.com"


async def _make_trip_with_stops(client, headers, stops):
    """建行程 + 第 1 天 + 若干站点，返回 trip_id 与 day_id。"""
    today = date.today()
    resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "地图拖拽测试",
            "destination": "杭州",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=1)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/days",
        json={"day_number": 1, "note": "第一天"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    for i, s in enumerate(stops, start=1):
        resp = await client.post(
            f"/api/v1/trips/days/{day_id}/stops",
            json={
                "name": s["name"],
                "stop_type": s.get("stop_type", "attraction"),
                "lat": s["lat"],
                "lng": s["lng"],
                "estimated_cost": s.get("estimated_cost", 0),
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["order_index"] == i
    return trip_id, day_id


async def test_map_edit_moves_stop(client, auth_user):
    """拖拽 marker 改坐标 → 站点坐标更新 + 落库 + plan 快照返回。"""
    _, headers = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers,
        [{"name": "西湖", "lat": 30.24, "lng": 120.15}],
    )

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "西湖", "lat": 30.25, "lng": 120.16},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert "地图调整" in body["summary"]

    # plan 快照里坐标已更新
    stops = body["plan"]["days"][0]["stops"]
    assert stops[0]["name"] == "西湖"
    assert abs(stops[0]["lat"] - 30.25) < 1e-6
    assert abs(stops[0]["lng"] - 120.16) < 1e-6

    # 落库持久化：重新 GET 行程确认
    trip = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert trip.status_code == 200
    saved = trip.json()["days"][0]["stops"][0]
    assert abs(saved["lat"] - 30.25) < 1e-6
    assert abs(saved["lng"] - 120.16) < 1e-6


async def test_map_edit_noop_on_same_coords(client, auth_user):
    """拖回原位 → no-op（applied=False），不落库不触发约束门。"""
    _, headers = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers,
        [{"name": "灵隐寺", "lat": 30.24, "lng": 120.10}],
    )

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "灵隐寺", "lat": 30.24, "lng": 120.10},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is False


async def test_map_edit_stop_not_found(client, auth_user):
    """站点不存在 → 404。"""
    _, headers = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers,
        [{"name": "西湖", "lat": 30.24, "lng": 120.15}],
    )

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "不存在的站点", "lat": 30.3, "lng": 120.2},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


async def test_map_edit_bad_coords_422(client, auth_user):
    """坐标越界 → 422（Pydantic 强校验，绝不进 diff）。"""
    _, headers = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers,
        [{"name": "西湖", "lat": 30.24, "lng": 120.15}],
    )

    # lat 越界
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "西湖", "lat": 91.0, "lng": 120.15},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    # lng 越界
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "西湖", "lat": 30.24, "lng": 181.0},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text

    # 落库不受影响（坐标未变）
    trip = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    saved = trip.json()["days"][0]["stops"][0]
    assert abs(saved["lat"] - 30.24) < 1e-6
    assert abs(saved["lng"] - 120.15) < 1e-6


async def test_map_edit_driving_gate_rejects_far_move(client, auth_user):
    """DrivingGate 约束前置：拖到超距（>120km）→ 400 拒绝，坐标不落库。"""
    _, headers = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers,
        [
            {"name": "西湖", "lat": 30.24, "lng": 120.15},
            {"name": "断桥", "lat": 30.26, "lng": 120.15},  # 距西湖 ~2km
        ],
    )

    # 把断桥拖到上海方向（距西湖 ~170km）→ 单段超距 critical
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "断桥", "lat": 31.23, "lng": 121.47},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()["error"]
    assert body["code"] == "revise_driving_violation"
    assert body["detail"]["issues"], "拒绝时应返回自驾 issues"

    # 坐标未落库（原子拒绝）
    trip = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    stops = trip.json()["days"][0]["stops"]
    by_name = {s["name"]: s for s in stops}
    assert abs(by_name["断桥"]["lat"] - 30.26) < 1e-6
    assert abs(by_name["断桥"]["lng"] - 120.15) < 1e-6


async def test_map_edit_single_stop_no_driving_block(client, auth_user):
    """单站点拖拽不受自驾约束影响（无相邻段）。"""
    _, headers = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers,
        [{"name": "孤山", "lat": 30.25, "lng": 120.13}],
    )

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "孤山", "lat": 30.26, "lng": 120.14},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_map_edit_requires_auth(client):
    """未登录 → 401。"""
    resp = await client.post(
        "/api/v1/trips/some-trip/map-edit",
        json={"name": "西湖", "lat": 30.3, "lng": 120.2},
    )
    assert resp.status_code == 401, resp.text


async def test_map_edit_owner_isolation(client, auth_user):
    """非 owner 改不了别人的行程 → 404（与 revise 同款 owner 过滤）。"""
    user_a, headers_a = auth_user
    trip_id, _ = await _make_trip_with_stops(
        client, headers_a,
        [{"name": "西湖", "lat": 30.24, "lng": 120.15}],
    )
    assert user_a["id"]

    # 注册用户 B
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": _rand_email(), "password": "test1234", "display_name": "路人乙"},
    )
    headers_b = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/map-edit",
        json={"name": "西湖", "lat": 30.3, "lng": 120.2},
        headers=headers_b,
    )
    assert resp.status_code == 404, resp.text
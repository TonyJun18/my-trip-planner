"""test_plan_b_api.py —— Plan B 备选方案 API 测试。

覆盖：
- 有站点行程 → 返回一个备选变体（label/deltas/days/budget）
- 无站点行程 → 404（与 /trips/{id} 同一鉴权语义）
- 未登录 → 401
- 他人行程 → 404（owner 隔离）
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta


def _rand_email() -> str:
    return f"planb-{uuid.uuid4().hex[:8]}@test.com"


async def test_plan_b_returns_variant(client, auth_user):
    """有站点的行程 → 返回备选变体（确定性、无 LLM）。"""
    _, headers = auth_user
    today = date.today()
    resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "杭州三日",
            "destination": "杭州",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=2)).isoformat(),
            "travelers": 2,
            "budget": 3000,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    # 两天，每天一个景点 + 一天带酒店站点（触发确定性备选：预算档变体）
    for i in (1, 2):
        d = await client.post(
            f"/api/v1/trips/{trip_id}/days",
            json={"day_number": i, "note": f"第{i}天"},
            headers=headers,
        )
        assert d.status_code == 201, d.text
        day_id = d.json()["id"]
        s = await client.post(
            f"/api/v1/trips/days/{day_id}/stops",
            json={
                "name": f"景点{i}",
                "stop_type": "attraction",
                "estimated_cost": 50,
                "estimated_duration_minutes": 120,
                "description": f"第{i}天景点",
            },
            headers=headers,
        )
        assert s.status_code == 201, s.text
    # 第 1 天再加一个酒店站点（有可取舍内容 → 备选必然生成）
    day1 = (
        await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    ).json()["days"][0]
    h = await client.post(
        f"/api/v1/trips/days/{day1['id']}/stops",
        json={
            "name": "西湖大酒店",
            "stop_type": "hotel",
            "estimated_cost": 400,
            "estimated_duration_minutes": None,
            "description": "近西湖",
        },
        headers=headers,
    )
    assert h.status_code == 201, h.text

    resp = await client.get(f"/api/v1/trips/{trip_id}/plan-b", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trip_id"] == trip_id
    assert body["variant"] is not None
    v = body["variant"]
    assert v["label"] in ("节奏优化版", "预算优化版", "精简取舍版")
    assert v["description"]
    assert isinstance(v["deltas"], list) and v["deltas"]
    assert v["days"] and all(d["stops"] for d in v["days"])
    assert v["budget"]["total_estimated"] >= 0
    assert v["budget"]["currency"] == "CNY"


async def test_plan_b_requires_auth(client):
    """未登录 → 401。"""
    resp = await client.get("/api/v1/trips/whatever/plan-b")
    assert resp.status_code == 401


async def test_plan_b_not_found(client, auth_user):
    """不存在的行程 → 404。"""
    _, headers = auth_user
    resp = await client.get(f"/api/v1/trips/{uuid.uuid4()}/plan-b", headers=headers)
    assert resp.status_code == 404


async def test_plan_b_owner_isolation(client):
    """他人行程 → 404（与 /trips/{id} 同一 owner 隔离语义）。"""
    ea = _rand_email()
    ra = await client.post("/api/v1/auth/register", json={"email": ea, "password": "test1234"})
    headers_a = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    eb = _rand_email()
    rb = await client.post("/api/v1/auth/register", json={"email": eb, "password": "test1234"})
    headers_b = {"Authorization": f"Bearer {rb.json()['access_token']}"}

    today = date.today()
    resp = await client.post(
        "/api/v1/trips",
        json={
            "title": "A 的行程",
            "destination": "杭州",
            "start_date": today.isoformat(),
            "end_date": today.isoformat(),
        },
        headers=headers_a,
    )
    trip_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/trips/{trip_id}/plan-b", headers=headers_b)
    assert resp.status_code == 404
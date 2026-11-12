"""相框数据投影测试（frame-marketplace）。

覆盖 spec「单日卡数据投影」「整程总结图数据投影」场景：
- 单日投影仅含 checked 站点（坐标/名称/类型/备注/当日 note）
- 空日 → empty=true（诚实返回，非报错）
- 非 owner → 403/404，不泄露数据
- 总结图投影聚合各日 checked 站点 + 全程统计，空日跳过；全程无打卡 → empty=true
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _make_trip(client: AsyncClient, headers: dict, days: int = 2) -> tuple[str, list[str]]:
    """创建带 days 天的行程（日期从今天起，保证处于「行中」可打卡），返回 (trip_id, day_ids)。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "相框投影测试", "destination": "杭州",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=days - 1)).isoformat(),
        "travelers": 2,
    })
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]
    day_ids: list[str] = []
    for n in range(1, days + 1):
        r = await client.post(
            f"/api/v1/trips/{trip_id}/days",
            headers=headers,
            json={"day_number": n, "note": f"第{n}天主题"},
        )
        assert r.status_code in (200, 201), r.text
        day_ids.append(r.json()["id"])
    return trip_id, day_ids


async def _add_stop(client: AsyncClient, headers: dict, day_id: str, name: str, *, lat=None, lng=None, description=None) -> dict:
    payload: dict = {"name": name, "stop_type": "attraction"}
    if lat is not None:
        payload["lat"] = lat
    if lng is not None:
        payload["lng"] = lng
    if description is not None:
        payload["description"] = description
    r = await client.post(f"/api/v1/trips/days/{day_id}/stops", headers=headers, json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _check_stop(client: AsyncClient, headers: dict, trip_id: str, stop_id: str):
    r = await client.post(f"/api/v1/trips/{trip_id}/live/stops/{stop_id}/check", headers=headers, json={})
    assert r.status_code in (200, 201), r.text


# ── 单日卡投影 ────────────────────────────────────────────────


async def test_day_projection_only_contains_checked_stops(client, auth_user):
    _, headers = auth_user
    trip_id, (day1_id, day2_id) = await _make_trip(client, headers)

    checked = await _add_stop(client, headers, day1_id, "西湖", lat=30.24, lng=120.15, description="湖边看日落")
    unchecked = await _add_stop(client, headers, day1_id, "灵隐寺", lat=30.24, lng=120.10)
    await _add_stop(client, headers, day2_id, "宋城", lat=30.20, lng=120.12)  # 别的日子，不该出现在 day1
    await _check_stop(client, headers, trip_id, checked["id"])

    resp = await client.get(f"/api/v1/trips/{trip_id}/frames/{day1_id}/data", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["empty"] is False
    assert body["day_number"] == 1
    assert body["day_note"] == "第1天主题"
    names = [s["name"] for s in body["stops"]]
    assert names == ["西湖"]
    stop = body["stops"][0]
    assert stop["lat"] == pytest.approx(30.24)
    assert stop["lng"] == pytest.approx(120.15)
    assert stop["description"] == "湖边看日落"
    assert stop["stop_id"] == checked["id"]


async def test_day_projection_empty_day_returns_empty_flag(client, auth_user):
    _, headers = auth_user
    trip_id, (day1_id, _) = await _make_trip(client, headers)
    await _add_stop(client, headers, day1_id, "未打卡的景点")

    resp = await client.get(f"/api/v1/trips/{trip_id}/frames/{day1_id}/data", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["empty"] is True
    assert resp.json()["stops"] == []


async def test_day_projection_non_owner_forbidden(client, auth_user):
    _, headers_a = auth_user
    trip_id, (day1_id, _) = await _make_trip(client, headers_a)

    # 用户 B
    email_b = f"user-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email_b, "password": "test1234", "display_name": "B"})
    headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    resp = await client.get(f"/api/v1/trips/{trip_id}/frames/{day1_id}/data", headers=headers_b)
    assert resp.status_code in (403, 404)
    assert "stops" not in resp.json()


# ── 整程总结图投影 ────────────────────────────────────────────


async def test_summary_projection_aggregates_checked_days_skips_empty(client, auth_user):
    _, headers = auth_user
    trip_id, (day1_id, day2_id) = await _make_trip(client, headers)

    s1 = await _add_stop(client, headers, day1_id, "西湖", lat=30.24, lng=120.15)
    await _add_stop(client, headers, day2_id, "宋城", lat=30.20, lng=120.12)
    await _add_stop(client, headers, day2_id, "河坊街", lat=30.24, lng=120.17)
    await _check_stop(client, headers, trip_id, s1["id"])  # day2 全未打卡

    resp = await client.get(f"/api/v1/trips/{trip_id}/frames/summary/data", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["empty"] is False
    assert body["stats"]["checked_stops"] == 1
    assert body["stats"]["days_with_checkins"] == 1
    day_numbers = [d["day_number"] for d in body["days"]]
    assert day_numbers == [1]  # 空日 day2 跳过
    assert body["days"][0]["stops"][0]["name"] == "西湖"


async def test_summary_projection_all_empty_returns_empty_flag(client, auth_user):
    _, headers = auth_user
    trip_id, _ = await _make_trip(client, headers)

    resp = await client.get(f"/api/v1/trips/{trip_id}/frames/summary/data", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["empty"] is True


async def test_summary_projection_non_owner_forbidden(client, auth_user):
    _, headers_a = auth_user
    trip_id, _ = await _make_trip(client, headers_a)

    email_b = f"user-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email_b, "password": "test1234", "display_name": "B"})
    headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    resp = await client.get(f"/api/v1/trips/{trip_id}/frames/summary/data", headers=headers_b)
    assert resp.status_code in (403, 404)
    assert "days" not in resp.json()

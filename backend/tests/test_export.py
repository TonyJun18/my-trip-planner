"""行程 JSON 导出测试（task-export-offline）。

覆盖：owner 导出 / 令牌免登录导出 / 归属隔离 / 无效令牌 / plan 元信息随行。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_trip_with_stop(client: AsyncClient, headers: dict) -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "导出测试行程", "destination": "杭州", "departure": "上海",
        "start_date": "2026-11-01", "end_date": "2026-11-02", "travelers": 2,
        "budget": 3000,
    })
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers,
                             json={"day_number": 1, "note": "西湖日"})
    assert resp.status_code in (200, 201), resp.text
    day_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", headers=headers,
                             json={"name": "西湖", "stop_type": "attraction",
                                   "estimated_cost": 100.0, "estimated_duration_minutes": 120})
    assert resp.status_code in (200, 201), resp.text
    return trip_id


@pytest.mark.asyncio
async def test_export_trip_owner(client: AsyncClient, auth_user):
    """owner 导出：trip + days + stops + 预算汇总，无令牌字段。"""
    _user, headers = auth_user
    trip_id = await _make_trip_with_stop(client, headers)

    resp = await client.get(f"/api/v1/trips/{trip_id}/export", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] == "1.0"
    assert body["exported_at"]
    assert body["trip"]["destination"] == "杭州"
    assert body["trip"]["departure"] == "上海"
    assert body["trip"]["travelers"] == 2
    # 令牌/凭证绝不进导出
    assert "share_token" not in body["trip"]
    assert "edit_token" not in body["trip"]

    assert len(body["days"]) == 1
    assert body["days"][0]["day_number"] == 1
    assert body["days"][0]["stops"][0]["name"] == "西湖"
    assert body["days"][0]["stops"][0]["estimated_cost"] == 100.0

    # 预算汇总：站点合计（无 plan → 无大交通）
    assert body["budget_summary"]["total_estimated"] == 100.0
    assert body["budget_summary"]["by_type"]["attraction"] == 100.0
    # 无 AI plan → plan 为 None（手工行程也可导出）
    assert body["plan"] is None


@pytest.mark.asyncio
async def test_export_trip_owner_isolation(client: AsyncClient, auth_user):
    """归属隔离：非 owner 无法导出他人的行程。"""
    _user, headers = auth_user
    trip_id = await _make_trip_with_stop(client, headers)

    other = await client.post("/api/v1/auth/register", json={
        "email": "other-export@test.com", "password": "test1234", "display_name": "他者",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.get(f"/api/v1/trips/{trip_id}/export", headers=other_headers)
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_export_shared_trip_by_token(client: AsyncClient, auth_user):
    """分享令牌免登录导出：与 /share/{token} 同信任语义。"""
    _user, headers = auth_user
    trip_id = await _make_trip_with_stop(client, headers)

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    token = resp.json()["share_token"]

    resp = await client.get(f"/api/v1/trips/share/{token}/export")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trip"]["id"] == trip_id
    assert body["days"][0]["stops"][0]["name"] == "西湖"
    assert body["budget_summary"]["total_estimated"] == 100.0


@pytest.mark.asyncio
async def test_export_shared_invalid_token(client: AsyncClient):
    """无效分享令牌 → 404（不泄露行程是否存在）。"""
    resp = await client.get("/api/v1/trips/share/not-a-real-token/export")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_includes_plan_meta(client: AsyncClient, auth_user, db_session):
    """有 AI plan 快照时：质检/时段校验/警告随之导出，day 不重复。"""
    _user, headers = auth_user
    trip_id = await _make_trip_with_stop(client, headers)

    from app.models import TripPlan

    db_session.add(TripPlan(
        trip_id=trip_id,
        plan_data={
            "warnings": ["酒店搜索失败，已用通用描述替代"],
            "quality": {"score": 85, "passed": True, "rounds": 1,
                        "issues": [], "summary": "ok"},
            "time_gate": {"passed": True, "issues": [], "critical_count": 0,
                          "warning_count": 0, "summary": "时段校验通过"},
            "budget": {"total_estimated": 100.0,
                       "by_type": {"attraction": 100.0}, "currency": "CNY"},
            "days": [{"day_number": 1, "stops": []}],  # 冗余 days 应被剔除
        },
        status="completed",
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/trips/{trip_id}/export", headers=headers)
    assert resp.status_code == 200, resp.text
    plan = resp.json()["plan"]
    assert plan["warnings"] == ["酒店搜索失败，已用通用描述替代"]
    assert plan["quality"]["score"] == 85
    assert plan["time_gate"]["passed"] is True
    # plan 里的冗余 days 不随导出（权威数据在顶层 days）
    assert "days" not in plan
    # 顶层 days 仍来自 trip（1 个真实站点）
    assert resp.json()["days"][0]["stops"][0]["name"] == "西湖"
"""回归：带 TripPlan 快照的行程可正常删除（DELETE 204）。

背景（2026-11-15 实测发现）：`Trip.plans` relationship 补 `cascade="all, delete-orphan"` 前，
`_TRIP_LOADS` 会把 TripPlan eager-load 进 session，delete_trip 时 SQLAlchemy 对已加载但无 cascade
的子对象执行默认 nullify（UPDATE trip_plans SET trip_id = NULL）→ 违反 trip_plans.trip_id NOT NULL
→ IntegrityError → 500。规划自动建的行程必带 TripPlan → 用户删行程必炸。

本文件锁住：带 plan 的行程 DELETE 必须 204，且 trip_plans 行被级联清掉。
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


async def _seed_plan(test_engine, trip_id):
    """给行程补一条 completed TripPlan 快照（等同 AI 规划产物）。"""
    from app.models import TripPlan

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        db.add(TripPlan(
            trip_id=trip_id,
            plan_data={"destination": "杭州", "days": [], "budget": {"total_estimated": 0.0}},
            status="completed",
        ))
        await db.commit()


async def _count_plans(test_engine, trip_id) -> int:
    from app.models import TripPlan

    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as db:
        return (await db.execute(
            select(func.count()).select_from(TripPlan).where(TripPlan.trip_id == trip_id)
        )).scalar_one()


async def _make_trip(client, headers) -> str:
    from datetime import date, timedelta

    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "带方案行程", "destination": "杭州",
        "start_date": (today + timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=3)).isoformat(),
        "travelers": 2, "budget": 2000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_delete_trip_with_plan_snapshot_succeeds(client, auth_user, test_engine):
    """带 completed TripPlan 的行程 DELETE 204，且 trip_plans 级联清空。"""
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    await _seed_plan(test_engine, trip_id)
    assert await _count_plans(test_engine, trip_id) == 1, "前置：plan 快照已存在"

    resp = await client.delete(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 204, f"DELETE 带 plan 行程应 204，实得 {resp.status_code}: {resp.text[:300]}"

    assert await _count_plans(test_engine, trip_id) == 0, "级联：trip_plans 行应随行程删除被清空"


async def test_delete_trip_with_archived_versions_succeeds(client, auth_user, test_engine):
    """修订产生的 archived 多版本快照也能一并删除（多行级联）。"""
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    await _seed_plan(test_engine, trip_id)
    await _seed_plan(test_engine, trip_id)  # 两条 plan（等效 archived + completed）

    resp = await client.delete(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 204, f"DELETE 多版本 plan 行程应 204，实得 {resp.status_code}: {resp.text[:300]}"
    assert await _count_plans(test_engine, trip_id) == 0
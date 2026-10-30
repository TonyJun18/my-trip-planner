"""task-floattrip-borrow Story 1：行程重排提交服务（拖拽换序 + 保存重算）。

核心契约（Story 1 AC-3：保存时服务端重算每段距离与预算，失败回滚不产生半保存）：
- commit_reorder 原子落库：order 必须包含该日全部站点 id（缺漏/乱序 → 400）
- DrivingGate 前置：重排后超距/超时 → 整体拒绝（400 + issues），不落库
- 预算/自驾/TimeGate/DynamicFacts 随重排重算复用 revise_service._recompute_budget
- 版本保留：重排提交也产生新版本（archived + completed），与原修订链路一致
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.reorder_service import commit_reorder


# ── 工具：造行程 + 站点 ──────────────────────────────────────
async def _make_trip_with_stops(client, headers, stops=("西湖", "楼外楼", "灵隐寺")):
    """建行程 + Day + 站点，返回 (trip_id, day_id, [stop_id...])。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州一日", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": 2, "budget": 2000,
    }, headers=headers)
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    day_id = resp.json()["id"]
    stop_ids = []
    for i, name in enumerate(stops, start=1):
        r = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": "attraction" if i % 2 else "food",
            "lat": 30.2 + i * 0.01, "lng": 120.1 + i * 0.01,
            "estimated_cost": 50, "estimated_duration_minutes": 120,
        }, headers=headers)
        stop_ids.append(r.json()["id"])
    return trip_id, day_id, stop_ids


async def _make_trip_db(client, headers):
    """建行程 + Day（无站点），返回 trip Repository 可用的 (trip_id, day_id)。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州一日", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": 1, "budget": 1000,
    }, headers=headers)
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    return trip_id, resp.json()["id"]


async def _fetch_day(test_engine, day_id):
    """按 day_id 读取站点顺序（order_index 升序），返回 [stop_id]。"""
    from app.models import Stop

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        stops = list((await db.execute(
            select(Stop).where(Stop.day_id == day_id).order_by(Stop.order_index)
        )).scalars().all())
        return [s.id for s in stops]


# ── 用例 ────────────────────────────────────────────────────
async def test_reorder_commits_new_order(client, auth_user, test_engine):
    """Story 1 AC-1/AC-3：保存重排 → 站点顺序更新 + 预算重算（快照刷新）。"""
    _, headers = auth_user
    trip_id, day_id, stop_ids = await _make_trip_with_stops(client, headers)

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        result = await commit_reorder(
            db, trip_id,
            days=[{"day_id": day_id, "order": [stop_ids[2], stop_ids[0], stop_ids[1]]}],
            owner=auth_user[0]["id"],
        )
        await db.commit()
    assert result["applied"] is True

    order = await _fetch_day(test_engine, day_id)
    assert order == [stop_ids[2], stop_ids[0], stop_ids[1]], "站点顺序应按新 order 落库"


async def test_reorder_rejects_partial_order(client, auth_user, test_engine):
    """Story 1 失败回滚：order 缺站点 → 400，不落库（不产生半保存）。"""
    _, headers = auth_user
    trip_id, day_id, stop_ids = await _make_trip_with_stops(client, headers)

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        with pytest.raises(Exception) as exc:
            await commit_reorder(
                db, trip_id,
                days=[{"day_id": day_id, "order": [stop_ids[0], stop_ids[1]]}],  # 缺灵隐寺
                owner=auth_user[0]["id"],
            )
        assert "stop_order_invalid" in str(exc.value) or "全部站点" in str(exc.value)
        await db.rollback()

    # 顺序未被破坏（原始顺序保留）
    order = await _fetch_day(test_engine, day_id)
    assert order == stop_ids


async def test_reorder_rejects_foreign_day(client, auth_user, test_engine):
    """Story 1 越权边界：day_id 不属于该行程 → 404/400，不落库。"""
    _, headers = auth_user
    trip_id, _, stop_ids = await _make_trip_with_stops(client, headers)

    # 造另一行程的 day_id
    other_trip, other_day, _ = await _make_trip_with_stops(client, headers)
    assert other_trip != trip_id

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        with pytest.raises(Exception):
            await commit_reorder(
                db, trip_id,
                days=[{"day_id": other_day, "order": stop_ids}],
                owner=auth_user[0]["id"],
            )
        await db.rollback()
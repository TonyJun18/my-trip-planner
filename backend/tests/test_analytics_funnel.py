"""最小漏斗埋点落库测试（task-launch-deploy-eval §2.2）。

覆盖：
1. dedicated=true + funnel → 204 且 analytics_events 落 1 条
2. 5 类白名单事件逐一落库（event_name 原样保存）
3. 白名单外事件名 → 422
4. 匿名（无 user_id，仅 anonymous_session_id）可记录
5. 既有意图埋点（无 dedicated）→ 204 且不落库（零回归）
6. dedicated=true 但缺 funnel → 422
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.analytics import AnalyticsEvent

FUNNEL_NAMES = ["page_view", "register", "plan_submitted", "plan_completed", "share_created"]


async def _count(test_engine) -> int:
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(AnalyticsEvent))).scalar_one())


@pytest.mark.asyncio
async def test_funnel_event_persisted(client, test_engine):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "dedicated": True,
            "funnel": {
                "name": "page_view",
                "anonymous_session_id": "s1",
                "payload": {"page": "/"},
            },
        },
    )
    assert resp.status_code == 204
    assert await _count(test_engine) == 1


@pytest.mark.asyncio
async def test_funnel_all_five_events(client, test_engine):
    for name in FUNNEL_NAMES:
        resp = await client.post(
            "/api/v1/analytics/events",
            json={"dedicated": True, "funnel": {"name": name, "anonymous_session_id": "s1"}},
        )
        assert resp.status_code == 204, resp.text
    assert await _count(test_engine) == len(FUNNEL_NAMES)

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        names = {
            row[0]
            for row in (await session.execute(select(AnalyticsEvent.event_name))).all()
        }
    assert names == set(FUNNEL_NAMES)


@pytest.mark.asyncio
async def test_funnel_rejects_unknown_event(client, test_engine):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={"dedicated": True, "funnel": {"name": "not_a_funnel_event"}},
    )
    assert resp.status_code == 422
    assert await _count(test_engine) == 0


@pytest.mark.asyncio
async def test_funnel_anonymous_allowed(client, test_engine):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "dedicated": True,
            "funnel": {
                "name": "page_view",
                "anonymous_session_id": "anon-123",
                "payload": {"path": "/wizard"},
            },
        },
    )
    assert resp.status_code == 204

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        row = (await session.execute(select(AnalyticsEvent))).scalar_one()
    assert row.user_id is None
    assert row.anonymous_session_id == "anon-123"
    assert row.payload == {"path": "/wizard"}


@pytest.mark.asyncio
async def test_intent_event_not_persisted(client, test_engine):
    """既有意图埋点（无 dedicated）行为不变：204 日志，不落库。"""
    resp = await client.post("/api/v1/analytics/events", json={"name": "planning_tool_open"})
    assert resp.status_code == 204
    assert await _count(test_engine) == 0


@pytest.mark.asyncio
async def test_dedicated_without_funnel_422(client, test_engine):
    resp = await client.post("/api/v1/analytics/events", json={"dedicated": True})
    assert resp.status_code == 422
    assert await _count(test_engine) == 0

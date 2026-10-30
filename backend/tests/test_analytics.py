"""埋点端点测试（task-trip-detail-refactor：POST /api/v1/analytics/events）。"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_analytics_post_event_planning_tool_open(client):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "name": "planning_tool_open",
            "payload": {
                "trip_id": "trip-1",
                "trip_phase": "planning",
                "viewport_width": 1440,
                "is_touch": False,
                "role": "owner",
                "tool": "ai_revise",
            },
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_analytics_post_event_top_action(client):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "name": "top_action_click",
            "payload": {
                "trip_id": "trip-1",
                "trip_phase": "planning",
                "viewport_width": 375,
                "is_touch": True,
                "role": "owner",
                "action": "share",
            },
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_analytics_post_event_first_view(client):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "name": "itinerary_first_view",
            "payload": {
                "trip_id": "trip-1",
                "trip_phase": "live",
                "viewport_width": 1440,
                "is_touch": False,
                "role": "owner",
                "visible": True,
            },
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_analytics_post_event_scroll_depth(client):
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "name": "itinerary_scroll_depth",
            "payload": {
                "trip_id": "trip-1",
                "trip_phase": "planning",
                "viewport_width": 1440,
                "is_touch": False,
                "role": "owner",
                "depth": 50,
            },
        },
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_analytics_rejects_unknown_event(client):
    """白名单外事件名 → 422。"""
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "name": "not_a_real_event",
            "payload": {"trip_id": "trip-1"},
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_analytics_rejects_bad_tool(client):
    """tool 不在白名单 → 422。"""
    resp = await client.post(
        "/api/v1/analytics/events",
        json={
            "name": "planning_tool_open",
            "payload": {"tool": "not_a_tool"},
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_analytics_minimal_payload_ok(client):
    """最小载荷（只有 name）也接受——fire-and-forget 语义。"""
    resp = await client.post("/api/v1/analytics/events", json={"name": "top_action_click"})
    assert resp.status_code == 204
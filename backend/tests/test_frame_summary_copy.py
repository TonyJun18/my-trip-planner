"""整程总结图配文测试（frame-marketplace，任务 7.2）。

覆盖：总结图配文 LLM 主路径 / 模板兜底 / 空投影 empty=true / owner 限定。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import Stop, Trip, TripDay

pytestmark = pytest.mark.asyncio


def _make_trip(*, owner="u-sum", checked=True) -> Trip:
    start = date(2026, 11, 1)
    trip = Trip(
        owner=owner, title="总结", destination="杭州",
        start_date=start, end_date=start + timedelta(days=1), travelers=2,
    )
    d1 = TripDay(day_number=1, date=start, note="西湖日")
    d1.stops.append(Stop(name="西湖", stop_type="attraction", order_index=1, checked=checked))
    trip.days.append(d1)
    return trip


def _summary_proj(trip: Trip):
    day = trip.days[0]
    checked = [s for s in day.stops if s.checked]
    return {
        "trip_id": trip.id,
        "destination": trip.destination,
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "empty": not checked,
        "stats": {"days_with_checkins": 1 if checked else 0, "total_days": 2, "checked_stops": len(checked)},
        "days": [
            {
                "day_id": day.id, "day_number": 1, "date": "2026-11-01", "day_note": day.note,
                "stops": [{
                    "stop_id": s.id, "name": s.name, "stop_type": s.stop_type,
                    "lat": s.lat, "lng": s.lng, "description": s.description, "order_index": s.order_index,
                } for s in checked],
            }
        ] if checked else [],
    }


async def test_trip_copy_llm_success(monkeypatch):
    from app.services import frame_copy_service

    class R:
        content = '{"title": "杭州两日", "body": "两天走了很多地方。", "topics": ["杭州"]}'

    async def fake_invoke(provider, messages, **kwargs):
        return R()

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", fake_invoke)
    monkeypatch.setattr("app.agent.providers.get_provider", lambda name: object())

    trip = _make_trip()
    out = await frame_copy_service.build_trip_copy(trip, _summary_proj(trip), provider="openai")
    assert out["source"] == "llm"
    assert out["empty"] is False


async def test_trip_copy_fallback_template(monkeypatch):
    from app.services import frame_copy_service

    async def boom(*a, **k):
        raise RuntimeError("off")

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)

    trip = _make_trip()
    out = await frame_copy_service.build_trip_copy(trip, _summary_proj(trip), provider="openai")
    assert out["source"] == "template"
    assert "杭州" in out["body"]
    assert "1" in out["body"] or "西湖" in out["body"]  # 统计或站点来自真实投影


async def test_trip_copy_empty_projection(monkeypatch):
    from app.services import frame_copy_service

    async def boom(*a, **k):
        raise RuntimeError("off")

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)

    trip = _make_trip(checked=False)
    out = await frame_copy_service.build_trip_copy(trip, _summary_proj(trip), provider="openai")
    assert out["empty"] is True
    assert out["source"] == "template"


async def test_trip_copy_endpoint_owner_only(client, auth_user):
    import uuid

    from app.services.frame_copy_service import build_trip_copy  # noqa: F401  确认可导入

    async def boom(*a, **k):
        raise RuntimeError("off")

    from httpx import AsyncClient  # noqa: F401

    _, headers = auth_user
    today = date.today()
    r = await client.post("/api/v1/trips", headers=headers, json={
        "title": "总结API", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(), "travelers": 1,
    })
    trip_id = r.json()["id"]

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/frames/summary/copy",
        headers=headers, json={"provider": "openai"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "template"

    email_b = f"user-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email_b, "password": "test1234", "display_name": "B"})
    headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    resp_b = await client.post(
        f"/api/v1/trips/{trip_id}/frames/summary/copy",
        headers=headers_b, json={"provider": "openai"},
    )
    assert resp_b.status_code in (403, 404)

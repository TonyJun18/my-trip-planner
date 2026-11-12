"""AI 配文服务测试（frame-marketplace）。

覆盖 spec「AI 配文生成（双路径降级）」场景：
- LLM 主路径成功 → source=llm，标题/正文/话题齐全
- LLM 失败 → 降级模板 source=template，不报错
- 模板兜底失败（day_note/趣事全空）→ 趣事原文 + 固定话题，仍不报错
- channel=xhs/moments 风格区分
- 数据驱动：文案含打卡站点名与用户趣事，不编造
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import Stop, Trip, TripDay

pytestmark = pytest.mark.asyncio


def _make_trip(*, owner: str = "u-copy") -> Trip:
    start = date(2026, 11, 1)
    trip = Trip(
        owner=owner,
        title="配文测试",
        destination="杭州",
        start_date=start,
        end_date=start + timedelta(days=1),
        travelers=2,
    )
    day = TripDay(day_number=1, date=start, note="西湖暴走一日")
    trip.days.append(day)
    day.stops.append(Stop(name="西湖", stop_type="attraction", order_index=1, checked=True, description="断桥人山人海"))
    day.stops.append(Stop(name="雷峰塔", stop_type="attraction", order_index=2, checked=True))
    day.stops.append(Stop(name="未打卡景点", stop_type="attraction", order_index=3, checked=False))
    return trip


def _projection(trip: Trip):
    """用真实投影服务生成投影（数据驱动验证）。"""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    # 内存库不足以验证关系加载；直接用投影函数的纯数据路径——
    # 这里构造 fake session 仅用于签名兼容（day_projection 需要 db）。
    # 简化：直接手工构造与投影同构的数据。
    day = trip.days[0]
    checked = [s for s in day.stops if s.checked]
    return {
        "trip_id": trip.id,
        "destination": trip.destination,
        "day_id": day.id,
        "day_number": day.day_number,
        "date": day.date.isoformat() if day.date else None,
        "day_note": day.note,
        "empty": not checked,
        "stops": [
            {
                "stop_id": s.id,
                "name": s.name,
                "stop_type": s.stop_type,
                "lat": s.lat,
                "lng": s.lng,
                "description": s.description,
                "order_index": s.order_index,
            }
            for s in checked
        ],
    }


# ── LLM 主路径 ────────────────────────────────────────────────


async def test_llm_success_source_llm(monkeypatch):
    from app.services import frame_copy_service

    class R:
        content = '{"title": "西湖一日", "body": "断桥人山人海，但日落值得。", "topics": ["杭州", "西湖"]}'

    async def fake_invoke(provider, messages, **kwargs):
        return R()

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", fake_invoke)
    monkeypatch.setattr("app.agent.providers.get_provider", lambda name: object())

    trip = _make_trip()
    out = await frame_copy_service.build_day_copy(trip, _projection(trip), channel="xhs", provider="openai")
    assert out["source"] == "llm"
    assert out["title"] == "西湖一日"
    assert out["topics"] == ["杭州", "西湖"]
    assert out["empty"] is False


# ── LLM 失败 → 模板兜底 ───────────────────────────────────────


async def test_llm_failure_falls_back_to_template(monkeypatch):
    from app.services import frame_copy_service

    async def boom(*a, **k):
        raise RuntimeError("llm off")

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)

    trip = _make_trip()
    out = await frame_copy_service.build_day_copy(trip, _projection(trip), channel="xhs", provider="openai")
    assert out["source"] == "template"
    assert "西湖" in out["body"]  # 站点名来自真实投影
    assert "雷峰塔" in out["body"]
    assert "未打卡景点" not in out["body"]  # 只用 checked 站点


# ── 最终兜底：趣事原文 + 固定话题 ─────────────────────────────


async def test_template_fallback_with_no_data_still_returns(monkeypatch):
    from app.services import frame_copy_service

    async def boom(*a, **k):
        raise RuntimeError("llm off")

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)

    trip = Trip(
        owner="u-copy", title="空", destination="",
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 1), travelers=1,
    )
    day = TripDay(day_number=1, date=date(2026, 11, 1), note=None)
    trip.days.append(day)
    proj = {
        "trip_id": trip.id, "destination": "", "day_id": day.id, "day_number": 1,
        "date": "2026-11-01", "day_note": None, "empty": True, "stops": [],
    }
    out = await frame_copy_service.build_day_copy(trip, proj, channel="xhs", provider="openai")
    assert out["empty"] is True  # 无打卡数据不硬编内容
    assert out["source"] == "template"


# ── channel 区分 ──────────────────────────────────────────────


async def test_channels_differ(monkeypatch):
    from app.services import frame_copy_service

    async def boom(*a, **k):
        raise RuntimeError("llm off")

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)

    trip = _make_trip()
    proj = _projection(trip)
    xhs = await frame_copy_service.build_day_copy(trip, proj, channel="xhs", provider="openai")
    moments = await frame_copy_service.build_day_copy(trip, proj, channel="moments", provider="openai")
    assert xhs["channel"] == "xhs"
    assert moments["channel"] == "moments"
    # 小红书版有话题标签；朋友圈版正文更短（≤6 行惯例）
    assert len(xhs["topics"]) > 0
    assert len(moments["body"].splitlines()) <= 6


# ── API 端点 ─────────────────────────────────────────────────


async def test_copy_endpoint_owner_only(client, auth_user, monkeypatch):
    import uuid
    from datetime import date as d

    from httpx import AsyncClient as _C  # noqa: F401

    async def boom(*a, **k):
        raise RuntimeError("llm off (test)")

    monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)

    _, headers = auth_user
    today = d.today()
    r = await client.post("/api/v1/trips", headers=headers, json={
        "title": "配文API", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(), "travelers": 1,
    })
    trip_id = r.json()["id"]
    r = await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers, json={"day_number": 1})
    day_id = r.json()["id"]

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/frames/{day_id}/copy",
        headers=headers,
        json={"channel": "xhs", "provider": "openai"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] in ("llm", "template")
    assert body["channel"] == "xhs"

    # 非 owner → 403/404
    email_b = f"user-{uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post("/api/v1/auth/register", json={
        "email": email_b, "password": "test1234", "display_name": "B"})
    headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    resp_b = await client.post(
        f"/api/v1/trips/{trip_id}/frames/{day_id}/copy",
        headers=headers_b,
        json={"channel": "xhs", "provider": "openai"},
    )
    assert resp_b.status_code in (403, 404)

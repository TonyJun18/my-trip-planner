"""自驾真实路径层（amap_driving）单元测试：真实路径优先 + 熔断 + 降级。

覆盖：
- 配置开关/API key 未启用 → 恒降级（None）
- 高德响应解析（route.paths[0] distance/duration）
- 超长单段经停建议（rest_km / rest_minutes）
- fetch_driving_legs：全部成功（source=amap）/ 单条失败降级 haversine / 熔断
- check_plan_driving_async：amap 路径与 haversine 兜底的报告组装
"""
from __future__ import annotations

from typing import Any

import pytest

from app.common.config import settings
from app.services import amap_driving
from app.services.driving_service import check_plan_driving_async


def _stop(name: str, lat: float, lng: float) -> dict:
    return {"name": name, "type": "attraction", "lat": lat, "lng": lng,
            "estimated_cost": 0, "duration_minutes": 60, "description": ""}


@pytest.fixture(autouse=True)
def _amap_enabled(monkeypatch):
    """默认启用真实路径：DRIVING_ROUTE_SOURCE=amap + 假 key + 清空熔断。"""
    monkeypatch.setattr(settings, "DRIVING_ROUTE_SOURCE", "amap")
    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    amap_driving._reset_breaker_for_tests()
    yield
    amap_driving._reset_breaker_for_tests()


# ── 启用开关 ─────────────────────────────────────────────
def test_disabled_when_source_not_amap(monkeypatch):
    monkeypatch.setattr(settings, "DRIVING_ROUTE_SOURCE", "haversine")
    assert amap_driving._amap_enabled() is False


def test_disabled_without_key(monkeypatch):
    monkeypatch.setattr(settings, "AMAP_API_KEY", None)
    assert amap_driving._amap_enabled() is False


# ── 响应解析 ─────────────────────────────────────────────
def test_parse_leg_normal():
    data = {"route": {"paths": [{"distance": "153000", "duration": "6300", "strategy": "10"}]}}
    leg = amap_driving._parse_leg(data)
    assert leg == {"source": "amap", "distance_km": 153.0, "drive_minutes": 105}


def test_parse_leg_no_path():
    assert amap_driving._parse_leg({"route": {"paths": []}}) is None
    assert amap_driving._parse_leg({}) is None
    assert amap_driving._parse_leg({"route": {"paths": [{"distance": "0", "duration": "0"}]}}) is None


# ── 经停建议 ─────────────────────────────────────────────
def test_rest_suggestion_only_for_long_leg():
    rest = amap_driving._rest_suggestion(130.0, 160)
    assert rest is not None
    assert rest["rest_km"] == 65.0
    assert rest["rest_minutes"] == settings.DRIVING_LEG_REST_MINUTES


def test_rest_suggestion_short_leg_none():
    assert amap_driving._rest_suggestion(30.0, 40) is None
    assert amap_driving._rest_suggestion(100.0, 140) is None  # 未超 2.5h/120km


# ── fetch_driving_legs ───────────────────────────────────
async def test_fetch_legs_all_amap(monkeypatch):
    async def _fake_fetch(origin, dest, *, timeout=None):
        return {"source": "amap", "distance_km": 40.0, "drive_minutes": 50}

    monkeypatch.setattr(amap_driving, "_fetch_leg", _fake_fetch)
    legs = await amap_driving.fetch_driving_legs(
        [_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1), _stop("C", 30.2, 120.2)]
    )
    assert legs is not None
    assert len(legs) == 2
    assert all(l["source"] == "amap" for l in legs)
    assert legs[0]["from"] == "A" and legs[0]["to"] == "B"


async def test_fetch_legs_single_failure_degrades_haversine(monkeypatch):
    calls = {"n": 0}

    async def _fake_fetch(origin, dest, *, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # 第一条失败 → 该 leg 降级
        return {"source": "amap", "distance_km": 40.0, "drive_minutes": 50}

    monkeypatch.setattr(amap_driving, "_fetch_leg", _fake_fetch)
    legs = await amap_driving.fetch_driving_legs(
        [_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1), _stop("C", 30.2, 120.2)]
    )
    assert legs is not None
    assert legs[0]["source"] == "haversine"  # 降级
    assert legs[1]["source"] == "amap"
    # 未达熔断阈值（threshold 默认 3）
    assert amap_driving._amap_failures == 0  # record_success 已清零


async def test_fetch_legs_breaker_after_threshold(monkeypatch):
    async def _fake_fetch(origin, dest, *, timeout=None):
        return None  # 全部失败

    monkeypatch.setattr(amap_driving, "_fetch_leg", _fake_fetch)
    stops = [_stop(f"S{i}", 30.0 + i * 0.1, 120.0) for i in range(5)]
    legs = await amap_driving.fetch_driving_legs(stops)
    # 4 条 leg 全部失败 → 达到阈值 3 → 熔断打开
    assert legs is not None
    assert all(l["source"] == "haversine" for l in legs)
    assert amap_driving._amap_failures >= settings.DRIVING_ROUTE_BREAKER_THRESHOLD
    # 熔断后下一次调用直接返回 None（恒降级）
    assert await amap_driving.fetch_driving_legs(stops) is None


async def test_fetch_legs_disabled_returns_none():
    from app.common.config import settings as st

    st.DRIVING_ROUTE_SOURCE = "haversine"  # type: ignore[assignment]
    try:
        assert await amap_driving.fetch_driving_legs([_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1)]) is None
    finally:
        st.DRIVING_ROUTE_SOURCE = "amap"  # type: ignore[assignment]


# ── check_plan_driving_async：amap 路径 ──────────────────
async def test_check_plan_driving_async_uses_amap(monkeypatch):
    async def _fake_fetch(stops):
        return [
            {"from": "A", "to": "B", "distance_km": 40.0, "drive_minutes": 50, "source": "amap"},
        ]

    monkeypatch.setattr(amap_driving, "fetch_driving_legs", _fake_fetch)
    plan = {"days": [{"day_number": 1, "stops": [_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1)]}]}
    report = await check_plan_driving_async(plan)
    assert report["passed"] is True
    assert report["source"] == "amap"
    assert report["per_day"][0]["legs"][0]["source"] == "amap"


async def test_check_plan_driving_async_rest_suggestion_in_issue(monkeypatch):
    async def _fake_fetch(stops):
        return [{
            "from": "A", "to": "B",
            "distance_km": 180.0, "drive_minutes": 200, "source": "amap",
            "rest_km": 90.0, "rest_minutes": 45,
        }]

    monkeypatch.setattr(amap_driving, "fetch_driving_legs", _fake_fetch)
    plan = {"days": [{"day_number": 1, "stops": [_stop("A", 30.0, 120.0), _stop("B", 31.2, 121.5)]}]}
    report = await check_plan_driving_async(plan)
    assert report["passed"] is False
    issue = report["issues"][0]
    assert "经停" in issue["suggestion"]
    assert "90" in issue["suggestion"]  # rest_km 出现在建议里


async def test_check_plan_driving_async_fallback_haversine(monkeypatch):
    async def _fake_fetch(stops):
        return None  # 未启用/熔断

    monkeypatch.setattr(amap_driving, "fetch_driving_legs", _fake_fetch)
    plan = {"days": [{"day_number": 1, "stops": [_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1)]}]}
    report = await check_plan_driving_async(plan)
    assert report["source"] == "haversine"
    assert report["per_day"][0]["source"] == "haversine"
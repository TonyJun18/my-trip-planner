"""天气卡降水概率透出测试（task-weather-probability-card，2026-11-12）。

背景（2026-11-11 task-weather-probability-eval 一手实测）：
- 高德 AMAP v3 weatherInfo casts 字段表**无概率/降水毫米字段**（仅 date/
  dayweather/nightweather/daytemp/nighttemp/daywind/nightwind/daypower/
  nightpower/humidity）——「高德含降水概率」立项假设不成立；
- wttr.in j1 hourly 每 3 小时一条，含 chanceofrain（11-11 实测 24 个）——
  降级源**有概率信号**（小时粒度）；
- 任务原文：wttr 源把当天 max(chanceofrain) 如实展示到行中天气卡
  （basis=weather_forecast 标注；高德源无概率字段不展示不编造）。

实现（task-weather-probability-card）：
1. ``_weather_wttr``：对每小时 chanceofrain 取当天最大值 → ``rain_probability``
   （字段缺失/非法 → None，诚实沉默）；``_weather_amap`` 显式置 None（schema 一致）；
2. ``weather_card``：把 ``rain_probability`` 如实透出；前端据此渲染
   （None 不渲染概率）。

覆盖：
- _weather_wttr：chanceofrain 取 max / 部分缺失跳过 / 全缺失 None / 字符串数字。
- _weather_amap：显式 None（source=amap）。
- weather_card：wttr 有概率透出 / 高德 None 透出 / plan 无 weather → None。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools import _weather_amap, _weather_wttr
from app.services.weather_validation import weather_card


# ── 1. _weather_wttr：chanceofrain 聚合 ─────────────────────────
class _FakeResp:
    """最小 httpx.Response 替身（只暴露 .json()）。"""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        pass


def _wttr_payload(days: list[dict[str, Any]]) -> dict[str, Any]:
    return {"current_condition": [], "nearest_area": [], "request": [], "weather": days}


def _hour(time: str, chanceofrain: Any = None) -> dict[str, Any]:
    h: dict[str, Any] = {"time": time, "humidity": "70"}
    if chanceofrain is not None:
        h["chanceofrain"] = chanceofrain
    return h


def _wttr_day(date: str, hours: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "date": date,
        "maxtempC": "18",
        "mintempC": "12",
        "hourly": hours,
    }


@pytest.mark.asyncio
async def test_wttr_rain_probability_takes_max(monkeypatch):
    """chanceofrain 取当天最大值（含高低起伏的小时序列）。"""
    import httpx

    payload = _wttr_payload([
        _wttr_day("2026-11-12", [
            _hour("0", "10"), _hour("300", "20"), _hour("600", "80"),
            _hour("900", "35"), _hour("1200", "13"), _hour("1500", "6"),
        ]),
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["rain_probability"] == 80


@pytest.mark.asyncio
async def test_wttr_rain_probability_skips_missing_and_bad(monkeypatch):
    """部分小时缺 chanceofrain / 非法值 → 跳过；仍有合法值 → 正常返回。"""
    import httpx

    payload = _wttr_payload([
        _wttr_day("2026-11-12", [
            _hour("0", None), _hour("300", "abc"), _hour("600"), _hour("900", "45"),
        ]),
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["rain_probability"] == 45


@pytest.mark.asyncio
async def test_wttr_rain_probability_none_when_all_missing(monkeypatch):
    """所有小时都无合法 chanceofrain → None（诚实沉默，绝不编造）。"""
    import httpx

    payload = _wttr_payload([
        _wttr_day("2026-11-12", [_hour("0"), _hour("300", "bad"), _hour("600", None)]),
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["rain_probability"] is None


@pytest.mark.asyncio
async def test_wttr_rain_probability_none_when_no_hourly(monkeypatch):
    """无 hourly → None（不 IndexError，不编造）。"""
    import httpx

    payload = _wttr_payload([
        {"date": "2026-11-12", "maxtempC": "18", "mintempC": "12"},
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["rain_probability"] is None


# ── 2. _weather_amap：显式 None（数据源无概率字段） ──────────────
@pytest.mark.asyncio
async def test_amap_rain_probability_explicit_none(monkeypatch):
    """高德源无概率字段 → rain_probability 显式 None（schema 一致）。"""
    import httpx

    district = {"status": "1", "districts": [{"adcode": "330100"}]}
    weather = {
        "status": "1",
        "forecasts": [{
            "casts": [{"date": "2026-11-12", "dayweather": "晴", "nightweather": "多云",
                       "daytemp": "18", "nighttemp": "12", "humidity": "60"}],
        }],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        if "config/district" in str(url):
            return _FakeResp(district)
        return _FakeResp(weather)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    # 需要 key；打桩 settings（参考 price-realism 先例——此处直接伪造配置）
    from app.common.config import settings as _settings

    _orig_key = _settings.AMAP_API_KEY
    _settings.AMAP_API_KEY = "fake-key-for-test"
    try:
        result = await _weather_amap("Hangzhou", days=1)
    finally:
        _settings.AMAP_API_KEY = _orig_key
    assert result["source"] == "amap"
    assert result["days"][0]["rain_probability"] is None
    assert result["days"][0]["text_day"] == "晴"


# ── 3. weather_card：概率透出（None 不渲染） ────────────────────
def _weather(days: list[dict[str, Any]], source: str = "wttr.in") -> dict[str, Any]:
    return {"city": "Hangzhou", "days": days, "count": len(days), "source": source}


def _plan(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"destination": "Hangzhou", "days": []}
    base.update(kw)
    return base


def test_weather_card_passes_rain_probability():
    """wttr 源有概率 → weather_card 原样透出。"""
    plan = _plan(weather=_weather([
        {"date": "2026-11-12", "text_day": "Patchy rain nearby",
         "temp_max": "16", "temp_min": "12", "rain_probability": 80},
    ]))
    card = weather_card(plan, day_date="2026-11-12")
    assert card is not None
    assert card["rain_probability"] == 80


def test_weather_card_amap_no_probability_none():
    """高德源无概率字段 → rain_probability 为 None（前端不渲染）。"""
    plan = _plan(weather=_weather([
        {"date": "2026-11-12", "text_day": "晴",
         "temp_max": "18", "temp_min": "12", "rain_probability": None},
    ], source="amap"))
    card = weather_card(plan, day_date="2026-11-12")
    assert card is not None
    assert card["rain_probability"] is None
    assert card["source"] == "amap"


def test_weather_card_normal_fields_unchanged():
    """既有字段（温度/文本/来源）不受概率字段影响。"""
    plan = _plan(weather=_weather([
        {"date": "2026-11-12", "text_day": "多云",
         "temp_max": "20", "temp_min": "15", "rain_probability": 30},
    ]))
    card = weather_card(plan, day_date="2026-11-12")
    assert card is not None
    assert card["text_day"] == "多云"
    assert card["temp_max"] == "20"
    assert card["temp_min"] == "15"
    assert card["rain_probability"] == 30
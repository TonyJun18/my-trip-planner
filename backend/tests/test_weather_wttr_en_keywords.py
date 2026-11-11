"""wttr.in 降级路径英文雨天关键词修复测试（task-weather-wttr-en-keywords，2026-11-12）。

背景（2026-11-11 task-weather-probability-eval 一手实测）：
- wttr.in 带 lang=zh 时返回的 hourly[i].lang_zh 实际是 **英文** 描述，
  且是 ``[{"value": "..."}]`` 列表（不是字符串）；
- lang_en 恒为 null，英文描述实际在 hourly[i].weatherDesc[0].value。
- 旧 `_weather_wttr` 把整个列表塞进 text_day（字符串化 "['Smoke']"），
  weather_validation RAIN_KEYWORDS 仅中文 → wttr 降级路径雨天漏报。

修复：
1. `_weather_wttr` 解包 lang_zh[0].value，空则回退 weatherDesc[0].value，
   保证 text_day 永远是 str|None（绝不把列表/空串塞进 text_day）；
2. `RAIN_KEYWORDS` 补英文降水词（rain/snow/thunder/drizzle/shower/sleet/hail），
   wttr 文本（Patchy rain nearby / Light rain / Thunderstorm）可命中雨天告警。

覆盖：
- _weather_wttr：真实 wttr j1 结构（lang_zh 列表）→ text_day 为字符串；
  lang_zh 缺失 → 回退 weatherDesc；hourly 不足 5 段 → 用首段；空 → None。
- check_plan_weather_gate：英文 text_day（rain/thunder/snow/drizzle）→ 雨天提示；
  非降水英文文本（Sunny/Clear/Overcast/Partly Cloudy/Mist/Smoke）→ 不误报；
  中文路径回归（小雨）→ 仍命中。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools import _weather_wttr
from app.services.weather_validation import RAIN_KEYWORDS, check_plan_weather_gate


# ── 1. _weather_wttr 提取逻辑（httpx.AsyncClient.get 打桩，复刻 price-realism 手法）──
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


def _wttr_day(date: str, *, lang_zh: Any = None, weather_desc: Any = None) -> dict[str, Any]:
    return {
        "date": date,
        "maxtempC": "18",
        "mintempC": "12",
        "hourly": [
            {"time": "0", "humidity": "80", "lang_zh": lang_zh, "weatherDesc": weather_desc},
            {"time": "300", "humidity": "81", "lang_zh": lang_zh, "weatherDesc": weather_desc},
            {"time": "600", "humidity": "82", "lang_zh": lang_zh, "weatherDesc": weather_desc},
            {"time": "900", "humidity": "83", "lang_zh": lang_zh, "weatherDesc": weather_desc},
            {"time": "1200", "humidity": "84", "lang_zh": lang_zh, "weatherDesc": weather_desc},
        ],
    }


@pytest.mark.asyncio
async def test_wttr_unpacks_lang_zh_list(monkeypatch):
    """lang_zh 为 [{'value': 'Patchy rain nearby'}]（11-11 实测结构）→ text_day 是字符串。"""
    import httpx

    payload = _wttr_payload([
        _wttr_day("2026-11-12", lang_zh=[{"value": "Patchy rain nearby"}],
                  weather_desc=[{"value": "Patchy rain nearby"}]),
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["source"] == "wttr.in"
    assert result["count"] == 1
    td = result["days"][0]["text_day"]
    assert isinstance(td, str)
    assert td == "Patchy rain nearby"
    assert result["days"][0]["date"] == "2026-11-12"


@pytest.mark.asyncio
async def test_wttr_falls_back_to_weather_desc(monkeypatch):
    """lang_zh 缺失/为空 → 回退 weatherDesc[0].value（英文描述）。"""
    import httpx

    payload = _wttr_payload([
        _wttr_day("2026-11-13", lang_zh=[], weather_desc=[{"value": "Light rain"}]),
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["text_day"] == "Light rain"


@pytest.mark.asyncio
async def test_wttr_short_hourly_uses_first(monkeypatch):
    """hourly 不足 5 段（len<=4）→ 取首段，不 IndexError；无 hourly → text_day None。"""
    import httpx

    payload = _wttr_payload([
        {
            "date": "2026-11-14",
            "maxtempC": "20",
            "mintempC": "15",
            "hourly": [
                {"time": "0", "humidity": "70",
                 "lang_zh": [{"value": "Sunny"}], "weatherDesc": [{"value": "Sunny"}]},
            ],
        },
    ])

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["text_day"] == "Sunny"

    payload_none = _wttr_payload([{"date": "2026-11-15", "maxtempC": "20", "mintempC": "15"}])

    async def _fake_get_none(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload_none)

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get_none)
    result = await _weather_wttr("Hangzhou", days=1)
    assert result["days"][0]["text_day"] is None


# ── 2. RAIN_KEYWORDS 英文词（wttr 降级路径命中）────────────────
def _stop(name: str, stop_type: str = "attraction", **kw: Any) -> dict[str, Any]:
    return {"name": name, "stop_type": stop_type, **kw}


def _day(day_number: int, *stops: dict[str, Any], date: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"day_number": day_number, "stops": list(stops)}
    if date:
        d["date"] = date
    return d


def _weather(days: list[dict[str, Any]], source: str = "wttr.in") -> dict[str, Any]:
    return {"city": "Hangzhou", "days": days, "count": len(days), "source": source}


def _plan(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"destination": "Hangzhou", "days": []}
    base.update(kw)
    return base


@pytest.mark.parametrize("text_day", [
    "Patchy rain nearby",
    "Light rain",
    "Heavy rain",
    "Thunderstorm",
    "Light snow",
    "Drizzle",
    "Rain Shower",
])
def test_en_rain_keywords_trigger_warning(text_day: str):
    """英文降水文本 → 户外站点雨天室内替代提示。"""
    plan = _plan(
        weather=_weather([{"date": "2026-11-12", "text_day": text_day, "temp_max": "16"}]),
        days=[_day(1, _stop("West Lake"), date="2026-11-12")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is False, f"英文雨天文本 {text_day!r} 应命中雨天提示"
    assert result["issues"], "应产生 warning issue"
    assert "West Lake" in result["issues"][0]["message"]
    assert result["issues"][0]["severity"] == "warning"


@pytest.mark.parametrize("text_day", [
    "Sunny",
    "Clear",
    "Overcast",
    "Partly Cloudy",
    "Mist",
    "Smoke",
    "Smoky haze",
    "Cloudy",
])
def test_en_non_rain_text_no_false_positive(text_day: str):
    """非降水英文文本 → 不误报。"""
    plan = _plan(
        weather=_weather([{"date": "2026-11-12", "text_day": text_day, "temp_max": "22"}]),
        days=[_day(1, _stop("West Lake"), date="2026-11-12")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


def test_zh_rain_regression():
    """中文雨天路径回归：小雨 → 仍命中。"""
    plan = _plan(
        weather=_weather([{"date": "2026-11-12", "text_day": "小雨", "temp_max": "16"}]),
        days=[_day(1, _stop("西湖"), date="2026-11-12")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is False
    assert any("雨" in i["message"] for i in result["issues"])


def test_en_keywords_present():
    """英文降水词必须在 RAIN_KEYWORDS 中（防未来误删）。"""
    for kw in ("rain", "snow", "thunder", "drizzle", "shower"):
        assert kw in RAIN_KEYWORDS
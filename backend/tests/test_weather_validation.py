"""WeatherGate 天气感知排程校验测试（task-weather-gate-eval，2026-11-09）。

覆盖：
1. 纯函数校验：
   - 雨天（text_day 含雨）→ 户外站点提示室内替代 + suggestion
   - 酷暑（temp_max ≥ 35）→ 高温提示
   - 无对应日期天气数据 → 保持沉默（绝不编造）
   - 室内豁免（名称含 博物馆/商场 等）→ 雨天不重复提醒
   - 非雨天/非酷暑 → passed
   - weather 缺失 / days 空 → passed（绝不误报）
2. FinalizePlanStep 编排接线：
   - run_finalize_stage(plan, req, w_res=...) 后 plan.weather_gate 存在 + basis
   - plan.weather 快照回填（供行中天气卡/导出）
   - warnings 注入 [天气] 前缀
3. 行中天气卡：
   - weather_card 纯函数：雨天/酷暑/正常三路径 + 无数据 None
   - live_snapshot 带 weather 卡（有 plan 快照 + 日期匹配）；无 plan → None
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.agent.pipeline import run_finalize_stage
from app.services.weather_validation import (
    HOT_TEMP_THRESHOLD,
    check_plan_weather_gate,
    weather_advice_codes,
    weather_card,
)


def _stop(name: str, stop_type: str = "attraction", **kw: Any) -> dict[str, Any]:
    return {"name": name, "stop_type": stop_type, **kw}


def _day(day_number: int, *stops: dict[str, Any], date: str | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {"day_number": day_number, "stops": list(stops)}
    if date:
        d["date"] = date
    return d


def _weather(days: list[dict[str, Any]], source: str = "wttr.in") -> dict[str, Any]:
    return {"city": "杭州", "days": days, "count": len(days), "source": source}


def _plan(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"destination": "杭州", "days": []}
    base.update(kw)
    return base


# ── 1. 雨天：户外站点 → 室内替代 ──────────────────────────────
def test_rainy_day_warns_outdoor():
    plan = _plan(
        weather=_weather([
            {"date": "2026-11-10", "text_day": "小雨", "temp_max": "18", "temp_min": "12"},
        ]),
        days=[_day(1, _stop("西湖"), date="2026-11-10")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is False
    rain = [i for i in result["issues"] if "雨" in i["message"]]
    assert rain, "雨天应产生提示"
    assert "西湖" in rain[0]["message"]
    assert "室内" in rain[0]["suggestion"]
    assert rain[0]["severity"] == "warning"
    assert rain[0]["category"] == "schedule"
    assert rain[0]["day_number"] == 1
    # 诚实标注：预报非事实 → basis
    assert result["critical_count"] == 0


# ── 雨天豁免：名称含室内关键词 → 不重复提醒 ──
def test_rainy_indoor_stop_exempt():
    plan = _plan(
        weather=_weather([{"date": "2026-11-10", "text_day": "中雨", "temp_max": "16"}]),
        days=[_day(1, _stop("浙江省博物馆"), date="2026-11-10")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 雨天：food/hotel 不参与室内替代提醒 ──
def test_rainy_food_hotel_not_warned():
    plan = _plan(
        weather=_weather([{"date": "2026-11-10", "text_day": "大雨", "temp_max": "15"}]),
        days=[_day(1, _stop("外婆家", stop_type="food"), date="2026-11-10")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is True


# ── 酷暑：temp_max ≥ 阈值 → 高温提示 ──
def test_hot_day_warns():
    plan = _plan(
        weather=_weather([{"date": "2026-07-15", "text_day": "晴", "temp_max": str(HOT_TEMP_THRESHOLD + 1)}]),
        days=[_day(1, _stop("西湖"), date="2026-07-15")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is False
    hot = [i for i in result["issues"] if "酷暑" in i["message"] or "Heat" in i["message"]]
    assert hot, "酷暑应产生提示"
    assert str(HOT_TEMP_THRESHOLD + 1) in hot[0]["message"]


# ── 无对应日期天气数据 → 沉默（绝不编造）─
def test_no_matching_weather_silent():
    plan = _plan(
        weather=_weather([{"date": "2026-11-10", "text_day": "暴雨", "temp_max": "40"}]),
        days=[_day(1, _stop("西湖"), date="2026-11-11")],  # 日期不匹配
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── weather 缺失 -> 沉默 ──
def test_missing_weather_silent():
    plan = _plan(days=[_day(1, _stop("西湖"), date="2026-11-10")])
    result = check_plan_weather_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 正常天气 -> passed ──
def test_normal_weather_passed():
    plan = _plan(
        weather=_weather([{"date": "2026-11-10", "text_day": "晴", "temp_max": "22"}]),
        days=[_day(1, _stop("西湖"), date="2026-11-10")],
    )
    result = check_plan_weather_gate(plan)
    assert result["passed"] is True
    assert result["issues"] == []


# ── 2. FinalizePlanStep 编排接线 ──────────────────────────────
async def test_finalize_injects_weather_gate():
    plan = _plan(
        days=[_day(1, _stop("西湖"), date="2026-11-10")],
    )
    req = {"destination": "杭州", "language": "zh-CN"}
    w_res = {
        "status": "completed",
        "weather": _weather([{"date": "2026-11-10", "text_day": "小雨", "temp_max": "18"}]),
    }
    await run_finalize_stage(plan, req, w_res=w_res)
    assert plan.get("weather") is not None
    assert plan["weather"]["source"] == "wttr.in"
    wg = plan.get("weather_gate")
    assert wg is not None, "run_finalize_stage 必须注入 weather_gate"
    assert wg["basis"] == "weather_forecast"
    assert wg["warning_count"] >= 1
    assert any("雨" in i["message"] for i in wg["issues"])
    # warnings 注入 [天气] 前缀
    assert any("[天气]" in w or "Weather" in w for w in plan.get("warnings", []))


async def test_finalize_weather_gate_passes_when_no_weather():
    plan = _plan(days=[_day(1, _stop("西湖"), date="2026-11-10")])
    req = {"destination": "杭州", "language": "zh-CN"}
    await run_finalize_stage(plan, req)  # 无 w_res -> weather 空
    assert plan.get("weather") == {}
    wg = plan.get("weather_gate")
    assert wg is not None
    assert wg["passed"] is True
    assert wg["issues"] == []


# ── 3. 行中天气卡 ─────────────────────────────────────────────
def test_weather_card_rain():
    plan = _plan(
        weather=_weather([{"date": "2026-11-10", "text_day": "阵雨", "temp_max": "17"}]),
    )
    card = weather_card(plan, day_date="2026-11-10")
    assert card is not None
    assert card["text_day"] == "阵雨"
    assert "降水" in card["summary"]
    assert card["source"] == "wttr.in"


def test_weather_card_hot():
    plan = _plan(
        weather=_weather([{"date": "2026-07-15", "text_day": "晴", "temp_max": str(HOT_TEMP_THRESHOLD + 2)}]),
    )
    card = weather_card(plan, day_date="2026-07-15")
    assert card is not None
    assert "酷暑" in card["summary"] or "Heat" in card["summary"]


def test_weather_card_normal():
    plan = _plan(weather=_weather([{"date": "2026-11-10", "text_day": "多云", "temp_max": "20"}]))
    card = weather_card(plan, day_date="2026-11-10")
    assert card is not None
    assert "多云" in card["summary"]


def test_weather_card_no_data_none():
    assert weather_card(_plan(), day_date="2026-11-10") is None
    assert weather_card(_plan(weather=[]), day_date="2026-11-10") is None


# ── 行动建议代码（前端按 locale 渲染文案；后端只给代码） ──────────
def test_advice_codes_rain():
    plan = _plan(weather=_weather([
        {"date": "2026-11-10", "text_day": "小雨", "temp_max": "18"},
    ]))
    assert weather_advice_codes(plan, day_date="2026-11-10") == ["rain"]


def test_advice_codes_hot():
    plan = _plan(weather=_weather([
        {"date": "2026-07-15", "text_day": "晴", "temp_max": str(HOT_TEMP_THRESHOLD + 1)},
    ]))
    assert weather_advice_codes(plan, day_date="2026-07-15") == ["hot"]


def test_advice_codes_rain_and_hot():
    plan = _plan(weather=_weather([
        {"date": "2026-07-15", "text_day": "雷阵雨", "temp_max": str(HOT_TEMP_THRESHOLD + 2)},
    ]))
    assert weather_advice_codes(plan, day_date="2026-07-15") == ["rain", "hot"]


def test_advice_codes_silent_without_data():
    """无天气数据 / 无匹配日期 → 空列表（保持沉默，绝不编造）。"""
    assert weather_advice_codes(_plan(), day_date="2026-11-10") == []
    assert weather_advice_codes(_plan(weather=[]), day_date="2026-11-10") == []
    plan = _plan(weather=_weather([
        {"date": "2026-11-10", "text_day": "小雨", "temp_max": "18"},
    ]))
    assert weather_advice_codes(plan, day_date="2026-11-11") == []


def test_advice_codes_normal_day_empty():
    plan = _plan(weather=_weather([
        {"date": "2026-11-10", "text_day": "晴", "temp_max": "24"},
    ]))
    assert weather_advice_codes(plan, day_date="2026-11-10") == []


# ── live_snapshot 天气卡集成（ORM 冒烟；纯逻辑已在上面覆盖）──
async def test_live_snapshot_weather_card(db_session):
    """行程在 live 且 plan 快照含 weather → live_snapshot.weather 非 None。"""
    from app.models import Stop, Trip, TripDay, TripPlan

    today = date(2026, 11, 10)
    trip = Trip(owner="u-wx", title="天气卡测试", destination="杭州",
                start_date=today, end_date=today)
    day = TripDay(day_number=1, date=today)
    day.stops.append(Stop(name="西湖", stop_type="attraction", order_index=1, checked=False))
    trip.days.append(day)
    trip.plans.append(TripPlan(
        plan_data=_plan(
            weather=_weather([{"date": "2026-11-10", "text_day": "小雨", "temp_max": "16"}]),
            days=[_day(1, _stop("西湖", date="2026-11-10"))],
        ),
        status="completed",
    ))
    db_session.add(trip)
    await db_session.flush()

    from app.services.live_service import live_snapshot

    snap = live_snapshot(trip, today=today)
    assert snap["phase"] == "live"
    assert snap["weather"] is not None
    assert snap["weather"]["text_day"] == "小雨"
    assert "降水" in snap["weather"]["summary"]
    # 行动建议以代码形式透出（文案由前端 i18n 渲染）
    assert snap["weather"]["advice"] == ["rain"]


async def test_live_snapshot_no_plan_weather_none(db_session):
    """行程在 live 但无 AI 方案（无 weather 数据）→ weather=None（绝不伪造）。"""
    from app.models import Trip, TripDay

    today = date(2026, 11, 10)
    trip = Trip(owner="u-wx2", title="无天气卡", destination="杭州",
                start_date=today, end_date=today)
    # 显式初始化 relationship（避免 async 懒加载 MissingGreenlet；
    # 真实 API 路径由 TRIP_LOADS eager-load，此处模拟空集合语义）
    day = TripDay(day_number=1, date=today)
    day.stops = []
    trip.days.append(day)
    trip.plans = []
    db_session.add(trip)
    await db_session.flush()

    from app.services.live_service import live_snapshot

    snap = live_snapshot(trip, today=today)
    assert snap["phase"] == "live"
    assert snap["weather"] is None


async def test_live_snapshot_upcoming_weather_none():
    """非 live（upcoming）→ weather=None。"""
    from app.models import Trip

    today = date(2026, 11, 10)
    trip = Trip(owner="u-wx3", title="未开始", destination="杭州",
                start_date=today + timedelta(days=5), end_date=today + timedelta(days=6))

    from app.services.live_service import live_snapshot

    snap = live_snapshot(trip, today=today)
    assert snap["phase"] == "upcoming"
    assert snap["weather"] is None
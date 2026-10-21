"""多城市衔接测试（task-multi-city-segments）：分段 / 占位 / 衔接冲突三路径。"""
from __future__ import annotations

from app.services.multi_city import (
    FALLBACK_TRANSFER_MINUTES,
    TRANSFER_BUFFER_MINUTES,
    apply_multi_city,
)


def _stop(name, lat=None, lng=None, visit_start=None, duration=120):
    s = {"name": name, "stop_type": "attraction", "estimated_duration_minutes": duration}
    if lat is not None:
        s["lat"] = lat
    if lng is not None:
        s["lng"] = lng
    if visit_start:
        s["visit_start"] = visit_start
    return s


def _day(n, *stops):
    return {"day_number": n, "stops": list(stops)}


def _plan(*days):
    return {"days": list(days)}


# ── 多段：2 城市 4 天 → 2 段，第 3 天插入交通占位 ──
def test_multi_city_splits_and_inserts_transfer():
    plan = _plan(
        _day(1, _stop("故宫", 39.916, 116.397, "09:00")),
        _day(2, _stop("颐和园", 39.999, 116.275, "09:00")),
        _day(3, _stop("外滩", 31.240, 121.490, "14:00")),
        _day(4, _stop("豫园", 31.227, 121.492, "09:00")),
    )
    result = apply_multi_city(plan, ["北京", "上海"])

    assert result["enabled"] is True
    assert len(result["segments"]) == 2
    assert result["segments"][0]["city"] == "北京"
    assert result["segments"][0]["day_numbers"] == [1, 2]
    assert result["segments"][1]["city"] == "上海"
    assert result["segments"][1]["day_numbers"] == [3, 4]

    # 每天打上 city 归属
    assert plan["days"][0]["city"] == "北京"
    assert plan["days"][2]["city"] == "上海"

    # 段间交通占位插入第 3 天首位
    day3 = plan["days"][2]
    transfer = day3["stops"][0]
    assert transfer.get("is_transfer") is True
    assert "上海" in transfer["name"]
    assert transfer["stop_type"] == "attraction"
    # 北京→上海 ≈ 1060km / 50kmh ≈ 1270 分钟
    assert transfer["estimated_duration_minutes"] > 600

    # 第 3 天首站 14:00 开始，到港约 09:00+1270min（次日凌晨）→ 缓冲不足 → warning
    assert result["passed"] is False
    assert result["warning_count"] >= 1
    assert any("上海" in i["message"] for i in result["issues"])
    assert result["issues"][0]["severity"] == "warning"
    assert result["issues"][0]["category"] == "logistics"


# ── 单段：只有 1 个城市 → 不启用、不改动 ──
def test_single_city_no_segments():
    plan = _plan(
        _day(1, _stop("西湖", 30.24, 120.15, "09:00")),
        _day(2, _stop("灵隐寺", 30.24, 120.10, "09:00")),
    )
    result = apply_multi_city(plan, ["杭州"])
    assert result["enabled"] is False
    assert result["passed"] is True
    assert result["issues"] == []
    # 未改动 plan
    assert "city" not in plan["days"][0]
    assert len(plan["days"][0]["stops"]) == 1


# ── 衔接冲突：到港晚于首站开始（同城短途也应留缓冲）──
def test_tight_connection_warns():
    plan = _plan(
        _day(1, _stop("A点", 31.0, 121.0, "09:00")),
        _day(2, _stop("B点", 31.5, 121.6, "09:10")),  # 跨城 ~75km ≈ 90min 车程，09:00 出发 10:30 到
        _day(3, _stop("C点", 31.5, 121.6, "09:00")),
    )
    result = apply_multi_city(plan, ["甲城", "乙城"])
    assert result["enabled"] is True
    # 第 2 天是乙城首日：09:00 出发 + 90min ≈ 10:30 到港，首站 09:10 开始 → 冲突
    assert result["passed"] is False
    assert any("乙城" in i["message"] for i in result["issues"])
    assert str(TRANSFER_BUFFER_MINUTES) in result["issues"][0]["message"]


# ── 无坐标：兜底 3 小时，仍可插入占位并校验 ──
def test_no_coords_fallback():
    plan = _plan(
        _day(1, _stop("无坐标景点")),
        _day(2, _stop("另一个景点", visit_start="09:30")),
    )
    result = apply_multi_city(plan, ["甲城", "乙城"])
    transfer = plan["days"][1]["stops"][0]
    assert transfer["estimated_duration_minutes"] == FALLBACK_TRANSFER_MINUTES
    assert result["passed"] is False  # 09:00+180=12:00 到港 > 09:30 首站


# ── 城市数 > 天数：只分配有天的段，不崩 ──
def test_more_cities_than_days():
    plan = _plan(_day(1, _stop("A点", 31.0, 121.0, "09:00")))
    result = apply_multi_city(plan, ["甲城", "乙城", "丙城"])
    assert result["enabled"] is False  # 只有 1 天 < 2 天 → 不启用
    assert result["passed"] is True


# ── 空行程 / 空城市：边界不崩 ──
def test_empty_inputs():
    assert apply_multi_city({}, ["甲城", "乙城"])["enabled"] is False
    assert apply_multi_city(_plan(_day(1)), [])["enabled"] is False
    assert apply_multi_city(_plan(_day(1), _day(2)), ["甲城"])["enabled"] is False
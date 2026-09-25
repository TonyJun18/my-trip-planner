"""酒店价格估算（task-hotel-budget）单元测试：estimate_hotel_cost 确定性计算。"""
from __future__ import annotations

from app.services.budget_service import estimate_hotel_cost


def test_hotel_known_city_base():
    """已知城市 + 无档位关键词 → 城市基准价。"""
    assert estimate_hotel_cost("某某大酒店", city="杭州") == 430.0


def test_hotel_unknown_city_fallback():
    """未知城市 → 全国兜底 380。"""
    assert estimate_hotel_cost("某某大酒店", city="爱丁堡") == 380.0


def test_hotel_tier_multiplier():
    """档位关键词 → 基准价 × 倍率（经济 0.7 / 五星 2.8 / 青旅 0.55）。"""
    assert estimate_hotel_cost("杭州经济型酒店", city="杭州") == round(430 * 0.7, 2)
    assert estimate_hotel_cost("杭州五星大酒店", city="杭州") == round(430 * 2.8, 2)
    assert estimate_hotel_cost("杭州国际青旅", city="杭州") == round(430 * 2.2, 2)  # 先命中「国际」


def test_hotel_rating_correction():
    """评分修正：≥4.5 上浮 15%，≤3.5 下浮 15%。"""
    base = 430.0
    assert estimate_hotel_cost("杭州某酒店", city="杭州", rating=4.8) == round(base * 1.15, 2)
    assert estimate_hotel_cost("杭州某酒店", city="杭州", rating=3.2) == round(base * 0.85, 2)
    assert estimate_hotel_cost("杭州某酒店", city="杭州", rating=4.0) == base


def test_hotel_empty_name():
    """空名称 → 兜底 380。"""
    assert estimate_hotel_cost("", city="杭州") == 380.0
    assert estimate_hotel_cost(None) == 380.0


def test_hotel_city_suffix_match():
    """城市后缀/前缀兼容（'杭州市'、'浙江杭州'）。"""
    assert estimate_hotel_cost("某某酒店", city="杭州市") == 430.0
    assert estimate_hotel_cost("某某酒店", city="浙江杭州") == 430.0


# ── compute_budget：口径标注（09-26 竞品分析补充验收） ──────────────
def _fake_trip(*, stops: list[dict], destination: str = "杭州"):
    """构造带 trip/days/stops 的最小对象（不落库，供纯逻辑测试）。"""
    from datetime import date

    from app.models import Stop, Trip, TripDay

    trip = Trip(
        id="t1",
        destination=destination,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 3),
    )
    day = TripDay(id="d1", trip_id="t1", day_number=1)
    trip.days = [day]
    day.stops = [Stop(id=f"s{i}", day_id="d1", **s) for i, s in enumerate(stops, start=1)]
    return trip


def test_compute_budget_hotel_nonzero_and_basis():
    """酒店站点 → hotel 预算非 0（不再是空壳）+ estimate_basis 口径标注。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "杭州西湖", "stop_type": "attraction", "estimated_cost": 0.0},
            {
                "name": "杭州经济型酒店",
                "stop_type": "hotel",
                "estimated_cost": estimate_hotel_cost("杭州经济型酒店", city="杭州"),
            },
        ]
    )
    budget = compute_budget(trip)
    assert budget["by_type"]["hotel"] > 0
    assert budget["total_estimated"] == budget["by_type"]["hotel"]
    basis = budget["estimate_basis"]["hotel"]
    assert basis["source"] == "city_base_2024"
    assert basis["confidence"] == "medium"
    assert basis["estimated_count"] == 1
    assert basis["base_note"]


def test_compute_budget_no_hotel_no_basis():
    """无酒店站点 → 不输出 estimate_basis（避免无意义标注）。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 120.0},
        ]
    )
    budget = compute_budget(trip)
    assert "estimate_basis" not in budget
    assert budget["by_type"]["hotel"] == 0.0
    assert budget["total_estimated"] == 170.0


def test_hotel_estimate_basis_counts():
    """口径标注统计多酒店站点。"""
    from app.services.budget_service import hotel_estimate_basis

    basis = hotel_estimate_basis(3)
    assert basis["estimated_count"] == 3
    assert basis["actual_count"] == 0
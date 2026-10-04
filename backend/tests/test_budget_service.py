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


# ── 预算人均分摊（task-budget-split：AiGo/Wanderlog 多人出行刚需） ──────
def test_compute_budget_per_person_split():
    """travelers=2：总额、按类、日均均按人数分摊。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 100.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 200.0},
            {"name": "杭州经济型酒店", "stop_type": "hotel", "estimated_cost": 300.0},
        ]
    )
    trip.travelers = 2
    budget = compute_budget(trip)

    assert budget["total_estimated"] == 600.0
    assert budget["per_person_total"] == 300.0
    assert budget["per_person_by_type"]["attraction"] == 50.0
    assert budget["per_person_by_type"]["food"] == 100.0
    assert budget["per_person_by_type"]["hotel"] == 150.0
    # 3 天 → 日均 200，人均日均 100
    assert budget["daily_average"] == 200.0
    assert budget["per_person_daily"] == 100.0


def test_compute_budget_per_person_single_traveler():
    """默认 travelers=1：人均 == 总额（不产生额外分摊）。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 100.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 200.0},
        ]
    )
    budget = compute_budget(trip)

    assert budget["total_estimated"] == 300.0
    assert budget["per_person_total"] == 300.0
    assert budget["per_person_by_type"]["attraction"] == 100.0


def test_compute_budget_zero_total_no_zero_division():
    """总额为 0 时人均为 0（不崩、不除 0）。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(stops=[{"name": "空", "stop_type": "attraction", "estimated_cost": 0.0}])
    trip.travelers = 4
    budget = compute_budget(trip)

    assert budget["total_estimated"] == 0.0
    assert budget["per_person_total"] == 0.0
    assert budget["per_person_daily"] is None


def test_compute_budget_travelers_zero_is_single():
    """travelers 异常（0/缺省）→ 按单人处理，不产除 0 错误。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 100.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 200.0},
        ]
    )
    trip.travelers = None  # 异常数据
    budget = compute_budget(trip)
    assert budget["per_person_total"] == 300.0
    trip2 = _fake_trip(
        stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 100.0}]
    )
    trip2.travelers = 0
    b2 = compute_budget(trip2)
    assert b2["per_person_total"] == 100.0


# ── 大交通往返预算（task: 详情页预算口径） ─────────────────────
def _plan_with_transport(price_range: list[float] | None) -> dict:
    return {
        "transport": {
            "from": "上海",
            "to": "杭州",
            "options": [
                {
                    "mode": "train",
                    "duration_minutes": 60,
                    "price_range": price_range,
                    "confidence": 0.7,
                    "source": "tavily",
                }
            ],
        }
    }


def test_compute_budget_includes_transport_round_trip():
    """plan_data.transport 有参考价 → by_type.transport = 单程最低 ×2，总额含往返。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 120.0},
        ]
    )
    budget = compute_budget(trip, plan_data=_plan_with_transport([72.5, 118.0]))
    # 单程最低 72.5 ×2 = 145；总额 = 50 + 120 + 145 = 315
    assert budget["by_type"]["transport"] == 145.0
    assert budget["total_estimated"] == 315.0
    assert budget["estimate_basis"]["transport"]["source"] == "transport_agent_collected"


def test_compute_budget_transport_daily_average_excludes_one_off():
    """日均不含一次性往返大交通（大交通不是每天发生），总额含。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 90.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 120.0},
        ]
    )
    budget = compute_budget(trip, plan_data=_plan_with_transport([100.0, 200.0]))
    # 总额 = 90 + 120 + 200 = 410；日均 = (90+120)/3 = 70（不含 200 往返）
    assert budget["total_estimated"] == 410.0
    assert budget["daily_average"] == 70.0
    assert budget["per_person_daily"] == 70.0


def test_compute_budget_transport_missing_price_no_fabrication():
    """transport 无参考价（price_range 缺失）→ 不编造，transport 键不出现。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0}]
    )
    budget = compute_budget(trip, plan_data=_plan_with_transport(None))
    assert "transport" not in budget["by_type"]
    assert budget["total_estimated"] == 50.0
    assert "transport" not in (budget.get("estimate_basis") or {})


def test_compute_budget_transport_plan_data_none():
    """无 plan_data（旧行程/无 AI 方案）→ 与既有行为一致，不报错不加项。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0}]
    )
    budget = compute_budget(trip)  # 不传 plan_data
    assert "transport" not in budget["by_type"]
    assert budget["total_estimated"] == 50.0
"""酒店价格估算（task-hotel-budget）+ 预算全口径（2026-11-14 预算对不上修复）测试。

口径说明（统一 compute_full_budget）：
- 站级兜底：0 价站按类型/关键词参考估算（方案 A）
- 住宿缺口：N 天行程缺失住宿晚数 × 城市基准价（方案 C）
- 大交通：plan_data.transport 单程最低 ×2
- 对账块：planned / gap / daily_needed（方案 C 展示层）
"""
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


# ── compute_budget：全口径（2026-11-14 起：站兜底 + 住宿缺口） ─────────
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
    # 酒店站价格 + 住宿缺口（3 天 1 站 → 补 2 晚）
    assert budget["by_type"]["hotel"] == round(estimate_hotel_cost("杭州经济型酒店", city="杭州") + 430 * 2, 2)
    assert budget["total_estimated"] == budget["by_type"]["hotel"] + budget["by_type"]["attraction"]
    basis = budget["estimate_basis"]["hotel"]
    assert basis["source"] == "city_base_2024"
    assert basis["confidence"] == "medium"
    assert basis["estimated_count"] == 1
    assert basis["base_note"]


def test_compute_budget_no_hotel_no_basis():
    """无酒店站点但补缺口 → 有 hotel basis（住宿缺口也是估算，需标注）。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 120.0},
        ]
    )
    budget = compute_budget(trip)
    assert budget["by_type"]["hotel"] == round(430 * 3, 2)  # 3 天无酒店站 → 补 3 晚
    assert budget["total_estimated"] == round(50 + 120 + 430 * 3, 2)
    assert budget["estimate_basis"]["hotel"]  # 缺口也标注口径


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
    # 3 天 1 酒店站 → 缺口 2 晚 × 430 = 860；站级 100+200+300=600
    hotel = 300 + 860.0
    total = 100 + 200 + hotel
    assert budget["total_estimated"] == total
    assert budget["per_person_total"] == total / 2
    assert budget["per_person_by_type"]["attraction"] == 50.0
    assert budget["per_person_by_type"]["food"] == 100.0
    assert budget["per_person_by_type"]["hotel"] == hotel / 2
    # 3 天 → 日均 = 站级总额 / 3（不含一次性往返）
    assert budget["daily_average"] == round((100 + 200 + hotel) / 3, 2)
    # 人均日均 = round(日均,2) 再 ÷ 人数（与 _per_person_views 实现一致）
    assert budget["per_person_daily"] == round(round((100 + 200 + hotel) / 3, 2) / 2, 2)


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
    total = 100 + 200 + 430 * 3  # 3 天住宿缺口
    assert budget["total_estimated"] == total
    assert budget["per_person_total"] == total


def test_compute_budget_zero_total_no_zero_division():
    """总额非 0（有住宿缺口）时人均正常；无除 0。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(stops=[{"name": "空", "stop_type": "attraction", "estimated_cost": 0.0}])
    trip.travelers = 4
    budget = compute_budget(trip)
    # 0 价景点兜底 25 + 3 晚住宿缺口 1290
    assert budget["total_estimated"] == 25.0 + 430 * 3
    assert budget["per_person_total"] == (25.0 + 430 * 3) / 4


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
    assert budget["per_person_total"] == budget["total_estimated"]
    trip2 = _fake_trip(
        stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 100.0}]
    )
    trip2.travelers = 0
    b2 = compute_budget(trip2)
    assert b2["per_person_total"] == b2["total_estimated"]


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
    # 单程最低 72.5 ×2 = 145；站级 50+120 + 住宿缺口 1290 + 145
    assert budget["by_type"]["transport"] == 145.0
    assert budget["total_estimated"] == round(50 + 120 + 430 * 3 + 145, 2)
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
    # 总额 = 90 + 120 + 1290(住宿) + 200(往返) = 1700；日均 = (90+120+1290)/3 = 500
    assert budget["total_estimated"] == 90 + 120 + 430 * 3 + 200
    assert budget["daily_average"] == (90 + 120 + 430 * 3) / 3


def test_compute_budget_transport_missing_price_no_fabrication():
    """transport 无参考价（price_range 缺失）→ 不编造，transport 键不出现。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0}]
    )
    budget = compute_budget(trip, plan_data=_plan_with_transport(None))
    assert "transport" not in budget["by_type"]
    assert budget["total_estimated"] == 50.0 + 430 * 3
    assert "transport" not in (budget.get("estimate_basis") or {})


def test_compute_budget_transport_plan_data_none():
    """无 plan_data（旧行程/无 AI 方案）→ 与既有行为一致，不报错不加项。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 50.0}]
    )
    budget = compute_budget(trip)  # 不传 plan_data
    assert "transport" not in budget["by_type"]
    assert budget["total_estimated"] == 50.0 + 430 * 3


# ── 方案 A：站级费用兜底估算（2026-11-14 预算对不上修复） ──────────────
def test_estimate_stop_cost_attraction():
    from app.services.budget_service import estimate_stop_cost

    assert estimate_stop_cost("杭州西湖", "attraction") == 25.0  # 湖
    assert estimate_stop_cost("浙江省博物馆", "attraction") == 30.0  # 博物馆
    assert estimate_stop_cost("上海迪士尼乐园", "attraction") == 250.0  # 乐园
    assert estimate_stop_cost("免费公园", "attraction") == 0.0  # 公园免费
    assert estimate_stop_cost("某人气景点", "attraction") == 25.0  # 兜底


def test_estimate_stop_cost_food():
    from app.services.budget_service import estimate_stop_cost

    assert estimate_stop_cost("海底捞火锅", "food") == 130.0
    assert estimate_stop_cost("星巴克咖啡", "food") == 35.0
    assert estimate_stop_cost("路边小馆", "food") == 60.0  # 兜底


def test_estimate_stop_cost_hotel_uses_estimate_hotel_cost():
    from app.services.budget_service import estimate_stop_cost

    assert estimate_stop_cost("杭州经济型酒店", "hotel", city="杭州") == round(430 * 0.7, 2)


def test_fill_stop_estimated_costs_only_missing():
    from app.services.budget_service import fill_stop_estimated_costs

    stops = [
        {"name": "西湖", "type": "attraction", "estimated_cost": 0.0},
        {"name": "楼外楼", "type": "food", "estimated_cost": None},
        {"name": "灵隐寺", "type": "attraction", "estimated_cost": 45.0},  # 真实价保留
    ]
    filled = fill_stop_estimated_costs(stops)
    assert filled == 2
    assert stops[0]["estimated_cost"] == 25.0
    assert stops[0]["estimate_sources"]["estimated_cost"] == "rule_based"
    assert stops[1]["estimated_cost"] == 60.0
    assert stops[2]["estimated_cost"] == 45.0  # 不覆盖真实价
    assert "estimate_sources" not in stops[2]


# ── 方案 C：住宿晚数缺口补齐 + 预算对账块（2026-11-14） ────────────────
def test_missing_hotel_nights_cost():
    from app.services.budget_service import missing_hotel_nights_cost

    trip = _fake_trip(stops=[{"name": "西湖", "stop_type": "attraction", "estimated_cost": 0}])
    # 3 天行程，无酒店站 → 缺口 3 晚 × 杭州基准 430
    assert missing_hotel_nights_cost(trip) == round(430 * 3, 2)


def test_missing_hotel_nights_cost_partial():
    from app.services.budget_service import missing_hotel_nights_cost

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 0},
            {"name": "杭州经济型酒店", "stop_type": "hotel", "estimated_cost": 300.0},
        ]
    )
    # 3 天有 1 个酒店站 → 缺口 2 晚 × 430
    assert missing_hotel_nights_cost(trip) == round(430 * 2, 2)


def test_missing_hotel_nights_cost_covered():
    from app.services.budget_service import missing_hotel_nights_cost

    trip = _fake_trip(
        stops=[{"name": f"酒店{i}", "stop_type": "hotel", "estimated_cost": 300.0} for i in range(3)]
    )
    assert missing_hotel_nights_cost(trip) is None  # 3 酒店站覆盖 3 晚


def test_compute_budget_includes_missing_hotel_nights():
    """方案 C：3 天无酒店站 → hotel 补 3 晚基准价，预算不再偏小。"""
    from app.services.budget_service import compute_budget

    trip = _fake_trip(
        stops=[
            {"name": "西湖", "stop_type": "attraction", "estimated_cost": 0.0},
            {"name": "楼外楼", "stop_type": "food", "estimated_cost": 0.0},
        ]
    )
    trip.budget = 6000.0
    budget = compute_budget(trip)
    # attraction 25 + food 60 + 住宿缺口 3×430
    assert budget["by_type"]["hotel"] == round(430 * 3, 2)
    assert budget["total_estimated"] == round(25 + 60 + 430 * 3, 2)
    assert budget["estimate_basis"]["hotel"]  # 缺口也带口径标注
    # 对账块：planned 6000
    assert budget["reconciliation"]["planned"] == 6000.0
    assert budget["reconciliation"]["status"] == "under"
    assert budget["reconciliation"]["gap"] > 0
    assert budget["reconciliation"]["daily_needed"] is not None
    assert "note" in budget["reconciliation"]


def test_annotate_budget_no_planned():
    """未填预算 → reconciliation.status=none。"""
    from app.services.budget_service import annotate_budget

    out = annotate_budget({"total_estimated": 100.0}, planned=None)
    assert out["reconciliation"]["status"] == "none"
    assert out["reconciliation"]["planned"] is None
    assert out["total_estimated"] == 100.0


# ── 统一口径：tools / plan_b / revise 一致（2026-11-14） ───────────────
def test_tools_compute_budget_same_basis():
    """tools.compute_budget（pipeline/revise 用的纯站级）与 budget_service 兜底同值。"""
    from app.agent.tools import compute_budget as tools_budget

    b = tools_budget(
        [
            {"name": "西湖", "type": "attraction", "estimated_cost": 0.0},
            {"name": "楼外楼", "type": "food", "estimated_cost": 0.0},
        ]
    )
    assert b["total_estimated"] == 25.0 + 60.0
    assert b["by_type"]["attraction"] == 25.0
    assert b["by_type"]["food"] == 60.0


def test_plan_b_sum_budget_same_basis():
    """plan_b 备选预算与主案同口径（0 价站兜底）。"""
    from app.services.plan_b import _sum_budget

    b = _sum_budget(
        [
            {
                "day_number": 1,
                "stops": [
                    {"name": "西湖", "stop_type": "attraction", "estimated_cost": 0.0},
                    {"name": "楼外楼", "stop_type": "food", "estimated_cost": 0.0},
                ],
            }
        ]
    )
    assert b["total_estimated"] == 25.0 + 60.0


# ── compute_full_budget 纯函数（pipeline / 无 ORM 场景） ────────────────
def test_compute_full_budget_pure_dict():
    """纯 dict days（无 ORM）→ 全口径（站兜底 + 住宿缺口 + 对账）。"""
    from app.services.budget_service import compute_full_budget

    budget = compute_full_budget(
        days=[
            {
                "day_number": 1,
                "stops": [
                    {"name": "西湖", "stop_type": "attraction", "estimated_cost": 0.0},
                    {"name": "楼外楼", "stop_type": "food", "estimated_cost": 0.0},
                ],
            }
        ],
        start_date="2026-10-01",
        end_date="2026-10-03",
        destination="杭州",
        travelers=2,
        planned=6000.0,
    )
    assert budget["total_estimated"] == round(25 + 60 + 430 * 3, 2)
    assert budget["reconciliation"]["planned"] == 6000.0
    assert budget["per_person_total"] == round((25 + 60 + 430 * 3) / 2, 2)


def test_compute_full_budget_missing_dates_no_hotel_gap():
    """无日期 → 不补住宿缺口（无法推断晚数），仅站级兜底。"""
    from app.services.budget_service import compute_full_budget

    budget = compute_full_budget(
        days=[
            {
                "day_number": 1,
                "stops": [
                    {"name": "西湖", "stop_type": "attraction", "estimated_cost": 0.0},
                ],
            }
        ],
        destination="杭州",
    )
    assert budget["total_estimated"] == 25.0
    assert budget["by_type"]["hotel"] == 0.0
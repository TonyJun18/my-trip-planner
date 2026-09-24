"""test_plan_b.py —— Plan B 备选方案服务层测试（纯函数，无 DB）。

覆盖三种确定性变体：
- 节奏变体：过满日（>=5 站）把末尾站点移到次日开头
- 预算档变体：有酒店 → 全部酒店 ×0.7 下调，预算重算
- 取舍变体：无过满日、无酒店 → 每天去掉最后 food 站（或时长最短站）
- 边界：空行程 / 单日行程（节奏不可用降级）/ 单站日不移除
"""
from __future__ import annotations

from app.services.plan_b import (
    BUDGET_TIER_MULTIPLIER,
    VARIANT_BUDGET,
    VARIANT_CURATED,
    VARIANT_RELAXED,
    generate_plan_b_variant,
)


def _stop(name, stop_type="attraction", cost=0.0, dur=None):
    return {
        "name": name,
        "stop_type": stop_type,
        "lat": None,
        "lng": None,
        "description": None,
        "estimated_cost": cost,
        "estimated_duration_minutes": dur,
    }


def _day(n, stops):
    return {"day_number": n, "date": f"2026-10-0{n}", "theme": f"Day{n}", "stops": stops}


def test_empty_days_returns_none():
    assert generate_plan_b_variant([]) is None
    assert generate_plan_b_variant([{"day_number": 1, "stops": []}]) is None


def test_relaxed_variant_moves_overfull_tail():
    """过满日（5 站）→ 末尾站点移到次日开头，节奏变体。"""
    days = [
        _day(1, [_stop(f"景点{i}") for i in range(1, 6)]),  # 5 站 → 过满
        _day(2, [_stop("次日首站")]),
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    assert v["label"] == VARIANT_RELAXED
    assert len(v["days"][0]["stops"]) == 4
    assert v["days"][1]["stops"][0]["name"] == "景点5"  # 末尾站点移到次日开头
    assert v["deltas"] and "景点5" in v["deltas"][0]


def test_relaxed_variant_not_applicable_single_day():
    """单日行程 → 节奏不可用，降级预算档（无酒店）→ 取舍。"""
    days = [_day(1, [_stop("景点1"), _stop("景点2"), _stop("餐厅1", "food")])]
    v = generate_plan_b_variant(days)
    assert v is not None
    assert v["label"] == VARIANT_CURATED


def test_budget_variant_lowers_hotel_cost():
    """有酒店且无过满日 → 预算档变体：全部酒店 ×0.7，预算重算。"""
    days = [
        _day(1, [_stop("A", "attraction", cost=100, dur=120), _stop("酒店", "hotel", cost=400, dur=None)]),
        _day(2, [_stop("B", "attraction", cost=50, dur=120)]),
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    assert v["label"] == VARIANT_BUDGET
    hotel = next(s for d in v["days"] for s in d["stops"] if s["stop_type"] == "hotel")
    assert hotel["estimated_cost"] == round(400 * BUDGET_TIER_MULTIPLIER, 2)
    # 预算重算：100 + 280(酒店) + 50 = 430
    assert v["budget"]["total_estimated"] == 430
    assert v["budget"]["by_type"]["hotel"] == 280
    assert any("酒店" in d and "¥400" in d and "¥280" in d for d in v["deltas"])


def test_curated_variant_removes_last_food():
    """无过满日、无酒店 → 取舍变体：每天去掉最后一个 food 站。"""
    days = [
        _day(1, [_stop("景点1"), _stop("餐厅1", "food"), _stop("餐厅2", "food"), _stop("景点2")]),
        _day(2, [_stop("景点3")]),
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    assert v["label"] == VARIANT_CURATED
    names = [s["name"] for s in v["days"][0]["stops"]]
    assert "餐厅2" not in names  # 最后 food 站被去掉
    assert "餐厅1" in names
    assert len(v["days"][1]["stops"]) == 1  # 单站日不移除


def test_curated_variant_removes_shortest_when_no_food():
    """无 food 日 → 去掉该日时长最短的站。"""
    days = [
        _day(1, [_stop("景点1", dur=30), _stop("景点2", dur=120), _stop("景点3", dur=90)]),
        _day(2, [_stop("另一天")]),
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    names = [s["name"] for s in v["days"][0]["stops"]]
    assert "景点1" not in names  # 时长最短
    assert set(names) == {"景点2", "景点3"}


def test_generation_is_deterministic():
    """同一输入 → 同一输出（幂等、确定性）。"""
    days = [
        _day(1, [_stop("A"), _stop("酒店", "hotel", cost=500)]),
        _day(2, [_stop("B", dur=120), _stop("餐厅", "food")]),
    ]
    v1 = generate_plan_b_variant(days)
    v2 = generate_plan_b_variant(days)
    assert v1 == v2


def test_input_not_mutated():
    """生成不修改主案输入（纯函数，副本操作）。"""
    import copy

    days = [
        _day(1, [_stop("A"), _stop("酒店", "hotel", cost=500)]),
        _day(2, [_stop("B", dur=120), _stop("餐厅", "food")]),
    ]
    snapshot = copy.deepcopy(days)
    generate_plan_b_variant(days)
    assert days == snapshot
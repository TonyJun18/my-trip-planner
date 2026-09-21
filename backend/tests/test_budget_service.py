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
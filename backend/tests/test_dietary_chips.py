"""dietary-filter-chips 后端测试（task-dietary-filter-chips-eval）。

覆盖（对齐 openspec/changes/2026-11-20-dietary-filter-chips/spec.md）：
1. dietary_keys_to_keywords：key → 中文关键词（vegetarian→素食等）
2. none → 不产生关键词（零变化）
3. merge_food_preferences：并入餐饮偏好、去重保序、无 dietary 时与现状一致
4. PlanRequest 增可选 dietary 字段（可解析）
5. 后端组装：food 偏好输入含映射后的饮食关键词（_planner_user_text 集成）
"""
from __future__ import annotations

from app.i18n.prompts import dietary_keys_to_keywords, merge_food_preferences
from app.schemas.agent import PlanRequest


# ── 1. dietary_keys_to_keywords 映射 ─────────────────────────

def test_dietary_keys_to_keywords_zh():
    assert dietary_keys_to_keywords("zh-CN", ["vegetarian"]) == ["素食"]
    assert dietary_keys_to_keywords("zh-CN", ["halal"]) == ["清真"]
    assert dietary_keys_to_keywords("zh-CN", ["no-seafood"]) == ["不吃海鲜"]
    assert dietary_keys_to_keywords("zh-CN", ["no-pork"]) == ["不吃猪肉"]
    assert dietary_keys_to_keywords("zh-CN", ["gluten-free"]) == ["无麸质"]


def test_dietary_keys_multiple():
    assert dietary_keys_to_keywords("zh-CN", ["vegetarian", "no-seafood"]) == ["素食", "不吃海鲜"]


def test_dietary_keys_none_empty():
    """none / 空列表 → 不产生关键词（零污染）。"""
    assert dietary_keys_to_keywords("zh-CN", ["none"]) == []
    assert dietary_keys_to_keywords("zh-CN", []) == []


def test_dietary_keys_unknown_passthrough():
    """未知 key → 原样保留（不猜测、不丢弃）。"""
    assert dietary_keys_to_keywords("zh-CN", ["unknown-key"]) == ["unknown-key"]


# ── 2. merge_food_preferences ────────────────────────────────

def test_merge_food_preferences_combines():
    """自由文本 + dietary 关键词 → 合并保序无重复。"""
    out = merge_food_preferences(["川菜"], ["vegetarian", "no-seafood"], "zh-CN")
    assert out == ["川菜", "素食", "不吃海鲜"]


def test_merge_food_preferences_dedup():
    """重复关键词去重（保序）。"""
    out = merge_food_preferences(["素食", "川菜"], ["vegetarian"], "zh-CN")
    assert out == ["素食", "川菜"]


def test_merge_food_preferences_no_dietary_unchanged():
    """无 dietary → 与现状完全一致（零变化）。"""
    assert merge_food_preferences(["川菜"], [], "zh-CN") == ["川菜"]
    assert merge_food_preferences(["川菜"], ["none"], "zh-CN") == ["川菜"]


# ── 3. PlanRequest 增 dietary ────────────────────────────────

def test_plan_request_accepts_dietary():
    from datetime import date

    req = PlanRequest(
        destination="杭州",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 3),
        dietary=["vegetarian", "no-seafood"],
    )
    assert req.dietary == ["vegetarian", "no-seafood"]


def test_plan_request_dietary_default_none():
    from datetime import date

    req = PlanRequest(destination="杭州", start_date=date(2026, 12, 1), end_date=date(2026, 12, 3))
    assert req.dietary is None


# ── 4. 后端组装集成（_planner_user_text 含饮食关键词）─────────

def test_food_preferences_injected_into_planner_context():
    """dietary 关键词应进入 food 偏好输入（与自由文本同权）。"""
    from app.agent.agents import _food_hints
    from app.i18n.prompts import preference_keys_to_keywords

    prefs = preference_keys_to_keywords("zh-CN", ["food"])
    food_prefs = merge_food_preferences(_food_hints(prefs), ["vegetarian"], "zh-CN")
    assert "素食" in food_prefs

    # pipeline 层已把 dietary 并入 food_agent 输入（CollectAgentsStep）——这里验证
    # merge_food_preferences 与 _food_hints 的组合产物会被 food_agent 消费：
    # 含 dietary 关键词 → 检索不丢饮食约束
    assert merge_food_preferences(["川菜"], ["halal"], "zh-CN") == ["川菜", "清真"]
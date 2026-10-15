"""test_inspiration_service.py —— 灵感优先目的地推荐（确定性规则库）测试。

覆盖：
- 兴趣过滤：交集计数，至少一个命中才入选；无兴趣输入时按预算+季节推荐
- 预算诚实：目的地基准消费档超出请求档位 → 不推荐
- 季节标注：最佳季节无提示；非最佳季节降权不排除并附 season_note
- 排序确定性：匹配度降序（match_score），同分热榜兜底
- limit 边界（1-5）
"""
from __future__ import annotations

from app.services.inspiration_service import DESTINATIONS, INTEREST_TAGS, recommend_destinations


def _all_tiers(items) -> set[str]:
    return {it["budget_tier"] for it in items}


# ── 兴趣过滤 ─────────────────────────────────────────────
def test_interest_match_counts_overlap():
    items = recommend_destinations(interests=["food", "nightlife"], budget_tier="comfort", limit=5)
    assert items, "应返回推荐"
    # 每个候选必须至少命中一个兴趣
    for it in items:
        assert it["matched_tags"], f"{it['name']} 应命中至少一个兴趣标签"
        assert set(it["matched_tags"]) <= {"food", "nightlife"}
    # 命中 2 个兴趣的候选分数应不低于命中 1 个的
    scores = [it["match_score"] for it in items]
    assert scores == sorted(scores, reverse=True), "应严格按匹配度降序"


def test_no_interests_recommends_all_affordable():
    items = recommend_destinations(interests=None, budget_tier="comfort", limit=5)
    assert items
    # 预算诚实：返回的候选消费档都不超过请求档位
    assert _all_tiers(items) <= {"economy", "comfort"}, "不应推荐超出预算档的目的地"
    for it in items:
        assert it["basis"] == "rule_based"
        assert it["matched_tags"] == []


# ── 预算诚实 ─────────────────────────────────────────────
def test_budget_tier_filters_luxury():
    # economy 请求：库里 luxury（东京/京都大阪/新加坡/巴黎）必须全部被过滤
    items = recommend_destinations(interests=None, budget_tier="economy", limit=5)
    assert _all_tiers(items) == {"economy"}
    assert not any("东京" in it["name"] or "巴黎" in it["name"] for it in items)


def test_budget_tier_comfort_includes_spending_options():
    items = recommend_destinations(interests=None, budget_tier="quality", limit=5)
    # quality 档可以包含 economy/comfort/quality 的目的地
    assert _all_tiers(items) <= {"economy", "comfort", "quality"}


# ── 季节标注 ─────────────────────────────────────────────
def test_season_match_no_note():
    # winter 最佳：哈尔滨（economy）/ 西双版纳（comfort）/ 三亚（quality>comfort 被过滤）
    items = recommend_destinations(interests=None, budget_tier="comfort", season="winter", limit=5)
    names = {it["name"] for it in items}
    assert "哈尔滨" in names and "西双版纳" in names
    hrb = next(it for it in items if it["name"] == "哈尔滨")
    assert hrb["season_note"] == "", "冬季最佳目的地不应有季节提示"


def test_season_mismatch_downgraded_not_excluded():
    """非最佳季节（青岛，夏季最佳）在冬季请求中降权但不从知识库硬删。"""
    kw_interest = ["food", "family"]
    neutral = recommend_destinations(interests=kw_interest, budget_tier="comfort", limit=5)
    names_neutral = [x["name"] for x in neutral]
    # 不排除：无季节请求下青岛（food+family 双命中）正常入选
    assert "青岛" in names_neutral, "青岛应存在于知识库并可被推荐（未被硬排除）"

    winter = recommend_destinations(interests=kw_interest, budget_tier="comfort", season="winter", limit=5)
    names_winter = [x["name"] for x in winter]
    assert "哈尔滨" in names_winter, "当季最佳（冬季）应进入推荐前列"
    # 降权真实生效：冬季请求下青岛被挤出前 5（或排在当季最佳之后）
    if "青岛" in names_winter:
        assert names_winter.index("青岛") > names_winter.index("哈尔滨"), "非最佳季节应排当季最佳之后"
    else:
        assert "青岛" not in names_winter  # 被挤出前 5 也是降权的正确表现


def test_season_best_ranks_above_all_season():
    """当季最佳目的地应优先于四季皆宜（季节是用户显式约束，必须真实影响排序）。"""
    winter = recommend_destinations(interests=None, budget_tier="comfort", season="winter", limit=5)
    names = [x["name"] for x in winter]
    # 当季最佳（哈尔滨/西双版纳）必须进入前 5
    assert "哈尔滨" in names and "西双版纳" in names, "当季最佳目的地应进入推荐前列"
    # 若非最佳季节目的地（青岛）仍入选（降权不排除），必须排在当季最佳之后
    if "青岛" in names:
        assert names.index("哈尔滨") < names.index("青岛"), "当季最佳应排在非最佳季节之前"

    # 无季节请求：四季皆宜的目的地恢复热榜排序，不背季节权重
    neutral = recommend_destinations(interests=None, budget_tier="comfort", limit=5)
    assert all(it["season_note"] == "" for it in neutral), "无季节请求不应带季节提示"


# ── limit 边界 ───────────────────────────────────────────
def test_limit_clamped_to_1_5():
    assert len(recommend_destinations(limit=1)) == 1
    assert len(recommend_destinations(limit=3)) == 3
    assert len(recommend_destinations(limit=5)) == 5
    assert len(recommend_destinations(limit=99)) == 5, "limit 被钳制到 5"


# ── 知识库与前端契约 ─────────────────────────────────────
def test_knowledge_base_tags_aligned_with_wizard():
    """知识库兴趣标签必须落在 PlanWizard 偏好 chips 词表内（前端才能匹配）。"""
    for dest in DESTINATIONS:
        for tag in dest["tags"]:
            assert tag in INTEREST_TAGS, f"{dest['name']} 含未知兴趣标签 {tag}"


def test_every_destination_has_full_card_fields():
    for dest in DESTINATIONS:
        for field in ("name", "reason", "play", "est_daily_budget", "suggested_days", "budget_tier", "best_season"):
            assert dest.get(field), f"{dest.get('name')} 缺字段 {field}"
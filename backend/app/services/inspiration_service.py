"""灵感优先目的地推荐（Inspiration Engine）：确定性规则库，零 LLM / 零 API key。

背景（竞争分析结论，docs/nightly/competitive-analysis/2026-10-09.md）：
- Mindtrip Start Anywhere / Layla 五问「Let me inspire you」验证了「还没想好去哪」
  是行程规划最大的起点摩擦；我们「问答表单 + 四通道导入 + questions 追问」入口策略
  缺一个低摩擦起点：先选目的地，再进入创建表单预填。
- 本服务是 task-inspiration-mode 的后端：推荐接口不依赖 LLM，纯规则匹配，
  可离线单测；前端灵感入口 + 目的地卡片 + 选点预填在前端接线。

设计决策（与 plan_b / time_validation 同风格）：
- 目的地知识库 = 内置精选清单（国内 + 亚洲/欧洲高频出境目的地），每条带
  兴趣标签 / 最佳季节 / 预估日均预算 / 建议天数 / 一句话理由 / 参考玩法；
- 兴趣标签词表与 PlanWizard 偏好 chips 对齐（food/nature/history/shopping/
  family/hiking/museum/nightlife/photo/hotspring），前端选什么这里就能匹配什么；
- 匹配逻辑：兴趣交集计数 → 季节标注（当季最佳 +1 优先、"all" 平权不提示、
  非最佳季节 -0.5 降权不排除）→ 预算可负担过滤
  （超过请求档位的目的地不推荐，诚实口径：推荐消费得起的地方）→ 确定性排序；
- 全部产物带 basis=rule_based 诚实标注；预估日均预算为基准推断，以实际为准。
"""

from __future__ import annotations

from typing import Any, Literal

# ── 档位定义（与 PlanWizard budgetPresets 对齐：1500/3000/6000/12000 元档）──
BUDGET_TIERS: dict[str, int] = {"economy": 0, "comfort": 1, "quality": 2, "luxury": 3}
BUDGET_TIER_LABEL: dict[str, str] = {
    "economy": "经济",
    "comfort": "舒适",
    "quality": "品质",
    "luxury": "奢华",
}

# ── 季节词表 ─────────────────────────────────────────────
SEASONS = ("spring", "summer", "autumn", "winter")
_SEASON_LABEL = {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"}

# 兴趣标签词表（与 PlanWizard prefLabelKeyMap 对齐）
INTEREST_TAGS = ("food", "nature", "history", "shopping", "family", "hiking",
                 "museum", "nightlife", "photo", "hotspring")

# ── 目的地知识库（精选清单；字段含义见模块 docstring）────────────────
# budget_tier: 该目的地基准消费档（超出用户请求档位 → 不推荐）
# best_season: 最佳季节；"all" 表示四季皆宜
DESTINATIONS: list[dict[str, Any]] = [
    # ── 国内 ──
    {"name": "杭州", "country": "中国", "tags": ["nature", "history", "photo", "food"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 800,
     "suggested_days": 3, "hotness": 9,
     "reason": "西湖四季皆景，Citywalk 与人文底蕴兼备，是入门级目的地天花板",
     "play": "西湖环线漫步 + 灵隐寺祈福 + 龙井村喝茶 + 河坊街小吃"},
    {"name": "成都", "country": "中国", "tags": ["food", "history", "nightlife", "family"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 700,
     "suggested_days": 3, "hotness": 9,
     "reason": "美食之都 + 慢生活，熊猫基地老少通吃，夜生活丰富",
     "play": "熊猫基地 + 宽窄巷子 + 人民公园喝茶 + 火锅/川菜 + 九眼桥夜生活"},
    {"name": "大理", "country": "中国", "tags": ["nature", "photo", "hiking", "food"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 900,
     "suggested_days": 4, "hotness": 8,
     "reason": "苍山洱海是摄影天花板，环海骑行慢节奏治愈",
     "play": "洱海骑行 + 苍山索道 + 喜洲古镇 + 双廊看日落"},
    {"name": "厦门", "country": "中国", "tags": ["nature", "food", "photo", "family"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 850,
     "suggested_days": 3, "hotness": 8,
     "reason": "海岛文艺风，鼓浪屿 + 环岛路适合亲子与拍照党",
     "play": "鼓浪屿 + 环岛路骑行 + 沙坡尾 + 海鲜排档"},
    {"name": "北京", "country": "中国", "tags": ["history", "museum", "food", "family"],
     "best_season": "all", "budget_tier": "quality", "est_daily_budget": 1200,
     "suggested_days": 4, "hotness": 10,
     "reason": "故宫长城国博是人文历史爱好者的终极目的地",
     "play": "故宫 + 长城 + 国家博物馆 + 胡同citywalk + 烤鸭"},
    {"name": "上海", "country": "中国", "tags": ["shopping", "museum", "nightlife", "food"],
     "best_season": "all", "budget_tier": "quality", "est_daily_budget": 1500,
     "suggested_days": 3, "hotness": 9,
     "reason": "看展逛街夜生活一条龙，都市感最强的目的地",
     "play": "外滩夜景 + 武康路漫步 + 西岸美术馆 + 淮海路购物"},
    {"name": "西安", "country": "中国", "tags": ["history", "food", "museum"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 800,
     "suggested_days": 3, "hotness": 8,
     "reason": "十三朝古都，兵马俑与城墙是历史控必去",
     "play": "兵马俑 + 陕西历史博物馆 + 城墙骑行 + 回民街小吃"},
    {"name": "长沙", "country": "中国", "tags": ["food", "nightlife", "shopping"],
     "best_season": "all", "budget_tier": "economy", "est_daily_budget": 600,
     "suggested_days": 3, "hotness": 7,
     "reason": "茶颜悦色+湘菜+夜市，性价比最高的吃喝城市",
     "play": "橘子洲头 + 岳麓山 + 太平街夜市 + 湘菜馆"},
    {"name": "重庆", "country": "中国", "tags": ["food", "nightlife", "photo", "shopping"],
     "best_season": "spring", "budget_tier": "economy", "est_daily_budget": 700,
     "suggested_days": 3, "hotness": 8,
     "reason": "8D 魔幻地形 + 火锅，出片率极高（夏季太热，春秋最佳）",
     "play": "洪崖洞夜景 + 李子坝轻轨 + 磁器口 + 老火锅"},
    {"name": "三亚", "country": "中国", "tags": ["nature", "family", "photo"],
     "best_season": "winter", "budget_tier": "quality", "est_daily_budget": 1400,
     "suggested_days": 4, "hotness": 7,
     "reason": "国内海岛度假首选，亲子玩水与躺平度假两相宜",
     "play": "亚龙湾沙滩 + 蜈支洲岛 + 海鲜市场 + 酒店躺平"},
    {"name": "丽江", "country": "中国", "tags": ["nature", "photo", "hiking", "history"],
     "best_season": "spring", "budget_tier": "comfort", "est_daily_budget": 900,
     "suggested_days": 4, "hotness": 7,
     "reason": "雪山古镇慢生活，玉龙雪山与束河是治愈系天花板",
     "play": "玉龙雪山 + 丽江古城 + 束河古镇 + 拉市海骑行"},
    {"name": "桂林", "country": "中国", "tags": ["nature", "photo", "hiking"],
     "best_season": "spring", "budget_tier": "economy", "est_daily_budget": 700,
     "suggested_days": 4, "hotness": 7,
     "reason": "山水甲天下，漓江竹筏与阳朔攀岩性价比极高",
     "play": "漓江竹筏 + 阳朔西街 + 遇龙河 + 龙脊梯田"},
    {"name": "张家界", "country": "中国", "tags": ["nature", "hiking", "photo"],
     "best_season": "spring", "budget_tier": "comfort", "est_daily_budget": 800,
     "suggested_days": 3, "hotness": 7,
     "reason": "三千奇峰是徒步与摄影爱好者的秘境",
     "play": "天子山 + 袁家界 + 金鞭溪徒步 + 玻璃桥"},
    {"name": "青岛", "country": "中国", "tags": ["nature", "food", "family", "photo"],
     "best_season": "summer", "budget_tier": "comfort", "est_daily_budget": 900,
     "suggested_days": 3, "hotness": 7,
     "reason": "红瓦绿树碧海蓝天，啤酒海鲜是夏天的正确打开方式",
     "play": "八大关 + 栈桥 + 啤酒博物馆 + 海鲜烧烤"},
    {"name": "哈尔滨", "country": "中国", "tags": ["food", "photo", "family"],
     "best_season": "winter", "budget_tier": "economy", "est_daily_budget": 700,
     "suggested_days": 3, "hotness": 6,
     "reason": "冰雪大世界 + 中央大街，冬季限定童话感",
     "play": "冰雪大世界 + 中央大街 + 圣索菲亚教堂 + 铁锅炖"},
    {"name": "西双版纳", "country": "中国", "tags": ["nature", "family", "food"],
     "best_season": "winter", "budget_tier": "comfort", "est_daily_budget": 900,
     "suggested_days": 4, "hotness": 6,
     "reason": "热带雨林 + 傣族风情，冬季避寒亲子圣地",
     "play": "告庄夜市 + 热带植物园 + 傣族园 + 雨林徒步"},
    # ── 亚洲出境 ──
    {"name": "东京", "country": "日本", "tags": ["food", "shopping", "museum", "family"],
     "best_season": "all", "budget_tier": "luxury", "est_daily_budget": 3000,
     "suggested_days": 5, "hotness": 9,
     "reason": "美食购物博物馆全拉满，城市文明体验无短板",
     "play": "浅草寺 + 秋叶原 + 筑地市场 + 明治神宫 + 涩谷购物"},
    {"name": "京都 · 大阪", "country": "日本", "tags": ["food", "history", "shopping"],
     "best_season": "spring", "budget_tier": "luxury", "est_daily_budget": 2800,
     "suggested_days": 5, "hotness": 9,
     "reason": "古都神社 + 大阪美食，樱花季与红叶季是双重巅峰",
     "play": "清水寺 + 伏见稻荷 + 岚山 + 道顿堀美食"},
    {"name": "曼谷", "country": "泰国", "tags": ["food", "shopping", "nightlife", "family"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 1500,
     "suggested_days": 4, "hotness": 8,
     "reason": "性价比超高的出境第一站，庙宇美食购物夜市俱全",
     "play": "大皇宫 + 湄南河 + 暹罗商圈 + 火车头夜市"},
    {"name": "新加坡", "country": "新加坡", "tags": ["shopping", "family", "food"],
     "best_season": "all", "budget_tier": "luxury", "est_daily_budget": 2600,
     "suggested_days": 4, "hotness": 8,
     "reason": "花园城市，亲子友好度高，安全干净省心",
     "play": "滨海湾花园 + 环球影城 + 圣淘沙 + 牛车水美食"},
    {"name": "首尔", "country": "韩国", "tags": ["shopping", "food", "nightlife"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 2000,
     "suggested_days": 4, "hotness": 7,
     "reason": "逛街美妆韩餐三件套，年轻人第一趟出境游优选",
     "play": "明洞 + 弘大 + 景福宫 + 南山塔 + 韩餐探店"},
    {"name": "普吉岛", "country": "泰国", "tags": ["nature", "family", "photo"],
     "best_season": "all", "budget_tier": "comfort", "est_daily_budget": 1800,
     "suggested_days": 5, "hotness": 7,
     "reason": "出海跳岛 + 沙滩躺平，海岛度假性价比之王",
     "play": "皮皮岛跳岛 + 芭东海滩 + 夜市 + 泰式按摩"},
    # ── 欧洲 ──
    {"name": "巴黎", "country": "法国", "tags": ["history", "museum", "photo", "food"],
     "best_season": "spring", "budget_tier": "luxury", "est_daily_budget": 3500,
     "suggested_days": 5, "hotness": 8,
     "reason": "卢浮宫铁塔塞纳河，浪漫与艺术的代名词",
     "play": "卢浮宫 + 埃菲尔铁塔 + 塞纳河游船 + 蒙马特高地"},
]


def _tier_rank(tier: str) -> int:
    return BUDGET_TIERS.get(tier, 1)


def _season_score(dest: dict[str, Any], season: str | None) -> tuple[float, bool]:
    """季节评分（season 指定时的排序权重）：

    - 无请求季节 → (0.0, False)：不参与排序
    - dest.best_season == 请求季节 → (+1.0, False)：当季标杆，无提示
    - dest.best_season == 'all' → (0.0, False)：四季皆宜，非「当季之最」，不提示
    - 其余（非最佳季节）→ (-0.5, True)：降权不排除，附 season_note

    返回 (评分增量, 是否非最佳季节需提示)。
    """
    if not season:
        return 0.0, False
    best = dest.get("best_season") or "all"
    if best == "all":
        return 0.0, False
    if best == season:
        return 1.0, False
    return -0.5, True


def recommend_destinations(
    interests: list[str] | None = None,
    budget_tier: str = "comfort",
    season: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """根据兴趣 / 预算档 / 季节推荐目的地（确定性规则，零 LLM）。

    参数：
    - interests: 兴趣标签（与 PlanWizard 偏好 chips 对齐）；空 → 按预算+季节推荐
    - budget_tier: economy/comfort/quality/luxury（可负担过滤：超出档位不推荐）
    - season: spring/summer/autumn/winter；None 不过滤（最佳季节标注仍保留）
    - limit: 返回条数（3-5 之间按需）

    返回：按匹配度降序的目的地卡片列表，附加 match_score / season_note / basis。
    """
    tags = [t for t in (interests or []) if t in INTEREST_TAGS]
    user_tier_rank = _tier_rank(budget_tier)

    scored: list[dict[str, Any]] = []
    for dest in DESTINATIONS:
        # 预算诚实：目的地基准消费档超出用户档位 → 不推荐（推荐消费得起的地方）
        if _tier_rank(dest.get("budget_tier", "comfort")) > user_tier_rank:
            continue

        # 兴趣匹配：交集计数（至少一个命中才入选；无兴趣输入时全部候选）
        hit = [t for t in tags if t in dest.get("tags", [])]
        if tags and not hit:
            continue

        match_score = len(hit)
        season_boost, needs_note = _season_score(dest, season)
        score = match_score + season_boost + dest.get("hotness", 0) / 20
        # 预算接近度：同档最优先（同分时热榜兜底）
        score += 0.05 if dest.get("budget_tier") == budget_tier else 0.0

        scored.append({
            **{k: v for k, v in dest.items() if k not in ("hotness",)},
            "match_score": round(score, 2),
            "matched_tags": hit,
            "season_note": (
                "" if not needs_note
                else f"最佳季节为{_SEASON_LABEL.get(str(dest.get('best_season') or ''), '')}，当前并非最佳体验期"
            ),
            "basis": "rule_based",
        })

    scored.sort(key=lambda x: (-x["match_score"], -x.get("hotness", 0), x["name"]))
    return scored[: max(1, min(limit, 5))]
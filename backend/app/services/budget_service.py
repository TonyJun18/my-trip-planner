"""预算计算服务。"""
from __future__ import annotations

from app.models import Trip

# 酒店估算：城市基准价（元/晚，中档）— 竞品分析确认的高优先缺口，代码确定性估算
_HOTEL_CITY_BASE: dict[str, float] = {
    "北京": 520.0, "上海": 560.0, "广州": 420.0, "深圳": 480.0,
    "杭州": 430.0, "成都": 360.0, "重庆": 340.0, "西安": 360.0,
    "南京": 400.0, "武汉": 360.0, "长沙": 350.0, "苏州": 430.0,
    "厦门": 450.0, "青岛": 390.0, "天津": 380.0, "三亚": 520.0,
}
_HOTEL_FALLBACK = 380.0  # 未知城市兜底（接近全国中档均价）

# 档位关键词 → 倍率（相对基准价）
_HOTEL_TIER: list[tuple[str, float]] = [
    ("奢华", 3.2), ("豪华", 2.6), ("五星", 2.8), ("国际", 2.2), ("度假", 2.2),
    ("精品", 1.8), ("四星", 1.8), ("高档", 1.9), ("商务", 1.5), ("主题", 1.4),
    ("三星", 1.25), ("品牌", 1.15), ("连锁", 1.05), ("快捷", 0.8), ("经济", 0.7),
    ("民宿", 0.9), ("客栈", 0.85), ("青旅", 0.55), ("招待所", 0.5),
]


def _match_city(city: str | None) -> str:
    """从城市名里匹配已知基准城市（支持'杭州'、'杭州市'、'浙江杭州'等）。"""
    if not city:
        return ""
    for known in _HOTEL_CITY_BASE:
        if known in city or city in known:
            return known
    return ""


def estimate_hotel_cost(
    name: str | None,
    city: str | None = None,
    *,
    rating: float | None = None,
) -> float:
    """估算酒店每晚参考价（元）。

    纯代码确定性估算，无外部依赖：城市基准价 × 档位倍率 × 评分修正。
    竞品分析确认我们酒店价格多为 0（预算空壳），此函数补上「合理参考价」，
    前端展示时标注「参考价，以实际询价为准」。

    - 城市命中已知基准 → 用之；否则全国兜底 380
    - 名称含档位关键词（经济/快捷/豪华/五星…）→ 乘对应倍率
    - rating 4.5+ 上浮 15%，3.5- 下浮 15%
    """
    name = (name or "").strip()
    if not name:
        return round(_HOTEL_FALLBACK, 2)

    base = _HOTEL_CITY_BASE.get(_match_city(city), _HOTEL_FALLBACK)
    multiplier = 1.0
    for kw, m in _HOTEL_TIER:
        if kw in name:
            multiplier = m
            break

    cost = base * multiplier
    if rating is not None:
        if rating >= 4.5:
            cost *= 1.15
        elif rating <= 3.5:
            cost *= 0.85
    return round(cost, 2)


def compute_budget(trip: Trip) -> dict:
    """根据行程中的站点费用汇总预算明细。

    返回结构：
    {
      "total_estimated": float,
      "by_type": {"attraction": float, "food": float, "hotel": float},
      "daily_average": float | None,
      "currency": "CNY"
    }
    """
    by_type: dict[str, float] = {"attraction": 0.0, "food": 0.0, "hotel": 0.0}
    total = 0.0
    for day in trip.days:
        for stop in day.stops:
            cost = stop.estimated_cost or 0.0
            by_type[stop.stop_type] = by_type.get(stop.stop_type, 0.0) + cost
            total += cost

    n_days = (trip.end_date - trip.start_date).days + 1
    return {
        "total_estimated": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "daily_average": round(total / n_days, 2) if n_days > 0 and total else None,
        "currency": "CNY",
    }
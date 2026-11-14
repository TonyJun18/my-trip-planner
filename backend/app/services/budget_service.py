"""预算计算服务。"""
from __future__ import annotations

from typing import Any

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

    口径标注（09-26 竞品分析补充验收：iPlan.ai 预算偏差 20-30% 翻车 → 诚实估算差异化）：
    本函数返回的是「规划层参考价」，基于静态城市基准价（2024 年中档酒店均价口径），
    非实时房价；前端须展示「估算口径」而非当作真实价格。
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


def hotel_estimate_basis(estimated_count: int) -> dict:
    """酒店预算估算口径标注（09-26 竞品分析补充验收）。

    返回描述估算来源 / 基准口径 / 置信度的结构化信息，供预算视图展示
    「估算 vs 实际可验证」，对齐 iPlan.ai 翻车教训：预算必须是可审计的诚实估算。
    """
    return {
        "source": "city_base_2024",
        "base_note": "城市中档酒店基准价 × 档位倍率（静态口径，非实时房价）",
        "confidence": "medium",
        "estimated_count": estimated_count,
        "actual_count": 0,
        "updated_at": "2026-09-26",
    }


# 多币种未落库：行程预算以 CNY 单一币种记账（task-budget-split 范围说明）
# — 多币种（行程级 currency 字段 + 汇率换算）需 DB 变更 + 汇率数据源，
#   超出单 worker 窗口，记入检查点 issues 待后续评估（对照 AiGo/Wanderlog 海外场景）。


# ── 大交通预算（task: 详情页预算口径）──────────────────────────
# budget 只汇总 stops（attraction/food/hotel）会导致预算偏小且与心理预期对不上。
# 从此处读取 plan_data.transport（TransportAgent 采集产物）把「往返大交通参考价」
# 计入 by_type.transport 与 total；无 price_range（无可信来源）时不编造，置 None。
_TRANSPORT_BASIS_NOTE = "大交通往返参考（单程最低参考价 ×2，非实时票价，以官方渠道为准）"


def _transport_round_trip(plan_data: dict | None) -> float | None:
    """从 plan_data.transport.options 取「单程最低参考价 ×2」；无可信价格返回 None。"""
    transport = (plan_data or {}).get("transport") if isinstance(plan_data, dict) else None
    if not isinstance(transport, dict):
        return None
    options = transport.get("options") or []
    lowest: float | None = None
    for o in options:
        if not isinstance(o, dict):
            continue
        price_range = o.get("price_range")
        if not isinstance(price_range, list) or not price_range:
            continue
        try:
            val = float(price_range[0])
        except (TypeError, ValueError):
            continue
        if val > 0 and (lowest is None or val < lowest):
            lowest = val
    if lowest is None:
        return None
    return round(lowest * 2, 2)


def transport_round_trip_cost(plan_data: dict | None) -> float | None:
    """公开入口：从 plan_data.transport 取「单程最低参考价 ×2」（无可信价格返回 None）。

    供预算计算（compute_budget）与规划编排层的 plan.budget 同步共用同一口径，
    避免两处各写一份往返估算逻辑导致偏差。
    """
    return _transport_round_trip(plan_data)


def _per_person_views(result: dict) -> dict:
    """在预算汇总上派生「人均分摊」视图（09-26 竞品分析：AiGo/Wanderlog 海外多人出行刚需）。

    - 人均 = 汇总项 ÷ travelers（行程成员数，Trips.travelers 已存在，无需 DB 变更）
    - travelers 缺省/异常（<1）视为 1（单人），不产出除 0 的伪人均
    - 保留原始汇总字段不动（total_estimated 等），前端可自由切换「总额 / 人均」展示
    """
    travelers = result.get("_travelers") or 1
    if travelers < 1:
        travelers = 1
    per_person = {
        "per_person_total": round(result["total_estimated"] / travelers, 2),
        "per_person_by_type": {
            k: round(v / travelers, 2) for k, v in result["by_type"].items()
        },
        # 键恒定（值为 None），避免 total=0 时缺键导致前端 undefined
        "per_person_daily": (
            round(result["daily_average"] / travelers, 2)
            if result.get("daily_average") is not None
            else None
        ),
    }
    return per_person


def compute_budget_stops(days: list[Any]) -> tuple[dict[str, float], float]:
    """按「行程天数列表」汇总站级预算（统一纯函数口径）。

    - 入参兼容 TripDay ORM 列表 / plan JSON 的 days dict 列表（stops 元素
      兼容 Stop ORM / dict，type 与 stop_type 都认）。
    - 语义：**0 价站按类型/关键词兜底估算计入**（方案 A 统计层兜底，与
      fill_stop_estimated_costs 同源同值），免费地标（公园/古镇/街等）仍为 0；
      已有正数价格原样计入。
    - 返回 (by_type, total)；by_type 恒含 attraction/food/hotel 三键。
    """
    by_type: dict[str, float] = {"attraction": 0.0, "food": 0.0, "hotel": 0.0}
    total = 0.0
    for day in days or []:
        stops = day.stops if hasattr(day, "stops") else (day.get("stops") or [])
        for s in stops:
            if hasattr(s, "stop_type"):
                stype = s.stop_type or "attraction"
                name = s.name
                cost = float(s.estimated_cost or 0)
                rating = None
                if isinstance(getattr(s, "details", None), dict):
                    rating = getattr(s, "details", {}).get("rating")
            else:
                stype = s.get("stop_type") or s.get("type") or "attraction"
                name = s.get("name")
                try:
                    cost = float(s.get("estimated_cost") or 0)
                except (TypeError, ValueError):
                    cost = 0.0
                rating = s.get("rating")
            if cost <= 0:
                cost = estimate_stop_cost(name, stype, rating=rating)
            by_type[stype] = by_type.get(stype, 0.0) + cost
            total += cost
    return by_type, total


def _days_range(start_date: Any, end_date: Any) -> int:
    """宽容计算行程天数（date / datetime / ISO 字符串）。无效返回 0。"""
    try:
        from datetime import date as _Date, datetime as _DT

        def _d(v: Any) -> _Date | None:
            if not v:
                return None
            if isinstance(v, _DT):
                return v.date()
            if isinstance(v, _Date):
                return v
            return _Date.fromisoformat(str(v)[:10])

        s, e = _d(start_date), _d(end_date)
        if not s or not e:
            return 0
        return (e - s).days + 1
    except Exception:
        return 0


def compute_full_budget(
    *,
    days: list[Any],
    start_date: Any = None,
    end_date: Any = None,
    destination: str | None = None,
    travelers: int | None = 1,
    planned: float | None = None,
    plan_data: dict | None = None,
    note: str | None = None,
) -> dict:
    """全口径预算汇总（纯函数，不依赖 Trip ORM）。

    统一口径（方案 A + C，2026-11-14）：四个消费方（API/分享页、pipeline
    生成 plan_data.budget、revise 修订重算、trip_edit_tool 试算）共用，
    保证 PlanWizard 结果页 / 详情页 / 修订后 / 分享页四处预算完全一致：

    1. 站级汇总：0 价站按类型/关键词兜底估算（compute_budget_stops）；
    2. 住宿缺口：N 天行程缺失的住宿晚数 × 目的地城市基准价（真实缺口，
       非权重硬凑）；
    3. 大交通：plan_data.transport 单程最低 ×2（无价格不编造）；
    4. 人均 / 日均派生；5. 用户预算对账块（reconciliation）。

    参数均接受 ORM（Trip/TripDay/Stop）或 dict（plan JSON / materials）。
    """
    by_type, total = compute_budget_stops(days)
    hotel_count = _count_hotel_stops(days)

    # 住宿晚数缺口（方案 C）
    missing_nights = _missing_nights_cost(
        hotel_count=hotel_count,
        start_date=start_date,
        end_date=end_date,
        destination=destination,
    )
    if missing_nights is not None:
        by_type["hotel"] = by_type.get("hotel", 0.0) + missing_nights
        total += missing_nights

    # 大交通往返参考价（plan_data.transport → 单程最低 ×2）；无价格不编造
    transport_cost = _transport_round_trip(plan_data)
    if transport_cost is not None:
        by_type["transport"] = transport_cost
        total += transport_cost

    n_days = _days_range(start_date, end_date)
    # 日均 = 目的地每日花销（不含一次性往返大交通）；总额含大交通。
    local_total = total - (transport_cost or 0.0)
    result = {
        "total_estimated": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "daily_average": round(local_total / n_days, 2) if n_days > 0 and local_total else None,
        "currency": "CNY",
    }
    # 人均分摊视图（travelers 异常按 1）
    travelers = travelers if isinstance(travelers, (int, float)) and travelers >= 1 else 1
    result.update(_per_person_views({**result, "_travelers": travelers}))
    # 估算口径标注
    basis: dict = {}
    if hotel_count > 0 or missing_nights is not None:
        basis["hotel"] = hotel_estimate_basis(hotel_count)
    if transport_cost is not None:
        basis["transport"] = {
            "source": "transport_agent_collected",
            "base_note": _TRANSPORT_BASIS_NOTE,
            "confidence": "medium",
            "estimated_count": 1,
            "actual_count": 0,
            "updated_at": "2026-10-04",
        }
    if basis:
        result["estimate_basis"] = basis
    # 用户预算对账块（方案 C）
    result["_days"] = n_days
    result = annotate_budget(result, planned=planned, note=note)
    result.pop("_days", None)
    return result


def _missing_nights_cost(
    *,
    hotel_count: int,
    start_date: Any,
    end_date: Any,
    destination: str | None,
) -> float | None:
    """住宿晚数缺口金额（方案 C 核心纯逻辑）。

    - 行程 N 天 → 需要 N 晚住宿（统一按 N 晚估算，口标注为「按晚数估算」）。
    - 已有酒店站覆盖 min(酒店站数, N) 晚；缺口 = N - 覆盖。
    - 缺口 × 目的地城市基准价（未知城市兜底 380）。
    - 返回 None = 无缺口 / 无日期，不产生金额。
    """
    n_days = _days_range(start_date, end_date)
    if n_days <= 0:
        return None
    covered = min(max(hotel_count, 0), n_days)
    gap = n_days - covered
    if gap <= 0:
        return None
    city = (destination or "").strip()
    known = _match_city(city) if city else ""
    base = _HOTEL_CITY_BASE.get(known, _HOTEL_FALLBACK)
    return round(base * gap, 2)


def compute_budget(trip: Trip, *, plan_data: dict | None = None) -> dict:
    """根据行程中的站点费用汇总预算明细（Trip ORM 入口，委托 compute_full_budget）。

    参数：
        plan_data: 可选。行程的 AI 规划方案快照（plan_data JSON）。传入后把
            大交通往返参考价（plan_data.transport，TransportAgent 采集产物）
            计入 by_type.transport 与 total —— stops 汇总不含大交通，会导致
            预算偏小且与用户直觉（含往返路费）对不上。无 transport / 无价格
            时不编造，transport 项置 None。

    返回结构：
    {
      "total_estimated": float,          # 站点合计 + 住宿缺口 + 大交通（若有）
      "by_type": {"attraction": float, "food": float, "hotel": float,
                  "transport": float | None},   # transport 键只在有参考价时出现
      "daily_average": float | None,
      "per_person_total": float | None,        # 人均分摊（task-budget-split）
      "per_person_by_type": dict,              # 人均 × 类别
      "per_person_daily": float | None,        # 人均日均
      "currency": "CNY",
      "estimate_basis": {"hotel": {...}, "transport": {...}},  # 估算口径标注
      "reconciliation": {...}                  # 用户预算对账块（方案 C）
    }
    """
    return compute_full_budget(
        days=trip.days,
        start_date=trip.start_date,
        end_date=trip.end_date,
        destination=trip.destination,
        travelers=trip.travelers,
        planned=trip.budget,
        plan_data=plan_data,
        note="估算为静态参考价（城市基准×档位/关键词），非实时报价",
    )


# ── 站点级费用兜底估算（方案 A）+ 住宿缺口补齐（方案 C） ──────────────
# 背景（2026-11-14 排查）：
# - PlannerAgent 提示词不要求 stop 输出 estimated_cost → 绝大多数字段为
#   StopSchema 默认 0.0；高德 POI 的 cost 字段也常为空 → 逐站求和预算 ≈ 0，
#   与用户填的 Trip.budget（如 6000）完全对不上，且日卡「每日花费」看着
#   像没统计（实际是站价全 0）。
# - 修复分层：
#   A. 落库前给 0 价站点按类型/关键词补「确定性参考估算」（不改 LLM 输出，
#      纯代码兜底，可审计）；compute_budget 统计时对 0 价站即时兜底（防御
#      旧数据 / 分享页）。
#   C. 住宿按「晚数缺口」补齐：行程 N 天 = 需要 N 晚住宿，已有酒店站只覆盖
#      部分 → 缺口晚数 × 城市基准价计入 hotel（真实缺口，非权重硬凑）。
#      另输出 reconciliation 对账块（planned / gap / daily_needed / note），
#      让「预算 6000 vs 生成 1800」的差距变成看得懂的「还差 X / 日均 Y」。
# 口径红线：估算一律带来源标注（source="rule_based"），绝不冒充真实报价。

# 景点/餐饮站级参考价（元/人·次，静态基准；关键词命中优先，否则类型兜底）
_ATTRACTION_BY_KEYWORD: tuple[tuple[str, float], ...] = (
    ("博物馆", 30.0), ("美术馆", 25.0), ("展览", 20.0),
    ("公园", 0.0), ("景区", 25.0), ("乐园", 250.0), ("游乐园", 250.0),
    ("主题公园", 300.0), ("动物园", 130.0), ("海洋馆", 180.0),
    ("古镇", 0.0), ("古城", 0.0), ("老街", 0.0), ("步行街", 0.0),
    ("塔", 40.0), ("寺", 45.0), ("庙", 30.0), ("教堂", 25.0),
    ("宫", 60.0), ("园", 30.0), ("湖", 25.0), ("山", 20.0),
    ("桥", 15.0), ("岛", 20.0), ("谷", 30.0), ("墙", 20.0),
    ("馆", 20.0), ("场", 15.0), ("街", 0.0),
)
_ATTRACTION_FALLBACK = 25.0  # 一般景点参考
_FOOD_BY_KEYWORD: tuple[tuple[str, float], ...] = (
    ("自助", 150.0), ("海鲜", 180.0), ("火锅", 130.0), ("烧烤", 100.0),
    ("日料", 150.0), ("西餐", 120.0), ("咖啡", 35.0), ("甜品", 40.0),
    ("料理", 120.0), ("酒楼", 110.0), ("餐厅", 80.0),
)
_FOOD_FALLBACK = 60.0  # 一般餐饮人均参考


def estimate_stop_cost(
    name: str | None,
    stop_type: str | None,
    *,
    city: str | None = None,
    rating: float | None = None,
) -> float:
    """站点费用确定性兜底估算（元）。

    - 名称命中餐厅/景点关键词 → 对应基准；否则按类型兜底
      （attraction 一般 25 / food 一般 60）。
    - hotel 复用 estimate_hotel_cost（城市基准价 × 档位倍率 × 评分修正）。
    - 纯代码、零 IO、同一输入恒同输出；返回 round(2)。

    仅用于 estimated_cost 缺失（0/None）时的「参考估算」，落库时带
    source=rule_based 标注；已有真实价格绝不覆盖。
    """
    name = (name or "").strip()
    stop_type = (stop_type or "").strip().lower()

    if stop_type == "hotel":
        return estimate_hotel_cost(name, city=city, rating=rating)

    if stop_type == "food":
        for kw, val in _FOOD_BY_KEYWORD:
            if kw in name:
                return float(val)
        return float(_FOOD_FALLBACK)

    # 默认 attraction（含未知类型，保守按景点）
    for kw, val in _ATTRACTION_BY_KEYWORD:
        if kw in name:
            return float(val)
    return float(_ATTRACTION_FALLBACK)


def fill_stop_estimated_costs(
    stops: list[dict[str, Any]],
    *,
    city: str | None = None,
) -> int:
    """把 stops 里 estimated_cost 缺失（None/0/非正数）的站点原地补齐为参考估算。

    - 只补「缺失」：已有正数价格保持原样（LLM/采集/手动给的真实价优先）。
    - 直接修改传入列表（dict in-place），返回补齐的站点数。
    - 同步写入 stop["estimate_sources"]["estimated_cost"]="rule_based"，
      供前端/导出区分「规则估算 vs 真实价」，保持诚实口径。
    """
    filled = 0
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        try:
            existing = float(stop.get("estimated_cost") or 0)
        except (TypeError, ValueError):
            existing = 0.0
        if existing > 0:
            continue
        cost = estimate_stop_cost(
            stop.get("name"),
            stop.get("type") or stop.get("stop_type"),
            city=city,
            rating=stop.get("rating"),
        )
        stop["estimated_cost"] = cost
        sources = stop.setdefault("estimate_sources", {})
        if not isinstance(sources, dict):
            stop["estimate_sources"] = {}
        stop["estimate_sources"]["estimated_cost"] = "rule_based"
        filled += 1
    return filled


def _count_hotel_stops(days: list[Any]) -> int:
    """统计行程里的酒店站点数（Trip.days 或 plan days dict 都接受）。"""
    n = 0
    for day in days or []:
        stops = day.stops if hasattr(day, "stops") else (day.get("stops") or [])
        for s in stops:
            st = s.stop_type if hasattr(s, "stop_type") else (s.get("stop_type") or s.get("type") or "")
            if st == "hotel":
                n += 1
    return n


def missing_hotel_nights_cost(trip: Trip, *, plan_data: dict | None = None) -> float | None:
    """住宿晚数缺口补齐（方案 C：真实缺口，非权重硬凑）。 Trip ORM 入口。

    - 行程 N 天 → 需要 N 晚住宿（统一按 N 晚估算，口标注为「按晚数估算」）。
    - 已有酒店站覆盖的晚数 = min(已有酒店站数, N)（多站/换酒店按 1 晚计）。
    - 缺口晚数 = N - 已覆盖 → × 目的地城市基准价（未知城市兜底 380）。
    - 已有酒店站价格已计入 by_type.hotel（站级），这里只补「缺口」。
    - 返回 None 表示无缺口（已有酒店站覆盖全部晚数 / 无日期），不产生金额。
    """
    return _missing_nights_cost(
        hotel_count=_count_hotel_stops(trip.days),
        start_date=trip.start_date,
        end_date=trip.end_date,
        destination=trip.destination,
    )


def annotate_budget(budget: dict[str, Any], *, planned: float | None, note: str | None = None) -> dict[str, Any]:
    """在预算汇总上附加 reconciliation 对账块（方案 C 展示层）。

    - planned: 用户 Trip.budget（规划时填的额度），None = 未填。
    - estimated: budget 的 total_estimated。
    - status: under=预计≤计划 / over=超出 / none=未填计划。
    - daily_needed: 若预计显著低于计划（≤计划的 80%），给出「日均还差 X」参考
      （不是硬凑 target，只是提示缺口量级）。
    - note: 诚实口径说明（估算为参考价，非实际报价）。
    - 只读派生：不修改 budget 原值，返回新 dict。
    """
    out = dict(budget)
    if planned is None or planned <= 0:
        out["reconciliation"] = {"planned": None, "status": "none", "note": note}
        return out
    total = float(budget.get("total_estimated") or 0)
    gap = planned - total
    n_days = float(budget.get("_days") or 0)
    daily_needed = round(gap / n_days, 2) if n_days > 0 and gap > 0 else None
    out["reconciliation"] = {
        "planned": round(planned, 2),
        "estimated": round(total, 2),
        "gap": round(gap, 2),
        "status": "over" if total > planned else "under",
        "daily_needed": daily_needed,
        "note": note,
    }
    return out
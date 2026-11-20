"""候选淘汰理由规则库（task-decision-drop-reason-eval / openspec 2026-11-20-decision-drop-reason）。

把候选筛选从黑盒变成可解释：对筛选过程中被淘汰的候选，以纯函数产出
「为什么淘汰」的确定性理由（rule_based，零 LLM / 可追溯 / 不编造）。

设计（与 TimeGate / DrivingGate 同哲学：确定性规则、复用既有阈值常量）：
- ``compute_drop_reasons(candidates, kept, ctx)``——组合入口，对每个未入选
  候选按优先级判定命中规则，产出 {stop_id, name, reason_code,
  reason_i18n_key, basis="rule_based"}；
- 五类 reason_code 枚举：budget_over（超出预算档）/ distance_too_far（距锚点
  超阈值）/ category_mismatch（类目不匹配用户偏好）/ capacity_full（当日容量
  已满）/ pacing_conflict（节奏冲突）；
- 阈值复用既有常量：单日人均预算 = 总预算/天数/人数（预算档口径）、
  DrivingGate ``MAX_LEG_KM``（距离红线）、``MAX_STOPS_PER_DAY``（当日容量 5 站）、
  ``MAX_PLAY_MINUTES_PER_DAY``（单日游玩时长红线）；
- 数据不足（无 cost / 无坐标 / 无类型）→ 该规则不判定（诚实沉默，绝不编造）；
- 只记录不改结果：调用方把 drops 当作审计信息挂到 solver_meta / plan_b 变体 /
  hotel 候选，不参与筛选判定（理由与决定解耦）。

i18n：reason_i18n_key 为机器键（dropReason.*），前端按 locale 渲染。
"""
from __future__ import annotations

from typing import Any

from app.services.driving_service import MAX_LEG_KM, haversine_km
from app.services.time_validation import MAX_PLAY_MINUTES_PER_DAY, MAX_STOPS_PER_DAY

# reason_code → i18n 键（前端 dropReason.* 渲染）
DROP_REASON_KEYS: dict[str, str] = {
    "budget_over": "dropReason.budgetOver",
    "distance_too_far": "dropReason.distanceTooFar",
    "category_mismatch": "dropReason.categoryMismatch",
    "capacity_full": "dropReason.capacityFull",
    "pacing_conflict": "dropReason.pacingConflict",
}

# 判定优先级（budget → distance → category → capacity → pacing）
_REASON_ORDER = ("budget_over", "distance_too_far", "category_mismatch", "capacity_full", "pacing_conflict")

# 酒店档位词（与 budget_service._HOTEL_TIER 同源）：名称含这些词视为「高档定位」
_LUXURY_TIER_WORDS = ("奢华", "豪华", "五星", "国际", "度假", "精品", "四星", "高档", "商务", "主题")


def _coords(stop: dict[str, Any]) -> tuple[float, float] | None:
    lat_raw, lng_raw = stop.get("lat"), stop.get("lng")
    if lat_raw is None or lng_raw is None:
        return None
    try:
        lat, lng = float(lat_raw), float(lng_raw)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _duration(stop: dict[str, Any]) -> int | None:
    d = stop.get("duration_minutes") or stop.get("estimated_duration_minutes")
    if d is None:
        return None
    try:
        return max(0, int(d))
    except (TypeError, ValueError):
        return None


def _kept_daily_duration(kept: list[dict[str, Any]]) -> int:
    """已入选候选的单日累计时长（缺时长不参与累计，与 TimeGate 同口径）。"""
    return sum(_duration(s) or 0 for s in (kept or []))


def _hit_budget_over(stop: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """超出预算档：人均消费 > 单日人均预算（总预算/天数/人数，零除防御）。"""
    cost = stop.get("estimated_cost")
    if cost is None:
        return False
    try:
        cost = float(cost)
    except (TypeError, ValueError):
        return False
    if cost <= 0:
        return False
    budget = ctx.get("budget")
    days = ctx.get("days") or 1
    travelers = ctx.get("travelers") or 1
    if not budget or days <= 0 or travelers <= 0:
        return False
    per_day = float(budget) / days / travelers
    return cost > per_day


def _hit_distance_too_far(stop: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """距锚点超阈值：复用 DrivingGate haversine 阈值（MAX_LEG_KM）。"""
    c = _coords(stop)
    anchor = ctx.get("anchor")
    if c is None or not isinstance(anchor, (tuple, list)) or len(anchor) != 2:
        return False
    try:
        km = haversine_km(c[0], c[1], float(anchor[0]), float(anchor[1]))
    except (TypeError, ValueError):
        return False
    return km > MAX_LEG_KM


def _hit_category_mismatch(stop: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """类目不匹配用户偏好类目（preferred_types 白名单）。"""
    preferred = ctx.get("preferred_types") or []
    if not preferred:
        return False
    typ = stop.get("type") or stop.get("stop_type") or ""
    return typ not in preferred


def _hit_capacity_full(ctx: dict[str, Any]) -> bool:
    """当日容量已满：已入选站点数 >= MAX_STOPS_PER_DAY。"""
    kept = ctx.get("kept") or []
    return len(kept) >= MAX_STOPS_PER_DAY


def _hit_pacing_conflict(ctx: dict[str, Any]) -> bool:
    """节奏冲突：已入选单日累计时长超红线（MAX_PLAY_MINUTES_PER_DAY）。"""
    kept = ctx.get("kept") or []
    return _kept_daily_duration(kept) > MAX_PLAY_MINUTES_PER_DAY


def compute_drop_reasons(
    candidates: list[dict[str, Any]],
    kept: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    """对未入选候选产出淘汰理由（纯函数，零 LLM / 零外部依赖）。

    参数：
    - ``candidates``：筛选前的候选列表（含 stop_id/name/type/estimated_cost/
      lat/lng/duration_minutes）
    - ``kept``：筛选后入选的候选列表（按 stop_id 或 name 判等）
    - ``ctx``：判定上下文 {budget, days, travelers, anchor, preferred_types}

    返回：每条 {stop_id, name, reason_code, reason_i18n_key, basis="rule_based"}；
    无淘汰 / 数据不足 → 空数组（不编造理由）。只记录不改结果——调用方
    把它当审计信息挂载，不参与筛选判定。
    """
    kept_ids = {str(s.get("stop_id") or s.get("name") or "") for s in (kept or [])}
    drop_ctx = {**ctx, "kept": kept}

    drops: list[dict[str, Any]] = []
    for cand in candidates or []:
        stop_id = str(cand.get("stop_id") or cand.get("name") or "")
        name = str(cand.get("name") or cand.get("stop_id") or "")
        if stop_id in kept_ids:
            continue  # 入选候选绝不产生淘汰理由
        for code in _REASON_ORDER:
            hit = {
                "budget_over": lambda: _hit_budget_over(cand, drop_ctx),
                "distance_too_far": lambda: _hit_distance_too_far(cand, drop_ctx),
                "category_mismatch": lambda: _hit_category_mismatch(cand, drop_ctx),
                "capacity_full": lambda: _hit_capacity_full(drop_ctx),
                "pacing_conflict": lambda: _hit_pacing_conflict(drop_ctx),
            }[code]()
            if hit:
                drops.append({
                    "stop_id": stop_id,
                    "name": name,
                    "reason_code": code,
                    "reason_i18n_key": DROP_REASON_KEYS[code],
                    "basis": "rule_based",
                })
                break  # 每个候选只记命中优先级最高的一条理由
    return drops


def _norm_hotel_name(name: str | None) -> str:
    """酒店名归一化（与前端 HotelRecommend.normName 同源）。"""
    return str(name or "").lower().replace(" ", "").replace("酒店", "").replace("hotel", "")


def _hotel_anchor(hotels: list[dict[str, Any]], chosen_names: set[str]) -> tuple[float, float] | None:
    """已选酒店的坐标均值作为锚（无已选 → None，距离规则沉默）。"""
    pts = [
        _coords(h) for h in hotels
        if _norm_hotel_name(h.get("name")) in chosen_names
    ]
    pts = [p for p in pts if p is not None]
    if not pts:
        return None
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _hotel_category_mismatch(hotel: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """酒店类目是否匹配住宿需求：需求含「经济/民宿/青旅/快捷」而候选是高档定位 → 不匹配。"""
    hints = " ".join(ctx.get("accommodation_hints") or [])
    wants_budget = any(w in hints for w in ("经济", "民宿", "青旅", "快捷", "连锁", "客栈"))
    if not wants_budget:
        return False
    name = str(hotel.get("name") or "")
    return any(w in name for w in _LUXURY_TIER_WORDS)


def attach_hotel_drop_reasons(
    hotels: list[dict[str, Any]],
    days: list[dict[str, Any]],
    ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    """给酒店候选附加淘汰理由对照（入选家展示其余候选为何被淘汰）。

    入选 = 行程 days 里实际安排进日程的酒店站（按名称归一化匹配）。
    背景：plan.hotels 是一批候选，用户最终只住 1 家；入选项的
    ``drop_reasons`` 列出其余候选各自的淘汰理由（budget_over /
    distance_too_far / category_mismatch），让「为什么选它」可对照。
    无已选酒店 / 无淘汰 → 不附加（诚实沉默）。纯函数，只读不改。
    """
    if not hotels or not days:
        return hotels

    chosen_names = {
        _norm_hotel_name(s.get("name"))
        for day in days for s in (day.get("stops") or [])
        if isinstance(s, dict) and (s.get("type") == "hotel" or s.get("stop_type") == "hotel")
    }
    if not chosen_names:
        return hotels  # 无已选 → 诚实沉默

    anchor = _hotel_anchor(hotels, chosen_names)
    drop_ctx = {
        **ctx,
        "anchor": anchor,
        "preferred_types": ["hotel"],
        "days": ctx.get("days") or max(1, len(days)),
        "travelers": ctx.get("travelers") or 1,
    }

    chosen = [h for h in hotels if _norm_hotel_name(h.get("name")) in chosen_names]
    losers = [h for h in hotels if _norm_hotel_name(h.get("name")) not in chosen_names]

    out: list[dict[str, Any]] = []
    for h in hotels:
        h = dict(h)  # 浅拷贝，不改输入
        if _norm_hotel_name(h.get("name")) in chosen_names:
            # 入选项：对照展示其余候选的淘汰理由
            reasons: list[dict[str, Any]] = []
            for loser in losers:
                # 逐规则判定：budget（超单日人均预算）→ distance（距已选锚点）→ category（需求类目不符）
                code = None
                if _hit_budget_over(loser, drop_ctx):
                    code = "budget_over"
                elif anchor is not None and _hit_distance_too_far(loser, drop_ctx):
                    code = "distance_too_far"
                elif _hotel_category_mismatch(loser, drop_ctx):
                    code = "category_mismatch"
                if code is not None:
                    reasons.append({
                        "stop_id": str(loser.get("stop_id") or loser.get("name") or ""),
                        "name": str(loser.get("name") or ""),
                        "reason_code": code,
                        "reason_i18n_key": DROP_REASON_KEYS[code],
                        "basis": "rule_based",
                    })
            if reasons:
                h["drop_reasons"] = reasons
        out.append(h)
    return out
"""行程备选方案（Plan B）服务：为已生成的行程生成一个可对比的备选骨架。

定位：马蜂窝 AI 路书「行程备选方案」是行前高频需求（2026-09-22 竞品分析
记入 backlog，2026-09-25 竞品分析确认 task-roadtrip-mode 已落地、评估条件满足）。

设计决策（与 note_import 同风格：纯函数、零外部依赖）：
- 不用 LLM、不消耗 API key：纯确定性规则生成（节奏 / 预算档 / 取舍 三种变体），
  同一输入永远得到同一输出，便于测试与回归；
- 只读派生：不落库、不改 trips 表——备选是主案的「对比预览」，
  「切换」由前端在读取侧完成（主案/备选对比），避免写库竞态与数据分裂；
- 结构与 TripPlan.plan_data 同构（days / budget），前端可复用行程渲染；
- 输入按字典传递（由 API 层从 ORM 装配），本模块不触数据库、不做 IO。

变体选择（确定性优先级）：
1. 节奏变体（Relaxed）：存在「过满日」（站点数 >= 5 或预估时长合计 > 480 分钟）
   且行程天数 >= 2 → 把过满日末尾的站点移到次日开头，整体节奏更松弛。
2. 预算档变体（Budget）：存在酒店站点 → 全部酒店按「经济档」×0.7 下调，
   预算随之重算（与主案形成预算档对比）。
3. 取舍变体（Curated）：兜底（任何有站点的行程都能生成）——每天去掉
   最后一个 food 站（无 food 则去掉该日时长最短的站），行程更精简。
   （单日行程过满无法移动时也降级到这里。）
"""
from __future__ import annotations

from datetime import date
from typing import Any

# 过满阈值：站点数 >= MAX_STOPS_PER_DAY 或预估时长合计 > MAX_MINUTES_PER_DAY
MAX_STOPS_PER_DAY = 5
MAX_MINUTES_PER_DAY = 480
# 预算档变体的酒店价格系数（经济档：-30%）
BUDGET_TIER_MULTIPLIER = 0.7
# 每日最大移除站点数（取舍变体防过度删减）
MAX_REMOVED_PER_DAY = 1

VARIANT_RELAXED = "节奏优化版"
VARIANT_BUDGET = "预算优化版"
VARIANT_CURATED = "精简取舍版"


def _stop_to_dict(stop: dict[str, Any]) -> dict[str, Any]:
    """规整一个站点字典（保留原字段，缺省兜底）。"""
    return {
        "name": stop.get("name") or "",
        "stop_type": stop.get("stop_type") or "attraction",
        "lat": stop.get("lat"),
        "lng": stop.get("lng"),
        "description": stop.get("description"),
        "estimated_cost": stop.get("estimated_cost"),
        "estimated_duration_minutes": stop.get("estimated_duration_minutes"),
    }


def _day_to_dict(day: dict[str, Any]) -> dict[str, Any]:
    """规整一天字典（stops 按原顺序，过滤无名字站点）。"""
    stops = [_stop_to_dict(s) for s in (day.get("stops") or []) if s.get("name")]
    return {
        "day_number": day.get("day_number") or 0,
        "date": day.get("date"),
        "theme": day.get("theme"),
        "stops": stops,
    }


def _sum_budget(days: list[dict[str, Any]]) -> dict[str, Any]:
    """按站点 estimated_cost 汇总预算（与 budget_service 同构）。

    返回 {total_estimated, by_type: {attraction, food, hotel}, currency}。
    """
    by_type: dict[str, float] = {"attraction": 0.0, "food": 0.0, "hotel": 0.0}
    total = 0.0
    for day in days:
        for stop in day.get("stops") or []:
            cost = stop.get("estimated_cost") or 0.0
            t = stop.get("stop_type") or "attraction"
            by_type[t] = by_type.get(t, 0.0) + cost
            total += cost
    return {
        "total_estimated": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "currency": "CNY",
    }


def _is_overfull(day: dict[str, Any]) -> bool:
    """一天是否「过满」：站点数 >= 5 或预估时长合计 > 480 分钟。"""
    stops = day.get("stops") or []
    if len(stops) >= MAX_STOPS_PER_DAY:
        return True
    total_minutes = sum(
        (s.get("estimated_duration_minutes") or 0) for s in stops
    )
    return total_minutes > MAX_MINUTES_PER_DAY


def _clone_days(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """深拷贝天数列表（所有变体都基于副本操作，绝不修改主案输入）。"""
    return [_day_to_dict(d) for d in days]


def _relaxed_variant(days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """节奏变体：把过满日末尾的站点移到次日开头。

    失败条件：没有过满日 / 只有一天（无处可移）→ 返回 None（调用方降级）。
    """
    if len(days) < 2:
        return None
    overfull_idx = next((i for i, d in enumerate(days) if _is_overfull(d)), None)
    if overfull_idx is None:
        return None

    result = _clone_days(days)
    src = result[overfull_idx]
    dst = result[overfull_idx + 1]

    # 取过满日「末尾」的站点移动（前一天收尾顺延到次日，符合直觉）
    moves: list[dict[str, Any]] = []
    while len(src["stops"]) >= MAX_STOPS_PER_DAY and src["stops"]:
        moves.append(src["stops"].pop())
    if not moves:
        return None

    moved_names = "、".join(m["name"] for m in moves)
    dst["stops"] = moves + dst["stops"]
    deltas = [
        f"第 {src['day_number']} 天站点偏多（{len(src['stops']) + len(moves)} 站），"
        f"把「{moved_names}」移到第 {dst['day_number']} 天早上，节奏更松弛。"
    ]
    return {
        "label": VARIANT_RELAXED,
        "description": "把过满的一天拆分到相邻一天，整体节奏更松弛，适合不想赶场的出行。",
        "deltas": deltas,
        "days": result,
        "budget": _sum_budget(result),
    }


def _budget_variant(days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """预算档变体：全部酒店按经济档 ×0.7 下调，预算重算。

    失败条件：行程里没有酒店站点 → 返回 None（调用方降级）。
    """
    result = _clone_days(days)
    hotel_diffs: list[str] = []
    total_saved = 0.0
    for day in result:
        for stop in day.get("stops") or []:
            if stop.get("stop_type") == "hotel":
                old = stop.get("estimated_cost") or 0.0
                new = round(old * BUDGET_TIER_MULTIPLIER, 2)
                stop["estimated_cost"] = new
                saved = round(old - new, 2)
                total_saved += saved
                hotel_diffs.append(f"「{stop['name']}」按经济档调整：约 ¥{old} → ¥{new}")

    if not hotel_diffs:
        return None

    deltas = hotel_diffs + [f"预算合计约节省 ¥{round(total_saved, 2)}（{VARIANT_BUDGET}）。"]
    return {
        "label": VARIANT_BUDGET,
        "description": "住宿整体换成经济档（约 -30%），适合预算敏感出行，行程站点不变。",
        "deltas": deltas,
        "days": result,
        "budget": _sum_budget(result),
    }


def _curated_variant(days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """取舍变体：每天去掉最后一个 food 站；无 food 则去掉该日时长最短的站。

    任何有站点的行程都能生成（兜底）；每天最多移除 MAX_REMOVED_PER_DAY 个，
    每天至少保留 1 个站点（防删空）。
    """
    result = _clone_days(days)
    total_stops = sum(len(d.get("stops") or []) for d in result)
    if total_stops == 0:
        return None

    removed: list[str] = []
    for day in result:
        stops = day.get("stops") or []
        if len(stops) <= 1:
            continue  # 单站日不移除（保底不删空）
        food_idx = next(
            (i for i in range(len(stops) - 1, -1, -1) if stops[i].get("stop_type") == "food"),
            None,
        )
        if food_idx is not None:
            target = food_idx
            reason = "餐饮站"
        else:
            # 去掉该日预估时长最短的站（时间有限时的取舍）
            target = min(
                range(len(stops)),
                key=lambda i: (stops[i].get("estimated_duration_minutes") or 0, i),
            )
            reason = "时长最短的站点"
        removed.append(f"第 {day['day_number']} 天去掉「{stops[target]['name']}」（{reason}）")
        del stops[target]

    if not removed:
        return None

    deltas = removed + ["整体更精简：保留核心站点，适合时间有限或想走慢一点的出行。"]
    return {
        "label": VARIANT_CURATED,
        "description": "砍掉可取舍的站点（餐饮冗余/耗时最长），保留核心行程，整体更精简。",
        "deltas": deltas,
        "days": result,
        "budget": _sum_budget(result),
    }


def generate_plan_b_variant(days: list[dict[str, Any]]) -> dict[str, Any] | None:
    """为行程天数列表生成一个备选方案变体（纯函数，确定性）。

    days: [{"day_number": 1, "date": "2026-10-01", "theme": "西湖经典",
            "stops": [{"name": "西湖", "stop_type": "attraction", ...}, ...]}, ...]
    返回: {"label", "description", "deltas", "days", "budget"} 或 None（无可生成内容）。

    变体选择优先级（确定性）：
      过满且可移 → 节奏；否则有酒店 → 预算档；否则 → 取舍。
    """
    normalized = [_day_to_dict(d) for d in days if (d.get("stops") or [])]
    if not normalized:
        return None

    variant = _relaxed_variant(normalized)
    if variant is None:
        variant = _budget_variant(normalized)
    if variant is None:
        variant = _curated_variant(normalized)
    return variant


def _date_to_iso(value: Any) -> str | None:
    """日期 → ISO 字符串（date / datetime / str 都接受）。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]
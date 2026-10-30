"""确定性行程求解服务（task-floattrip-borrow Story 4：候选排序 + 硬约束校验）。

对标 FloatTrip「LLM 候选 + 确定性优化器排程」——本轮不引入 OR-Tools CP-SAT
（P1 实验，见 PRD §3.1/§8 非目标），先落「规则排序 + 时间/距离硬约束校验 +
有限修复」的确定性层，让**规划结果不是模型凭空排的**，而是可核对：

- ``rank_candidates``：同一天内候选站点（attraction/food）按「到前序站点距离
  升序 + 评分降序」加权排序（LLM 选的站点顺序可被规则纠正）；
- ``check_hard_constraints``：硬约束校验（纯函数）：
  1. 超时校验：单日站点测算时长累计超限（按类目基准，缺时长不告警）
  2. 超距校验：相邻站点距离超限（复用 driving_service 的 haversine 阈值）
     → 标记 violation；**违反即尝试修复**；
- ``repair_violations``：有限修复（最多 repair_rounds 轮）——把超距的后置站点
  与后续站点交换顺序（贪心），修复不了则保留（不静默当成功：unresolved 非空）；
- ``solve``：组合入口，产出 ``plan.solver_meta``（排序依据 / 校验结果 / 修复记录）；
  硬约束不通过且未全修复时 solver_meta.passed=False 且 unresolved 非空——
  调用方（前端）看到「校验未通过」，绝不伪装成功。

设计哲学（与 DrivingGate/TimeGate 同源）：
- 一切为纯函数、确定性、零 LLM、零外部依赖，可单测；
- 数据不足（缺坐标/缺时长）→ 不告警（规则不确定时保持沉默，绝不编造）；
- 修复是尽力而为：修复失败 → 保留原状 + unresolved 记录，诚实标注。
"""
from __future__ import annotations

import math
from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t
from app.services.driving_service import estimate_drive_minutes, haversine_km

# ── 硬约束阈值（与 DrivingGate/TimeGate 同风格的规则库口径） ────────
MAX_DAY_DURATION_MINUTES = 600  # 单日站点测算时长累计上限（10h；紧凑 480 是建议档，这里是硬红线）
MAX_ADJACENT_KM = 40.0  # 相邻站点直线距离上限（同城高频换场红线）
REPAIR_MAX_ROUNDS = 3  # 有限修复最大轮数（有界，不无限循环）

# 无时长时按类目基准估算（分钟）
_DEFAULT_DURATION_MINUTES = {"attraction": 120, "food": 60, "hotel": None}
# 类目别名 → 基准键（理性宽容：attraction/museum/park → attraction）
_TRANSLATE_TYPE = {"museum": "attraction", "park": "attraction", "shopping": "food"}


def _norm_type(stop: dict[str, Any]) -> str:
    raw = stop.get("type") or "attraction"
    return _TRANSLATE_TYPE.get(raw, raw)


def _duration_minutes(stop: dict[str, Any]) -> int | None:
    """站点测算时长：显式字段优先，否则类目基准（酒店不估时）。"""
    d = stop.get("duration_minutes") or stop.get("estimated_duration_minutes")
    if d is not None:
        try:
            return max(0, int(d))
        except (TypeError, ValueError):
            return None
    base = _DEFAULT_DURATION_MINUTES.get(_norm_type(stop))
    if base is None:
        return None
    return base


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


def _adjacent_km(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    ca, cb = _coords(a), _coords(b)
    if ca is None or cb is None:
        return None
    return haversine_km(ca[0], ca[1], cb[0], cb[1])


def _rating(stop: dict[str, Any]) -> float:
    try:
        r = float(stop.get("rating") or 0.0)
    except (TypeError, ValueError):
        r = 0.0
    return r if 0 <= r <= 5 else 0.0


# ── 1. 候选排序 ───────────────────────────────────────────────
def _candidate_score(current: dict[str, Any], stop: dict[str, Any]) -> float:
    """加权得分：距离归一(0-1) × 0.65 + (5 - 评分)/5 × 0.35。

    分数越低越靠前（距离占主导、评分微调；高分优先）。无坐标站点按最远档
    （d_norm=2）处理——只影响排序不告警，缺数据不崩溃。
    """
    d = _adjacent_km(current, stop)
    d_norm = min(d / MAX_ADJACENT_KM, 2.0) if d is not None else 2.0
    return d_norm * 0.65 + ((5.0 - _rating(stop)) / 5.0) * 0.35


def rank_candidates(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一天内候选站点排序：到锚点距离升序 + 评分降序加权（贪心链）。

    输入 plan.days；返回排序后的 days（原地替换每天 stops 顺序）。
    锚点 = 当天酒店（住宿固定，其它站点围绕它展开）或原第一个可动站点；
    每步从剩余可动候选中选加权得分最小者（距离占主导、评分微调）。
    排序依据写入 plan.solver_meta（诚实口径：distance_asc_rating_desc）。
    """
    out: list[dict[str, Any]] = []
    for day in days or []:
        stops = [s for s in (day.get("stops") or []) if isinstance(s, dict)]
        if not stops:
            out.append({**day, "stops": []})
            continue
        hotels = [s for s in stops if _norm_type(s) == "hotel"]
        movable = [s for s in stops if _norm_type(s) != "hotel"]

        if not movable:
            out.append({**day, "stops": stops})
            continue

        # 锚点：优先当天酒店（围绕住宿展开）；否则原第一个可动站点
        anchor = hotels[0] if hotels else movable[0]
        remaining = list(movable)
        ordered: list[dict[str, Any]] = []
        current = anchor
        while remaining:
            best_j, best_score = 0, float("inf")
            for i, s in enumerate(remaining):
                score = _candidate_score(current, s)
                if score < best_score:
                    best_j, best_score = i, score
            picked = remaining.pop(best_j)
            ordered.append(picked)
            current = picked

        # 酒店插回原位（保持酒店在 stops 中的原相对位置）
        result: list[dict[str, Any]] = []
        hotel_idx = 0
        for s in stops:
            if _norm_type(s) == "hotel":
                result.append(hotels[hotel_idx])
                hotel_idx += 1
            else:
                result.append(ordered.pop(0))
        out.append({**day, "stops": result})
    return out


# ── 2. 硬约束校验 ─────────────────────────────────────────────
def check_hard_constraints(plan: dict[str, Any]) -> dict[str, Any]:
    """校验时间/距离硬约束，返回 {passed, violations}。

    violation 结构：{type: "over_duration"|"over_distance", day_number,
    message, stop_name?, gap_km?}。校验失败 → violations 非空。
    """
    violations: list[dict[str, Any]] = []
    for day in plan.get("days") or []:
        stops = [s for s in (day.get("stops") or []) if isinstance(s, dict)]
        if not stops:
            continue
        day_num = day.get("day_number")

        # 超时：单日累计测算时长超限（缺时长站点不参与累计）
        total = 0
        for s in stops:
            dur = _duration_minutes(s)
            if dur is not None:
                total += dur
        if total > MAX_DAY_DURATION_MINUTES:
            violations.append({
                "type": "over_duration",
                "day_number": day_num,
                "message": f"Day {day_num} 测算时长 {total}min 超限（>{MAX_DAY_DURATION_MINUTES}min）",
                "total_minutes": total,
            })

        # 超距：相邻站点直线距离超限（缺坐标跳过；酒店→首站 / 末站→酒店照常校验）
        prev: dict[str, Any] | None = None
        for s in stops:
            if prev is not None:
                d = _adjacent_km(prev, s)
                if d is not None and d > MAX_ADJACENT_KM:
                    violations.append({
                        "type": "over_distance",
                        "day_number": day_num,
                        "message": f"「{prev.get('name', '?')}」→「{s.get('name', '?')}」直线距离 {d:.1f}km 超限（>{MAX_ADJACENT_KM}km）",
                        "stop_name": s.get("name"),
                        "gap_km": round(d, 1),
                    })
            prev = s

    return {"passed": not violations, "violations": violations}


# ── 3. 有限修复 ───────────────────────────────────────────────
def repair_violations(plan: dict[str, Any], *, max_rounds: int = REPAIR_MAX_ROUNDS) -> dict[str, Any]:
    """有限修复：把超距的后置站点与后续最近站点交换（贪心）；最多 max_rounds 轮。

    返回 {repaired: [{day_number, message}], unresolved: [...]}——
    repaired 是已成功消解的 violation 摘要；unresolved 是修复不动（仍违反）
    的 violation 摘要。绝不静默当成功：unresolved 非空 → solver_meta.passed=False。
    """
    repaired: list[dict[str, Any]] = []
    for _round in range(max_rounds):
        check = check_hard_constraints(plan)
        if check["passed"]:
            break
        # 只修超距（超时无法靠换序修复——站点数和时长是 LLM 决定的）
        dist_violations = [v for v in check["violations"] if v["type"] == "over_distance"]
        if not dist_violations:
            break
        v = dist_violations[0]
        day = next((d for d in plan.get("days") or [] if d.get("day_number") == v["day_number"]), None)
        if day is None:
            break
        stops = day.get("stops") or []
        # 找「超距 stop」：与前一站距离超限的那个（v 的 stop_name）
        idx = None
        for i, s in enumerate(stops):
            if s.get("name") == v.get("stop_name"):
                idx = i
                break
        if idx is None or idx >= len(stops) - 1:
            break  # 已到最后/找不到 → 停（不无限循环）
        # 与后续最近的点交换（尝试拉近；若交换后仍超距则不再尝试）
        best_j, best_d = -1, float("inf")
        for j in range(idx + 1, len(stops)):
            d = _adjacent_km(stops[idx], stops[j])
            if d is not None and d < best_d:
                best_j, best_d = j, d
        if best_j == -1:
            break
        # 交换
        stops[idx], stops[best_j] = stops[best_j], stops[idx]
        day["stops"] = [s for s in stops]
        repaired.append({
            "day_number": v["day_number"],
            "message": f"已交换 Day {v['day_number']} 「{stops[idx].get('name', '?')}」与「{stops[best_j].get('name', '?')}」尝试修复超距",
        })
        # 一轮只修一个 violation（其它 violation 下轮继续；有界）
    final_check = check_hard_constraints(plan)
    unresolved = [
        {k: vv for k, vv in vv.items()}
        for vv in final_check["violations"]
    ]
    return {"repaired": repaired, "unresolved": unresolved, "passed": final_check["passed"]}


# ── 4. 组合入口：solve ────────────────────────────────────────
def solve(plan: dict[str, Any], *, locale: str = "zh-CN") -> dict[str, Any]:
    """确定性求解组合入口：排序 → 校验 → 有限修复 → 产出 solver_meta。

    原地修改 plan（days 排序 + plan.solver_meta）；返回 solver_meta。
    solver_meta 结构：:
        {
          "version": 1,
          "basis": "rule_based",
          "sorting": {"enabled": true, "strategy": "distance_asc_rating_desc"},
          "hard_constraints": {
             "passed": bool,
             "violations": [...],      # 原始违规
             "repaired": [...],        # 已修复记录
             "unresolved": [...],      # 仍未解决（passed=False 时非空）
          },
          "repair_rounds": int,
        }
    """
    locale = normalize_locale(locale)
    sorted_days = rank_candidates(plan.get("days") or [])
    plan["days"] = sorted_days

    check = check_hard_constraints(plan)
    repair = repair_violations(plan)

    meta: dict[str, Any] = {
        "version": 1,
        "basis": "rule_based",
        "sorting": {
            "enabled": True,
            "strategy": "distance_asc_rating_desc",
            "note": t(locale, "solver.sorting.note"),
        },
        "hard_constraints": {
            "passed": check["passed"] and repair["passed"],
            "violations": check["violations"],
            "repaired": repair["repaired"],
            "unresolved": repair["unresolved"],
        },
        "repair_rounds": len(repair["repaired"]),
    }
    plan["solver_meta"] = meta
    return meta
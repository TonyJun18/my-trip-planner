"""自驾模式：站点间驾车距离/时长校验 + 折返告警（确定性代码，无外部依赖）。

背景（竞品分析结论）：
- TripPlanner AI 主打自驾差异化：经停优化、避免折返；
- Mindtrip / Wanderlog 对自驾路线也有里程与时长提示。

我们以「确定性代码」实现自驾约束最小版（不依赖 LLM，可单元测试）：
- 同一天相邻站点：单段驾车距离 / 时长超限 → critical（拒绝该站点组合）
- 单日累计驾驶里程超限 → critical
- 站点序列折返（刚走远又折回出发点方向）→ warning
- 缺少坐标的站点 → warning（降级为不可校验，不阻断）

用途：
- ``run_planning_agents`` 在 Planner 每代输出后运行 DrivingGate：
  critical 存在且还有评审轮次 → 该站点组合被拒绝，反馈给 Planner 修订；
  达最大评审轮 → 强制定稿但保留告警（系统始终产出某种东西）。
- ``revise_service`` 修订落库后重算 driving 报告注入 plan snapshot。

一切为纯函数：输入 stops / plan dict，输出结构化报告（issue 结构与
``CritiqueIssueSchema`` 兼容，可直接进入评审反馈链路）。
"""
from __future__ import annotations

import math
from typing import Any

# ── 阈值（自驾友好，可在调用处覆盖） ────────────────────────
DEFAULT_AVG_KMH = 50.0  # 含市区/红绿灯/拥堵的平均车速
MAX_LEG_KM = 120.0  # 相邻站点单段驾车距离上限（约 2.4h 车程）
MAX_LEG_MINUTES = 150.0  # 相邻站点单段驾车时长上限（约 2.5h）
MAX_DAILY_KM = 300.0  # 单日累计驾驶里程上限（跨城赶路红线）


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """球面距离（千米），Haversine 公式。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_drive_minutes(distance_km: float, avg_kmh: float = DEFAULT_AVG_KMH) -> int:
    """驾车时长估算（分钟）。纯代码确定性估算，非导航数据。"""
    if distance_km <= 0 or avg_kmh <= 0:
        return 0
    return int(round(distance_km / avg_kmh * 60))


def _stop_coords(stop: dict[str, Any]) -> tuple[float, float] | None:
    """提取站点坐标；缺失或非法返回 None。"""
    if not isinstance(stop, dict):
        return None
    lat, lng = stop.get("lat"), stop.get("lng")
    if lat is None or lng is None:
        return None
    try:
        f_lat, f_lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= f_lat <= 90 and -180 <= f_lng <= 180):
        return None
    return f_lat, f_lng


def leg_distance_km(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """两个站点间的直线距离（千米）；任一缺坐标返回 None。"""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    ca, cb = _stop_coords(a), _stop_coords(b)
    if ca is None or cb is None:
        return None
    return haversine_km(ca[0], ca[1], cb[0], cb[1])


def _is_backtrack(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any]) -> bool:
    """A→B→C 折返：C 明显折回 A 方向（走了远路又绕回来），而非继续前进。

    判定：dist(A,C) < dist(A,B) * 0.4（C 贴近起点）且 dist(B,C) > dist(A,B) * 0.6
    （B→C 仍是一段不短的路）→ 视为折返。
    """
    d_ab = leg_distance_km(a, b)
    d_bc = leg_distance_km(b, c)
    d_ac = leg_distance_km(a, c)
    if d_ab is None or d_bc is None or d_ac is None or d_ab <= 0:
        return False
    return d_ac < d_ab * 0.4 and d_bc > d_ab * 0.6


def check_day_stops(
    stops: list[dict[str, Any]],
    *,
    day_number: int = 1,
    max_leg_km: float = MAX_LEG_KM,
    max_leg_minutes: float = MAX_LEG_MINUTES,
    max_daily_km: float = MAX_DAILY_KM,
) -> dict[str, Any]:
    """单日站点序列的驾车校验。

    返回：
    {
      "day_number": 1,
      "total_km": float,          # 相邻站点实际可算距离之和（缺坐标段不计）
      "legs": [{"from","to","distance_km","drive_minutes"}],
      "issues": [CritiqueIssueSchema 兼容 dict],
      "passed": bool              # 无 critical 即通过（warning 不阻断）
    }
    """
    issues: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    total_km = 0.0

    for i, stop in enumerate(stops):
        if not isinstance(stop, dict):
            continue
        name = stop.get("name") or f"站点{i + 1}"
        if _stop_coords(stop) is None:
            issues.append({
                "severity": "warning",
                "category": "logistics",
                "message": f"Day {day_number} 站点「{name}」缺少坐标，无法校验驾驶距离",
                "suggestion": "补全站点经纬度后可启用自驾距离校验",
                "day_number": day_number,
            })
        if i == 0:
            continue
        prev = stops[i - 1]
        if not isinstance(prev, dict):
            continue
        prev_name = prev.get("name") or f"站点{i}"
        d = leg_distance_km(prev, stop)
        if d is None:
            continue
        minutes = estimate_drive_minutes(d)
        legs.append({"from": prev_name, "to": name, "distance_km": round(d, 1), "drive_minutes": minutes})
        total_km += d

        if d > max_leg_km:
            issues.append({
                "severity": "critical",
                "category": "geography",
                "message": (
                    f"Day {day_number} 站点「{prev_name}」→「{name}」单段驾车约 {d:.0f}km，"
                    f"超过 {max_leg_km:.0f}km 上限"
                ),
                "suggestion": f"把「{name}」调整到另一天，或拆成两天行程",
                "day_number": day_number,
            })
        elif minutes > max_leg_minutes:
            issues.append({
                "severity": "critical",
                "category": "geography",
                "message": (
                    f"Day {day_number} 站点「{prev_name}」→「{name}」驾车约 {minutes} 分钟，"
                    f"超过 {max_leg_minutes:.0f} 分钟上限"
                ),
                "suggestion": f"把「{name}」调整到另一天，避免单日长途赶路",
                "day_number": day_number,
            })

    if total_km > max_daily_km:
        issues.append({
            "severity": "critical",
            "category": "geography",
            "message": (
                f"Day {day_number} 累计驾驶约 {total_km:.0f}km，超过单日 {max_daily_km:.0f}km 上限"
            ),
            "suggestion": "减少当日站点数，或把部分站点拆到相邻天",
            "day_number": day_number,
        })

    for i in range(1, len(stops) - 1):
        a, b, c = stops[i - 1], stops[i], stops[i + 1]
        if not (isinstance(a, dict) and isinstance(b, dict) and isinstance(c, dict)):
            continue
        if _is_backtrack(a, b, c):
            issues.append({
                "severity": "warning",
                "category": "geography",
                "message": (
                    f"Day {day_number} 路线「{a.get('name', '')}」→「{b.get('name', '')}」"
                    f"→「{c.get('name', '')}」存在折返（绕回出发点方向）"
                ),
                "suggestion": "按地理位置排序站点，避免先走远再折回",
                "day_number": day_number,
            })

    return {
        "day_number": day_number,
        "total_km": round(total_km, 1),
        "legs": legs,
        "issues": issues,
        "passed": not any(i.get("severity") == "critical" for i in issues),
    }


def check_plan_driving(
    plan: dict[str, Any],
    **thresholds: Any,
) -> dict[str, Any]:
    """整个行程的自驾校验。

    返回：
    {
      "mode": "driving",
      "passed": bool,           # 所有天无 critical
      "critical_count": int,
      "total_km": float,        # 全部天累计可算驾驶里程
      "per_day": [check_day_stops 报告...],
      "issues": [全部 critical/warning 问题],
      "summary": str
    }
    """
    per_day: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    total_km = 0.0

    for day in plan.get("days") or []:
        report = check_day_stops(day.get("stops") or [], day_number=day.get("day_number", 0), **thresholds)
        per_day.append(report)
        total_km += report["total_km"]
        issues.extend(report["issues"])

    critical_count = sum(1 for i in issues if i.get("severity") == "critical")
    if critical_count:
        summary = f"自驾路线校验未通过：{critical_count} 个超距/超时问题"
    elif issues:
        summary = f"自驾路线可用（{len(issues)} 条注意项）"
    else:
        summary = "自驾路线校验通过"

    return {
        "mode": "driving",
        "passed": critical_count == 0,
        "critical_count": critical_count,
        "total_km": round(total_km, 1),
        "per_day": per_day,
        "issues": issues,
        "summary": summary,
    }
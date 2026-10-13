"""营业时间 / 游玩时长校验（TimeGate）：确定性规则库，零外部依赖。

背景（竞争分析结论）：
- iPlan.ai 商店差评「推荐到达即闭馆 25 分钟的景点」是「AI 行程时间不诚实」
  的翻车现场；10-10 竞品分析把「闭馆到达 / 路线 / 签证」事实错误升级为
  用户对 AI 规划的两大核心抱怨之一，甚至涉及安全（16 岁少年徒步被困悬崖）。
- 我们的「价格诚实」哲学（城市基准价 + 口径标注）需要扩展到时间维度：
  排程校验闭馆到达 / 单日过饱和，产出 warning + 调整建议。

设计决策（与 driving_service 同风格：纯函数、确定性、无 LLM）：
- POI 类目基准营业时段表 + 游玩时长表（规则库，先不接外部营业时间 API）；
- ``check_plan_time_gate`` 消费与 DrivingGate 相同的 plan dict（days/stops：
  name / stop_type / open_hours? / estimated_duration_minutes / visit_start?），
  输出结构与 CritiqueIssueSchema 兼容（severity/category/message/suggestion/
  day_number），可直接进入评审反馈链路与前端质检卡；
- 全部为 warning（建议级别），不设 critical —— 规则库是基准推断，
  真实营业时间以 POI 现场为准（诚实标注：basis=rule_based）；
- 未知类目不告警（规则不确定时保持沉默，绝不编造时间）；
- 校验两类问题：
  1. 闭馆到达：站点可推断闭馆时间且到达时刻 ≥ 闭馆 - 30min 缓冲 → warning；
  2. 单日过饱和：每日站点数 / 预估游玩时长合计超限 → warning（与 Plan B
     Relaxed 变体同一过满直觉，但独立阈值可调）。

字段约定（与 revise_service/Plan B 同构，均为可选）：
- stop.open_hours: 可选字符串，如 "09:00-18:00"（显式营业时间优先于规则库）
- stop.visit_start: 可选字符串，如 "14:00"（排程起点；缺省按一天起点推算）
- stop.estimated_duration_minutes: 可选 int（先生成后修订；缺省按类目基准）
"""
from __future__ import annotations

import re
from typing import Any

# ── 类目基准表（规则库）────────────────────────────────────────
# 文化/历史/公园类：09:00-18:00 是主流；博物馆/展馆常见 09:00-17:00；
# 购物中心/夜市更晚。真实营业时间以现场为准（basis=rule_based 诚实标注）。
OPEN_HOURS_BY_TYPE: dict[str, tuple[str, str]] = {
    "attraction": ("09:00", "18:00"),  # 景点/公园/文化场馆通用基准
    "museum": ("09:00", "17:00"),  # 博物馆/美术馆（细分）
    "park": ("06:00", "22:00"),  # 开放公园/绿地
    "shopping": ("10:00", "22:00"),  # 购物中心/商业街
    "night_market": ("17:00", "23:00"),  # 夜市/晚间集市
}
# 常见 stop_type（Plan schema：attraction/food/hotel）→ 基准表键。
_STOP_TYPE_TO_BASIS: dict[str, str] = {
    "attraction": "attraction",
    "food": "shopping",  # 餐饮按购物基准（10:00-22:00），宽口径不误伤
}

# 显式营业时间解析：支持 "09:00-18:00" / "9:00~18:00" / "09:00-18:00 (周一闭馆)" 等
_OPEN_HOURS_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-~至]\s*(\d{1,2}):(\d{2})")

# 闭馆缓冲（分钟）：到达时刻距闭馆不足此时长 → 告警「赶不上体验」
CLOSING_BUFFER_MINUTES = 30
# 单日过饱和阈值（与 Plan B Relaxed 同直觉，独立可调）
MAX_STOPS_PER_DAY = 5
MAX_PLAY_MINUTES_PER_DAY = 480  # 8 小时（景点本身游玩，不含交通）
# 一天排程起点（无 visit_start 时按此推算）
DAY_START = (9, 0)


def _parse_clock(value: str | None) -> tuple[int, int] | None:
    """解析 "HH:MM" → (hour, minute)；非法/None 返回 None。"""
    if not value:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def _parse_open_hours(value: str | None) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """解析 "09:00-18:00" → ((9,0),(18,0))；无法解析返回 None。"""
    if not value:
        return None
    m = _OPEN_HOURS_RE.search(value)
    if not m:
        return None
    o = _parse_clock(f"{m.group(1)}:{m.group(2)}")
    c = _parse_clock(f"{m.group(3)}:{m.group(4)}")
    if o is None or c is None:
        return None
    return o, c


def _minutes(hhmm: tuple[int, int]) -> int:
    """(hour, minute) → 当日分钟数。"""
    return hhmm[0] * 60 + hhmm[1]


def _stop_open_hours(stop: dict[str, Any], stop_type: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """站点营业时段：显式 open_hours 优先，否则类目规则库；未知类目返回 None。"""
    explicit = _parse_open_hours(stop.get("open_hours"))
    if explicit is not None:
        return explicit
    basis_key = _STOP_TYPE_TO_BASIS.get(stop_type) or stop_type
    basis = OPEN_HOURS_BY_TYPE.get(basis_key)
    if basis is None:
        return None
    o = _parse_clock(basis[0])
    c = _parse_clock(basis[1])
    if o is None or c is None:
        return None
    return o, c


def _stop_duration(stop: dict[str, Any], stop_type: str) -> int | None:
    """站点建议游玩时长（分钟）：显式字段优先，否则类目基准；未知返回 None。"""
    explicit = stop.get("estimated_duration_minutes")
    if explicit is not None:
        try:
            d = int(explicit)
        except (TypeError, ValueError):
            return None
        return d if d > 0 else None
    # 类目基准游玩时长（与 Plan B 的时长语义一致：站内体验，非交通）
    return {
        "attraction": 120,  # 2h
        "museum": 150,  # 2.5h（展馆）
        "park": 90,
        "food": 60,
        "hotel": 0,  # 住宿站点不计入游玩时长
    }.get(stop_type, 120)


def _day_start_clock(day: dict[str, Any]) -> tuple[int, int]:
    """一天的排程起点：站点 visit_start 优先，否则默认 9:00。"""
    for stop in day.get("stops") or []:
        if not isinstance(stop, dict):
            continue
        v = _parse_clock(stop.get("visit_start"))
        if v is not None:
            return v
    return DAY_START


def check_plan_time_gate(plan: dict[str, Any]) -> dict[str, Any]:
    """行程级时间校验（TimeGate）：闭馆到达 + 单日过饱和。

    与 driving_service.check_plan_driving 同风格返回：
    {
      "passed": bool,          # 无 warning 即通过
      "issues": [...],         # CritiqueIssueSchema 兼容（severity=warning）
      "critical_count": 0,     # 恒 0（时间校验不语压倒排程）
      "warning_count": int,
      "summary": str,
    }
    """
    issues: list[dict[str, Any]] = []
    days = plan.get("days") or []

    # ── 单日过饱和：站点数 / 游玩时长合计超限（与 Plan B Relaxed 同直觉）──
    for day in days:
        if not isinstance(day, dict):
            continue
        stops = [s for s in (day.get("stops") or []) if isinstance(s, dict)]
        if not stops:
            continue
        day_no = day.get("day_number")

        if len(stops) > MAX_STOPS_PER_DAY:
            issues.append({
                "severity": "warning",
                "category": "schedule",
                "message": (
                    f"Day {day_no} 安排了 {len(stops)} 个站点，超过建议上限 "
                    f"{MAX_STOPS_PER_DAY} 个，节奏可能过满"
                ),
                "suggestion": f"考虑把其中 {len(stops) - MAX_STOPS_PER_DAY} 个站点移到相邻日或精简",
                "day_number": day_no,
            })

        play_total = 0
        for stop in stops:
            d = _stop_duration(stop, stop.get("stop_type") or "attraction")
            if d:
                play_total += d
        if play_total > MAX_PLAY_MINUTES_PER_DAY:
            over = play_total - MAX_PLAY_MINUTES_PER_DAY
            issues.append({
                "severity": "warning",
                "category": "schedule",
                "message": (
                    f"Day {day_no} 景点游玩时长合计约 {play_total} 分钟，"
                    f"超过建议上限 {MAX_PLAY_MINUTES_PER_DAY} 分钟（约 8 小时）"
                ),
                "suggestion": f"压缩或移出约 {over} 分钟（约 {round(over / 60, 1)} 小时）的站点",
                "day_number": day_no,
            })

    # ── 闭馆到达：到达时刻 ≥ 闭馆 - 缓冲 → 告警「赶不上体验」──
    for day in days:
        if not isinstance(day, dict):
            continue
        stops = [s for s in (day.get("stops") or []) if isinstance(s, dict)]
        if not stops:
            continue
        day_no = day.get("day_number")
        cursor = _minutes(_day_start_clock(day))

        for stop in stops:
            stop_type = stop.get("stop_type") or "attraction"
            hours = _stop_open_hours(stop, stop_type)
            duration = _stop_duration(stop, stop_type) or 0

            visit_start = _parse_clock(stop.get("visit_start"))
            arrival = _minutes(visit_start) if visit_start is not None else cursor

            if hours is not None:
                close = _minutes(hours[1])
                if arrival >= close - CLOSING_BUFFER_MINUTES:
                    issues.append({
                        "severity": "warning",
                        "category": "schedule",
                        "message": (
                            f"「{stop.get('name') or '站点'}」到达约 {arrival // 60:02d}:{arrival % 60:02d}"
                            f"，距闭馆 {hours[1][0]:02d}:{hours[1][1]:02d} 不足 {CLOSING_BUFFER_MINUTES} 分钟"
                            + (f"（建议游玩约 {duration} 分钟）" if duration else "")
                        ),
                        "suggestion": "建议把该站点安排在当天更早时段，或换到营业时间更晚的同类地点",
                        "day_number": day_no,
                    })

            # 游完该站 → 下一站到达时刻（含站内时长；站点间交通不在本规则库） 
            if duration:
                cursor += duration

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "critical_count": 0,
        "warning_count": len(issues),
        "summary": (
            "时间校验通过（营业时间/节奏）" if not issues
            else f"时间校验发现 {len(issues)} 个提示（闭馆到达/单日过满）"
        ),
    }
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

体力负荷提示（task-exertion-check，2026-10-22 扩展）：
- 新浪横测点名「AI 做不好体力/天气预判」：华山估算 2h vs 实际 7h 为反例；
  Wonderplan 给带孩子的家庭推荐 night bar 为同质翻车。
- 与 OPEN_HOURS_BY_TYPE 同思路：EXERTION_BY_TYPE 体力系数表（类目 → 单位强度），
  单日累计体力负荷 = Σ（站点建议时长 × 强度系数），超阈值 → warning。
- 高强度站点（登山/徒步/暴走）提示「实际耗时可能显著上浮」，
  复用 timegate-card 前端透出通道，basis=rule_based 诚实标注。
- 天气实时数据零凭证做不了，明确不做（README 诚实清单已声明）。

字段约定（与 revise_service/Plan B 同构，均为可选）：
- stop.open_hours: 可选字符串，如 "09:00-18:00"（显式营业时间优先于规则库）
- stop.visit_start: 可选字符串，如 "14:00"（排程起点；缺省按一天起点推算）
- stop.estimated_duration_minutes: 可选 int（先生成后修订；缺省按类目基准）
"""
from __future__ import annotations

import re
from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t

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

# ── 体力负荷系数表（task-exertion-check）────────────────────────
# 新浪横测点名「AI 做不好体力/天气预判」——华山估算 2h 实际 7h 为反例。
# 与 OPEN_HOURS_BY_TYPE 同风格的确定性规则库：类目 → 单位强度系数。
# 系数语义：相对「常规观光 1.0」的体力消耗倍率；单日累计 = Σ(时长 × 系数)。
# 真实体力消耗因人而异（basis=rule_based 诚实标注），只做提示不做裁决。
# ⚠️ StopSchema.type 只有 attraction/food/hotel 三值（schemas/plan.py Literal），
#    所以独立类目永远无法从 stop_type 命中 → 用「名称关键词」识别高强度站点
#    （华山/黄山/登山/徒步/爬山/索道/徒步路线等），与「显式字段优先 + 规则库推断」
#    哲学一致；系数仅供内部计算与文案展示，不扩展 schema 契约。
EXERTION_BY_TYPE: dict[str, float] = {
    "hiking": 2.5,       # 登山/徒步：体力消耗最大的类目（华山 2h→实际 7h 同源直觉）
    "trekking": 2.5,     # 徒步/越野
    "mountain": 2.2,     # 名山景区（含台阶/缆车混合）
    "adventure": 2.0,    # 探险/户外运动（攀岩/漂流/ATV）
    "sports": 1.8,       # 运动场馆（滑雪/骑行等）
    "theme_park": 1.6,   # 主题乐园（暴走型）
    "water_park": 1.5,   # 水上乐园
    "zoo": 1.3,          # 动物园/野生动物园（户外步行多）
    "park": 1.2,         # 大型公园/园林（比常规景点多走）
    "attraction": 1.0,   # 常规观光（基准）
    "museum": 0.8,       # 博物馆/美术馆（室内为主，体力消耗低）
    "shopping": 0.6,     # 购物/商业街（轻走）
    "food": 0.4,         # 餐饮（坐下为主）
    "hotel": 0.0,        # 住宿不计体力
}
# 高强度站点阈值：达到此系数即提示「实际耗时可能显著上浮」
HIGH_EXERTION_THRESHOLD = 1.8
# 单日体力负荷上限（分钟当量）：超过提示当日体力偏大，建议拆分/减负
MAX_EXERTION_POINTS_PER_DAY = 720  # 8h × 1.5 体力强度的心理上限

# 高强度站点识别（名称关键词规则库，零 schema 改动）：
# StopSchema.type 只有 attraction/food/hotel，无法区分「登山/博物馆」，
# 所以用名称关键词推断（华山/黄山/武夷山等名山 + 徒步/雪山/漂流等动词）；
# 排除词优先（山下古镇/老山城火锅/中山陵等含「山」但非高强度的场景）。
# 真实体力消耗因人而异，规则只做提示不做裁决（basis=rule_based）。
_HIGH_EXERTION_KEYWORDS: dict[str, float] = {
    "徒步": 2.5, "登山": 2.5, "爬山": 2.5, "攀岩": 2.5, "溯溪": 2.5,
    "雪山": 2.2,                                # 玉龙雪山/梅里雪山（先于「山」后缀命中）
    "漂流": 2.0, "越野": 2.0, "探险": 2.0, "峡谷": 2.0, "栈道": 2.0,
    "滑雪": 1.8, "骑行": 1.8,
    "峰": 2.2,                                  # 飞来峰/玉女峰/莲花峰（山岳特征）
}
_EXERTION_EXCLUDE_KEYWORDS: tuple[str, ...] = (
    "山下", "山脚", "山城", "山房", "山庄", "山居",
    "陵", "烤肉", "火锅", "餐厅", "酒店", "民宿",
)
# 名山后缀（「XX山」如华山/黄山/武夷山/武功山 → 山岳强度）
_MOUNTAIN_SUFFIX_COEF = 2.2

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


def _stop_type_by_name(stops: list[dict[str, Any]], name: str) -> str:
    """按站点名找回其 stop_type（用于高强度站点提示的系数展示）。"""
    for s in stops:
        if s.get("name") == name:
            return s.get("stop_type") or "attraction"
    return "attraction"


def _stop_exertion_coef(stop: dict[str, Any]) -> float:
    """站点体力系数：名称关键词规则库推断（零 schema 改动）。

    优先级：排除词（山下/山庄/餐厅…）→ 0；动作词（徒步/登山/滑雪…）→ 对应系数；
    名山后缀（XX山，如华山/玉龙雪山）→ 山岳系数；否则按类目基准（attraction 1.0
    / museum 0.8 / food 0.4 / hotel 0.0）。真实体力消耗因人而异（basis=rule_based）。
    """
    stop_type = stop.get("stop_type") or "attraction"
    name = str(stop.get("name") or "")
    if not name:
        # 无名站点：退回类目基准
        return EXERTION_BY_TYPE.get(stop_type, 1.0)
    for w in _EXERTION_EXCLUDE_KEYWORDS:
        if w in name:
            return 0.0
    for w, coef in _HIGH_EXERTION_KEYWORDS.items():
        if w in name:
            return coef
    if name.endswith("山"):
        return _MOUNTAIN_SUFFIX_COEF
    # 类目基准（世界级博物馆/餐饮等属低强度）
    return EXERTION_BY_TYPE.get(stop_type, 1.0)


def _day_start_clock(day: dict[str, Any]) -> tuple[int, int]:
    """一天的排程起点：站点 visit_start 优先，否则默认 9:00。"""
    for stop in day.get("stops") or []:
        if not isinstance(stop, dict):
            continue
        v = _parse_clock(stop.get("visit_start"))
        if v is not None:
            return v
    return DAY_START


def check_plan_time_gate(plan: dict[str, Any], locale: str = "zh-CN") -> dict[str, Any]:
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
    locale = normalize_locale(locale)
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
                    t(locale, "timegate.msg.too_many",
                      day=day_no, n=len(stops), max=MAX_STOPS_PER_DAY)
                ),
                "suggestion": t(locale, "timegate.suggest.too_many", n=len(stops) - MAX_STOPS_PER_DAY),
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
                    t(locale, "timegate.msg.play_long",
                      day=day_no, min=play_total, max=MAX_PLAY_MINUTES_PER_DAY)
                ),
                "suggestion": t(locale, "timegate.suggest.play_long", min=over, h=round(over / 60, 1)),
                "day_number": day_no,
            })

        # ── 体力负荷（task-exertion-check）：单日累计超限 + 高强度站点提示 ──
        exertion_total = 0
        high_stops: list[str] = []  # 高强度站点名（系数 ≥ 阈值）
        for stop in stops:
            stop_type = stop.get("stop_type") or "attraction"
            duration = _stop_duration(stop, stop_type) or 0
            coef = _stop_exertion_coef(stop)  # 名称关键词规则库推断
            points = duration * coef
            exertion_total += points
            if coef >= HIGH_EXERTION_THRESHOLD and points > 0:
                high_stops.append(stop.get("name") or t(locale, "timegate.stop.fallback"))
        if exertion_total > MAX_EXERTION_POINTS_PER_DAY:
            over = exertion_total - MAX_EXERTION_POINTS_PER_DAY
            issues.append({
                "severity": "warning",
                "category": "schedule",
                "message": (
                    t(locale, "timegate.msg.exertion_high",
                      day=day_no, pts=int(exertion_total), max=MAX_EXERTION_POINTS_PER_DAY)
                ),
                "suggestion": t(locale, "timegate.suggest.exertion_high",
                                 min=int(over), names="、".join(high_stops) if high_stops else ""),
                "day_number": day_no,
            })
        elif high_stops:
            # 未超总负荷但有高强度站点 → 提示「实际耗时可能显著上浮」
            spot_coef = _stop_exertion_coef(next(
                (s for s in stops if (s.get("name") or "") == high_stops[0]), {}
            ))
            issues.append({
                "severity": "warning",
                "category": "schedule",
                "message": (
                    t(locale, "timegate.msg.exertion_spot",
                      day=day_no, names="、".join(high_stops),
                      coef=spot_coef)
                ),
                "suggestion": t(locale, "timegate.suggest.exertion_spot",
                                 names="、".join(high_stops)),
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
                    extra = (
                        t(locale, "timegate.msg.arrive_close.play", min=duration)
                        if duration else ""
                    )
                    issues.append({
                        "severity": "warning",
                        "category": "schedule",
                        "message": (
                            t(locale, "timegate.msg.arrive_close",
                              name=stop.get("name") or t(locale, "timegate.stop.fallback"),
                              arrive=f"{arrival // 60:02d}:{arrival % 60:02d}",
                              close=f"{hours[1][0]:02d}:{hours[1][1]:02d}",
                              buffer=CLOSING_BUFFER_MINUTES,
                              extra=extra)
                        ),
                        "suggestion": t(locale, "timegate.suggest.arrive_close"),
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
            t(locale, "timegate.summary.pass") if not issues
            else t(locale, "timegate.summary.warn", n=len(issues))
        ),
    }
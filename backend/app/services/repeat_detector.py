"""重复站点确定性查重（RepeatGate）：同一地点重复安排 → warning。

背景（竞品分析 2026-11-13 MonkeyEatingMango 356 行程量化研究，模式 4）：
- 研究实证：169 天/5.1% 的规划日带「同一地点重复安排」；3 天行程重复率
  6.2% vs 15 天以上 56.2%；57% 重复落在相邻两天内；第 9 天重复率 21.1%；
  重复行程中 93% 同时有时间错（与 TimeGate 缺陷共现）。
- 我们此前无专责确定性查重器（planner 只靠提示词约束，无代码级复核），
  研究中重复随行程长度飙升且与时间错共现，值得独立规则库复核。

设计决策（与 time_validation / dynamic_facts 同风格：纯函数、确定性、无 LLM）：
- ``check_plan_repeat_gate`` 消费 plan dict（days/stops：name / type? /
  stop_type? / is_transfer?），输出与 CritiqueIssueSchema 兼容的 issues
  （severity=warning / category=schedule / message / suggestion /
  day_number / basis=rule_based）。
- 归一化：去空白 + 小写（与 favorite_spots normalize_spot_key 同源）；
  「同 POI 别名」= 一个归一 key 是另一个的子串（如「西湖」vs「西湖风景区」）。
- 窗口规则（对齐研究 57% 主战场）：
  - 同天重复 / 相邻两天重复 → 始终检测；
  - 远端重复（间隔 ≥2 天）→ 仅长行程（总天数 ≥10）提示（长行程放大：
    研究 15 天以上重复率 56.2%，远端重复拖累节奏并常与时间错共现）。
- 刻意跳过：酒店住宿（同一酒店连住是正常行为，重复不等于错误）、
  交通占位（is_transfer=True 或名称含「交通占位」/「(transfer)」）、空名。
- 全部为 warning（建议级别），basis=rule_based 诚实标注；只提示不阻断。

字段约定（与 TimeGate / DynamicFacts 同构，均为可选）：
- stop.name: 站点名（归一化后查重；空名跳过）
- stop.type / stop.stop_type: 站点类型（"hotel" → 跳过住宿重复）
- stop.is_transfer: 交通占位标记（True → 跳过）
"""
from __future__ import annotations

import re
from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t

# 长行程阈值（天）：≥ 该阈值则远端重复也检测（研究 15 天以上重复率 56.2%）
LONG_TRIP_DAY_THRESHOLD = 10
# 远端重复 = 两天间隔 ≥ 2 天
FAR_REPEAT_GAP = 2

# 交通占位名称标记（多城市段间占位 stop_type=attraction，靠名称后缀识别）
_TRANSFER_MARKERS = ("交通占位", "(transfer)", "（transfer）", "前往")


def normalize_stop_key(name: str) -> str:
    """归一化去重键：去空白 + 小写（与 favorite_spots normalize_spot_key 同源）。"""
    return re.sub(r"\s+", "", name or "").lower()


def _is_skip(stop: dict[str, Any]) -> bool:
    """跳过不参与查重的站点：酒店住宿 / 交通占位 / 空名。"""
    name = str(stop.get("name") or "").strip()
    if not name:
        return True
    stop_type = stop.get("stop_type") or stop.get("type") or ""
    if stop_type == "hotel":
        return True
    if stop.get("is_transfer"):
        return True
    lowered = name.lower()
    if any(marker in lowered for marker in _TRANSFER_MARKERS):
        return True
    return False


def _same_poi(k1: str, k2: str) -> bool:
    """同 POI 判定：归一 key 相等，或一个包含另一个（别名，如「西湖」vs「西湖风景区」）。

    仅当较短 key 长度 ≥ 2 时启用子串判定，避免「一环」与「二环路」这类
    单字公共前缀误合并；子串判定只用于别名，不跨天合并多个别名站点。
    """
    if k1 == k2:
        return True
    if len(k1) >= 2 and len(k2) >= 2:
        return k1 in k2 or k2 in k1
    return False


def check_plan_repeat_gate(plan: dict[str, Any], locale: str = "zh-CN") -> dict[str, Any]:
    """行程级重复站点查重：同地点重复安排 → warning。

    与 check_plan_time_gate / check_plan_dynamic_facts 同风格返回：
    {
      "passed": bool,
      "issues": [...],         # CritiqueIssueSchema 兼容（severity=warning）
      "critical_count": 0,
      "warning_count": int,
      "summary": str,
    }
    """
    locale = normalize_locale(locale)
    issues: list[dict[str, Any]] = []
    days = plan.get("days") or []
    total_days = len([d for d in days if isinstance(d, dict) and d.get("stops")])
    long_trip = total_days >= LONG_TRIP_DAY_THRESHOLD

    # 收集 (day_number, index, key, name) —— 保持原始顺序，配对取先出现者
    entries: list[tuple[int, int, str, str]] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        day_no = day.get("day_number")
        if day_no is None:
            day_no = 0
        stops = [s for s in (day.get("stops") or []) if isinstance(s, dict)]
        for idx, stop in enumerate(stops):
            if _is_skip(stop):
                continue
            name = str(stop.get("name") or "").strip()
            key = normalize_stop_key(name)
            if not key:
                continue
            entries.append((day_no, idx, key, name))

    reported: set[str] = set()  # 已提示过的地点 key（同一地点只报一次）
    for i in range(len(entries)):
        d1, i1, k1, n1 = entries[i]
        for j in range(i + 1, len(entries)):
            d2, i2, k2, n2 = entries[j]
            if not _same_poi(k1, k2):
                continue
            gap = abs(d2 - d1) if (d1 is not None and d2 is not None) else FAR_REPEAT_GAP
            if gap == 0:
                rtype = "same_day"
            elif gap == 1:
                rtype = "adjacent"
            else:
                if not long_trip:
                    continue  # 短行程远端重复不提示（不误伤换城重游）
                rtype = "far"

            # 去重：该地点任一端已提示过 → 整组跳过（如 3 连排只报 1 次）
            if k1 in reported and k2 in reported:
                continue
            reported.add(k1)
            reported.add(k2)

            if rtype == "same_day":
                msg_key = "repeatgate.msg.same_day"
                sugg_key = "repeatgate.suggest.same_day"
            elif rtype == "adjacent":
                msg_key = "repeatgate.msg.adjacent"
                sugg_key = "repeatgate.suggest.adjacent"
            else:
                msg_key = "repeatgate.msg.far"
                sugg_key = "repeatgate.suggest.far"

            message = t(
                locale, msg_key,
                name=n1, day=d1,
                other=n2, day2=d2,
            )
            issues.append({
                "severity": "warning",
                "category": "schedule",
                "message": message,
                "suggestion": t(locale, sugg_key, name=n1, day=d1, other=n2, day2=d2),
                "day_number": d1,
                "basis": "rule_based",
            })

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "critical_count": 0,
        "warning_count": len(issues),
        "summary": (
            t(locale, "repeatgate.summary.pass") if not issues
            else t(locale, "repeatgate.summary.warn", n=len(issues))
        ),
    }
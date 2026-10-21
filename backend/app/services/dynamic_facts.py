"""动态事实校验（Dynamic Facts）：行程日期 × POI 特例规则表。

背景（竞品分析 2026-10-19 罗马九工具实测）：
- 全行业在「单一动态事实」（免费周日 / 临时闭馆 / 节假日）集体翻车——
  Mindtrip 漏 Colosseum 免费周日且列错闭馆时间，只有 ChatGPT(web) 答对；
- 我们的 open-hours 规则库（time_validation）同样缺动态层：类目基准是静态的，
  无法感知「每月第一个周日免票」「周一闭馆」「公共假日闭馆」这类日期相关的例外。

设计决策（与 time_validation / driving_service 同风格：纯函数、确定性、无 LLM）：
- ``DATE_EXCEPTION_RULES``：日期特例规则表（站点名关键词 → 规则）。
  规则类型：weekly_day（周一闭馆类）/ monthly（每月特定日免票/闭馆）/
  holiday（公共假日闭馆）。
- ``check_plan_dynamic_facts`` 消费 plan dict（days/stops：name / date? / day_number）
  外加行程日期上下文，输出与 CritiqueIssueSchema 兼容的 issues（severity=warning）。
- 信号语义：
  -「闭馆日」type=closed → 强烈建议改期（该站点当天不可访问）；
  -「免票日」type=free → 提示可省钱（当天免费开放，建议核对）；
  -「周一闭馆」type=weekly → 若行程日期落在周一且站点通常周一闭馆 → warning。
- 全部为 warning（建议级别），basis=rule_based 诚实标注（规则表是维护性知识，
  非实时数据源；接真实动态源需凭证（Google Flights 需登录/高德无此接口/Amadeus
  付费），本实现为运营侧可维护的零凭证路线）。

字段约定（与 TimeGate 同构，均为可选）：
- day.date: 可选 YYYY-MM-DD（行程具体日期；缺省跳过日期相关规则）
- stop.name: 站点名（关键词匹配规则表；未知站点保持沉默）
- stop.open_hours: 显式营业时间（含「周一闭馆」等字样时跳过同名规则，避免双报）
"""
from __future__ import annotations

import re
from datetime import date as _Date
from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t

# ── 日期特例规则表（规则库，运营侧可维护）────────────────────────
# 类型语义：
#   weekly  → 每周固定日闭馆（如周一闭馆的博物馆）；闭馆日 = 该星期几
#   monthly → 每月第 N 个星期几（如每月第一个周日免票）；用 occurrence=N 表达
#   holiday → 公共假日闭馆（用 Chinese holidays 关键词匹配；规则库只覆盖常见）
# 每条规则可选标注 note（如「建议核对」），诚实口径：真实开放情况以官方为准。
DATE_EXCEPTION_RULES: list[dict[str, Any]] = [
    # ── 周一闭馆（博物馆/展馆惯例）──────────────────────
    {
        "keywords": ("故宫", "博物院"),
        "type": "weekly",
        "day_of_week": 0,  # 0=周一
        "closed": True,
        "note": "周一闭馆（法定节假日除外）",
    },
    {
        "keywords": ("国家博物馆", "国博"),
        "type": "weekly",
        "day_of_week": 0,
        "closed": True,
        "note": "周一闭馆（法定节假日除外）",
    },
    {
        "keywords": ("美术馆", "艺术馆", "博物馆", "科技馆", "规划馆"),
        "type": "weekly",
        "day_of_week": 0,
        "closed": True,
        "note": "多数展馆周一闭馆",
    },
    # ── 每月特定日免票（博物馆月度免费开放惯例）──────────
    {
        "keywords": ("博物馆",),
        "type": "monthly_free",
        "occurrence": 1,  # 每月第一个周日
        "day_of_week": 6,  # 0=周一, 6=周日
        "closed": False,
        "note": "部分博物馆每月第一个周日免费开放",
    },
    # ── 节假日闭馆/调整（公共假日惯例，覆盖常见大节）──────
    {
        "keywords": ("故宫", "博物院", "博物馆", "展馆", "景区"),
        "type": "holiday",
        "holiday": ("元旦", "春节", "清明", "劳动节", "端午", "中秋", "国庆"),
        "closed": False,
        "note": "法定节假日部分场馆开放时间调整或需预约",
    },
]

# 中文星期序（用于文案展示，i18n 文案直接用 day_of_week 数字 + 模板）
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 星期几 → 数字（0=周一）
_WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}

# 常见假日关键词（显示用）
_HOLIDAY_CN = ("元旦", "春节", "清明", "劳动节", "端午", "中秋", "国庆")

# 显式 open_hours 中含「周一闭馆」「周一休」等 → 视为已声明特例，跳过规则
_WEEKLY_CLOSED_RE = re.compile(r"周[一二三四五六日天]\s*(闭馆|休|休息|不开|不开放)")
# 显式 open_hours 中含「节假日」→ 视为已声明节假日调整
_HOLIDAY_RE = re.compile(r"节|假|特别")


def _parse_iso_date(value: Any) -> _Date | None:
    """解析 YYYY-MM-DD / date 对象 → date；非法/None 返回 None。"""
    if isinstance(value, _Date):
        return value
    if isinstance(value, str):
        try:
            return _Date.fromisoformat(value.strip())
        except ValueError:
            return None
    # datetime / 其他 → 尝试 str 化后解析
    try:
        return _Date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None


def _weekly_closed(open_hours: str | None) -> int | None:
    """显式 open_hours 中声明的工作日闭馆（如「周一闭馆」）→ 返回星期几，无则 None。"""
    if not open_hours:
        return None
    m = _WEEKLY_CLOSED_RE.search(open_hours)
    if not m:
        return None
    day_cn = m.group(0)[1]  # 「周一闭馆」的第二个字符是「一」→ 星期几
    return _WEEKDAY_MAP.get(day_cn)


def _match_rules(name: str, open_hours: str | None) -> list[dict[str, Any]]:
    """站点名 → 命中的规则列表（排除已在 open_hours 里声明的特例）。

    语义：如果 open_hours 已声明「周一闭馆」等，说明用户已掌握该站点开放情况，
    此时**该站点所有 weekly 规则都跳过**（避免双报「周一闭馆」）；holiday 规则
    独立判断（名称含 博物馆/展馆/景区 且未声明节假日调整 → 提示）。
    """
    if not name:
        return []
    hits: list[dict[str, Any]] = []
    weekly_declared = _weekly_closed(open_hours) is not None
    holiday_declared = bool(_HOLIDAY_RE.search(open_hours or ""))
    for rule in DATE_EXCEPTION_RULES:
        if not any(k in name for k in rule.get("keywords", ())):
            continue
        # 已声明过工作日闭馆 → 跳过所有 weekly 规则（用户已知晓）
        if rule["type"] == "weekly" and weekly_declared:
            continue
        # 已声明节假日调整 → 跳过 holiday 规则
        if rule["type"] == "holiday" and holiday_declared:
            continue
        hits.append(rule)
    return hits


def check_plan_dynamic_facts(plan: dict[str, Any], locale: str = "zh-CN") -> dict[str, Any]:
    """行程级动态事实校验：日期特例规则表命中 → warning。

    与 check_plan_time_gate 同风格返回：
    {
      "passed": bool,
      "issues": [...],         # CritiqueIssueSchema 兼容（severity=warning）
      "critical_count": 0,
      "warning_count": int,
      "summary": str,
    }

    issues 字段：
    - severity: "warning"
    - category: "schedule"（排程真实性）
    - message: 具体提示（含站点名/日期/规则说明）
    - suggestion: 建议（改期/核对）
    - day_number: int（有则填）
    - basis: "rule_based"
    """
    locale = normalize_locale(locale)
    issues: list[dict[str, Any]] = []
    days = plan.get("days") or []

    for day in days:
        if not isinstance(day, dict):
            continue
        stops = [s for s in (day.get("stops") or []) if isinstance(s, dict)]
        if not stops:
            continue
        day_no = day.get("day_number")
        day_date = _parse_iso_date(day.get("date"))

        for stop in stops:
            name = str(stop.get("name") or "")
            if not name:
                continue
            open_hours = stop.get("open_hours")
            if not isinstance(open_hours, str):
                open_hours = None
            rules = _match_rules(name, open_hours)
            if not rules:
                continue

            for rule in rules:
                rtype = rule["type"]
                msg_args: dict[str, Any] = {"name": name}

                if rtype == "weekly":
                    dow = rule["day_of_week"]
                    # 无具体日期 → 提示「通常周一闭馆，请核对具体日期」
                    if day_date is None:
                        msg_args.update(day=_WEEKDAY_CN[dow], note=rule.get("note", ""))
                        message = t(locale, "dynfacts.msg.weekly.undated", **msg_args)
                        suggestion = t(locale, "dynfacts.suggest.weekly")
                    elif day_date.weekday() == dow:
                        msg_args.update(
                            date=day_date.isoformat(),
                            day=_WEEKDAY_CN[dow],
                            note=rule.get("note", ""),
                        )
                        message = t(locale, "dynfacts.msg.weekly.hit", **msg_args)
                        suggestion = t(locale, "dynfacts.suggest.weekly.hit")
                    else:
                        # 落在非闭馆日 → 静默（规则库不误伤）
                        continue

                elif rtype == "monthly_free":
                    occ = rule.get("occurrence", 1)
                    dow = rule["day_of_week"]
                    if day_date is None:
                        msg_args.update(
                            occ=occ, day=_WEEKDAY_CN[dow], note=rule.get("note", ""),
                        )
                        message = t(locale, "dynfacts.msg.free.undated", **msg_args)
                        suggestion = t(locale, "dynfacts.suggest.free")
                    else:
                        # 每月第 occ 个星期几
                        first = _Date(day_date.year, day_date.month, 1)
                        first_dow = first.weekday()
                        offset = (dow - first_dow) % 7
                        nth_date = _Date(
                            day_date.year, day_date.month, 1 + offset + (occ - 1) * 7
                        )
                        if nth_date.month != day_date.month:
                            # 该月不存在第 occ 个星期几 → 跳过
                            continue
                        if day_date == nth_date:
                            msg_args.update(
                                date=day_date.isoformat(),
                                day=_WEEKDAY_CN[dow],
                                occ=occ,
                                note=rule.get("note", ""),
                            )
                            message = t(locale, "dynfacts.msg.free.hit", **msg_args)
                            suggestion = t(locale, "dynfacts.suggest.free.hit")
                        else:
                            continue

                elif rtype == "holiday":
                    # 公共假日判断：用「公历日期落在常见假日窗口」的近似规则。
                    # 规则库诚实口径：不精确判断调休，只提示「节假日附近开放时间
                    # 可能调整，建议核对」；holiday 关键词仅用于文案。
                    holidays = rule.get("holiday") or _HOLIDAY_CN
                    if day_date is None:
                        msg_args.update(
                            holidays="、".join(holidays),
                            note=rule.get("note", ""),
                        )
                        message = t(locale, "dynfacts.msg.holiday.undated", **msg_args)
                        suggestion = t(locale, "dynfacts.suggest.holiday")
                    elif _is_chinese_holiday(day_date):
                        msg_args.update(
                            date=day_date.isoformat(),
                            holidays="、".join(holidays),
                            note=rule.get("note", ""),
                        )
                        message = t(locale, "dynfacts.msg.holiday.hit", **msg_args)
                        suggestion = t(locale, "dynfacts.suggest.holiday.hit")
                    else:
                        continue
                else:
                    continue

                issues.append({
                    "severity": "warning",
                    "category": "schedule",
                    "message": message,
                    "suggestion": suggestion,
                    "day_number": day_no,
                    "basis": "rule_based",
                })

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "critical_count": 0,
        "warning_count": len(issues),
        "summary": (
            t(locale, "dynfacts.summary.pass") if not issues
            else t(locale, "dynfacts.summary.warn", n=len(issues))
        ),
    }


def _is_chinese_holiday(dt: _Date) -> bool:
    """公历日期是否落在常见中国法定假日窗口（近似规则，不精确调休）。

    覆盖：元旦（1/1）、春节（农历难精算 → 用 1 月底-2 月中窗口近似）、
    清明（4/4-4/6）、劳动节（5/1-5/5）、端午（6 月，窗口 6/1-6/15 近似）、
    中秋（9 月底-10 月初窗口）、国庆（10/1-10/7）。
    诚实口径：规则库不精确判断调休，只做「节假日附近」提示。
    """
    m, d = dt.month, dt.day
    if (m == 1 and 1 <= d <= 3) or (m == 1 and 25 <= d <= 31):  # 元旦 + 春节前
        return True
    if m == 2 and 1 <= d <= 20:  # 春节（农历，窗口近似）
        return True
    if m == 4 and 4 <= d <= 6:  # 清明
        return True
    if m == 5 and 1 <= d <= 5:  # 劳动节
        return True
    if 6 <= m <= 8 and 1 <= d <= 20:  # 端午/暑期高峰（近似）
        return True
    if m == 10 and 1 <= d <= 7:  # 国庆
        return True
    return False
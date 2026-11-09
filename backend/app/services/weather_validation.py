"""天气感知排程校验（WeatherGate）：确定性规则库，零外部依赖。

背景（task-weather-gate-eval，2026-11-09 竞品分析）：
- Journelyx v3.2.1（2026-11-08 更新）把「15 天预报 + 降雨 >60% 自动室内替代」
  做成付费卖点；圆周旅迹在行程日旁标天气——天气是 2026 横测反复点名的
  「AI 做不好天气预判」缺口（新浪横测：体力/天气两大致命短板）。
- 我们 agent 规划期已有 query_weather（高德 AMAP / wttr.in 降级，零常态化成本），
  但**不进排程约束、行中无天气展示**：天气数据只进过 LLM context，之后即弃。

设计决策（与 time_validation / dynamic_facts 同风格：纯函数、确定性、无 LLM）：
- ``check_plan_weather_gate`` 消费 plan dict（days/stops + 可选 weather：
  {"days": [{"date", "text_day", "temp_max", "temp_min"}], "source"}），
  输出结构与 CritiqueIssueSchema 兼容（severity=warning），直接进质检 warning 链路；
- 只做**提示不裁决**（basis=rule_based 诚实标注，与 TimeGate 同哲学）：
  预报不是事实，绝不把 weather warning 当 critical；
- 两类告警：
  1. 雨天（text_day 含 雨/雪/雷 关键词）→ 当天户外站点提示「室内替代建议」；
  2. 酷暑（temp_max ≥ 阈值）→ 当天提示「补水/避开正午暴晒」；
- 规则保守：**没有对应日期的天气数据 → 保持沉默**（绝不编造天气）；
- 天气随修订重算（revise_service 复用与 time_gate 相同的注入点）。

天气卡（行中「今日视图」）：
- ``weather_card`` 纯函数：从 live_snapshot 的 context 提取当日天气摘要，
  供前端行中卡片展示；失败/无数据 → None（绝不伪造）。

字段约定（与 TimeGate 同构，均为可选）：
- plan.weather: 可选 dict，来自采集阶段 weather_agent 的归一化产物
  （{city, days: [{date, text_day, temp_max, temp_min}], source}），
  结构由 app.services.weather_service.query_weather 保证；
- day.date: 可选 ISO 字符串（天气按日匹配；无日期日无法匹配 → 跳过）。

注意与 task-open-hours-real-eval 同构的「预报不可作硬约束」口径：
天气是预报不是事实，本门控只产出 warning + 室内替代建议，绝不阻断排程。
"""
from __future__ import annotations

import re
from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t

# ── 天气告警阈值（规则库，零凭证） ─────────────────────────────
# 雨天关键词：预报 text_day 命中任一即视为当天有降水（含雪/雷暴）。
RAIN_KEYWORDS: tuple[str, ...] = (
    "雨", "雪", "雷", "阵", "雹", "霰",
)
# 酷暑阈值：日最高温 ≥ 35°C 视为酷暑（气象学高温预警标准口径）。
HOT_TEMP_THRESHOLD: int = 35
# 户外类目：雨天建议室内替代时命中（food/hotel 不受影响）。
OUTDOOR_STOP_TYPES: tuple[str, ...] = ("attraction", "park")
# 已声明「室内」的站点名关键词：命中即视为已有室内替代，不再重复提醒。
_INDOOR_EXEMPT_KEYWORDS: tuple[str, ...] = (
    "博物馆", "美术馆", "展览", "科技馆", "图书馆", "室内", "商城", "购物", "水族馆", "剧院",
)

_RAIN_RE = re.compile("|".join(RAIN_KEYWORDS))


def _parse_iso_date(value: Any) -> Any | None:
    """解析 YYYY-MM-DD → date；非法/None 返回 None。"""
    from datetime import date as _Date

    if isinstance(value, _Date):
        return value
    if isinstance(value, str):
        try:
            return _Date.fromisoformat(value.strip())
        except ValueError:
            return None
    try:
        return _Date.fromisoformat(str(value).strip()[:10])
    except (ValueError, TypeError):
        return None


def _day_weather(plan: dict[str, Any], day_date: Any) -> dict[str, Any] | None:
    """按日期匹配 plan.weather.days 中的预报条目；无匹配返回 None。"""
    weather = plan.get("weather") or {}
    if not isinstance(weather, dict):
        return None
    for item in weather.get("days") or []:
        if not isinstance(item, dict):
            continue
        if _parse_iso_date(item.get("date")) == _parse_iso_date(day_date):
            return item
    return None


def _is_rainy(text_day: Any) -> bool:
    """预报白天天气文本是否含降水关键词（含雪/雷暴）。"""
    if not text_day:
        return False
    return bool(_RAIN_RE.search(str(text_day)))


def _temp_max(item: dict[str, Any]) -> int | None:
    """提取日最高温（int）；非法/缺失返回 None。"""
    raw = item.get("temp_max")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_outdoor_without_indoor(stop: dict[str, Any]) -> bool:
    """户外站点且名称未声明室内替代 → True（雨天提醒对象）。"""
    stop_type = stop.get("stop_type") or "attraction"
    if stop_type not in OUTDOOR_STOP_TYPES:
        return False
    name = str(stop.get("name") or "")
    if not name:
        return True
    return not any(kw in name for kw in _INDOOR_EXEMPT_KEYWORDS)


def check_plan_weather_gate(plan: dict[str, Any], locale: str = "zh-CN") -> dict[str, Any]:
    """行程级天气校验（WeatherGate）：雨天/酷暑 → 室内替代建议 warning。

    与 check_plan_time_gate 同风格返回：
    {
      "passed": bool,          # 无 warning 即通过
      "issues": [...],         # CritiqueIssueSchema 兼容（severity=warning）
      "critical_count": 0,     # 恒 0（天气是预报，绝不阻断排程）
      "warning_count": int,
      "summary": str,
    }

    issues 字段：
    - severity: "warning"
    - category: "schedule"（排程真实性）
    - message: 具体提示（含日期/站点名/天气描述）
    - suggestion: 建议（室内替代 / 补水防暑）
    - day_number: int（有则填）
    - basis: "weather_forecast"（诚实标注——预报非事实）
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
        day_date = day.get("date")
        w = _day_weather(plan, day_date)
        # 该日无天气数据 → 保持沉默（绝不编造/过报）
        if w is None:
            continue

        # ── 雨天：户外站点 → 室内替代建议 ──
        if _is_rainy(w.get("text_day")):
            outdoor = [s.get("name") or t(locale, "weathergate.stop.fallback")
                       for s in stops if _is_outdoor_without_indoor(s)]
            if outdoor:
                issues.append({
                    "severity": "warning",
                    "category": "schedule",
                    "message": t(
                        locale, "weathergate.msg.rain",
                        date=w.get("date") or "", day=day_no,
                        cond=w.get("text_day") or "",
                        names="、".join(outdoor[:5]),
                    ),
                    "suggestion": t(locale, "weathergate.suggest.rain"),
                    "day_number": day_no,
                })

        # ── 酷暑：高温提示 ──
        tmax = _temp_max(w)
        if tmax is not None and tmax >= HOT_TEMP_THRESHOLD:
            issues.append({
                "severity": "warning",
                "category": "schedule",
                "message": t(
                    locale, "weathergate.msg.hot",
                    date=w.get("date") or "", day=day_no, temp=tmax,
                ),
                "suggestion": t(locale, "weathergate.suggest.hot"),
                "day_number": day_no,
            })

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "critical_count": 0,
        "warning_count": len(issues),
        "summary": (
            t(locale, "weathergate.summary.pass")
            if not issues
            else t(locale, "weathergate.summary.warn", n=len(issues))
        ),
    }


def weather_card(plan: dict[str, Any], *, day_date: Any = None, locale: str = "zh-CN") -> dict[str, Any] | None:
    """行中「今日天气卡」摘要：消费 plan 的 weather 快照，供前端行中卡片展示。

    返回 None（无天气数据/无匹配日期）→ 前端不渲染天气卡（绝不伪造）。
    返回结构：{"date", "text_day", "temp_min", "temp_max", "source", "summary"}
    """
    locale = normalize_locale(locale)
    weather = plan.get("weather") or {}
    if not isinstance(weather, dict):
        return None
    if day_date is not None:
        item = _day_weather(plan, day_date)
    else:
        item = (weather.get("days") or [{}])[0] if weather.get("days") else None
    if not isinstance(item, dict):
        return None
    out = {
        "date": item.get("date"),
        "text_day": item.get("text_day"),
        "temp_min": item.get("temp_min"),
        "temp_max": item.get("temp_max"),
        "source": weather.get("source"),
    }
    tmax = _temp_max(item)
    if _is_rainy(item.get("text_day")):
        out["summary"] = t(locale, "weathergate.card.rain")
    elif tmax is not None and tmax >= HOT_TEMP_THRESHOLD:
        out["summary"] = t(locale, "weathergate.card.hot", temp=tmax)
    else:
        out["summary"] = t(locale, "weathergate.card.normal",
                            text=item.get("text_day") or "")
    return out
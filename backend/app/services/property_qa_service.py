"""行程内结构化事实问答服务（task-property-qa-eval）。

背景（Expedia Property Expert 产品化 ground QA）：行程有结构化字段
（open_hours / rating / estimated_cost / budget / quality warning），
但只有单向透出（timegate-card），无问答。本服务提供**最小版规则问答**：

- 答案全部来自结构化字段，零 LLM（防编造）；
- 数据源双轨：
  1. ``plan_data`` 快照（最新 TripPlan）：days[].stops[].open_hours（显式营业时间）、
     budget（预算汇总）、quality / time_gate / dynamic_facts / weather_gate（质检预警）；
  2. ``trip.days[].stops[]`` 落库站点：details.rating（高德真实评分）、
     estimated_cost / estimated_duration_minutes（估算字段）。
- 无数据 → available=false + basis=none 的 unknown 文案，**绝不编造数字/时间**；
- basis 标注：explicit（字段真实存在）/ rule_based（类目规则库推断）/ none（无数据）。

防编造口径（与 time_validation / dynamic_facts 同风格）：
- 营业时间：显式 open_hours 优先；无显式值时按类目规则库（OPEN_HOURS_BY_TYPE）
  推断并标注 rule_based；两者皆无 → unknown（绝不猜具体时刻）。
- 预算：trip.budget（用户预设）与 plan_data.budget.total_estimated（AI 汇总估算）
  分开返回，标注口径。
- 评分：只答 details.rating（真实采集），无 → unknown（绝不编评分）。
"""

from __future__ import annotations

import re
from typing import Any

from app.i18n.translations import t
from app.models import Trip, TripPlan

# ── 问题意图关键词（中文；按优先级匹配）────────────────────────
_HOURS_KEYS = ("几点关门", "几点开门", "营业时间", "开放时间", "几点开", "几点关", "什么时候关", "什么时候开", "关门", "开门", "开放到", "营业到", "hours", "open", "close")
_BUDGET_KEYS = ("预算", "还剩", "花了", "花费", "超支", "多少钱", "总价", "费用", "budget", "cost", "spend")
_WARNING_KEYS = ("警告", "预警", "提示", "注意", "问题", "warning", "为什么", "不合适", "有问题", "提醒")
_RATING_KEYS = ("评分", "几分", "好不好", "口碑", "rating", "score")
# 站点级价格强词：明确指向「某站点的票价」，应在 budget 之前匹配（否则
# 「西湖门票多少钱」会因含「多少钱」被判行程总预算）。
_STRONG_PRICE_KEYS = ("门票", "票价", "price", "ticket")
_PRICE_KEYS = ("价格", "贵不贵", "贵吗", "便宜", "贵")
_DURATION_KEYS = ("多久", "时长", "几个小时", "玩多久", "duration", "多长时间", "几小时")


def _stop_basis(stop: dict[str, Any], key: str) -> str:
    """站点字段的来源标注：显式非空 → explicit，否则 rule_based/none。"""
    if stop.get(key) is not None and str(stop.get(key)) != "":
        return "explicit"
    return "none"


def _plan_stops(plan_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从 plan_data 快照取全部站点（带显式 open_hours 等规划字段）。"""
    if not isinstance(plan_data, dict):
        return []
    return [
        s for d in plan_data.get("days") or []
        if isinstance(d, dict)
        for s in (d.get("stops") or []) if isinstance(s, dict)
    ]


def _db_stops(trip: Trip) -> list[dict[str, Any]]:
    """从落库的 trip.days[].stops[] 取站点（details.rating 等 ORM 字段）。"""
    out: list[dict[str, Any]] = []
    for day in trip.days:
        for stop in day.stops:
            out.append({
                "name": stop.name,
                "stop_type": stop.stop_type,
                "estimated_cost": stop.estimated_cost,
                "estimated_duration_minutes": stop.estimated_duration_minutes,
                "details": stop.details or {},
            })
    return out


def _find_stop(plan_data: dict[str, Any] | None, trip: Trip, name: str) -> dict[str, Any] | None:
    """按名称在 plan_data / 落库站点中找站点（归一化匹配）。"""
    target = name.strip().lower()
    for s in _plan_stops(plan_data):
        if target and target in str(s.get("name") or "").lower():
            return s
    for s in _db_stops(trip):
        if target and target in str(s.get("name") or "").lower():
            return s
    return None


def _hours_answer(stop: dict[str, Any], stop_type: str, locale: str) -> dict[str, Any]:
    """营业时间答案：显式 open_hours → explicit；否则类目规则库 → rule_based；无 → unknown。"""
    explicit = stop.get("open_hours")
    if explicit:
        return {
            "available": True,
            "answer": t(locale, "propertyqa.hours.explicit", hours=explicit),
            "basis": "explicit",
            "detail": {"open_hours": explicit},
        }
    from app.services.time_validation import _STOP_TYPE_TO_BASIS, OPEN_HOURS_BY_TYPE, _parse_clock

    basis_key = _STOP_TYPE_TO_BASIS.get(stop_type) or stop_type
    basis = OPEN_HOURS_BY_TYPE.get(basis_key)
    if basis is not None:
        o, c = basis
        o_clock = _parse_clock(o)
        c_clock = _parse_clock(c)
        if o_clock and c_clock:
            return {
                "available": True,
                "answer": t(locale, "propertyqa.hours.rule", open=o, close=c),
                "basis": "rule_based",
                "detail": {"open_hours": f"{o}-{c}"},
            }
    return {
        "available": False,
        "answer": t(locale, "propertyqa.unknown"),
        "basis": "none",
        "detail": {},
    }


def _budget_answer(trip: Trip, plan_data: dict[str, Any] | None, locale: str) -> dict[str, Any]:
    """预算答案：预设预算 + AI 汇总估算，分开返回（口径诚实）。"""
    detail: dict[str, Any] = {}
    if trip.budget is not None:
        detail["preset_budget"] = trip.budget
    plan_budget = None
    if isinstance(plan_data, dict) and isinstance(plan_data.get("budget"), dict):
        plan_budget = plan_data["budget"]
    if plan_budget is not None:
        detail["estimated_total"] = plan_budget.get("total_estimated")
        detail["by_type"] = plan_budget.get("by_type")
        detail["currency"] = plan_budget.get("currency")
    if not detail:
        return {
            "available": False,
            "answer": t(locale, "propertyqa.unknown"),
            "basis": "none",
            "detail": {},
        }
    parts: list[str] = []
    if trip.budget is not None:
        parts.append(t(locale, "propertyqa.budget.preset", budget=trip.budget))
    if plan_budget is not None and plan_budget.get("total_estimated") is not None:
        parts.append(
            t(locale, "propertyqa.budget.estimated",
              total=plan_budget["total_estimated"])
        )
    basis = "explicit" if trip.budget is not None else "rule_based"
    return {
        "available": True,
        "answer": "；".join(parts),
        "basis": basis,
        "detail": detail,
    }


def _warnings_answer(plan_data: dict[str, Any] | None, locale: str) -> dict[str, Any]:
    """质检预警答案：汇总 time_gate / dynamic_facts / weather_gate 的 warning issues。"""
    warnings: list[dict[str, Any]] = []
    for key in ("time_gate", "dynamic_facts", "weather_gate"):
        gate = (plan_data or {}).get(key) if isinstance(plan_data, dict) else None
        if not isinstance(gate, dict):
            continue
        for issue in gate.get("issues") or []:
            if isinstance(issue, dict):
                warnings.append({
                    "source": key,
                    "message": issue.get("message"),
                    "suggestion": issue.get("suggestion"),
                    "severity": issue.get("severity", "warning"),
                })
    if not warnings:
        return {
            "available": True,  # 无预警也是确定性事实（可答「没有发现预警」）
            "answer": t(locale, "propertyqa.warning.none"),
            "basis": "rule_based",
            "detail": {"warnings": []},
        }
    lines = [w["message"] for w in warnings[:5] if w.get("message")]
    return {
        "available": True,
        "answer": "；".join(lines),
        "basis": "rule_based",
        "detail": {"warnings": warnings},
    }


def _rating_answer(stop_db: dict[str, Any] | None, locale: str) -> dict[str, Any]:
    """评分答案：只答 details.rating（真实采集），无 → unknown。"""
    rating = None
    if stop_db and isinstance(stop_db.get("details"), dict):
        rating = stop_db["details"].get("rating")
    if rating is None:
        return {
            "available": False,
            "answer": t(locale, "propertyqa.rating.unknown"),
            "basis": "none",
            "detail": {},
        }
    return {
        "available": True,
        "answer": t(locale, "propertyqa.rating.value", rating=rating),
        "basis": "explicit",
        "detail": {"rating": rating},
    }


def _price_answer(stop: dict[str, Any] | None, locale: str) -> dict[str, Any]:
    """站点费用答案：estimated_cost（估算字段），无 → unknown。"""
    cost = stop.get("estimated_cost") if stop else None
    if cost is None:
        return {
            "available": False,
            "answer": t(locale, "propertyqa.unknown"),
            "basis": "none",
            "detail": {},
        }
    return {
        "available": True,
        "answer": t(locale, "propertyqa.price.value", cost=cost),
        "basis": "explicit",
        "detail": {"estimated_cost": cost},
    }


def _duration_answer(stop: dict[str, Any] | None, stop_type: str, locale: str) -> dict[str, Any]:
    """游玩时长答案：显式字段优先；否则类目基准（rule_based）；无 → unknown。"""
    explicit = stop.get("estimated_duration_minutes") if stop else None
    if explicit:
        return {
            "available": True,
            "answer": t(locale, "propertyqa.duration.value", minutes=explicit),
            "basis": "explicit",
            "detail": {"minutes": explicit},
        }
    basis_minutes = {
        "attraction": 120, "museum": 150, "park": 90, "food": 60, "hotel": 0,
    }.get(stop_type)
    if basis_minutes:
        return {
            "available": True,
            "answer": t(locale, "propertyqa.duration.rule", minutes=basis_minutes),
            "basis": "rule_based",
            "detail": {"minutes": basis_minutes},
        }
    return {
        "available": False,
        "answer": t(locale, "propertyqa.unknown"),
        "basis": "none",
        "detail": {},
    }


def _match_intent(question: str) -> str | None:
    """解析问题意图：hours / budget / warning / rating / price / duration / None。

    优先级：rating（明确问评分）→ hours（时间词）→ budget（预算词）→
    warning（预警词）→ price（价格词，需与 budget 区分：站点级问价）→ duration。
    """
    q = question.lower()
    if any(k in q for k in _RATING_KEYS):
        return "rating"
    if any(k in q for k in _HOURS_KEYS):
        return "hours"
    if any(k in q for k in _STRONG_PRICE_KEYS):
        return "price"
    if any(k in q for k in _BUDGET_KEYS):
        return "budget"
    if any(k in q for k in _WARNING_KEYS):
        return "warning"
    if any(k in q for k in _PRICE_KEYS):
        return "price"
    if any(k in q for k in _DURATION_KEYS):
        return "duration"
    return None


def _extract_target(question: str, plan_data: dict[str, Any] | None, trip: Trip) -> str | None:
    """在站点名里找问题里提到的目标；找不到返回 None（行程级问题）。"""
    for s in [*_plan_stops(plan_data), *_db_stops(trip)]:
        name = str(s.get("name") or "")
        if name and name in question:
            return name
    return None


def answer_property_question(
    trip: Trip,
    plan: TripPlan | None,
    question: str,
    *,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """入口：回答一个行程内结构化事实问题。

    返回 PropertyQaOut 字段 dict：
    question / matched_type / target / available / answer / basis / detail。
    """
    plan_data = plan.plan_data if plan is not None else None
    intent = _match_intent(question)
    if intent is None:
        return {
            "question": question,
            "matched_type": "unknown",
            "target": None,
            "available": False,
            "answer": t(locale, "propertyqa.unknown.intent"),
            "basis": "none",
            "detail": {},
        }

    target_name = _extract_target(question, plan_data, trip)
    # 语义修正：预算意图但问题同时命中站点名 + 站点价格词（如「西湖门票多少钱」）
    # → 转站点价格（用户问的是该站点的花费，不是行程总预算）。
    if intent == "budget" and target_name and any(k in question.lower() for k in ("门票", "价格", "票价", "price", "ticket")):
        intent = "price"
    stop_plan = None
    stop_db = None
    if target_name:
        stop_plan = next(
            (s for s in _plan_stops(plan_data) if target_name in str(s.get("name") or "")),
            None,
        )
        stop_db = next(
            (s for s in _db_stops(trip) if target_name in str(s.get("name") or "")),
            None,
        )

    if intent == "budget":
        result = _budget_answer(trip, plan_data, locale)
        result.update({"question": question, "matched_type": "budget", "target": None})
        return result
    if intent == "warning":
        result = _warnings_answer(plan_data, locale)
        result.update({"question": question, "matched_type": "warning", "target": None})
        return result
    if intent == "rating":
        result = _rating_answer(stop_db, locale)
        result.update({
            "question": question,
            "matched_type": "rating",
            "target": target_name,
        })
        return result

    stop = stop_plan or stop_db
    stop_type = (stop_plan or {}).get("stop_type") or (stop_db or {}).get("stop_type") or "attraction"
    if intent == "hours":
        if target_name is None:
            # 未指明具体站点 / 站点不在行程数据中 → 不回答（防编造）
            result = {
                "available": False,
                "answer": t(locale, "propertyqa.unknown"),
                "basis": "none",
                "detail": {},
            }
        else:
            result = _hours_answer(stop or {}, stop_type, locale)
        result.update({"question": question, "matched_type": "hours", "target": target_name})
        return result
    if intent == "price":
        if target_name is None:
            result = {
                "available": False,
                "answer": t(locale, "propertyqa.unknown"),
                "basis": "none",
                "detail": {},
            }
        else:
            result = _price_answer(stop, locale)
        result.update({"question": question, "matched_type": "price", "target": target_name})
        return result
    if intent == "duration":
        if target_name is None:
            result = {
                "available": False,
                "answer": t(locale, "propertyqa.unknown"),
                "basis": "none",
                "detail": {},
            }
        else:
            result = _duration_answer(stop, stop_type, locale)
        result.update({"question": question, "matched_type": "duration", "target": target_name})
        return result

    # 不可达（intent 已全覆盖）
    return {
        "question": question,
        "matched_type": "unknown",
        "target": None,
        "available": False,
        "answer": t(locale, "propertyqa.unknown.intent"),
        "basis": "none",
        "detail": {},
    }


def collect_property_facts(
    trip: Trip,
    plan: TripPlan | None,
    *,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """不带 q 时的「当前可答事实清单」（facts + budget + warnings + suggestions）。"""
    plan_data = plan.plan_data if plan is not None else None
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for s in [*_plan_stops(plan_data), *_db_stops(trip)]:
        name = str(s.get("name") or "")
        if not name or (name, "hours") in seen:
            continue
        seen.add((name, "hours"))
        hours = _hours_answer(s, s.get("stop_type") or "attraction", locale)
        facts.append({
            "kind": "hours",
            "target": name,
            "value": hours["answer"] if hours["available"] else None,
            "basis": hours["basis"],
            "available": hours["available"],
        })
    for s in _db_stops(trip):
        name = str(s.get("name") or "")
        if not name or (name, "rating") in seen:
            continue
        seen.add((name, "rating"))
        rating = _rating_answer(s, locale)
        facts.append({
            "kind": "rating",
            "target": name,
            "value": rating["answer"] if rating["available"] else None,
            "basis": rating["basis"],
            "available": rating["available"],
        })

    budget = _budget_answer(trip, plan_data, locale)
    warnings = _warnings_answer(plan_data, locale)
    suggestions = [
        t(locale, "propertyqa.suggest.hours"),
        t(locale, "propertyqa.suggest.budget"),
        t(locale, "propertyqa.suggest.warning"),
        t(locale, "propertyqa.suggest.rating"),
    ]
    return {
        "trip_id": trip.id,
        "title": trip.title,
        "destination": trip.destination,
        "start_date": trip.start_date,
        "end_date": trip.end_date,
        "facts": facts[:20],  # 上限 20 条，避免超大行程撑爆响应
        "budget": budget["detail"],
        "warnings": warnings["detail"].get("warnings", []),
        "suggestions": suggestions,
    }
"""酒店入住办理指引生成（HotelCheckinAgent 的模板基座 + LLM 润色）。

设计（HITL 边界 / 隐私 / 兜底）：
- 本模块以「确定性模板」为主，LLM 仅在模板基础上做「润色/补充说明」；
- 绝不收集、不存储任何证件号码（身份证/护照等）——指引只说明「需要带什么」，
  不要求用户提供敏感信息；
- LLM 失败（或未配置）→ 纯模板兜底照常输出，绝不会让该能力静默失效；
- 输出结构固定，前端可直接渲染；
- 文案语言化（i18n 方案 A）：模板文案（docs/steps/disclaimer/transit/时间）
  全部经 t(locale, ...) 取当前语种；LLM 润色 prompt 也按 locale 输出。

输出结构（与 PlanSchema.checkin 兼容）：
{
  "hotel_name": str,
  "hotel_address": str | None,
  "check_in_time": "通常 14:00 后",
  "check_out_time": "通常 12:00 前",
  "docs_required": [str],        # 需要携带的证件/材料清单
  "steps": [str],                # 办理入住步骤
  "transit": [str],              # 从最近站点/机场到酒店的交通建议（确定性）
  "disclaimer": str,             # 免责声明（以酒店实际规则为准）
  "source": "template" | "llm"   # 生成方式
}
"""
from __future__ import annotations

from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t


def _default_docs(locale: str = "zh-CN") -> list[str]:
    return [
        t(locale, "checkin.docs.default.1"),
        t(locale, "checkin.docs.default.2"),
    ]


def _default_steps(locale: str = "zh-CN") -> list[str]:
    return [t(locale, f"checkin.steps.{i}") for i in range(1, 6)]


def _default_disclaimer(locale: str = "zh-CN") -> str:
    return t(locale, "checkin.disclaimer")


def _template_checkin(
    hotel_name: str,
    *,
    address: str | None = None,
    transit_hints: list[str] | None = None,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """纯模板入住指引（LLM 不可用时兜底）。"""
    locale = normalize_locale(locale)
    return {
        "hotel_name": hotel_name,
        "hotel_address": address,
        "check_in_time": t(locale, "checkin.check_in_time"),
        "check_out_time": t(locale, "checkin.check_out_time"),
        "docs_required": _default_docs(locale),
        "steps": _default_steps(locale),
        "transit": transit_hints or [t(locale, "checkin.transit.generic")],
        "disclaimer": _default_disclaimer(locale),
        "source": "template",
    }


async def generate_checkin_guide(
    plan: dict[str, Any],
    *,
    provider: str = "auto",
    llm_timeout: float = 15.0,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """为定稿行程生成入住办理指引（模板基座 + LLM 可选润色）。

    - 从 plan 中确定「本次入住的酒店」：优先取行程内实际安排的酒店
      （days[].stops[] 中 type=hotel 的站点，即已安排住宿）；若行程中
      没有具体酒店，回退到 plan.hotels（酒店候选列表）第一家；再没有则用
      plan.destination 生成通用指引。
    - LLM 润色全程 try/except：任何失败都回退纯模板，绝不抛异常。
    - locale（i18n 方案 A）：模板文案语言；LLM 润色 prompt 亦按此语种。
    """
    locale = normalize_locale(locale)
    hotel = _pick_checkin_hotel(plan)
    if hotel is None:
        # 没有具体酒店：生成目的地级通用指引
        return {
            **_template_checkin(
                t(locale, "checkin.stay.name", destination=plan.get("destination", "")),
                locale=locale,
            ),
            "hotel_address": None,
        }

    hotel_name = hotel.get("name", "")
    address = hotel.get("address") or hotel.get("description") or None
    transit_hints = _transit_hints(plan, hotel, locale)

    base = _template_checkin(hotel_name, address=address, transit_hints=transit_hints, locale=locale)

    # LLM 润色：可选增强（失败回退模板）。超时/异常/无 provider 全部静默降级。
    try:
        from app.agent.providers import get_provider, invoke_with_resilience

        prov = get_provider(provider)
        from langchain_core.messages import HumanMessage, SystemMessage

        language_note = (
            "请用中文输出。"
            if locale == "zh-CN"
            else "Respond in English."
        )
        messages = [
            SystemMessage(
                content=(
                    "你是酒店入住办理助手。根据给定酒店与模板，输出一份更贴合实际的入住指引 JSON。\n"
                    "规则：\n"
                    "1. 不得编造具体政策（如确切入住时间、押金金额）；未知时保留模板默认值\n"
                    "2. 不得要求用户提供或输入证件号码等敏感信息，只说明需要携带什么\n"
                    "3. 只输出 JSON 对象，字段：hotel_name, hotel_address, check_in_time, "
                    "check_out_time, docs_required(list), steps(list), transit(list), disclaimer\n"
                    "4. 简短精炼，每项 1 句话\n"
                    f"5. {language_note}"
                )
            ),
            HumanMessage(
                content=(
                    f"酒店：{hotel_name}\n"
                    f"地址：{address or '未知'}\n"
                    f"所在城市：{plan.get('destination', '')}\n"
                    f"模板基线：{json_dumps(base)}\n"
                    "请输出润色后的入住指引 JSON。"
                )
            ),
        ]
        response = await invoke_with_resilience(prov, messages, providers=[prov])
        content = str(getattr(response, "content", ""))
        parsed = _extract_json(content)
        if isinstance(parsed, dict) and parsed.get("hotel_name"):
            # 合并：以 LLM 输出为主，但强制保留免责声明与来源标注
            parsed["disclaimer"] = _default_disclaimer(locale)
            parsed["source"] = "llm"
            return parsed
    except Exception:  # noqa: BLE001,S110 — LLM 润色失败静默降级模板（有意设计）
        pass

    return base


def _pick_checkin_hotel(plan: dict[str, Any]) -> dict[str, Any] | None:
    """确定「本次入住的酒店」。

    优先级（与「已安排住宿」语义一致）：
    1. 行程内实际安排的酒店：days[].stops[] 中 type=hotel 的站点；
    2. 酒店候选列表 plan.hotels 中第一家（兼容酒店信息未进入 days 的情况）；
    3. None → 调用方生成目的地级通用指引。

    注意优先级 1 优先于 2：候选列表只是「推荐/备选」，只有当行程里
    真的安排了住宿时，入住指引才应该显示那家酒店。
    """
    # 1) 行程内已安排的酒店站点（type=hotel）
    for day in plan.get("days") or []:
        for stop in day.get("stops") or []:
            if not isinstance(stop, dict):
                continue
            if stop.get("type") == "hotel" and stop.get("name"):
                return stop
    # 2) 酒店候选列表第一家（有名字的）
    for h in plan.get("hotels") or []:
        if isinstance(h, dict) and h.get("name"):
            return h
    return None


def _transit_hints(plan: dict[str, Any], hotel: dict[str, Any], locale: str = "zh-CN") -> list[str]:
    """基于定稿计划生成到酒店的交通建议（确定性规则）。

    简单启发式：若行程含机场/火车站站点（名称含「机场/站/高铁」），
    提示从枢纽到酒店；否则给通用建议。
    """
    locale = normalize_locale(locale)
    hubs: list[str] = []
    for day in plan.get("days") or []:
        for stop in day.get("stops") or []:
            name = (stop.get("name") or "") if isinstance(stop, dict) else ""
            if any(k in name for k in ("机场", "高铁站", "火车站", "汽车站")):
                hubs.append(name)
    if hubs:
        return [t(locale, "checkin.transit.hub", hub=hubs[0])]
    return [t(locale, "checkin.transit.generic")]


import json as _json


def json_dumps(value: Any) -> str:
    """工具内 JSON 序列化（避免循环 import）。"""
    return _json.dumps(value, ensure_ascii=False)


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出提取 JSON（容忍代码块/杂质）。"""
    if not text:
        return None
    text = text.strip()
    import re

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return _json.loads(text[start : end + 1])
    except _json.JSONDecodeError:
        return None
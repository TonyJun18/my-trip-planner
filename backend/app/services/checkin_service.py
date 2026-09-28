"""酒店入住办理指引生成（HotelCheckinAgent 的模板基座 + LLM 润色）。

设计（HITL 边界 / 隐私 / 兜底）：
- 本模块以「确定性模板」为主，LLM 仅在模板基础上做「润色/补充说明」；
- 绝不收集、不存储任何证件号码（身份证/护照等）——指引只说明「需要带什么」，
  不要求用户提供敏感信息；
- LLM 失败（或未配置）→ 纯模板兜底照常输出，绝不会让该能力静默失效；
- 输出结构固定，前端可直接渲染。

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

# 固定模板（确定性，不依赖 LLM）
_DEFAULT_DOCS = ["本人有效身份证原件（大陆居民）", "入住人实名登记所需证件（护照/港澳台通行证等，按身份选择）"]
_DEFAULT_STEPS = [
    "在酒店前台出示预订信息（姓名/订单号）与有效证件",
    "按酒店要求完成实名登记（未成年人需监护人陪同或按酒店政策）",
    "确认房型、入住人数与离店日期，领取房卡",
    "如需押金/预授权，确认金额与退还方式",
    "了解早餐时间、Wi-Fi 密码、退房时间等酒店服务信息",
]
_DEFAULT_DISCLAIMER = "以上为通用办理指引，实际以酒店前台公示规则为准（入住/退房时间、证件要求各酒店略有差异）。"


def _template_checkin(
    hotel_name: str,
    *,
    address: str | None = None,
    transit_hints: list[str] | None = None,
) -> dict[str, Any]:
    """纯模板入住指引（LLM 不可用时兜底）。"""
    return {
        "hotel_name": hotel_name,
        "hotel_address": address,
        "check_in_time": "通常 14:00 后",
        "check_out_time": "通常 12:00 前",
        "docs_required": list(_DEFAULT_DOCS),
        "steps": list(_DEFAULT_STEPS),
        "transit": transit_hints or ["从目的地交通枢纽打车/地铁前往酒店（以前端市内通勤建议为准）"],
        "disclaimer": _DEFAULT_DISCLAIMER,
        "source": "template",
    }


async def generate_checkin_guide(
    plan: dict[str, Any],
    *,
    provider: str = "auto",
    llm_timeout: float = 15.0,
) -> dict[str, Any]:
    """为定稿行程生成入住办理指引（模板基座 + LLM 可选润色）。

    - 从 plan.hotels（定稿酒店候选）取第一家有地址的酒店；找不到则用
      plan.destination 生成通用指引。
    - LLM 润色全程 try/except：任何失败都回退纯模板，绝不抛异常。
    """
    hotels = plan.get("hotels") or []
    hotel = None
    for h in hotels:
        if isinstance(h, dict) and h.get("name"):
            hotel = h
            break
    if hotel is None:
        # 没有具体酒店：生成目的地级通用指引
        return {
            **_template_checkin(f"{plan.get('destination', '目的地')}住宿"),
            "hotel_address": None,
            "disclaimer": _DEFAULT_DISCLAIMER,
        }

    hotel_name = hotel.get("name", "")
    address = hotel.get("address") or hotel.get("description") or None
    transit_hints = _transit_hints(plan, hotel)

    base = _template_checkin(hotel_name, address=address, transit_hints=transit_hints)

    # LLM 润色：可选增强（失败回退模板）。超时/异常/无 provider 全部静默降级。
    try:
        from app.agent.providers import get_provider, invoke_with_resilience

        prov = get_provider(provider)
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(
                content=(
                    "你是酒店入住办理助手。根据给定酒店与模板，输出一份更贴合实际的入住指引 JSON。\n"
                    "规则：\n"
                    "1. 不得编造具体政策（如确切入住时间、押金金额）；未知时保留模板默认值\n"
                    "2. 不得要求用户提供或输入证件号码等敏感信息，只说明需要携带什么\n"
                    "3. 只输出 JSON 对象，字段：hotel_name, hotel_address, check_in_time, "
                    "check_out_time, docs_required(list), steps(list), transit(list), disclaimer\n"
                    "4. 简短精炼，每项 1 句话"
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
            parsed["disclaimer"] = _DEFAULT_DISCLAIMER
            parsed["source"] = "llm"
            return parsed
    except Exception:  # noqa: BLE001,S110 — LLM 润色失败静默降级模板（有意设计）
        pass

    return base


def _transit_hints(plan: dict[str, Any], hotel: dict[str, Any]) -> list[str]:
    """基于定稿计划生成到酒店的交通建议（确定性规则）。

    简单启发式：若行程含机场/火车站站点（名称含「机场/站/高铁」），
    提示从枢纽到酒店；否则给通用建议。
    """
    hubs: list[str] = []
    for day in plan.get("days") or []:
        for stop in day.get("stops") or []:
            name = (stop.get("name") or "") if isinstance(stop, dict) else ""
            if any(k in name for k in ("机场", "高铁站", "火车站", "汽车站")):
                hubs.append(name)
    if hubs:
        return [f"从「{hubs[0]}」打车/地铁前往酒店，约 20-60 分钟（以实时路况为准）"]
    return ["从目的地交通枢纽打车/地铁前往酒店（以前端市内通勤建议为准）"]


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
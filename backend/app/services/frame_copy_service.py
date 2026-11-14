"""单日卡 AI 配文服务（frame-marketplace）。

设计哲学与 story_service / xhs_service 同源：
- **数据驱动**：配文只引用投影里的 checked 站点名与用户趣事（Stop.description /
  TripDay.note），未打卡的站点绝不进文案；
- **LLM 主路径 → 模板兜底 → 最终兜底**：LLM 全链失败不阻断出稿，source 诚实标注
  （llm/template）；无打卡数据返回 empty=true 引导先打卡，不硬编内容；
- **无发布副作用**：只产出文字，发布动作永远在用户手里（复制 → 跳转 App）。
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_STOPS_IN_COPY = 6
_MOMENTS_MAX_LINES = 6


def _context(trip: Any, projection: dict[str, Any]) -> str:
    """投喂 LLM 的确定性上下文（只来自投影）。"""
    stops = [s["name"] for s in (projection.get("stops") or [])][:_MAX_STOPS_IN_COPY]
    notes = [
        s["description"] for s in (projection.get("stops") or [])
        if s.get("description")
    ]
    lines = [
        f"目的地：{projection.get('destination') or ''}",
        f"第 {projection.get('day_number')} 天"
        + (f"（{projection['date']}）" if projection.get("date") else ""),
    ]
    if projection.get("day_note"):
        lines.append(f"当日主题：{projection['day_note']}")
    if stops:
        lines.append("已打卡站点：" + "、".join(stops))
    if notes:
        lines.append("途中最有趣的事：" + "；".join(notes))
    return "\n".join(lines)


_LLM_PROMPT = """你是旅行博主的好友，帮 TA 写一段可直接发布的社媒配文。
要求：
- 只使用提供的信息（目的地/日期/已打卡站点/趣事），绝不编造地名或情节；
- 语气自然真实，像朋友分享，不用夸张营销腔；
- 输出 JSON：{"title": "一句话标题", "body": "正文", "topics": ["话题", ...]}。
"""


def _parse_llm_json(content: str) -> dict[str, Any]:
    import json

    content = (content or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    data = json.loads(content)
    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not title or not body:
        raise ValueError("LLM 输出缺少 title/body")
    topics = [str(x).strip().lstrip("#") for x in (data.get("topics") or []) if str(x).strip()]
    return {"title": title, "body": body, "topics": topics[:8]}


async def _generate_with_llm(trip: Any, projection: dict[str, Any], provider_name: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agent.providers import get_provider, invoke_with_resilience

    provider = get_provider(provider_name)
    messages = [
        SystemMessage(content=_LLM_PROMPT),
        HumanMessage(content=_context(trip, projection)),
    ]
    response = await invoke_with_resilience(provider, messages, temperature=0.8)
    content = (getattr(response, "content", "") or "").strip()
    return _parse_llm_json(content)


def _template_xhs(projection: dict[str, Any]) -> dict[str, Any]:
    stops = [s["name"] for s in (projection.get("stops") or [])][:_MAX_STOPS_IN_COPY]
    day_note = projection.get("day_note") or ""
    notes = [s["description"] for s in (projection.get("stops") or []) if s.get("description")]
    dest = projection.get("destination") or "旅途中"

    title = f"{dest} 第{projection.get('day_number')}天打卡 ✅"
    lines = [f"今天在{dest}走了这些地方：", "・" + " → ".join(stops)] if stops else []
    if day_note:
        lines.append(day_note)
    if notes:
        lines.extend(f"✨ {n}" for n in notes[:3])
    topics = [dest, "旅行日记", "旅行打卡", "城市漫步"]
    return {"title": title, "body": "\n".join(lines), "topics": topics}


def _template_moments(projection: dict[str, Any]) -> dict[str, Any]:
    stops = [s["name"] for s in (projection.get("stops") or [])][:3]
    dest = projection.get("destination") or "旅途中"
    day_note = projection.get("day_note")
    notes = [s["description"] for s in (projection.get("stops") or []) if s.get("description")]

    lines = [f"{dest} 第{projection.get('day_number')}天。"]
    if stops:
        lines.append("、".join(stops) + "，都值得。")
    if day_note:
        lines.append(day_note)
    if notes:
        lines.append(notes[0])
    return {"title": "", "body": "\n".join(lines)[:_MOMENTS_MAX_LINES * 40], "topics": []}


_TEMPLATES = {"xhs": _template_xhs, "moments": _template_moments}


def _trip_context(trip: Any, projection: dict[str, Any]) -> str:
    """整程总结图配文上下文（只来自聚合投影）。"""
    stats = projection.get("stats") or {}
    lines = [
        f"目的地：{projection.get('destination') or ''}",
        f"行程日期：{projection.get('start_date') or ''} ~ {projection.get('end_date') or ''}",
        f"有打卡的天数：{stats.get('days_with_checkins', 0)} / {stats.get('total_days', 0)}",
        f"累计打卡站点：{stats.get('checked_stops', 0)}",
    ]
    for day in projection.get("days") or []:
        names = "、".join(s["name"] for s in (day.get("stops") or [])[:6])
        note = f"（{day['day_note']}）" if day.get("day_note") else ""
        lines.append(f"第 {day['day_number']} 天{note}：{names}")
    return "\n".join(lines)


_TRIP_LLM_PROMPT = """你是旅行博主的好友，帮 TA 写一段旅程总结配文（可直接发布）。
要求：
- 只使用提供的信息（目的地/天数/打卡站点/当日主题），绝不编造情节；
- 语气自然真实，像朋友回顾旅程，不夸张营销；
- 输出 JSON：{"title": "一句话标题", "body": "正文", "topics": ["话题", ...]}。
"""


def _template_trip_xhs(trip: Any, projection: dict[str, Any]) -> dict[str, Any]:
    stats = projection.get("stats") or {}
    dest = projection.get("destination") or "旅途中"
    days = stats.get("days_with_checkins", 0)
    stops = stats.get("checked_stops", 0)
    title = f"{dest} {days} 天，打卡 {stops} 站 ✅"
    body = f"这趟{dest}旅行，走了 {days} 天，打卡了 {stops} 个地方。"
    highlights = []
    for day in (projection.get("days") or [])[:3]:
        names = "、".join(s["name"] for s in (day.get("stops") or [])[:3])
        if names:
            highlights.append(f"D{day['day_number']}：{names}")
    if highlights:
        body += "\n" + "\n".join(highlights)
    return {"title": title, "body": body, "topics": [dest, "旅行总结", "旅行日记"]}


def _template_trip_moments(trip: Any, projection: dict[str, Any]) -> dict[str, Any]:
    stats = projection.get("stats") or {}
    dest = projection.get("destination") or "旅途中"
    days = stats.get("days_with_checkins", 0)
    stops = stats.get("checked_stops", 0)
    body = f"{dest} {days} 天，{stops} 个打卡点。\n每个地方都值得再来一次。"
    return {"title": "", "body": body, "topics": []}


_TRIP_TEMPLATES = {"xhs": _template_trip_xhs, "moments": _template_trip_moments}


async def build_trip_copy(
    trip: Any,
    projection: dict[str, Any],
    *,
    channel: str = "xhs",
    provider: str = "auto",
) -> dict[str, Any]:
    """生成整程总结图配文（聚合投影驱动，双路径降级）。"""
    if projection.get("empty"):
        fallback = _TRIP_TEMPLATES.get(channel, _template_trip_xhs)(trip, projection)
        return {
            "trip_id": trip.id,
            "day_id": None,
            "channel": channel,
            "empty": True,
            "title": fallback["title"],
            "body": fallback["body"],
            "topics": fallback["topics"],
            "source": "template",
        }

    fallback = _TRIP_TEMPLATES.get(channel, _template_trip_xhs)(trip, projection)
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from app.agent.providers import get_provider, invoke_with_resilience

        provider_obj = get_provider(provider)
        messages = [
            SystemMessage(content=_TRIP_LLM_PROMPT),
            HumanMessage(content=_trip_context(trip, projection)),
        ]
        response = await invoke_with_resilience(provider_obj, messages, temperature=0.8)
        generated = _parse_llm_json((getattr(response, "content", "") or "").strip())
        return {
            "trip_id": trip.id,
            "day_id": None,
            "channel": channel,
            "empty": False,
            **generated,
            "source": "llm",
        }
    except Exception as exc:  # noqa: BLE001 — LLM 全链失败不阻断出稿
        logger.warning("trip frame copy LLM 生成失败，降级模板: %s", exc)
        return {
            "trip_id": trip.id,
            "day_id": None,
            "channel": channel,
            "empty": False,
            **fallback,
            "source": "template",
        }



async def build_day_copy(
    trip: Any,
    projection: dict[str, Any],
    *,
    channel: str = "xhs",
    provider: str = "auto",
) -> dict[str, Any]:
    """生成单日卡配文。

    Returns:
        dict: {trip_id, day_id, channel, empty, title, body, topics, source}
        empty=True 表示无打卡数据（引导先打卡，不硬编内容）。
    """
    stops = projection.get("stops") or []
    if projection.get("empty") or not stops:
        fallback = _TEMPLATES.get(channel, _template_xhs)(projection)
        return {
            "trip_id": trip.id,
            "day_id": projection.get("day_id"),
            "channel": channel,
            "empty": True,
            "title": fallback["title"],
            "body": fallback["body"],
            "topics": fallback["topics"],
            "source": "template",
        }

    fallback = _TEMPLATES.get(channel, _template_xhs)(projection)
    try:
        generated = await _generate_with_llm(trip, projection, provider)
        return {
            "trip_id": trip.id,
            "day_id": projection.get("day_id"),
            "channel": channel,
            "empty": False,
            **generated,
            "source": "llm",
        }
    except Exception as exc:  # noqa: BLE001 — LLM 全链失败不阻断出稿
        logger.warning("frame copy LLM 生成失败，降级模板: %s", exc)
        return {
            "trip_id": trip.id,
            "day_id": projection.get("day_id"),
            "channel": channel,
            "empty": False,
            **fallback,
            "source": "template",
        }

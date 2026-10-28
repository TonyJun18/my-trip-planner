"""旅程故事服务（task-trip-story：晒图高光卡生成）。

设计哲学（与 xhs_service 同源，数据来自真实旅程投影）：
- **数据驱动**：故事基于 journey.projection + passport 徽章 + expense 汇总，
  只输出已记录的数据（打卡数/费用/徽章/站点名），无记录不推断；
- **LLM 主路径 → 模板兜底**：LLM 失败照常出稿（source 标注 llm/template）；
- **三类渠道模板**：小红书（标题/正文/话题）/ 朋友圈（短文案 + 封面卡 spec）/
  通用长图（HTML 卡片数据，前端渲染后可截图保存）；
- **PII 过滤**：story 只输出 name/金额/日期/徽章，凭证号/确认码绝不进文案；
- **空投影引导**：无打卡/无费用时不硬生成（返回 empty=true，前端引导先记一笔）。

产物结构（TripStoryOut）：
{
  "trip_id", "empty": bool,
  "channel": "xhs" | "moments" | "poster",
  "title", "body", "topics": [],
  "stats": {"destination", "days", "stops", "checked", "expense_total", "per_person", "badge_count"},
  "badges": [], "highlights": [],
  "source": "llm" | "template",
  "image_spec": {"width", "height", "ratio"}  // 封面卡规格（前端渲染用）
}
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.i18n import normalize_locale
from app.i18n.translations import t

logger = get_logger(__name__)


def _stats_from_projection(trip: Any, proj: dict[str, Any]) -> dict[str, Any]:
    """从投影 + trip 构造 stats（确定性，供模板与 LLM 共用）。"""
    stops = sum(len(d.stops or []) for d in (trip.days or []))
    return {
        "destination": trip.destination or "",
        "days": max(1, (trip.end_date - trip.start_date).days + 1),
        "stops": stops,
        "checked": proj.get("completed_stops", 0),
        "expense_total": round(proj.get("expense_total", 0.0), 2),
        "per_person": round(proj.get("per_person", 0.0), 2),
        "badge_count": len(proj.get("badges", [])),
        "phase": proj.get("phase", "upcoming"),
    }


def _badge_names(badges: list[dict[str, Any]]) -> list[str]:
    return [str(b.get("label") or b.get("key") or "") for b in badges if isinstance(b, dict)]


def _highlights_text(highlights: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for h in highlights or []:
        if isinstance(h, dict) and h.get("summary"):
            out.append(str(h["summary"]))
    return out[:5]


# ── 模板兜底（确定性，无 LLM） ────────────────────────────────
def _template_xhs(trip: Any, stats: dict[str, Any], badges: list[str], highlights: list[str]) -> dict[str, Any]:
    dest = stats["destination"] or trip.destination or ""
    body_lines = [f"【{dest} {stats['days']}天 {stats.get('stops', 0)}站 真实足迹】", ""]
    body_lines.append("这次旅行把每一步都记下来了：")
    if highlights:
        for h in highlights:
            body_lines.append(f"✅ {h}")
        body_lines.append("")
    if stats.get("expense_total"):
        body_lines.append(f"💸 总花费 {stats['expense_total']} 元（人均 {stats['per_person']} 元）")
    if badges:
        body_lines.append(f"🏅 集齐徽章：{'、'.join(badges)}")
    body_lines.append("")
    body_lines.append("全程用 AI 行程助手打卡记账，旅程有迹可循～")
    return {
        "title": f"{dest} {stats['days']}天旅行足迹",
        "body": "\n".join(body_lines),
        "topics": [dest, "旅行足迹", "行程打卡", "自由行"],
    }


def _template_moments(trip: Any, stats: dict[str, Any], badges: list[str], highlights: list[str]) -> dict[str, Any]:
    dest = stats["destination"] or trip.destination or ""
    lines = [f"{dest} {stats['days']}天，说走就走 ✈️"]
    if highlights:
        lines.append("行程高光：")
        for h in highlights[:3]:
            lines.append(f"· {h}")
    if stats.get("expense_total"):
        lines.append(f"总花费 {stats['expense_total']} 元")
    if badges:
        lines.append(f"🏅 {len(badges)} 枚旅程徽章")
    lines.append("")
    lines.append("#旅行 #足迹 #自由行")
    return {"title": f"{dest}之旅", "body": "\n".join(lines), "topics": []}


def _template_poster(trip: Any, stats: dict[str, Any], badges: list[str], highlights: list[str]) -> dict[str, Any]:
    dest = stats["destination"] or trip.destination or ""
    return {
        "title": f"{dest} {stats['days']}天 旅程回顾",
        "body": (
            f"从 {trip.start_date} 到 {trip.end_date}，共 {stats['stops']} 站，"
            f"打卡 {stats['checked']} 站，花费 {stats['expense_total']} 元。"
            f"徽章 {len(badges)} 枚。数据来自你的真实打卡与记账。"
        ),
        "topics": [],
    }


_TEMPLATES = {
    "xhs": _template_xhs,
    "moments": _template_moments,
    "poster": _template_poster,
}

_IMAGE_SPEC = {
    "xhs": {"width": 1080, "height": 1440, "ratio": "3:4"},
    "moments": {"width": 1080, "height": 1080, "ratio": "1:1"},
    "poster": {"width": 1080, "height": 1920, "ratio": "9:16"},
}

# LLM 只用行程上下文（不含凭证号等 PII）
_LLM_PROMPT = """你是一位旅行内容创作者。基于以下真实行程数据，写一篇适合社交分享的旅程回顾文案。

要求：
- 只使用提供的数据，不要编造没提到的景点、金额或经历
- 语言有感染力，像真人发朋友圈，不要AI腔
- 金额、天数、站点数必须和提供的数据一致
- 输出 JSON：{"title": "标题", "body": "正文(多个段落)", "topics": ["话题1", "话题2"]}

行程数据：
{context}
"""


def _trip_context(trip: Any, stats: dict[str, Any], badges: list[str], highlights: list[str]) -> str:
    lines = [
        f"目的地：{stats['destination']}",
        f"天数：{stats['days']}",
        f"站点数：{stats['stops']}（已打卡 {stats['checked']}）",
        f"总花费：{stats['expense_total']} 元（人均 {stats['per_person']} 元）",
        f"旅程徽章：{'、'.join(badges) if badges else '暂无'}",
    ]
    if highlights:
        lines.append("行程高光：")
        lines.extend(f"- {h}" for h in highlights)
    return "\n".join(lines)


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


async def _generate_with_llm(trip: Any, stats: dict[str, Any], badges: list[str], highlights: list[str], provider_name: str) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agent.providers import get_provider, invoke_with_resilience

    provider = get_provider(provider_name)
    context = _trip_context(trip, stats, badges, highlights)
    messages = [
        SystemMessage(content=_LLM_PROMPT),
        HumanMessage(content=context),
    ]
    response = await invoke_with_resilience(provider, messages, temperature=0.8)
    content = (getattr(response, "content", "") or "").strip()
    return _parse_llm_json(content)


async def build_trip_story(
    trip: Any,
    projection: dict[str, Any],
    *,
    channel: str = "xhs",
    provider: str = "auto",
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """生成旅程故事卡。

    Args:
        trip: Trip ORM（已加载 days）
        projection: journey_service.journey_projection 结果（含 badges/highlights）
        channel: xhs / moments / poster
        provider: LLM 提供商（auto 用默认）
        locale: 输出语种

    Returns:
        TripStoryOut dict；empty=True 表示数据不足（前端引导打卡/记账）。
    """
    locale = normalize_locale(locale)
    stats = _stats_from_projection(trip, projection)
    badges = _badge_names(projection.get("badges") or [])
    highlights = _highlights_text(projection.get("highlights") or [])

    # 空投影：无打卡且无费用 → 不硬生成（引导用户先记一笔）
    if stats["checked"] == 0 and stats["expense_total"] == 0:
        return {
            "trip_id": trip.id,
            "empty": True,
            "channel": channel,
            "title": "",
            "body": "",
            "topics": [],
            "stats": stats,
            "badges": badges,
            "highlights": highlights,
            "source": "template",
            "image_spec": _IMAGE_SPEC.get(channel, _IMAGE_SPEC["xhs"]),
            "message": t(locale, "story.empty.hint"),
        }

    template = _TEMPLATES.get(channel, _template_xhs)
    fallback = template(trip, stats, badges, highlights)

    # LLM 主路径 → 模板兜底
    try:
        generated = await _generate_with_llm(trip, stats, badges, highlights, provider)
        return {
            "trip_id": trip.id,
            "empty": False,
            "channel": channel,
            **generated,
            "stats": stats,
            "badges": badges,
            "highlights": highlights,
            "source": "llm",
            "image_spec": _IMAGE_SPEC.get(channel, _IMAGE_SPEC["xhs"]),
        }
    except Exception as exc:  # noqa: BLE001 — LLM 全链失败不阻断出稿
        logger.warning("story LLM 生成失败，降级模板: %s", exc)
        return {
            "trip_id": trip.id,
            "empty": False,
            "channel": channel,
            **fallback,
            "stats": stats,
            "badges": badges,
            "highlights": highlights,
            "source": "template",
            "image_spec": _IMAGE_SPEC.get(channel, _IMAGE_SPEC["xhs"]),
        }
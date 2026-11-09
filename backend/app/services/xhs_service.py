"""小红书「内容工厂」：文案生成（LLM 主路径 + 规则模板兜底）。

发布通道已拆到 ``app/services/publishers/``（策略 + 工厂 + 模板方法）：

- ``manual``：复制文案 → 小红书 App 粘贴（默认，零依赖零风控）
- ``rpa``：驱动创作服务平台自动填表（半自动，人点发布）
- 未来 ``openapi``：官方 API 放量后新增一个策略类即可，业务零改动

本模块只负责**生成**，并保留旧符号的再导出（``BasePublisher`` /
``XhsManualPublisher`` / ``get_publisher`` 等），历史调用方不用改。
"""
from __future__ import annotations

import logging

from app.agent.providers import get_provider, invoke_with_resilience
from app.services.publishers import (  # noqa: F401 — 兼容再导出
    BasePublisher,
    NoteImageSpec,
    PublisherFactory,
    PublishError,
    XhsNote,
    factory,
    get_publisher,
    register_publisher,
)

logger = logging.getLogger(__name__)


# ── 文案生成（LLM 主路径 + 规则兜底） ──────────────────────
_XHS_SYSTEM_PROMPT = """你是一位擅长种草文的小红书旅行博主，熟悉小红书的内容风格与话题运营。
根据给定的行程信息，生成一篇适合发布在小红书上的旅行笔记草稿。

要求：
1. 标题：20 字以内，有吸引力、带情绪价值（如「宝藏」「小众」「3天2夜」等），不要夸张失实。
2. 正文：300 字以内，口语化、有温度；按「行程亮点 → 每日行程简介 → 实用提示（预算/交通/时间）」组织；突出真实细节，避免 AI 腔和空话。
3. 话题：5-8 个相关话题标签，含目的地、旅行类型、实用类话题。

只输出 JSON，不要输出任何其他内容。
JSON 结构（字段名固定）：
{"title": "标题", "body": "正文", "topics": ["话题1", "话题2"]}
"""


def _trip_context(trip) -> str:
    """把行程模型转成 LLM 可读的紧凑上下文（仅角色所需字段，不传多余数据）。"""
    lines = [
        f"目的地：{trip.destination}",
        f"行程标题：{trip.title}",
        f"旅行时间：{trip.start_date} 至 {trip.end_date}（共 {max(1, (trip.end_date - trip.start_date).days + 1)} 天）",
        f"出行人数：{trip.travelers}",
        f"预算：{trip.budget if trip.budget is not None else '未设定'}",
    ]
    for day in trip.days or []:
        stops = day.stops or []
        stop_text = ""
        if stops:
            stop_text = " → ".join(
                f"{s.name}（{s.stop_type}）" for s in stops if getattr(s, "name", None)
            )
        if stop_text:
            lines.append(f"Day{day.day_number}: {stop_text}")
    return "\n".join(lines)


async def _generate_with_llm(trip, provider_name: str = "auto") -> XhsNote:
    """LLM 主路径：生成小红书文案。失败抛异常，由调用方降级。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    provider = get_provider(provider_name)
    messages = [
        SystemMessage(content=_XHS_SYSTEM_PROMPT),
        HumanMessage(content=_trip_context(trip)),
    ]
    response = await invoke_with_resilience(provider, messages, temperature=0.8)
    content = (getattr(response, "content", "") or "").strip()
    # 去除可能的 ```json 围栏
    if content.startswith("```"):
        content = content.strip("`")
        content = content.removeprefix("json")
    content = content.strip()
    try:
        import json

        data = json.loads(content)
        title = str(data.get("title", "")).strip()
        body = str(data.get("body", "")).strip()
        topics = [str(t).strip().lstrip("#") for t in (data.get("topics") or []) if str(t).strip()]
        if not title or not body:
            raise ValueError("LLM 输出缺少 title/body")
        return XhsNote(title=title, body=body, topics=topics[:8])
    except Exception as exc:  # 解析失败走兜底
        logger.warning("XHS 文案 LLM 输出解析失败，走规则兜底: %s", exc)
        raise ValueError(f"LLM 输出不是合法 JSON: {exc}") from exc


def _generate_with_template(trip) -> XhsNote:
    """规则兜底：基于行程数据的模板文案（LLM 不可用/失败时照常出稿）。"""
    dest = trip.destination
    days = trip.days or []
    highlights = []
    for day in days[:3]:
        stops = day.stops or []
        if stops:
            names = "、".join(s.name for s in stops[:3] if getattr(s, "name", None))
            if names:
                highlights.append(f"Day{day.day_number}：{names}")
    highlight_text = "\n".join(highlights) if highlights else "行程按天安排，节奏自由。"
    day_count = max(1, (trip.end_date - trip.start_date).days + 1)
    travelers = trip.travelers or 1
    budget = f"预算约 {trip.budget} 元" if trip.budget else "预算丰俭由人"

    body = (
        f"【{dest} {day_count}天{travelers}人出行攻略】\n\n"
        f"这次去{dest}玩，把整个行程都整理好啦！\n\n"
        f"{highlight_text}\n\n"
        f"💡 实用提示：{budget}，行程安排紧凑但不赶，适合喜欢深度游的朋友～\n\n"
        f"收藏这份攻略，出发不迷路！"
    )
    topics = [dest, "旅行攻略", "出行计划", "自由行", "周末去哪儿", "小众旅行地"]
    return XhsNote(title=f"{dest} {day_count}天{travelers}人 保姆级攻略", body=body, topics=topics)


async def generate_xhs_note(trip, provider: str = "auto") -> tuple[XhsNote, str]:
    """生成小红书笔记（LLM 主路径 → 规则兜底），返回 (note, source)。

    source ∈ {"llm", "template"}，供前端标注「AI 生成 / 模板生成」。
    """
    try:
        note = await _generate_with_llm(trip, provider_name=provider)
        return note, "llm"
    except Exception as exc:  # noqa: BLE001 — LLM 全链失败不阻断出稿
        logger.warning("XHS 文案 LLM 生成失败，降级模板: %s", exc)
        return _generate_with_template(trip), "template"


def note_image_spec() -> NoteImageSpec:
    """封面图规格（前端渲染小红书笔记卡用）。"""
    return NoteImageSpec()

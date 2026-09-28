"""社交平台发布适配器（可插拔）。

当前实现：方案 A —— 小红书笔记「内容工厂」：为行程生成适配小红书的
标题/正文/话题/封面卡数据，由用户复制文案 → 打开小红书 App → 粘贴发布。

架构上为「方案 B：官方开放平台 API 自动发布」预留了插槽：

- ``BasePublisher`` 定义统一的发布契约（publish_note / list_channels / health）
- ``XhsNoteFactory`` 负责把行程数据 + LLM 生成的内容组装成小红书笔记产物
- 未来接入官方 API 时，新增 ``XhsOpenApiPublisher(BasePublisher)``，
  并在 ``get_publisher("xhs")`` 的工厂里按配置返回即可，接口层零改动

LLM 生成文案失败时降级为基于行程数据的规则模板（照常出稿，绝不无声失败）。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.agent.providers import get_provider, invoke_with_resilience

logger = logging.getLogger(__name__)


# ── 数据契约 ────────────────────────────────────────────────
@dataclass
class XhsNote:
    """小红书笔记产物（方案 A：供用户复制 + 封面图导出）。"""

    title: str
    body: str
    topics: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """复制到剪贴板的完整文案 = 正文 + 话题标签。"""
        topics_text = " ".join(f"#{t}" for t in self.topics) if self.topics else ""
        if topics_text:
            return f"{self.body}\n\n{topics_text}"
        return self.body


@dataclass
class NoteImageSpec:
    """封面图规格（小红书图文笔记首图 3:4，1080×1440）。"""

    width: int = 1080
    height: int = 1440
    ratio: str = "3:4"


class PublishError(Exception):
    """发布失败（未来官方 API 通道用；当前方案 A 不含自动发布）。"""


# ── 发布契约（方案 B 预留） ─────────────────────────────────
class BasePublisher(ABC):
    """社交平台发布器统一契约。

    方案 A 阶段不实现自动发布：``publish_note`` 先抛 ``PublishError``，
    由 UI 走「复制文案 → 去 App 粘贴」路径。接入官方 API 后实现本接口。
    """

    channel: str = "xhs"

    @abstractmethod
    async def publish_note(self, note: XhsNote, images: list[str] | None = None) -> dict:
        """发布笔记。images 为图片 URL 列表（未来官方 API 上传用）。"""

    async def list_channels(self) -> list[dict]:
        """返回可用发布渠道（供前端展示接入状态）。"""
        return [{"channel": self.channel, "connected": False, "mode": "manual"}]

    async def health(self) -> dict:
        return {"channel": self.channel, "ok": True, "mode": "manual"}


class XhsManualPublisher(BasePublisher):
    """方案 A：手动发布通道（用户复制文案后自行去小红书发布）。"""

    async def publish_note(self, note: XhsNote, images: list[str] | None = None) -> dict:
        raise PublishError(
            "当前为手动发布模式：请复制文案后在小红书 App 内粘贴发布。"
            "接入官方开放平台 API 后可实现自动发布。"
        )


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


def _trip_context(trip: Any) -> str:
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


async def _generate_with_llm(trip: Any, provider_name: str = "auto") -> XhsNote:
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
        if content.startswith("json"):
            content = content[4:]
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
    except Exception as exc:  # noqa: BLE001 — 解析失败走兜底
        logger.warning("XHS 文案 LLM 输出解析失败，走规则兜底: %s", exc)
        raise ValueError(f"LLM 输出不是合法 JSON: {exc}") from exc


def _generate_with_template(trip: Any) -> XhsNote:
    """规则兜底：基于行程数据的模板文案（LLM 不可用/失败时照常出稿）。"""
    dest = trip.destination
    days = trip.days or []
    stop_count = sum(len(d.stops or []) for d in days)
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


async def generate_xhs_note(trip: Any, provider: str = "auto") -> tuple[XhsNote, str]:
    """生成小红书笔记（LLM 主路径 → 规则兜底），返回 (note, source)。

    source ∈ {"llm", "template"}，供前端标注「AI 生成 / 模板生成」。
    """
    try:
        note = await _generate_with_llm(trip, provider_name=provider)
        return note, "llm"
    except Exception as exc:  # noqa: BLE001 — LLM 全链失败不阻断出稿
        logger.warning("XHS 文案 LLM 生成失败，降级模板: %s", exc)
        return _generate_with_template(trip), "template"


# ── 工厂 ────────────────────────────────────────────────────
def get_publisher(channel: str = "xhs") -> BasePublisher:
    """按渠道返回发布器实例（可插拔：未来注册 XhsOpenApiPublisher 即可无缝切换）。"""
    if channel == "xhs":
        return XhsManualPublisher()
    raise PublishError(f"不支持的渠道: {channel}")


def note_image_spec() -> NoteImageSpec:
    """封面图规格（前端渲染小红书笔记卡用）。"""
    return NoteImageSpec()
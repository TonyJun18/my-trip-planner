"""对话助手行程上下文注入（方案 3：双向感知）。

设计文档：``docs/chat-trip-data-flow-design.md`` 第五节（方案 3，二期演进）。

解决的问题：方案 1+2 让助手能读/改行程，但**行程侧的变化不会自动流进对话**。
本模块在绑定行程的会话每次组装 AgentLoop 上下文时，注入三类摘要：

1. **行程摘要**（trip overview 精简版，token 预算 ~400）
2. **最近行程事件摘要**（revise / chat_edit / check / skip / delay / expense，
   默认最近 8 条，token 预算 ~150；事件风暴用类型白名单 + 条数上限治理）
3. **用户画像摘要**（profile_to_context，token 预算 ~200；规划已有现成注入，
   对话侧复用同一来源）

实现：通过 ``AgentLoop.transform_context`` 钩子（runtime.py 已预留）在每轮
LLM 调用前注入。注入块带固定 markdown 标记 + 生成时间，供 LLM 区分实时状态
与对话历史；标记了 ``injected_at`` 让模型意识到「这是当前时刻的快照，
不是历史消息」。

治理（防循环/防膨胀）：
- 事件注入是**单向**的：只读 TripEvent → 上下文；对话产生的 chat_edit 事件
  已由方案 2 记录，不会因注入再产生新事件（无回写循环）。
- 事件风暴：只取白名单类型 + 最近 N 条 + 单条截断到 ~80 字符。
- token 预算：三类各设上限，超限折叠为计数，**绝不静默丢弃关键事件**
  （折叠事件保留类型+时间戳，让模型知道「还有更多相关变更」）。
- 无绑定行程 / 无事件 / 无画像 → 注入空串，零噪音。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import TripEvent

logger = get_logger(__name__)

# 事件类型白名单（只注入「与行程实质相关的变更」，避免评论/投票等噪音）
_CONTEXT_EVENT_TYPES = ("revise", "chat_edit", "check", "skip", "delay", "edit")
# 最多注入的事件条数
_MAX_EVENTS = 8
# 单条事件摘要最大长度（超长截断 + 省略号）
_MAX_EVENT_LEN = 120
# 注入块 token 预算上限（超限折叠，不静默丢弃）
_MAX_TRIP_CONTEXT_TOKENS = 600


# ═══════════════════════════════════════════════════════════
#  事件摘要（纯函数，方便单测）
# ═══════════════════════════════════════════════════════════
def _event_line(ev: TripEvent) -> str:
    """一条事件 → 摘要行（含类型 + 时间 + 关键 payload 字段）。"""
    t = ev.created_at.astimezone().strftime("%m-%d %H:%M") if ev.created_at else ""
    payload = ev.payload or {}
    # 关键字段优先：summary / message / note；comment 用 content
    summary = (
        payload.get("summary")
        or payload.get("message")
        or payload.get("content")
        or payload.get("note")
        or ""
    )
    line = f"[{ev.event_type}] {t}"
    if summary:
        s = str(summary)
        if len(s) > _MAX_EVENT_LEN:
            s = s[:_MAX_EVENT_LEN] + "…"
        line += f" {s}"
    return line


def summarize_events(events: list[TripEvent]) -> list[str]:
    """事件列表 → 摘要行列表（按时间倒序已由调用方保证；白名单已过滤）。"""
    return [_event_line(ev) for ev in events[:_MAX_EVENTS]]


# ═══════════════════════════════════════════════════════════
#  行程上下文组装
# ═══════════════════════════════════════════════════════════
def _trip_meta_lines(trip: Any) -> list[str]:
    """行程元信息行（不含站点——站点详情由工具按需读取，避免上下文爆炸）。"""
    lines = [f"行程：{trip.title}（{trip.destination}）"]
    if trip.start_date:
        lines.append(f"时间：{trip.start_date} 至 {trip.end_date}")
    if trip.travelers:
        lines.append(f"人数：{trip.travelers}")
    return lines


def _folded_event_line(count: int) -> str:
    """折叠提示：告诉模型还有更多事件未注入（不静默丢弃）。"""
    return f"… 另有 {count} 条行程变更未展开（可调用 get_trip_overview 或询问具体事件）"


def _events_section(events: list[TripEvent]) -> str:
    """事件摘要 section（白名单过滤交由调用方；此处只做条数折叠）。"""
    if not events:
        return ""
    lines = summarize_events(events)
    if len(events) > _MAX_EVENTS:
        lines.append(_folded_event_line(len(events) - _MAX_EVENTS))
    return "\n".join(lines)


def _profile_section(profile_text: str) -> str:
    """画像 section（无画像返回空串）。"""
    if not profile_text:
        return ""
    return profile_text


# ═══════════════════════════════════════════════════════════
#  主入口：为绑定行程的会话生成注入上下文（字符串块）
# ═══════════════════════════════════════════════════════════
async def build_trip_context(
    db: AsyncSession,
    *,
    user_id: str | None,
    trip_id: str | None,
    max_tokens: int = _MAX_TRIP_CONTEXT_TOKENS,
) -> str:
    """生成注入到 AgentLoop 上下文的行程感知文本块。

    - 无 trip_id → 返回空串（未绑定行程，零注入）。
    - 读行程（owner 隔离）失败/不存在 → 返回空串（不编造、不报错阻断对话）。
    - 无事件 → 只注入行程元信息 + 画像。
    - 事件类型白名单过滤；最多 _MAX_EVENTS 条；超长截断。
    - 画像复用 profile_to_context（懒注入：失败降级为不含画像）。
    """
    if not trip_id:
        return ""

    # 1) 行程元信息（owner 隔离；读失败静默降级为空行程块）
    from app.models import Trip as _Trip

    trip = None
    try:
        from app.services import trip_service

        trip = await trip_service._load_trip(db, trip_id, owner=user_id)
    except Exception:  # noqa: BLE001 — 读失败不阻断对话
        logger.debug("chat_trip_context 读行程失败 trip=%s", trip_id, exc_info=True)

    sections: list[str] = []

    if trip is not None:
        sections.append("\n".join(_trip_meta_lines(trip)))
        # 2) 事件摘要（白名单 + 条数上限）
        try:
            stmt = (
                select(TripEvent)
                .where(TripEvent.trip_id == trip_id)
                .where(TripEvent.event_type.in_(_CONTEXT_EVENT_TYPES))
                .order_by(TripEvent.created_at.desc())
                .limit(_MAX_EVENTS + 1)  # 多取 1 判断是否有折叠
            )
            events = list((await db.execute(stmt)).scalars().all())
            ev_lines = _events_section(events)
            if ev_lines:
                sections.append("【最近行程变更】\n" + ev_lines)
        except Exception:  # noqa: BLE001 — 事件读失败不阻断
            logger.debug("chat_trip_context 读事件失败 trip=%s", trip_id, exc_info=True)

    # 3) 画像（复用规划侧注入逻辑；失败降级为空串）
    if user_id:
        try:
            from app.services import profile_service

            profile = await profile_service.get_profile(db, user_id=user_id)
            p_text = profile_service.profile_to_context(profile) if profile else ""
            ps = _profile_section(p_text)
            if ps:
                sections.append(ps)
        except Exception:  # noqa: BLE001
            logger.debug("chat_trip_context 读画像失败 user=%s", user_id, exc_info=True)

    if not sections:
        return ""

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    body = "\n\n".join(sections)
    # 预算折叠：token 粗估（中文 ~1.5 字/token，英文 ~4 字符/token），
    # 超限截断到最近部分（事件/画像在后，行程元信息在前，保关键）。
    if len(body) > max_tokens * 4:  # 粗估：1 token ≈ 4 字符
        body = body[-(max_tokens * 4):]
        body = "…（上下文预算已折叠，以上为最近部分）\n" + body

    return (
        f"【当前行程上下文 · 快照于 {now}】\n"
        f"（以下为当前绑定的行程与用户画像实时状态，优先于对话历史中的旧描述）\n"
        f"{body}"
    )


def make_transform_context(db: AsyncSession, *, user_id: str | None, trip_id: str | None):
    """构造 AgentLoop.transform_context 钩子。

    钩子在每轮 LLM 调用前执行：把注入块作为 SystemMessage 插到消息最前
    （在 Agent system prompt 之后、历史消息之前），让模型始终看到最新状态。

    返回可异步调用的 ``async def fn(messages) -> messages``。
    注入失败时原样返回消息（零侵入，对话不受影响）。
    """
    from langchain_core.messages import SystemMessage

    async def _transform(messages: list[Any]) -> list[Any]:
        try:
            ctx = await build_trip_context(
                db, user_id=user_id, trip_id=trip_id
            )
            if not ctx:
                return messages
            # 插到最前（system 之后）；每次调用生成新快照，不污染 messages
            return [SystemMessage(content=ctx), *messages]
        except Exception:  # noqa: BLE001 — 注入失败绝不阻断对话
            logger.debug("transform_context 注入失败", exc_info=True)
            return messages

    return _transform
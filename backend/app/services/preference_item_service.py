"""旅行记忆偏好条目服务（task-floattrip-borrow Story 2：可查看/编辑/删除）。

与 FloatTrip「旅行长期记忆」产品化对齐：记忆必须是**用户可见、可编辑、可忘记**
的条目，而不是藏在 DB 里不被信任的隐式画像。

存储：UserProfile.preferences_json["items"] = [{id, category, content,
source, updated_at}...]。与既有 ProfileIn.preferences_json（自由格式兜底）
并存：旧的自由格式（无 items 键）读取时归一为 legacy 条目，写操作时迁移为
结构化 items（保留旧字段不丢）。

语义契约：
- ``list_items`` 返回可读条目列表（含来源/更新时间）——Story 2 AC-1
- ``add_item / update_item / delete_item`` 提供新增/编辑/忘记——Story 2 AC-2
- ``items_to_text`` 把条目转成规划注入文本，且**显式标注「本次明确需求优先于
  历史画像」**——Story 2 AC-3
- ``delete_item`` 后条目从 items 移除 → profile_to_context 不再注入——Story 2 AC-4
- 最小权限：所有操作仅限 owner 本人（调用方保证 user_id = 当前登录用户）
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import UserProfile

logger = get_logger(__name__)

ITEMS_KEY = "items"
# 条目数上限：防止偏好列表无界增长（记忆是精选的，不是流水账）
MAX_ITEMS = 50

# 来源标注（诚实口径：与 preference_service 的 rule_based 区分用户声明）
SOURCE_USER = "user"
SOURCE_RULE = "rule"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    """把 preferences_json 归一为含 items 的结构（旧自由格式迁移不丢数据）。

    返回**全新 dict**（深拷贝）：SQLAlchemy 对 JSON 列只按引用/值比较判定
    dirty——原地修改后赋回同一引用不会被标记为变更，导致 flush/commit
    静默不写库。所有写操作必须持有新对象再赋值。
    """
    import copy

    payload = payload or {}
    if not isinstance(payload, dict):
        payload = {}
    if ITEMS_KEY not in payload:
        # 旧数据：把自由格式键值归一为 legacy 条目（source=user）
        items: list[dict[str, Any]] = []
        for k, v in payload.items():
            if k in (ITEMS_KEY, "updated_at"):
                continue
            if v is None or v == "":
                continue
            items.append({
                "id": uuid.uuid4().hex[:12],
                "category": "other",
                "content": f"{k}: {v}" if not isinstance(v, str) else f"{k}: {v}",
                "source": SOURCE_USER,
                "updated_at": _now_iso(),
            })
        payload = {ITEMS_KEY: items, "updated_at": _now_iso()}
    if not isinstance(payload.get(ITEMS_KEY), list):
        payload[ITEMS_KEY] = []
    return copy.deepcopy(payload)


async def get_profile(db: AsyncSession, *, user_id: str) -> UserProfile | None:
    """读取用户画像（无则返回 None，调用方决定兜底）。"""
    stmt = select(UserProfile).where(UserProfile.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


def _ensure_profile(db: AsyncSession, *, user_id: str) -> UserProfile:
    """懒创建 UserProfile（偏好条目是用户主动行为，应允许无画像直接新建）。"""
    profile = UserProfile(user_id=user_id, preferences_json={ITEMS_KEY: []})
    db.add(profile)
    return profile


async def list_items(db: AsyncSession, *, user_id: str) -> tuple[list[dict[str, Any]], int]:
    """返回用户的偏好条目列表（含来源/更新时间）与总数。

    无画像 → 空列表（不报错）；旧自由格式 → 按 legacy 归一展示。
    """
    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        return [], 0
    payload = _norm_profile(profile.preferences_json)
    items = payload.get(ITEMS_KEY) or []
    return list(items), len(items)


async def add_item(
    db: AsyncSession, *, user_id: str, category: str, content: str, source: str = SOURCE_USER
) -> dict[str, Any]:
    """新增一条偏好条目（用户主动声明，默认 source=user）。"""
    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        profile = _ensure_profile(db, user_id=user_id)
    payload = _norm_profile(profile.preferences_json)
    items = payload[ITEMS_KEY]
    if len(items) >= MAX_ITEMS:
        items = items[-(MAX_ITEMS - 1):]  # 有界：超出上限时裁剪最旧
    item = {
        "id": uuid.uuid4().hex[:12],
        "category": category,
        "content": content.strip(),
        "source": source,
        "updated_at": _now_iso(),
    }
    items.append(item)
    payload[ITEMS_KEY] = items
    payload["updated_at"] = _now_iso()
    profile.preferences_json = payload
    await db.flush()
    return item


async def update_item(
    db: AsyncSession, *, user_id: str, item_id: str, category: str | None = None,
    content: str | None = None,
) -> dict[str, Any] | None:
    """按 id 编辑条目；不存在返回 None（调用方转 404）。"""
    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        return None
    payload = _norm_profile(profile.preferences_json)
    items = payload[ITEMS_KEY]
    for item in items:
        if item.get("id") == item_id:
            if category is not None:
                item["category"] = category
            if content is not None:
                item["content"] = content.strip()
            item["updated_at"] = _now_iso()
            payload[ITEMS_KEY] = items
            payload["updated_at"] = _now_iso()
            profile.preferences_json = payload
            await db.flush()
            return item
    return None


async def delete_item(db: AsyncSession, *, user_id: str, item_id: str) -> bool:
    """按 id 删除（忘记）条目；返回是否真的删了。删除后不再注入。"""
    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        return False
    payload = _norm_profile(profile.preferences_json)
    items = payload[ITEMS_KEY]
    before = len(items)
    payload[ITEMS_KEY] = [i for i in items if i.get("id") != item_id]
    if len(payload[ITEMS_KEY]) == before:
        return False
    payload["updated_at"] = _now_iso()
    profile.preferences_json = payload
    await db.flush()
    return True


# ── 规划注入：条目文本 + 显式优先级 ─────────────────────────────
def items_to_text(items: list[dict[str, Any]], *, locale: str = "zh-CN") -> str:
    """把偏好条目转成给 Agent 的注入文本。

    显式语义（Story 2 AC-3）：「本次明确需求优先于历史画像」。同一主题下
    用户本次请求覆盖历史记忆——注入文案明说这一点，让 Planner 不把旧偏好
    凌驾于当前诉求之上。
    """
    if not items:
        return ""
    lines: list[str] = []
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        source = item.get("source")
        prefix = "" if source == SOURCE_USER else "【系统推断】"
        lines.append(f"- {prefix}{content}")
    if not lines:
        return ""
    head = (
        "【旅行记忆 · 偏好条目】以下为系统记住的长期偏好；"
        "仅作参考，**本次对话/需求中你明确提出的要求优先于历史记忆**，"
        "同一主题以本次为准。"
    )
    return head + "\n" + "\n".join(lines[:MAX_ITEMS])
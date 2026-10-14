"""用户画像服务：跨会话偏好记忆的读写 + 规划注入 + 行为记忆回写。

最小权限：画像只按 owner 访问，永不复用他人画像；规划注入只在创建任务时
从 DB 读一次，作为 request_data 快照落库（任务执行时不再触库）。

行为记忆（task-travel-memory-feedback）：用户修订/手动编辑行程是「真实
行为信号」，比声明式画像更能反映偏好。触点（revise_trip / update_stop）
在成功落库后尽力而为回写（fire-and-forget 语义——失败绝不影响主流程）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import UserProfile
from app.schemas.profile import ProfileIn

logger = get_logger(__name__)

# 行为记忆上限：防止无界增长（每次规划注入只读摘要，不需要无限历史）
MAX_BEHAVIOR_SIGNALS = 100

# 无效行为（不产生记忆信号）：纯 reorder / 空 actions / 空 summary
_NOISE_OPS = {"reorder"}
_MEANINGFUL_OPS = {"replace", "add", "remove"}


async def get_profile(db: AsyncSession, *, user_id: str) -> UserProfile | None:
    """读取用户画像；未创建过画像返回 None（调用方决定默认值）。"""
    stmt = select(UserProfile).where(UserProfile.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_profile(db: AsyncSession, *, user_id: str, data: ProfileIn) -> UserProfile:
    """全量覆盖 upsert：不存在则创建，存在则整体替换字段。

    幂等：同一画像连续 PUT 相同内容结果一致；返回刷新后的 ORM。
    **注意**：只覆盖 ProfileIn 声明的字段（行为记忆 behavior_memory_json
    不在其中，因此用户手动 PUT 不会清掉系统观察记忆）。
    """
    profile = await get_profile(db, user_id=user_id)
    values = data.model_dump()
    if profile is None:
        profile = UserProfile(user_id=user_id, **values)
        db.add(profile)
    else:
        for field, value in values.items():
            setattr(profile, field, value)
    await db.flush()
    await db.refresh(profile)
    return profile


async def _record_behavior(
    db: AsyncSession,
    *,
    user_id: str,
    signal_kind: str,
    destination: str,
    actions: list[dict[str, Any]],
    summary: str,
) -> None:
    """记录一条行为信号（noise 过滤 + 有界累计）。触点成功落库后调用。

    fire-and-forget 语义：本函数只在用户已有画像时写入（无画像不自动创建），
    失败由调用方 try/except 包裹，绝不阻断主流程。
    """
    meaningful = [
        a for a in (actions or []) if isinstance(a, dict) and a.get("op") in _MEANINGFUL_OPS
    ]
    if not meaningful or not destination or not summary:
        return

    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        return
    _append_signal(profile, {
        "kind": signal_kind,
        "destination": destination,
        "summary": summary,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    # 调用方负责 flush/commit（与主流程同事务或独立小事务，由调用方决定）


def _append_signal(profile: UserProfile, signal: dict[str, Any]) -> None:
    """把 signal 追加到 profile.behavior_memory_json（带上限裁剪）。"""
    mem = profile.behavior_memory_json or {}
    signals = mem.get("signals") or []
    signals.append(signal)
    if len(signals) > MAX_BEHAVIOR_SIGNALS:
        signals = signals[-MAX_BEHAVIOR_SIGNALS:]
    profile.behavior_memory_json = {
        "signals": signals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _summarize_behaviors(profile: UserProfile) -> list[str]:
    """把行为记忆压缩成给 Agent 的摘要行（去重 + 归纳，≤5 行）。

    只保留真正可指导下次规划的观察：
    - 去过城市去重
    - 节奏信号（修订缩短/加长时长）
    - 删除信号（明确不感兴趣）
    """
    mem = profile.behavior_memory_json or {}
    signals = mem.get("signals") or []
    if not signals:
        return []

    lines: list[str] = []

    # 去过城市（去重，按最近在前）
    cities: list[str] = []
    seen: set[str] = set()
    for s in signals:
        dest = (s.get("destination") or "").strip()
        if dest and dest not in seen:
            cities.append(dest)
            seen.add(dest)
    if cities:
        lines.append(f"近期规划/修订过的城市：{'、'.join(cities[:5])}")

    # 节奏信号：对同一城市多次缩短时长 → 提示偏好轻松节奏
    shorten: dict[str, int] = {}
    for s in signals:
        dest = (s.get("destination") or "").strip()
        if dest and "缩短" in (s.get("summary") or "") or "半天" in (s.get("summary") or ""):
            shorten[dest] = shorten.get(dest, 0) + 1
    for dest, cnt in list(shorten.items())[:3]:
        if cnt >= 2:
            lines.append(f"{dest}多次调整紧凑行程（≥{cnt} 次缩短/精简），倾向更轻松节奏")

    # 删除信号：明确表示不感兴趣
    removed: set[str] = set()
    for s in signals:
        if s.get("kind") == "revise" and "删" in (s.get("summary") or ""):
            removed.add(s.get("destination") or "")
    for dest in list(removed)[:3]:
        if dest:
            lines.append(f"{dest}明确删除过部分站点，请优先推荐精选、非打卡式")

    return lines


def profile_to_context(profile: UserProfile | None) -> str:
    """把画像转成给 Agent 的纯文本上下文（无画像返回空串，不注入）。

    - 用户声明画像在前（traveler_type/pace/budget_tier/favorite_cities/preferences）
    - 系统观察行为记忆在后（_summarize_behaviors 归纳，标注来源）
    """
    if profile is None:
        return ""
    lines: list[str] = []
    if profile.traveler_type:
        lines.append(f"出行人群：{profile.traveler_type}")
    if profile.pace:
        lines.append(f"节奏偏好：{profile.pace}")
    if profile.budget_tier:
        lines.append(f"预算档：{profile.budget_tier}")
    if profile.favorite_cities:
        lines.append(f"常去城市：{'、'.join(profile.favorite_cities)}")
    prefs = profile.preferences_json or {}
    if prefs:
        try:
            import json

            lines.append(f"其它偏好：{json.dumps(prefs, ensure_ascii=False)}")
        except (TypeError, ValueError):
            lines.append(f"其它偏好：{prefs}")

    # 系统观察行为记忆（来源标注，与用户声明分离）
    behavior_lines = _summarize_behaviors(profile)
    if behavior_lines:
        lines.append("【系统观察 · 基于你近期的行程修订/编辑】" + "；".join(behavior_lines))

    if not lines:
        return ""
    return "【跨会话用户画像】（来自该用户历史偏好，规划时请优先尊重；与本次请求冲突时以本次请求为准）\n" + "\n".join(lines)


async def profile_for_request(db: AsyncSession, *, user_id: str) -> dict[str, Any]:
    """规划任务创建时调用：读取画像并返回注入段。

    返回 {"profile_text": str}；未设置画像时 profile_text 为空串。

    注入内容 = 声明画像（profile_to_context）+ 系统推断偏好（preference_service，
    懒计算并写回 inferred_preferences_json）。推断段始终在声明段之后，
    且来源标注「系统推断」，避免与用户声明混淆（诚实口径）。
    """
    profile = await get_profile(db, user_id=user_id)
    if profile is None:
        return {"profile_text": ""}

    declared = profile_to_context(profile)
    inferred = ""
    try:
        # 懒计算：行为记忆变化才重算；写回由调用方（create_task）的 commit 落库
        from app.services.preference_service import ensure_inferred, inferred_to_text

        inferred_dict = ensure_inferred(db, profile)
        inferred = inferred_to_text(inferred_dict or {})
    except Exception:  # noqa: BLE001 — 推理失败绝不影响规划主流程
        logger.debug("偏好推断失败（降级为仅声明画像）", exc_info=True)

    parts = [p for p in (declared, inferred) if p]
    return {"profile_text": "\n\n".join(parts) if parts else ""}
"""收藏地点服务（task-social-favorites-flow-eval：Plotline collect-first 范式）。

背景（2026-11-10 竞品分析）：Plotline collect-first（分享表→增长地图→行程）
vs Wanderlog trip-only（导入直接进行程）两范式。我们现有导入（social/note/
email/link/screenshot）全部是 **trip-first**：解析出候选 → 必须选一个已存在
的行程并入。行程未定时（「还没想好去哪，先攒着」）候选就丢了。

本模块把「地点收集」做成独立底座：
- **collect_spots**：把导入解析出的候选（地点名/类型/描述/价格/坐标）+ 来源
  信息（平台 + 原文片段）保存为用户自己的收藏地点（FavoriteSpot）。
  - 零凭证、纯规则、确定性强；外部内容只作为数据字段，绝不作为指令。
  - name_key 归一化（去空白 + 小写）：重复收藏幂等跳过，返回 skipped 计数。
  - 不编造：候选缺坐标就不存坐标、缺价格就不存价格。
- **list_spots / remove_spot**：收集箱的读/删（供前端「我的收藏地点」页）。
- **与 favorites-to-route 闭环衔接**：收藏地点聚合后可直接喂给后续
  「地点 → 路线」入口（favorites-to-route 已做「收藏行程 → 一键成路线」，
  本模块补「地点收集箱」底座，两段拼成完整 collect-first 链路）。
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import FavoriteSpot, User
from app.schemas.favorite_spots import FavoriteSpotIn, FavoriteSpotOut

# 单次批量收藏上限（与导入候选上限同量级，防超大请求）
MAX_BATCH_SPOTS = 50
# 展示用原文片段上限（防止把大段原文塞进收集箱）
MAX_SNIPPET_LENGTH = 200


def normalize_spot_key(name: str) -> str:
    """归一化去重键：去空白 + 小写（与 social/note 导入 dedup_key 同源）。"""
    return re.sub(r"\s+", "", name or "").lower()


def _snippet(text: str | None) -> str | None:
    """来源片段截断（仅展示参考，绝不当指令）。"""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    return text[:MAX_SNIPPET_LENGTH]


async def collect_spots(
    db: AsyncSession,
    user: User,
    spots: list[FavoriteSpotIn],
) -> dict:
    """批量收藏地点（幂等：同 user + 同 name_key 已存在则跳过）。

    - 输入来自导入解析出的候选（外部内容按敌意源处理：只取结构化字段，
      名称/类型等经 schema 白名单，不执行任何文本指令）。
    - 返回 {collected, skipped, total}；不抛错（单条脏数据不影响整批）。
    """
    if not spots:
        return {"collected": 0, "skipped": 0, "total": 0}

    spots = spots[:MAX_BATCH_SPOTS]

    # 先查已有 name_key（原子性不依赖 DB 唯一约束的异常路径）
    keys = [normalize_spot_key(s.name) for s in spots]
    stmt = select(FavoriteSpot.name_key).where(
        FavoriteSpot.user_id == user.id,
        FavoriteSpot.name_key.in_(keys),
    )
    existing = set((await db.execute(stmt)).scalars().all())

    collected = 0
    skipped = 0
    for s in spots:
        key = normalize_spot_key(s.name)
        if not key:
            skipped += 1
            continue
        if key in existing:
            skipped += 1
            continue
        spot = FavoriteSpot(
            user_id=user.id,
            name=(s.name or "").strip()[:200],
            name_key=key,
            stop_type=s.stop_type or "attraction",
            lat=s.lat,
            lng=s.lng,
            description=(s.description or "").strip() or None,
            estimated_cost=s.estimated_cost,
            estimated_duration_minutes=s.estimated_duration_minutes,
            source_platform=s.source_platform or None,
            source_snippet=_snippet(s.source_snippet),
        )
        db.add(spot)
        existing.add(key)
        collected += 1

    await db.flush()
    return {"collected": collected, "skipped": skipped, "total": collected + skipped}


async def list_spots(
    db: AsyncSession,
    user: User,
    *,
    offset: int = 0,
    limit: int = 100,
) -> dict:
    """当前用户的收藏地点（按收藏时间倒序）。"""
    stmt = (
        select(FavoriteSpot)
        .where(FavoriteSpot.user_id == user.id)
        .order_by(FavoriteSpot.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list((await db.execute(stmt)).scalars().all())

    total_stmt = (
        select(FavoriteSpot.id)
        .where(FavoriteSpot.user_id == user.id)
    )
    total = len(list((await db.execute(total_stmt)).scalars().all()))

    return {
        "items": [FavoriteSpotOut.model_validate(s) for s in items],
        "total": total,
    }


async def remove_spot(db: AsyncSession, user: User, spot_id: str) -> None:
    """删除一条收藏地点（幂等：不存在视为已完成删除）。"""
    stmt = select(FavoriteSpot).where(
        FavoriteSpot.id == spot_id,
        FavoriteSpot.user_id == user.id,
    )
    spot = (await db.execute(stmt)).scalar_one_or_none()
    if spot is None:
        raise NotFoundError("收藏地点不存在", code="favorite_spot_not_found")
    await db.delete(spot)
    await db.flush()
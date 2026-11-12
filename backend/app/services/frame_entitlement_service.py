"""兑换码与权益服务（frame-marketplace）。

设计要点：
- 兑换码只存 SHA-256 哈希（`redemption_codes.code_hash`），明文不落库；
- 权益以 (user_id, pack_slug) 唯一约束保证幂等：同一用户重放自己的码返回已解锁；
- 错误语义：码不存在 404 / 他人已用 409 / 已吊销 410（文案明确区分，便于对账）；
- 码即资产：任何有效码兑换后只解锁「兑换者本人」，与码的来源无关。
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FrameEntitlement, FramePack, FrameTemplate, RedemptionCode


def hash_code(code: str) -> str:
    """兑换码哈希（去空格统一大写后 SHA-256）。"""
    normalized = code.strip().upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


async def list_packs(db: AsyncSession) -> list[FramePack]:
    """全部 active 模板包。"""
    rows = await db.execute(
        select(FramePack).where(FramePack.active.is_(True)).order_by(FramePack.price_cents)
    )
    return list(rows.scalars().all())


async def list_templates(db: AsyncSession) -> list[FrameTemplate]:
    """全部 active 模板。"""
    rows = await db.execute(
        select(FrameTemplate).where(FrameTemplate.active.is_(True)).order_by(FrameTemplate.id)
    )
    return list(rows.scalars().all())


async def unlocked_pack_slugs(db: AsyncSession, user_id: str) -> set[str]:
    """用户已解锁的模板包 slug 集合。"""
    rows = await db.execute(
        select(FrameEntitlement.pack_slug).where(FrameEntitlement.user_id == user_id)
    )
    return {r[0] for r in rows.all()}


async def list_entitlements(db: AsyncSession, user_id: str) -> list[FrameEntitlement]:
    rows = await db.execute(
        select(FrameEntitlement)
        .where(FrameEntitlement.user_id == user_id)
        .order_by(FrameEntitlement.redeemed_at)
    )
    return list(rows.scalars().all())


async def redeem(db: AsyncSession, user_id: str, code: str) -> FrameEntitlement:
    """兑换码换权益（幂等）。

    - 未命中哈希 → 404（响应不回显明文码）
    - 已吊销 → 410
    - 已被他人使用 → 409
    - 自己已兑换（重放） → 幂等返回既有权益，200
    """
    code_hash = hash_code(code)
    row = await db.execute(select(RedemptionCode).where(RedemptionCode.code_hash == code_hash))
    record = row.scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="兑换码不存在")
    if record.status == "revoked":
        raise HTTPException(status_code=410, detail="该兑换码已被吊销，请联系购买渠道")

    # 同一用户重放：幂等返回已解锁权益
    existing = await db.execute(
        select(FrameEntitlement).where(
            FrameEntitlement.user_id == user_id,
            FrameEntitlement.pack_slug == record.pack_slug,
        )
    )
    if (ent := existing.scalar_one_or_none()) is not None:
        return ent

    if record.status == "used":
        raise HTTPException(status_code=409, detail="该码已被使用")

    # 首次兑换：写权益 + 标记码 used（同一事务，原子生效）
    entitlement = FrameEntitlement(user_id=user_id, pack_slug=record.pack_slug)
    db.add(entitlement)
    record.status = "used"
    record.redeemed_by = user_id
    record.redeemed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(entitlement)
    return entitlement

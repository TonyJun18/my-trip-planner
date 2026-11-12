"""旅拍相框市场 API（frame-marketplace）。

端点（挂 /frames 前缀）：
- GET  /frames/catalog        模板目录（免登录可看，付费模板带 locked 标注）
- GET  /frames/entitlements   我的已解锁包列表（需登录）
- POST /frames/redeem         兑换码换权益（需登录，幂等；404/409/410 语义明确）

投影与配文端点在 trips 前缀下（trips_frames.py）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, get_optional_user
from app.core.database import get_session
from app.models import User
from app.schemas.frames import (
    CatalogOut,
    EntitlementOut,
    EntitlementsOut,
    FramePackOut,
    FrameTemplateOut,
    RedeemOut,
    RedeemRequest,
)
from app.services import frame_entitlement_service as svc

router = APIRouter()


@router.get(
    "/catalog",
    response_model=CatalogOut,
    summary="模板目录（免登录）",
)
async def get_catalog(
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
) -> CatalogOut:
    """全部 active 模板与模板包；付费模板按当前用户权益标注 locked。"""
    templates = await svc.list_templates(db)
    packs = await svc.list_packs(db)
    unlocked: set[str] = set()
    if user is not None:
        unlocked = await svc.unlocked_pack_slugs(db, user.id)

    def _locked(t) -> bool:
        if t.tier == "free":
            return False
        return not any(t.slug in (p.template_slugs or []) and p.slug in unlocked for p in packs)

    return CatalogOut(
        templates=[
            FrameTemplateOut(
                slug=t.slug,
                name=t.name,
                tier=t.tier,
                theme=t.theme,
                layout_config=t.layout_config or {},
                price_cents=t.price_cents,
                locked=_locked(t),
            )
            for t in templates
        ],
        packs=[
            FramePackOut(
                slug=p.slug,
                name=p.name,
                description=p.description,
                template_slugs=p.template_slugs or [],
                price_cents=p.price_cents,
            )
            for p in packs
        ],
    )


@router.get(
    "/entitlements",
    response_model=EntitlementsOut,
    summary="我的已解锁包列表",
)
async def get_entitlements(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EntitlementsOut:
    rows = await svc.list_entitlements(db, user.id)
    return EntitlementsOut(
        entitlements=[
            EntitlementOut(pack_slug=e.pack_slug, redeemed_at=e.redeemed_at.isoformat() if e.redeemed_at else None)
            for e in rows
        ]
    )


@router.post(
    "/redeem",
    response_model=RedeemOut,
    summary="兑换码换权益（幂等）",
)
async def redeem_code(
    data: RedeemRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RedeemOut:
    entitlement = await svc.redeem(db, user.id, data.code)
    rows = await svc.list_entitlements(db, user.id)
    return RedeemOut(
        redeemed=True,
        pack_slug=entitlement.pack_slug,
        entitlements=[
            EntitlementOut(pack_slug=e.pack_slug, redeemed_at=e.redeemed_at.isoformat() if e.redeemed_at else None)
            for e in rows
        ],
    )

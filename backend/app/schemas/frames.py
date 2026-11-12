"""旅拍相框市场 Schemas（frame-marketplace）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RedeemRequest(BaseModel):
    """兑换码兑换请求。"""

    code: str = Field(min_length=4, max_length=64)


class FrameTemplateOut(BaseModel):
    """模板目录条目（含当前用户的 locked 标注）。"""

    slug: str
    name: str
    tier: Literal["free", "paid"]
    theme: str
    layout_config: dict[str, Any]
    price_cents: int = 0
    locked: bool = False


class FramePackOut(BaseModel):
    """模板包（售卖单元）。"""

    slug: str
    name: str
    description: str | None = None
    template_slugs: list[str] = []
    price_cents: int = 0


class CatalogOut(BaseModel):
    """模板目录（商店页展示，免登录可看）。"""

    templates: list[FrameTemplateOut]
    packs: list[FramePackOut]


class EntitlementOut(BaseModel):
    """已解锁模板包权益。"""

    pack_slug: str
    redeemed_at: str | None = None


class EntitlementsOut(BaseModel):
    """我的已解锁包列表。"""

    entitlements: list[EntitlementOut]


class RedeemOut(BaseModel):
    """兑换结果（幂等：重放返回已解锁）。"""

    redeemed: bool
    pack_slug: str
    entitlements: list[EntitlementOut]

"""灵感优先目的地推荐 API：还没想好去哪 → 按兴趣/预算/季节推荐目的地。

独立 router（不并入 trips.py），纯确定性规则（零 LLM / 零 API key），
与 plan_b / map_edit 同风格：读取侧派生，不改任何表。

GET /trips/inspiration?interests=food,nature&budget_tier=comfort&season=spring&limit=5
→ 推荐目的地卡片列表（name/理由/参考玩法/预估日均预算/建议天数/匹配标签/季节提示）。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.models import User
from app.services.inspiration_service import recommend_destinations

router = APIRouter()


class InspirationOut(BaseModel):
    """单个目的地推荐卡片。"""

    name: str = Field(description="目的地名称")
    country: str = Field(default="", description="国家/地区")
    tags: list[str] = Field(default_factory=list, description="兴趣标签")
    best_season: str = Field(default="", description="最佳季节（spring/summer/autumn/winter/all）")
    budget_tier: str = Field(default="comfort", description="基准消费档（economy/comfort/quality/luxury）")
    est_daily_budget: int = Field(default=0, description="预估日均预算（元）")
    suggested_days: int = Field(default=3, description="建议游玩天数")
    reason: str = Field(default="", description="一句话推荐理由")
    play: str = Field(default="", description="参考玩法")
    match_score: float = Field(default=0, description="匹配度评分（确定性规则，越大越匹配）")
    matched_tags: list[str] = Field(default_factory=list, description="命中的兴趣标签")
    season_note: str = Field(default="", description="季节提示（非最佳季节时非空，诚实标注）")
    basis: str = Field(default="rule_based", description="口径标注（诚实：规则库推断）")


class InspirationListOut(BaseModel):
    """GET /inspiration 响应。"""

    items: list[InspirationOut] = Field(default_factory=list, description="推荐目的地卡片（按匹配度降序）")
    counts: dict = Field(default_factory=dict, description="统计：matched 命中的兴趣数 / season 是否有季节过滤")
    note: str = Field(default="", description="提示文案（如无兴趣时推荐全部可负担目的地）")


@router.get(
    "/inspiration",
    response_model=InspirationListOut,
    summary="灵感优先：按兴趣/预算/季节推荐目的地（确定性规则，零 LLM）",
)
async def recommend(
    interests: str = Query(
        default="",
        description="逗号分隔的兴趣标签（food/nature/history/shopping/family/hiking/museum/nightlife/photo/hotspring）",
    ),
    budget_tier: Literal["economy", "comfort", "quality", "luxury"] = Query(default="comfort"),
    season: Literal["spring", "summer", "autumn", "winter", ""] = Query(default=""),
    limit: int = Query(default=5, ge=1, le=5, description="返回条数（3-5）"),
    user: User = Depends(get_current_user),
) -> InspirationListOut:
    """返回目的地推荐卡片；前端灵感入口消费 → 选点预填创建表单。"""
    tag_list = [t.strip() for t in interests.split(",") if t.strip()] if interests else []
    items = recommend_destinations(
        interests=tag_list or None,
        budget_tier=budget_tier,
        season=season or None,
        limit=limit,
    )
    return InspirationListOut(
        items=[InspirationOut(**it) for it in items],
        counts={
            "matched": len(tag_list),
            "season_filter": bool(season),
            "budget_tier": budget_tier,
            "returned": len(items),
        },
        note=(
            "根据预算档位推荐可负担的目的地"
            if not tag_list
            else f"根据兴趣标签与预算档位推荐（命中 {len(tag_list)} 个兴趣）"
        ),
    )
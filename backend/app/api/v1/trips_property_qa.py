"""行程内结构化事实问答路由（task-property-qa-eval）。

GET /trips/{trip_id}/property-qa
- 带 ?q=  → 回答单个问题（结构化字段规则问答，零 LLM，防编造）
- 不带 q → 返回「当前可答事实清单」（facts + budget + warnings + suggestions）

数据源：最新 TripPlan.plan_data 快照（open_hours/budget/quality/gate warnings）
+ trip.days[].stops[] 落库字段（details.rating / estimated_cost / duration）。
无数据 → available=false + basis=none，绝不编造。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.i18n import normalize_locale
from app.models import User
from app.schemas import PropertyQaFactsOut, PropertyQaOut
from app.services import property_qa_service, trip_service

router = APIRouter()


@router.get("/{trip_id}/property-qa", response_model=PropertyQaOut | PropertyQaFactsOut, summary="行程内结构化事实问答（规则版，零 LLM）")
async def property_qa(
    trip_id: str,
    q: str | None = Query(default=None, max_length=200, description="问题文本；缺省返回当前可答事实清单"),
    locale: str = Query(default="zh-CN", description="语种（zh-CN / en-US 等）"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PropertyQaOut | PropertyQaFactsOut:
    """行程内结构化事实问答（task-property-qa-eval）。

    - 只回答结构化字段里真实存在的事实（营业时间/预算/质检预警/评分/费用/时长）；
    - basis 诚实标注来源（explicit 显式字段 / rule_based 规则库推断 / none 无数据）；
    - 无数据 → available=false，绝不编造数字/时间/评分。
    """
    locale = normalize_locale(locale)
    trip = await trip_service.get_trip(db, trip_id, owner=user.id)
    plan = await trip_service.get_plan_by_trip_id(db, trip_id)

    if not q or not q.strip():
        result = property_qa_service.collect_property_facts(trip, plan, locale=locale)
        return PropertyQaFactsOut(**result)

    result = property_qa_service.answer_property_question(
        trip, plan, q.strip(), locale=locale,
    )
    return PropertyQaOut(**result)
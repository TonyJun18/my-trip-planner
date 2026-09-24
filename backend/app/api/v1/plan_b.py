"""行程备选方案（Plan B）API：为已生成的行程生成备选骨架。

独立 router（不并入 trips.py），避免与用户未提交的 trips.py 改动混淆；
纯确定性规则生成（不依赖 LLM / API key），返回主案的可对比备选。

读取侧派生：不改 trips 表、不新表——「切换」由前端在读取侧完成对比展示。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import Trip, TripDay, User
from app.schemas.plan_b import PlanBOut, PlanBVariantOut
from app.services.plan_b import generate_plan_b_variant

router = APIRouter()


def _days_from_trip(trip: Trip) -> list[dict]:
    """把 Trip 的 ORM 结构（days/stops）装配成 plan_b 服务需要的字典列表。

    只读装配，不写库；站点字段与 TripPlan.plan_data.days 同构。
    """
    days: list[dict] = []
    for day in trip.days:
        stops: list[dict] = []
        for stop in day.stops:
            stops.append(
                {
                    "name": stop.name,
                    "stop_type": stop.stop_type or "attraction",
                    "lat": stop.lat,
                    "lng": stop.lng,
                    "description": stop.description,
                    "estimated_cost": stop.estimated_cost,
                    "estimated_duration_minutes": stop.estimated_duration_minutes,
                }
            )
        days.append(
            {
                "day_number": day.day_number,
                "date": day.date,
                "theme": day.note,
                "stops": stops,
            }
        )
    return days


@router.get(
    "/trips/{trip_id}/plan-b",
    response_model=PlanBOut,
    summary="生成行程备选方案（Plan B，确定性规则，无 LLM 成本）",
)
async def get_plan_b(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PlanBOut:
    """返回该行程的一个备选骨架（节奏 / 预算档 / 取舍 三种变体之一）。

    - 纯规则生成：无 LLM、无外部 API、无 API key（与 note-import 同风格）；
    - 只读派生：不落库、不改 trips 表，产生任何副作用；
    - 行程无站点 → variant=None + note 说明（前端隐藏入口）；
    - 鉴权：与行程管理一致（owner 才能查看）。
    """
    stmt = (
        select(Trip)
        .options(selectinload(Trip.days).selectinload(TripDay.stops))
        .where(Trip.id == trip_id)
    )
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None or trip.owner != user.id:
        raise NotFoundError("行程不存在", code="trip_not_found")

    days = _days_from_trip(trip)
    variant = generate_plan_b_variant(days)

    note = ""
    if variant is None:
        note = "行程还没有可生成备选的站点"
    return PlanBOut(
        trip_id=trip.id,
        variant=PlanBVariantOut(
            label=variant["label"],
            description=variant["description"],
            deltas=variant["deltas"],
            days=variant["days"],
            budget=variant["budget"],
        )
        if variant
        else None,
        note=note,
    )
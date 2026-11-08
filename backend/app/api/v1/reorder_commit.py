"""行程拖拽重排提交 API：POST /api/v1/trips/{trip_id}/reorder-commit。

Story 1（task-floattrip-borrow）：拖拽换序 → 本地草稿（撤销/重做）→ 点保存
提交多日重排。本端点做原子落库 + DrivingGate 前置 + 预算重算，失败整体回滚。

- 登录必需；仅 owner 可改（与 revise/map_edit 同鉴权）；
- order 必须包含该日全部站点 id（缺漏/乱序 → 400，不产生半保存）；
- DrivingGate 拒绝 → 400 + detail.issues（前端提示「约束未通过」）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas.reorder import OptimizeOrderOut, ReorderCommitIn, ReorderCommitOut
from app.services.day_optimizer import optimize_day_order
from app.services.reorder_service import commit_reorder

router = APIRouter()


@router.post(
    "/trips/{trip_id}/reorder-commit",
    response_model=ReorderCommitOut,
    summary="保存拖拽重排（原子落库 + DrivingGate 前置 + 预算重算）",
)
async def reorder_commit(
    trip_id: str,
    data: ReorderCommitIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ReorderCommitOut:
    """提交一次多日重排：校验 → 原子应用 → 约束门 → 预算重算 → 落库。"""
    if not data.days:
        raise NotFoundError("重排指令为空", code="reorder_empty")
    result = await commit_reorder(
        db,
        trip_id,
        days=[d.model_dump() for d in data.days],
        owner=user.id,
    )
    return ReorderCommitOut(**result)


@router.post(
    "/trips/{trip_id}/days/{day_id}/optimize-order",
    response_model=OptimizeOrderOut,
    summary="单日按最优顺序重排（最近邻 + DrivingGate 前置 + 预算重算）",
)
async def optimize_day_order_endpoint(
    trip_id: str,
    day_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OptimizeOrderOut:
    """确定性重排某一天：首站锚定 + 最近邻，只有真变短才落库。

    落库复用 ``commit_reorder``（DrivingGate 前置 + 预算重算 + 原子提交），
    约束不通过时像拖拽保存一样返回 400，不做任何降级放行。
    """
    result = await optimize_day_order(db, trip_id, day_id, owner=user.id)
    return OptimizeOrderOut(**result)
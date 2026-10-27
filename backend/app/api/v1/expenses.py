"""行中费用记录 API（task-expense-split-mini：费用记录 + 人均结余）。

端点（挂 /trips 前缀，路径字面量在 /{trip_id} 之前注册，避免路由吞参）：
- GET  /trips/{trip_id}/expenses       —— 费用列表 + 分摊汇总（owner）
- POST /trips/{trip_id}/expenses       —— 记一笔（owner / 受邀协作者）
- DELETE /trips/{trip_id}/expenses/{expense_id} —— 撤销误记（owner）

与 share_token 的关系：费用是「实付」，只对 owner 与受邀编辑者开放
（凭 share_token 的只读分享页不返回费用，避免把财务数据暴露给任意链接持有者）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import ExpenseBalanceOut, ExpenseIn, ExpenseOut
from app.services import expense_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get(
    "/{trip_id}/expenses",
    response_model=dict,
    summary="行程费用列表 + 人均结余汇总（owner）",
)
async def list_trip_expenses(
    trip_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """owner 查看行程的费用记录与分摊汇总。"""
    records, balance = await expense_service.list_expenses(db, trip_id, owner=user.id)
    return {
        "items": [ExpenseOut.model_validate(r).model_dump(mode="json") for r in records],
        "balance": ExpenseBalanceOut(**{**balance, "trip_id": trip_id}).model_dump(mode="json"),
    }


@router.post(
    "/{trip_id}/expenses",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    summary="记一笔费用（owner）",
)
async def add_trip_expense(
    trip_id: str,
    data: ExpenseIn,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ExpenseOut:
    """owner 记一笔实际花费（类别/金额/支付人/备注）。"""
    expense = await expense_service.add_expense(db, trip_id, data, owner=user.id)
    return ExpenseOut.model_validate(expense)


@router.delete(
    "/{trip_id}/expenses/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除一条费用记录（owner，撤销误记）",
)
async def delete_trip_expense(
    trip_id: str,
    expense_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    """owner 删除一条费用记录（物理删除；删除后分摊自动重算）。"""
    await expense_service.delete_expense(db, trip_id, expense_id, owner=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
"""行中费用记录与分摊服务（task-expense-split-mini：Stippl/MonkeyTravel 行中管理一体化）。

设计哲学（与 live_service / budget_service 同源）：
- **代码确定性**：记账/汇总全是确定性计算，不经过 LLM；
- **零凭证**：支付人（payer）用自由文本姓名（如「小彭」），不建成员表、
  不接支付 API——用户旅程是「记一笔账」，不是「对账系统」；汇率同样零凭证：
  不接实时汇率 API（需第三方凭证），由用户填写或规则库兜底；
- **浅表结构**：TripExpense 挂 trip_id（不挂 day_id），最小版不按天拆分，
  行中「今天花了多少」由前端按 created_at 自行过滤；
- **append-only 记账语义**：金额不允许原地修改（改=删旧+新增），
  保证结余可复算、误记可撤销（物理删除）；汇率随记录锁定（录入时汇率），
  历史结余不漂移；
- **诚实口径**：payer 为空串（未指定）的记录**计入 total 但不参与分摊**，
  避免「结余」出现虚假的谁欠谁；未知币种且未提供汇率 → 明确报错，不编造汇率。

边界（最小版明确不做）：
- 不做多币种的行程级基准币切换（整体 CNY 口径，见 budget_service 注释）；
- 不做实时汇率（需凭证，本任务评估关单，与 price-alert-eval 同构）；
- 不做自动分类 / 24h 超预算预警（需常驻任务，Journelyx 付费卖点，评估降级）；
- 不做还款/结算闭环（谁付给谁），只做「结余」——结余为正 = 别人欠他，
  为负 = 他欠别人；实际转账由用户线下完成；
- 不做费用修改端点（见上文 append-only 语义）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models import Trip, TripExpense
from app.schemas import ExpenseIn

# ── 零凭证汇率规则库（task-multi-currency-expense-eval）──────────────────
# 只放**长期稳定**的参考中间价（市场波动会变，但作为「用户没填汇率时的兜底」可接受；
# 数据标注 basis=rule_based，前端可提示「参考汇率，请以实际结算为准」）。
# 绝不用实时汇率 API（零凭证哲学，与 price-alert-eval / open-hours-real-eval 同构）。
_RULE_RATES: dict[str, float] = {
    "CNY": 1.0,
    "USD": 7.1,
    "EUR": 7.7,
    "JPY": 0.047,
    "KRW": 0.0052,
    "GBP": 9.0,
    "THB": 0.20,
    "SGD": 5.3,
    "MYR": 1.6,
    "AUD": 4.7,
}

_BASE_CURRENCY = "CNY"


def resolve_rate_to_base(currency: str, rate_to_base: float | None) -> float:
    """解析录入时的锁定汇率。

    - 显式 ``rate_to_base`` 优先（用户填写的真实成交汇率）；
    - 缺省时查规则库 ``_RULE_RATES``（CNY 恒为 1.0）；
    - 规则库也没有 → 抛 ValidationError（不编造汇率，诚实口径）。
    """
    if rate_to_base is not None and rate_to_base > 0:
        return rate_to_base
    normalized = (currency or _BASE_CURRENCY).strip().upper()
    if normalized in _RULE_RATES:
        return _RULE_RATES[normalized]
    raise AppError(
        f"未提供 {currency} → {_BASE_CURRENCY} 的汇率，且规则库暂无该币种；请填写约当汇率",
        code="currency_rate_required",
    )


async def add_expense(
    db: AsyncSession,
    trip_id: str,
    data: ExpenseIn,
    *,
    owner: str | None = None,
) -> TripExpense:
    """新增一条费用记录（owner 或受邀协作者）。"""
    from app.services.trip_service import get_trip

    await get_trip(db, trip_id, owner=owner)  # 归属校验（与 live_service 同信任语义）
    rate = resolve_rate_to_base(data.currency, data.rate_to_base)
    amount_base = round(data.amount * rate, 2)
    expense = TripExpense(
        trip_id=trip_id,
        category=data.category,
        amount=data.amount,
        amount_base=amount_base,
        currency=(data.currency or _BASE_CURRENCY).strip().upper(),
        rate_to_base=rate,
        payer=(data.payer or "").strip(),
        note=data.note,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return expense


async def delete_expense(
    db: AsyncSession,
    trip_id: str,
    expense_id: str,
    *,
    owner: str | None = None,
) -> None:
    """删除一条费用记录（物理删除 = 撤销误记；owner 专属）。"""
    from app.services.trip_service import get_trip

    await get_trip(db, trip_id, owner=owner)  # 归属校验
    result = await db.execute(
        delete(TripExpense).where(
            TripExpense.id == expense_id, TripExpense.trip_id == trip_id
        )
    )
    if result.rowcount == 0:
        raise NotFoundError("费用记录不存在", code="expense_not_found")
    await db.commit()


async def list_expenses(
    db: AsyncSession,
    trip_id: str,
    *,
    owner: str | None = None,
) -> tuple[list[TripExpense], dict[str, Any]]:
    """列出行程全部费用记录 + 分摊汇总（owner 视角；时间正序）。"""
    from app.services.trip_service import get_trip

    trip = await get_trip(db, trip_id, owner=owner)
    records = await _load_expenses(db, trip_id)
    return records, compute_balance(records, travelers=trip.travelers or 1)


async def list_expenses_by_trip(db: AsyncSession, trip: Trip) -> tuple[list[TripExpense], dict[str, Any]]:
    """已通过分享/编辑令牌校验访问权的场景：按已加载的 Trip 直接查（不做 owner 过滤）。"""
    records = await _load_expenses(db, trip.id)
    return records, compute_balance(records, travelers=trip.travelers or 1)


async def _load_expenses(db: AsyncSession, trip_id: str) -> list[TripExpense]:
    stmt = (
        select(TripExpense)
        .where(TripExpense.trip_id == trip_id)
        .order_by(TripExpense.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


def compute_balance(records: list[TripExpense], *, travelers: int) -> dict[str, Any]:
    """按支付人聚合出人均结余（纯函数，便于单测）。

    - ``total``：全部记录按基准币（CNY）折算后的合计（含未指定支付人）；
    - ``assigned``：指定支付人的记录折算后合计（参与分摊的部分）；
    - ``per_person``：人均应摊 = assigned ÷ travelers（travelers<1 视为 1）；
    - ``balances``：payer → 结余 = 该支付人已付 - 人均应摊（正=别人欠他，负=他欠别人）；
    - ``unassigned``：payer 为空串的记录折算后合计（不计入分摊，仅计入 total）。
    - ``currencies``：本批记录出现过的原币种集合（信息透出，不做折算干预）。

    多币种口径：一律以**录入时锁定的 amount_base**（= amount × 锁定汇率）聚合，
    历史记录不受汇率波动影响；四舍五入到分。结余的正负口径：
    正数表示「这个支付人垫付超过了人均」，别人应该还他；负数表示「他还没付够人均」。
    """
    n = travelers if travelers and travelers > 0 else 1
    total = 0.0
    assigned = 0.0
    unassigned = 0.0
    paid: dict[str, float] = {}
    currencies: set[str] = set()
    for r in records:
        amount = r.amount_base if r.amount_base is not None else (r.amount or 0.0)
        total += amount
        currencies.add((r.currency or "CNY").upper())
        payer = (r.payer or "").strip()
        if payer:
            assigned += amount
            paid[payer] = paid.get(payer, 0.0) + amount
        else:
            unassigned += amount

    per_person = round(assigned / n, 2) if assigned else 0.0
    balances = {p: round(v - per_person, 2) for p, v in paid.items()}
    return {
        "total": round(total, 2),
        "assigned": round(assigned, 2),
        "per_person": per_person,
        "balances": balances,
        "unassigned": round(unassigned, 2),
        "travelers": n,
        "count": len(records),
        "currencies": sorted(currencies),
    }
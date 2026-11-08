"""登录用户额度治理（task-quota-governance-eval：最小版 = 计数 + 软提示）。

设计哲学（与 time_validation / expense_service 同源）：

- **零表零迁移**：直接统计既有 ``plan_tasks``（``owner`` + ``created_at``），不新增表、
  不加列——额度只是既有数据的投影。
- **只提示不拦截**：本版**没有**硬限流。软阈值只驱动前端文案，绝不让一个合规请求
  失败（硬配额/限流与 guest-trial 重启同源，需用户立项，见评估记录
  ``docs/nightly/evaluations/task-quota-governance-eval-2026-11-08.md``）。
- **诚实口径**：返回窗口、已用、阈值与"最早一次何时释放"，前端原样展示；
  不承诺「还剩 N 次」之外的任何东西，也不做假数据。
- **纯函数可测**：``summarize`` 不碰 DB，窗口统计与阈值判断可单测。

行业参照（2026-11 竞品分析）：Wanderlog 免费档 AI 5–10 条封顶、Pro 无限，但**行程数
与协作人数永不限制**——限制的是 LLM 调用，不是用户的数据。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlanTask

# 滚动窗口：24 小时（自然意义上的「今天」不依赖时区，滚动窗口对用户更可解释）
WINDOW_HOURS = 24
# 软阈值：仅用于提示文案（Wanderlog 免费档 5–10 条；我们给自托管者更宽松的参考线）
SOFT_LIMIT = 10


def summarize(
    *,
    used: int,
    limit: int = SOFT_LIMIT,
    window_hours: int = WINDOW_HOURS,
    resets_at: datetime | None = None,
) -> dict:
    """纯函数：把「已用次数」折叠成前端可消费的额度快照。

    ``remaining`` 下限为 0（不返回负数）；``soft_limit_reached`` 表示**达到**阈值
    （``>=``）而不是超过——文案要说的是「该提醒了」，不是「你违法了」。
    """
    used = max(0, int(used))
    limit = max(1, int(limit))
    return {
        "used": used,
        "limit": limit,
        "window_hours": int(window_hours),
        "remaining": max(0, limit - used),
        "soft_limit_reached": used >= limit,
        "resets_at": resets_at,
    }


async def snapshot(
    db: AsyncSession,
    owner: str,
    *,
    now: datetime | None = None,
    limit: int = SOFT_LIMIT,
    window_hours: int = WINDOW_HOURS,
) -> dict:
    """统计 ``owner`` 在最近 ``window_hours`` 小时内创建的规划任务。

    单条聚合查询同时取「次数」与「最早一次创建时间」——后者用于算 ``resets_at``
    （滚动窗口里最早那次滑出窗口时，剩余次数就会释放）。
    """
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=window_hours)
    stmt = select(func.count(PlanTask.id), func.min(PlanTask.created_at)).where(
        PlanTask.owner == owner,
        PlanTask.created_at >= since,
    )
    used, oldest = (await db.execute(stmt)).one()
    resets_at = None
    if oldest is not None:
        # created_at 可能是 naive（测试库 server_default），统一按 UTC 解释后加窗口
        base = oldest if oldest.tzinfo is not None else oldest.replace(tzinfo=UTC)
        resets_at = base + timedelta(hours=window_hours)
    return summarize(used=int(used or 0), limit=limit, window_hours=window_hours, resets_at=resets_at)

"""人工兜底最小版（task-human-escalation-eval）。

背景：当前降级链以「结构化降级响应」收尾（Critic 失败 → degraded 通过；
达最大评审轮 → 强制定稿），无人工评审入口。OTA 有真人定制师场景
（低置信 / 反复修订失败）我们直接放弃。

方案：零 schema 演进——escalation 信号从 ``TripPlan.plan_data.quality``
**派生**（finalized / passed=false / degraded），不新增表/列，无生命周期
管理负担。评审列表 API 给 owner 一个可查队列（自托管者自行接人工）。

设计原则：
- 不假装有人：escalated 只表示「建议人工复核」，不自动发通知、不阻塞任何流程
- 派生而非存储：quality 更新（重新规划/修订）后 escalation 状态自然翻新
- 低置信阈值：passed=false 已覆盖「Critic 未通过 / 修订复核未通过」；
  不再额外用分数阈值（避免把「通过但分不高」误报）
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trip, TripPlan
from app.schemas import EscalationOut, EscalationQualityOut

# 低置信分数底线（Critic 通过线，与 agent/agents.py CRITIC_PASS_SCORE 同值语义；
# 此处仅用于摘要排序/展示，不参与判定——判定只看 passed/finalized/degraded）
CRITIC_PASS_SCORE = 80


def escalate_from_quality(quality: dict[str, Any] | None) -> bool:
    """plan.quality → 是否需要人工复核。

    - ``finalized=true``：达最大评审轮强制定稿（评审没走完就被定稿）
    - ``passed=false``：Critic 未通过 / 修订复核未通过（低置信）
    - ``degraded=true``：Critic 调用失败降级通过（健康风险信号）

    其余（正常通过 / 无评审 / quality=None）不升级。
    """
    if not quality:
        return False
    if quality.get("finalized"):
        return True
    if quality.get("passed") is False:
        return True
    if quality.get("degraded"):
        return True
    return False


def escalation_summary(quality: dict[str, Any] | None) -> dict[str, Any]:
    """从 quality 提炼结构化失败摘要（给评审队列展示）。"""
    if not quality:
        return {"reason": None, "summary": None, "issues": [], "score": None}
    reasons: list[str] = []
    if quality.get("finalized"):
        reasons.append("finalized")
    if quality.get("passed") is False:
        reasons.append("low_confidence")
    if quality.get("degraded"):
        reasons.append("degraded")
    return {
        "reason": reasons[0] if reasons else None,
        "summary": quality.get("summary"),
        "issues": (quality.get("issues") or [])[:5],
        "score": quality.get("score"),
    }


async def list_escalations(
    db: AsyncSession,
    *,
    owner: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[EscalationOut], int]:
    """当前 owner 的「需人工复核」行程列表（评审队列）。

    实现：查该 owner 全部 Trip → 每 trip 最新 TripPlan → 从 plan_data.quality
    派生 escalated → 过滤。数据量级（个人行程）下 N+1 可忽略（每 trip 最新
    plan 一次查询，selectin 预载）。
    """
    from app.services._common import TRIP_LOADS as _TRIP_LOADS

    trips_stmt = (
        select(Trip)
        .options(*_TRIP_LOADS)
        .where(Trip.owner == owner)
        .order_by(Trip.updated_at.desc())
    )
    trips = (await db.execute(trips_stmt)).scalars().all()

    # 每 trip 最新 plan（plan_data.quality 是权威信号来源）
    plans_stmt = (
        select(TripPlan)
        .where(TripPlan.trip_id.in_([t.id for t in trips]))
        .order_by(TripPlan.created_at.desc())
    )
    plans = (await db.execute(plans_stmt)).scalars().all()
    latest_by_trip: dict[str, TripPlan] = {}
    for p in plans:
        latest_by_trip.setdefault(p.trip_id, p)

    items: list[EscalationOut] = []
    for trip in trips:
        plan = latest_by_trip.get(trip.id)
        if plan is None:
            continue  # 无 AI 方案（手工行程）不升级
        quality = (plan.plan_data or {}).get("quality")
        if not escalate_from_quality(quality):
            continue
        q = escalation_summary(quality)
        items.append(
            EscalationOut(
                trip_id=trip.id,
                title=trip.title,
                destination=trip.destination,
                start_date=trip.start_date,
                end_date=trip.end_date,
                budget=trip.budget,
                escalated_at=plan.created_at.isoformat() if plan.created_at else None,
                quality=EscalationQualityOut(
                    reason=q["reason"],
                    summary=q["summary"],
                    issues=q["issues"],
                    score=q["score"],
                ),
            )
        )

    items.sort(key=lambda x: x.escalated_at or "", reverse=True)
    total = len(items)
    return items[offset : offset + limit], total
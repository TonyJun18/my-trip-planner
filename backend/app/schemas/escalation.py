"""人工兜底评审队列 Schemas（task-human-escalation-eval）。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class EscalationQualityOut(BaseModel):
    """结构化失败摘要（从 plan.quality 提炼，供 owner 评审/自托管接人工）。"""

    reason: str | None = None  # finalized / low_confidence / degraded
    summary: str | None = None
    issues: list = Field(default_factory=list)  # 最多 5 条
    score: int | None = None


class EscalationOut(BaseModel):
    """评审队列中的一条（escalated 行程 + 失败摘要）。"""

    trip_id: str
    title: str
    destination: str
    start_date: date
    end_date: date
    budget: float | None = None
    escalated_at: str | None = None
    quality: EscalationQualityOut = Field(default_factory=EscalationQualityOut)


class EscalationListOut(BaseModel):
    items: list[EscalationOut] = []
    total: int = 0
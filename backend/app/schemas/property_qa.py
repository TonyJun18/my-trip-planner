"""行程内结构化事实问答 Schemas（task-property-qa-eval）。

设计口径（详见 docs/nightly/evaluations/task-property-qa-eval-2026-11-10.md）：
- 只回答「结构化字段里真实存在」的事实；无数据 → available=false + unknown 文案，
  绝不编造数字/时间（防编造口径，LLM 自由问答明确不做）。
- basis 标注答案来源：explicit（显式字段）/ rule_based（类目规则库推断）/
  none（无数据），供前端透出「估算/推断口径」。
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PropertyQaFact(BaseModel):
    """一条可答的结构化事实（无 q 时的「可问什么」清单项）。"""

    kind: str  # hours / rating / price / duration
    target: str  # 站点名
    value: str | None = None
    basis: str = "explicit"  # explicit / rule_based
    available: bool = True


class PropertyQaOut(BaseModel):
    """单个问题（q 参数）的答案。"""

    question: str
    matched_type: str  # hours / budget / warning / rating / price / duration / unknown
    target: str | None = None  # 命中的站点名（如适用）
    available: bool = False
    answer: str | None = None
    basis: str = "none"  # explicit / rule_based / none
    detail: dict = Field(default_factory=dict)  # 结构化数据（供前端渲染）


class PropertyQaFactsOut(BaseModel):
    """不带 q 时的「当前可答事实清单」。"""

    trip_id: str
    title: str
    destination: str
    start_date: date | None = None
    end_date: date | None = None
    facts: list[PropertyQaFact] = Field(default_factory=list)
    budget: dict = Field(default_factory=dict)  # 预算汇总（有则带口径）
    warnings: list[dict] = Field(default_factory=list)  # 质检预警（time_gate/dynamic_facts/weather_gate）
    suggestions: list[str] = Field(default_factory=list)  # 示例问题
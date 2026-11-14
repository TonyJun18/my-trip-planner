"""质检报告 Schemas（task-trip-quality-report-a：五类只读聚合）。

只读输出契约：不含任何凭证/订单/令牌字段；gate 未检查时 checked=false
（不编造「通过了」）。单 gate issues 上限 20（与 Critic 输出上限一致）。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class QualityGateOut(BaseModel):
    """一类质检 gate 的聚合结果（owner/share 双路径共用）。"""

    model_config = ConfigDict(extra="ignore")

    key: str
    title_key: str = ""
    checked: bool = False       # gate 是否存在于 plan（缺失 → false，绝不假装查过）
    passed: bool | None = None  # None = 未检查
    warning_count: int = 0
    issues: list[dict] = Field(default_factory=list)
    basis: str | None = None    # rule_based / weather_forecast / llm（诚实口径）
    score: int | None = None    # 仅 quality gate 有
    summary: str | None = None


class QualityReportOut(BaseModel):
    """质检报告（五类 gate + 汇总统计）。"""

    model_config = ConfigDict(extra="ignore")

    gates: list[QualityGateOut] = Field(default_factory=list)
    total_issues: int = 0
    checked_gates: int = 0
    passed_gates: int = 0
    generated_at: str | None = None
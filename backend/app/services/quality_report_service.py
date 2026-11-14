"""质检五类只读聚合报告（task-trip-quality-report-a）。

从 ``TripPlan.plan_data`` 聚合五类质检信号，供 owner / 分享只读查看：
- ``quality``      —— AI Critic 评审（score / passed / issues / finalized）
- ``time_gate``    —— TimeGate 时间校验（营业时间 / 过饱和 / 餐饮锚定）
- ``repeat_gate``  —— RepeatGate 重复站点查重（独立露出，此前只并进 warnings）
- ``weather_gate`` —— WeatherGate 天气感知排程（雨天/酷暑室内替代建议）
- ``dynamic_facts``—— DynamicFacts 日期特例（周一闭馆 / 免费日 / 节假日）

设计原则（与仓库哲学一致）：
- **纯函数只读**：只聚合 plan 快照，不重新计算、不写库、零 LLM；
- **诚实口径**：gate 缺失 / 从未检查 → ``checked=false``，绝不编造「通过了」；
- **双路径**：owner（JWT）与 share（免登录令牌）复用同一构建函数，访问控制由
  API 层保证（与 export_service 同模式）；
- **不含凭证**：只输出质检结论（severity/message/suggestion/day_number），
  不输出任何订单号/凭证/令牌字段。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# 五类质检 gate 的顺序（面板展示次序）
GATE_KEYS: tuple[str, ...] = (
    "quality",
    "time_gate",
    "repeat_gate",
    "weather_gate",
    "dynamic_facts",
)


def _gate_status(gate: dict[str, Any] | None) -> dict[str, Any]:
    """归一化单个 gate 的输出（缺失 → checked=false，不编造通过）。"""
    if not gate or not isinstance(gate, dict):
        return {
            "key": "",
            "checked": False,
            "passed": None,
            "warning_count": 0,
            "issues": [],
            "basis": None,
            "score": None,
            "summary": None,
        }
    issues = gate.get("issues") or []
    return {
        "key": "",
        "checked": True,
        "passed": gate.get("passed"),
        "warning_count": len(issues),
        "issues": issues[:20],  # 单 gate 最多 20 条（与 Critic 输出上限一致）
        "basis": gate.get("basis"),
        "score": gate.get("score"),
        "summary": gate.get("summary"),
    }


def build_quality_report(plan_data: dict[str, Any] | None) -> dict[str, Any]:
    """从 plan_data 构建质检报告（纯函数，无 DB / 无 LLM / 无网络）。

    - plan_data 为 None / {}（行程未 AI 规划）→ gates 全部 checked=false，
      绝不假装查过；
    - 每个 gate 附带 title_key（前端 i18n 键），服务端不产文案；
    - ``total_issues`` / ``checked_gates`` / ``passed_gates`` 供面板头部统计。
    """
    data = plan_data or {}
    gates: list[dict[str, Any]] = []
    for key in GATE_KEYS:
        status = _gate_status(data.get(key))
        status["key"] = key
        status["title_key"] = f"qualityReport.gate.{key}"
        gates.append(status)

    checked = [g for g in gates if g["checked"]]
    return {
        "gates": gates,
        "total_issues": sum(g["warning_count"] for g in gates),
        "checked_gates": len(checked),
        "passed_gates": sum(1 for g in checked if g["passed"] is True),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
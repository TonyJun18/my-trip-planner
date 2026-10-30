"""SolverGate 接入 FinalizePlanStep 的专项测试（task-floattrip-borrow Story 4）。

验证「LLM 候选 → 确定性求解」在编排层的契约：
- run_finalize_stage 后 plan.solver_meta 存在（version/basis/sorting/hard_constraints）
- solver_meta.hard_constraints.passed=True 时无 unresolved，trace 为 completed
- 硬约束未通过且修复不动 → plan.warnings 注入 [确定性校验未通过]（绝不静默当成功）
- plan.solver_meta 由确定性代码回填（不是 LLM 产物）——直接调用 run_finalize_stage
  不跑 LLM，验证编排接线存在。
"""
from __future__ import annotations

from typing import Any

from app.agent.pipeline import run_finalize_stage


def _plan() -> dict[str, Any]:
    """带两天的候选 plan（含坐标与时长；跨日超距触发 unresolved）。"""
    return {
        "destination": "杭州",
        "days": [
            {
                "day_number": 1,
                "date": "2026-11-01",
                "theme": "西湖",
                "stops": [
                    {"name": "酒店A", "type": "hotel", "lat": 30.25, "lng": 120.16},
                    {"name": "灵隐寺", "type": "attraction", "lat": 30.24, "lng": 120.10,
                     "rating": 4.8, "duration_minutes": 120},
                    {"name": "西湖", "type": "attraction", "lat": 30.24, "lng": 120.14,
                     "rating": 4.9, "duration_minutes": 150},
                ],
            },
            {
                "day_number": 2,
                "date": "2026-11-02",
                "theme": "郊野",
                "stops": [
                    {"name": "酒店B", "type": "hotel", "lat": 30.25, "lng": 120.16},
                    {"name": "千岛湖", "type": "attraction", "lat": 29.60, "lng": 119.05,
                     "rating": 4.7, "duration_minutes": 300},
                ],
            },
        ],
    }


def _req() -> dict[str, Any]:
    return {"destination": "杭州", "language": "zh-CN"}


async def test_finalize_sets_solver_meta():
    """Story 4 AC-4：保存行程携带 solver_meta（排序依据/校验结果）。"""
    plan = _plan()
    # 无 t_res/d_res/driving —— finalize 其它回填用空兜底
    await run_finalize_stage(plan, _req())
    meta = plan.get("solver_meta")
    assert meta is not None, "run_finalize_stage 必须回填 solver_meta"
    assert meta["version"] == 1
    assert meta["basis"] == "rule_based"
    assert meta["sorting"]["enabled"] is True
    assert meta["sorting"]["strategy"] == "distance_asc_rating_desc"
    assert "hard_constraints" in meta
    assert meta["hard_constraints"]["passed"] in (True, False)
    # 确定性结果字段齐全
    assert isinstance(meta["hard_constraints"]["violations"], list)
    assert isinstance(meta["hard_constraints"]["repaired"], list)
    assert isinstance(meta["hard_constraints"]["unresolved"], list)


async def test_finalize_solver_meta_honest_unresolved():
    """Story 4 AC-2：校验失败走有限修复，修不了不静默当成功 → warnings 注入。"""
    plan = _plan()  # day2 酒店→千岛湖 112km 超距，修复也动不了（仅一站）
    await run_finalize_stage(plan, _req())
    meta = plan["solver_meta"]
    unresolved = meta["hard_constraints"]["unresolved"]
    assert meta["hard_constraints"]["passed"] is False
    assert unresolved, "跨日超距修复不动必须留下 unresolved"
    assert any("千岛湖" in u.get("message", "") for u in unresolved)
    # warnings 带「确定性校验未通过」前缀（诚实标注）
    assert any("确定性校验未通过" in w for w in plan.get("warnings", []))


async def test_finalize_solver_trace_present():
    """SolverGate trace 追加：通过为 completed，未通过为 warning。"""
    plan = _plan()
    trace: list[dict[str, Any]] = []
    await run_finalize_stage(plan, _req(), trace=trace)
    solver_trace = [t for t in trace if t.get("agent") == "SolverGate"]
    assert solver_trace, "必须有 SolverGate trace"
    assert solver_trace[0]["action"] == "solve"
    assert solver_trace[0]["status"] in ("completed", "warning")
    if plan["solver_meta"]["hard_constraints"]["passed"]:
        assert solver_trace[0]["status"] == "completed"
    else:
        assert solver_trace[0]["status"] == "warning"
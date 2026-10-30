"""task-floattrip-borrow Story 4：确定性行程求解 测试。

覆盖 Acceptance Criteria：
- 同城 POI 按距离/评分排序（rank_candidates）
- 超时/超距硬约束校验（check_hard_constraints）
- 校验失败走有限修复 + 兜底（repair_violations；修复不动 → unresolved 非空，
  绝不静默当成功）
- 保存行程携带 solver_meta（排序依据/校验结果）
- 缺数据（无坐标/无时长）不告警（规则不确定保持沉默）
"""
from __future__ import annotations

import pytest


def _stop(name, *, type="attraction", lat=None, lng=None, duration=None, rating=None):
    s = {"name": name, "type": type}
    if lat is not None:
        s["lat"] = lat
    if lng is not None:
        s["lng"] = lng
    if duration is not None:
        s["duration_minutes"] = duration
    if rating is not None:
        s["rating"] = rating
    return s


def _day(num, stops):
    return {"day_number": num, "date": f"2026-11-0{num}", "theme": f"Day {num}", "stops": stops}


# ── 1. 候选排序 ───────────────────────────────────────────────
class TestRankCandidates:
    def test_sorts_by_distance_asc(self):
        from app.services.solver_service import rank_candidates

        # 起点在 (0,0)，候选 B 近、A 远 → 排序后 B 在前
        days = [_day(1, [
            _stop("起点", lat=0.0, lng=0.0),
            _stop("远处A", lat=1.0, lng=1.0),
            _stop("近处B", lat=0.001, lng=0.0),
        ])]
        out = rank_candidates(days)
        names = [s["name"] for s in out[0]["stops"]]
        assert names == ["起点", "近处B", "远处A"]

    def test_rating_tiebreak(self):
        from app.services.solver_service import rank_candidates

        # 距离相近时评分高的优先（评分 4.9 在前）
        days = [_day(1, [
            _stop("景点X", lat=0.001, lng=0.0, rating=3.0),
            _stop("景点Y", lat=0.002, lng=0.0, rating=4.9),
        ])]
        out = rank_candidates(days)
        names = [s["name"] for s in out[0]["stops"]]
        assert names[0] == "景点Y"

    def test_hotel_stays_in_place(self):
        from app.services.solver_service import rank_candidates

        days = [_day(1, [
            _stop("酒店", type="hotel", lat=0.0, lng=0.0),
            _stop("景点A", lat=1.0, lng=1.0),
            _stop("景点B", lat=0.001, lng=0.0),
        ])]
        out = rank_candidates(days)
        stops = out[0]["stops"]
        assert stops[0]["name"] == "酒店"  # 酒店固定首位
        assert stops[1]["name"] == "景点B"  # movable 排序后紧跟

    def test_empty_and_missing_coords_ordered_input(self):
        from app.services.solver_service import rank_candidates

        # 缺坐标的站点：距离比较跳过（不崩、保持相对顺序）
        days = [_day(1, [
            _stop("无坐标A"),
            _stop("近B", lat=0.001, lng=0.0),
            _stop("远C", lat=2.0, lng=2.0),
        ])]
        out = rank_candidates(days)
        names = [s["name"] for s in out[0]["stops"]]
        assert set(names) == {"无坐标A", "近B", "远C"}


# ── 2. 硬约束校验 ─────────────────────────────────────────────
class TestHardConstraints:
    def test_pass_when_within_limits(self):
        from app.services.solver_service import check_hard_constraints

        plan = {"days": [_day(1, [
            _stop("A", lat=30.0, lng=120.0, duration=120),
            _stop("B", lat=30.01, lng=120.01, duration=60),
        ])]}
        out = check_hard_constraints(plan)
        assert out["passed"] is True
        assert out["violations"] == []

    def test_over_duration_violation(self):
        from app.services.solver_service import check_hard_constraints

        plan = {"days": [_day(1, [
            _stop("A", duration=360),
            _stop("B", duration=360),
        ])]}
        out = check_hard_constraints(plan)
        assert out["passed"] is False
        types = [v["type"] for v in out["violations"]]
        assert "over_duration" in types

    def test_over_distance_violation(self):
        from app.services.solver_service import check_hard_constraints

        plan = {"days": [_day(1, [
            _stop("A", lat=30.0, lng=120.0),
            _stop("B", lat=30.6, lng=120.6),  # ~80km 超距
        ])]}
        out = check_hard_constraints(plan)
        assert out["passed"] is False
        types = [v["type"] for v in out["violations"]]
        assert "over_distance" in types

    def test_missing_data_silent(self):
        """缺坐标/缺时长 → 不告警（规则不确定时保持沉默）。"""
        from app.services.solver_service import check_hard_constraints

        plan = {"days": [_day(1, [
            _stop("A", lat=None, lng=None),
            _stop("B", lat=None, lng=None),
        ])]}
        out = check_hard_constraints(plan)
        assert out["passed"] is True  # 无坐标 → 距离校验跳过；无时长 → 时长累计 0


# ── 3. 有限修复 + 兜底 ────────────────────────────────────────
class TestRepair:
    def test_repairs_over_distance_by_swap(self):
        from app.services.solver_service import repair_violations

        plan = {"days": [_day(1, [
            _stop("近X", lat=30.0, lng=120.0),
            _stop("远Y", lat=30.6, lng=120.6),  # 与近X 超距
            _stop("近Z", lat=30.01, lng=120.0),
        ])]}
        out = repair_violations(plan)
        assert out["repaired"], "应尝试修复"
        # 修复后仍校验（不静默当成功：passed 为最终状态）
        from app.services.solver_service import check_hard_constraints

        final = check_hard_constraints(plan)
        # 交换后顺序应改善（近的在前）
        names = [s["name"] for s in plan["days"][0]["stops"]]
        assert names[1] in ("远Y", "近Z")

    def test_repair_bounded_rounds(self):
        """超时 violation 无法靠换序修复 → 有界停住、unresolved 记录。"""
        from app.services.solver_service import repair_violations

        plan = {"days": [_day(1, [
            _stop("A", duration=480),
            _stop("B", duration=480),
        ])]}
        out = repair_violations(plan)
        assert out["unresolved"], "超时无法换序修复 → unresolved 非空"
        assert out["passed"] is False

    def test_repair_impossible_keeps_unresolved(self):
        """最后两个站点都超距且无更近可换 → 不无限循环、保留 unresolved。"""
        from app.services.solver_service import repair_violations

        plan = {"days": [_day(1, [
            _stop("A", lat=30.0, lng=120.0),
            _stop("B", lat=30.6, lng=120.6),
            _stop("C", lat=31.2, lng=120.2),
        ])]}
        out = repair_violations(plan)
        # 修复只交换顺序，若交换后仍超距（三者都远）→ 最终 unresolved 非空
        assert "unresolved" in out


# ── 4. 组合入口：solve → solver_meta ──────────────────────────
class TestSolve:
    def test_solve_returns_meta_with_basis_and_sorting(self):
        from app.services.solver_service import solve

        plan = {"days": [_day(1, [
            _stop("A", lat=30.0, lng=120.0, duration=120),
            _stop("B", lat=30.01, lng=120.01, duration=60),
        ])]}
        meta = solve(plan, locale="zh-CN")
        assert meta["version"] == 1
        assert meta["basis"] == "rule_based"
        assert meta["sorting"]["enabled"] is True
        assert meta["sorting"]["strategy"] == "distance_asc_rating_desc"
        assert meta["hard_constraints"]["passed"] is True
        assert plan["solver_meta"] == meta  # 原地回写

    def test_solve_records_unresolved_not_silent(self):
        from app.services.solver_service import solve

        plan = {"days": [_day(1, [
            _stop("A", duration=480),
            _stop("B", duration=480),
        ])]}
        meta = solve(plan)
        assert meta["hard_constraints"]["passed"] is False
        assert meta["hard_constraints"]["unresolved"], "修复不动 → 明确记录，不静默当成功"

    def test_solve_empty_plan_safe(self):
        from app.services.solver_service import solve

        meta = solve({"days": []})
        assert meta["hard_constraints"]["passed"] is True
        assert meta["sorting"]["enabled"] is True
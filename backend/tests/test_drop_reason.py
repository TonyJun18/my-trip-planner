"""decision-drop-reason 纯函数规则库测试（task-decision-drop-reason-eval）。

覆盖（对齐 openspec/changes/2026-11-20-decision-drop-reason/spec.md）：
1. 五类 reason 各命中场景：budget_over / distance_too_far / category_mismatch /
   capacity_full / pacing_conflict
2. 输出契约 {stop_id, name, reason_code, reason_i18n_key, basis="rule_based"}
3. 预算判定复用预算档口径、距离判定复用 DrivingGate haversine 阈值
4. 无淘汰 → 空数组；数据不足（无 cost/无坐标）→ 不产生理由（诚实沉默）
"""
from __future__ import annotations

from app.services.drop_reason_service import compute_drop_reasons

# 杭州（约 30.25, 120.17）市中心
_HZ = (30.25, 120.17)
# 距杭州 ~1000km+ 的离群点
_FAR = (38.04, 114.51)


def _cand(name, *, cost=None, lat=None, lng=None, typ="attraction", stop_id=None, **kw):
    return {
        "stop_id": stop_id or name,
        "name": name,
        "type": typ,
        "estimated_cost": cost,
        "lat": lat,
        "lng": lng,
        **kw,
    }


def _ctx(**kw):
    return {
        "budget": 3000,          # 总预算（元）
        "days": 3,               # 行程天数
        "travelers": 1,          # 人数 → 单日人均预算 = budget/days/travelers
        "anchor": _HZ,           # 当日锚点坐标
        "preferred_types": ["attraction", "food"],
        **kw,
    }


# ── 1. 五类 reason 各命中场景 ────────────────────────────────

def test_budget_over():
    """候选人均消费 > 单日预算档 → budget_over。"""
    # 单日人均预算 = 3000/3/1 = 1000；候选 cost=2000 → 超
    cands = [_cand("A", cost=2000, lat=30.25, lng=120.17)]
    kept = []
    drops = compute_drop_reasons(cands, kept, _ctx())
    assert len(drops) == 1
    d = drops[0]
    assert d["name"] == "A"
    assert d["reason_code"] == "budget_over"
    assert d["reason_i18n_key"] == "dropReason.budgetOver"
    assert d["basis"] == "rule_based"


def test_distance_too_far():
    """候选距锚点 > DrivingGate haversine 阈值（MAX_LEG_KM=120）→ distance_too_far。"""
    cands = [_cand("B", lat=_FAR[0], lng=_FAR[1])]  # 距杭州 ~1000km+
    drops = compute_drop_reasons(cands, [], _ctx())
    assert drops[0]["reason_code"] == "distance_too_far"
    assert drops[0]["reason_i18n_key"] == "dropReason.distanceTooFar"


def test_category_mismatch():
    """类目不匹配用户偏好类目 → category_mismatch。"""
    # preferred_types 只有 attraction/food；候选是 hotel → 类目不匹配
    cands = [_cand("C", typ="hotel", lat=30.25, lng=120.17)]
    drops = compute_drop_reasons(cands, [], _ctx())
    assert drops[0]["reason_code"] == "category_mismatch"
    assert drops[0]["reason_i18n_key"] == "dropReason.categoryMismatch"


def test_capacity_full():
    """当日容量已满（kept 已达 MAX_STOPS_PER_DAY=5）→ capacity_full。"""
    kept = [_cand(f"k{i}", lat=30.25, lng=120.17) for i in range(5)]  # 已满 5 站
    cands = [_cand("D", lat=30.25, lng=120.17)]
    drops = compute_drop_reasons(cands, kept, _ctx())
    assert drops[0]["reason_code"] == "capacity_full"
    assert drops[0]["reason_i18n_key"] == "dropReason.capacityFull"


def test_pacing_conflict():
    """行程过满（kept 时长超限 / 节奏冲突）→ pacing_conflict。"""
    # 用超长时长模拟节奏冲突：kept 单日累计 > MAX_DAY_DURATION_MINUTES(600)
    kept = [_cand("k1", lat=30.25, lng=120.17, duration_minutes=700, typ="attraction")]
    cands = [_cand("E", lat=30.25, lng=120.17)]
    drops = compute_drop_reasons(cands, kept, _ctx())
    assert drops[0]["reason_code"] == "pacing_conflict"
    assert drops[0]["reason_i18n_key"] == "dropReason.pacingConflict"


# ── 2. 输出契约 ──────────────────────────────────────────────

def test_output_contract():
    cands = [_cand("A", cost=2000, lat=30.25, lng=120.17)]
    drops = compute_drop_reasons(cands, [], _ctx())
    assert set(drops[0].keys()) == {"stop_id", "name", "reason_code", "reason_i18n_key", "basis"}
    assert drops[0]["stop_id"] == "A"
    assert drops[0]["name"] == "A"
    assert drops[0]["basis"] == "rule_based"


# ── 3. 无淘汰 / 数据不足沉默 ─────────────────────────────────

def test_no_drops_empty():
    """无淘汰 → 空数组。"""
    cands = [
        _cand("A", cost=500, lat=30.25, lng=120.17),
        _cand("B", cost=600, lat=30.24, lng=120.10),
    ]
    kept = [_cand("A", cost=500, lat=30.25, lng=120.17), _cand("B", cost=600, lat=30.24, lng=120.10)]
    assert compute_drop_reasons(cands, kept, _ctx()) == []


def test_data_insufficient_silent():
    """无 cost 无坐标 → 无法判定，不产生理由（诚实沉默）。"""
    cands = [_cand("X", cost=None, lat=None, lng=None)]
    drops = compute_drop_reasons(cands, [], _ctx())
    assert drops == []


def test_kept_not_dropped():
    """入选候选绝不产生淘汰理由；未入选但命中规则 → 只记入选外的。"""
    cands = [
        _cand("A", cost=2000, lat=30.25, lng=120.17),
        _cand("B", cost=2000, lat=30.24, lng=120.10),
    ]
    kept = [_cand("A", cost=2000, lat=30.25, lng=120.17)]  # A 入选（即使超预算，入选就是入选）
    drops = compute_drop_reasons(cands, kept, _ctx())
    assert all(d["name"] != "A" for d in drops)
    assert [d["name"] for d in drops] == ["B"]
    assert drops[0]["reason_code"] == "budget_over"


def test_kept_not_dropped_no_reason_silent():
    """未入选但无规则命中（数据不全/无超限）→ 不编造理由。"""
    cands = [_cand("A", cost=500, lat=30.25, lng=120.17)]  # 无超限但未入选
    drops = compute_drop_reasons(cands, [_cand("B", cost=500, lat=30.24, lng=120.10)], _ctx())
    assert drops == []
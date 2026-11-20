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
        "stop_type": typ,  # plan_b / solver 读取 stop_type（solver 读 type）
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


# ═══════════════════════════════════════════════════════════
# Task 5：三个筛选出口挂载 drops（solver / plan_b / hotel）
# ═══════════════════════════════════════════════════════════

# ── ① solver_meta.drops ─────────────────────────────────────

def test_solver_solve_records_capacity_drops():
    """单日 6 站（>MAX_STOPS_PER_DAY=5）→ 第 6 站进 solver_meta.drops（capacity_full），与保留互斥。"""
    from app.services.solver_service import solve

    plan = {
        "days": [{
            "day_number": 1,
            "stops": [
                _cand("A", cost=100, lat=30.25, lng=120.17),
                _cand("B", cost=100, lat=30.24, lng=120.10),
                _cand("C", cost=100, lat=30.23, lng=120.09),
                _cand("D", cost=100, lat=30.26, lng=120.08),
                _cand("E", cost=100, lat=30.22, lng=120.11),
                _cand("F", cost=100, lat=30.27, lng=120.13),
            ],
        }],
        "budget": 3000,
    }
    meta = solve(plan, locale="zh-CN")
    drops = meta.get("drops") or []
    assert len(drops) >= 1
    assert all(d["reason_code"] == "capacity_full" for d in drops)
    kept_names = {s["name"] for s in plan["days"][0]["stops"][:5]}
    assert all(d["name"] not in kept_names for d in drops)


def test_solver_solve_no_drops_when_within_capacity():
    """单日 ≤5 站 → solver_meta 无 drops（不产出空理由）。"""
    from app.services.solver_service import solve

    plan = {
        "days": [{
            "day_number": 1,
            "stops": [
                _cand("A", cost=100, lat=30.25, lng=120.17),
                _cand("B", cost=100, lat=30.24, lng=120.10),
                _cand("C", cost=100, lat=30.23, lng=120.09),
            ],
        }],
        "budget": 3000,
    }
    meta = solve(plan, locale="zh-CN")
    assert "drops" not in meta or meta["drops"] == []


def test_solver_solve_budget_over_recorded():
    """超预算的溢出站 → budget_over（优先于 capacity_full）。"""
    from app.services.solver_service import solve

    plan = {
        "days": [{
            "day_number": 1,
            "stops": [
                _cand("A", cost=100, lat=30.25, lng=120.17),
                _cand("B", cost=100, lat=30.24, lng=120.10),
                _cand("C", cost=100, lat=30.23, lng=120.09),
                _cand("D", cost=100, lat=30.26, lng=120.08),
                _cand("E", cost=100, lat=30.22, lng=120.11),
                _cand("贵站", cost=5000, lat=30.27, lng=120.13),
            ],
        }],
        "budget": 3000,
    }
    meta = solve(plan, locale="zh-CN")
    drops = meta.get("drops") or []
    names = [d["name"] for d in drops]
    assert "贵站" in names
    expensive = next(d for d in drops if d["name"] == "贵站")
    assert expensive["reason_code"] == "budget_over"


# ── ② plan_b 变体 drop 记录 ─────────────────────────────────

def test_planb_relaxed_variant_drops_pacing():
    """节奏变体：过满日末尾站点被移到次日 → 该站 drop 记录 pacing_conflict。"""
    from app.services.plan_b import generate_plan_b_variant

    days = [
        {"day_number": 1, "stops": [_cand(f"S{i}", lat=30.25, lng=120.17, typ="attraction") for i in range(6)]},
        {"day_number": 2, "stops": [_cand("T0", lat=30.25, lng=120.17)]},
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    drops = v.get("drops") or []
    assert drops, "节奏变体应携带被移动站点的 drop 记录"
    assert all(d["reason_code"] == "pacing_conflict" for d in drops)
    assert all(d["reason_i18n_key"] == "dropReason.pacingConflict" for d in drops)


def test_planb_curated_variant_drops_pacing():
    """取舍变体：被移除的站点 → drop 记录 pacing_conflict。"""
    from app.services.plan_b import generate_plan_b_variant

    days = [
        {"day_number": 1, "stops": [
            _cand("景点1", lat=30.25, lng=120.17, typ="attraction", cost=100),
            _cand("餐厅1", lat=30.25, lng=120.17, typ="food", cost=100),
            _cand("餐厅2", lat=30.25, lng=120.17, typ="food", cost=100),
        ]},
        {"day_number": 2, "stops": [_cand("景点2", lat=30.25, lng=120.17, typ="attraction", cost=100)]},
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    drops = v.get("drops") or []
    assert drops, "取舍变体应携带被移除站点的 drop 记录"
    assert all(d["reason_code"] == "pacing_conflict" for d in drops)


def test_planb_budget_variant_no_stop_drops():
    """预算档变体只调酒店价、不移除站点 → drops 为空/缺失（不编造）。"""
    from app.services.plan_b import generate_plan_b_variant

    days = [
        {"day_number": 1, "stops": [
            _cand("经济酒店", lat=30.25, lng=120.17, typ="hotel", cost=500),
            _cand("景点1", lat=30.25, lng=120.17, typ="attraction", cost=100),
        ]},
    ]
    v = generate_plan_b_variant(days)
    assert v is not None
    assert not (v.get("drops") or [])


# ── ③ hotel 候选 drop_reasons 对照 ─────────────────────────

def test_attach_hotel_drop_reasons():
    """5 候选 1 入选 → 入选项 drop_reasons 含其余 4 家淘汰理由（budget/distance/category 分类正确）。"""
    from app.services.drop_reason_service import attach_hotel_drop_reasons

    hotels = [
        {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.17, "estimated_cost": 500},
        {"name": "奢华国际饭店", "type": "hotel", "lat": 30.25, "lng": 120.17, "estimated_cost": 3000},  # 超预算
        {"name": "豪华威斯汀", "type": "hotel", "lat": 30.26, "lng": 120.18, "estimated_cost": 2500},  # 超预算
        {"name": "远郊度假村", "type": "hotel", "lat": 39.90, "lng": 116.40, "estimated_cost": 400},  # 距离远
        {"name": "五星皇宫酒店", "type": "hotel", "lat": 30.24, "lng": 120.16, "estimated_cost": 600},  # 与「经济」需求类目不符
    ]
    days = [{"day_number": 1, "stops": [{"name": "西湖大酒店", "type": "hotel"}]}]
    ctx = {"budget": 3000, "days": 3, "travelers": 1, "accommodation_hints": ["经济"]}

    out = attach_hotel_drop_reasons(hotels, days, ctx)
    chosen = next(h for h in out if h["name"] == "西湖大酒店")
    drops = chosen.get("drop_reasons") or []
    assert len(drops) == 4, f"应含 4 家淘汰理由，实际 {len(drops)}: {drops}"
    codes = {d["name"]: d["reason_code"] for d in drops}
    assert codes["奢华国际饭店"] == "budget_over"
    assert codes["豪华威斯汀"] == "budget_over"
    assert codes["远郊度假村"] == "distance_too_far"
    assert codes["五星皇宫酒店"] == "category_mismatch"
    assert all(d["basis"] == "rule_based" for d in drops)


def test_attach_hotel_drop_reasons_no_chosen_silent():
    """无已选酒店（无 hotel 站）→ 不附加 drop_reasons（诚实沉默）。"""
    from app.services.drop_reason_service import attach_hotel_drop_reasons

    hotels = [{"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.17, "estimated_cost": 500}]
    days = [{"day_number": 1, "stops": [{"name": "西湖", "type": "attraction"}]}]
    out = attach_hotel_drop_reasons(hotels, days, {})
    assert out[0].get("drop_reasons", []) == []
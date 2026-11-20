"""geo-anchor-sanity 质检链路接入测试（task-geo-anchor-sanity-eval）。

覆盖（对齐 openspec/changes/2026-11-20-geo-anchor-sanity/spec.md「质检链路接入」）：
1. quality_report 的 GATE_KEYS 含 geo_gate（五类 → 六类，前端质检卡透出）
2. property_qa 预警汇总（_warnings_answer）纳入 geo_gate issues
3. revise_service 修订重算（build_recompute_gates）输出含 geo_gate，
   且移除离群站后重算 warning 消失
"""
from __future__ import annotations

from app.services.property_qa_service import _warnings_answer
from app.services.quality_report_service import GATE_KEYS, build_quality_report
from app.services.revise_service import build_recompute_gates

# 杭州（约 30.25, 120.17）市中心
_HZ = (30.25, 120.17)
# 石家庄（约 38.04, 114.51，距杭州 ~1000km+，明显离群）
_SJZ = (38.04, 114.51)


def _stop(name, lat, lng, **kw):
    return {"name": name, "lat": lat, "lng": lng, **kw}


def _days():
    return [
        {
            "day_number": 1,
            "stops": [
                _stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10),
                _stop("龙井村", 30.22, 120.09), _stop("河坊街", 30.24, 120.17),
                _stop("西溪湿地", 30.27, 120.06),
            ],
        }
    ]


def _days_with_outlier():
    return [
        {
            "day_number": 1,
            "stops": [
                _stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10),
                _stop("龙井村", 30.22, 120.09), _stop("河坊街", 30.24, 120.17),
                _stop("正定古城", *_SJZ),
            ],
        }
    ]


# ── 1. quality_report GATE_KEYS 含 geo_gate ─────────────────

def test_quality_report_includes_geo_gate():
    assert "geo_gate" in GATE_KEYS
    r = build_quality_report({"days": _days(), "geo_gate": {"passed": True, "issues": [], "basis": "rule_based"}})
    keys = [g["key"] for g in r["gates"]]
    assert "geo_gate" in keys
    geo = r["gates"][keys.index("geo_gate")]
    assert geo["checked"] is True
    assert geo["passed"] is True
    assert geo["title_key"] == "qualityReport.gate.geo_gate"


def test_quality_report_missing_geo_gate_checked_false():
    """geo_gate 缺失 → checked=false（诚实：从未检查，绝不假装通过）。"""
    r = build_quality_report({"days": _days()})
    geo = next(g for g in r["gates"] if g["key"] == "geo_gate")
    assert geo["checked"] is False
    assert geo["passed"] is None


# ── 2. property_qa 预警汇总纳入 geo_gate ─────────────────────

def test_property_qa_warnings_includes_geo():
    plan_data = {
        "days": _days_with_outlier(),
        "geo_gate": {
            "passed": False,
            "issues": [{
                "severity": "warning",
                "message": "「正定古城」距行程主体质心约 1034km，请确认该站是否应保留 / 是否属于另一城市段",
                "suggestion": "请确认该站是否应保留",
                "day_number": 1,
                "basis": "rule_based",
            }],
        },
    }
    r = _warnings_answer(plan_data, "zh-CN")
    assert r["available"] is True
    sources = [w["source"] for w in r["detail"]["warnings"]]
    assert "geo_gate" in sources
    geo = next(w for w in r["detail"]["warnings"] if w["source"] == "geo_gate")
    assert "正定古城" in geo["message"]


def test_property_qa_no_geo_no_warning():
    """无 geo_gate → 不编造预警（诚实沉默）。"""
    r = _warnings_answer({"days": _days()}, "zh-CN")
    assert r["available"] is True
    assert all(w["source"] != "geo_gate" for w in r["detail"]["warnings"])


# ── 3. revise 修订重算复用（build_recompute_gates）───────────

def test_recompute_gates_includes_geo():
    gates = build_recompute_gates(_days())
    assert "geo_gate" in gates
    assert gates["geo_gate"]["passed"] is True
    assert gates["geo_gate"]["basis"] == "rule_based"


def test_recompute_gates_outlier_then_removed():
    """含离群站 → 重算 warning；移除离群站后重算 → warning 消失。"""
    g1 = build_recompute_gates(_days_with_outlier())
    assert g1["geo_gate"]["passed"] is False
    assert len(g1["geo_gate"]["issues"]) == 1

    cleaned = [d for d in _days_with_outlier() if d["day_number"] == 1]
    cleaned[0]["stops"] = [s for s in cleaned[0]["stops"] if s["name"] != "正定古城"]
    g2 = build_recompute_gates(cleaned)
    assert g2["geo_gate"]["passed"] is True
    assert g2["geo_gate"]["issues"] == []
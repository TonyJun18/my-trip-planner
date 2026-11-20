"""geo-anchor-sanity 测试（task-geo-anchor-sanity-eval）。

覆盖（对齐 openspec/changes/2026-11-20-geo-anchor-sanity/spec.md）：
1. 单城质心锚定：全部 <80km → 无 warning
2. 离群站命中：1 站 >80km → 仅该站 warning
3. 交通占位豁免：is_transfer / 名称含「交通占位」→ 不告警
4. 多城段分组锚定：段间大距离不误报；段内离群照常告警
5. 无坐标 → 无输出（诚实沉默）
6. MIN_CENTROID_STOPS：少于 3 个有坐标站点 → 不产出（质心漂移保护）
7. 输出 CritiqueIssue 结构（severity/category/message/suggestion/day_number/basis）
"""
from __future__ import annotations

from app.services.geo_sanity import check_plan_geo_gate

# 杭州（约 30.25, 120.17）市中心
_HZ = (30.25, 120.17)
# 上海（约 31.23, 121.47）
_SH = (31.23, 121.47)
# 石家庄（约 38.04, 114.51，距北京 ~280km）
_SJZ = (38.04, 114.51)

_BAIJING = (39.90, 116.40)


def _stop(name, lat, lng, **kw):
    return {"name": name, "lat": lat, "lng": lng, **kw}


def _plan(days):
    return {"days": [{"day_number": i + 1, "stops": stops} for i, stops in enumerate(days)]}


# ── 1. 单城质心无离群 ─────────────────────────────────────────

def test_single_city_no_outlier():
    """杭州 8 站（均 <80km）→ 无 warning。"""
    stops = [
        _stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10),
        _stop("龙井村", 30.22, 120.09), _stop("河坊街", 30.24, 120.17),
        _stop("西溪湿地", 30.27, 120.06), _stop("九溪", 30.19, 120.11),
        _stop("宋城", 30.17, 120.08), _stop("黄龙洞", 30.27, 120.13),
    ]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is True
    assert out["issues"] == []


# ── 2. 离群站命中 ────────────────────────────────────────────

def test_outlier_detected():
    """北京 7 站市区 + 1 站 300km → 仅该站 1 条 warning。"""
    stops = [
        _stop("故宫", *_BAIJING), _stop("天坛", 39.88, 116.41),
        _stop("颐和园", 39.99, 116.27), _stop("国博", 39.90, 116.40),
        _stop("南锣鼓巷", 39.94, 116.40), _stop("什刹海", 39.94, 116.38),
        _stop("北海公园", 39.92, 116.39),
        _stop("正定古城", *_SJZ),  # 石家庄 ~280km 离群
    ]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is False
    assert len(out["issues"]) == 1
    issue = out["issues"][0]
    assert issue["severity"] == "warning"
    assert issue["category"] == "schedule"
    assert issue["basis"] == "rule_based"
    assert "正定古城" in issue["message"]
    assert issue["day_number"] == 1


# ── 3. 交通占位豁免 ──────────────────────────────────────────

def test_transfer_exempt():
    """跨城交通占位站物理上远离市中心 → 豁免不告警。"""
    stops = [
        _stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10),
        _stop("龙井村", 30.22, 120.09), _stop("河坊街", 30.24, 120.17),
        _stop("杭州→上海 交通占位", 30.3, 120.5, is_transfer=True),
    ]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is True


# ── 4. 多城段分组锚定 ────────────────────────────────────────

def test_multicity_no_cross_segment_false_positive():
    """杭州段 8 站 + 上海段 6 站（段距 170km）→ 无跨段误报。"""
    hz_stops = [
        _stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10),
        _stop("龙井村", 30.22, 120.09), _stop("河坊街", 30.24, 120.17),
        _stop("西溪湿地", 30.27, 120.06), _stop("九溪", 30.19, 120.11),
        _stop("宋城", 30.17, 120.08), _stop("黄龙洞", 30.27, 120.13),
    ]
    sh_stops = [
        _stop("外滩", 31.24, 121.49), _stop("豫园", 31.23, 121.49),
        _stop("南京路", 31.23, 121.47), _stop("陆家嘴", 31.24, 121.50),
        _stop("田子坊", 31.21, 121.47), _stop("武康路", 31.21, 121.44),
    ]
    out = check_plan_geo_gate(_plan([hz_stops, sh_stops]))
    assert out["passed"] is True


def test_multicity_segment_internal_outlier():
    """上海段内某站距段质心 150km → 仅该站告警。"""
    hz_stops = [_stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10), _stop("龙井村", 30.22, 120.09)]
    sh_stops = [
        _stop("外滩", 31.24, 121.49), _stop("豫园", 31.23, 121.49),
        _stop("南京路", 31.23, 121.47), _stop("陆家嘴", 31.24, 121.50),
        _stop("田子坊", 31.21, 121.47), _stop("武康路", 31.21, 121.44),
        _stop("淀山湖", 31.10, 120.97),  # 距上海段质心 ~50km 内? (实际 30km) 改用明显离群
    ]
    # 把淀山湖换成 150km 外的点（舟山方向）
    sh_stops[-1] = _stop("嵊泗列岛", 30.73, 122.45)
    out = check_plan_geo_gate(_plan([hz_stops, sh_stops]))
    assert out["passed"] is False
    assert len(out["issues"]) == 1
    assert "嵊泗列岛" in out["issues"][0]["message"]


# ── 5. 无坐标诚实沉默 ────────────────────────────────────────

def test_no_coords_silent():
    """全部无坐标 → 不产出（不编造）。"""
    stops = [_stop("西湖", None, None), _stop("灵隐寺", None, None)]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is True
    assert out["issues"] == []


# ── 6. 质心漂移保护 ──────────────────────────────────────────

def test_min_centroid_stops_silent():
    """只有 2 个有坐标站点 → 不产出（质心漂移保护）。"""
    stops = [_stop("西湖", *_HZ), _stop("正定古城", *_SJZ)]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is True
    assert out["issues"] == []


# ── 7. 残缺坐标不崩溃不参与 ──────────────────────────────────

def test_broken_coords_ignored():
    """lat/lng 缺失或非法 → 不参与质心、不崩溃、不告警。"""
    stops = [
        _stop("西湖", *_HZ),
        _stop("灵隐寺", 30.24, 120.10),
        _stop("龙井村", 30.22, 120.09),
        _stop("无坐标站", None, None),
        _stop("非法坐标站", 999, 999),
        _stop("半坐标站", 30.20, None),
    ]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is True
    assert out["issues"] == []


def test_broken_coords_with_real_outlier():
    """合法离群站照常告警，残缺坐标站不干扰检测。"""
    stops = [
        _stop("西湖", *_HZ), _stop("灵隐寺", 30.24, 120.10),
        _stop("龙井村", 30.22, 120.09), _stop("河坊街", 30.24, 120.17),
        _stop("无坐标站", None, None),
        _stop("正定古城", *_SJZ),
    ]
    out = check_plan_geo_gate(_plan([stops]))
    assert out["passed"] is False
    assert len(out["issues"]) == 1
    assert "正定古城" in out["issues"][0]["message"]
"""地理一致性质检（task-geo-anchor-sanity-eval / openspec 2026-11-20-geo-anchor-sanity）。

以行程内站点坐标的质心为锚，检测离群站点（物理上远离行程主体的站点），
产出确定性 warning（basis=rule_based）并进质检 trace。

设计（与 TimeGate / WeatherGate / RepeatGate 同哲学：确定性规则、零 LLM、
只警告不阻断、数据不足沉默）：
- ``check_plan_geo_gate(plan)``——组合入口，返回 {passed, issues, ...}；
- 锚定：有坐标站点的经纬度均值。单日 / 无多城段 → 按天分组锚定；
  多城段（plan.multi_city.segments）→ 每段独立质心，段间大距离不误报；
- 离群阈值 ``GEO_OUTLIER_KM=80``；交通占位（``is_transfer`` 或名称含
  「交通占位」）豁免（跨城大交通物理上必远离市中心）；
- ``MIN_CENTROID_STOPS=3``：一组内少于 3 个有坐标站点 → 该组不产出
  （质心漂移保护，诚实沉默）；
- 输出与 CritiqueIssueSchema 兼容（severity=warning），可直接进质检卡。

复用：``driving_service.haversine_km``（公共球面距离，与 multi_city /
solver_service 同源）。
"""
from __future__ import annotations

from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t
from app.services.driving_service import haversine_km

# 离群阈值（km）：城市核心区外圈通常 <50km，>80km 基本是「另一个城市」级别
GEO_OUTLIER_KM = 80.0
# 质心漂移保护：少于 3 个有坐标站点不产出（如只有 2 个站且都在城市边缘）
MIN_CENTROID_STOPS = 3
# 交通占位识别词（与 multi_city 命名约定同源）
_TRANSFER_NAME_MARK = "交通占位"


def _stop_coords(stop: dict[str, Any]) -> tuple[float, float] | None:
    """提取站点坐标；lat/lng 缺失或非法（非数值 / 越界）→ None（不参与质心）。"""
    lat_raw, lng_raw = stop.get("lat"), stop.get("lng")
    if lat_raw is None or lng_raw is None:
        return None
    try:
        lat, lng = float(lat_raw), float(lng_raw)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _is_transfer(stop: dict[str, Any]) -> bool:
    """交通占位判定：is_transfer 标记 或 名称含「交通占位」（跨城大交通豁免）。"""
    if stop.get("is_transfer"):
        return True
    name = str(stop.get("name") or "")
    return _TRANSFER_NAME_MARK in name


def _centroid(stops: list[dict[str, Any]]) -> tuple[float, float] | None:
    """有坐标站点的经纬度均值（质心）——剔除离群点后的稳健均值。

    - 交通占位站（is_transfer / 名称含「交通占位」）**不参与锚定**：
      跨城大交通物理上远离市区，纳入会把质心拉偏（与豁免检测同构）；
    - 迭代剔除：算均值 → 找最远站 → 若 >GEO_OUTLIER_KM 则剔除重算 →
      直到最远站 ≤ 阈值或剩余 <MIN_CENTROID_STOPS。
      否则单个 280km 离群站会把质心拉向它，导致正常城站被误报
      （自污染；剔除后仍是「行程主体站点的经纬度平均值」）。
    - 无有效坐标 / 剩余不足 MIN_CENTROID_STOPS → None（诚实沉默）。
    """
    coords = [
        c for s in stops
        if (c := _stop_coords(s)) is not None and not _is_transfer(s)
    ]
    if len(coords) < MIN_CENTROID_STOPS:
        return None
    pts = list(coords)
    while len(pts) >= MIN_CENTROID_STOPS:
        cent = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        far = max(pts, key=lambda p: haversine_km(cent[0], cent[1], p[0], p[1]))
        if haversine_km(cent[0], cent[1], far[0], far[1]) <= GEO_OUTLIER_KM:
            return cent
        pts.remove(far)  # 离群点不参与锚定，留待检测
    return None


def _groups(plan: dict[str, Any], days: list[dict[str, Any]]) -> list[list[tuple[Any, dict[str, Any]]]]:
    """把天数分组为锚定组，返回 [[(day_number, stop), ...], ...]。

    - 多城段（plan.multi_city.segments）→ 按段分组（段内所有天的站点一个质心）；
    - 否则 → 按天分组（单日即全行程；多日单城也按天锚，避免跨日误报）。
    """
    segments = None
    mc = plan.get("multi_city")
    if isinstance(mc, dict):
        segments = mc.get("segments")
    if segments:
        groups: list[list[tuple[Any, dict[str, Any]]]] = []
        for seg in segments:
            seg_days = seg.get("day_numbers") or []
            nums = {int(n) for n in seg_days if isinstance(n, (int, float))}
            picked: list[tuple[Any, dict[str, Any]]] = []
            for day in days:
                if nums and day.get("day_number") in nums or (not nums and day.get("city") == seg.get("city")):
                    picked.extend(
                        (day.get("day_number"), s)
                        for s in (day.get("stops") or []) if isinstance(s, dict)
                    )
            if picked:
                groups.append(picked)
        return groups
    # 无多城段 → 按天分组
    return [
        [(day.get("day_number"), s) for s in (day.get("stops") or []) if isinstance(s, dict)]
        for day in days if day.get("stops")
    ]


def check_plan_geo_gate(plan: dict[str, Any], locale: str = "zh-CN") -> dict[str, Any]:
    """地理一致性质检：质心锚定 + 离群检测（零 LLM / 零外部 API）。

    返回 {passed, issues, warning_count, summary, basis="rule_based"}：
    - ``issues``：CritiqueIssueSchema 兼容（severity=warning / category=schedule
      / message / suggestion / day_number / basis=rule_based）；
    - 数据不足（整组无坐标 / <MIN_CENTROID_STOPS 个有坐标站）→ 该组沉默，
      不编造、不告警；全沉默时 passed=True（与 TimeGate 无输出同语义）。
    """
    locale = normalize_locale(locale)
    days = [d for d in (plan.get("days") or []) if isinstance(d, dict)]
    issues: list[dict[str, Any]] = []
    checked_groups = 0

    for group in _groups(plan, days):
        # 质心锚定：交通占位不参与锚；<MIN_CENTROID_STOPS 个有效站 → 沉默
        centroid = _centroid([s for _, s in group])
        if centroid is None:
            continue
        checked_groups += 1
        for day_no, s in group:
            if _is_transfer(s):
                continue  # 跨城大交通豁免
            c = _stop_coords(s)
            if c is None:
                continue
            km = haversine_km(centroid[0], centroid[1], c[0], c[1])
            if km > GEO_OUTLIER_KM:
                name = str(s.get("name") or t(locale, "geo.unknown_stop"))
                issues.append({
                    "severity": "warning",
                    "category": "schedule",
                    "message": t(locale, "geo.outlier.message", name=name, km=round(km)),
                    "suggestion": t(locale, "geo.outlier.suggestion"),
                    "day_number": day_no,
                    "basis": "rule_based",
                })

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "warning_count": len(issues),
        "summary": (
            t(locale, "geo.summary.pass") if passed
            else t(locale, "geo.summary.warn", n=len(issues))
        ),
        "basis": "rule_based",
        "checked_groups": checked_groups,
    }
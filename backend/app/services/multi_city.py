"""多城市/多目的地衔接（task-multi-city-segments）。

背景：Trip Planner AI 的 multi-city 优化是最强项（多城市路线/按地点聚合/交通衔接实在），
Mindtrip / Google Canvas 也在做；我们此前单行程单城市，城市间大交通只入预算、
未结构化进排程。

设计（与 TimeGate/DrivingGate 同哲学：确定性规则、零 LLM、只警告不阻断）：
- ``apply_multi_city(plan, cities)``：按天数把行程均分到有序城市段（segment），
  给每天打上 ``city`` 归属；
- 段间衔接：每个新城市段的首日插入「交通占位」站点（规则估算耗时：上一段末站
  坐标 → 本段首站坐标的球面距离 / 平均车速，复用 driving_service 常量），
  让「什么时候在赶路」进入排程而不是隐形；
- 衔接校验：到港时刻（占位起点 + 车程）与首站 visit_start 冲突（缓冲不足）→
  warning，提示留缓冲或改班次；无坐标/无 visit_start 时保持沉默（不编造）；
- 输出与 CritiqueIssueSchema 兼容（severity=warning），可直接进质检卡。

边界：
- 单城市（cities 长度 ≤1）→ 不做任何改动，返回 passed=True；
- 城市数 > 天数 → 只分配有天的城市段（不强行插空日）；
- 占位站点 ``stop_type="attraction"``（落库 schema 只有三类），名称带
  「（交通占位）」后缀便于前端识别，``description`` 说明估算依据（诚实标注）。
"""
from __future__ import annotations

from typing import Any

from app.i18n import normalize_locale
from app.i18n.translations import t
from app.services.driving_service import estimate_drive_minutes, haversine_km

MAX_CITIES = 5
# 段间衔接缓冲（分钟）：到港后至少留这么多时间再开始首站（放行李/接驳/找路）
TRANSFER_BUFFER_MINUTES = 30
# 无坐标时的兜底车程（分钟）：城市间大交通按 3 小时估算（诚实标注 estimate）
FALLBACK_TRANSFER_MINUTES = 180


def _stop_coords(stop: dict[str, Any]) -> tuple[float, float] | None:
    lat, lng = stop.get("lat"), stop.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)
    return None


def _first_coords(day: dict[str, Any]) -> tuple[float, float] | None:
    for s in day.get("stops") or []:
        if isinstance(s, dict):
            c = _stop_coords(s)
            if c is not None:
                return c
    return None


def _last_coords(day: dict[str, Any]) -> tuple[float, float] | None:
    coords = [_stop_coords(s) for s in (day.get("stops") or []) if isinstance(s, dict)]
    coords = [c for c in coords if c is not None]
    return coords[-1] if coords else None


def _segment_days(days: list[dict[str, Any]], cities: list[str]) -> list[dict[str, Any]]:
    """按天数均分到有序城市段（前置城市多分一天）。

    返回 ``[{"city": str, "days": [day, ...]}]``；城市数 > 天数时后面的城市不分配。
    """
    n, m = len(days), len(cities)
    if n == 0 or m == 0:
        return []
    base, extra = divmod(n, m)
    segments: list[dict[str, Any]] = []
    idx = 0
    for i, city in enumerate(cities):
        cnt = base + (1 if i < extra else 0)
        if cnt <= 0:
            continue
        segments.append({"city": city, "days": days[idx: idx + cnt]})
        idx += cnt
    return segments


def _transfer_minutes(prev_day: dict[str, Any] | None, next_day: dict[str, Any]) -> tuple[int, float | None]:
    """规则估算段间车程（分钟）与距离（km）：坐标可得则球面距离/均速，否则兜底。"""
    if prev_day is None:
        return FALLBACK_TRANSFER_MINUTES, None
    a, b = _last_coords(prev_day), _first_coords(next_day)
    if a is None or b is None:
        return FALLBACK_TRANSFER_MINUTES, None
    km = haversine_km(a[0], a[1], b[0], b[1])
    return max(estimate_drive_minutes(km), 30), round(km, 1)


def _day_start_minutes(day: dict[str, Any]) -> int:
    """一天的排程起点（分钟）：首个带 visit_start 的站点，否则 09:00。"""
    from app.services.time_validation import _parse_clock, DAY_START  # 复用解析口径

    for s in day.get("stops") or []:
        if isinstance(s, dict):
            c = _parse_clock(s.get("visit_start"))
            if c is not None:
                return c[0] * 60 + c[1]
    return DAY_START[0] * 60 + DAY_START[1]


def apply_multi_city(plan: dict[str, Any], cities: list[str], locale: str = "zh-CN") -> dict[str, Any]:
    """多城市分段 + 段间交通占位 + 衔接校验（原地修改 plan，返回报告）。

    返回：
    {
      "enabled": bool,          # 是否启用（cities ≥2 且有多天）
      "segments": [{"city","day_numbers":[...]}],
      "issues": [...],          # CritiqueIssueSchema 兼容（warning）
      "passed": bool,
      "warning_count": int,
      "summary": str,
    }
    """
    locale = normalize_locale(locale)
    days = [d for d in (plan.get("days") or []) if isinstance(d, dict)]
    cities = [c.strip() for c in (cities or []) if isinstance(c, str) and c.strip()][:MAX_CITIES]
    if len(cities) < 2 or len(days) < 2:
        return {
            "enabled": False, "segments": [], "issues": [],
            "passed": True, "warning_count": 0,
            "summary": t(locale, "multicity.summary.single"),
        }

    segments = _segment_days(days, cities)
    issues: list[dict[str, Any]] = []
    prev_day: dict[str, Any] | None = None

    for seg_idx, seg in enumerate(segments):
        for day in seg["days"]:
            day["city"] = seg["city"]  # 城市归属（落库/前端可直接用）
        if seg_idx > 0 and seg["days"]:
            first_day = seg["days"][0]
            minutes, km = _transfer_minutes(prev_day, first_day)
            transfer = {
                "name": t(locale, "multicity.transfer.name", city=seg["city"]),
                # 双键兼容：PlanSchema 用 type/duration_minutes（落库），
                # TimeGate/修订内核读 stop_type/estimated_duration_minutes
                "type": "attraction",
                "stop_type": "attraction",
                "duration_minutes": minutes,
                "estimated_duration_minutes": minutes,
                "description": t(
                    locale,
                    "multicity.transfer.desc.hint" if km is None else "multicity.transfer.desc.km",
                    minutes=minutes, km=km or 0,
                ),
                "visit_start": "09:00",
                "is_transfer": True,
            }
            first_day.setdefault("stops", [])
            first_day["stops"] = [transfer, *list(first_day["stops"])]

            # 衔接校验：到港时刻 vs 首站开始（有 visit_start 才校验，沉默优先）
            arrival = _day_start_minutes(first_day) + minutes
            real = next(
                (s for s in first_day["stops"][1:]
                 if isinstance(s, dict) and s.get("visit_start")),
                None,
            )
            if real is not None:
                from app.services.time_validation import _parse_clock

                c = _parse_clock(real.get("visit_start"))
                if c is not None:
                    start = c[0] * 60 + c[1]
                    if start < arrival + TRANSFER_BUFFER_MINUTES:
                        issues.append({
                            "severity": "warning",
                            "category": "logistics",
                            "message": t(
                                locale, "multicity.msg.tight",
                                city=seg["city"],
                                arrive=f"{arrival // 60:02d}:{arrival % 60:02d}",
                                start=real.get("visit_start"),
                                buffer=TRANSFER_BUFFER_MINUTES,
                            ),
                            "suggestion": t(locale, "multicity.suggest.tight",
                                             name=real.get("name") or ""),
                            "day_number": first_day.get("day_number"),
                            "basis": "rule_based",
                        })
        prev_day = seg["days"][-1]

    return {
        "enabled": True,
        "segments": [
            {"city": s["city"],
             "day_numbers": [d.get("day_number") for d in s["days"]]}
            for s in segments
        ],
        "issues": issues,
        "passed": not issues,
        "warning_count": len(issues),
        "summary": (
            t(locale, "multicity.summary.pass", n=len(segments))
            if not issues else t(locale, "multicity.summary.warn", n=len(issues))
        ),
    }
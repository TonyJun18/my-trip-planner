"""行程时间轴排程（读取路径派生时刻）：确定性纯函数，零 LLM 零网络。

背景（docs/superpowers/specs/2026-11-11-trip-detail-schedule-timeline-design.md）：
- 详情页日程卡此前只有「N 站 · ¥587 · 17h30m」聚合数字，用户看不到每站几点出发、
  几点到达，一天 17.5 小时的过载毫无视觉感知；竞品（Wanderlog / Mindtrip / Stippl）
  均为时间轴标配。
- TimeGate（time_validation）已有 cursor 推时刻的确定性能力，但只产出 warning 文字；
  本模块把同款游标推进抽成「输出每站起止时刻」的排程器，读取路径注入响应
  （与 budget_service.compute_budget 的读取路径重算范式同构），时刻是派生值、
  不落库——任意写操作后再次读取自动正确，不存在脏数据。

口径（与 TimeGate 同源、诚实标注 basis=rule）：
- 起点常量单一出处：``DAY_START`` import 自 time_validation；
- 游玩时段：逐站 ``start → start + estimated_duration_minutes``；
- 段间交通：相邻站点均有坐标时 haversine + 均速估算（driving_service），
  缺坐标跳过不编造（与 servicing「缺坐标跳过」一致）；
- 住宿站：停留时长是过夜语义（如 720 分钟），不占时段队列，
  记「到店时刻」瞬时段（渲染「入住 HH:MM」）；其后站点从到店时刻继续；
- 交通占位站（多城市）：``details.is_transfer`` 优先，存量行程按名称
  「（交通占位）」后缀兜底（命名稳定出处见 multi_city）；
- 跨夜钳制与过载：end > 24:00 钳到 24:00 且 overflow；全天跨度 > 720 分钟（12h）
  亦 overflow——与 TimeGate 过饱和告警（>480min 游玩）口径互补不重复。
"""
from __future__ import annotations

from typing import Any

from app.services.driving_service import estimate_drive_minutes, haversine_km
from app.services.time_validation import DAY_START

# 全天时间窗口跨度上限（分钟）：超过即「时间超出一天」的过载信号。
MAX_DAY_SPAN_MINUTES = 720
_END_OF_DAY = ("24", "00")


def _parse_hhmm(value: str | None) -> tuple[int, int] | None:
    """解析 "HH:MM" 为 (h, m)；非法返回 None。"""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 24 and 0 <= m < 60):
        return None
    return (h, m)


def _fmt_hhmm(total_minutes: int) -> str:
    """绝对分钟 → HH:MM；超过当日边界钳制为 24:00。"""
    if total_minutes >= 24 * 60:
        return ":".join(_END_OF_DAY)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _stop_duration(stop: dict[str, Any]) -> int:
    """游玩时长（分钟）；缺省 0（不编造游玩时间，start==end 瞬时点）。"""
    v = stop.get("estimated_duration_minutes")
    if isinstance(v, (int, float)) and v > 0:
        return int(v)
    return 0


def _is_hotel(stop: dict[str, Any]) -> bool:
    return stop.get("stop_type") == "hotel"


def _is_transfer(stop: dict[str, Any]) -> bool:
    """交通占位识别：details.is_transfer 显式标记优先，存量按名称后缀兜底。"""
    details = stop.get("details")
    if isinstance(details, dict) and details.get("is_transfer"):
        return True
    name = stop.get("name") or ""
    return "（交通占位）" in name


def _coords(stop: dict[str, Any]) -> tuple[float, float] | None:
    lat, lng = stop.get("lat"), stop.get("lng")
    if lat is None or lng is None:
        return None
    return (float(lat), float(lng))


def _gap_minutes(prev: dict[str, Any], cur: dict[str, Any]) -> int | None:
    """相邻站点段间交通估算（分钟）；任一侧缺坐标 → None（不编造）。"""
    a, b = _coords(prev), _coords(cur)
    if a is None or b is None:
        return None
    return estimate_drive_minutes(haversine_km(a[0], a[1], b[0], b[1]))


def schedule_day(
    stops: list[dict[str, Any]],
    *,
    start: tuple[int, int] = DAY_START,
) -> dict[str, Any]:
    """确定性排程一日站点。

    Args:
        stops: 该日站点（按 order_index 序）的字典列表，支持字段：
            id / name / stop_type / lat / lng / estimated_duration_minutes /
            details{is_transfer} / visit_start（显式锚点，可选）。
        start: 默认日起点（单一出处 time_validation.DAY_START），
            首站显式 visit_start 优先。

    Returns:
        {"items": [{stop_id, start, end, travel_to_next_minutes, is_transfer}],
         "window": {start, end, span_minutes, overflow}}
        start/end 为 "HH:MM"（跨夜钳制为 "24:00"）；住宿站 start==end==到店时刻。
    """
    items: list[dict[str, Any]] = []
    overflow = False
    window_start: str | None = None
    window_end: str | None = None

    # 起点锚点：首站显式 visit_start 优先于默认起点。
    cursor = start[0] * 60 + start[1]
    first_anchor = _parse_hhmm(stops[0].get("visit_start")) if stops else None
    if first_anchor is not None:
        cursor = first_anchor[0] * 60 + first_anchor[1]

    for idx, stop in enumerate(stops):
        stop_id = stop.get("id")
        # 段间交通：上一站 → 本站（前置计算，与顺序一致）
        if idx > 0 and items:
            gap = _gap_minutes(stops[idx - 1], stop)
            items[idx - 1]["travel_to_next_minutes"] = gap
            if gap is not None:
                cursor += gap

        # 站点内显式锚点（如占位站 plan 里的 09:00 / 未来手动锁时刻）：
        # 晚于当前游标才快进（时间单向，不回拨）。
        anchor = _parse_hhmm(stop.get("visit_start"))
        if anchor is not None:
            anchor_min = anchor[0] * 60 + anchor[1]
            if anchor_min > cursor:
                cursor = anchor_min

        start_str = _fmt_hhmm(cursor)
        if _is_hotel(stop):
            # 住宿站：停留下时长是过夜语义，记「到店时刻」瞬时段。
            end_str = start_str
        else:
            cursor += _stop_duration(stop)
            end_str = _fmt_hhmm(cursor)
            if cursor >= 24 * 60:
                overflow = True
        items.append({
            "stop_id": stop_id,
            "start": start_str,
            "end": end_str,
            "travel_to_next_minutes": None,
            "is_transfer": _is_transfer(stop),
        })
        if window_start is None:
            window_start = start_str
        window_end = end_str

    # 全天跨度过载：>12h（不含跨夜钳制引起的 24:00 情形——那已置 overflow）。
    if window_start is not None and window_end is not None:
        ws = _parse_hhmm(window_start)
        we = _parse_hhmm(window_end)
        if ws is not None and we is not None:
            span = (we[0] * 60 + we[1]) - (ws[0] * 60 + ws[1])
            if span >= MAX_DAY_SPAN_MINUTES or cursor > 24 * 60:
                overflow = True

    return {
        "items": items,
        "window": {
            "start": window_start,
            "end": window_end,
            "span_minutes": None if window_start is None else _span_minutes(window_start, window_end),
            "overflow": overflow,
        },
    }


def _span_minutes(start: str, end: str) -> int:
    def to_min(v: str) -> int:
        p = _parse_hhmm(v)
        return (p[0] * 60 + p[1]) if p else 0

    return max(0, to_min(end) - to_min(start))


# ══ 读取路径注入（响应层派生，非存储）══════════════════════════════

def _stop_to_dict(stop: Any) -> dict[str, Any]:
    """ORM Stop / plan 数据 dict → 排程器输入 dict（兼容两种来源）。"""
    if isinstance(stop, dict):
        return dict(stop)
    return {
        "id": stop.id,
        "name": stop.name,
        "stop_type": stop.stop_type,
        "lat": stop.lat,
        "lng": stop.lng,
        "estimated_duration_minutes": stop.estimated_duration_minutes,
        "details": stop.details,
        "visit_start": (stop.details or {}).get("visit_start"),
    }


def attach_day_schedule(day: Any) -> None:
    """把该日派生时刻回填到 StopOut 对象（in-place，读取路径专用）。

    day.stops 是 StopOut（Pydantic）；按 order_index 与排程 items 对齐回填。
    """
    stops = list(getattr(day, "stops", None) or [])
    if not stops:
        return
    ordered = sorted(stops, key=lambda s: s.order_index)
    result = schedule_day([_stop_to_dict(s) for s in ordered])
    items = result["items"]
    if len(items) != len(ordered):
        return
    for stop, item in zip(ordered, items):
        stop.visit_start = item["start"]
        stop.visit_end = item["end"]
        stop.travel_to_next_minutes = item["travel_to_next_minutes"]
        stop.is_transfer = item["is_transfer"]


def attach_trip_schedule(trip: Any) -> Any:
    """整条行程逐日注入派生时刻（TripOut，读取路径专用，in-place 返回同一对象）。"""
    for day in getattr(trip, "days", None) or []:
        attach_day_schedule(day)
    return trip

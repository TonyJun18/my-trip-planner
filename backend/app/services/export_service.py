"""行程导出（task-export-offline）：可移植 JSON 快照。

对齐「诚实预算 + 可审计」哲学：
- 导出携带预算口径标注（estimate_basis）、质检摘要（plan.quality / time_gate）、
  数据源标注，不做「看起来确定的假数据」；
- 不输出任何令牌/凭证（share_token / edit_token 一律排除）；
- 共享只读序列化：owner（JWT）与 share_token（免登录只读）两条路径复用同一构建函数，
  访问控制由调用方（API 层）保证——owner 走 trip_service.get_trip(owner=...)，
  share 走 trip_service.get_trip_by_share_token（生命周期门禁一致）。

Schema 版本约定：schema_version 语义化递增；前端仅提示「数据随版本演进」，
不做解析承诺——JSON 导出是「完整数据备份」，跨工具迁移靠人/脚本，不保证双向。
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.models import Trip


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _iso_dt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _sanitize_plan(plan_data: dict[str, Any]) -> dict[str, Any]:
    """裁剪 plan 快照为可导出元信息。

    - 去掉 days：权威数据在 trip.days（避免双份不一致）；
    - 其余键全部保留（budget/transport/discount_rules/quality/time_gate/
      driving/warnings/hotels/transit/checkin/discounts/language 等都是
      规划上下文，导出后可用于离线审阅与迁移）。
    """
    return {k: v for k, v in plan_data.items() if k != "days"}


def _sanitize_booking(b: Any, *, full: bool) -> dict[str, Any]:
    """预订条目导出序列化（脱敏单处集中，task-booking-ledger-rhythm）。

    - full=True（owner 自备份）：全量含 credential 原值；
    - full=False（share 令牌路径）：credential 永不输出；order_no 尾 4 掩码
      （em- 合成键不是真实凭证，输出「—」）。
    """
    data: dict[str, Any] = {
        "id": b.id,
        "kind": b.kind,
        "provider": b.provider,
        "title": b.title,
        "provider_url": b.provider_url,
        "status": b.status,
        "reference": b.reference,
        "service_date": _iso(b.service_date),
        "service_note": b.service_note,
        "amount": b.amount,
        "currency": b.currency,
        "confirmed_at": _iso_dt(b.confirmed_at),
        "cancelled_at": _iso_dt(b.cancelled_at),
    }
    if full:
        data["order_no"] = b.order_no
        data["credential"] = b.credential
    else:
        order_no = b.order_no or ""
        if order_no.startswith("em-"):
            data["order_no"] = "—"
        elif order_no:
            data["order_no"] = f"****{order_no[-4:]}"
        else:
            data["order_no"] = None
    return data


def build_trip_export(
    trip: Trip, *, plan_data: dict[str, Any] | None = None,
    bookings: list[Any] | None = None, bookings_full: bool = False,
) -> dict[str, Any]:
    """构建导出行程 JSON（两条访问路径共用）。

    plan_data 为 None 或 {} 时 plan 输出 None（行程可能尚未 AI 规划；
    手工创建的行程照样可导出）。
    bookings 为行程台账条目（owner 路径 full=True 全量；share 路径 full=False 脱敏）。
    """
    from app.services import budget_service

    data = plan_data or {}
    budget_summary = budget_service.compute_budget(trip, plan_data=data or None)

    days = []
    for day in trip.days:
        days.append(
            {
                "id": day.id,
                "day_number": day.day_number,
                "date": _iso(day.date),
                "note": day.note,
                "stops": [
                    {
                        "id": stop.id,
                        "name": stop.name,
                        "stop_type": stop.stop_type,
                        "order_index": stop.order_index,
                        "lat": stop.lat,
                        "lng": stop.lng,
                        "description": stop.description,
                        "estimated_cost": stop.estimated_cost,
                        "estimated_duration_minutes": stop.estimated_duration_minutes,
                        "checked": stop.checked,
                    }
                    for stop in day.stops
                ],
            }
        )

    return {
        "schema_version": "1.0",
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "trip": {
            "id": trip.id,
            "title": trip.title,
            "destination": trip.destination,
            "departure": trip.departure,
            "trip_type": trip.trip_type,
            "start_date": _iso(trip.start_date),
            "end_date": _iso(trip.end_date),
            "travelers": trip.travelers,
            "budget": trip.budget,
            "status": trip.status,
            "created_at": _iso_dt(trip.created_at),
            "updated_at": _iso_dt(trip.updated_at),
        },
        "days": days,
        "budget_summary": budget_summary,
        "bookings": [_sanitize_booking(b, full=bookings_full) for b in (bookings or [])],
        "plan": _sanitize_plan(data) if data else None,
    }


# ── ICS 日历导出（task-ics-export） ─────────────────────────────
# 设计约束（与 JSON 导出一致）：
# - 只输出行程本身（标题/日期/站点/坐标），**绝不输出任何令牌或凭证**；
# - 没有日期就不编造：day.date 缺失时用 trip.start_date + (day_number-1) 推导，
#   两者都没有则该天跳过（宁缺勿假）；
# - 纯函数、无网络、无第三方依赖：ICS 文本由代码按 RFC 5545 拼装。
_ICS_PRODID = "-//my-trip-planner//Trip Export 1.0//ZH"
_ICS_UID_DOMAIN = "my-trip-planner.local"


def _ics_escape(value: str | None) -> str:
    """RFC 5545 TEXT 转义：反斜杠、分号、逗号、换行。"""
    if not value:
        return ""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;").replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")
    return text


def _ics_fold(line: str, limit: int = 75) -> list[str]:
    """按 RFC 5545 折行：每行 ≤75 字节，续行以一个空格开头。

    以字节为单位切分（不是字符）——中文站名很容易超过 75 字节；切分点回退到
    UTF-8 字符边界，避免把多字节字符劈成两半产生乱码。
    """
    raw = line.encode("utf-8")
    if len(raw) <= limit:
        return [line]
    chunks: list[str] = []
    budget = limit
    while len(raw) > budget:
        cut = budget
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:  # 落在多字节字符中间 → 回退
            cut -= 1
        if cut == 0:  # 极端兜底：单个超长字符，硬切
            cut = budget
        chunks.append(raw[:cut].decode("utf-8", errors="ignore"))
        raw = raw[cut:]
        budget = limit - 1  # 续行有一个前导空格占 1 字节
    chunks.append(raw.decode("utf-8", errors="ignore"))
    return [chunks[0], *(" " + c for c in chunks[1:])]


def _ics_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _ics_stamp(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _day_date(trip: Trip, day) -> date | None:
    """day 的日历日期：显式 date 优先，否则按 day_number 从 start_date 推导。"""
    if day.date is not None:
        return day.date
    if trip.start_date is not None:
        return trip.start_date + timedelta(days=max(0, (day.day_number or 1) - 1))
    return None


def _stop_description(stop, day_number: int, index: int) -> str:
    parts: list[str] = []
    if stop.description:
        parts.append(stop.description)
    if stop.estimated_cost:
        parts.append(f"预计 ¥{stop.estimated_cost:g}")
    if stop.estimated_duration_minutes:
        parts.append(f"建议停留 {stop.estimated_duration_minutes} 分钟")
    parts.append(f"第 {day_number} 天 · 第 {index + 1} 站")
    return "；".join(parts)


def build_trip_ics(trip: Trip) -> str:
    """构建行程 ICS 日历文本（owner 与 share 两条访问路径共用）。

    每个站点一个全天 VEVENT（SUMMARY=站名，LOCATION=目的地，GEO=坐标，
    DESCRIPTION=简介/预算/时长/序号）；没有站点的天退化为「Day N」整天事件。
    """
    stamp = _ics_stamp(datetime.now(UTC))
    title = trip.title or trip.destination or "Trip"
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_ICS_PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(title)}",
    ]
    if trip.destination:
        lines.append(f"X-WR-CALDESC:{_ics_escape(trip.destination)}")

    for day in sorted(trip.days, key=lambda d: (d.day_number or 0)):
        day_date = _day_date(trip, day)
        if day_date is None:
            continue  # 无日期不编造
        stops = sorted(day.stops, key=lambda s: (s.order_index or 0))
        if not stops:
            stops = [None]  # 空天：仍保留一个整天事件，避免日程断层
        for idx, stop in enumerate(stops):
            day_number = day.day_number or 1
            if stop is None:
                summary = f"Day {day_number}" + (f" · {trip.destination}" if trip.destination else "")
                description = day.note or ""
                location = trip.destination or ""
                geo = None
                uid = f"trip-{trip.id}-d{day_number}@{_ICS_UID_DOMAIN}"
            else:
                summary = stop.name or f"Day {day_number} 第 {idx + 1} 站"
                description = _stop_description(stop, day_number, idx)
                location = trip.destination or stop.name or ""
                geo = (stop.lat, stop.lng) if stop.lat is not None and stop.lng is not None else None
                uid = f"trip-{trip.id}-d{day_number}-{idx}@{_ICS_UID_DOMAIN}"

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{_ics_date(day_date)}",
                # 全天事件的 DTEND 是「次日」（RFC 5545 排他语义）
                f"DTEND;VALUE=DATE:{_ics_date(day_date + timedelta(days=1))}",
                f"SUMMARY:{_ics_escape(summary)}",
                f"LOCATION:{_ics_escape(location)}",
                f"DESCRIPTION:{_ics_escape(description)}",
            ])
            if geo is not None:
                lines.append(f"GEO:{geo[0]:.6f};{geo[1]:.6f}")
            lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    folded: list[str] = []
    for line in lines:
        folded.extend(_ics_fold(line))
    return "\r\n".join(folded) + "\r\n"
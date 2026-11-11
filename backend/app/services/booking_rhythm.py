"""预订节奏规则库（task-booking-ledger-rhythm · booking-rhythm spec · design D8/D9）。

「什么时候该订什么」的确定性计算：纯函数 + 日期数学，零 LLM、零外部数据源、
零凭证、零后台任务。与 booking_service.scan_bookable_stops（「该订什么」前瞻扫描）
互补：扫描回答目标集，节奏回答每个目标的时间窗。

四类规则（常量为 2026-11 公开口径，注释即口径声明，条目 note 均带「以官方渠道为准」）：
1. train  —— 火车预售期 15 天：window_open = service_date - 15d
   （12306 起售时刻分批放号的细节不建模，只给日期窗）；
2. ticket —— 站点名命中放票日规则表（如 故宫 -7 天 20:00）用表内提前量与时刻；
   未命中表但 timed-entry 关键词命中 → 通用档「提前 7 天关注」，不编造放票时刻；
3. flight —— 国内启发式 T-30 关注窗：只给「建议关注窗口」，不作任何价格断言
   （免费价格源不存在，task-price-alert-eval 已关单）；
4. hotel  —— 入住日前 7 天取消检查提醒（复核取消政策/房价变动）。

输入 = trip（days/stops）+ 既有台账 bookings + today；输出 = 节奏条目列表。
**纯派生读路径**：签名不含 db/session（无写入路径可言），不落 trip_events（D9），
每次调用结果一致。

目标来源与去重（spec「节奏条目与台账去重」）：
- train/flight/hotel 目标来自台账（suggested/pending 且带 service_date 的条目——
  「未建条目不凭空推荐」，该订什么由 bookings/scan 前瞻扫描负责）；
- ticket 目标来自行程站点（timed-entry / 热门关键词，与 scan 同词表）；
- 同目标（kind + service_date 或 stop）至多一条；confirmed 覆盖同目标 → 整体
  不再提醒（已订完成），cancelled 条目视为无意图不产出。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.models import Trip, TripBooking
from app.services.booking_service import (
    _HOT_ATTRACTION_KEYWORDS,
    _TIMED_ENTRY_KEYWORDS,
    _match_keywords,
)

# ── 规则常量（2026-11 公开口径，以官方渠道为准） ─────────────────
_TRAIN_PRESALE_DAYS = 15          # 12306 火车票预售期
_VENUE_RELEASE_DAYS = 7           # 放票表未命中时的通用提前量
_FLIGHT_WATCH_DAYS = 30           # 机票 T-30 关注窗
_HOTEL_CANCEL_CHECK_DAYS = 7      # 酒店入住前取消政策复核
_CLOSING_DAYS = 3                 # 距截止 ≤3 天视为 closing
# 已知放票口径条目（只录高置信度条目；未列出的一律走通用档，不编造时刻）
_VENUE_RELEASE_TABLE: dict[str, str] = {
    "故宫": "提前 7 天 20:00 放票",
}

_OFFICIAL_HINT = "以官方渠道为准"


def _phase(window_open: date, deadline: date, today: date) -> str:
    """窗口状态：upcoming（未开）→ open（已开）→ closing（≤3 天临截止）。"""
    if today < window_open:
        return "upcoming"
    if (deadline - today).days <= _CLOSING_DAYS:
        return "closing"
    return "open"


def _entry(
    *, kind: str, target: str, target_date: date, window_open: date,
    note: str, today: date, booking_id: str | None = None, stop_id: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "target": target,
        "target_date": target_date,
        "window_open": window_open,
        "window_deadline": target_date,
        "phase": _phase(window_open, target_date, today),
        "basis": "rule_based",
        "note": f"{note}；{_OFFICIAL_HINT}",
        "booking_id": booking_id,
        "stop_id": stop_id,
    }


def compute_booking_rhythm(
    trip: Trip, bookings: list[TripBooking], *, today: date
) -> list[dict[str, Any]]:
    """确定性节奏计算（纯函数，无 DB 副作用，重复调用结果一致）。

    - 台账目标：suggested/pending 且带 service_date 的 train/flight/hotel；
      同（kind, service_date）至多一条；confirmed 覆盖同目标 → 跳过；
    - 站点目标：timed-entry/热门关键词命中的 ticket（游玩日 = 所在 day.date）；
      同一站点至多一条；已 confirmed 门票（标题互相包含）→ 跳过；
    - 目标日期早于 today 的过期条目不产出。
    输出按 (target_date, kind, target) 稳定排序。
    """
    entries: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, Any]] = set()

    # confirmed 目标集合：同（kind, service_date）整体不再提醒
    confirmed_keys = {
        (b.kind, b.service_date) for b in bookings
        if b.status == "confirmed" and b.service_date is not None
    }

    # ── 1. 台账目标：train 预售 / flight 关注窗 / hotel 取消检查 ──
    for b in bookings:
        if b.status not in ("suggested", "pending") or b.service_date is None:
            continue
        if b.service_date < today:
            continue  # 目标日期已过（已出行/入住）不再提醒
        if b.kind not in ("train", "flight", "hotel"):
            continue
        if (b.kind, b.service_date) in confirmed_keys:
            continue  # 已确认完成，不再提醒
        key = (b.kind, b.service_date)
        if key in seen_targets:
            continue  # 同目标至多一条
        seen_targets.add(key)
        target = b.title or {"train": "火车票", "flight": "机票", "hotel": "酒店"}[b.kind]
        if b.kind == "train":
            window_open = b.service_date - timedelta(days=_TRAIN_PRESALE_DAYS)
            note = (
                f"火车票预售期 {_TRAIN_PRESALE_DAYS} 天（2026-11 口径），"
                f"{b.service_date.isoformat()} 出行建议 {window_open.isoformat()} 起购票"
            )
        elif b.kind == "flight":
            window_open = b.service_date - timedelta(days=_FLIGHT_WATCH_DAYS)
            note = (
                "国内机票 T-30 前后为关注窗口，T-14 后涨价风险上升"
                "（启发式建议，非任何价格断言）"
            )
        else:  # hotel
            window_open = b.service_date - timedelta(days=_HOTEL_CANCEL_CHECK_DAYS)
            note = f"入住前 {_HOTEL_CANCEL_CHECK_DAYS} 天建议复核取消政策与房价变动"
        entries.append(_entry(
            kind=b.kind, target=target, target_date=b.service_date,
            window_open=window_open, note=note, today=today, booking_id=b.id,
        ))

    # ── 2. 站点目标：ticket 放票窗口（与 scan 同词表） ────────────
    confirmed_ticket_titles = [
        (b.title or "") for b in bookings if b.status == "confirmed" and b.kind == "ticket"
    ]
    for day in getattr(trip, "days", None) or []:
        visit = day.date
        if visit is None or visit < today:
            continue
        for stop in day.stops or []:
            name = (stop.name or "").strip()
            if not name or ("ticket", (visit, name)) in seen_targets:
                continue
            named = next((k for k in _VENUE_RELEASE_TABLE if k in name), None)
            timed = _match_keywords(name, _TIMED_ENTRY_KEYWORDS)
            hot = _match_keywords(name, _HOT_ATTRACTION_KEYWORDS)
            if not (named or timed or hot):
                continue
            # 已确认同名门票（标题互相包含）→ 该站点不再提醒
            if any(name in t or t in name for t in confirmed_ticket_titles if t):
                continue
            seen_targets.add(("ticket", (visit, name)))
            if named:
                note = f"{name} {named} {_VENUE_RELEASE_TABLE[named]}（2026-11 口径）"
            else:
                note = (
                    f"{name} 为热门/限时场馆，建议提前 {_VENUE_RELEASE_DAYS} 天"
                    "关注购票（未掌握具体放票时刻）"
                )
            entries.append(_entry(
                kind="ticket", target=f"{name} 门票", target_date=visit,
                window_open=visit - timedelta(days=_VENUE_RELEASE_DAYS),
                note=note, today=today, stop_id=stop.id,
            ))

    entries.sort(key=lambda e: (e["target_date"], e["kind"], e["target"]))
    return entries

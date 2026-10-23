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

from datetime import UTC, date, datetime
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


def build_trip_export(
    trip: Trip, *, plan_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建导出行程 JSON（两条访问路径共用）。

    plan_data 为 None 或 {} 时 plan 输出 None（行程可能尚未 AI 规划；
    手工创建的行程照样可导出）。
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
        "plan": _sanitize_plan(data) if data else None,
    }
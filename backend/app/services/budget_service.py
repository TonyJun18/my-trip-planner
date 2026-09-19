"""预算计算服务。"""
from __future__ import annotations

from app.models import Trip


def compute_budget(trip: Trip) -> dict:
    """根据行程中的站点费用汇总预算明细。

    返回结构：
    {
      "total_estimated": float,
      "by_type": {"attraction": float, "food": float, "hotel": float},
      "daily_average": float | None,
      "currency": "CNY"
    }
    """
    by_type: dict[str, float] = {"attraction": 0.0, "food": 0.0, "hotel": 0.0}
    total = 0.0
    for day in trip.days:
        for stop in day.stops:
            cost = stop.estimated_cost or 0.0
            by_type[stop.stop_type] = by_type.get(stop.stop_type, 0.0) + cost
            total += cost

    n_days = (trip.end_date - trip.start_date).days + 1
    return {
        "total_estimated": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "daily_average": round(total / n_days, 2) if n_days > 0 and total else None,
        "currency": "CNY",
    }
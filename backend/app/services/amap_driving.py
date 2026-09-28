"""自驾真实路径层：高德驾车路径 API → 结构化 legs（供 DrivingGate 校验）。

设计（工程化降级，绝不阻断规划）：
- 仅在 ``settings.DRIVING_ROUTE_SOURCE == 'amap'`` 且 ``AMAP_API_KEY`` 已配置时启用；
  否则是恒降级（直接返回 None，调用方走 haversine）。
- 单条 leg 请求失败 → 该 leg 降级 haversine（计数为「部分降级」）；
  连续失败达 ``DRIVING_ROUTE_BREAKER_THRESHOLD`` → 行程级熔断，后续 leg 不再请求真实路径。
- 超长单段（约 >2.5h）自动附加「中途经停」建议（rest_km / rest_minutes），
  供 DrivingGate 在超限 issue 的 suggestion 里给出经停优化（TripPlanner AI 差异化）。
- 本模块不做任何业务判定（超限/累计/折返），只产出可判定的 legs——
  判定逻辑唯一收敛在 ``driving_service._run_day_checks``（确定性、可测试）。

协议：
- 高德驾车路径规划 Web 服务 API:
  GET https://restapi.amap.com/v3/direction/driving?origin=lng,lat&destination=lng,lat&key=...
  返回 route.paths[0]: {distance(米), duration(秒), strategy}
"""

from __future__ import annotations

from typing import Any

import httpx

from app.common.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_AMAP_DRIVING_ENDPOINT = "https://restapi.amap.com/v3/direction/driving"
# 高德城市内驾车默认车速估值：用于在 API 的 duration 之外做经停点距离估算（km）
_AMAP_AVG_KMH = 60.0

# 行程级熔断状态（进程内）：连续失败计数；>= 阈值后本轮不再请求真实路径
_amap_failures = 0
_amap_breaker_open_until: float = 0.0


def _amap_enabled() -> bool:
    """真实路径是否启用：配置切换 + API key 就绪 + 熔断未打开。"""
    if settings.DRIVING_ROUTE_SOURCE != "amap":
        return False
    if not settings.AMAP_API_KEY:
        return False
    import time

    if time.monotonic() < _amap_breaker_open_until:
        return False
    return True


def _record_failure() -> None:
    """记录一次连续失败；达到阈值 → 打开熔断（冷却 DRIVING_ROUTE_TIMEOUT*2 秒）。"""
    global _amap_failures, _amap_breaker_open_until
    import time

    _amap_failures += 1
    if _amap_failures >= settings.DRIVING_ROUTE_BREAKER_THRESHOLD:
        _amap_breaker_open_until = time.monotonic() + settings.DRIVING_ROUTE_TIMEOUT * 2
        logger.warning(
            "高德驾车路径连续失败 %d 次，熔断 %s 秒，降级 haversine",
            _amap_failures, settings.DRIVING_ROUTE_TIMEOUT * 2,
        )


def _record_success() -> None:
    global _amap_failures
    _amap_failures = 0


def _reset_breaker_for_tests() -> None:
    """测试辅助：清空熔断状态（幂等）。"""
    global _amap_failures, _amap_breaker_open_until
    _amap_failures = 0
    _amap_breaker_open_until = 0.0


def _parse_leg(data: dict[str, Any]) -> dict[str, Any] | None:
    """解析高德驾车路径响应 → 单条 leg。

    返回 {"from","to","distance_km","drive_minutes","source":"amap"}；
    无有效路径返回 None（调用方降级 haversine）。
    """
    try:
        path = (data.get("route") or {}).get("paths") or []
        if not path:
            return None
        distance_m = float(path[0].get("distance") or 0)
        duration_s = float(path[0].get("duration") or 0)
    except (TypeError, ValueError):
        return None
    if distance_m <= 0:
        return None
    return {
        "source": "amap",
        "distance_km": round(distance_m / 1000.0, 1),
        "drive_minutes": int(round(duration_s / 60.0)),
    }


def _rest_suggestion(distance_km: float, drive_minutes: int) -> dict[str, Any] | None:
    """超长单段（约 >2.5h 或 >120km）附加中途经停建议。

    经停点距离 = 总里程的一半（约行驶 1.25h 后休息），时长取 DRIVING_LEG_REST_MINUTES。
    """
    if drive_minutes <= 0:
        return None
    if distance_km <= 0:
        return None
    # 超过 2.5h（150min）且里程 >120km 才建议经停（短途不需休息）
    if drive_minutes > 150 and distance_km > 120:
        return {
            "rest_km": round(distance_km / 2.0, 1),
            "rest_minutes": settings.DRIVING_LEG_REST_MINUTES,
        }
    return None


async def _fetch_leg(
    origin: tuple[float, float], destination: tuple[float, float], *, timeout: float | None = None
) -> dict[str, Any] | None:
    """请求高德驾车路径 API 并解析为 leg；任何失败返回 None（调用方降级）。"""
    key = settings.AMAP_API_KEY
    if not key:
        return None
    params = {
        "key": key,
        "origin": f"{origin[1]},{origin[0]}",  # 高德格式：经度,纬度
        "destination": f"{destination[1]},{destination[0]}",
        "strategy": "10",  # 速度优先
        "extensions": "base",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout or settings.DRIVING_ROUTE_TIMEOUT) as client:
            resp = await client.get(_AMAP_DRIVING_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning("高德驾车路径请求失败: %s", exc)
        return None
    if data.get("status") != "1":
        logger.warning("高德驾车路径返回非成功: %s", data.get("info"))
        return None
    leg = _parse_leg(data)
    if leg is None:
        logger.warning("高德驾车路径响应无有效路径")
    return leg


async def fetch_driving_legs(stops: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """为相邻站点批量请求真实驾车 leg。

    - 未启用（配置/key/熔断）→ 返回 None（调用方走 haversine）
    - 单条失败 → 该 leg 降级为 haversine 估算（_build_haversine_legs 同名段兜底）
    - 全部成功 → 返回 [{from,to,distance_km,drive_minutes,source:'amap', rest_km?, rest_minutes?}]

    返回 None 表示「本行程完全走 haversine」（未启用或首条就熔断），
    返回列表则每条 leg 都有确定 source（amap 或已降级 haversine）。
    """
    if not _amap_enabled():
        return None

    from app.services.driving_service import _build_haversine_legs, leg_distance_km, _stop_coords

    legs: list[dict[str, Any]] = []
    degraded = 0
    for i in range(1, len(stops)):
        prev, stop = stops[i - 1], stops[i]
        if not (isinstance(prev, dict) and isinstance(stop, dict)):
            continue
        prev_coords = _stop_coords(prev)
        stop_coords = _stop_coords(stop)
        if prev_coords is None or stop_coords is None:
            continue
        name = stop.get("name") or f"站点{i + 1}"
        prev_name = prev.get("name") or f"站点{i}"

        leg = await _fetch_leg(prev_coords, stop_coords)
        if leg is None:
            degraded += 1
            _record_failure()
            h = leg_distance_km(prev, stop)
            if h is None:
                continue
            leg = {
                "from": prev_name, "to": name,
                "distance_km": round(h, 1),
                "drive_minutes": int(round(h / 50.0 * 60.0)),
                "source": "haversine",  # 显式标注：本条已降级
            }
        else:
            _record_success()
            leg["from"] = prev_name
            leg["to"] = name

        rest = _rest_suggestion(float(leg.get("distance_km") or 0), int(leg.get("drive_minutes") or 0))
        if rest:
            leg.update(rest)
        legs.append(leg)

    if degraded:
        logger.info("自驾真实路径部分降级：%d/%d 条 leg 回退 haversine", degraded, len(legs))
    return legs
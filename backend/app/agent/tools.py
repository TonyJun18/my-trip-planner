"""Agent 工具：search_attractions / search_hotels / query_weather / compute_budget。

每个工具返回结构化 observation（真实业务数据），供 Agent 在 Thought 之后
得到 Observation，形成完整的 T-A-O 循环。多 Agent 场景下：
- AttractionSearchAgent / HotelAgent → search_attractions / search_hotels
- WeatherQueryAgent                    → query_weather
- PlannerAgent                         → 不调用工具，仅整合

数据来源：
- ``search_attractions`` / ``search_hotels``：高德地图 POI 搜索（AMAP_API_KEY）；
  未配置时降级 Tavily Search 搜索真实结果 + Nominatim 地理编码
- ``query_weather``：高德天气（AMAP_API_KEY）；未配置时降级 wttr.in
- ``compute_budget``：纯计算，无需外部依赖

统一 POI 输出结构（所有搜索工具一致，供 Planner 直接组装）：
{
  "name", "type"("attraction"|"food"|"hotel"), "lat"|"lng"(或 null),
  "estimated_cost", "duration_minutes"(可 null), "description", "source"
}
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from app.common.config import settings
from app.core.logging import get_logger
from app.services.budget_service import estimate_hotel_cost

logger = get_logger(__name__)


class SearchServiceError(Exception):
    """搜索/地理编码外部服务失败。"""


class WeatherServiceError(Exception):
    """天气查询外部服务失败。"""


# ── Tavily Search ───────────────────────────────────────
_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_SEARCH_TIMEOUT = 15.0

# ── 外部数据源运行时降级（进程级滑动窗口） ───────────────
class _SourceCircuit:
    """记录某个外部数据源的连续失败；连续失败 ≥ 阈值时暂时禁用，过冷却期恢复。"""

    def __init__(self, name: str, threshold: int = 2, recovery: float = 60.0) -> None:
        self.name = name
        self.threshold = threshold
        self.recovery = recovery
        self._fails: list[float] = []
        self._blocked_until: float = 0.0

    def ok(self) -> bool:
        return time.monotonic() >= self._blocked_until

    def record_failure(self) -> None:
        now = time.monotonic()
        self._fails = [t for t in self._fails if now - t < 60.0]
        self._fails.append(now)
        if len(self._fails) >= self.threshold:
            self._blocked_until = now + self.recovery
            logger.warning("数据源 %s 连续失败 %d 次，降级 %s 秒", self.name, self.threshold, self.recovery)

    def record_success(self) -> None:
        self._fails.clear()


_source_circuits = {
    "amap": _SourceCircuit("amap"),
    "tavily": _SourceCircuit("tavily"),
    "nominatim": _SourceCircuit("nominatim"),
    "wttr": _SourceCircuit("wttr"),
}


def _source_available(name: str) -> bool:
    return _source_circuits[name].ok()


async def _run_source(name: str, fn, *args, **kwargs):
    """执行带熔断的外部调用；失败计数并抛原始异常。"""
    try:
        result = await fn(*args, **kwargs)
        _source_circuits[name].record_success()
        return result
    except Exception:
        _source_circuits[name].record_failure()
        raise


def _tavily_headers() -> dict[str, str] | None:
    api_key = settings.TAVILY_API_KEY
    if not api_key:
        return None
    return {"Authorization": f"Bearer {api_key}"}


async def tavily_search(
    query: str,
    *,
    max_results: int = 8,
    search_depth: str = "basic",
) -> dict[str, Any]:
    """调用 Tavily Search，返回标准化结果。"""
    headers = _tavily_headers()
    if headers is None:
        raise SearchServiceError(
            "TAVILY_API_KEY 未配置，无法执行真实景点/餐厅搜索。请在 backend/.env 配置。"
        )

    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": False,
        "include_raw_content": False,
    }

    try:
        async with httpx.AsyncClient(timeout=_SEARCH_TIMEOUT) as client:
            resp = await client.post(_TAVILY_ENDPOINT, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Tavily 搜索失败 http=%s query=%s", exc.response.status_code, query)
        raise SearchServiceError(f"Tavily 搜索失败 HTTP {exc.response.status_code}") from exc
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning("Tavily 搜索超时/网络错误 query=%s", query)
        raise SearchServiceError(f"Tavily 搜索不可达: {exc}") from exc

    results: list[dict[str, Any]] = []
    for item in data.get("results", []):
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("content", "")
        results.append({"title": title, "url": url, "content": content})
    return {"query": query, "count": len(results), "results": results}


# ── Nominatim 地理编码 ───────────────────────────────────
_NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"
_GEO_TIMEOUT = 10.0


async def geocode(name: str, *, city: str | None = None) -> dict[str, Any] | None:
    """把地点名称解析为经纬度（免费 Nominatim，带 UA 与限速）。

    优先精确搜索 `name city`；失败再放宽为 `name`。
    """
    headers = {
        "User-Agent": "my-trip-planner/0.1 (personal demo; contact: pengtony9@gmail.com)",
        "Accept": "application/json",
    }
    queries = [q for q in (f"{name} {city}" if city else None, name) if q]

    async with httpx.AsyncClient(timeout=_GEO_TIMEOUT, headers=headers) as client:
        for q in queries:
            # Nominatim 使用条款：最多 1 请求/秒。统一在每次请求前限速（含成功路径），
            # 而非只在失败后 sleep——并发 geocode 时也要遵守限速，避免封 IP。
            await asyncio.sleep(1.1)
            try:
                resp = await client.get(
                    _NOMINATIM_ENDPOINT,
                    params={"q": q, "format": "json", "limit": 1, "addressdetails": 0},
                )
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning("地理编码失败 name=%s err=%s", name, exc)
                continue
            if data:
                item = data[0]
                try:
                    return {
                        "lat": float(item["lat"]),
                        "lng": float(item["lon"]),
                        "display_name": item.get("display_name", ""),
                        "source": "nominatim",
                    }
                except (KeyError, ValueError):
                    continue
    return None


# ── 解析 Tavily 结果 → 结构化 POI ────────────────────────
_TYPE_KEYWORDS = {
    "attraction": ["景点", "景区", "公园", "博物馆", "寺", "庙", "故居", "古城", "遗址", "湖", "山", "街",
                   "塔", "宫", "园", "馆", "sight", "museum", "park", "temple", "palace",
                   "garden", "lake", "old town", "ancient"],
    "food": ["餐厅", "饭店", "菜馆", "小吃", "食府", "火锅", "烧烤", "茶馆", "restaurant", "dining",
             "food", "cafe", "bistro", "cuisine", "street food"],
    "hotel": ["酒店", "民宿", "客栈", "宾馆", "hotel", "inn", "hostel", "resort", "b&b"],
}


def _guess_type(text: str) -> str:
    lowered = text.lower()
    # 优先体力法：先看是否命中酒店关键词（避免"西湖景区酒店"被误判）
    for stype, kws in _TYPE_KEYWORDS.items():
        for kw in kws:
            if kw in lowered:
                return stype
    return "attraction"


def _clean_name(title: str, max_len: int = 50) -> str:
    """从搜索标题里提取干净的地名（去掉常见前后缀杂质）。"""
    name = title.strip()
    # 去掉 "xx攻略", "xx门票", "xx一日游" 等尾巴
    name = re.sub(r"(_攻略|攻略|门票|一日游|两日游|旅游攻略|开放时间|怎么样|好玩吗|在哪里|地址|电话)$", "", name)
    name = re.sub(r"^(【|\[).*?(\]|】)", "", name)
    return name[:max_len].strip() or title[:max_len].strip()


async def _poi_from_search_result(item: dict[str, Any], city: str, source: str = "tavily") -> dict[str, Any] | None:
    """把一条 Tavily 结果转成 POI（统一结构，含 source）。地理编码失败则丢弃并计数。"""
    title = item.get("title", "")
    content = item.get("content", "")
    name = _clean_name(title)
    if not name:
        return None

    stype = _guess_type(f"{name} {content[:200]}")
    # 价格启发式：从内容里找 ¥/元 数字（粗糙但可用的低成本估计）
    cost = 0.0
    m = re.search(r"[¥￥]\s*(\d+)", content)
    if m:
        cost = float(m.group(1))

    geo = await geocode(name, city=city)
    if geo is None:
        # 地理编码失败：返回带空坐标的条目，标注不可定位（地图可跳过，不阻断规划）
        return {
            "name": name,
            "type": stype,
            "lat": None,
            "lng": None,
            "estimated_cost": cost,
            "duration_minutes": None,
            "description": content[:200],
            "source_url": item.get("url", ""),
            "geocoded": False,
            "source": source,
        }

    return {
        "name": geo.get("display_name", name),
        "type": stype,
        "lat": geo["lat"],
        "lng": geo["lng"],
        "estimated_cost": cost,
        "duration_minutes": None,
        "description": content[:200],
        "source_url": item.get("url", ""),
        "geocoded": True,
        "source": source,
    }


async def _search_pois_tavily(
    city: str,
    *,
    query: str | None = None,
    limit: int = 8,
    want_type: str = "attraction",
) -> dict[str, Any]:
    """Tavily + Nominatim 降级搜索（高德未配置时）。

    want_type: "attraction" | "hotel" | "food" → 用于构造搜索词与过滤。
    """
    type_query = {"attraction": "必去景点 旅游景点", "hotel": "酒店 住宿 推荐", "food": "必吃 餐厅 美食"}.get(want_type, "必去景点")
    search_query = query or f"{city} {type_query} 攻略"
    search_result = await tavily_search(search_query, max_results=limit)

    raw_items = search_result.get("results", [])
    # Nominatim 限速 1 req/s：串行地理编码（sem=1 + geocode 内请求前 sleep），
    # 避免并发打爆 Nominatim 被封 IP。
    sem = asyncio.Semaphore(1)

    async def _bounded(item: dict[str, Any]) -> dict[str, Any] | None:
        async with sem:
            return await _poi_from_search_result(item, city, source="tavily")

    pois = await asyncio.gather(*(_bounded(it) for it in raw_items))
    pois = [p for p in pois if p]

    # 按期望类型软过滤：不强制（同一条目的标题可能描述不清），但尽量对齐
    if want_type == "hotel":
        pois = [p for p in pois if _guess_type(f"{p['name']}") == "hotel"] or pois

    geocoded = sum(1 for p in pois if p.get("geocoded"))
    logger.info("search_pois city=%s want=%s raw=%d pois=%d geocoded=%d",
                city, want_type, len(raw_items), len(pois), geocoded)

    return {
        "city": city,
        "query": search_query,
        "count": len(pois),
        "results": pois,
    }


# ── 高德地图 POI 搜索（首选数据源） ────────────────────────
_AMAP_POI_ENDPOINT = "https://restapi.amap.com/v3/place/text"
# 高德 types: 景点/旅游=110000, 美食=050000, 酒店=100000
_AMAP_TYPE = {"attraction": "110000", "food": "050000", "hotel": "100000"}


async def search_pois_amap(
    city: str,
    *,
    query: str | None = None,
    limit: int = 8,
    want_type: str = "attraction",
) -> dict[str, Any]:
    """高德 POI 文本搜索，返回统一 POI 结构。

    需 ``AMAP_API_KEY``；未配置抛 ``SearchServiceError``（由上层降级）。
    """
    key = settings.AMAP_API_KEY
    if not key:
        raise SearchServiceError("AMAP_API_KEY 未配置")

    params = {
        "key": key,
        "keywords": query or (city if want_type == "attraction" else f"{city} {'酒店' if want_type == 'hotel' else ''}"),
        "city": city,
        "citylimit": "true",
        "types": _AMAP_TYPE.get(want_type, "110000"),
        "offset": str(limit),
        "page": "1",
        "extensions": "base",
        "output": "JSON",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            resp = await client.get(_AMAP_POI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning("高德 POI 搜索失败 city=%s err=%s", city, exc)
        raise SearchServiceError(f"高德 POI 搜索失败: {exc}") from exc

    if data.get("status") != "1":
        logger.warning("高德 POI 返回非成功 status=%s info=%s", data.get("status"), data.get("info"))
        raise SearchServiceError(f"高德 POI 搜索返回错误: {data.get('info')}")

    results = data.get("pois") or []
    pois = []
    for item in results:
        try:
            lat, lng = float(item["location"].split(",")[1]), float(item["location"].split(",")[0])
        except (KeyError, ValueError, IndexError):
            lat = lng = None
        # 高德 name 规整；type 字段形如 "景点;公园"，取第一段
        # 估算费用：酒店用城市基准价×档位倍率（代码确定性估算，补竞品缺口），
        # 其他类型 0（景点门票等实际价格高德不返回，前端标注"以实际为准"）
        est_cost = 0.0
        if want_type == "hotel":
            est_cost = estimate_hotel_cost(item.get("name"), city)
        pois.append({
            "name": item.get("name", ""),
            "type": want_type,
            "lat": lat,
            "lng": lng,
            "estimated_cost": est_cost,
            "duration_minutes": None,
            "description": (item.get("address") or item.get("type") or "")[:200],
            "source": "amap",
            "source_url": "",
            "geocoded": lat is not None,
        })
    logger.info("search_pois_amap city=%s want=%s pois=%d", city, want_type, len(pois))
    return {"city": city, "query": query or city, "count": len(pois), "results": pois}


async def search_attractions(city: str, *, query: str | None = None, limit: int = 8) -> dict[str, Any]:
    """搜索某城市的推荐景点/餐厅，返回结构化 POI 列表。

    真实数据：优先高德 POI（AMAP_API_KEY），未配置或高德连续失败时降级 Tavily + Nominatim。
    """
    primary = search_pois_amap if settings.AMAP_API_KEY else None
    return await _search_with_fallback(
        city, query=query, limit=limit, want_type="attraction",
        primary=primary, fallback=_search_pois_tavily,
    )


async def search_hotels(city: str, *, query: str | None = None, limit: int = 8) -> dict[str, Any]:
    """搜索某城市符合需求的酒店，返回结构化 POI 列表（type=hotel）。"""
    primary = search_pois_amap if settings.AMAP_API_KEY else None
    return await _search_with_fallback(
        city, query=query, limit=limit, want_type="hotel",
        primary=primary, fallback=_search_pois_tavily,
    )


async def _search_with_fallback(
    city: str,
    *,
    query: str | None,
    limit: int,
    want_type: str,
    primary: Any | None,
    fallback: Any,
) -> dict[str, Any]:
    """带数据源熔断的搜索：主源可用则试主源，失败/熔断则自动切备源。

    - 主源未配置（primary=None）→ 直接用备源
    - 主源连续失败触发熔断 → 跳过主源直接走备源
    - 主源一次失败 → 记录并降级到备源（本次用备源成功则平滑恢复）
    """
    if primary is not None and _source_available("amap"):
        try:
            return await _run_source("amap", primary, city, query=query, limit=limit, want_type=want_type)
        except Exception as exc:
            logger.warning("高德 POI 搜索失败，降级 Tavily (city=%s): %s", city, exc)
    return await _run_source("tavily", fallback, city, query=query, limit=limit, want_type=want_type)


async def search_foods(city: str, *, query: str | None = None, limit: int = 8) -> dict[str, Any]:
    """搜索某城市的美食/餐厅，返回结构化 POI 列表（type=food）。"""
    primary = search_pois_amap if settings.AMAP_API_KEY else None
    return await _search_with_fallback(
        city, query=query, limit=limit, want_type="food",
        primary=primary, fallback=_search_pois_tavily,
    )


# ── 天气查询 ─────────────────────────────────────────────
_AMAP_WEATHER_ENDPOINT = "https://restapi.amap.com/v3/weather/weatherInfo"
_WTTR_ENDPOINT = "https://wttr.in"


async def query_weather(city: str, *, days: int = 3) -> dict[str, Any]:
    """查询某城市未来几天的天气预报。

    真实数据：优先高德天气（AMAP_API_KEY，按 adcode），未配置/高德连续失败降级 wttr.in。
    返回结构：{"city", "days": [{"date","text_day","temp_min","temp_max","humidity"}],
              "count", "source"}
    """
    if settings.AMAP_API_KEY and _source_available("amap"):
        try:
            return await _run_source("amap", _weather_amap, city, days=days)
        except SearchServiceError as exc:
            logger.warning("高德天气失败，降级 wttr.in city=%s err=%s", city, exc)
    return await _run_source("wttr", _weather_wttr, city, days=days)


async def _weather_amap(city: str, *, days: int = 3) -> dict[str, Any]:
    """高德天气：先按城市名查 adcode（district），再查天气。"""
    key = settings.AMAP_API_KEY
    if not key:
        raise SearchServiceError("AMAP_API_KEY 未配置")

    # 1) 城市名 → adcode
    async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
        try:
            resp = await client.get(
                "https://restapi.amap.com/v3/config/district",
                params={"key": key, "keywords": city, "subdistrict": "0", "extensions": "base"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
            raise SearchServiceError(f"高德 district 查询失败: {exc}") from exc

    adcode = None
    districts = data.get("districts") or []
    if data.get("status") == "1" and districts:
        adcode = districts[0].get("adcode")

    if not adcode:
        raise SearchServiceError(f"高德未找到城市 {city} 的 adcode")

    # 2) 按 adcode 查天气（extensions=all 返回近 5 天预报）
    params = {"key": key, "city": adcode, "extensions": "all", "output": "JSON"}
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            resp = await client.get(_AMAP_WEATHER_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
        raise SearchServiceError(f"高德天气查询失败: {exc}") from exc

    if data.get("status") != "1":
        raise SearchServiceError(f"高德天气返回错误: {data.get('info')}")

    forecasts = data.get("forecasts") or []
    days_out = []
    for item in (forecasts[0].get("casts") if forecasts else [])[: max(days, 1)]:
        days_out.append({
            "date": item.get("date"),
            "text_day": item.get("dayweather"),
            "text_night": item.get("nightweather"),
            "temp_max": item.get("daytemp"),
            "temp_min": item.get("nighttemp"),
            "humidity": item.get("humidity"),
        })
    return {"city": city, "days": days_out, "count": len(days_out), "source": "amap"}


async def _weather_wttr(city: str, *, days: int = 3) -> dict[str, Any]:
    """wttr.in 降级（无需 key，JSON 输出）。"""
    params = {"format": "j1", "lang": "zh"}
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            resp = await client.get(f"{_WTTR_ENDPOINT}/{city}", params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
        raise WeatherServiceError(f"wttr.in 天气查询失败: {exc}") from exc

    days_out = []
    for item in (data.get("weather") or [])[: max(days, 1)]:
        days_out.append({
            "date": item.get("date"),
            "text_day": (item.get("hourly") or [{}])[4].get("lang_zh") or item.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value"),
            "text_night": None,
            "temp_max": item.get("maxtempC"),
            "temp_min": item.get("mintempC"),
            "humidity": (item.get("hourly") or [{}])[4].get("humidity"),
        })
    return {"city": city, "days": days_out, "count": len(days_out), "source": "wttr.in"}


def compute_budget(stops: list[dict[str, Any]]) -> dict[str, Any]:
    """根据站点列表计算预算明细（纯计算）。"""
    by_type: dict[str, float] = {}
    total = 0.0
    for stop in stops:
        cost = float(stop.get("estimated_cost") or 0)
        stype = stop.get("type", "attraction")
        by_type[stype] = by_type.get(stype, 0.0) + cost
        total += cost
    return {
        "total_estimated": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "currency": "CNY",
    }


def plan_payload(destination: str, days: list[dict[str, Any]], budget: dict[str, Any]) -> dict[str, Any]:
    """组装最终行程 JSON（TripPlan.plan_data 结构）。"""
    return {
        "destination": destination,
        "days": days,
        "budget": budget,
    }


def as_json(value: Any) -> str:
    """工具结果 → observation 字符串（供 LLM 读取）。"""
    return json.dumps(value, ensure_ascii=False)
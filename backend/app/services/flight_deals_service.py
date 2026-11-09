"""机票特价采集（Flight Deals）：全网搜索 → 航线页抽取 → 解析 → 硬闸门 → 2–3 方案。

设计哲学（与 `discount_service` / `servicing_service` / `booking_service` 同源）：

1. **确定性优先**：解析/排序/闸门全是纯函数，可单测、零 LLM；采集 agent 不调 LLM。
2. **硬闸门（防编造）**：没有来源 URL、没有价格、没有币种、域名不在白名单 → 一律不进
   ``options``；来源为公开搜索结果的促销帖只进 ``promos``（不做具体价格断言）。
3. **诚实口径**：拿到的价格是「航线页展示的最低参考价（起价）+ 样例日期」，
   不是任意日期的实时报价；``price_kind="from"`` 且必须同时给出 ``source_url`` +
   ``fetched_at``，前端需标注「以承运人/OTA 实时价为准」。
4. **失败不阻断**：任一外部调用失败只降级（``status=degraded``），绝不抛给主流程。
5. **可换源**：``FlightDealProvider`` 协议 + 注册表，未来接第三方实时报价 API
   （Amadeus 免费版已于 2026-07-17 停用，勿按老教程设计）只需新增一个 provider。

数据源现状（2026-11-09 实测）：
- Tavily Search 2.4s 可命中天巡航线页；
- Tavily Extract 抓 `tianxun.com/routes/...` 1.3–3.8s 返回含日期/价格/航司的正文；
- 英文站（skyscanner.com 等）为 SPA，Extract 返回空 → 国际线走天巡中国站（币种 CNY），
  解析器同时支持 £/$/€/HK$/S$/JPY，供未来 provider 直接复用。
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import date as _Date
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── 口径常量 ─────────────────────────────────────────────────
CACHE_TTL_SECONDS = 6 * 3600          # 缓存 6h：航线页最低价不会分钟级变化
PARTIAL_CACHE_TTL_SECONDS = 300       # 只有促销/无可靠报价：短缓存 5min，允许快速重试
COLLECT_TIMEOUT_SECONDS = 20.0        # 单次采集总超时（超时即降级，不拖慢规划）
MAX_OPTIONS = 3                       # 给用户的方案数上限（2–3）
MAX_PROMOS = 4
_MEMORY_CACHE_MAX = 128
_MAX_EXTRACT_PAGES = 2                # 单次采集最多抽取 2 个页面

PRICE_KIND_FROM = "from"              # 明确标注：航线页「起价」，不是所选日期实价
NOTE_DEFAULT = "价格来自公开航线页展示的最低参考价，以承运人/OTA 实时价格为准"
NOTE_EMPTY = "暂未获取到可靠的机票特价信息"

# 来源域名白名单（页面可信 + 结构可解析）。不在名单内的链接只允许进 promos。
SOURCE_DOMAINS: tuple[str, ...] = (
    "tianxun.com",
    "skyscanner.net",
    "skyscanner.com",
    "trip.com",
    "ctrip.com",
    "qunar.com",
    "fliggy.com",
    "ly.com",
    # 航司官网（促销页）
    "csair.com", "ch.com", "ceair.com", "airchina.com.cn",
    "sda.cn", "juneyaoair.com", "ch.com.cn", "springairlines.com",
    "airasia.com", "jal.com", "ana.co.jp", "singaporeair.com",
)

_SYMBOL_CURRENCY = {
    "¥": "CNY", "￥": "CNY", "US$": "USD", "S$": "SGD", "HK$": "HKD",
    "$": "USD", "£": "GBP", "€": "EUR", "JP¥": "JPY",
}
_KNOWN_CURRENCIES = {"CNY", "USD", "GBP", "EUR", "HKD", "SGD", "JPY", "THB", "KRW"}

__all__ = [
    "CACHE_TTL_SECONDS",
    "MAX_OPTIONS",
    "NOTE_DEFAULT",
    "NOTE_EMPTY",
    "PRICE_KIND_FROM",
    "SOURCE_DOMAINS",
    "FlightDealProvider",
    "collect_flight_deals",
    "get_provider",
    "infer_year",
    "parse_offers",
    "rank_options",
    "register_provider",
    "route_key",
    "source_domain_allowed",
    "clear_memory_cache",
]


# ══════════════════════════════════════════════════════════════
#  Provider 协议 + 注册表（策略模式；未来接实时报价 API 只加实现）
# ══════════════════════════════════════════════════════════════
@runtime_checkable
class FlightDealProvider(Protocol):
    """机票特价采集源协议。

    实现者负责「拿到原始素材」，解析/闸门/排序由本模块统一做——保证不同来源
    产出的口径一致（同为 ``price_kind="from"``、同样必须带 ``source_url``）。
    """

    name: str

    async def collect(self, request: dict[str, Any]) -> dict[str, Any]:
        """返回 ``{"pages": [(url, text)], "search": [result...], "provider": name}``。"""
        ...


_PROVIDER_REGISTRY: dict[str, FlightDealProvider] = {}


def register_provider(provider: FlightDealProvider) -> None:
    """注册采集源（同名覆盖；便于测试注入 fake）。"""
    _PROVIDER_REGISTRY[getattr(provider, "name", "") or ""] = provider


def get_provider(name: str = "tavily") -> FlightDealProvider:
    """取采集源；未注册时惰性注册默认 Tavily 实现。"""
    if name not in _PROVIDER_REGISTRY:
        from app.services.flight_deals_tavily import TavilyFlightDealProvider

        register_provider(TavilyFlightDealProvider())
    return _PROVIDER_REGISTRY[name]


# ══════════════════════════════════════════════════════════════
#  基础工具（纯函数）
# ══════════════════════════════════════════════════════════════
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _as_date(value: Any) -> _Date | None:
    """把 request 里的日期（date / ISO 字符串）归一成 date，无法解析返回 None。"""
    if isinstance(value, _Date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()[:10]
    match = _DATE_RE.match(text)
    if not match:
        return None
    try:
        return _Date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def infer_year(month: int, day: int, anchor: _Date | None) -> int:
    """航线页只给「M月D日」→ 选离 anchor 最近的年份（前后各一年内）。

    航线页通常展示未来 12 个月的报价，缺年份时用「离出发日期最近」的年份，
    避免把 12 月报价算成三年前。
    """
    if anchor is None:
        return datetime.now(timezone.utc).year
    best_year, best_gap = anchor.year, None
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            candidate = _Date(year, month, day)
        except ValueError:
            continue
        gap = abs((candidate - anchor).days)
        if best_gap is None or gap < best_gap:
            best_year, best_gap = year, gap
    return best_year


def _currency_from_symbol(symbol: str, text: str = "") -> str | None:
    """币种符号 → ISO 代码；页面里显式 ``currency=XXX`` 优先。"""
    explicit = re.search(r"currency=([A-Z]{3})", text or "")
    if explicit and explicit.group(1) in _KNOWN_CURRENCIES:
        return explicit.group(1)
    return _SYMBOL_CURRENCY.get(symbol)


def _to_float(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def source_domain_allowed(url: str) -> bool:
    """来源域名是否在白名单（用于决定能否进 options）。"""
    low = (url or "").lower()
    return any(domain in low for domain in SOURCE_DOMAINS)


def _domain_label(url: str) -> str:
    """从 URL 提取可读来源名（skyscanner / trip.com ...）。"""
    low = (url or "").lower()
    for domain in SOURCE_DOMAINS:
        if domain in low:
            return "skyscanner" if domain.startswith("skyscanner") else domain
    host = re.sub(r"^https?://", "", low).split("/")[0]
    return host.removeprefix("www.") or "unknown"


def route_key(request: dict[str, Any]) -> str:
    """缓存键：航线 + 日期窗 + 人数（同一航线同日期窗复用一次采集）。"""
    return "|".join(
        [
            str(request.get("departure") or "").strip(),
            str(request.get("destination") or "").strip(),
            str(request.get("start_date") or ""),
            str(request.get("end_date") or ""),
            str(request.get("travelers") or 1),
        ]
    )


# ══════════════════════════════════════════════════════════════
#  解析器（吃 Tavily Extract 的 markdown，产出候选 offer）
# ══════════════════════════════════════════════════════════════
# ① 中文航线页「报价块」：每位乘客¥1,103。12月10日周四出发，12月17日周四返回。A和B的往返航班。
_BLOCK_RE = re.compile(
    r"每位乘客\s*([$£€¥￥]|US\$|S\$|HK\$|JP¥)\s?([\d,]{3,9})[。.]"
    r"\s*(\d{1,2})月(\d{1,2})日周.出发[，,]\s*(\d{1,2})月(\d{1,2})日周.返回[。.]"
    r"\s*(.{0,80}?)的往返航班",
)
# ② 中文航线页「最优惠航班」行：| 已找到的最优惠航班 | [¥2,149](/transport/flights/HGH/NRT/20270301/20270302?...)
_CHEAPEST_RE = re.compile(
    r"已找到的最优惠航班\s*\|\s*\[([$£€¥￥]|US\$|S\$|HK\$|JP¥)\s?([\d,]{3,9})\]"
    r"\(([^)\s]+)\)"
)
_URL_ROUTE_RE = re.compile(r"/([A-Z]{3})/([A-Z]{3})/(\d{8})/(\d{8})")
_URL_ROUTE_SHORT_RE = re.compile(r"/routes/([a-z]{3})/([a-z]{3,4})/")
_AIRLINE_CODE_RE = re.compile(r"priceTrace=[^)\s]*?%2A([A-Z]{2})%7C")
# ③ 英文站通用：「from $512」+ 可选日期
_EN_PRICE_RE = re.compile(
    r"(?:from|From|cheapest|Cheapest)[^.\n]{0,40}?(US\$|S\$|HK\$|[$£€¥])\s?([\d,]{3,9})"
)
_EN_DATE_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_EN_DATE_TEXT_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s*,?\s*(\d{4})?")


def _parse_stops(context: str) -> int | None:
    """从报价块上下文判断经停：非直飞 → 1（次数未知，保守取 1）；N次中转 → N；直飞 → 0。"""
    if "非直飞" in context:
        match = re.search(r"(\d+)\s*次中转", context)
        return int(match.group(1)) if match else 1
    match = re.search(r"(\d+)\s*次中转", context)
    if match:
        return int(match.group(1))
    if "直飞" in context:
        return 0
    return None


def _split_airlines(raw: str) -> list[str]:
    """「北京首都航空和中国东方航空」→ ['北京首都航空', '中国东方航空']。"""
    text = (raw or "").strip().strip("。.")
    if not text:
        return []
    parts = re.split(r"和|与|、|/|,| and ", text)
    return [p.strip() for p in parts if p.strip()][:4]


def _new_offer(
    *,
    price: float,
    currency: str,
    source_url: str,
    airlines: list[str] | None = None,
    outbound: _Date | None = None,
    inbound: _Date | None = None,
    stops: int | None = None,
    from_code: str | None = None,
    to_code: str | None = None,
    confidence: float = 0.8,
    note: str | None = None,
) -> dict[str, Any]:
    """构造一条候选 offer（字段契约见 PlanSchema.flight_deals.options）。"""
    return {
        "price": round(price, 2),
        "currency": currency,
        "price_kind": PRICE_KIND_FROM,
        "airlines": airlines or [],
        "outbound_date": outbound.isoformat() if outbound else None,
        "inbound_date": inbound.isoformat() if inbound else None,
        "stops": stops,
        "source": _domain_label(source_url),
        "source_url": source_url,
        "from_code": from_code,
        "to_code": to_code,
        "confidence": round(float(confidence), 2),
        "note": note or "航线页展示的样例日期最低价",
    }


def parse_offers(
    text: str,
    *,
    page_url: str,
    anchor: _Date | None = None,
    request: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """从一页正文解析候选 offer（不做闸门；闸门在 ``_gate_offers``）。

    支持的页面形态（均来自实测 fixture）：
    - 中文航线页报价块（国内/国际）；
    - 中文航线页「最优惠航班」表格行（国际线常见，日期在链接路径里）；
    - 英文站 ``from $512`` + 可选 ISO 日期。
    """
    if not text or not page_url:
        return []
    anchor = anchor or _as_date((request or {}).get("start_date"))
    offers: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def _push(offer: dict[str, Any]) -> None:
        key = (offer["price"], offer["currency"], offer["outbound_date"], tuple(offer["airlines"][:1]))
        if key in seen:
            return
        seen.add(key)
        offers.append(offer)

    # ① 报价块
    for match in _BLOCK_RE.finditer(text):
        symbol, price_raw, m1, d1, m2, d2, airline_raw = match.groups()
        price = _to_float(price_raw)
        if price is None:
            continue
        currency = _currency_from_symbol(symbol, page_url)
        if not currency:
            continue
        outbound = _safe_date(infer_year(int(m1), int(d1), anchor), int(m1), int(d1))
        inbound = _safe_date(infer_year(int(m2), int(d2), anchor), int(m2), int(d2))
        context = text[match.end(): match.end() + 400]
        _push(
            _new_offer(
                price=price,
                currency=currency,
                source_url=page_url,
                airlines=_split_airlines(airline_raw),
                outbound=outbound,
                inbound=inbound,
                stops=_parse_stops(context),
                confidence=0.8 if outbound else 0.6,
            )
        )

    # ② 「最优惠航班」行（日期/航司藏在链接里）
    for match in _CHEAPEST_RE.finditer(text):
        symbol, price_raw, link = match.groups()
        price = _to_float(price_raw)
        if price is None:
            continue
        currency = _currency_from_symbol(symbol, link) or _currency_from_symbol(symbol, page_url)
        if not currency:
            continue
        source_url = _absolute_url(link, page_url)
        from_code = to_code = None
        outbound = inbound = None
        route_match = _URL_ROUTE_RE.search(link)
        if route_match:
            from_code, to_code = route_match.group(1), route_match.group(2)
            outbound = _parse_compact_date(route_match.group(3))
            inbound = _parse_compact_date(route_match.group(4))
        else:
            short = _URL_ROUTE_SHORT_RE.search(link)
            if short:
                from_code, to_code = short.group(1).upper(), short.group(2).upper()
        airline_match = _AIRLINE_CODE_RE.search(link)
        airlines = [airline_match.group(1)] if airline_match else []
        if not airlines:
            popular = re.search(r"最受欢迎的航空公司\s*\|\s*\[([^\]]+)\]", text)
            if popular:
                airlines = [popular.group(1).strip()]
        _push(
            _new_offer(
                price=price,
                currency=currency,
                source_url=source_url,
                airlines=airlines,
                outbound=outbound,
                inbound=inbound,
                stops=None,
                from_code=from_code,
                to_code=to_code,
                confidence=0.75 if outbound else 0.6,
                note="航线页「已找到的最优惠航班」样例日期",
            )
        )

    # ③ 英文站通用（未来 provider 直接复用）
    if not offers:
        en_prices = list(_EN_PRICE_RE.finditer(text))
        en_dates = _parse_en_dates(text)
        if en_prices:
            price_match = en_prices[0]
            symbol, price_raw = price_match.groups()
            price = _to_float(price_raw)
            currency = _currency_from_symbol(symbol, page_url)
            if price is not None and currency:
                outbound = en_dates[0] if en_dates else None
                inbound = en_dates[1] if len(en_dates) > 1 else None
                _push(
                    _new_offer(
                        price=price,
                        currency=currency,
                        source_url=page_url,
                        outbound=outbound,
                        inbound=inbound,
                        stops=None,
                        confidence=0.6 if outbound else 0.45,
                        note="英文航线页展示的最低起价",
                    )
                )

    return offers


def _safe_date(year: int, month: int, day: int) -> _Date | None:
    try:
        return _Date(year, month, day)
    except ValueError:
        return None


def _parse_compact_date(raw: str) -> _Date | None:
    if not raw or len(raw) != 8:
        return None
    return _safe_date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))


def _parse_en_dates(text: str) -> list[_Date]:
    dates: list[_Date] = []
    for match in _EN_DATE_ISO_RE.finditer(text or ""):
        parsed = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed:
            dates.append(parsed)
    if dates:
        return dates
    for match in _EN_DATE_TEXT_RE.finditer(text or ""):
        month = _MONTHS.get(match.group(2).lower())
        if not month:
            continue
        year = int(match.group(3)) if match.group(3) else datetime.now(timezone.utc).year
        parsed = _safe_date(year, month, int(match.group(1)))
        if parsed:
            dates.append(parsed)
    return dates


def _absolute_url(link: str, base_url: str) -> str:
    """相对链接 → 绝对链接（保留原站，便于用户点开核对）。"""
    if link.startswith("http://") or link.startswith("https://"):
        return link
    match = re.match(r"^(https?://[^/]+)", base_url or "")
    if not match:
        return base_url or link
    if link.startswith("/"):
        return match.group(1) + link
    return match.group(1) + "/" + link.lstrip("./")


# ══════════════════════════════════════════════════════════════
#  硬闸门 + 排序（确定性，零 LLM）
# ══════════════════════════════════════════════════════════════
def _gate_offers(offers: list[dict[str, Any]], request: dict[str, Any]) -> list[dict[str, Any]]:
    """硬闸门：无来源/无价/无币种/非白名单 → 丢弃；日期偏离过远 → 置信度打折。"""
    start = _as_date(request.get("start_date"))
    passed: list[dict[str, Any]] = []
    for offer in offers:
        url = (offer.get("source_url") or "").strip()
        price = offer.get("price")
        currency = offer.get("currency")
        if not url.startswith("http"):
            continue
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        if currency not in _KNOWN_CURRENCIES:
            continue
        if not source_domain_allowed(url):
            # 非白名单来源：不进 options（可解析但不可信）；promos 走搜索结果。
            continue
        outbound = _as_date(offer.get("outbound_date"))
        if start and outbound:
            drift = abs((outbound - start).days)
            if drift > 14:
                offer = {**offer, "confidence": round(float(offer.get("confidence", 0.6)) * 0.6, 2)}
                offer["note"] = f"{offer.get('note') or ''}（报价日期偏离行程 {drift} 天）".strip()
        if float(offer.get("confidence") or 0) < 0.3:
            continue
        passed.append(offer)
    return passed


def _date_gap(offer: dict[str, Any], anchor: _Date) -> int:
    """报价出发日期与行程出发日期的天数差（无日期 → 极大值，排到最后）。"""
    outbound = _as_date(offer.get("outbound_date"))
    return abs((outbound - anchor).days) if outbound else 10**6


def rank_options(
    offers: list[dict[str, Any]],
    request: dict[str, Any],
    *,
    limit: int = MAX_OPTIONS,
) -> list[dict[str, Any]]:
    """确定性产出 2–3 个方案位：最省 / 日期最贴合 / 最稳妥（直飞优先）。

    - 数据不足时输出 1–2 条，**绝不补假数据**；
    - 同一 offer 只能占一个方案位，位子空了按价格补齐。
    """
    if not offers:
        return []
    start = _as_date(request.get("start_date"))
    picked: list[dict[str, Any]] = []
    used: set[int] = set()

    def _take(index: int, strategy: str, reason: str) -> None:
        if index in used or len(picked) >= limit:
            return
        used.add(index)
        picked.append({**offers[index], "strategy": strategy, "reason": reason})

    def _take_best(strategy: str, reason: str, key) -> None:
        """按 key 排序取「第一个还没被占用的」——保证三个方案位不互相挤掉。"""
        for index in sorted(range(len(offers)), key=key):
            if index not in used:
                _take(index, strategy, reason)
                return

    _take_best("cheapest", "价格最低", lambda i: float(offers[i].get("price") or 1e12))

    if start:
        dated = [i for i in range(len(offers)) if _as_date(offers[i].get("outbound_date"))]
        if dated:
            _take_best("best_dates", "出发日期最贴合行程", lambda i: _date_gap(offers[i], start))

    def _stops_key(index: int) -> tuple[int, int, float]:
        stops = offers[index].get("stops")
        known_direct = 0 if stops == 0 else (1 if isinstance(stops, int) else 2)
        return (known_direct, int(stops) if isinstance(stops, int) else 9, float(offers[index].get("price") or 1e12))

    _take_best("safest", "直飞/少中转优先", _stops_key)

    by_price = sorted(range(len(offers)), key=lambda i: float(offers[i].get("price") or 1e12))
    for index in by_price:
        if len(picked) >= limit:
            break
        _take(index, "alternative", "备选")

    for position, option in enumerate(picked, start=1):
        option["option_id"] = f"fd_{position}"
        option["title"] = _option_title(option)
    return picked


def _option_title(option: dict[str, Any]) -> str:
    price = option.get("price")
    currency = option.get("currency") or "CNY"
    symbol = {"CNY": "¥", "USD": "$", "GBP": "£", "EUR": "€", "HKD": "HK$", "SGD": "S$", "JPY": "JP¥"}.get(currency, "")
    outbound = option.get("outbound_date") or ""
    inbound = option.get("inbound_date") or ""
    parts = [f"往返 {symbol}{price:,.0f} 起" if price else "往返机票"]
    if outbound and inbound:
        parts.append(f"{outbound[5:]} → {inbound[5:]}")
    # 只有航司中文/全名才进标题；两字码（如 JD/NH）放 details，避免标题难读
    airlines = [a for a in (option.get("airlines") or []) if a and not (len(a) <= 3 and a.isascii() and a.isupper())]
    if airlines:
        parts.append(" / ".join(airlines[:2]))
    return " · ".join(parts)


# ══════════════════════════════════════════════════════════════
#  内存缓存（进程级 TTL；DB 快照由 API 层负责持久化）
# ══════════════════════════════════════════════════════════════
_memory_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_memory_cache() -> None:
    """清空进程级缓存（测试用）。"""
    _memory_cache.clear()


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _memory_cache.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if time.time() >= expires_at:
        _memory_cache.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: dict[str, Any], *, ttl: int = CACHE_TTL_SECONDS) -> None:
    if len(_memory_cache) >= _MEMORY_CACHE_MAX:
        # 简单裁剪：先清过期项，仍超限则丢最早插入的
        now = time.time()
        for stale in [k for k, (exp, _) in _memory_cache.items() if exp <= now]:
            _memory_cache.pop(stale, None)
        while len(_memory_cache) >= _MEMORY_CACHE_MAX:
            _memory_cache.pop(next(iter(_memory_cache)), None)
    _memory_cache[key] = (time.time() + ttl, payload)


# ══════════════════════════════════════════════════════════════
#  促销信息（搜索结果摘要，不做价格断言）
# ══════════════════════════════════════════════════════════════
_PROMO_HINTS = ("特价", "促销", "优惠", "大促", "机票节", "低价", "折扣", "满减", "抢购", "sale", "deal", "promo")


def _build_promos(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从搜索结果里挑促销/活动页（带链接 + 摘要；不含价格断言）。"""
    promos: list[dict[str, Any]] = []
    for item in results or []:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if not url.startswith("http") or not title:
            continue
        if not source_domain_allowed(url):
            continue
        blob = f"{title}{content[:120]}".lower()
        if not any(hint.lower() in blob for hint in _PROMO_HINTS):
            continue
        if any(p["source_url"] == url for p in promos):
            continue
        promos.append(
            {
                "title": title[:120],
                "source_url": url,
                "snippet": content[:160],
                "source": _domain_label(url),
                "confidence": 0.6,
                "note": "活动摘要，价格以活动页为准",
            }
        )
        if len(promos) >= MAX_PROMOS:
            break
    return promos


def _route_from_offers(offers: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
    from_code = next((o.get("from_code") for o in offers if o.get("from_code")), None)
    to_code = next((o.get("to_code") for o in offers if o.get("to_code")), None)
    return {
        "from": (request.get("departure") or "").strip(),
        "to": (request.get("destination") or "").strip(),
        "from_code": from_code,
        "to_code": to_code,
    }


# ══════════════════════════════════════════════════════════════
#  组合入口
# ══════════════════════════════════════════════════════════════
async def collect_flight_deals(
    request: dict[str, Any],
    *,
    provider_name: str = "tavily",
    refresh: bool = False,
) -> dict[str, Any]:
    """采集并组装 ``plan.flight_deals``（永不抛异常，失败即降级）。

    返回契约见模块 docstring 与 ``PlanSchema.flight_deals``；``status``：
    - ``completed``：拿到 ≥1 条可用方案；
    - ``partial``：只有促销活动（无可靠报价）；
    - ``degraded``：采集失败/无结果；
    - ``skipped``：缺出发地或目的地。
    """
    departure = (request.get("departure") or "").strip()
    destination = (request.get("destination") or "").strip()
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    base: dict[str, Any] = {
        "route": {"from": departure, "to": destination, "from_code": None, "to_code": None},
        "fetched_at": fetched_at,
        "provider": provider_name,
        "status": "degraded",
        "price_kind": PRICE_KIND_FROM,
        "options": [],
        "promos": [],
        "note": NOTE_EMPTY,
        "is_cached": False,
    }
    if not departure or not destination:
        return {**base, "status": "skipped", "note": "未提供出发地或目的地，未查询机票"}

    key = route_key(request)
    if not refresh:
        cached = _cache_get(key)
        if cached is not None:
            return {**cached, "is_cached": True}

    try:
        provider = get_provider(provider_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("机票采集源不可用 provider=%s err=%s", provider_name, exc)
        return {**base, "note": f"机票采集源不可用：{exc}"}

    try:
        raw = await asyncio.wait_for(provider.collect(request), timeout=COLLECT_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.TimeoutError):
        logger.warning("机票采集超时 %s→%s", departure, destination)
        return {**base, "note": "机票采集超时，已降级"}
    except Exception as exc:  # noqa: BLE001 — 采集失败绝不阻断规划
        logger.warning("机票采集失败 %s→%s err=%s", departure, destination, exc)
        return {**base, "note": f"机票采集失败：{exc}"}

    pages: list[tuple[str, str]] = list(raw.get("pages") or [])
    search_results: list[dict[str, Any]] = list(raw.get("search") or [])
    anchor = _as_date(request.get("start_date"))

    candidates: list[dict[str, Any]] = []
    for page_url, text in pages:
        candidates.extend(parse_offers(text, page_url=page_url, anchor=anchor, request=request))
    gated = _gate_offers(candidates, request)
    options = rank_options(gated, request)
    promos = _build_promos(search_results)

    if options:
        status = "completed"
        note = NOTE_DEFAULT
    elif promos:
        status = "partial"
        note = "仅获取到促销活动信息，未获得可靠报价"
    else:
        status = "degraded"
        note = NOTE_EMPTY

    payload = {
        **base,
        "route": _route_from_offers(options or gated, request),
        "status": status,
        "options": options,
        "promos": promos,
        "note": note,
        "candidates": len(candidates),
        "gated": len(gated),
        "pages": [url for url, _ in pages][:5],
    }
    logger.info(
        "机票采集完成 %s→%s status=%s candidates=%d gated=%d options=%d promos=%d",
        departure, destination, status, len(candidates), len(gated), len(options), len(promos),
    )
    if options or promos:
        # 拿到可靠报价 → 长缓存；只有促销摘要 → 短缓存（避免一次抽取失败毒化 6h）
        _cache_put(
            key,
            payload,
            ttl=CACHE_TTL_SECONDS if options else PARTIAL_CACHE_TTL_SECONDS,
        )
    return payload


# ── 供 API 层复用的时间工具 ────────────────────────────────────
def is_stale(fetched_at: str | None, *, ttl: int = CACHE_TTL_SECONDS) -> bool:
    """快照是否过期（fetched_at 解析失败按过期处理）。"""
    parsed = None
    try:
        parsed = datetime.fromisoformat((fetched_at or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - parsed > timedelta(seconds=ttl)

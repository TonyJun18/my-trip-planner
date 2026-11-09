"""机票特价采集源：Tavily（搜索 + 航线页抽取）。

为什么是「搜索 + 抽取」而不是实时报价 API（2026-11-09 调研结论）：
- Amadeus Self-Service 门户已于 2026-07-17 关停（密钥失效，仅剩企业版）；
- Kiwi/Travelpayouts 等需注册/商务审批，接不通就无法交付；
- 实测 Tavily Search 2.4s 命中天巡航线页，Tavily Extract 1.3–3.8s 返回正文，
  正文里带**真实日期 + 价格 + 航司 + 原文链接**，足够支撑 2–3 个方案。

口径红线（本 provider 只负责拿素材，不做断言）：
- 只抓公开页面，不代订、不缓存全页、不声称库存；
- 页面正文原样交给 ``flight_deals_service.parse_offers`` 解析，价格一律标 ``from``；
- 英文站（skyscanner.com 等）为 SPA，Extract 常返回空 → 不重试、不编造，直接少一页。

未来接实时报价 API：实现同样的 ``collect()`` 契约并 ``register_provider()`` 即可，
解析/闸门/排序/缓存全部复用。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from app.core.logging import get_logger
from app.services.flight_deals_service import SOURCE_DOMAINS, source_domain_allowed

logger = get_logger(__name__)

# 航线页优先的特征（SEO 页正文含报价；SPA 搜索页抽不到内容）
_ROUTE_PAGE_HINTS = ("/routes/", "/transport/flights/", "/flights/", "/airlines/", "/tickets-")
_EXTRACT_TIMEOUT = 15.0
_SEARCH_RESULTS_PER_QUERY = 6
_MAX_PAGES = 3  # 并行抽取 3 页：单页失败仍有素材，延迟与 2 页基本相同
# 国家级落地页（/routes/hgh/cn/...）：有「目的地概览」但无具体报价
_COUNTRY_LEVEL_RE = re.compile(r"/routes/[a-z]{3}/[a-z]{2}/")
# 航线级页面（/routes/hgh/cctu/hangzhou-to-chengdu.html）
_ROUTE_SLUG_RE = re.compile(r"/routes/[a-z]{3}/[a-z]{3,4}/")


class TavilyFlightDealProvider:
    """Tavily 实现：两路搜索 → 挑航线页 → 并行抽取。"""

    name = "tavily"

    async def collect(self, request: dict[str, Any]) -> dict[str, Any]:
        """搜索 + 抽取素材；单个查询/页面失败只少一份素材，不整体失败。"""
        from app.agent import tools as agent_tools

        departure = (request.get("departure") or "").strip()
        destination = (request.get("destination") or "").strip()
        if not departure or not destination:
            return {"pages": [], "search": [], "provider": self.name}

        queries = [
            f"{departure}到{destination}特价机票 往返",
            f"{departure}飞{destination}机票 促销 优惠 大促",
        ]
        gathered = await asyncio.gather(
            *[agent_tools.tavily_search(q, max_results=_SEARCH_RESULTS_PER_QUERY) for q in queries],
            return_exceptions=True,
        )

        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in gathered:
            if isinstance(item, BaseException) or not isinstance(item, dict):
                logger.debug("机票搜索降级: %s", item)
                continue
            for row in item.get("results") or []:
                url = (row.get("url") or "").strip()
                if not url or url in seen_urls or not source_domain_allowed(url):
                    continue
                seen_urls.add(url)
                results.append(row)

        page_urls = self._pick_pages(results)
        if not page_urls:
            return {"pages": [], "search": results, "provider": self.name}

        # 用一次批量抽取（Tavily 支持 urls 数组）：请求数 3→3，但只有 1 次抽取 RTT，
        # 且单页失败不影响其他页（失败项进 failed_results）。
        pages: list[tuple[str, str]] = []
        try:
            data = await asyncio.wait_for(
                agent_tools.tavily_extract(page_urls, extract_depth="basic"),
                timeout=_EXTRACT_TIMEOUT,
            )
            for row in data.get("results") or []:
                url = (row.get("url") or "").strip()
                text = (row.get("raw_content") or "").strip()
                if url and len(text) >= 200:
                    pages.append((url, text))
        except Exception as exc:  # noqa: BLE001 — 抽取失败只少素材，promos 仍可用
            logger.debug("机票页面批量抽取降级 urls=%s err=%s", page_urls[:3], exc)

        # 一页都没抽到 → 对首选页补一次（Tavily 偶发慢/空响应，不重试会让卡片空一整天）
        if not pages:
            try:
                retry = await asyncio.wait_for(
                    agent_tools.tavily_extract(page_urls[:1], extract_depth="basic"),
                    timeout=_EXTRACT_TIMEOUT,
                )
                for row in retry.get("results") or []:
                    url = (row.get("url") or "").strip()
                    text = (row.get("raw_content") or "").strip()
                    if url and len(text) >= 200:
                        pages.append((url, text))
            except Exception as exc:  # noqa: BLE001
                logger.debug("机票页面重试抽取仍失败 err=%s", exc)
        return {"pages": pages, "search": results, "provider": self.name}

    def _pick_pages(self, results: list[dict[str, Any]]) -> list[str]:
        """优先「航线级」页面，最多 3 个（并行抽取控延迟）；同域名只取 1 个。

        评分启发式（实测踩坑）：
        - `/routes/<出发>/<目的>/` 这种两段三字码是航线页，正文含报价；
        - `/routes/<出发>/cn/hangzhou-to-china.html` 这类「第二段是国家码」的是国家级
          落地页，正文没有具体报价 → 降权；
        - tianxun / skyscanner 航线页是服务端渲染，Trip.com 等 SPA 抽不到内容 → 加权。
        """
        ranked: list[tuple[int, str]] = []
        for row in results:
            url = (row.get("url") or "").strip()
            if not source_domain_allowed(url):
                continue
            score = 0
            low = url.lower()
            if any(hint in low for hint in _ROUTE_PAGE_HINTS):
                score += 3
            if "tianxun.com" in low or "skyscanner" in low:
                score += 2
            if "trip.com" in low:
                score += 1
            # 国家级落地页降权：/routes/hgh/cn/
            if _COUNTRY_LEVEL_RE.search(low):
                score -= 3
            # 明确带「出发-到-目的地」的航线页加权
            if _ROUTE_SLUG_RE.search(low):
                score += 1
            ranked.append((-score, url))
        ranked.sort()
        picked: list[str] = []
        used_domains: set[str] = set()
        for _, url in ranked:
            domain = next((d for d in SOURCE_DOMAINS if d in url.lower()), url)
            if domain in used_domains:
                continue
            used_domains.add(domain)
            picked.append(url)
            if len(picked) >= _MAX_PAGES:
                break
        return picked

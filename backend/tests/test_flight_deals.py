"""机票特价采集（FlightDeals）测试：解析 / 硬闸门 / 排序 / 缓存 / provider 契约。

全部离线：用 ``tests/fixtures/`` 里真实抓取的天巡航线页正文（2026-11-09）做解析样本，
provider 用 fake 实现注入注册表，不打任何外部网络。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services import flight_deals_service as fds

FIXTURES = Path(__file__).parent / "fixtures"
DOMESTIC_URL = "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html"
INTL_URL = "https://www.tianxun.com/routes/hgh/tyoa/hangzhou-to-tokyo.html"


def _domestic_text() -> str:
    return (FIXTURES / "flight_tianxun_hgh_cctu.md").read_text()


def _intl_text() -> str:
    return (FIXTURES / "flight_tianxun_hgh_tyoa.md").read_text()


@pytest.fixture(autouse=True)
def _clear_cache():
    fds.clear_memory_cache()
    yield
    fds.clear_memory_cache()


# ── 解析：中文航线页报价块 ─────────────────────────────────────
class TestParseDomestic:
    def test_extracts_offers_with_dates_prices_airlines(self):
        offers = fds.parse_offers(
            _domestic_text(),
            page_url=DOMESTIC_URL,
            anchor=date(2026, 12, 8),
            request={"start_date": "2026-12-08"},
        )
        assert len(offers) >= 7
        first = min(offers, key=lambda o: o["price"])
        assert first["price"] == 1103.0
        assert first["currency"] == "CNY"
        assert first["price_kind"] == "from"
        assert first["source_url"] == DOMESTIC_URL
        assert first["source"] == "tianxun.com"
        assert first["outbound_date"] == "2026-12-10"
        assert first["inbound_date"] == "2026-12-17"
        assert first["stops"] == 0
        assert "北京首都航空" in first["airlines"]
        assert 0 < first["confidence"] <= 1

    def test_infers_cross_year_dates(self):
        """12月25日出发 / 1月14日返回：返回日期必须落到下一年，不能算成同年 1 月。"""
        offers = fds.parse_offers(
            _domestic_text(), page_url=DOMESTIC_URL, anchor=date(2026, 12, 8)
        )
        cross = [o for o in offers if o["outbound_date"] == "2026-12-25"]
        assert cross, "应解析出 12-25 出发的报价"
        assert cross[0]["inbound_date"] == "2027-01-14"

    def test_detects_non_direct(self):
        offers = fds.parse_offers(
            _domestic_text(), page_url=DOMESTIC_URL, anchor=date(2026, 12, 8)
        )
        assert any(o["stops"] and o["stops"] >= 1 for o in offers), "非直飞报价应被识别"


# ── 解析：国际航线页「最优惠航班」行 ───────────────────────────
class TestParseInternational:
    def test_parses_cheapest_row_with_codes_and_dates(self):
        offers = fds.parse_offers(
            _intl_text(),
            page_url=INTL_URL,
            anchor=date(2027, 3, 1),
            request={"start_date": "2027-03-01"},
        )
        assert len(offers) >= 1
        option = offers[0]
        assert option["price"] == 2149.0
        assert option["currency"] == "CNY"
        assert option["outbound_date"] == "2027-03-01"
        assert option["inbound_date"] == "2027-03-02"
        assert option["from_code"] == "HGH"
        assert option["to_code"] == "NRT"
        assert option["source_url"].startswith("https://www.tianxun.com/transport/flights/HGH/NRT/")
        assert "NH" in option["airlines"]

    def test_empty_text_returns_empty(self):
        assert fds.parse_offers("", page_url=DOMESTIC_URL) == []
        assert fds.parse_offers("no prices here", page_url=DOMESTIC_URL) == []


# ── 硬闸门 ────────────────────────────────────────────────────
class TestGate:
    def _request(self):
        return {"departure": "杭州", "destination": "成都", "start_date": "2026-12-08"}

    def test_drops_missing_source_price_currency_and_untrusted_domain(self):
        good = {
            "price": 900.0, "currency": "CNY", "price_kind": "from", "airlines": [],
            "outbound_date": "2026-12-10", "inbound_date": None, "stops": 0,
            "source": "skyscanner", "source_url": DOMESTIC_URL, "confidence": 0.8,
        }
        bad = [
            {**good, "source_url": ""},
            {**good, "price": 0},
            {**good, "currency": "XYZ"},
            {**good, "source_url": "https://evil.example.com/deal"},
            {**good, "confidence": 0.1},
        ]
        passed = fds._gate_offers([good, *bad], self._request())
        assert passed == [good]

    def test_far_off_dates_are_discounted_not_dropped(self):
        offer = {
            "price": 900.0, "currency": "CNY", "price_kind": "from", "airlines": [],
            "outbound_date": "2027-02-07", "inbound_date": None, "stops": 0,
            "source": "skyscanner", "source_url": DOMESTIC_URL, "confidence": 0.8,
        }
        passed = fds._gate_offers([offer], self._request())
        assert len(passed) == 1
        assert passed[0]["confidence"] < 0.8
        assert "偏离" in (passed[0]["note"] or "")

    def test_domain_whitelist_allows_known_sources_only(self):
        assert fds.source_domain_allowed("https://www.tianxun.com/routes/hgh/ctu/")
        assert fds.source_domain_allowed("https://www.trip.com/flights/x")
        assert fds.source_domain_allowed("https://www.csair.com/cn/")
        assert not fds.source_domain_allowed("https://random-blog.example.com/post")


# ── 排序：2–3 个方案位 ────────────────────────────────────────
class TestRankOptions:
    def _office(self, price, outbound, stops, airline="测试航空"):
        return {
            "price": price, "currency": "CNY", "price_kind": "from",
            "airlines": [airline], "outbound_date": outbound, "inbound_date": None,
            "stops": stops, "source": "skyscanner", "source_url": DOMESTIC_URL,
            "confidence": 0.8,
        }

    def test_three_distinct_strategies(self):
        offers = [
            self._office(1500, "2026-12-10", 1),
            self._office(1200, "2026-12-20", 2),
            self._office(1800, "2026-12-09", 0),
            self._office(2000, "2026-12-11", 1),
        ]
        ranked = fds.rank_options(offers, {"start_date": "2026-12-08"})
        assert len(ranked) == 3
        assert [o["strategy"] for o in ranked] == ["cheapest", "best_dates", "safest"]
        assert [o["option_id"] for o in ranked] == ["fd_1", "fd_2", "fd_3"]
        # 三个方案位不能指向同一条报价
        assert len({(o["price"], o["outbound_date"]) for o in ranked}) == 3
        assert ranked[0]["price"] == 1200
        # cheapest(1200) 与 best_dates(12-09) 已占位，safest 只能取剩下的直飞/少中转
        assert ranked[2]["stops"] == 1

    def test_safest_prefers_direct_when_unused(self):
        offers = [
            self._office(1500, "2026-12-10", 1),
            self._office(1200, "2026-12-20", 2),
            self._office(1800, "2026-12-19", 0),
        ]
        ranked = fds.rank_options(offers, {"start_date": "2026-12-08"})
        safest = next(o for o in ranked if o["strategy"] == "safest")
        assert safest["stops"] == 0 and safest["price"] == 1800

    def test_does_not_pad_with_fake_options(self):
        ranked = fds.rank_options([self._office(900, "2026-12-09", 0)], {"start_date": "2026-12-08"})
        assert len(ranked) == 1
        assert ranked[0]["option_id"] == "fd_1"

    def test_empty_input(self):
        assert fds.rank_options([], {"start_date": "2026-12-08"}) == []

    def test_title_skips_iata_codes(self):
        option = self._office(900, "2026-12-09", 0, airline="JD")
        option["inbound_date"] = "2026-12-15"
        ranked = fds.rank_options([option], {"start_date": "2026-12-08"})
        assert "JD" not in ranked[0]["title"]
        assert "¥900" in ranked[0]["title"]


# ── 采集编排 + 缓存 ───────────────────────────────────────────
class _FakeProvider:
    name = "fake"
    calls = 0

    async def collect(self, request):
        _FakeProvider.calls += 1
        return {
            "pages": [(DOMESTIC_URL, _domestic_text())],
            "search": [
                {
                    "title": "杭州到成都特价机票 大促",
                    "url": "https://www.csair.com/cn/promo",
                    "content": "冬季机票促销活动",
                }
            ],
            "provider": self.name,
        }


class TestCollect:
    async def test_collect_ranks_and_caches(self, monkeypatch):
        _FakeProvider.calls = 0
        monkeypatch.setitem(fds._PROVIDER_REGISTRY, "fake", _FakeProvider())
        request = {
            "departure": "杭州", "destination": "成都",
            "start_date": "2026-12-08", "end_date": "2026-12-15", "travelers": 2,
        }
        payload = await fds.collect_flight_deals(request, provider_name="fake")
        assert payload["status"] == "completed"
        assert 1 <= len(payload["options"]) <= 3
        assert payload["note"] == fds.NOTE_DEFAULT
        assert payload["is_cached"] is False
        assert payload["promos"] and payload["promos"][0]["source_url"].endswith("/promo")
        assert all(o["source_url"] for o in payload["options"])

        again = await fds.collect_flight_deals(request, provider_name="fake")
        assert again["is_cached"] is True
        assert _FakeProvider.calls == 1, "6h 内应命中内存缓存，不再打外部"

        forced = await fds.collect_flight_deals(request, provider_name="fake", refresh=True)
        assert forced["is_cached"] is False
        assert _FakeProvider.calls == 2

    async def test_missing_departure_is_skipped(self, monkeypatch):
        monkeypatch.setitem(fds._PROVIDER_REGISTRY, "fake", _FakeProvider())
        payload = await fds.collect_flight_deals(
            {"departure": "", "destination": "成都", "start_date": "2026-12-08"},
            provider_name="fake",
        )
        assert payload["status"] == "skipped"
        assert payload["options"] == []

    async def test_provider_failure_degrades(self, monkeypatch):
        class _Boom:
            name = "boom"

            async def collect(self, request):
                raise RuntimeError("network down")

        monkeypatch.setitem(fds._PROVIDER_REGISTRY, "boom", _Boom())
        payload = await fds.collect_flight_deals(
            {"departure": "杭州", "destination": "成都", "start_date": "2026-12-08"},
            provider_name="boom",
        )
        assert payload["status"] == "degraded"
        assert payload["options"] == []
        assert "失败" in payload["note"]

    async def test_untrusted_pages_produce_degraded(self, monkeypatch):
        class _Spam:
            name = "spam"

            async def collect(self, request):
                return {
                    "pages": [("https://blog.example.com/x", "每位乘客¥99。12月10日周四出发，12月17日周四返回。某航的往返航班。")],
                    "search": [],
                    "provider": "spam",
                }

        monkeypatch.setitem(fds._PROVIDER_REGISTRY, "spam", _Spam())
        payload = await fds.collect_flight_deals(
            {"departure": "杭州", "destination": "成都", "start_date": "2026-12-08"},
            provider_name="spam",
        )
        assert payload["options"] == []
        assert payload["status"] == "degraded"


# ── 采集源页面挑选（实测踩坑：国家级落地页无私家报价）────────
class TestPagePicking:
    def test_prefers_route_page_over_country_landing(self):
        from app.services.flight_deals_tavily import TavilyFlightDealProvider

        results = [
            {"url": "https://www.skyscanner.com.my/my/zh-cn/myr/routes/hgh/cn/hangzhou-to-china.html"},
            {"url": "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html"},
            {"url": "https://blog.example.com/hangzhou-chengdu"},
        ]
        picked = TavilyFlightDealProvider()._pick_pages(results)
        assert picked[0] == "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html"
        assert "blog.example.com" not in " ".join(picked)

    def test_caps_pages_at_three(self):
        from app.services.flight_deals_tavily import TavilyFlightDealProvider

        results = [
            {"url": "https://www.tianxun.com/routes/hgh/cctu/hangzhou-to-chengdu.html"},
            {"url": "https://www.skyscanner.net/transport/flights/hgh/ctu/"},
            {"url": "https://www.trip.com/flights/hangzhou-to-chengdu/tickets-hgh-ctu/"},
            {"url": "https://www.qunar.com/hgh-ctu"},
        ]
        assert len(TavilyFlightDealProvider()._pick_pages(results)) <= 3


# ── Agent 接入：无出发地跳过 / Planner 上下文注入 ─────────────
class TestAgentWiring:
    async def test_agent_skips_without_departure(self):
        from app.agent.agents import flight_deal_agent

        result = await flight_deal_agent(
            {"departure": "", "destination": "成都", "start_date": "2026-12-08"}
        )
        assert result["status"] == "skipped"
        assert result["flight_deals"] is None

    async def test_agent_degrades_on_service_failure(self, monkeypatch):
        from app.agent import agents
        from app.services import flight_deals_service

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(flight_deals_service, "collect_flight_deals", _boom)
        result = await agents.flight_deal_agent(
            {"departure": "杭州", "destination": "成都", "start_date": "2026-12-08"}
        )
        assert result["status"] == "degraded"
        assert result["flight_deals"] is None

    def test_planner_context_injects_flight_options_only_when_present(self):
        from app.agent.agents import _planner_user_text

        request = {
            "destination": "成都", "departure": "杭州",
            "start_date": "2026-12-08", "end_date": "2026-12-15",
            "travelers": 2, "preferences": [],
        }
        with_flights = _planner_user_text(
            request,
            {
                "attractions": [], "hotels": [], "foods": [], "weather": {},
                "transport": None, "discount_rules": [],
                "flight_deals": {"options": [{"option_id": "fd_1", "title": "往返 ¥1,103 起", "price": 1103}]},
            },
        )
        assert "机票特价方案" in with_flights
        assert "fd_1" in with_flights

        without = _planner_user_text(
            request,
            {"attractions": [], "hotels": [], "foods": [], "weather": {},
             "transport": None, "discount_rules": [], "flight_deals": None},
        )
        assert "机票特价方案" not in without


# ── 工具函数 ──────────────────────────────────────────────────
class TestHelpers:
    def test_infer_year_picks_nearest(self):
        assert fds.infer_year(12, 10, date(2026, 12, 8)) == 2026
        assert fds.infer_year(1, 14, date(2026, 12, 25)) == 2027
        assert fds.infer_year(11, 29, date(2026, 12, 8)) == 2026

    def test_route_key_is_stable_and_distinct(self):
        base = {"departure": "杭州", "destination": "成都", "start_date": "2026-12-08",
                "end_date": "2026-12-15", "travelers": 2}
        assert fds.route_key(base) == fds.route_key(dict(base))
        assert fds.route_key(base) != fds.route_key({**base, "travelers": 3})

    def test_is_stale(self):
        assert fds.is_stale(None) is True
        assert fds.is_stale("not-a-date") is True
        fresh = fds.datetime.now(fds.timezone.utc).isoformat()
        assert fds.is_stale(fresh) is False

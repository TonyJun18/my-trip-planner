"""新 Agent 专项测试：TransportAgent / DiscountAgent / 入住办理 / 折扣比价 / servicing。

覆盖方案 B（两段式）的新增能力，关键验收：
- TransportAgent：无出发地 → skipped；有出发地 → 过滤无来源/低置信条目（不编造）
- DiscountAgent：确定性规则库（学生/老年/儿童/军人/年卡/平台），零外部依赖
- 入住办理：模板基座 + LLM 失败兜底；不收集证件号码
- 折扣比价：无来源硬闸门（丢弃）；失败只保留规则区
- servicing：三子任务故障隔离（任一失败不影响其他）
"""
from __future__ import annotations

import json

import pytest

from app.services import discount_service, servicing_service
from app.services.checkin_service import generate_checkin_guide
from app.services.driving_service import leg_distance_km


# ── DiscountService（确定性规则库） ─────────────────────────
class TestDiscountRules:
    def test_general_rules_present(self):
        rules = discount_service.city_discount_rules(None)
        assert len(rules) >= 4  # 学生/老年/儿童/军人
        assert any("学生" in r["target"] for r in rules)
        assert all(r["confidence"] >= 0.8 for r in rules)
        assert all(r["category"] in ("attraction", "hotel", "transport", "general") for r in rules)

    def test_platform_rules_always_included(self):
        rules = discount_service.city_discount_rules("某地")
        assert any(r["target"] == "平台优惠" for r in rules)

    def test_city_pass_applied_for_beijing(self):
        rules = discount_service.city_discount_rules("北京")
        assert any("北京旅游年卡" in r["target"] for r in rules)

    def test_city_pass_applied_for_hangzhou(self):
        rules = discount_service.city_discount_rules("杭州")
        assert any("杭州西湖景区" in r["target"] for r in rules)

    def test_city_pass_not_for_unknown(self):
        rules = discount_service.city_discount_rules("未知城")
        assert not any("年卡" in r["target"] or "西湖" in r["target"] for r in rules)

    def test_rules_must_have_source_field(self):
        for r in discount_service.city_discount_rules("北京"):
            assert r.get("source") == "rule"
            assert "source_url" in r  # 键存在（可为 None）

    def test_discount_for_request_extracts_city(self):
        rules = discount_service.discount_rules_for_request({"destination": "杭州"})
        assert any("杭州西湖景区" in r["target"] for r in rules)

    def test_discount_for_request_missing_destination(self):
        rules = discount_service.discount_rules_for_request({})
        assert len(rules) >= 4  # 通用规则兜底


# ── 入住办理（模板 + LLM 兜底） ────────────────────────────
class TestCheckinGuide:
    async def test_template_fallback_without_llm(self, monkeypatch):
        """LLM 抛异常 → 纯模板兜底照常输出。"""
        plan = {"destination": "杭州", "hotels": [{"name": "西湖大酒店", "address": "西湖边"}]}

        async def _boom(*a, **k):
            raise RuntimeError("llm down")

        monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _boom)
        guide = await generate_checkin_guide(plan, provider="deepseek")
        assert guide["hotel_name"] == "西湖大酒店"
        assert guide["source"] == "template"
        assert guide["docs_required"]  # 有证件清单
        assert "身份证" in guide["docs_required"][0]
        assert guide["disclaimer"]  # 免责声明

    async def test_llm_output_used_when_valid(self, monkeypatch):
        """LLM 返回合法 JSON → 使用并强制带免责声明。"""
        plan = {"destination": "杭州", "hotels": [{"name": "西湖大酒店", "address": "西湖边"}]}

        class _FakeResp:
            content = json.dumps({
                "hotel_name": "西湖大酒店", "hotel_address": "西湖边",
                "check_in_time": "15:00 后", "check_out_time": "11:00 前",
                "docs_required": ["身份证"], "steps": ["step1"], "transit": ["打车"],
                "disclaimer": "",
            }, ensure_ascii=False)

        async def _fake(*a, **k):
            return _FakeResp()

        monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _fake)
        guide = await generate_checkin_guide(plan, provider="deepseek")
        assert guide["source"] == "llm"
        assert guide["check_in_time"] == "15:00 后"
        assert guide["disclaimer"]  # 强制覆盖

    async def test_no_hotel_uses_destination(self, monkeypatch):
        plan = {"destination": "成都"}
        guide = await generate_checkin_guide(plan)
        assert "成都" in guide["hotel_name"]
        assert guide["source"] == "template"

    def test_docs_do_not_contain_credential_numbers(self, monkeypatch):
        """隐私边界：指引不要求用户提供/填写证件号码，只说明携带什么。"""
        # 强制走模板（mock LLM 失败路径），保证测试确定性、无真实网络/模型调用
        async def _boom(*a, **k):
            raise RuntimeError("llm off")

        monkeypatch.setattr("app.agent.providers.invoke_with_resilience", _boom)
        plan = {"destination": "杭州", "hotels": [{"name": "X", "address": "Y"}]}
        import asyncio

        guide = asyncio.run(generate_checkin_guide(plan, provider="deepseek"))
        assert guide["source"] == "template"
        joined = " ".join(guide["docs_required"] + guide["steps"])
        # 不要求用户提供/输入敏感证件号码（模板不含该要求）
        assert "填写证件号" not in joined
        assert "输入证件号" not in joined
        assert "提供证件号" not in joined
        assert "上报证件号" not in joined


# ── 市内通勤视图（确定性） ─────────────────────────────────
class TestTransitView:
    def test_short_distance_walk(self):
        plan = {
            "destination": "杭州",
            "days": [{"day_number": 1, "stops": [
                {"name": "A", "lat": 30.0, "lng": 120.0},
                {"name": "B", "lat": 30.01, "lng": 120.01},  # ~1.5km
            ]}],
        }
        import asyncio

        view = asyncio.run(servicing_service.build_transit_view(plan))
        assert view["count"] == 1
        assert view["legs"][0]["mode"] in ("步行", "公共交通（地铁/公交）")

    def test_long_distance_car(self):
        plan = {
            "destination": "杭州",
            "days": [{"day_number": 1, "stops": [
                {"name": "A", "lat": 30.0, "lng": 120.0},
                {"name": "B", "lat": 30.5, "lng": 120.5},  # 远
            ]}],
        }
        import asyncio

        view = asyncio.run(servicing_service.build_transit_view(plan))
        assert view["legs"][0]["mode"] == "打车/自驾"

    def test_missing_coords_skipped(self):
        plan = {
            "destination": "杭州",
            "days": [{"day_number": 1, "stops": [
                {"name": "A", "lat": None, "lng": None},
                {"name": "B", "lat": 30.0, "lng": 120.0},
            ]}],
        }
        import asyncio

        view = asyncio.run(servicing_service.build_transit_view(plan))
        assert view["count"] == 0  # 缺坐标不编造


# ── 折扣比价（硬闸门） ─────────────────────────────────────
class TestDiscountsView:
    async def test_sources_required(self, monkeypatch):
        """无来源的搜索结果被丢弃（硬闸门）。"""
        async def _fake_tavily(query, *, max_results=5, search_depth="basic"):
            # 只有第一个带 url，其余不带 → 只产出 1 条
            return {"query": query, "count": 3, "results": [
                {"title": "西湖门票优惠", "url": "https://example.com/a"},
                {"title": "无来源条目", "url": ""},
                {"title": "也没有来源", "url": None},
            ]}

        monkeypatch.setattr("app.agent.tools.tavily_search", _fake_tavily)
        plan = {"destination": "杭州", "days": [{"day_number": 1, "stops": [
            {"name": "西湖", "type": "attraction", "estimated_cost": 100, "lat": 30.0, "lng": 120.0},
        ]}]}
        view = await servicing_service.build_discounts_view(plan, max_targets=5)
        assert view["count"] == 1
        assert view["items"][0]["source_url"] == "https://example.com/a"

    async def test_empty_targets_no_items(self):
        """无站点 → 无比价目标 → 空 items。"""
        plan = {"destination": "杭州", "days": [{"day_number": 1, "stops": []}]}
        view = await servicing_service.build_discounts_view(plan)
        assert view["count"] == 0
        assert view["items"] == []

    async def test_network_failure_graceful(self, monkeypatch):
        """Tavily 抛异常 → 不抛、返回空比价。"""

        async def _boom(*a, **k):
            raise RuntimeError("tavily down")

        monkeypatch.setattr("app.agent.tools.tavily_search", _boom)
        plan = {"destination": "杭州", "days": [{"day_number": 1, "stops": [
            {"name": "西湖", "type": "attraction", "estimated_cost": 100, "lat": 30.0, "lng": 120.0},
        ]}]}
        view = await servicing_service.build_discounts_view(plan)
        assert view["count"] == 0
        assert "暂未找到" in view["note"]

    def test_top_cost_targets_selected(self):
        """比价目标选取费用最高的站点。"""
        plan = {"destination": "杭州", "days": [{"day_number": 1, "stops": [
            {"name": "便宜点", "type": "attraction", "estimated_cost": 10, "lat": 30.0, "lng": 120.0},
            {"name": "贵点", "type": "attraction", "estimated_cost": 300, "lat": 30.1, "lng": 120.1},
            {"name": "最贵", "type": "attraction", "estimated_cost": 500, "lat": 30.2, "lng": 120.2},
        ]}]}
        # 用真实 view 验证目标选取逻辑（通过 _discount_search mock 拿目标名）
        async def _fake_tavily(query, *, max_results=5, search_depth="basic"):
            return {"query": query, "count": 0, "results": []}

        # 这里直接测试内部目标选择辅助（保持私有但可用）
        # 简化：直接调用 _discount_search 无法拿目标；用 build_discounts_view 的查询参数
        # 无法直接断言，因此改为验证「空结果时不会崩 + 无网络」
        import asyncio

        from app.services import servicing_service as svc

        async def _run():
            return await svc.build_discounts_view(plan, max_targets=2)

        async def _fake_tavily2(query, *, max_results=5, search_depth="basic"):
            return {"query": query, "count": 0, "results": []}

        # 打桩：验证查询里包含「贵点」（费用高者优先）
        seen = []
        async def _fake_tavily3(query, *, max_results=5, search_depth="basic"):
            seen.append(query)
            return {"query": query, "count": 0, "results": []}

        import app.agent.tools as atools
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(atools, "tavily_search", _fake_tavily3)
        try:
            asyncio.run(svc.build_discounts_view(plan, max_targets=2))
        finally:
            monkeypatch.undo()
        assert any("最贵" in q for q in seen)


# ── TransportAgent（不编造 + 硬闸门） ─────────────────────
class TestTransportAgent:
    async def test_skipped_without_departure(self):
        from app.agent.agents import transport_agent

        res = await transport_agent(None, "杭州")
        assert res["status"] == "skipped"
        assert res["transport"] is None

    async def test_skipped_with_empty_departure(self):
        from app.agent.agents import transport_agent

        res = await transport_agent("", "杭州")
        assert res["status"] == "skipped"

    async def test_filters_unverified_options(self, monkeypatch):
        """无 source_url / 低置信条目被硬闸门过滤。"""
        from app.agent import agents as agents_mod

        class _FakeResp:
            content = json.dumps({
                "from": "上海", "to": "杭州", "options": [
                    {"mode": "train", "source_url": "https://x", "confidence": 0.9,
                     "duration_minutes": 60, "price_range": [100, 200], "note": "高铁"},
                    {"mode": "flight", "source_url": "", "confidence": 0.3,
                     "duration_minutes": 90, "price_range": None, "note": "无来源"},
                ],
                "summary": "高铁",
            }, ensure_ascii=False)

        class _FakeLLM:
            _llm_type = "fake"

            def bind_tools(self, tools, **kwargs):
                return self

            async def ainvoke(self, messages):
                return _FakeResp()

        class _FakeProv:
            name = "deepseek"
            model_id = "fake"

            def get_chat_model(self, temperature=0.2):
                return _FakeLLM()

        from app.agent import providers as providers_mod

        providers_mod.PROVIDER_REGISTRY["deepseek"] = _FakeProv()  # type: ignore[assignment]
        try:
            # 关键：工具执行也 mock（search_transport 真实网络）
            async def _fake_search_transport(departure, destination, **kw):
                return {"from": departure, "to": destination, "options": [], "count": 0,
                        "status": "completed"}

            monkeypatch.setattr(agents_mod.agent_tools, "search_transport", _fake_search_transport)
            res = await agents_mod.transport_agent("上海", "杭州", provider="deepseek")
        finally:
            providers_mod.PROVIDER_REGISTRY.pop("deepseek", None)

        assert res["status"] == "completed"
        assert res["transport"]["count"] == 1  # 只剩有来源那条
        assert res["transport"]["options"][0]["source_url"] == "https://x"

    async def test_llm_no_tool_call_fails(self, monkeypatch):
        from app.agent import agents as agents_mod

        class _FakeResp:
            content = "我不需要工具，直接给结论"

        class _FakeLLM:
            _llm_type = "fake"

            def bind_tools(self, tools, **kwargs):
                return self

            async def ainvoke(self, messages):
                return _FakeResp()

        class _FakeProv:
            name = "deepseek"
            model_id = "fake"

            def get_chat_model(self, temperature=0.2):
                return _FakeLLM()

        from app.agent import providers as providers_mod

        providers_mod.PROVIDER_REGISTRY["deepseek"] = _FakeProv()  # type: ignore[assignment]
        try:
            res = await agents_mod.transport_agent("上海", "杭州", provider="deepseek")
        finally:
            providers_mod.PROVIDER_REGISTRY.pop("deepseek", None)
        assert res["status"] == "failed"


# ── run_servicing 故障隔离 ─────────────────────────────────
class TestServicingIsolation:
    async def test_one_failure_does_not_block_others(self, monkeypatch):
        """折扣比价抛错 → 市内通勤与入住指引仍生成，warnings 记录。"""
        plan = {"destination": "杭州", "hotels": [{"name": "西湖大酒店", "address": "西湖边"}],
                "days": [{"day_number": 1, "stops": [
                    {"name": "西湖", "lat": 30.0, "lng": 120.0},
                    {"name": "岳庙", "lat": 30.25, "lng": 120.13},
                ]}]}

        async def _boom(*a, **k):
            raise RuntimeError("tavily down")

        monkeypatch.setattr("app.agent.tools.tavily_search", _boom)
        result = await servicing_service.run_servicing(plan, provider="deepseek")
        assert result["transit"] is not None
        assert result["checkin"] is not None
        # 折扣比价优雅降级：不抛异常、不产生 warning，返回空 items + 说明
        assert result["discounts"] is not None
        assert result["discounts"]["items"] == []
        assert result["discounts"]["count"] == 0

    async def test_checkin_failure_isolated(self, monkeypatch):
        """入住指引生成抛错 → 其他两项不受影响。"""
        plan = {"destination": "杭州", "hotels": [{"name": "X", "address": "Y"}],
                "days": [{"day_number": 1, "stops": [
                    {"name": "A", "lat": 30.0, "lng": 120.0},
                    {"name": "B", "lat": 30.1, "lng": 120.1},
                ]}]}

        async def _boom(*a, **k):
            raise RuntimeError("checkin down")

        monkeypatch.setattr(
            "app.services.servicing_service.generate_checkin_guide", _boom,
        )
        result = await servicing_service.run_servicing(plan)
        assert result["transit"] is not None
        assert result["checkin"] is None
        assert any("入住" in w for w in result["warnings"])


# ── 数据工具（价格/班次启发式） ────────────────────────────
class TestHelpers:
    def test_extract_price_range(self):
        from app.agent.tools import _extract_price_range

        assert _extract_price_range("票价 ¥150，往返 300 元") == [150.0, 300.0]
        assert _extract_price_range("没有价格") is None

    def test_extract_price_range_rejects_outliers(self):
        from app.agent.tools import _extract_price_range

        # 区间过宽视为噪声
        assert _extract_price_range("¥99 和 ¥50000 的套餐") is None

    def test_extract_frequency(self):
        from app.agent.tools import _extract_frequency

        assert _extract_frequency("高铁 每30分钟一班", "") == "每30分钟一班"
        assert _extract_frequency("随便什么", "每日 3 班") == "每日 3 班"
        assert _extract_frequency("无信息", "") is None


# ── leg_distance_km 复用（供 inbound 通勤） ────────────────
class TestLegDistance:
    def test_valid_coords(self):
        d = leg_distance_km({"lat": 30.0, "lng": 120.0}, {"lat": 30.01, "lng": 120.01})
        assert d is not None and d > 0

    def test_missing_coords_none(self):
        assert leg_distance_km({"lat": None, "lng": None}, {"lat": 30.0, "lng": 120.0}) is None
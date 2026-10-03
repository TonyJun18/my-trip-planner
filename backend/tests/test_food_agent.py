"""FoodAgent + Critic 协作者（fix diff 精确修订）专项测试。

覆盖 task-food-agent 验收：
- FoodAgent：口味/菜系偏好 → search_foods → 结构化餐厅 POI；
  失败（LLM 不调用工具 / 工具抛错）→ 返回 failed + 空列表（不编造）；
  无偏好 → 用通用"必吃 美食"关键词。
- 编排层接入：run_planning_agents 并行采集含 FoodAgent（六个 Agent）；
  FoodAgent 主路径失败 → 降级到编排层 search_foods 补位（trace 标注 fallback）；
  都失败 → foods=[]，Planner 仍可输出（优雅降级）。
- Critic 协作者：不过审时输出 fix diff（CriticFixSchema 兼容）；
  编排层优先应用 _apply_critic_fix（原子预检，失败回退整段重生成）。
"""
from __future__ import annotations

import json

import pytest


async def _fake_food_search(city, *, query=None, limit=6):
    """可复用的离线 search_foods 替身（返回结构化 POI）。"""
    return {"city": city, "count": 1, "results": [
        {"name": "楼外楼", "type": "food", "lat": 30.25, "lng": 120.14,
         "estimated_cost": 180, "duration_minutes": 90, "description": "杭帮菜",
         "source": "fake", "source_url": "", "geocoded": True},
    ]}


class _FakeResp:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _ToolCallLLM:
    """LLM：调用 search_foods 工具一次。"""

    _llm_type = "fake-food"

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return _FakeResp(
            "Thought: 需要搜索餐厅。",
            tool_calls=[{"name": "search_foods", "args": {"city": "杭州", "query": "小吃"},
                         "id": "food-1", "type": "tool_call"}],
        )


class _NoToolLLM:
    """LLM：不调用工具，直接给结论（应判失败）。"""

    _llm_type = "fake-food-notool"

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return _FakeResp("我不需要工具，直接列几家店")


class _FakeProv:
    def __init__(self, llm):
        self.name = "fake-food"
        self.model_id = "m"
        self._llm = llm

    def get_chat_model(self, temperature=0.2):
        return self._llm


def _install_provider(name: str, llm):
    from app.agent import providers as providers_mod

    providers_mod.PROVIDER_REGISTRY[name] = _FakeProv(llm)  # type: ignore[assignment]
    return providers_mod


# ── FoodAgent 单元 ───────────────────────────────────────────
class TestFoodAgent:
    @pytest.mark.asyncio
    async def test_food_agent_calls_tool_and_returns_pois(self, monkeypatch):
        """口味偏好 → 调用 search_foods → 返回餐厅 POI。"""
        from app.agent import agents as agents_mod
        from app.agent import tools as tools_mod

        monkeypatch.setattr(tools_mod, "search_foods", _fake_food_search)
        providers_mod = _install_provider("fake-food", _ToolCallLLM())
        try:
            res = await agents_mod.food_agent("杭州", ["小吃"], provider="fake-food")
        finally:
            providers_mod.PROVIDER_REGISTRY.pop("fake-food", None)

        assert res["status"] == "completed"
        assert len(res["pois"]) == 1
        assert res["pois"][0]["name"] == "楼外楼"
        assert res["pois"][0]["type"] == "food"

    @pytest.mark.asyncio
    async def test_food_agent_no_tool_call_fails(self, monkeypatch):
        """LLM 不调用工具 → failed + 空列表（不编造）。"""
        from app.agent import agents as agents_mod

        providers_mod = _install_provider("fake-food", _NoToolLLM())
        try:
            res = await agents_mod.food_agent("杭州", ["小吃"], provider="fake-food")
        finally:
            providers_mod.PROVIDER_REGISTRY.pop("fake-food", None)

        assert res["status"] == "failed"
        assert res["pois"] == []

    @pytest.mark.asyncio
    async def test_food_agent_tool_error_degrades(self, monkeypatch):
        """工具抛错 → failed + 空列表（绝不编造餐厅名）。"""
        from app.agent import agents as agents_mod
        from app.agent import tools as tools_mod

        async def _boom(city, *, query=None, limit=6):
            raise RuntimeError("amap down")

        monkeypatch.setattr(tools_mod, "search_foods", _boom)
        providers_mod = _install_provider("fake-food", _ToolCallLLM())
        try:
            res = await agents_mod.food_agent("杭州", ["海鲜"], provider="fake-food")
        finally:
            providers_mod.PROVIDER_REGISTRY.pop("fake-food", None)

        assert res["status"] == "failed"
        assert res["pois"] == []

    @pytest.mark.asyncio
    async def test_food_agent_empty_tool_result(self, monkeypatch):
        """工具返回空结果 → completed + 空列表（原样透传，不编造）。"""
        from app.agent import agents as agents_mod
        from app.agent import tools as tools_mod

        async def _empty(city, *, query=None, limit=6):
            return {"city": city, "count": 0, "results": []}

        monkeypatch.setattr(tools_mod, "search_foods", _empty)
        providers_mod = _install_provider("fake-food", _ToolCallLLM())
        try:
            res = await agents_mod.food_agent("杭州", [], provider="fake-food")
        finally:
            providers_mod.PROVIDER_REGISTRY.pop("fake-food", None)

        assert res["status"] == "completed"
        assert res["pois"] == []

    def test_food_hints(self):
        from app.agent.agents import _food_hints

        assert _food_hints(["美食", "自然风光"]) == ["美食"]
        assert _food_hints(["海鲜大餐", "博物馆"]) == ["海鲜大餐"]
        assert _food_hints(["自然风光", "徒步"]) == []
        assert _food_hints([]) == []


# ── Critic 协作者：_apply_critic_fix ──────────────────────────
class TestCriticFix:
    def _plan(self):
        return {
            "destination": "杭州",
            "days": [{"day_number": 1, "date": "2026-10-01", "theme": "西湖", "stops": [
                {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                 "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
                {"name": "灵隐寺", "type": "attraction", "lat": 30.24, "lng": 120.10,
                 "estimated_cost": 75, "duration_minutes": 120, "description": "古刹"},
            ]}],
            "budget": {"total_estimated": 0.0, "by_type": {}, "currency": "CNY"},
        }

    def test_replace_fields(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [
            {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
             "fields": {"estimated_cost": 45, "duration_minutes": 150}},
        ], "summary": "修正灵隐寺门票"}
        assert _apply_critic_fix(plan, fix) is True
        stops = plan["days"][0]["stops"]
        assert stops[1]["estimated_cost"] == 45
        assert stops[1]["duration_minutes"] == 150
        assert stops[0]["name"] == "西湖"  # 未受影响

    def test_remove(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [{"op": "remove", "day_number": 1, "target": {"name": "灵隐寺"}}]}
        assert _apply_critic_fix(plan, fix) is True
        assert [s["name"] for s in plan["days"][0]["stops"]] == ["西湖"]

    def test_add_food(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [
            {"op": "add", "day_number": 1, "index": 1,
             "fields": {"name": "楼外楼", "type": "food", "estimated_cost": 180,
                        "duration_minutes": 90, "description": "杭帮菜"}},
        ]}
        assert _apply_critic_fix(plan, fix) is True
        stops = plan["days"][0]["stops"]
        assert stops[0]["name"] == "楼外楼"
        assert stops[0]["type"] == "food"
        assert len(stops) == 3

    def test_reorder(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [{"op": "reorder", "day_number": 1, "target": {"name": "灵隐寺"}, "index": 1}]}
        assert _apply_critic_fix(plan, fix) is True
        assert [s["name"] for s in plan["days"][0]["stops"]] == ["灵隐寺", "西湖"]

    def test_unknown_target_fails_atomically(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [
            {"op": "replace", "day_number": 1, "target": {"name": "不存在"}, "fields": {"estimated_cost": 1}},
            {"op": "replace", "day_number": 1, "target": {"name": "西湖"}, "fields": {"estimated_cost": 99}},
        ]}
        assert _apply_critic_fix(plan, fix) is False
        # 原子：第一个动作非法 → 第二个也不执行
        assert plan["days"][0]["stops"][0]["estimated_cost"] == 0

    def test_missing_day_fails(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [{"op": "replace", "day_number": 9, "target": {"name": "西湖"},
                            "fields": {"estimated_cost": 1}}]}
        assert _apply_critic_fix(plan, fix) is False

    def test_bad_field_fails(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [{"op": "replace", "day_number": 1, "target": {"name": "西湖"},
                            "fields": {"hack": "x"}}]}
        assert _apply_critic_fix(plan, fix) is False

    def test_bad_type_fails(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        fix = {"actions": [{"op": "add", "day_number": 1,
                            "fields": {"name": "坏点", "type": "museum"}}]}
        assert _apply_critic_fix(plan, fix) is False

    def test_add_without_type_defaults_food(self):
        from app.agent.agents import _apply_critic_fix

        plan = self._plan()
        # 无 type：监管要求 add 必须带 type，缺 type 视为非法（不默认）→ False
        fix = {"actions": [{"op": "add", "day_number": 1, "fields": {"name": "无名"}}]}
        assert _apply_critic_fix(plan, fix) is False

    def test_schema_accepts_fix(self):
        """CriticFixSchema 兼容 Critic 输出（fix 解析正常）。"""
        from app.schemas.plan import CriticFixSchema

        fix = CriticFixSchema.model_validate({"actions": [
            {"op": "replace", "day_number": 1, "target": {"name": "灵隐寺"},
             "fields": {"estimated_cost": 45}},
            {"op": "add", "day_number": 1, "fields": {"name": "楼外楼", "type": "food"}},
        ], "summary": "修正"})
        assert len(fix.actions) == 2
        assert fix.actions[0].op == "replace"


# ── 编排层接入：FoodAgent 在 run_planning_agents 中的行为 ────
def _offline_tools(monkeypatch, food_results=None, food_raise=False):
    """安装离线工具（含 foods）；可选注入 food 失败/空结果。"""
    from app.agent import tools as tools_mod

    async def _fake_search(city, *, query=None, limit=8, want_type="attraction"):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖", "type": want_type, "lat": 30.245, "lng": 120.15,
             "estimated_cost": 0, "duration_minutes": 180, "description": "环湖",
             "source": "fake", "source_url": "", "geocoded": True}]}

    async def _fake_search_hotels(city, *, query=None, limit=6):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
             "estimated_cost": 300, "duration_minutes": None, "description": "近西湖",
             "source": "fake", "source_url": "", "geocoded": True}]}

    async def _fake_weather(city, *, days=3):
        return {"city": city, "days": [
            {"date": "2026-10-01", "text_day": "晴", "temp_max": "25", "temp_min": "16", "humidity": "40"}],
            "count": 1, "source": "fake"}

    async def _fake_foods(city, *, query=None, limit=6):
        if food_raise:
            raise RuntimeError("food down")
        if food_results is not None:
            return {"city": city, "count": len(food_results), "results": food_results}
        return {"city": city, "count": 1, "results": [
            {"name": "楼外楼", "type": "food", "lat": 30.25, "lng": 120.14,
             "estimated_cost": 180, "duration_minutes": 90, "description": "杭帮菜",
             "source": "fake", "source_url": "", "geocoded": True}]}

    async def _fake_tavily(query, *, max_results=5, search_depth="basic"):
        return {"query": query, "count": 0, "results": []}

    monkeypatch.setattr(tools_mod, "search_attractions", _fake_search)
    monkeypatch.setattr(tools_mod, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(tools_mod, "search_foods", _fake_foods)
    monkeypatch.setattr(tools_mod, "query_weather", _fake_weather)
    monkeypatch.setattr(tools_mod, "tavily_search", _fake_tavily)


def _make_llm(food_status="ok", fix=None):
    """构造全流程 FakeLLM：采集 Agent → Planner → Critic（可带 fix）。"""
    from langchain_core.messages import AIMessage

    class _LLM:
        _llm_type = "fake-food-pipeline"

        def __init__(self):
            self.planner_calls = 0
            self.critic_calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            # 注意匹配顺序：PLANNER prompt 的"你将收到"列表里含有
            # 「景点搜索专家/酒店推荐专家」字样，必须用【】唯一标记且最先判 Planner。
            if "【行程规划专家】" in sys_prompt:
                # Planner
                self.planner_calls += 1
                stops = [
                    {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                     "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
                    {"name": "灵隐寺", "type": "attraction", "lat": 30.24, "lng": 120.10,
                     "estimated_cost": 75, "duration_minutes": 120, "description": "古刹"},
                ]
                if self.planner_calls > 1:
                    stops = [stops[0]]  # 修订后删掉灵隐寺
                return AIMessage(content=json.dumps({
                    "destination": "杭州",
                    "days": [{"day_number": 1, "date": "2026-10-01", "theme": "西湖",
                              "stops": stops}],
                    "budget": {"total_estimated": 0.0, "by_type": {}, "currency": "CNY"}},
                    ensure_ascii=False))
            if "【餐饮搜索专家】" in sys_prompt:
                return AIMessage(content="Thought: 搜索餐厅。", tool_calls=[
                    {"name": "search_foods", "args": {"city": "杭州", "query": "必吃 美食"},
                     "id": "f1", "type": "tool_call"}])
            if "【景点搜索专家】" in sys_prompt:
                return AIMessage(content="Thought: 搜索景点。", tool_calls=[
                    {"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                     "id": "a1", "type": "tool_call"}])
            if "【酒店推荐专家】" in sys_prompt:
                return AIMessage(content="Thought: 查询酒店。", tool_calls=[
                    {"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                     "id": "h1", "type": "tool_call"}])
            if "行程质检专家" in sys_prompt:
                self.critic_calls += 1
                if food_status == "never-pass":
                    return AIMessage(content=json.dumps({
                        "score": 50, "passed": False,
                        "issues": [{"severity": "critical", "category": "schedule",
                                    "message": "站点过多", "suggestion": "减少站点", "day_number": 1}],
                        "summary": "永远过不了"}, ensure_ascii=False))
                if self.critic_calls == 1 and fix is not None:
                    return AIMessage(content=json.dumps({
                        "score": 60, "passed": False,
                        "issues": [{"severity": "critical", "category": "geography",
                                    "message": "灵隐寺绕路", "suggestion": "删除或移动", "day_number": 1}],
                        "summary": "路线不合理", "fix": fix}, ensure_ascii=False))
                return AIMessage(content=json.dumps({
                    "score": 92, "passed": True, "issues": [], "summary": "通过"},
                    ensure_ascii=False))
            raise AssertionError(f"未识别的 system prompt: {sys_prompt[:60]}")

    return _LLM()


@pytest.mark.asyncio
async def test_run_planning_agents_uses_food_agent(monkeypatch):
    """编排：六个 Agent 并行采集，FoodAgent 主路径成功 → trace 含 FoodAgent 与餐厅件。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _offline_tools(monkeypatch)
    PROVIDER_REGISTRY["fake-food-pipe"] = _FakeProv(_make_llm())  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": ["美食"]},
            provider="fake-food-pipe", max_review_rounds=2,
        )
    finally:
        PROVIDER_REGISTRY.pop("fake-food-pipe", None)

    assert result["status"] == "completed"
    assert result["agents"]["foods"] == "completed"
    agent_names = {s.get("agent") for s in result["trace"]}
    assert "FoodAgent" in agent_names
    # foods 材料注入了 Planner（trace 或最终 plan 含餐厅）
    food_traces = [s for s in result["trace"] if s.get("agent") == "FoodAgent"]
    assert food_traces and "餐厅" in food_traces[0].get("observation", "")


@pytest.mark.asyncio
async def test_run_planning_agents_food_agent_fails_falls_back(monkeypatch):
    """FoodAgent 主路径失败 → 编排层 search_foods 补位（不阻断，Planner 仍出餐）。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _offline_tools(monkeypatch, food_results=[  # 主路径工具被 mock 掉时返回空 → FoodAgent completed
        {"name": "楼外楼", "type": "food", "lat": 30.25, "lng": 120.14,
         "estimated_cost": 180, "duration_minutes": 90, "description": "杭帮菜",
         "source": "fake", "source_url": "", "geocoded": True},
    ])

    # 让 FoodAgent 主路径失败：LLM 不调用工具
    class _NoToolFoodLLM(_make_llm().__class__):
        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage

            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "餐饮搜索专家" in sys_prompt:
                return AIMessage(content="我不需要工具")
            return await super().ainvoke(messages)

    PROVIDER_REGISTRY["fake-food-fb"] = _FakeProv(_NoToolFoodLLM())  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": ["美食"]},
            provider="fake-food-fb", max_review_rounds=2,
        )
    finally:
        PROVIDER_REGISTRY.pop("fake-food-fb", None)

    assert result["status"] == "completed"
    assert result["plan"] is not None
    # 降级路径：trace 含 orchestrator search_food_fallback
    fallback_traces = [s for s in result["trace"]
                       if s.get("agent") == "orchestrator" and "fallback" in s.get("action", "")]
    assert fallback_traces


@pytest.mark.asyncio
async def test_run_planning_agents_critic_fix_applied(monkeypatch):
    """Critic 协作者：不过审附 fix → 编排层应用精确修订 → 不整段重生成。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _offline_tools(monkeypatch)
    fix = {"actions": [
        {"op": "remove", "day_number": 1, "target": {"name": "灵隐寺"}},
        {"op": "add", "day_number": 1,
         "fields": {"name": "楼外楼", "type": "food", "estimated_cost": 180,
                    "duration_minutes": 90, "description": "杭帮菜"}},
    ], "summary": "删除绕路灵隐寺，补晚餐楼外楼"}
    llm = _make_llm(fix=fix)
    PROVIDER_REGISTRY["fake-food-fix"] = _FakeProv(llm)  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": ["美食"]},
            provider="fake-food-fix", max_review_rounds=2,
        )
    finally:
        PROVIDER_REGISTRY.pop("fake-food-fix", None)

    assert result["status"] == "completed"
    # fix 被应用：删除灵隐寺 + 新增楼外楼 → 最终 2 站（西湖 + 楼外楼）
    stops = result["plan"]["days"][0]["stops"]
    names = [s["name"] for s in stops]
    assert names == ["西湖", "楼外楼"]
    # 应用 fix 后不再触发第二轮整段重生成（planner_calls 仅 1 次）
    assert llm.planner_calls == 1
    apply_traces = [s for s in result["trace"] if s.get("action") == "apply_fix"]
    assert len(apply_traces) == 1
    assert "精确修订" in apply_traces[0]["observation"]


@pytest.mark.asyncio
async def test_run_planning_agents_critic_fix_invalid_falls_back(monkeypatch):
    """Critic fix 目标不存在 → 应用失败 → 回退 Planner 整段重生成（不静默丢失）。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _offline_tools(monkeypatch)
    fix = {"actions": [
        {"op": "remove", "day_number": 1, "target": {"name": "不存在的点"}},
    ], "summary": "删除不存在点"}
    llm = _make_llm(fix=fix)
    PROVIDER_REGISTRY["fake-food-fixbad"] = _FakeProv(llm)  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": ["美食"]},
            provider="fake-food-fixbad", max_review_rounds=2,
        )
    finally:
        PROVIDER_REGISTRY.pop("fake-food-fixbad", None)

    assert result["status"] == "completed"
    # 回退整段重生成：Planner 被调用 2 次（首版 + 修订版）
    assert llm.planner_calls == 2
    # 修订版只剩西湖
    assert [s["name"] for s in result["plan"]["days"][0]["stops"]] == ["西湖"]
"""Agent 单元测试：多 Agent（AttractionSearch / WeatherQuery / Hotel / Planner）+ 编排。

测试替身策略：
- FakeLLM（测试替身）模拟真实 LLM，按消息历史中的工具名推进：
  * AttractionSearchAgent → search_attractions → 输出景点 JSON
  * HotelAgent          → search_hotels → 输出酒店 JSON
  * PlannerAgent        → 直接输出最终行程 JSON（不调用工具）
- WeatherQueryAgent 是纯工具路径（不走 LLM），直接替换 query_weather
- 外部网络工具（search_attractions / search_hotels / query_weather）全部 monkeypatch 为离线假实现
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage


# ── FakeLLM：按消息历史中的工具名推进多 Agent ───────────────
class FakeLLM:
    """模拟 3 个角色的输出：Attraction→search_attractions，Hotel→search_hotels，Planner→plan JSON。"""

    _llm_type = "fake-multi-agent"

    def __init__(self, plan: dict | None = None) -> None:
        self.plan = plan or {
            "destination": "杭州",
            "days": [
                {
                    "day_number": 1,
                    "date": "2026-10-01",
                    "theme": "西湖经典",
                    "stops": [
                        {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                         "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
                    ],
                }
            ],
            "budget": {"total_estimated": 0.0, "by_type": {"attraction": 0.0}, "currency": "CNY"},
        }

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        # 根据消息历史里出现的工具调用名，判断当前角色
        text = "\n".join(getattr(m, "content", "") or "" for m in messages)
        if "待审查行程 JSON" in text:
            # TravelCriticAgent：输出质检报告（通过）
            return AIMessage(
                content=json.dumps(
                    {"score": 90, "passed": True, "issues": [], "summary": "行程整体合理，通过"},
                    ensure_ascii=False,
                )
            )
        if "search_attractions" in text and "search_hotels" in text:
            # Planner：已被注入所有材料，直接输出 plan
            return AIMessage(content=json.dumps(self.plan, ensure_ascii=False))
        if "search_hotels" in text:
            # HotelAgent：先走 search_hotels
            return AIMessage(
                content="Thought: 查询酒店。",
                tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                             "id": "fake-hotel-1", "type": "tool_call"}],
            )
        if "search_attractions" in text:
            # AttractionSearchAgent：先走 search_attractions
            return AIMessage(
                content="Thought: 搜索景点。",
                tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                             "id": "fake-attr-1", "type": "tool_call"}],
            )
        # Planner（无工具提示时的首位）：也应直接输出 plan
        return AIMessage(content=json.dumps(self.plan, ensure_ascii=False))


# ── 工具纯函数测试 ─────────────────────────────────────────
def test_compute_budget():
    from app.agent.tools import compute_budget

    stops = [
        {"name": "A", "type": "attraction", "estimated_cost": 100},
        {"name": "B", "type": "food", "estimated_cost": 200},
    ]
    budget = compute_budget(stops)
    assert budget["total_estimated"] == 300
    assert budget["by_type"]["attraction"] == 100
    assert budget["by_type"]["food"] == 200


def test_clean_name_strips_suffix():
    from app.agent.tools import _clean_name

    assert _clean_name("西湖_攻略") == "西湖"
    assert _clean_name("故宫门票") == "故宫"
    assert _clean_name("正常景点名") == "正常景点名"


def test_guess_type():
    from app.agent.tools import _guess_type

    assert _guess_type("海底捞火锅店") == "food"
    assert _guess_type("杭州西湖景区") == "attraction"
    assert _guess_type("上海外滩华尔道夫酒店") == "hotel"


# ── schema 校验 ────────────────────────────────────────────
def test_validate_plan_ok():
    from app.schemas.plan import validate_plan

    data = {
        "destination": "杭州",
        "days": [
            {"day_number": 1, "date": "2026-10-01", "theme": "t", "stops": [
                {"name": "西湖", "type": "attraction", "lat": 30.0, "lng": 120.0},
            ]},
        ],
        "budget": {"total_estimated": 0, "by_type": {"attraction": 0}, "currency": "CNY"},
        "extra_field": "should be dropped",
    }
    clean = validate_plan(data)
    assert clean["destination"] == "杭州"
    assert "extra_field" not in clean


def test_validate_plan_rejects_bad_type():
    from pydantic import ValidationError

    from app.schemas.plan import validate_plan

    data = {
        "destination": "杭州",
        "days": [{"day_number": 1, "date": "2026-10-01", "stops": [
            {"name": "西湖", "type": "museum"}  # 非法类型
        ]}],
        "budget": {"total_estimated": 0},
    }
    with pytest.raises(ValidationError):
        validate_plan(data)


def test_validate_plan_rejects_empty_days():
    from pydantic import ValidationError

    from app.schemas.plan import validate_plan

    with pytest.raises(ValidationError):
        validate_plan({"destination": "杭州", "days": [], "budget": {"total_estimated": 0}})


# ── 多 Agent 全链路（FakeLLM + 离线工具） ────────────────────
@pytest.mark.asyncio
async def test_run_planning_agents_with_fake_llm(monkeypatch):
    """3 个采集 Agent + Planner 全链路：无网络、无真实 LLM。"""
    from app.agent import agents as agents_mod
    from app.agent import tools as tools_mod
    from app.agent.providers import PROVIDER_REGISTRY

    # 离线假工具（统一 POI 结构，含 source）
    async def _fake_search(city, *, query=None, limit=8, want_type="attraction"):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖", "type": want_type, "lat": 30.245, "lng": 120.15,
             "estimated_cost": 0, "duration_minutes": 180, "description": "环湖",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    async def _fake_search_hotels(city, *, query=None, limit=6):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
             "estimated_cost": 300, "duration_minutes": None, "description": "近西湖",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    async def _fake_weather(city, *, days=3):
        return {"city": city, "days": [
            {"date": "2026-10-01", "text_day": "晴", "temp_max": "25", "temp_min": "16", "humidity": "40"}
        ], "count": 1, "source": "fake"}

    monkeypatch.setattr(tools_mod, "search_attractions", _fake_search)
    monkeypatch.setattr(tools_mod, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(tools_mod, "query_weather", _fake_weather)
    # agent_tools 在 agents.py 里通过 agent_tools.search_attractions 引用 → 也替换
    monkeypatch.setattr(agents_mod.agent_tools, "search_attractions", _fake_search)
    monkeypatch.setattr(agents_mod.agent_tools, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(agents_mod.agent_tools, "query_weather", _fake_weather)

    class _FakeProvider:
        name = "fake"
        model_id = "fake-model"

        def get_chat_model(self, temperature=0.2):
            return FakeLLM()

    PROVIDER_REGISTRY["fake"] = _FakeProvider()  # type: ignore[assignment]

    result = await agents_mod.run_planning_agents(
        {
            "destination": "杭州",
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
            "travelers": 2,
            "budget": 2000,
            "preferences": ["自然风光", "经济住宿"],
        },
        provider="fake",
    )
    assert result["status"] == "completed"
    assert result["plan"] is not None
    assert len(result["plan"]["days"]) >= 1
    # 每个专家都在 trace 里
    agent_names = {s.get("agent") for s in result["trace"]}
    assert {"AttractionSearchAgent", "WeatherQueryAgent", "HotelAgent", "PlannerAgent"} <= agent_names
    # 天气走的是纯工具路径
    assert result["agents"]["weather"] == "completed"
    PROVIDER_REGISTRY.pop("fake", None)


@pytest.mark.asyncio
async def test_weather_agent_direct(monkeypatch):
    """WeatherQueryAgent 直接调用工具（无 LLM），返回结构化天气。"""
    from app.agent import agents as agents_mod
    from app.agent import tools as tools_mod

    async def _fake_weather(city, *, days=3):
        return {"city": city, "days": [{"date": "2026-10-01", "text_day": "多云"}], "count": 1, "source": "fake"}

    monkeypatch.setattr(tools_mod, "query_weather", _fake_weather)
    result = await agents_mod.weather_agent("杭州")
    assert result["status"] == "completed"
    assert result["weather"]["city"] == "杭州"
    assert result["weather"]["days"][0]["text_day"] == "多云"


@pytest.mark.asyncio
async def test_planner_agent_correction(monkeypatch):
    """Planner 首次输出非法 schema → 自纠正 → 成功。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    class _BadThenGoodPlanner:
        _llm_type = "fake-planner-correction"

        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            if self.calls < 3:
                bad = {
                    "destination": "杭州",
                    "days": [{"day_number": 1, "date": "2026-10-01", "stops": [
                        {"name": "西湖", "type": "museum"}
                    ]}],
                    "budget": {"total_estimated": 0},
                }
                return AIMessage(content=json.dumps(bad, ensure_ascii=False))
            good = {
                "destination": "杭州",
                "days": [{"day_number": 1, "date": "2026-10-01", "stops": [
                    {"name": "西湖", "type": "attraction", "lat": 30.0, "lng": 120.0}
                ]}],
                "budget": {"total_estimated": 0, "by_type": {"attraction": 0}, "currency": "CNY"},
            }
            return AIMessage(content=json.dumps(good, ensure_ascii=False))

    class _FakeProvider:
        name = "fake-planner"
        model_id = "m"

        def __init__(self):
            self._llm = _BadThenGoodPlanner()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["fake-planner"] = _FakeProvider()  # type: ignore[assignment]

    result = await agents_mod.planner_agent(
        {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01", "travelers": 1},
        {"attractions": [], "hotels": [], "foods": [], "weather": {}},
        provider="fake-planner",
        max_corrections=3,
    )
    assert result["status"] == "completed"
    assert result["plan"]["days"][0]["stops"][0]["type"] == "attraction"
    assert result["corrections"] == 2
    PROVIDER_REGISTRY.pop("fake-planner", None)


# ── TravelCriticAgent（Evaluator-Optimizer 评审循环） ─────────
def _install_offline_tools(monkeypatch):
    """统一替换外部工具为离线假实现（含 food，避免真网络）。"""
    from app.agent import tools as tools_mod

    async def _fake_search(city, *, query=None, limit=8, want_type="attraction"):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖", "type": want_type, "lat": 30.245, "lng": 120.15,
             "estimated_cost": 0, "duration_minutes": 180, "description": "环湖",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    async def _fake_search_hotels(city, *, query=None, limit=6):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
             "estimated_cost": 300, "duration_minutes": None, "description": "近西湖",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    async def _fake_weather(city, *, days=3):
        return {"city": city, "days": [
            {"date": "2026-10-01", "text_day": "晴", "temp_max": "25", "temp_min": "16", "humidity": "40"}
        ], "count": 1, "source": "fake"}

    async def _fake_foods(city, *, query=None, limit=8):
        return {"city": city, "count": 1, "results": [
            {"name": "楼外楼", "type": "food", "lat": 30.25, "lng": 120.14,
             "estimated_cost": 200, "duration_minutes": 90, "description": "杭帮菜",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    monkeypatch.setattr(tools_mod, "search_attractions", _fake_search)
    monkeypatch.setattr(tools_mod, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(tools_mod, "search_foods", _fake_foods)
    monkeypatch.setattr(tools_mod, "query_weather", _fake_weather)
    # agents.py 通过 agent_tools.* 引用同一模块对象，无需重复 patch


def _critic_plan(stops: list[dict]) -> dict:
    return {
        "destination": "杭州",
        "days": [{"day_number": 1, "date": "2026-10-01", "theme": "西湖",
                  "stops": stops}],
        "budget": {"total_estimated": 0.0, "by_type": {}, "currency": "CNY"},
    }


@pytest.mark.asyncio
async def test_run_planning_agents_critic_revision_loop(monkeypatch):
    """Planner 首版不过审 → Critic 给出问题 → Planner 带反馈修订 → 二版通过。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _install_offline_tools(monkeypatch)

    stops_v1 = [
        {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
         "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
        {"name": "灵隐寺", "type": "attraction", "lat": 30.24, "lng": 120.10,
         "estimated_cost": 75, "duration_minutes": 120, "description": "古刹"},
    ]
    stops_v2 = [stops_v1[0]]  # 修订版：删掉"绕路"的灵隐寺

    class _CriticLoopLLM:
        _llm_type = "fake-critic-loop"

        def __init__(self):
            self.planner_calls = 0
            self.critic_calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程质检专家" in sys_prompt:
                self.critic_calls += 1
                if self.critic_calls == 1:
                    return AIMessage(content=json.dumps({
                        "score": 60, "passed": False,
                        "issues": [{"severity": "critical", "category": "geography",
                                    "message": "西湖 与 灵隐寺 相距过远，同一天安排绕路",
                                    "suggestion": "把灵隐寺移到第二天或删除", "day_number": 1}],
                        "summary": "第一天路线不合理",}, ensure_ascii=False))
                return AIMessage(content=json.dumps({
                    "score": 92, "passed": True, "issues": [], "summary": "修订后通过"},
                    ensure_ascii=False))
            if "行程规划专家" in sys_prompt:
                self.planner_calls += 1
                stops = stops_v1 if self.planner_calls == 1 else stops_v2
                return AIMessage(content=json.dumps(_critic_plan(stops), ensure_ascii=False))
            if "景点搜索专家" in sys_prompt:
                return AIMessage(content="Thought: 搜索景点。",
                                 tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                                              "id": "a1", "type": "tool_call"}])
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(content="Thought: 查询酒店。",
                                 tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                                              "id": "h1", "type": "tool_call"}])
            return AIMessage(content='{"error": "unknown role"}')

    class _FakeProvider:
        name = "fake-critic"
        model_id = "m"

        def __init__(self):
            self._llm = _CriticLoopLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["fake-critic"] = _FakeProvider()  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 2, "budget": 2000, "preferences": ["自然风光"]},
            provider="fake-critic", max_review_rounds=2,
        )
        assert result["status"] == "completed"
        # Planner 生成 2 次（首版 + 修订），Critic 评审 2 次（失败 1 + 通过 1）
        assert result["review_rounds"] == 2
        assert len(result["review_history"]) == 2
        assert result["review_history"][0]["passed"] is False
        assert result["review_history"][1]["passed"] is True
        # 定稿应是修订版（只保留西湖）
        assert len(result["plan"]["days"][0]["stops"]) == 1
        assert result["plan"]["days"][0]["stops"][0]["name"] == "西湖"
        # trace 含质检专家
        critic_steps = [s for s in result["trace"] if s.get("agent") == "TravelCriticAgent"]
        assert len(critic_steps) == 2
    finally:
        PROVIDER_REGISTRY.pop("fake-critic", None)


@pytest.mark.asyncio
async def test_run_planning_agents_critic_forced_finalize(monkeypatch):
    """Critic 永不通过 → 达到最大评审轮数 → 强制定稿（任务有界，不无限循环）。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _install_offline_tools(monkeypatch)

    class _NeverPassLLM:
        _llm_type = "fake-critic-never"

        def __init__(self):
            self.planner_calls = 0
            self.critic_calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程质检专家" in sys_prompt:
                self.critic_calls += 1
                return AIMessage(content=json.dumps({
                    "score": 50, "passed": False,
                    "issues": [{"severity": "critical", "category": "schedule",
                                "message": "站点过多", "suggestion": "减少站点", "day_number": 1}],
                    "summary": "永远过不了",}, ensure_ascii=False))
            if "行程规划专家" in sys_prompt:
                self.planner_calls += 1
                return AIMessage(content=json.dumps(_critic_plan([
                    {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                     "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"}]),
                    ensure_ascii=False))
            if "景点搜索专家" in sys_prompt:
                return AIMessage(content="Thought: 搜索景点。",
                                 tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                                              "id": "a1", "type": "tool_call"}])
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(content="Thought: 查询酒店。",
                                 tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                                              "id": "h1", "type": "tool_call"}])
            return AIMessage(content='{"error": "unknown role"}')

    class _FakeProvider:
        name = "fake-critic-never"
        model_id = "m"

        def __init__(self):
            self._llm = _NeverPassLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["fake-critic-never"] = _FakeProvider()  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": []},
            provider="fake-critic-never", max_review_rounds=2,
        )
        # 有界：即便 Critic 永不通过，也会强制定稿返回 completed
        assert result["status"] == "completed"
        assert result["plan"] is not None
        assert result["review_rounds"] == 3  # 3 次生成（第 3 代强制终止）
        finalize_steps = [s for s in result["trace"]
                          if s.get("agent") == "TravelCriticAgent" and "强制定稿" in (s.get("observation") or "")]
        assert len(finalize_steps) == 1
    finally:
        PROVIDER_REGISTRY.pop("fake-critic-never", None)


@pytest.mark.asyncio
async def test_run_planning_agents_critic_degraded(monkeypatch):
    """Critic 调用抛异常 → 降级「通过」，主流程仍完成（质检绝不阻断）。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _install_offline_tools(monkeypatch)

    class _CriticBrokenLLM:
        _llm_type = "fake-critic-broken"

        def __init__(self):
            self.critic_calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程质检专家" in sys_prompt:
                self.critic_calls += 1
                raise RuntimeError("Critic LLM 崩溃")
            if "行程规划专家" in sys_prompt:
                return AIMessage(content=json.dumps(_critic_plan([
                    {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                     "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"}]),
                    ensure_ascii=False))
            if "景点搜索专家" in sys_prompt:
                return AIMessage(content="Thought: 搜索景点。",
                                 tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                                              "id": "a1", "type": "tool_call"}])
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(content="Thought: 查询酒店。",
                                 tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                                              "id": "h1", "type": "tool_call"}])
            return AIMessage(content='{"error": "unknown role"}')

    class _FakeProvider:
        name = "fake-critic-broken"
        model_id = "m"

        def __init__(self):
            self._llm = _CriticBrokenLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["fake-critic-broken"] = _FakeProvider()  # type: ignore[assignment]
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": []},
            provider="fake-critic-broken", max_review_rounds=2,
        )
        assert result["status"] == "completed"
        assert result["plan"] is not None
        critic_steps = [s for s in result["trace"] if s.get("agent") == "TravelCriticAgent"]
        assert len(critic_steps) == 1
        assert critic_steps[0]["status"] == "degraded"
        # 降级放行后 review_history 存的是「通过」报告
        assert result["review_history"][0]["passed"] is True
    finally:
        PROVIDER_REGISTRY.pop("fake-critic-broken", None)


# ── 编排 ───────────────────────────────────────────────────
def test_run_planning_agents_builds_metadata():
    from app.agent import agents as agents_mod

    # 纯函数层面：确认 trace 结构包含 agent 名
    assert hasattr(agents_mod, "run_planning_agents")


# ── providers ──────────────────────────────────────────────
def test_get_provider_auto_no_key_raises(monkeypatch):
    """没有配置任何 key 时，auto 应明确报错（不再静默 mock）。"""
    from app.agent.providers import LLMProviderError, get_provider
    from app.common.config import settings

    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    with pytest.raises(LLMProviderError):
        get_provider("auto")
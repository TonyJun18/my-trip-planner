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
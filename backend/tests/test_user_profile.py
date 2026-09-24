"""task-user-profile-memory：跨会话用户画像 测试。

覆盖四件事：
1. ProfileIn/ProfileOut schema：字段清洗（空白 → None、城市列表去空）
2. profile CRUD API：GET 空画像 / PUT upsert / GET 读回 / 覆盖更新
3. 规划注入：create_task 自动读画像 → request.profile_text 注入 → 各 Agent 上下文含画像
4. 用户隔离：A 的画像 B 不可见；无画像（空值）不注入、不影响规划
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent import agents
from app.agent.agents import _profile_text
from app.models import PlanTask
from app.schemas import PlanRequest
from app.schemas.profile import ProfileIn


# ── 1. schema ────────────────────────────────────────────────
class TestProfileSchema:
    def test_clean_blank_strings(self):
        p = ProfileIn(traveler_type="  ", pace="", budget_tier="  舒适  ")
        assert p.traveler_type is None
        assert p.pace is None
        assert p.budget_tier == "舒适"

    def test_clean_cities(self):
        p = ProfileIn(favorite_cities=[" 杭州 ", "", "上海"])
        assert p.favorite_cities == ["杭州", "上海"]

    def test_cities_all_blank_becomes_none(self):
        p = ProfileIn(favorite_cities=["", "  "])
        assert p.favorite_cities is None

    def test_default_all_none(self):
        p = ProfileIn()
        assert p.traveler_type is None
        assert p.favorite_cities is None
        assert p.preferences_json is None


# ── 2. _profile_text 注入层 ───────────────────────────────────
class TestProfileText:
    def test_empty_when_no_profile(self):
        assert _profile_text({}) == ""
        assert _profile_text({"profile_text": ""}) == ""
        assert _profile_text({"profile_text": None}) == ""

    def test_renders_full_profile(self):
        text = _profile_text({
            "profile_text": "【跨会话用户画像】\n出行人群：亲子（带娃）\n节奏偏好：慢节奏\n预算档：舒适",
        })
        # 二次封装：外层再加标题（与 agents._profile_text 输出一致）
        assert "跨会话用户画像" in text
        assert "亲子（带娃）" in text
        assert "慢节奏" in text

    def test_injected_into_planner_context(self):
        request = {"destination": "杭州", "profile_text": "出行人群：亲子（带娃）\n预算档：舒适"}
        text = agents._planner_user_text(request, {})
        assert "【跨会话用户画像】" in text
        assert "亲子（带娃）" in text

    def test_not_injected_when_absent(self):
        text = agents._planner_user_text({"destination": "杭州"}, {})
        assert "跨会话用户画像" not in text


# ── 3. profile CRUD API ──────────────────────────────────────
async def test_profile_get_empty_and_put_flow(client, auth_user):
    _, headers = auth_user

    # GET 空画像 → 200，所有字段 None
    resp = await client.get("/api/v1/profile", headers=headers)
    assert resp.status_code == 200, resp.text
    empty = resp.json()
    assert empty["traveler_type"] is None
    assert empty["favorite_cities"] is None

    # PUT 创建
    resp = await client.put("/api/v1/profile", json={
        "traveler_type": "亲子（带娃）",
        "pace": "慢节奏",
        "budget_tier": "舒适",
        "favorite_cities": ["杭州", "上海"],
        "preferences_json": {"avoid": ["辣"]},
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["traveler_type"] == "亲子（带娃）"
    assert created["favorite_cities"] == ["杭州", "上海"]
    assert created["preferences_json"] == {"avoid": ["辣"]}
    assert created["id"]

    # GET 读回
    resp = await client.get("/api/v1/profile", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["pace"] == "慢节奏"

    # PUT 覆盖（全量替换：不给 pace → 置空）
    resp = await client.put("/api/v1/profile", json={
        "traveler_type": "朋友",
        "budget_tier": "经济",
        "favorite_cities": ["北京"],
    }, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["traveler_type"] == "朋友"
    assert body["pace"] is None
    assert body["budget_tier"] == "经济"
    assert body["favorite_cities"] == ["北京"]
    assert body["preferences_json"] is None


async def test_profile_requires_auth(client):
    resp = await client.get("/api/v1/profile")
    assert resp.status_code == 401
    resp = await client.put("/api/v1/profile", json={"traveler_type": "情侣"})
    assert resp.status_code == 401


async def test_profile_owner_isolation(client):
    """A 的画像 B 不可见、不可改。"""
    import uuid

    ea = f"pa-{uuid.uuid4().hex[:8]}@test.com"
    ra = await client.post("/api/v1/auth/register", json={"email": ea, "password": "test1234"})
    ha = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    eb = f"pb-{uuid.uuid4().hex[:8]}@test.com"
    rb = await client.post("/api/v1/auth/register", json={"email": eb, "password": "test1234"})
    hb = {"Authorization": f"Bearer {rb.json()['access_token']}"}

    await client.put("/api/v1/profile", json={"traveler_type": "亲子"}, headers=ha)

    # A 能读到
    ra2 = await client.get("/api/v1/profile", headers=ha)
    assert ra2.json()["traveler_type"] == "亲子"
    # B 读到的是空画像
    rb2 = await client.get("/api/v1/profile", headers=hb)
    assert rb2.json()["traveler_type"] is None


# ── 4. 端到端：带画像的规划请求 ───────────────────────────────
async def test_plan_with_profile_end_to_end(client, auth_user, monkeypatch, db_session):
    """先存画像 → 提交规划：画像自动注入 Planner/Critic/Attraction 上下文，并随请求落库。"""
    from app.agent import providers as providers_mod

    _, headers = auth_user

    # 1) 先存画像
    resp = await client.put("/api/v1/profile", json={
        "traveler_type": "亲子（带娃）",
        "pace": "慢节奏",
        "budget_tier": "舒适",
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    # 2) 真实数据源全部替换为假实现（无网络）
    async def _fake_search(city, *, query=None, limit=8):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
             "estimated_cost": 0, "duration_minutes": 180,
             "description": "环湖漫步", "source": "fake", "geocoded": True},
        ]}

    async def _fake_search_hotels(city, *, query=None, limit=6):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
             "estimated_cost": 300, "description": "近西湖", "source": "fake", "geocoded": True},
        ]}

    async def _fake_weather(city, *, days=3):
        return {"city": city, "count": 1, "source": "fake",
                "days": [{"date": date.today().isoformat(), "text_day": "晴",
                          "temp_max": "25", "temp_min": "16", "humidity": "40"}]}

    monkeypatch.setattr(agents.agent_tools, "search_attractions", _fake_search)
    monkeypatch.setattr(agents.agent_tools, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(agents.agent_tools, "query_weather", _fake_weather)
    monkeypatch.setattr(agents.agent_tools, "search_foods", _fake_search)

    # 3) FakeProvider：记录注入到各 Agent 的上下文，答案由行程规划专家直接给出
    class _FakeLLM:
        _llm_type = "fake-api"

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程质检专家" in sys_prompt:
                return AIMessage(
                    content=json.dumps(
                        {"score": 90, "passed": True, "issues": [], "summary": "行程合理，通过"},
                        ensure_ascii=False,
                    )
                )
            if "行程规划专家" in sys_prompt:
                human = next((getattr(m, "content", "") or "" for m in messages
                              if getattr(m, "type", "") == "human"), "")
                assert "【跨会话用户画像】" in human, "Planner 上下文应包含画像"
                assert "亲子（带娃）" in human, "Planner 上下文应包含画像具体内容"
                plan = {
                    "destination": "杭州",
                    "days": [{
                        "day_number": 1, "date": date.today().isoformat(), "theme": "西湖经典",
                        "stops": [
                            {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                             "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
                            {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
                             "estimated_cost": 300, "duration_minutes": None, "description": "近西湖"},
                        ],
                    }],
                    "budget": {"total_estimated": 0.0, "by_type": {"attraction": 0.0}, "currency": "CNY"},
                }
                return AIMessage(content=json.dumps(plan, ensure_ascii=False))
            if "景点搜索专家" in sys_prompt:
                human = next((getattr(m, "content", "") or "" for m in messages
                              if getattr(m, "type", "") == "human"), "")
                assert "【跨会话用户画像】" in human, "景点专家上下文应包含画像"
                return AIMessage(
                    content="Thought: 搜索景点。",
                    tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "亲子"},
                                 "id": "s1", "type": "tool_call"}],
                )
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(
                    content="Thought: 查询酒店。",
                    tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "舒适型酒店"},
                                 "id": "h1", "type": "tool_call"}],
                )
            return AIMessage(content='{"error": "unknown role"}')

    class _FakeProvider:
        name = "deepseek"
        model_id = "fake-model"

        def __init__(self):
            self._llm = _FakeLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    providers_mod.PROVIDER_REGISTRY["deepseek"] = _FakeProvider()  # type: ignore[assignment]

    try:
        # 4) 提交规划（不带 questions，只验证画像注入）
        today = date.today()
        resp = await client.post("/api/v1/planner/plan", json={
            "destination": "杭州",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=1)).isoformat(),
            "travelers": 2,
            "budget": 2000,
            "preferences": ["美食"],
            "provider": "deepseek",
        }, headers=headers)
        assert resp.status_code == 202, resp.text
        task_id = resp.json()["task_id"]

        # 5) 轮询完成
        task = None
        for _ in range(50):
            resp = await client.get(f"/api/v1/planner/tasks/{task_id}", headers=headers)
            assert resp.status_code == 200
            task = resp.json()
            if task["status"] in ("completed", "failed"):
                break
            await asyncio.sleep(0.1)

        assert task["status"] == "completed", task
        assert task["trip_id"]

        # 6) 画像随请求落库（request_data 保留注入段）
        stmt = select(PlanTask).where(PlanTask.id == task_id)
        plan_task = (await db_session.execute(stmt)).scalar_one_or_none()
        assert plan_task is not None
        assert "【跨会话用户画像】" in (plan_task.request_data.get("profile_text") or "")
        assert "亲子（带娃）" in (plan_task.request_data.get("profile_text") or "")

    finally:
        providers_mod.PROVIDER_REGISTRY.pop("deepseek", None)
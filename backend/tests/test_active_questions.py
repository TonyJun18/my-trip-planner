"""task-active-questions：主动提问/需求挖掘 测试。

覆盖三件事：
1. PlanRequest schema：questions 字段合法解析、非法拒绝
2. _questions_text：Q&A 上下文组装的过滤（只注入有回答的问题）
3. 端到端：带 questions 提交规划 → Q&A 注入 Planner/Critic 上下文并随请求落库
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent import agents
from app.agent.agents import _questions_text
from app.models import PlanTask
from app.schemas import PlanQuestion, PlanRequest


# ── 1. PlanRequest schema ───────────────────────────────────────
class TestPlanRequestQuestions:
    def test_questions_field_parses(self):
        req = PlanRequest(
            destination="杭州",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            questions=[
                PlanQuestion(question="出行人群？", options=["情侣", "亲子"], answer="情侣"),
                PlanQuestion(question="节奏偏好？", answer="慢节奏"),
                PlanQuestion(question="没回答的问题", options=["A", "B"]),
            ],
        )
        assert len(req.questions) == 3
        assert req.questions[0].answer == "情侣"
        # 未回答的问题保留在请求里（过滤发生在注入层）
        assert req.questions[2].answer is None

    def test_questions_optional_default_empty(self):
        req = PlanRequest(
            destination="杭州",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
        )
        assert req.questions == []

    def test_questions_too_many_rejected(self):
        with pytest.raises(Exception):
            PlanRequest(
                destination="杭州",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 3),
                questions=[PlanQuestion(question=f"Q{i}") for i in range(11)],
            )


# ── 2. _questions_text 注入层 ───────────────────────────────────
class TestQuestionsText:
    def test_empty_when_no_questions(self):
        assert _questions_text({}) == ""
        assert _questions_text({"questions": []}) == ""

    def test_only_answered_questions_injected(self):
        text = _questions_text(
            {
                "questions": [
                    {"question": "出行人群？", "answer": "带 5 岁小孩"},
                    {"question": "节奏偏好？", "answer": ""},
                    {"question": "避峰吗？", "answer": None},
                    {"question": "备选方案？", "answer": "  "},
                ]
            }
        )
        assert "出行人群" in text
        assert "带 5 岁小孩" in text
        assert "节奏偏好" not in text
        assert "备选方案" not in text
        assert "需求澄清" in text

    def test_injected_into_planner_context(self):
        request = {
            "destination": "杭州",
            "questions": [{"question": "出行节奏？", "answer": "慢节奏，每天最多 3 个点"}],
        }
        text = agents._planner_user_text(request, {})
        assert "【需求澄清 · 用户追问答复】" in text
        assert "慢节奏，每天最多 3 个点" in text

    def test_not_injected_when_unanswered(self):
        request = {"destination": "杭州", "questions": [{"question": "出行节奏？", "answer": ""}]}
        text = agents._planner_user_text(request, {})
        assert "需求澄清" not in text
        assert "出行节奏" not in text


# ── 3. 端到端：带 questions 的规划请求 ───────────────────────────
async def test_plan_with_questions_end_to_end(client, auth_user, monkeypatch, db_session):
    """带 questions 提交 /planner/plan：Q&A 注入采集/规划/质检上下文并随请求落库。"""
    from app.agent import providers as providers_mod

    _, headers = auth_user

    # 1) 真实数据源全部替换为假实现（无网络）
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

    # 2) FakeProvider：记录注入到各 Agent 的上下文，答案由行程规划专家直接给出
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
                assert "【需求澄清" in human, "Planner 上下文应包含 Q&A"
                assert "慢节奏" in human, "Planner 上下文应包含用户回答"
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
                assert "【需求澄清" in human, "景点专家上下文应包含 Q&A"
                return AIMessage(
                    content="Thought: 搜索景点。",
                    tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                                 "id": "s1", "type": "tool_call"}],
                )
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(
                    content="Thought: 查询酒店。",
                    tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
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
        # 3) 带 questions 提交
        today = date.today()
        resp = await client.post("/api/v1/planner/plan", json={
            "destination": "杭州",
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=1)).isoformat(),
            "travelers": 2,
            "budget": 2000,
            "preferences": ["美食"],
            "questions": [
                {"question": "出行人群？", "options": ["情侣", "亲子", "朋友"], "answer": "情侣"},
                {"question": "节奏偏好？", "options": ["紧凑", "适中", "慢节奏"], "answer": "慢节奏"},
                {"question": "需要避峰吗？", "options": ["是", "否"], "answer": ""},
            ],
            "provider": "deepseek",
        }, headers=headers)
        assert resp.status_code == 202, resp.text
        task_id = resp.json()["task_id"]

        # 4) 轮询完成
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
        assert task["plan"]["destination"] == "杭州"

        # 5) questions 随请求落库（request_data 保留用户提交的追问）
        stmt = select(PlanTask).where(PlanTask.id == task_id)
        plan_task = (await db_session.execute(stmt)).scalar_one_or_none()
        assert plan_task is not None
        assert plan_task.request_data is not None
        saved_questions = plan_task.request_data.get("questions") or []
        assert len(saved_questions) == 3
        assert saved_questions[1]["answer"] == "慢节奏"
        # 未回答的问题也保留原样（答案为空串）
        assert saved_questions[2]["answer"] == ""

    finally:
        providers_mod.PROVIDER_REGISTRY.pop("deepseek", None)
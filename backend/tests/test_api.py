"""API 测试：auth / health / trips CRUD / 异步 planner（FakeLLM agent 全链路）。"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta


# ── auth ─────────────────────────────────────────────────────
def _rand_email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@test.com"


async def test_register_email(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": _rand_email(), "password": "test1234", "display_name": "小明",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"]

    # 用 token 访问 /me
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == body["user"]["email"]


async def test_register_phone(client):
    resp = await client.post("/api/v1/auth/register", json={
        "phone": "13800138000", "password": "test1234",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["phone"] == "13800138000"


async def test_register_duplicate(client):
    email = _rand_email()
    payload = {"email": email, "password": "test1234"}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400
    assert "已注册" in resp.json()["error"]["message"]


async def test_register_invalid(client):
    # 空身份
    resp = await client.post("/api/v1/auth/register", json={"password": "test1234"})
    assert resp.status_code == 400
    # 坏邮箱
    resp = await client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "test1234"})
    assert resp.status_code == 400
    # 密码太短
    resp = await client.post("/api/v1/auth/register", json={"email": _rand_email(), "password": "short"})
    assert resp.status_code == 422


async def test_login_and_wrong_password(client):
    email = _rand_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": "test1234"})

    ok = await client.post("/api/v1/auth/login", json={"account": email, "password": "test1234"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post("/api/v1/auth/login", json={"account": email, "password": "wrongpass"})
    assert bad.status_code == 401


async def test_me_unauthorized(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert resp.status_code == 401


# ── health ───────────────────────────────────────────────────
async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["app"] == "my-trip-planner"


# ── trips CRUD（需登录） ────────────────────────────────────
async def test_trips_require_auth(client):
    resp = await client.get("/api/v1/trips")
    assert resp.status_code == 401


async def test_trip_crud_flow(client, auth_user):
    _, headers = auth_user
    today = date.today()
    payload = {
        "title": "杭州三日游",
        "destination": "杭州",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=2)).isoformat(),
        "travelers": 2,
        "budget": 3000,
    }
    resp = await client.post("/api/v1/trips", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    trip = resp.json()
    trip_id = trip["id"]
    assert trip["destination"] == "杭州"
    assert trip["status"] == "draft"

    resp = await client.get("/api/v1/trips", headers=headers)
    assert resp.status_code == 200
    assert any(t["id"] == trip_id for t in resp.json()["items"])

    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "杭州三日游"

    resp = await client.patch(f"/api/v1/trips/{trip_id}", json={"budget": 5000, "status": "confirmed"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["budget"] == 5000
    assert resp.json()["status"] == "confirmed"

    resp = await client.delete(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 404


# ── days / stops ─────────────────────────────────────────────
async def test_add_day_and_stop(client, auth_user):
    _, headers = auth_user
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "上海周末",
        "destination": "上海",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }, headers=headers)
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1, "note": "第一天"}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "外滩",
        "stop_type": "attraction",
        "lat": 31.24,
        "lng": 121.49,
        "estimated_cost": 0,
        "description": "万国建筑博览群",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["order_index"] == 1

    resp = await client.get(f"/api/v1/trips/{trip_id}/budget", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total_estimated"] == 0


# ── 异步 planner（FakeLLM 多 Agent 全链路） ────────────────
async def test_planner_async_task_flow(client, auth_user, monkeypatch):
    """提交规划任务 → 轮询 → 完成 → 行程已回写数据库。"""
    from langchain_core.messages import AIMessage

    from app.agent import tools as agent_tools
    from app.agent.providers import PROVIDER_REGISTRY

    _, headers = auth_user

    # 1) 替换外部搜索/天气为离线假实现（高德/网络不依赖）
    async def _fake_search(city, *, query=None, limit=8):
        return {
            "city": city,
            "count": 1,
            "results": [
                {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                 "estimated_cost": 0, "duration_minutes": 180, "description": "环湖",
                 "source": "fake", "source_url": "", "geocoded": True}
            ],
        }

    async def _fake_search_hotels(city, *, query=None, limit=6):
        return {
            "city": city,
            "count": 1,
            "results": [
                {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
                 "estimated_cost": 300, "duration_minutes": None, "description": "近西湖",
                 "source": "fake", "source_url": "", "geocoded": True}
            ],
        }

    async def _fake_weather(city, *, days=3):
        return {"city": city, "count": 1, "source": "fake",
                "days": [{"date": date.today().isoformat(), "text_day": "晴",
                          "temp_max": "25", "temp_min": "16", "humidity": "40"}]}

    monkeypatch.setattr(agent_tools, "search_attractions", _fake_search)
    monkeypatch.setattr(agent_tools, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(agent_tools, "query_weather", _fake_weather)

    # 2) FakeProvider 注册在 deepseek 名下（绕过 Literal 校验）
    class _FakeLLM:
        """按系统提示词区分角色：景点/酒店专家调工具，规划师直接出最终 JSON。"""

        _llm_type = "fake-api"

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            # 行程规划专家：system 提示里含【行程规划专家】（也含"景点搜索专家"字样），必须先判断
            if "行程规划专家" in sys_prompt:
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
            # 未知角色兜底
            return AIMessage(content='{"error": "unknown role"}')

    class _FakeProvider:
        name = "deepseek"
        model_id = "fake-model"

        def __init__(self):
            self._llm = _FakeLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["deepseek"] = _FakeProvider()  # type: ignore[assignment]

    # 3) 提交异步任务
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

    # 4) 轮询直到完成
    import asyncio

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
    assert len(task["trace"]) >= 1

    # 5) 行程已回写
    trip_id = task["trip_id"]
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 200
    trip = resp.json()
    assert len(trip["days"]) >= 1
    assert trip["days"][0]["stops"], "Day 应有回填的 stops"

    PROVIDER_REGISTRY.pop("deepseek", None)


# ── 用户隔离 ─────────────────────────────────────────────────
async def test_owner_isolation(client):
    """不同用户的数据完全隔离。"""
    # 用户 A
    ea = _rand_email()
    ra = await client.post("/api/v1/auth/register", json={"email": ea, "password": "test1234"})
    headers_a = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    # 用户 B
    eb = _rand_email()
    rb = await client.post("/api/v1/auth/register", json={"email": eb, "password": "test1234"})
    headers_b = {"Authorization": f"Bearer {rb.json()['access_token']}"}

    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "A 的行程", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
    }, headers=headers_a)
    assert resp.status_code == 201

    # A 能查到
    resp = await client.get("/api/v1/trips", headers=headers_a)
    assert len(resp.json()["items"]) == 1
    # B 查不到 A 的
    resp = await client.get("/api/v1/trips", headers=headers_b)
    assert len(resp.json()["items"]) == 0
    # B 直接访问 A 的 trip_id → 404
    trip_id = (await client.get("/api/v1/trips", headers=headers_a)).json()["items"][0]["id"]
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers_b)
    assert resp.status_code == 404


# ── 参数校验 ─────────────────────────────────────────────────
async def test_plan_validation_error(client, auth_user):
    _, headers = auth_user
    resp = await client.post("/api/v1/planner/plan", json={"destination": ""}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"
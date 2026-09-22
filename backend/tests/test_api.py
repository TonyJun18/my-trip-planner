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
            # 行程质检专家：输出通过报告
            if "行程质检专家" in sys_prompt:
                return AIMessage(
                    content=json.dumps(
                        {"score": 90, "passed": True, "issues": [], "summary": "行程整体合理，通过"},
                        ensure_ascii=False,
                    )
                )
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


# ── 对话式修订行程（方案 B） ─────────────────────────────────
async def test_revise_trip_flow(client, auth_user, monkeypatch):
    """POST /trips/{id}/revise：AI 生成 diff → 代码原子应用 → 落库生效。"""
    from langchain_core.messages import AIMessage

    from app.agent import tools as agent_tools
    from app.agent.providers import PROVIDER_REGISTRY

    _, headers = auth_user
    today = date.today()

    # 1) 建行程 + Day + 两个站点
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州一日",
        "destination": "杭州",
        "start_date": today.isoformat(),
        "end_date": today.isoformat(),
        "travelers": 1,
        "budget": 2000,
    }, headers=headers)
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1, "note": "第一天"}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "西湖", "stop_type": "attraction", "lat": 30.245, "lng": 120.15,
        "estimated_cost": 0, "estimated_duration_minutes": 180, "description": "环湖",
    }, headers=headers)
    assert resp.status_code == 201
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "楼外楼", "stop_type": "food", "lat": 30.25, "lng": 120.14,
        "estimated_cost": 200, "estimated_duration_minutes": 90, "description": "杭帮菜",
    }, headers=headers)
    assert resp.status_code == 201

    # 2) FakeProvider：PlanReviseAgent 返回「西湖改半天 + 新增晚餐」diff
    class _ReviseLLM:
        _llm_type = "fake-revise"

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程修订专家" in sys_prompt:
                return AIMessage(content=json.dumps({
                    "actions": [
                        {"op": "replace", "day_number": 1,
                         "target": {"name": "西湖"},
                         "fields": {"duration_minutes": 90, "description": "半日西湖"}},
                        {"op": "add", "day_number": 1, "index": 3,
                         "fields": {"name": "知味观", "stop_type": "food",
                                    "estimated_cost": 150, "duration_minutes": 60}},
                    ],
                    "summary": "西湖改为半天，新增知味观晚餐",
                }, ensure_ascii=False))
            return AIMessage(content='{"error": "unknown role"}')

    class _ReviseProvider:
        name = "deepseek"
        model_id = "fake-revise-model"

        def __init__(self):
            self._llm = _ReviseLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["deepseek"] = _ReviseProvider()  # type: ignore[assignment]
    try:
        # 3) 调用 revise
        resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
            "message": "西湖只留半天，晚上再加一个知味观",
            "provider": "deepseek",
        }, headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["summary"] == "西湖改为半天，新增知味观晚餐"
        assert body["plan"]["days"][0]["stops"][0]["duration_minutes"] == 90
        assert body["plan"]["days"][0]["stops"][0]["description"] == "半日西湖"
        assert body["plan"]["days"][0]["stops"][2]["name"] == "知味观"
        assert body["trace"][0]["thought"] == "PlanReviseAgent"

        # 4) 落库可读回
        resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
        assert resp.status_code == 200
        stops = resp.json()["days"][0]["stops"]
        assert len(stops) == 3
        assert stops[2]["name"] == "知味观"
        assert stops[0]["estimated_duration_minutes"] == 90
    finally:
        PROVIDER_REGISTRY.pop("deepseek", None)


async def test_revise_trip_target_not_found(client, auth_user, monkeypatch):
    """修订目标不存在 → 原子失败，不落库任何变更。"""
    from langchain_core.messages import AIMessage

    from app.agent.providers import PROVIDER_REGISTRY

    _, headers = auth_user
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州一日", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
    }, headers=headers)
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    day_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "西湖", "stop_type": "attraction",
    }, headers=headers)
    assert resp.status_code == 201

    class _BadLLM:
        _llm_type = "fake-revise-bad"

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程修订专家" in sys_prompt:
                return AIMessage(content=json.dumps({
                    "actions": [
                        {"op": "remove", "day_number": 1, "target": {"name": "不存在的景点"}},
                    ],
                    "summary": "删掉不存在的景点",
                }, ensure_ascii=False))
            return AIMessage(content='{"error": "unknown role"}')

    class _BadProvider:
        name = "deepseek"
        model_id = "m"
        _llm = _BadLLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["deepseek"] = _BadProvider()  # type: ignore[assignment]
    try:
        resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
            "message": "删掉一个不存在的景点", "provider": "deepseek",
        }, headers=headers)
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "revise_target_not_found"

        # 原行程未被破坏
        resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
        stops = resp.json()["days"][0]["stops"]
        assert len(stops) == 1
        assert stops[0]["name"] == "西湖"
    finally:
        PROVIDER_REGISTRY.pop("deepseek", None)


async def test_revise_trip_requires_plan(client, auth_user, monkeypatch):
    """行程还没有 AI 规划方案（TripPlan）时，revise 仍可工作（基于 trip 数据）。"""
    from langchain_core.messages import AIMessage

    from app.agent.providers import PROVIDER_REGISTRY

    _, headers = auth_user
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州一日", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
    }, headers=headers)
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    day_id = resp.json()["id"]
    await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "西湖", "stop_type": "attraction",
    }, headers=headers)

    class _LLM:
        _llm_type = "fake-revise-no-plan"

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程修订专家" in sys_prompt:
                return AIMessage(content=json.dumps({
                    "actions": [
                        {"op": "add", "day_number": 1,
                         "fields": {"name": "灵隐寺", "stop_type": "attraction"}},
                    ],
                    "summary": "新增灵隐寺",
                }, ensure_ascii=False))
            return AIMessage(content='{"error": "unknown role"}')

    class _Provider:
        name = "deepseek"
        model_id = "m"
        _llm = _LLM()

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY["deepseek"] = _Provider()  # type: ignore[assignment]
    try:
        resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
            "message": "加一个灵隐寺", "provider": "deepseek",
        }, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["plan"]["days"][0]["stops"][1]["name"] == "灵隐寺"
    finally:
        PROVIDER_REGISTRY.pop("deepseek", None)


# ── 参数校验 ─────────────────────────────────────────────────
async def test_plan_validation_error(client, auth_user):
    _, headers = auth_user
    resp = await client.post("/api/v1/planner/plan", json={"destination": ""}, headers=headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


# ── 行程分享（只读链接） ─────────────────────────────────────
async def _make_trip_with_day(client, headers, title="杭州一日", destination="杭州"):
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": title, "destination": destination,
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": 2, "budget": 1000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip = resp.json()
    resp = await client.post(f"/api/v1/trips/{trip['id']}/days", json={"day_number": 1, "note": "第一天"}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]
    await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "西湖", "stop_type": "attraction", "lat": 30.245, "lng": 120.15,
        "estimated_cost": 0, "description": "环湖",
    }, headers=headers)
    return trip["id"]


async def test_share_link_flow(client, auth_user):
    """生成分享链接 → 匿名可读（含站点） → share_token 幂等复用。"""
    _, headers = auth_user
    trip_id = await _make_trip_with_day(client, headers)

    # 首次生成
    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    token = body["share_token"]
    assert len(token) >= 32
    assert body["trip_id"] == trip_id
    assert body["share_url"].endswith(f"/share/{token}")

    # 幂等：再次生成复用同一 token
    resp2 = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp2.json()["share_token"] == token

    # 公开 GET 返回行程详情（无需 auth header），并携带预算汇总（分享页免本地计算）
    resp = await client.get(f"/api/v1/trips/share/{token}")
    assert resp.status_code == 200, resp.text
    shared = resp.json()
    assert shared["id"] == trip_id
    assert shared["destination"] == "杭州"
    assert len(shared["days"]) == 1
    assert shared["days"][0]["stops"][0]["name"] == "西湖"
    assert "budget_summary" in shared
    assert shared["budget_summary"]["total_estimated"] == 0
    assert shared["budget_summary"]["currency"] == "CNY"

    # TripOut 携带 share_token（前端可判断已分享）
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["share_token"] == token


async def test_share_requires_auth_and_valid_token(client):
    """分享生成需登录；无效/不存在 token → 404。"""
    resp = await client.post("/api/v1/trips/any/share")
    assert resp.status_code == 401

    resp = await client.get("/api/v1/trips/share/not-a-real-token")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "share_token_invalid"


async def test_share_owner_isolation(client):
    """用户 B 不能为 A 的行程生成分享链接（404）；匿名也读不到未分享行程。"""
    ea = _rand_email()
    ra = await client.post("/api/v1/auth/register", json={"email": ea, "password": "test1234"})
    headers_a = {"Authorization": f"Bearer {ra.json()['access_token']}"}
    eb = _rand_email()
    rb = await client.post("/api/v1/auth/register", json={"email": eb, "password": "test1234"})
    headers_b = {"Authorization": f"Bearer {rb.json()['access_token']}"}

    trip_id = await _make_trip_with_day(client, headers_a, title="A 的行程")

    # B 给 A 的行程生成分享 → 404（视为不存在）
    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers_b)
    assert resp.status_code == 404

    # 匿名访问未分享行程 → 404
    resp = await client.get(f"/api/v1/trips/share/whatever")
    assert resp.status_code == 404
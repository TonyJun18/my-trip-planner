"""task-revise-qa-loop：修订质控闭环专项测试。

覆盖：
1. 修订通过 → quality.passed=True（fix_applied 视修正与否）
2. 未通过但带精确 fix → fix 原子应用 → 复审通过（fix_applied=True）
3. Critic 降级 → quality.passed=True + degraded（绝不阻断主修订）
4. 停滞检测：连续相同 fix → 停止重试（有界）
5. 自驾约束拒绝 fix → 回滚本轮 fix，主修订保留（独立小事务语义）
6. 大改/无 fix → quality.passed=False（保留主修订，不无限复审）
7. max_review_rounds=0 → 关闭复核（quality=None）
8. critic_fix_to_revise_diff 字段名映射（type/duration_minutes → ORM 名）

mock 策略：局级 patch `app.agent.agents.revise_critic_agent`（闭环内部
通过 from-import 引用该名字），不 mock PlanReviseAgent —— API 层测试
用 FakeProvider 走真实修订路径；这里用 client + provider 注册。
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from langchain_core.messages import AIMessage


# ── 工具：造行程 + 造 FakeProvider ──────────────────────────
async def _make_trip(client, headers, stops=("西湖", "楼外楼")):
    """建行程 + Day + 站点，返回 trip_id。"""
    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州一日", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": 2, "budget": 2000,
    }, headers=headers)
    trip_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    day_id = resp.json()["id"]
    for i, name in enumerate(stops, start=1):
        await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": "attraction" if i % 2 else "food",
            "lat": 30.2 + i * 0.01, "lng": 120.1 + i * 0.01,
            "estimated_cost": 50, "estimated_duration_minutes": 120,
        }, headers=headers)
    return trip_id


class _DummyReviseLLM:
    """PlanReviseAgent 的假 LLM：固定返回一个修改站点描述的 diff。"""

    _llm_type = "dummy-revise"

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content=json.dumps({
            "actions": [
                {"op": "replace", "day_number": 1,
                 "target": {"name": "西湖"},
                 "fields": {"description": "半日西湖"}},
            ],
            "summary": "西湖改为半天",
        }, ensure_ascii=False))


class _DummyProvider:
    """FakeProvider：让 PlanReviseAgent 走假的 _DummyReviseLLM。"""

    name = "deepseek"
    model_id = "dummy-revise-model"

    def __init__(self):
        self._llm = _DummyReviseLLM()

    def get_chat_model(self, temperature=0.2):
        return self._llm


@pytest.fixture
def revise_provider():
    from app.agent.providers import PROVIDER_REGISTRY

    PROVIDER_REGISTRY["deepseek"] = _DummyProvider()  # type: ignore[assignment]
    yield "deepseek"
    PROVIDER_REGISTRY.pop("deepseek", None)


# ── 用例 ────────────────────────────────────────────────────
async def test_revise_qa_pass(client, auth_user, monkeypatch, revise_provider):
    """Critic 通过 → quality.passed=True，主修订正常落库。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    calls = {}

    async def _pass_critic(request, plan, *, provider="auto", max_corrections=2):
        calls["plan"] = plan
        return {
            "status": "completed",
            "critique": {
                "score": 92, "passed": True, "issues": [],
                "summary": "修订合理",
            },
            "corrections": 0,
        }

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _pass_critic)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["quality"]["passed"] is True
    assert body["quality"]["score"] == 92
    assert body["quality"]["fix_applied"] is False
    # 修订确实落库
    assert body["plan"]["days"][0]["stops"][0]["description"] == "半日西湖"


async def test_revise_qa_fix_applied(client, auth_user, monkeypatch, revise_provider):
    """Critic 未通过但带精确 fix → fix 原子应用 → 复审通过，fix_applied=True。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    round_no = {"n": 0}

    async def _critic_fix(request, plan, *, provider="auto", max_corrections=2):
        round_no["n"] += 1
        if round_no["n"] == 1:
            # 第一轮：未通过 + 修正建议（把楼外楼的类型改成 food）
            return {
                "status": "completed",
                "critique": {
                    "score": 60, "passed": False,
                    "issues": [{"severity": "critical", "category": "logistics",
                                "message": "楼外楼应为餐厅", "day_number": 1}],
                    "summary": "楼外楼类型错误",
                    "fix": {
                        "actions": [
                            {"op": "replace", "day_number": 1,
                             "target": {"name": "楼外楼"},
                             "fields": {"type": "food"}},
                        ],
                        "summary": "把楼外楼改为餐厅",
                    },
                },
                "corrections": 0,
            }
        # 第二轮：fix 已应用 → 通过
        return {
            "status": "completed",
            "critique": {
                "score": 95, "passed": True, "issues": [],
                "summary": "修正后通过",
            },
            "corrections": 0,
        }

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _critic_fix)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["quality"]["passed"] is True
    assert body["quality"]["fix_applied"] is True
    assert body["quality"]["rounds"] == 2
    # fix 已落库：楼外楼类型变成 food
    stops = body["plan"]["days"][0]["stops"]
    louwai = next(s for s in stops if s["name"] == "楼外楼")
    assert louwai["type"] == "food"


async def test_revise_qa_degraded(client, auth_user, monkeypatch, revise_provider):
    """Critic 熔断/超时 → quality.passed=True + degraded=True，主修订不阻断。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    async def _degraded(request, plan, *, provider="auto", max_corrections=2):
        return {"status": "degraded", "critique": {"score": 80, "passed": True,
                                                   "issues": [], "summary": "降级"}, "corrections": 0}

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _degraded)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quality"]["passed"] is True
    assert body["quality"]["degraded"] is True
    assert body["plan"]["days"][0]["stops"][0]["description"] == "半日西湖"


async def test_revise_qa_stagnation(client, auth_user, monkeypatch, revise_provider):
    """停滞检测：连续两轮给出相同 fix → 停止重试（有界），quality.passed=False。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    calls = {"n": 0}

    async def _stuck_critic(request, plan, *, provider="auto", max_corrections=2):
        calls["n"] += 1
        # 每一轮都返回同样的 fix（无法修正 → 停滞）
        return {
            "status": "completed",
            "critique": {
                "score": 55, "passed": False,
                "issues": [{"severity": "critical", "category": "geography",
                            "message": "第一站太远", "day_number": 1}],
                "summary": "距离过远",
                "fix": {
                    "actions": [
                        {"op": "replace", "day_number": 1,
                         "target": {"name": "西湖"},
                         "fields": {"description": "近一点"}},
                    ],
                    "summary": "靠近一点",
                },
            },
            "corrections": 0,
        }

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _stuck_critic)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 最多调用 2 轮（max_review_rounds=2），停滞即停
    assert calls["n"] <= 2
    assert body["quality"]["passed"] is False
    assert "停止重试" in body["quality"]["summary"]
    # 第一轮 fix（把西湖改成"近一点"）已应用，第二轮重复建议被停滞检测拦下
    assert body["plan"]["days"][0]["stops"][0]["description"] == "近一点"


async def test_revise_qa_driving_rollback(client, auth_user, monkeypatch, revise_provider):
    """自驾约束拒绝 fix → 本轮 fix 回滚，主修订保留，quality.passed=False。"""
    from app.agent import agents as agents_mod
    from app.services import revise_service as rs

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    async def _critic_with_fix(request, plan, *, provider="auto", max_corrections=2):
        # 未通过 + 带 fix（只要 fix 应用后自驾会拒绝）
        return {
            "status": "completed",
            "critique": {
                "score": 50, "passed": False,
                "issues": [{"severity": "critical", "category": "geography",
                            "message": "新增远距站点", "day_number": 1}],
                "summary": "新增远距站点",
                "fix": {
                    "actions": [
                        {"op": "add", "day_number": 1,
                         "fields": {"name": "远郊", "type": "attraction",
                                    "lat": 35.0, "lng": 115.0}},
                    ],
                    "summary": "加一个远郊站点",
                },
            },
            "corrections": 0,
        }

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _critic_with_fix)

    # 自驾约束：主修订那轮（第 1 次调用）正常通过；fix 后（第 2 次）抛超距
    original = rs._enforce_driving_constraints
    gate_calls = {"n": 0}

    async def _driving_gate(trip):
        gate_calls["n"] += 1
        await original(trip)  # 先真实校验（主修订与两站行程都合法）
        if gate_calls["n"] >= 2:
            raise rs.AppError("超距", code="revise_driving_violation")

    monkeypatch.setattr(rs, "_enforce_driving_constraints", _driving_gate)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quality"]["passed"] is False
    assert "自驾约束" in body["quality"]["summary"]
    # 主修订仍在（西湖 description 改了），fix 未应用（没有远郊站）
    stops = body["plan"]["days"][0]["stops"]
    assert any(s["name"] == "西湖" and s.get("description") == "半日西湖" for s in stops)
    assert not any(s["name"] == "远郊" for s in stops)


async def test_revise_qa_no_fix_stops(client, auth_user, monkeypatch, revise_provider):
    """未通过但无 fix（大改/纯警告）→ 停在当前轮，quality.passed=False。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    async def _no_fix(request, plan, *, provider="auto", max_corrections=2):
        return {
            "status": "completed",
            "critique": {
                "score": 50, "passed": False,
                "issues": [{"severity": "critical", "category": "schedule",
                            "message": "整体行程不合理", "day_number": 1}],
                "summary": "需要大改",  # 无 fix
            },
            "corrections": 0,
        }

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _no_fix)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quality"]["passed"] is False
    assert body["quality"]["fix_applied"] is False
    # 主修订保留
    assert body["plan"]["days"][0]["stops"][0]["description"] == "半日西湖"


async def test_revise_qa_disabled(client, auth_user, monkeypatch, revise_provider):
    """max_review_rounds=0 → 关闭复核（quality=None），主修订正常。"""
    from app.agent import agents as agents_mod
    from app.services import revise_service as rs

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    async def _should_not_called(request, plan, *, provider="auto", max_corrections=2):
        raise AssertionError("max_review_rounds=0 时不应调用 revise_critic_agent")

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _should_not_called)
    orig = rs.revise_trip

    async def _revise_no_loop(*args, **kwargs):
        kwargs["max_review_rounds"] = 0
        return await orig(*args, **kwargs)

    monkeypatch.setattr(rs, "revise_trip", _revise_no_loop)
    # 直接调 service（避免 API 层参数透传差异）
    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    # 关闭复核 → quality 为 None；主修订生效
    assert body["quality"] is None
    assert body["plan"]["days"][0]["stops"][0]["description"] == "半日西湖"


# ── 转换器（纯函数） ─────────────────────────────────────────
def test_critic_fix_to_revise_diff_maps_fields():
    from app.schemas import critic_fix_to_revise_diff

    fix = {
        "actions": [
            {"op": "replace", "day_number": 1, "target": {"name": "x"},
             "fields": {"type": "food", "duration_minutes": 60, "estimated_cost": 80}},
            {"op": "add", "day_number": 2, "index": 1,
             "fields": {"name": "新站", "type": "attraction"}},
        ],
        "summary": "修正",
    }
    diff = critic_fix_to_revise_diff(fix)
    assert diff["actions"][0]["fields"] == {
        "stop_type": "food", "estimated_duration_minutes": 60, "estimated_cost": 80,
    }
    assert diff["actions"][1]["fields"] == {"name": "新站", "stop_type": "attraction"}
    assert diff["actions"][0]["target"] == {"name": "x"}
    assert diff["actions"][1]["index"] == 1


def test_critic_fix_to_revise_diff_empty_actions():
    from app.schemas import critic_fix_to_revise_diff

    assert critic_fix_to_revise_diff({"actions": [], "summary": "s"}) == {
        "actions": [], "summary": "s",
    }
    assert critic_fix_to_revise_diff(None) == {"actions": [], "summary": None}
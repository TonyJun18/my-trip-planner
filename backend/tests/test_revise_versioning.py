"""task-floattrip-borrow Story 3：@ 引用行程修改 → 修订保留原版本。

核心：修订（revise_trip）后必须「保留原版本 + 产生新版本」：
- 修订前最新 TripPlan 快照复制为 archived 历史版本（沿用原 created_at）
- 原行升级为新版本（created_at=当前，排序恒为最新）
- get_plan / escalate / 分享读路径全部按 created_at 倒序取 first → 自然读新版本

mock 策略：与 test_revise_qa_loop 一致——FakeProvider 走真实修订路径，
Critic 用 monkeypatch 降级为通过（不干扰版本保留断言）。
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# ── 工具：造行程 + 造 FakeProvider（复刻 test_revise_qa_loop） ──
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


async def _seed_plan(test_engine, trip_id):
    """给行程补一条 completed TripPlan 快照（等同 AI 规划产物）。"""
    from app.models import TripPlan

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        db.add(TripPlan(
            trip_id=trip_id,
            plan_data={"destination": "杭州", "days": [], "budget": {"total_estimated": 0.0}},
            status="completed",
        ))
        await db.commit()


def _db_factory(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _list_plans(test_engine, trip_id):
    from app.models import TripPlan

    factory = _db_factory(test_engine)
    async with factory() as db:
        return list((await db.execute(
            select(TripPlan).where(TripPlan.trip_id == trip_id)
            .order_by(TripPlan.created_at.desc())
        )).scalars().all())


class _DummyReviseLLM:
    """PlanReviseAgent 假 LLM：固定返回修改站点描述的 diff。"""

    _llm_type = "dummy-revise-v"

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
    name = "deepseek"
    model_id = "dummy-revise-v-model"

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


async def _pass_critic(request, plan, *, provider="auto", max_corrections=2):
    return {"status": "completed", "critique": {
        "score": 92, "passed": True, "issues": [], "summary": "修订合理",
    }, "corrections": 0}


# ── 用例 ────────────────────────────────────────────────────
async def test_revise_preserves_previous_version(client, auth_user, monkeypatch, revise_provider, test_engine):
    """Story 3 AC-3：修订产生新版本，保留原版本（archived + 新 completed 快照）。"""
    from app.agent import agents as agents_mod
    from app.models import TripPlan

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    await _seed_plan(test_engine, trip_id)

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _pass_critic)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text

    plans = await _list_plans(test_engine, trip_id)
    assert len(plans) == 2, "修订后应有 2 条快照（原版本 + 新版本）"
    newest, old = plans[0], plans[1]
    assert newest.status == "completed", "最晚 created_at 必须是新版本（completed）"
    assert old.status == "archived", "原版本必须是 archived（保留）"
    assert old.plan_data.get("days") == [], "archived 原版本内容保持修订前状态"
    assert newest.plan_data.get("destination") == "杭州"


async def test_revise_without_plan_snapshot_still_ok(client, auth_user, monkeypatch, revise_provider):
    """无 TripPlan 快照时修订不崩（版本保留是增强，降级为仅主修订）。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _pass_critic)

    resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
        "message": "西湖只留半天", "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["quality"]["passed"] is True


async def test_revise_twice_keeps_two_archived_versions(client, auth_user, monkeypatch, revise_provider, test_engine):
    """连续两次修订：每次保留一个原版本（archived 累计）。"""
    from app.agent import agents as agents_mod

    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    await _seed_plan(test_engine, trip_id)

    monkeypatch.setattr(agents_mod, "revise_critic_agent", _pass_critic)

    for msg in ("西湖只留半天", "楼外楼换到中午"):
        resp = await client.post(f"/api/v1/trips/{trip_id}/revise", json={
            "message": msg, "provider": "deepseek",
        }, headers=headers)
        assert resp.status_code == 200, resp.text

    plans = await _list_plans(test_engine, trip_id)
    # 2 次修订 → 1 条原 created + 2 条 archived = 3 条
    assert len(plans) == 3
    assert plans[0].status == "completed"
    assert all(p.status == "archived" for p in plans[1:])
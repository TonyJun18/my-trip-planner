"""task-property-qa-eval：行程内结构化事实问答专项测试。

覆盖：
1. 意图解析（hours / budget / warning / rating / price / duration / unknown）
2. 营业时间：显式 open_hours → explicit；无 → 类目规则库 rule_based；两无 → unknown 防编造
3. 预算：预设预算 / AI 估算 / 都没有 → unknown
4. 质检预警：有 warning 汇总 / 无 warning 明确回答
5. 评分：details.rating 有/无
6. 站点费用 / 游玩时长：显式 / 规则推断
7. 防编造：无数据绝不编造（available=false + basis=none）
8. 事实清单（无 q）：facts / budget / warnings / suggestions
9. API：鉴权、归属隔离、非法意图
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.property_qa_service import (
    _match_intent,
    answer_property_question,
    collect_property_facts,
)


# ── 纯函数：意图解析 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_match_intent_hours():
    assert _match_intent("西湖几点关门？") == "hours"
    assert _match_intent("灵隐寺营业时间") == "hours"
    assert _match_intent("博物馆开放到几点") == "hours"


@pytest.mark.asyncio
async def test_match_intent_budget():
    assert _match_intent("预算还剩多少？") == "budget"
    assert _match_intent("这趟花了多少钱") == "budget"
    assert _match_intent("总费用多少") == "budget"


@pytest.mark.asyncio
async def test_match_intent_rating_priority():
    """评分词优先于价格词（「评分」含「分」但不应落入时长/价格）。"""
    assert _match_intent("西湖评分怎么样？") == "rating"
    assert _match_intent("这酒店好不好，评分多少") == "rating"


@pytest.mark.asyncio
async def test_match_intent_warning():
    assert _match_intent("行程有什么预警？") == "warning"
    assert _match_intent("有什么需要注意的") == "warning"
    assert _match_intent("第二天为什么有问题") == "warning"


@pytest.mark.asyncio
async def test_match_intent_unknown():
    assert _match_intent("帮我推荐附近的餐厅") is None
    assert _match_intent("明天天气怎么样") is None


# ── 纯函数：营业时间 ──────────────────────────────────────────
def _trip(budget: float | None = 2000, travelers=2):
    from datetime import date

    from app.models import Trip

    return Trip(
        id="trip-1", title="杭州三日", destination="杭州",
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 3),
        travelers=travelers, budget=budget,
    )


def _plan(plan_data: dict):
    from app.models import TripPlan

    return TripPlan(id="plan-1", trip_id="trip-1", plan_data=plan_data, status="completed")


@pytest.mark.asyncio
async def test_hours_explicit():
    """显式 open_hours → explicit 答案。"""
    trip = _trip()
    plan = _plan({"days": [{"day_number": 1, "stops": [
        {"name": "西湖", "type": "attraction", "open_hours": "06:00-22:00"},
    ]}]})
    r = answer_property_question(trip, plan, "西湖几点关门？")
    assert r["matched_type"] == "hours"
    assert r["available"] is True
    assert r["basis"] == "explicit"
    assert "06:00-22:00" in r["answer"]
    assert r["target"] == "西湖"


@pytest.mark.asyncio
async def test_hours_rule_based():
    """无显式 open_hours → 类目规则库推断（rule_based），不编造具体时刻但给惯例区间。"""
    trip = _trip()
    plan = _plan({"days": [{"day_number": 1, "stops": [
        {"name": "西湖", "type": "attraction"},
    ]}]})
    r = answer_property_question(trip, plan, "西湖几点关门？")
    assert r["matched_type"] == "hours"
    assert r["available"] is True
    assert r["basis"] == "rule_based"
    assert "09:00" in r["answer"] and "18:00" in r["answer"]


@pytest.mark.asyncio
async def test_hours_unknown_no_fabrication():
    """既无显式也无规则库 → available=false + basis=none（绝不编造）。"""
    trip = _trip()
    plan = _plan({"days": [{"day_number": 1, "stops": [
        {"name": "神秘景点", "type": "attraction"},
    ]}]})
    # 用不存在的站点名触发 unknown
    r = answer_property_question(trip, plan, "不存在的地方几点关门？")
    assert r["matched_type"] == "hours"
    assert r["available"] is False
    assert r["basis"] == "none"
    assert "暂无" in r["answer"] or "No data" in r["answer"]


@pytest.mark.asyncio
async def test_hours_no_plan_unknown():
    """无 plan 且站点不在落库数据中 → unknown（防编造）。"""
    trip = _trip()
    # 无计划且行程里没有西湖这个站点
    r = answer_property_question(trip, None, "西湖几点关门？")
    assert r["matched_type"] == "hours"
    assert r["available"] is False
    assert r["basis"] == "none"


# ── 纯函数：预算 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_budget_preset_and_estimate():
    trip = _trip(budget=3000)
    plan = _plan({"budget": {"total_estimated": 2450.5, "currency": "CNY",
                             "by_type": {"attraction": 500, "food": 950.5, "hotel": 1000}}})
    r = answer_property_question(trip, plan, "预算还剩多少？")
    assert r["matched_type"] == "budget"
    assert r["available"] is True
    assert "3000" in r["answer"]
    assert "2450.5" in r["answer"]
    assert r["detail"]["preset_budget"] == 3000
    assert r["detail"]["estimated_total"] == 2450.5


@pytest.mark.asyncio
async def test_budget_only_preset():
    trip = _trip(budget=2000)
    r = answer_property_question(trip, None, "预算多少？")
    assert r["matched_type"] == "budget"
    assert r["available"] is True
    assert "2000" in r["answer"]


@pytest.mark.asyncio
async def test_budget_none_unknown():
    trip = _trip(budget=None)
    r = answer_property_question(trip, None, "预算多少？")
    assert r["matched_type"] == "budget"
    assert r["available"] is False
    assert r["basis"] == "none"


# ── 纯函数：质检预警 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_warnings_summary():
    plan = _plan({
        "days": [],
        "time_gate": {"passed": False, "issues": [
            {"severity": "warning", "message": "Day 1 站点过多", "suggestion": "精简"},
        ]},
        "dynamic_facts": {"issues": [
            {"severity": "warning", "message": "故宫周一闭馆"},
        ]},
        "weather_gate": {"issues": []},
    })
    r = answer_property_question(_trip(), plan, "行程有什么预警？")
    assert r["matched_type"] == "warning"
    assert r["available"] is True
    assert "Day 1 站点过多" in r["answer"]
    assert "故宫周一闭馆" in r["answer"]
    assert len(r["detail"]["warnings"]) == 2


@pytest.mark.asyncio
async def test_warnings_none():
    r = answer_property_question(_trip(), None, "有什么预警吗？")
    assert r["matched_type"] == "warning"
    assert r["available"] is True  # 无预警也是确定性事实
    assert r["detail"]["warnings"] == []


# ── 纯函数：评分 / 费用 / 时长 ────────────────────────────────
@pytest.mark.asyncio
async def test_rating_from_details():
    from app.models import Stop, TripDay

    trip = _trip()
    day = TripDay(id="day-1", trip_id="trip-1", day_number=1)
    stop = Stop(id="stop-1", day_id="day-1", name="西湖", stop_type="attraction",
                details={"rating": 4.7})
    day.stops = [stop]
    trip.days = [day]
    r = answer_property_question(trip, None, "西湖评分怎么样？")
    assert r["matched_type"] == "rating"
    assert r["available"] is True
    assert "4.7" in r["answer"]
    assert r["target"] == "西湖"


@pytest.mark.asyncio
async def test_rating_unknown():
    trip = _trip()
    r = answer_property_question(trip, None, "西湖评分怎么样？")
    assert r["matched_type"] == "rating"
    assert r["available"] is False
    assert r["basis"] == "none"


@pytest.mark.asyncio
async def test_price_explicit():
    from app.models import Stop, TripDay

    trip = _trip()
    day = TripDay(id="day-1", trip_id="trip-1", day_number=1)
    stop = Stop(id="stop-1", day_id="day-1", name="灵隐寺", stop_type="attraction",
                estimated_cost=75)
    day.stops = [stop]
    trip.days = [day]
    r = answer_property_question(trip, None, "灵隐寺门票多少钱？")
    assert r["matched_type"] == "price"
    assert r["available"] is True
    assert "75" in r["answer"]
    assert r["basis"] == "explicit"


@pytest.mark.asyncio
async def test_price_unknown():
    trip = _trip()
    r = answer_property_question(trip, None, "西湖门票多少钱？")
    assert r["matched_type"] == "price"
    assert r["available"] is False
    assert r["basis"] == "none"


@pytest.mark.asyncio
async def test_duration_explicit():
    from app.models import Stop, TripDay

    trip = _trip()
    day = TripDay(id="day-1", trip_id="trip-1", day_number=1)
    stop = Stop(id="stop-1", day_id="day-1", name="灵隐寺", stop_type="attraction",
                estimated_duration_minutes=120)
    day.stops = [stop]
    trip.days = [day]
    r = answer_property_question(trip, None, "灵隐寺玩多久？")
    assert r["matched_type"] == "duration"
    assert r["available"] is True
    assert "120" in r["answer"]
    assert r["basis"] == "explicit"


@pytest.mark.asyncio
async def test_duration_rule_based():
    """无显式时长 → 类目基准（120 分钟）rule_based。"""
    from app.models import Stop, TripDay

    trip = _trip()
    day = TripDay(id="day-1", trip_id="trip-1", day_number=1)
    stop = Stop(id="stop-1", day_id="day-1", name="某景点", stop_type="attraction")
    day.stops = [stop]
    trip.days = [day]
    r = answer_property_question(trip, None, "某景点玩多久？")
    assert r["matched_type"] == "duration"
    assert r["available"] is True
    assert r["basis"] == "rule_based"


# ── 纯函数：事实清单 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_collect_facts():
    from app.models import Stop, TripDay

    trip = _trip(budget=2000)
    day = TripDay(id="day-1", trip_id="trip-1", day_number=1)
    day.stops = [
        Stop(id="stop-1", day_id="day-1", name="西湖", stop_type="attraction",
             details={"rating": 4.7}, estimated_cost=0, estimated_duration_minutes=120),
    ]
    trip.days = [day]
    plan = _plan({"days": [{"day_number": 1, "stops": [
        {"name": "西湖", "type": "attraction", "open_hours": "06:00-22:00"},
    ]}], "budget": {"total_estimated": 500}})

    facts = collect_property_facts(trip, plan)
    assert facts["trip_id"] == "trip-1"
    kinds = {(f["kind"], f["target"]) for f in facts["facts"]}
    assert ("hours", "西湖") in kinds
    assert ("rating", "西湖") in kinds
    assert facts["budget"]["estimated_total"] == 500
    assert len(facts["suggestions"]) >= 3
    # 最多 20 条
    assert len(facts["facts"]) <= 20


# ── API 集成 ─────────────────────────────────────────────────
async def _make_trip(client: AsyncClient, headers: dict, budget=2000) -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "QA 测试行程", "destination": "杭州",
        "start_date": "2026-11-01", "end_date": "2026-11-03", "travelers": 2,
        "budget": budget,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_plan(db_session, trip_id: str, plan_data: dict) -> None:
    from app.models import TripPlan

    db_session.add(TripPlan(
        trip_id=trip_id,
        plan_data=plan_data,
        status="completed",
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_property_qa_api_question(client: AsyncClient, auth_user, db_session):
    """API：带 q 回答问题。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    await _add_plan(db_session, trip_id, {
        "days": [{"day_number": 1, "stops": [
            {"name": "西湖", "type": "attraction", "open_hours": "06:00-22:00"},
        ]}],
        "budget": {"total_estimated": 800},
        "time_gate": {"passed": False, "issues": [
            {"severity": "warning", "message": "Day 1 站点过多"},
        ]},
    })

    resp = await client.get(f"/api/v1/trips/{trip_id}/property-qa",
                            params={"q": "西湖几点关门？"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched_type"] == "hours"
    assert body["available"] is True
    assert body["target"] == "西湖"
    assert "06:00-22:00" in body["answer"]


@pytest.mark.asyncio
async def test_property_qa_api_facts(client: AsyncClient, auth_user, db_session):
    """API：不带 q 返回事实清单。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, budget=2000)
    await _add_plan(db_session, trip_id, {
        "days": [{"day_number": 1, "stops": [
            {"name": "西湖", "type": "attraction"},
        ]}],
    })

    resp = await client.get(f"/api/v1/trips/{trip_id}/property-qa", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trip_id"] == trip_id
    assert body["budget"]["preset_budget"] == 2000
    assert isinstance(body["facts"], list)
    assert len(body["suggestions"]) >= 3


@pytest.mark.asyncio
async def test_property_qa_requires_auth(client: AsyncClient):
    """未登录 401。"""
    resp = await client.get("/api/v1/trips/abc/property-qa")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_property_qa_owner_isolation(client: AsyncClient, auth_user, db_session):
    """归属隔离：他人不能查我的行程属性问答。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    other = await client.post("/api/v1/auth/register", json={
        "email": "other-qa@test.com", "password": "test1234", "display_name": "他者",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.get(f"/api/v1/trips/{trip_id}/property-qa",
                            params={"q": "西湖几点关门？"}, headers=other_headers)
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_property_qa_unknown_intent_api(client: AsyncClient, auth_user, db_session):
    """无法识别意图 → 明确说明能力边界（不编造）。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    resp = await client.get(f"/api/v1/trips/{trip_id}/property-qa",
                            params={"q": "帮我推荐附近的餐厅"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched_type"] == "unknown"
    assert body["available"] is False
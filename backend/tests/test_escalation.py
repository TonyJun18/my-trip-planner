"""task-human-escalation-eval：人工兜底最小版专项测试。

覆盖：
1. escalate_from_quality 纯函数：finalized / passed=false / degraded / 正常通过 / None 五路径
2. escalation_summary：理由/摘要/issues 截断/score
3. API GET /trips/escalations：owner 评审队列含 escalated 行程、排除正常行程、无 plan 不报错
4. API 归属隔离：他人看不见我的 escalated 行程
5. TripOut.escalated 派生：详情/列表带出标记（model_validate from_attributes）
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.escalation_service import escalate_from_quality, escalation_summary


# ── 纯函数：escalate_from_quality ──────────────────────────────
@pytest.mark.asyncio
async def test_escalate_finalized():
    """达最大评审轮强制定稿 → 升级。"""
    assert escalate_from_quality({"finalized": True, "passed": True, "score": 75})


@pytest.mark.asyncio
async def test_escalate_low_confidence():
    """Critic 未通过（passed=false）→ 升级。"""
    assert escalate_from_quality({"finalized": False, "passed": False, "score": 60})


@pytest.mark.asyncio
async def test_escalate_degraded():
    """Critic 调用失败降级通过 → 升级（健康风险信号）。"""
    assert escalate_from_quality({"finalized": False, "passed": True, "degraded": True})


@pytest.mark.asyncio
async def test_escalate_pass_not_escalated():
    """正常通过（高/低分但不 false）→ 不升级。"""
    assert not escalate_from_quality({"finalized": False, "passed": True, "score": 92})
    # 通过但分不高 → 不误报（判定只看 passed/finalized/degraded）
    assert not escalate_from_quality({"finalized": False, "passed": True, "score": 70})


@pytest.mark.asyncio
async def test_escalate_none_or_empty():
    """无 quality / 空 dict → 不升级。"""
    assert not escalate_from_quality(None)
    assert not escalate_from_quality({})


# ── 纯函数：escalation_summary ─────────────────────────────────
@pytest.mark.asyncio
async def test_escalation_summary_reason_priority():
    """理由优先级：finalized 优先于 low_confidence。"""
    q = escalation_summary({"finalized": True, "passed": False, "score": 60,
                            "summary": "太赶", "issues": [{"severity": "critical"}]})
    assert q["reason"] == "finalized"
    assert q["summary"] == "太赶"
    assert q["score"] == 60
    assert len(q["issues"]) == 1


@pytest.mark.asyncio
async def test_escalation_summary_issues_truncated():
    """issues 最多截断 5 条。"""
    q = escalation_summary({"finalized": True, "issues": [{"i": n} for n in range(9)]})
    assert len(q["issues"]) == 5


@pytest.mark.asyncio
async def test_escalation_summary_none():
    """无 quality → 空摘要。"""
    q = escalation_summary(None)
    assert q["reason"] is None
    assert q["issues"] == []


# ── API：评审队列 ──────────────────────────────────────────────
async def _make_trip(client: AsyncClient, headers: dict, title: str = "评审测试行程") -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": title, "destination": "杭州",
        "start_date": "2026-11-01", "end_date": "2026-11-02", "travelers": 2,
        "budget": 3000,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_plan(db_session, trip_id: str, quality: dict | None, *, status: str = "completed") -> None:
    from app.models import TripPlan

    db_session.add(TripPlan(
        trip_id=trip_id,
        plan_data={"quality": quality, "days": []},
        status=status,
    ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_escalations_list_only_escalated(client: AsyncClient, auth_user, db_session):
    """评审队列：只含命中信号的行程，正常/无 plan 行程排除。"""
    _user, headers = auth_user

    # 1 个 escalated（finalized）
    esc_id = await _make_trip(client, headers, "被迫定稿行程")
    await _add_plan(db_session, esc_id, {"finalized": True, "passed": True, "score": 72,
                                         "summary": "达最大评审轮强制定稿"})
    # 1 个正常通过
    ok_id = await _make_trip(client, headers, "正常行程")
    await _add_plan(db_session, ok_id, {"finalized": False, "passed": True, "score": 90})
    # 1 个无 plan（手工行程）
    await _make_trip(client, headers, "手工行程")

    resp = await client.get("/api/v1/trips/escalations", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["trip_id"] == esc_id
    assert body["items"][0]["destination"] == "杭州"
    assert body["items"][0]["quality"]["reason"] == "finalized"
    assert body["items"][0]["quality"]["summary"] == "达最大评审轮强制定稿"
    assert body["items"][0]["quality"]["score"] == 72


@pytest.mark.asyncio
async def test_escalations_owner_isolation(client: AsyncClient, auth_user, db_session):
    """归属隔离：他人看不到我的评审队列。"""
    _user, headers = auth_user
    esc_id = await _make_trip(client, headers, "我的待复核行程")
    await _add_plan(db_session, esc_id, {"finalized": True, "passed": False, "score": 55})

    # 注册第二个用户
    other = await client.post("/api/v1/auth/register", json={
        "email": "other-escalation@test.com", "password": "test1234", "display_name": "他者",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.get("/api/v1/trips/escalations", headers=other_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_escalations_requires_auth(client: AsyncClient):
    """评审队列需要登录。"""
    resp = await client.get("/api/v1/trips/escalations")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_escalations_pagination(client: AsyncClient, auth_user, db_session):
    """分页：limit/offset 生效，total 为全量。"""
    _user, headers = auth_user
    for i in range(3):
        tid = await _make_trip(client, headers, f"待复核{i}")
        await _add_plan(db_session, tid, {"finalized": True, "passed": False, "score": 50})

    resp = await client.get("/api/v1/trips/escalations?limit=2&offset=0", headers=headers)
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    resp2 = await client.get("/api/v1/trips/escalations?limit=2&offset=2", headers=headers)
    assert len(resp2.json()["items"]) == 1


# ── TripOut.escalated 派生（详情/列表带出标记） ─────────────────
@pytest.mark.asyncio
async def test_trip_detail_escalated_flag(client: AsyncClient, auth_user, db_session):
    """详情 TripOut：escalated 派生透出（finalized 行程标记 true）。"""
    _user, headers = auth_user
    esc_id = await _make_trip(client, headers, "详情待复核")
    await _add_plan(db_session, esc_id, {"finalized": True, "passed": True, "score": 70})

    resp = await client.get(f"/api/v1/trips/{esc_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["escalated"] is True


@pytest.mark.asyncio
async def test_trip_detail_escalated_false_when_ok(client: AsyncClient, auth_user, db_session):
    """详情 TripOut：正常通过 → escalated=false。"""
    _user, headers = auth_user
    ok_id = await _make_trip(client, headers, "详情正常")
    await _add_plan(db_session, ok_id, {"finalized": False, "passed": True, "score": 95})

    resp = await client.get(f"/api/v1/trips/{ok_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["escalated"] is False


@pytest.mark.asyncio
async def test_trip_list_escalated_flag(client: AsyncClient, auth_user, db_session):
    """列表 TripListOut：escalated 派生带出（无 plan 行程 default False）。"""
    _user, headers = auth_user
    esc_id = await _make_trip(client, headers, "列表待复核")
    await _add_plan(db_session, esc_id, {"finalized": True, "passed": False, "score": 45})
    await _make_trip(client, headers, "无计划行程")

    resp = await client.get("/api/v1/trips", headers=headers)
    assert resp.status_code == 200, resp.text
    by_id = {t["id"]: t for t in resp.json()["items"]}
    assert by_id[esc_id]["escalated"] is True
    assert any(t["escalated"] is False and t["title"] == "无计划行程" for t in by_id.values())
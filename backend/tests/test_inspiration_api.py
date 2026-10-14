"""test_inspiration_api.py —— 灵感优先目的地推荐 API 测试。

覆盖：
- GET /trips/inspiration 未登录 → 401（与行程 API 同一鉴权语义）
- 兴趣/预算/季节/limit 参数组合 → 返回卡片 + 统计 + 口径标注
- 无兴趣 → note 提示 + 预算可负担过滤
"""
from __future__ import annotations

import uuid

from app.services.inspiration_service import BUDGET_TIER_LABEL


def _rand_email() -> str:
    return f"insp-{uuid.uuid4().hex[:8]}@test.com"


async def _register(client) -> dict:
    email = _rand_email()
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test1234", "display_name": "灵感用户"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_inspiration_requires_login(client):
    resp = await client.get("/api/v1/trips/inspiration")
    assert resp.status_code == 401


async def test_inspiration_returns_cards(client):
    headers = await _register(client)
    resp = await client.get(
        "/api/v1/trips/inspiration",
        params={"interests": "food,nature", "budget_tier": "comfort", "season": "spring", "limit": 5},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["items"], list) and 1 <= len(body["items"]) <= 5
    card = body["items"][0]
    for field in ("name", "country", "reason", "play", "est_daily_budget", "suggested_days",
                  "budget_tier", "best_season", "match_score", "matched_tags", "season_note", "basis"):
        assert field in card, f"卡片缺字段 {field}"
    assert card["basis"] == "rule_based"
    # 统计口径
    assert body["counts"]["matched"] == 2
    assert body["counts"]["season_filter"] is True
    assert body["counts"]["budget_tier"] == "comfort"
    assert body["note"]


async def test_inspiration_no_interests_budget_filter(client):
    headers = await _register(client)
    resp = await client.get(
        "/api/v1/trips/inspiration",
        params={"budget_tier": "economy", "limit": 5},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["counts"]["matched"] == 0
    # 预算诚实：economy 档只返回 economy 目的地
    assert {it["budget_tier"] for it in body["items"]} == {"economy"}
    assert "可负担" in body["note"]


async def test_inspiration_invalid_tier_422(client):
    headers = await _register(client)
    resp = await client.get(
        "/api/v1/trips/inspiration",
        params={"budget_tier": "gold"},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_inspiration_limit_validates(client):
    headers = await _register(client)
    resp = await client.get(
        "/api/v1/trips/inspiration",
        params={"limit": 9},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_inspiration_season_note_visible(client):
    headers = await _register(client)
    resp = await client.get(
        "/api/v1/trips/inspiration",
        params={"season": "winter", "budget_tier": "comfort", "limit": 5},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    # 冬季最佳目的地（哈尔滨/西双版纳）进入前 5，且无季节提示（当季标杆）
    names = {it["name"] for it in items}
    assert "哈尔滨" in names, "当季最佳目的地应进入推荐"
    hrb = next(it for it in items if it["name"] == "哈尔滨")
    assert hrb["season_note"] == "", "当季最佳不应带季节提示"


async def test_inspiration_tier_labels_are_stable(client):
    """budget_tier 的标签表与后端档位对齐（前端硬编码 4 档）。"""
    assert set(BUDGET_TIER_LABEL.keys()) == {"economy", "comfort", "quality", "luxury"}
"""task-floattrip-borrow Story 2：旅行记忆偏好条目 CRUD + 注入优先级 测试。

覆盖 Acceptance Criteria：
- GET /api/v1/profile/preferences 返回可读条目列表（含来源、更新时间）
- POST/PUT/DELETE /api/v1/profile/preferences 新增/编辑/删除（忘记）
- 规划注入时显式声明「本次明确需求优先于历史画像」；同一主题本次覆盖历史
- 删除条目后规划上下文不再注入
- 旧自由格式 preferences_json 兼容（读取归一为 legacy 条目）
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.agent import agents
from app.models import PlanTask, User, UserProfile


async def _make_user(db_session, uid: str) -> User:
    """测试 helper：先建 User（满足 user_profiles.user_id 外键）。"""
    user = User(id=uid, email=f"{uid}@test.com")
    db_session.add(user)
    await db_session.flush()
    return user


# ── 1. 服务层：CRUD 纯逻辑 ────────────────────────────────────
async def test_add_and_list_items(db_session):
    from app.services import preference_item_service as svc

    uid = f"u-{uuid.uuid4().hex[:8]}"
    await _make_user(db_session, uid)
    item = await svc.add_item(db_session, user_id=uid, category="diet", content="不吃辣")
    assert item["source"] == "user"
    assert item["content"] == "不吃辣"
    assert item["id"]

    items, total = await svc.list_items(db_session, user_id=uid)
    assert total == 1
    assert items[0]["content"] == "不吃辣"
    assert items[0]["source"] == "user"
    assert "updated_at" in items[0]


async def test_update_item(db_session):
    from app.services import preference_item_service as svc

    uid = f"u-{uuid.uuid4().hex[:8]}"
    await _make_user(db_session, uid)
    item = await svc.add_item(db_session, user_id=uid, category="other", content="喜欢博物馆")
    updated = await svc.update_item(
        db_session, user_id=uid, item_id=item["id"],
        category="interest", content="喜欢美术馆",
    )
    assert updated is not None
    assert updated["category"] == "interest"
    assert updated["content"] == "喜欢美术馆"

    items, _ = await svc.list_items(db_session, user_id=uid)
    assert len(items) == 1
    assert items[0]["category"] == "interest"


async def test_delete_item(db_session):
    from app.services import preference_item_service as svc

    uid = f"u-{uuid.uuid4().hex[:8]}"
    await _make_user(db_session, uid)
    item = await svc.add_item(db_session, user_id=uid, category="other", content="不坐夜车")
    ok = await svc.delete_item(db_session, user_id=uid, item_id=item["id"])
    assert ok is True
    items, total = await svc.list_items(db_session, user_id=uid)
    assert total == 0

    # 再删一次 → False（不存在）
    assert await svc.delete_item(db_session, user_id=uid, item_id=item["id"]) is False


async def test_update_missing_returns_none(db_session):
    from app.services import preference_item_service as svc

    uid = f"u-{uuid.uuid4().hex[:8]}"
    await _make_user(db_session, uid)
    assert await svc.update_item(db_session, user_id=uid, item_id="nope", content="x") is None


# ── 2. 注入优先级：本次需求优先于历史画像 ───────────────────────
def test_items_to_text_priority_statement():
    from app.services.preference_item_service import items_to_text

    text = items_to_text([
        {"id": "1", "category": "diet", "content": "不吃辣", "source": "user", "updated_at": "x"},
    ])
    assert "旅行记忆" in text
    assert "不吃辣" in text
    # AC-3：显式优先级声明
    assert "本次" in text
    assert "优先于" in text
    assert "历史记忆" in text or "历史画像" in text


def test_items_to_text_marks_rule_source():
    from app.services.preference_item_service import items_to_text

    text = items_to_text([
        {"id": "1", "category": "other", "content": "常去杭州", "source": "rule", "updated_at": "x"},
    ])
    assert "【系统推断】" in text


def test_items_to_text_empty():
    from app.services.preference_item_service import items_to_text

    assert items_to_text([]) == ""
    assert items_to_text([{"id": "1", "category": "other", "content": "", "source": "user"}]) == ""


# ── 3. API：CRUD ──────────────────────────────────────────────
async def test_preferences_api_flow(client, auth_user):
    _, headers = auth_user

    # 空画像 → 空列表
    resp = await client.get("/api/v1/profile/preferences", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0

    # 新增
    resp = await client.post("/api/v1/profile/preferences", json={
        "category": "diet", "content": "不吃辣",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    item = resp.json()
    assert item["content"] == "不吃辣"
    assert item["source"] == "user"
    assert item["id"]
    assert item["updated_at"]

    # 列表读回
    resp = await client.get("/api/v1/profile/preferences", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == item["id"]

    # 编辑
    resp = await client.put(f"/api/v1/profile/preferences/{item['id']}", json={
        "category": "interest", "content": "喜欢古建",
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "interest"
    assert resp.json()["content"] == "喜欢古建"

    # 删除（忘记）
    resp = await client.delete(f"/api/v1/profile/preferences/{item['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get("/api/v1/profile/preferences", headers=headers)
    assert resp.json()["total"] == 0


async def test_preferences_api_missing_item_404(client, auth_user):
    _, headers = auth_user
    resp = await client.put("/api/v1/profile/preferences/nope", json={"content": "x"}, headers=headers)
    assert resp.status_code == 404
    resp = await client.delete("/api/v1/profile/preferences/nope", headers=headers)
    assert resp.status_code == 404


async def test_preferences_api_requires_auth(client):
    resp = await client.get("/api/v1/profile/preferences")
    assert resp.status_code == 401
    resp = await client.post("/api/v1/profile/preferences", json={"content": "x"})
    assert resp.status_code == 401


# ── 4. 删除后不再注入（AC-4 + 旧数据兼容） ──────────────────────
async def test_profile_for_request_includes_items_after_delete_excluded(db_session):
    """新增条目 → profile_for_request 注入；删除后不再注入。"""
    from app.services import preference_item_service as svc
    from app.services import profile_service

    uid = f"u-{uuid.uuid4().hex[:8]}"
    await _make_user(db_session, uid)
    item = await svc.add_item(db_session, user_id=uid, category="diet", content="不吃香菜")
    await db_session.flush()  # 让 profile 可见

    ctx = await profile_service.profile_for_request(db_session, user_id=uid)
    assert "不吃香菜" in ctx["profile_text"]
    assert "优先于" in ctx["profile_text"]  # AC-3

    # 删除（忘记）后 → 不再注入
    await svc.delete_item(db_session, user_id=uid, item_id=item["id"])
    await db_session.flush()
    ctx2 = await profile_service.profile_for_request(db_session, user_id=uid)
    assert "不吃香菜" not in (ctx2.get("profile_text") or "")


async def test_legacy_freeform_preferences_normalized(db_session):
    """旧自由格式 preferences_json（无 items 键）读取时归一为 legacy 条目，不丢数据。"""
    from sqlalchemy import select

    from app.services import preference_item_service as svc
    from app.services import profile_service

    uid = f"u-{uuid.uuid4().hex[:8]}"
    await _make_user(db_session, uid)
    profile = UserProfile(user_id=uid, preferences_json={"avoid": ["辣"], "theme": "自然"})
    db_session.add(profile)
    await db_session.flush()

    items, total = await svc.list_items(db_session, user_id=uid)
    assert total == 2  # legacy 归一为 2 条
    assert any("avoid" in i["content"] for i in items)
    assert any("theme" in i["content"] for i in items)

    # 注入也带 legacy 内容（来源 user，不丢）
    ctx = await profile_service.profile_for_request(db_session, user_id=uid)
    assert "avoid" in (ctx.get("profile_text") or "") or "辣" in (ctx.get("profile_text") or "")


# ── 5. 端到端：规划请求注入偏好条目（轻量：只验证 request_data 快照） ──
async def test_plan_request_snapshot_injects_preferences(client, auth_user, db_session, monkeypatch):
    """提交规划 → request_data.profile_text 含偏好条目与优先级声明。"""
    from app.services import preference_item_service as svc

    _, headers = auth_user
    # 直接为当前用户建画像 + 偏好条目（登录用户 id 从 auth_user 返回取）
    user_info, _ = auth_user
    uid = user_info["id"]
    await svc.add_item(db_session, user_id=uid, category="diet", content="不吃辣")
    await db_session.commit()

    today = date.today()
    resp = await client.post("/api/v1/planner/plan", json={
        "destination": "成都",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
        "provider": "deepseek",
    }, headers=headers)
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    stmt = select(PlanTask).where(PlanTask.id == task_id)
    task = (await db_session.execute(stmt)).scalar_one()
    assert "不吃辣" in (task.request_data.get("profile_text") or "")
    assert "优先于" in (task.request_data.get("profile_text") or "")
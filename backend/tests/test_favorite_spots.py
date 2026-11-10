"""task-social-favorites-flow-eval 测试：收藏地点（collect-first 底座）。

验收（docs/night-build-todo.md 2026-11-10）：
1. 导入候选可批量收藏为「收藏地点」（幂等：重复名跳过）
2. 收集箱列表（倒序）/ 删除（本人，404 越权）
3. 外部内容按敌意源处理：只取结构化字段，来源片段仅展示不执行
4. API：登录必需、超量 422
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import NotFoundError
from app.services.favorite_spots_service import (
    collect_spots,
    list_spots,
    normalize_spot_key,
    remove_spot,
)
from app.schemas.favorite_spots import FavoriteSpotIn


def _uid(auth_user) -> SimpleNamespace:
    """从 auth_user fixture 提取真实 user id（favorite_spots.user_id 有外键约束）。"""
    user_info, _headers = auth_user
    return SimpleNamespace(id=user_info["id"])


def _spot(name: str, **kw) -> FavoriteSpotIn:
    return FavoriteSpotIn(name=name, **kw)


async def _register_second(client) -> dict:
    """注册第二个用户（越权测试用），返回 auth headers。"""
    import uuid

    email = f"other-{uuid.uuid4().hex[:8]}@test.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test1234", "display_name": "路人乙"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── 1. 服务层：收藏 ─────────────────────────────────────────────
class TestCollectSpots:
    async def test_collect_basic(self, db_session, auth_user):
        """批量收藏：新增 + 返回计数。"""
        user = _uid(auth_user)
        result = await collect_spots(
            db_session,
            user,
            [
                _spot("西湖", stop_type="attraction", estimated_cost=0),
                _spot("灵隐寺", stop_type="attraction"),
                _spot("楼外楼餐厅", stop_type="food"),
            ],
        )
        assert result["collected"] == 3
        assert result["skipped"] == 0
        assert result["total"] == 3

        data = await list_spots(db_session, user)
        assert data["total"] == 3
        names = {s.name for s in data["items"]}
        assert names == {"西湖", "灵隐寺", "楼外楼餐厅"}

    async def test_collect_idempotent_dedup(self, db_session, auth_user):
        """重复收藏同一地点：幂等跳过；归一化（去空白+小写）也视为重复。"""
        user = _uid(auth_user)
        await collect_spots(db_session, user, [_spot("西湖"), _spot("灵隐寺")])

        result = await collect_spots(
            db_session,
            user,
            [_spot("西湖"), _spot(" 灵隐寺 "), _spot("新地点")],
        )
        assert result["collected"] == 1
        assert result["skipped"] == 2
        assert result["total"] == 3

        data = await list_spots(db_session, user)
        assert data["total"] == 3

    async def test_collect_blank_name_skipped(self, db_session, auth_user):
        """纯空白名被服务层跳过，不落库（空串已由 schema min_length 拒绝）。"""
        user = _uid(auth_user)
        result = await collect_spots(
            db_session,
            user,
            [_spot("   "), _spot("　"), _spot("有效地点")],
        )
        assert result["collected"] == 1
        assert result["skipped"] == 2

        data = await list_spots(db_session, user)
        assert data["total"] == 1
        assert data["items"][0].name == "有效地点"

    async def test_schema_rejects_empty_name(self):
        """空串名在 schema 层被拒绝（422 的底层保证）。"""
        with pytest.raises(Exception):
            _spot("")

    async def test_collect_user_isolated(self, db_session, auth_user, client):
        """A 的收藏不会被 B 看到（B 走 API 注册，服务层用 db_session 查）。"""
        await collect_spots(db_session, _uid(auth_user), [_spot("西湖")])

        # B 通过 API 列表（走同一 test_engine）
        headers_b = await _register_second(client)
        resp = await client.get("/api/v1/trips/favorite-spots", headers=headers_b)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_normalize_key(self):
        """归一化：去空白 + 小写。"""
        assert normalize_spot_key(" 西湖 景区 ") == "西湖景区"
        assert normalize_spot_key("In77 商场") == "in77商场"
        assert normalize_spot_key("") == ""


# ── 2. 服务层：列表 / 删除 ──────────────────────────────────────
class TestListRemove:
    async def test_list_orders_by_created_desc(self, db_session, auth_user):
        """列表按收藏时间倒序（新收藏在前）。"""
        user = _uid(auth_user)
        await collect_spots(db_session, user, [_spot("第一个"), _spot("第二个")])
        await collect_spots(db_session, user, [_spot("第三个")])
        data = await list_spots(db_session, user)
        names = [s.name for s in data["items"]]
        assert names[0] == "第三个"

    async def test_remove_own_spot(self, db_session, auth_user):
        """删除自己的收藏：成功且列表减少。"""
        user = _uid(auth_user)
        await collect_spots(db_session, user, [_spot("西湖"), _spot("灵隐寺")])
        data = await list_spots(db_session, user)
        spot_id = data["items"][0].id

        await remove_spot(db_session, user, spot_id)
        after = await list_spots(db_session, user)
        assert after["total"] == 1
        assert all(s.id != spot_id for s in after["items"])

    async def test_remove_other_user_spot_404(self, db_session, auth_user, client):
        """删除别人的收藏：404（越权保护）。"""
        await collect_spots(db_session, _uid(auth_user), [_spot("西湖")])
        data = await list_spots(db_session, _uid(auth_user))
        spot_id = data["items"][0].id

        # B 通过 API 尝试删除 A 的收藏 → 404
        headers_b = await _register_second(client)
        resp = await client.delete(f"/api/v1/trips/favorite-spots/{spot_id}", headers=headers_b)
        assert resp.status_code == 404

    async def test_remove_missing_404(self, db_session, auth_user):
        """删除不存在的收藏：404。"""
        with pytest.raises(NotFoundError):
            await remove_spot(db_session, _uid(auth_user), "no-such-id")


# ── 3. API 层 ───────────────────────────────────────────────────
class TestFavoriteSpotsApi:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/v1/trips/favorite-spots/batch", json={"spots": []})
        assert resp.status_code == 401

        resp = await client.get("/api/v1/trips/favorite-spots")
        assert resp.status_code == 401

    async def test_batch_collect_api(self, client, auth_user):
        _, headers = auth_user
        resp = await client.post(
            "/api/v1/trips/favorite-spots/batch",
            json={
                "spots": [
                    {"name": "西湖", "stop_type": "attraction"},
                    {"name": "灵隐寺", "stop_type": "attraction", "estimated_cost": 75},
                ]
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["collected"] == 2
        assert body["skipped"] == 0

    async def test_batch_collect_idempotent_api(self, client, auth_user):
        _, headers = auth_user
        payload = {"spots": [{"name": "西湖"}, {"name": "灵隐寺"}]}
        first = await client.post("/api/v1/trips/favorite-spots/batch", json=payload, headers=headers)
        assert first.status_code == 200
        second = await client.post(
            "/api/v1/trips/favorite-spots/batch",
            json={"spots": [{"name": "西湖"}, {"name": "新地点"}]},
            headers=headers,
        )
        body = second.json()
        assert body["collected"] == 1
        assert body["skipped"] == 1

    async def test_list_and_delete_api(self, client, auth_user):
        _, headers = auth_user
        await client.post(
            "/api/v1/trips/favorite-spots/batch",
            json={"spots": [{"name": "西湖"}]},
            headers=headers,
        )
        listed = await client.get("/api/v1/trips/favorite-spots", headers=headers)
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] == 1
        spot_id = body["items"][0]["id"]

        deleted = await client.delete(f"/api/v1/trips/favorite-spots/{spot_id}", headers=headers)
        assert deleted.status_code == 204
        after = await client.get("/api/v1/trips/favorite-spots", headers=headers)
        assert after.json()["total"] == 0

    async def test_delete_other_user_404_api(self, client, auth_user):
        _, headers_a = auth_user
        headers_b = await _register_second(client)
        await client.post(
            "/api/v1/trips/favorite-spots/batch",
            json={"spots": [{"name": "西湖"}]},
            headers=headers_a,
        )
        listed = await client.get("/api/v1/trips/favorite-spots", headers=headers_a)
        spot_id = listed.json()["items"][0]["id"]

        resp = await client.delete(f"/api/v1/trips/favorite-spots/{spot_id}", headers=headers_b)
        assert resp.status_code == 404

    async def test_too_many_spots_422(self, client, auth_user):
        _, headers = auth_user
        spots = [{"name": f"地点{i}"} for i in range(60)]
        resp = await client.post(
            "/api/v1/trips/favorite-spots/batch",
            json={"spots": spots},
            headers=headers,
        )
        assert resp.status_code == 422
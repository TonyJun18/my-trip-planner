"""收藏地点 → 一键成路线 测试（task-favorites-spots-to-route 第二段聚合）。

覆盖：
- 纯函数 assign_spots_to_days：酒店锚定每日首位 / 每天 ≤ 5 站 / 坐标字典序 /
  缺坐标回退勾选顺序 / 溢出（others 溢出 + hotel 溢出）计数 / 空输入
- 服务层 create_route_from_spots：只读本人收藏（skipped 计数）、全无效 400、
  单事务批量建 Trip+Days+Stops、TripOut 可序列化、原收集箱不变
- API：401 / 201（含报告）/ 400 全无效 / 越权（他人收藏不可见）
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.models import FavoriteSpot, Stop, Trip
from app.schemas.favorite_spots import FavoriteRouteIn
from app.services.favorite_spots_route_service import (
    assign_spots_to_days,
    create_route_from_spots,
)
from app.services.favorite_spots_service import collect_spots
from app.schemas.favorite_spots import FavoriteSpotIn


def _spot(name: str, stop_type: str = "attraction", lat=None, lng=None) -> FavoriteSpotIn:
    return FavoriteSpotIn(name=name, stop_type=stop_type, lat=lat, lng=lng)


def _spot_dict(name: str, stop_type: str = "attraction", lat=None, lng=None) -> dict:
    return {
        "id": f"id-{name}",
        "name": name,
        "stop_type": stop_type,
        "lat": lat,
        "lng": lng,
        "description": None,
        "estimated_cost": None,
        "estimated_duration_minutes": None,
    }


def _uid(auth_user):
    user_info, _headers = auth_user
    return SimpleNamespace(id=user_info["id"])


# ── 1. 纯函数：确定性分天 ──────────────────────────────────────
class TestAssignSpotsToDays:
    def test_hotel_anchors_first_per_day(self):
        """酒店每天至多 1 家且置首位；非酒店排其后。"""
        spots = [
            _spot_dict("西湖", lat=30.2, lng=120.1),
            _spot_dict("酒店A", "hotel", lat=30.3, lng=120.2),
            _spot_dict("灵隐寺", lat=30.25, lng=120.05),
        ]
        out = assign_spots_to_days(spots, days=2, start_date=date(2026, 11, 1))
        assert out["placed"] == 3
        assert out["overflow"] == 0
        assert out["hotel_overflow"] == 0
        # 酒店进第 1 天首位
        day1 = out["days"][0]
        assert day1["stops"][0]["name"] == "酒店A"
        assert day1["stops"][0]["stop_type"] == "hotel"

    def test_max_five_per_day(self):
        """每天 ≤ 5 站：5 站 1 天可全放；6 站 → overflow=1。"""
        six = [_spot_dict(f"点{i}", lat=30.0 + i, lng=120.0 + i) for i in range(6)]
        out = assign_spots_to_days(six, days=1, start_date=date(2026, 11, 1))
        assert out["placed"] == 5
        assert out["overflow"] == 1
        assert len(out["days"][0]["stops"]) == 5

    def test_coord_sort_deterministic(self):
        """全部有坐标 → 按 (lat,lng) 字典序，同输入同输出。"""
        spots = [
            _spot_dict("B点", lat=30.5, lng=120.1),
            _spot_dict("A点", lat=30.1, lng=120.2),
            _spot_dict("C点", lat=30.5, lng=119.9),
        ]
        out = assign_spots_to_days(spots, days=1, start_date=date(2026, 11, 1))
        names = [s["name"] for s in out["days"][0]["stops"]]
        assert names == ["A点", "C点", "B点"]
        # 确定性：再跑一次同结果
        out2 = assign_spots_to_days(spots, days=1, start_date=date(2026, 11, 1))
        assert [s["name"] for s in out2["days"][0]["stops"]] == names

    def test_missing_coords_falls_back_to_selection_order(self):
        """缺坐标 → 保持勾选顺序（不丢弃不报错）。"""
        spots = [
            _spot_dict("无坐标A"),
            _spot_dict("无坐标B"),
            _spot_dict("有坐标C", lat=30.1, lng=120.1),
        ]
        out = assign_spots_to_days(spots, days=1, start_date=date(2026, 11, 1))
        names = [s["name"] for s in out["days"][0]["stops"]]
        # 存在缺坐标 → 全部不排序，保持原顺序
        assert names == ["无坐标A", "无坐标B", "有坐标C"]

    def test_hotel_overflow(self):
        """酒店数 > 天数 → 溢出部分计 hotel_overflow。"""
        spots = [
            _spot_dict("酒店1", "hotel"),
            _spot_dict("酒店2", "hotel"),
            _spot_dict("酒店3", "hotel"),
        ]
        out = assign_spots_to_days(spots, days=2, start_date=date(2026, 11, 1))
        assert out["placed"] == 2
        assert out["hotel_overflow"] == 1
        assert out["overflow"] == 0
        assert len(out["days"]) == 2  # 两天各 1 家酒店

    def test_empty_input(self):
        """空输入：空结果，不报错。"""
        out = assign_spots_to_days([], days=1, start_date=date(2026, 11, 1))
        assert out["placed"] == 0
        assert out["overflow"] == 0
        assert out["hotel_overflow"] == 0
        assert out["days"] == []

    def test_invalid_days_raises(self):
        with pytest.raises(ValueError):
            assign_spots_to_days([_spot_dict("x")], days=0, start_date=date(2026, 11, 1))


# ── 2. 服务层：从收藏地点生成行程 ──────────────────────────────
class TestCreateRouteFromSpots:
    async def _seed_spots(self, db_session, auth_user, names):
        """把给定地点收藏进收集箱，返回 {name: spot_id}。"""
        await collect_spots(
            db_session,
            _uid(auth_user),
            [_spot(name, stop_type="attraction", lat=30.0, lng=120.0) for name in names],
        )
        rows = list(
            (await db_session.execute(select(FavoriteSpot).where(FavoriteSpot.user_id == _uid(auth_user).id)))
            .scalars()
            .all()
        )
        return {s.name: s.id for s in rows}

    async def test_create_basic(self, db_session, auth_user):
        """2 地点 1 天 → 新草稿行程有 1 day / 2 stops，字段正确。"""
        spot_ids = await self._seed_spots(db_session, auth_user, ["西湖", "灵隐寺"])
        data = FavoriteRouteIn(
            spot_ids=[spot_ids["西湖"], spot_ids["灵隐寺"]],
            title="杭州快闪",
            destination="杭州",
            start_date=date(2026, 11, 1),
            days=1,
            travelers=2,
        )
        out = await create_route_from_spots(db_session, _uid(auth_user), data)
        trip = out["trip"]
        assert trip.owner == auth_user[0]["id"]
        assert trip.status == "draft"
        assert trip.share_token is None and trip.edit_token is None
        assert trip.title == "杭州快闪"
        assert trip.destination == "杭州"
        assert trip.start_date == date(2026, 11, 1)
        assert trip.end_date == date(2026, 11, 1)
        assert len(trip.days) == 1
        stops = trip.days[0].stops
        assert [s.name for s in stops] == ["西湖", "灵隐寺"]
        assert all(s.checked is False for s in stops)
        assert out["report"] == {"placed": 2, "overflow": 0, "hotel_overflow": 0, "skipped": 0}

    async def test_skipped_unknown_ids(self, db_session, auth_user):
        """不存在的 id → skipped 计数；有效 id 仍成行。"""
        spot_ids = await self._seed_spots(db_session, auth_user, ["西湖"])
        data = FavoriteRouteIn(
            spot_ids=[spot_ids["西湖"], "no-such-id"],
            title="t", destination="d", start_date=date(2026, 11, 1), days=1,
        )
        out = await create_route_from_spots(db_session, _uid(auth_user), data)
        assert out["report"]["skipped"] == 1
        assert out["report"]["placed"] == 1
        assert [s.name for s in out["trip"].days[0].stops] == ["西湖"]

    async def test_all_invalid_raises_400(self, db_session, auth_user):
        """全部无效 id → AppError（400）。"""
        await self._seed_spots(db_session, auth_user, ["西湖"])
        data = FavoriteRouteIn(
            spot_ids=["no-such-id"], title="t", destination="d",
            start_date=date(2026, 11, 1), days=1,
        )
        with pytest.raises(AppError) as exc:
            await create_route_from_spots(db_session, _uid(auth_user), data)
        assert exc.value.status_code == 400
        assert exc.value.code == "no_valid_spots"

    async def test_other_user_spots_invisible(self, db_session, auth_user, client):
        """A 的收藏对 B 不可见：B 的 spot_ids 引用 A 的 id → skipped。"""
        # A 收藏
        spot_ids = await self._seed_spots(db_session, auth_user, ["A的景点"])
        a_id = spot_ids["A的景点"]

        # B（注册 API）用 A 的 id 生成 → 无效 → 400（防枚举）
        import uuid
        email = f"other-{uuid.uuid4().hex[:8]}@test.com"
        resp = await client.post("/api/v1/auth/register", json={
            "email": email, "password": "test1234", "display_name": "路人",
        })
        assert resp.status_code == 201
        b_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        data = FavoriteRouteIn(
            spot_ids=[a_id], title="t", destination="d",
            start_date=date(2026, 11, 1), days=1,
        )
        # 服务层直接调用 B（不同 user id）
        b_user = SimpleNamespace(id=resp.json()["user"]["id"])
        with pytest.raises(AppError):
            await create_route_from_spots(db_session, b_user, data)

    async def test_original_favorites_untouched(self, db_session, auth_user):
        """生成后收集箱原地点保留（未删除）。"""
        spot_ids = await self._seed_spots(db_session, auth_user, ["西湖"])
        data = FavoriteRouteIn(
            spot_ids=[spot_ids["西湖"]], title="t", destination="d",
            start_date=date(2026, 11, 1), days=1,
        )
        await create_route_from_spots(db_session, _uid(auth_user), data)
        rows = list(
            (await db_session.execute(select(FavoriteSpot).where(FavoriteSpot.user_id == _uid(auth_user).id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].name == "西湖"


# ── 3. API 层 ─────────────────────────────────────────────────
class TestFavoriteSpotsRouteApi:
    async def test_requires_auth(self, client):
        resp = await client.post("/api/v1/trips/favorite-spots/route", json={})
        assert resp.status_code == 401

    async def test_create_route_api(self, client, auth_user):
        """API 全流程：收藏 → 成路线 → 201 + TripOut + 报告。"""
        _, headers = auth_user
        # 收藏 3 个地点
        resp = await client.post(
            "/api/v1/trips/favorite-spots/batch",
            json={"spots": [
                {"name": "西湖", "stop_type": "attraction", "lat": 30.2, "lng": 120.1},
                {"name": "灵隐寺", "stop_type": "attraction", "lat": 30.25, "lng": 120.05},
                {"name": "楼外楼", "stop_type": "food", "lat": 30.24, "lng": 120.14},
            ]},
            headers=headers,
        )
        assert resp.status_code == 200
        listed = await client.get("/api/v1/trips/favorite-spots", headers=headers)
        ids = [s["id"] for s in listed.json()["items"]]

        resp = await client.post(
            "/api/v1/trips/favorite-spots/route",
            json={
                "spot_ids": ids,
                "title": "杭州两天",
                "destination": "杭州",
                "start_date": "2026-11-01",
                "days": 2,
                "travelers": 2,
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["trip"]["title"] == "杭州两天"
        assert body["trip"]["status"] == "draft"
        assert body["report"] == {"placed": 3, "overflow": 0, "hotel_overflow": 0, "skipped": 0}
        total_stops = sum(len(d["stops"]) for d in body["trip"]["days"])
        assert total_stops == 3

    async def test_all_invalid_400_api(self, client, auth_user):
        """全部无效 id → 400。"""
        _, headers = auth_user
        resp = await client.post(
            "/api/v1/trips/favorite-spots/route",
            json={"spot_ids": ["no-such"], "title": "t", "destination": "d",
                  "start_date": "2026-11-01", "days": 1},
            headers=headers,
        )
        assert resp.status_code == 400

    async def test_validation_422(self, client, auth_user):
        """空 spot_ids / days=0 → 422。"""
        _, headers = auth_user
        resp = await client.post(
            "/api/v1/trips/favorite-spots/route",
            json={"spot_ids": [], "title": "t", "destination": "d",
                  "start_date": "2026-11-01", "days": 1},
            headers=headers,
        )
        assert resp.status_code == 422

        resp = await client.post(
            "/api/v1/trips/favorite-spots/route",
            json={"spot_ids": ["x"], "title": "t", "destination": "d",
                  "start_date": "2026-11-01", "days": 0},
            headers=headers,
        )
        assert resp.status_code == 422
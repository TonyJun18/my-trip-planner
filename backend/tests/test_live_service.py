"""task-live-today-view：行中「今日视图」测试。

覆盖：
1. trip_phase 三态（upcoming / live / finished）
2. today_day 定位（按 date 精确匹配 / 无 date 按 day_number 推算）
3. live_snapshot 快照（stops 排序 + completed/total）
4. check_stop 打卡/取消 + 非 live 拒绝（trip_not_live）+ 站点不存在
5. skip_stop 跳过（删除 + 余站重排）
6. delay_today 迟到一键顺延（所有 day.date +1、end_date +1、事件发布）
7. API 端到端（GET /live、POST check / skip / delay、非 live 400）

时区稳定性：service 层测试显式传 today；API 端到端 monkeypatch
live_service.datetime（固定 UTC 日期），任何时刻跑都不 flaky。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models import Stop, Trip, TripDay


# ── helpers ─────────────────────────────────────────────────────
def _make_trip(today: date, *, owner: str = "u-live", num_days: int = 1) -> Trip:
    """直接 ORM 构造（不触发懒加载：用 relationship append）。"""
    trip = Trip(
        owner=owner,
        title="行中测试",
        destination="杭州",
        start_date=today,
        end_date=today + timedelta(days=num_days - 1),
    )
    for i in range(num_days):
        day = TripDay(day_number=i + 1, date=today + timedelta(days=i))
        trip.days.append(day)
        for j in range(1, 3):
            day.stops.append(Stop(
                name=f"站点{i + 1}{'A' if j == 1 else 'B'}",
                stop_type="attraction",
                order_index=j,
                checked=False,  # 显式初始化（DB 默认 false，但 ORM 未 flush 前是 None）
                estimated_duration_minutes=120,
            ))
    return trip


async def _add(db_session, trip: Trip) -> None:
    db_session.add(trip)
    # flush 让 id 生成，同时填充 relationship 集合（不触发 async 懒加载）
    await db_session.flush()


# ── 1. trip_phase 三态 ──────────────────────────────────────────
class TestTripPhase:
    def test_upcoming_before_start(self):
        from app.services.live_service import trip_phase

        trip = _make_trip(date(2026, 10, 20))
        assert trip_phase(trip, today=date(2026, 10, 14)) == "upcoming"

    def test_live_within_range(self):
        from app.services.live_service import trip_phase

        trip = _make_trip(date(2026, 10, 14), num_days=3)
        assert trip_phase(trip, today=date(2026, 10, 15)) == "live"

    def test_finished_after_end(self):
        from app.services.live_service import trip_phase

        trip = _make_trip(date(2026, 10, 10), num_days=2)
        assert trip_phase(trip, today=date(2026, 10, 13)) == "finished"


# ── 2. today_day 定位 ───────────────────────────────────────────
class TestTodayDay:
    def test_matches_by_date(self):
        from app.services.live_service import today_day

        trip = _make_trip(date(2026, 10, 14), num_days=3)
        day = today_day(trip, today=date(2026, 10, 15))
        assert day is not None
        assert day.day_number == 2

    def test_none_when_not_live(self):
        from app.services.live_service import today_day

        trip = _make_trip(date(2026, 10, 20))
        assert today_day(trip, today=date(2026, 10, 14)) is None

    def test_fallback_by_day_number_when_no_date(self):
        from app.services.live_service import today_day

        trip = _make_trip(date(2026, 10, 14), num_days=2)
        for day in trip.days:
            day.date = None  # 无日期日：按 day_number 推算
        day = today_day(trip, today=date(2026, 10, 15))
        assert day is not None
        assert day.day_number == 2


# ── 3. live_snapshot ────────────────────────────────────────────
class TestLiveSnapshot:
    def test_snapshot_structure_and_counts(self):
        from app.services.live_service import live_snapshot

        trip = _make_trip(date(2026, 10, 14))
        snap = live_snapshot(trip, today=date(2026, 10, 14))
        assert snap["phase"] == "live"
        assert snap["day_number"] == 1
        assert snap["total"] == 2
        assert snap["completed"] == 0
        assert [s["name"] for s in snap["stops"]] == ["站点1A", "站点1B"]
        assert snap["stops"][0]["checked"] is False

    def test_upcoming_snapshot_no_stops(self):
        from app.services.live_service import live_snapshot

        trip = _make_trip(date(2026, 10, 20))
        snap = live_snapshot(trip, today=date(2026, 10, 14))
        assert snap["phase"] == "upcoming"
        assert snap["day_number"] is None
        assert snap["stops"] == []


# ── 4. check_stop ───────────────────────────────────────────────
class TestCheckStop:
    async def test_check_and_uncheck(self, db_session):
        from app.services.live_service import check_stop

        trip = _make_trip(date(2026, 10, 14))
        await _add(db_session, trip)
        stop_id = trip.days[0].stops[0].id

        result = await check_stop(
            db_session, trip.id, stop_id, checked=True,
            owner="u-live", today=date(2026, 10, 14),
        )
        assert result["stop"]["checked"] is True
        assert result["live"]["completed"] == 1

        result = await check_stop(
            db_session, trip.id, stop_id, checked=False,
            owner="u-live", today=date(2026, 10, 14),
        )
        assert result["stop"]["checked"] is False
        assert result["live"]["completed"] == 0

    async def test_reject_when_not_live(self, db_session):
        from app.core.exceptions import AppError
        from app.services.live_service import check_stop

        trip = _make_trip(date(2026, 10, 20))  # upcoming
        await _add(db_session, trip)
        stop_id = trip.days[0].stops[0].id

        try:
            await check_stop(
                db_session, trip.id, stop_id, checked=True,
                owner="u-live", today=date(2026, 10, 14),
            )
            assert False, "应拒绝非行中行程的打卡"
        except AppError as exc:
            assert exc.code == "trip_not_live"

    async def test_reject_unknown_stop(self, db_session):
        from app.core.exceptions import AppError
        from app.services.live_service import check_stop

        trip = _make_trip(date(2026, 10, 14))
        await _add(db_session, trip)

        try:
            await check_stop(
                db_session, trip.id, "no-such-stop", checked=True,
                owner="u-live", today=date(2026, 10, 14),
            )
            assert False, "应拒绝不存在的站点"
        except AppError as exc:
            assert exc.code == "stop_not_found"


# ── 5. skip_stop ────────────────────────────────────────────────
class TestSkipStop:
    async def test_skip_removes_and_renumbers(self, db_session):
        from app.services.live_service import skip_stop

        trip = _make_trip(date(2026, 10, 14))
        await _add(db_session, trip)
        day = trip.days[0]
        stop_a, stop_b = day.stops

        result = await skip_stop(
            db_session, trip.id, stop_b.id,
            owner="u-live", today=date(2026, 10, 14),
        )
        names = [s["name"] for s in result["live"]["stops"]]
        assert names == ["站点1A"]  # 只跳 B，A 保留
        assert result["live"]["total"] == 1
        # 余站重排：A 的 order_index 应为 1
        remaining = result["live"]["stops"][0]
        assert remaining["order_index"] == 1

    async def test_skip_reject_when_not_live(self, db_session):
        from app.core.exceptions import AppError
        from app.services.live_service import skip_stop

        trip = _make_trip(date(2026, 10, 20))
        await _add(db_session, trip)
        stop_id = trip.days[0].stops[0].id

        try:
            await skip_stop(
                db_session, trip.id, stop_id,
                owner="u-live", today=date(2026, 10, 14),
            )
            assert False, "应拒绝非行中行程的跳过"
        except AppError as exc:
            assert exc.code == "trip_not_live"


# ── 6. delay_today 顺延 ─────────────────────────────────────────
class TestDelayToday:
    async def test_shifts_dates_and_end_date(self, db_session):
        from app.services.live_service import delay_today

        trip = _make_trip(date(2026, 10, 14), num_days=3)
        await _add(db_session, trip)

        result = await delay_today(
            db_session, trip.id, owner="u-live", today=date(2026, 10, 14),
        )
        assert result["live"]["phase"] == "live"
        # 所有日 +1、end_date +1（行程不缩水）
        assert trip.days[0].date == date(2026, 10, 15)
        assert trip.days[1].date == date(2026, 10, 16)
        assert trip.days[2].date == date(2026, 10, 17)
        assert trip.end_date == date(2026, 10, 17)

    async def test_reject_when_not_live(self, db_session):
        from app.core.exceptions import AppError
        from app.services.live_service import delay_today

        trip = _make_trip(date(2026, 10, 20))
        await _add(db_session, trip)

        try:
            await delay_today(
                db_session, trip.id, owner="u-live", today=date(2026, 10, 14),
            )
            assert False, "应拒绝非行中行程的顺延"
        except AppError as exc:
            assert exc.code == "trip_not_live"


# ── 7. API 端到端 ───────────────────────────────────────────────
# 固定「今天」：monkeypatch live_service.datetime，避免时区/时间 flaky。
class _FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 4, 0, 0, tzinfo=timezone.utc)


async def _make_live_trip_api(client, headers, *, start: date, end: date):
    """通过 API 建行程 + Day + 2 站点，返回 (trip_id, stops)。"""
    resp = await client.post("/api/v1/trips", json={
        "title": "行中测试", "destination": "杭州",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "travelers": 1, "budget": 1000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days",
                             json={"day_number": 1, "date": start.isoformat()}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    stop_ids = []
    for name in ("西湖", "灵隐寺"):
        r = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": "attraction",
            "estimated_cost": 50, "estimated_duration_minutes": 120,
        }, headers=headers)
        assert r.status_code == 201, r.text
        stop_ids.append(r.json()["id"])
    return trip_id, stop_ids


class TestLiveAPI:
    async def test_get_live_upcoming(self, client, auth_user, db_session, monkeypatch):
        """未开始行程：GET /live 返回 phase=upcoming，不报错。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        trip_id, _ = await _make_live_trip_api(
            client, headers, start=date(2026, 10, 20), end=date(2026, 10, 22))

        resp = await client.get(f"/api/v1/trips/{trip_id}/live", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["phase"] == "upcoming"
        assert resp.json()["stops"] == []

    async def test_check_skip_delay_flow(self, client, auth_user, db_session, monkeypatch):
        """行中行程：打卡 → 跳过 → 顺延 全流程。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        trip_id, (stop_a, stop_b) = await _make_live_trip_api(
            client, headers, start=date(2026, 10, 14), end=date(2026, 10, 14))

        # GET live
        resp = await client.get(f"/api/v1/trips/{trip_id}/live", headers=headers)
        assert resp.status_code == 200, resp.text
        snap = resp.json()
        assert snap["phase"] == "live"
        assert snap["total"] == 2

        # 打卡 A
        resp = await client.post(
            f"/api/v1/trips/{trip_id}/live/stops/{stop_a}/check",
            json={"checked": True}, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["completed"] == 1

        # 跳过 B
        resp = await client.post(
            f"/api/v1/trips/{trip_id}/live/stops/{stop_b}/skip", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 1
        assert [s["name"] for s in resp.json()["stops"]] == ["西湖"]

        # 迟到顺延
        resp = await client.post(f"/api/v1/trips/{trip_id}/live/delay", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["phase"] == "live"

    async def test_operation_rejected_when_upcoming(self, client, auth_user, db_session, monkeypatch):
        """未开始行程：POST check 返回 400 trip_not_live。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        trip_id, (stop_a, _) = await _make_live_trip_api(
            client, headers, start=date(2026, 10, 20), end=date(2026, 10, 22))

        resp = await client.post(
            f"/api/v1/trips/{trip_id}/live/stops/{stop_a}/check",
            json={"checked": True}, headers=headers)
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"]["code"] == "trip_not_live"